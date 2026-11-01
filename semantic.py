import ast
import re


class SemanticError(Exception):
    pass


NUMERIC = {"int", "float", "double", "char", "bool"}
COMPATIBLE = {
    "int":    {"int", "char", "bool", "float", "double"},
    "float":  {"float", "int", "double"},
    "double": {"double", "float", "int"},
    "char":   {"char", "int"},
    "bool":   {"bool", "int"},
    "void":   set(),
}


class Symbol:
    def __init__(self, name, type_, kind="var", params=None, return_type=None, scope="global",
                 container=None, dimensions=None):
        self.name = name
        self.type = type_
        self.kind = kind
        self.params = params or []
        self.return_type = return_type
        self.scope = scope
        self.container = container
        self.dimensions = list(dimensions) if dimensions is not None else []


class SymbolTable:
    def __init__(self):
        self.scopes = [{}]
        self.scope_names = ["global"]

    def push(self, name):
        self.scopes.append({})
        self.scope_names.append(name)

    def pop(self):
        self.scopes.pop()
        self.scope_names.pop()

    def declare(self, sym):
        if sym.name in self.scopes[-1]:
            raise SemanticError(f"Повторное объявление '{sym.name}' в области '{self.scope_names[-1]}'")
        self.scopes[-1][sym.name] = sym

    def lookup(self, name):
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        return None

    def current_scope(self):
        return self.scope_names[-1]


class SemanticAnalyzer:
    def __init__(self):
        self.table = SymbolTable()
        self.errors = []
        self.current_function = None
        for name in ("cout", "cin", "endl", "std"):
            self.table.scopes[0][name] = Symbol(name, "unknown", kind="var")

    def analyze(self, tree):
        try:
            self.visit(tree)
        except SemanticError as e:
            self.errors.append(str(e))
        return self.errors

    def visit(self, node):
        if node is None:
            return None
        method = getattr(self, f"visit_{node.type}", self.visit_generic)
        return method(node)

    def visit_generic(self, node):
        for child in node.children:
            self.visit(child)

    def visit_Program(self, node):
        for child in node.children:
            self.visit(child)

    def visit_Preprocessor(self, node):
        pass

    def visit_Block(self, node):
        self.table.push(f"block_{id(node)}")
        try:
            for child in node.children:
                self.visit(child)
        finally:
            self.table.pop()

    def visit_Function(self, node):
        return_type = None
        func_name = None
        params = []

        for child in node.children:
            if child.type == "ReturnType":
                return_type = child.value.split()[-1]
            elif child.type == "FuncName":
                func_name = child.value
            elif child.type == "Parameters":
                for p in child.children:
                    params.append((p.param_type or "unknown", p.value))

        if func_name is None:
            raise SemanticError("Функция без имени")

        self.table.declare(Symbol(func_name, return_type, kind="func",
                                  params=params, return_type=return_type))
        self.current_function = func_name

        self.table.push(f"func_{func_name}")
        try:
            for ptype, pname in params:
                self.table.declare(Symbol(pname, ptype, kind="param"))
            for child in node.children:
                if child.type == "Block":
                    self.visit(child)
        finally:
            self.table.pop()

    def visit_Declaration(self, node):
        var_type = node.value
        for child in node.children:
            if child.type not in ("VarName", "ArrayName", "VectorName"):
                continue
            element_type = var_type
            container = None
            dimensions = []
            if child.type == "ArrayName":
                container = "array"
                dimensions = [dim.value for dim in child.children if dim.type == "Dimension"]
                self.check_array_dimensions(child, dimensions)
            elif child.type == "VectorName":
                container = "vector"
                element_type = var_type[len("vector<"):-1]
            symbol = Symbol(child.value, element_type, scope=self.table.current_scope(),
                            container=container, dimensions=dimensions)
            self.table.declare(symbol)
            # Локальная область будет удалена из таблицы, но символ останется в дереве.
            child.symbol = symbol
            if child.type == "VarName":
                for sub in child.children:
                    if sub.type == "Value":
                        expr_type = self.eval_expr(sub.value)
                        self.check_assign(var_type, expr_type, child.value)

    def check_array_dimensions(self, node, dimensions):
        if len(dimensions) not in (1, 2):
            raise SemanticError(f"Массив '{node.value}' должен иметь одно или два измерения")
        has_initializer = any(child.type in ("InitializerList", "Value") for child in node.children)
        for index, expression in enumerate(dimensions):
            if expression is None:
                if index != 0 or not has_initializer:
                    raise SemanticError(f"У массива '{node.value}' можно пропустить только первый размер при наличии инициализации")
                continue
            # Python AST используется только для арифметики; имена C++ вроде
            # True или lambda временно получают префикс, строки не изменяются.
            # Целые литералы с ведущим нулём читаются по правилам C++ (основание 8).
            try:
                source = re.sub(r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\b0[0-9]+\b(?!\.)|\b[A-Za-z_]\w*\b''',
                                lambda match: (match[0] if match[0][0] in "\"'" else
                                               str(int(match[0], 8)) if match[0][0].isdigit() else
                                               "_size_" + match[0]), expression)
                parsed = ast.parse(source, mode="eval").body
            except (SyntaxError, ValueError) as error:
                raise SemanticError(f"Неподдерживаемое выражение размера массива '{node.value}': {expression}") from error
            type_, value = self._array_size_expression(parsed, source)
            if type_ != "int":
                raise SemanticError(f"Размер массива '{node.value}' должен иметь тип int, получен {type_}")
            if value is not None and value <= 0:
                raise SemanticError(f"Размер массива '{node.value}' должен быть положительным, получен {value}")

    def _array_size_expression(self, node, source):
        """Возвращает тип и известное целое значение; None означает размер времени выполнения."""
        if isinstance(node, ast.Constant):
            if type(node.value) is int:
                return "int", node.value
            if type(node.value) is float:
                return "float", None
            if isinstance(node.value, str):
                literal = ast.get_source_segment(source, node) or ""
                if literal.startswith("'") and len(node.value) == 1:
                    return "char", ord(node.value)
                return "string", None
        elif isinstance(node, ast.Name):
            name = node.id[len("_size_"):]
            if name in ("true", "false"):
                return "bool", int(name == "true")
            symbol = self.table.lookup(name)
            if symbol is None:
                raise SemanticError(f"Необъявленное имя в размере массива: '{name}'")
            if symbol.container or symbol.kind == "func":
                raise SemanticError(f"В размере массива нужен элемент контейнера или вызов функции, а не '{name}' целиком")
            return symbol.type, None
        elif isinstance(node, ast.Subscript):
            base, indices = node, []
            while isinstance(base, ast.Subscript):
                indices.append(base.slice)
                base = base.value
            symbol = self.table.lookup(base.id[len("_size_"):]) if isinstance(base, ast.Name) else None
            if symbol is None or not symbol.container:
                raise SemanticError("В размере массива индексируется необъявленный контейнер или обычная переменная")
            rank = len(symbol.dimensions) if symbol.container == "array" else 1
            if len(indices) != rank:
                raise SemanticError("В размере массива нужно указать отдельный элемент контейнера")
            for index in indices:
                self._array_size_expression(index, source)
            return symbol.type, None
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id[len("_size_"):]
            symbol = self.table.lookup(name)
            if symbol is None or symbol.kind != "func":
                raise SemanticError(f"Необъявленная функция в размере массива: '{name}'")
            if node.keywords or len(node.args) != len(symbol.params):
                raise SemanticError(f"Неверное число аргументов функции '{name}' в размере массива")
            for argument in node.args:
                self._array_size_expression(argument, source)
            return symbol.return_type, None
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            type_, value = self._array_size_expression(node.operand, source)
            if type_ not in NUMERIC:
                raise SemanticError("Унарная операция в размере массива требует числовой операнд")
            return ("int" if type_ in ("char", "bool") else type_,
                    -value if value is not None and isinstance(node.op, ast.USub) else value)
        elif isinstance(node, ast.BinOp):
            left_type, left = self._array_size_expression(node.left, source)
            right_type, right = self._array_size_expression(node.right, source)
            if left_type not in NUMERIC or right_type not in NUMERIC:
                raise SemanticError("Арифметика в размере массива требует числовые операнды")
            integer = ("int", "char", "bool")
            if isinstance(node.op, (ast.Mod, ast.LShift, ast.RShift)) and (left_type not in integer or right_type not in integer):
                raise SemanticError("Остаток и сдвиги в размере массива требуют целочисленные операнды")
            result_type = "double" if "double" in (left_type, right_type) else "float" if "float" in (left_type, right_type) else "int"
            value = self._array_size_operation(node.op, left, right)
            return result_type, value
        elif isinstance(node, ast.Compare):
            for operand in (node.left, *node.comparators):
                self._array_size_expression(operand, source)
            return "bool", None
        raise SemanticError("Неподдерживаемая операция в выражении размера массива")

    @staticmethod
    def _array_size_operation(operation, left, right):
        if isinstance(operation, (ast.Div, ast.Mod)) and right == 0:
            raise SemanticError("Деление на ноль в выражении размера массива")
        if isinstance(operation, (ast.LShift, ast.RShift)) and right is not None and right < 0:
            raise SemanticError("Отрицательный сдвиг в выражении размера массива")
        if left is None or right is None:
            return None
        if isinstance(operation, ast.Add):
            return left + right
        if isinstance(operation, ast.Sub):
            return left - right
        if isinstance(operation, ast.Mult):
            return left * right
        if isinstance(operation, (ast.Div, ast.Mod)):
            quotient = abs(left) // abs(right) * (-1 if (left < 0) != (right < 0) else 1)
            return quotient if isinstance(operation, ast.Div) else left - quotient * right
        if isinstance(operation, ast.LShift):
            return left << right
        if isinstance(operation, ast.RShift):
            return left >> right
        raise SemanticError("Неподдерживаемая арифметическая операция в размере массива")

    # ---------- for: инициализация ----------
    def visit_Init(self, node):
        if not node.value:
            return
        text = node.value.strip()
        m = re.match(
            r"^(int|float|double|char|bool|void|auto)\s+([A-Za-z_]\w*)\s*=\s*(.+)$",
            text,
        )
        if m:
            var_type, var_name, rhs = m.group(1), m.group(2), m.group(3)
            self.table.declare(Symbol(var_name, var_type))
            rhs_type = self.eval_expr(rhs)
            self.check_assign(var_type, rhs_type, var_name)
        else:
            # простое присваивание: i = 0
            self.eval_expr(text)

    # ---------- if / while ----------
    def visit_If(self, node):
        for child in node.children:
            if child.type == "Condition":
                self.check_condition(child.value)
            else:
                self.visit(child)

    visit_While = visit_If

    def visit_Then(self, node):
        for child in node.children:
            self.visit(child)

    visit_Else = visit_Then

    def visit_For(self, node):
        self.table.push(f"for_{id(node)}")
        try:
            for child in node.children:
                if child.type == "Condition":
                    self.check_condition(child.value)
                else:
                    self.visit(child)
        finally:
            self.table.pop()

    def visit_DoWhile(self, node):
        for child in node.children:
            if child.type == "Condition":
                self.check_condition(child.value)
            else:
                self.visit(child)

    def visit_Return(self, node):
        func = self.table.lookup(self.current_function or "")
        expected = func.return_type if func else None
        for child in node.children:
            if child.type == "Value":
                actual = self.eval_expr(child.value)
                if expected == "void":
                    raise SemanticError("Возврат значения из void-функции")
                if not self.is_compatible(expected, actual):
                    raise SemanticError(
                        f"Несовместимый тип возврата: ожидается {expected}, получен {actual}")
            else:
                if expected and expected != "void":
                    raise SemanticError(f"Функция {func.name} должна возвращать {expected}")

    def visit_ExprStmt(self, node):
        if node.value and node.value != "empty":
            self.eval_expr(node.value)

    def visit_Empty(self, node):
        pass

    def visit_Break(self, node):
        pass

    def visit_Continue(self, node):
        pass

    # ---------- проверки ----------
    def check_condition(self, expr):
        t = self.eval_expr(expr)
        if t not in ("bool", "int", "unknown"):
            raise SemanticError(f"Условие должно быть логическим, получено {t}")

    def check_assign(self, var_type, expr_type, var_name):
        if not self.is_compatible(var_type, expr_type):
            raise SemanticError(
                f"Несовместимое присваивание '{var_name}': {var_type} = {expr_type}")

    @staticmethod
    def is_compatible(dst, src):
        if dst == "unknown" or src == "unknown":
            return True
        return src in COMPATIBLE.get(dst, set())

    # ---------- вычисление типа выражения ----------
    def eval_expr(self, expr_text):
        if not expr_text:
            return "unknown"
        text = expr_text.strip()

        # cout / cin — не проверяем как обычное выражение
        if text.lstrip().startswith(("cout", "cin")):
            return "unknown"

        # присваивание
        assign = self._find_assign(text)
        if assign != -1:
            left = text[:assign].strip()
            right = text[assign + 1:].strip()
            sym = self.table.lookup(left)
            if sym is None:
                raise SemanticError(f"Присваивание необъявленной переменной '{left}'")
            rhs_type = self.eval_expr(right)
            self.check_assign(sym.type, rhs_type, left)
            return sym.type

        # литералы
        if text.startswith('"') and text.endswith('"'):
            return "string"
        if text.startswith("'") and text.endswith("'"):
            return "char"
        if text in ("true", "false"):
            return "bool"
        try:
            if text.startswith(("0x", "0X")):
                int(text, 16)
                return "int"
            if "." in text:
                float(text)
                return "float"
            int(text)
            return "int"
        except ValueError:
            pass

        # вызов функции
        m = re.match(r"^([A-Za-z_]\w*)\s*\((.*)\)$", text)
        if m:
            fname, args = m.group(1), m.group(2)
            sym = self.table.lookup(fname)
            if sym is None:
                # cout/endl могут попасть сюда
                if fname in ("cout", "cin", "endl", "printf"):
                    return "unknown"
                raise SemanticError(f"Вызов необъявленной функции '{fname}'")
            if sym.kind != "func":
                return sym.type  # cout как идентификатор
            args_list = [a.strip() for a in self.split_args(args)]
            if len(args_list) != len(sym.params):
                raise SemanticError(
                    f"Функция '{fname}' ожидает {len(sym.params)} аргументов, передано {len(args_list)}")
            return sym.return_type or "unknown"

        # идентификатор
        if re.match(r"^[A-Za-z_]\w*$", text):
            sym = self.table.lookup(text)
            if sym is None:
                raise SemanticError(f"Использование необъявленного идентификатора '{text}'")
            return sym.type

        # сравнения / логика -> bool
        if any(op in text for op in ("==", "!=", "<=", ">=", "&&", "||", "<", ">")):
            for token in re.findall(r"[A-Za-z_]\w*", text):
                if self.table.lookup(token) is None and token not in ("cout", "cin", "endl"):
                    raise SemanticError(f"Использование необъявленного идентификатора '{token}'")
            return "bool"

        # арифметика
        for token in re.findall(r"[A-Za-z_]\w*", text):
            sym = self.table.lookup(token)
            if sym and sym.type in NUMERIC:
                return sym.type
        for token in re.findall(r"\d+\.\d+", text):
            return "float"
        if re.search(r"\d+", text):
            return "int"
        return "unknown"

    @staticmethod
    def _find_assign(text):
        depth = 0
        for i, ch in enumerate(text):
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            elif ch == "=" and depth == 0:
                prev = text[i - 1] if i > 0 else ""
                nxt = text[i + 1] if i + 1 < len(text) else ""
                if prev in "=!<>" or nxt == "=":
                    continue
                return i
        return -1

    @staticmethod
    def split_args(s):
        args, depth, cur = [], 0, ""
        for ch in s:
            if ch == "," and depth == 0:
                args.append(cur)
                cur = ""
            else:
                if ch in "([{":
                    depth += 1
                if ch in ")]}":
                    depth -= 1
                cur += ch
        if cur.strip():
            args.append(cur)
        return args or []
