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
                 container=None, dimensions=None, known_dimensions=None, is_const=False):
        self.name = name
        self.type = type_
        self.kind = kind
        self.params = params or []
        self.return_type = return_type
        self.scope = scope
        self.container = container
        self.dimensions = list(dimensions) if dimensions is not None else []
        self.known_dimensions = list(known_dimensions) if known_dimensions is not None else []
        self.is_const = is_const


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
        is_const = any(child.type == "Qualifier" and child.value == "const" for child in node.children)
        for child in node.children:
            if child.type not in ("VarName", "ArrayName", "VectorName"):
                continue
            if is_const and not any(sub.type in ("Value", "InitializerList") for sub in child.children):
                raise SemanticError(f"Константа '{child.value}' должна иметь инициализацию")
            element_type = var_type
            container = None
            dimensions = []
            known_dimensions = []
            if child.type == "ArrayName":
                container = "array"
                dimensions = [dim.value for dim in child.children if dim.type == "Dimension"]
                known_dimensions = self.check_array_dimensions(child, dimensions)
            elif child.type == "VectorName":
                container = "vector"
                element_type = var_type[len("vector<"):-1]
            symbol = Symbol(child.value, element_type, scope=self.table.current_scope(),
                            container=container, dimensions=dimensions, known_dimensions=known_dimensions,
                            is_const=is_const)
            self.table.declare(symbol)
            # Локальная область будет удалена из таблицы, но символ останется в дереве.
            child.symbol = symbol
            if child.type == "VarName":
                for sub in child.children:
                    if sub.type == "Value":
                        expr_type = self.eval_expr(sub.value)
                        self.check_assign(var_type, expr_type, child.value)
            else:
                self.check_container_initializer(child, symbol, known_dimensions)

    def check_container_initializer(self, node, symbol, dimensions):
        initializer = next((child for child in node.children if child.type in ("InitializerList", "Value", "ConstructorArgs")), None)
        if initializer is None:
            return
        if initializer.type == "ConstructorArgs":
            if len(initializer.children) not in (1, 2):
                raise SemanticError(f"Конструктор вектора '{symbol.name}' ожидает один или два аргумента")
            for index, argument in enumerate(initializer.children):
                self._check_const_writes(argument.value)
                try:
                    parsed, source = self._parse_container_expression(argument.value)
                    type_, value = self._container_expression_info(parsed, source)
                except (SyntaxError, ValueError) as error:
                    raise SemanticError(f"Неподдерживаемый аргумент конструктора вектора '{symbol.name}': {argument.value}") from error
                if index == 0:
                    if type_ != "int":
                        raise SemanticError(f"Размер вектора '{symbol.name}' должен иметь тип int, получен {type_}")
                    if value is not None and value < 0:
                        raise SemanticError(f"Размер вектора '{symbol.name}' не может быть отрицательным, получен {value}")
                else:
                    self.check_assign(symbol.type, type_, symbol.name)
            return
        if initializer.type == "Value":
            if symbol.container != "array" or symbol.type != "char" or len(dimensions) != 1:
                raise SemanticError(f"Строкой можно инициализировать только одномерный char-массив: '{symbol.name}'")
            content = initializer.value[1:-1]
            # Одна escape-последовательность C++ занимает один элемент массива.
            characters = re.findall(r'''\\(?:[0-7]{1,3}|x[0-9a-fA-F]+|u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8}|['"?\\abfnrtv])|[^\\\r\n]''', content)
            if "".join(characters) != content:
                raise SemanticError(f"Некорректная или неподдерживаемая escape-последовательность в '{symbol.name}'")
            count = len(characters) + 1  # Включая завершающий нулевой символ.
        else:
            count = len(initializer.children)

        if symbol.container == "array" and symbol.dimensions[0] is None:
            if count == 0:
                raise SemanticError(f"Нельзя определить положительный размер массива '{symbol.name}' из пустого списка")
            symbol.dimensions[0] = str(count)
            dimensions[0] = count
            symbol.known_dimensions[0] = count

        if initializer.type == "Value":
            if dimensions[0] is not None and count > dimensions[0]:
                raise SemanticError(f"Строка не помещается в массив '{symbol.name}': требуется {count}, размер {dimensions[0]}")
        else:
            # У вектора нет фиксированной вместимости списка начальных значений.
            self._check_initializer_list(initializer, symbol.type,
                                         dimensions if symbol.container == "array" else [None], symbol.name)

    def _check_initializer_list(self, node, element_type, dimensions, name):
        if dimensions[0] is not None and len(node.children) > dimensions[0]:
            raise SemanticError(f"Слишком много начальных значений для '{name}': размер {dimensions[0]}, значений {len(node.children)}")
        for child in node.children:
            if len(dimensions) > 1:
                if child.type != "InitializerList":
                    raise SemanticError(f"Для двумерного массива '{name}' нужны вложенные списки инициализации")
                self._check_initializer_list(child, element_type, dimensions[1:], name)
            else:
                if child.type != "Value":
                    raise SemanticError(f"Лишняя вложенность списка инициализации '{name}'")
                self._check_const_writes(child.value)
                try:
                    parsed, source = self._parse_container_expression(child.value)
                    actual_type, _ = self._container_expression_info(parsed, source)
                except (SyntaxError, ValueError) as error:
                    raise SemanticError(f"Неподдерживаемое начальное выражение для '{name}': {child.value}") from error
                self.check_assign(element_type, actual_type, name)

    def check_array_dimensions(self, node, dimensions):
        if len(dimensions) not in (1, 2):
            raise SemanticError(f"Массив '{node.value}' должен иметь одно или два измерения")
        has_initializer = any(child.type in ("InitializerList", "Value") for child in node.children)
        known_dimensions = []
        for index, expression in enumerate(dimensions):
            if expression is None:
                if index != 0 or not has_initializer:
                    raise SemanticError(f"У массива '{node.value}' можно пропустить только первый размер при наличии инициализации")
                known_dimensions.append(None)
                continue
            self._check_const_writes(expression)
            try:
                parsed, source = self._parse_container_expression(expression)
            except (SyntaxError, ValueError) as error:
                raise SemanticError(f"Неподдерживаемое выражение размера массива '{node.value}': {expression}") from error
            type_, value = self._container_expression_info(parsed, source)
            if type_ != "int":
                raise SemanticError(f"Размер массива '{node.value}' должен иметь тип int, получен {type_}")
            if value is not None and value <= 0:
                raise SemanticError(f"Размер массива '{node.value}' должен быть положительным, получен {value}")
            known_dimensions.append(value)
        return known_dimensions

    @staticmethod
    def _parse_container_expression(expression):
        # Не смешиваем имена C++ (например, True и lambda) с ключевыми словами Python.
        # Литералы с ведущим нулём переводим из восьмеричной записи C++.
        source = re.sub(r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\b0[0-9]+\b(?!\.)|\b[A-Za-z_]\w*\b''',
                        lambda match: ("'?'" if match[0] == r"'\?'" else
                                       match[0] if match[0][0] in "\"'" else
                                       str(int(match[0], 8)) if match[0][0].isdigit() else
                                       "_size_" + match[0]), expression)
        return ast.parse(source, mode="eval").body, source

    def _container_expression_info(self, node, source):
        """Тип выражения и известное целое значение для размеров, инициализации и индексов."""
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
                raise SemanticError(f"Необъявленное имя в выражении: '{name}'")
            if symbol.container or symbol.kind == "func":
                raise SemanticError(f"В выражении нужен элемент контейнера или вызов функции, а не '{name}' целиком")
            return symbol.type, None
        elif isinstance(node, ast.Subscript):
            base, indices = node, []
            while isinstance(base, ast.Subscript):
                indices.append(base.slice)
                base = base.value
            symbol = self.table.lookup(base.id[len("_size_"):]) if isinstance(base, ast.Name) else None
            if symbol is None or not symbol.container:
                raise SemanticError("В выражении индексируется необъявленный контейнер или обычная переменная")
            rank = len(symbol.dimensions) if symbol.container == "array" else 1
            if len(indices) != rank:
                raise SemanticError("В выражении нужно указать отдельный элемент контейнера")
            for dimension, index in enumerate(reversed(indices)):
                index_type, value = self._container_expression_info(index, source)
                if index_type != "int":
                    raise SemanticError(f"Индекс '{symbol.name}' должен иметь тип int, получен {index_type}")
                size = symbol.known_dimensions[dimension] if symbol.container == "array" else None
                if value is not None and (value < 0 or (size is not None and value >= size)):
                    raise SemanticError(f"Индекс {value} выходит за границы '{symbol.name}', измерение {dimension + 1}")
            return symbol.type, None
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id[len("_size_"):]
            symbol = self.table.lookup(name)
            if symbol is None or symbol.kind != "func":
                raise SemanticError(f"Необъявленная функция в выражении: '{name}'")
            if node.keywords or len(node.args) != len(symbol.params):
                raise SemanticError(f"Неверное число аргументов функции '{name}' в выражении")
            for argument in node.args:
                self._container_expression_info(argument, source)
            return symbol.return_type, None
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            type_, value = self._container_expression_info(node.operand, source)
            if type_ not in NUMERIC:
                raise SemanticError("Унарная операция требует числовой операнд")
            return ("int" if type_ in ("char", "bool") else type_,
                    -value if value is not None and isinstance(node.op, ast.USub) else value)
        elif isinstance(node, ast.BinOp):
            left_type, left = self._container_expression_info(node.left, source)
            right_type, right = self._container_expression_info(node.right, source)
            if left_type not in NUMERIC or right_type not in NUMERIC:
                raise SemanticError("Арифметика требует числовые операнды")
            integer = ("int", "char", "bool")
            if isinstance(node.op, (ast.Mod, ast.LShift, ast.RShift)) and (left_type not in integer or right_type not in integer):
                raise SemanticError("Остаток и сдвиги требуют целочисленные операнды")
            result_type = "double" if "double" in (left_type, right_type) else "float" if "float" in (left_type, right_type) else "int"
            value = self._integer_operation(node.op, left, right)
            return result_type, value
        elif isinstance(node, ast.Compare):
            for operand in (node.left, *node.comparators):
                type_, _ = self._container_expression_info(operand, source)
                if type_ not in NUMERIC:
                    raise SemanticError("Сравнение требует числовые операнды")
            return "bool", None
        raise SemanticError("Неподдерживаемая операция в выражении")

    @staticmethod
    def _integer_operation(operation, left, right):
        if isinstance(operation, (ast.Div, ast.Mod)) and right == 0:
            raise SemanticError("Деление на ноль в выражении")
        if isinstance(operation, (ast.LShift, ast.RShift)) and right is not None and right < 0:
            raise SemanticError("Отрицательный сдвиг в выражении")
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
        raise SemanticError("Неподдерживаемая арифметическая операция в выражении")

    # ---------- for: инициализация ----------
    def visit_Init(self, node):
        if not node.value:
            return
        text = node.value.strip()
        if text.startswith("const "):
            declaration = re.fullmatch(r"const\s+(int|float|double|char|bool|void|auto)\s+(.+)", text)
            if declaration is None:
                raise SemanticError("Неподдерживаемое const-объявление в инициализации for")
            var_type, variables = declaration.groups()
            for variable in self.split_args(variables):
                match = re.fullmatch(r"\s*([A-Za-z_]\w*)\s*(?:=\s*(.+))?", variable)
                if match is None:
                    raise SemanticError("В инициализации for поддерживаются простые const-переменные")
                var_name, rhs = match.groups()
                if rhs is None:
                    raise SemanticError(f"Константа '{var_name}' должна иметь инициализацию")
                self.table.declare(Symbol(var_name, var_type, is_const=True))
                rhs_type = self.eval_expr(rhs)
                self.check_assign(var_type, rhs_type, var_name)
            return
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

    visit_Iter = visit_ExprStmt
    visit_Expression = visit_ExprStmt

    def visit_Empty(self, node):
        pass

    def visit_Break(self, node):
        pass

    def visit_Continue(self, node):
        pass

    # ---------- проверки ----------
    def check_writable(self, name):
        symbol = self.table.lookup(name)
        if symbol is not None and symbol.is_const:
            raise SemanticError(f"Нельзя изменять константу '{name}' или её элементы")

    def _check_const_writes(self, text):
        # Ищем цели записи во всём выражении, включая аргументы и индексы.
        tokens = re.findall(r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[A-Za-z_]\w*|\+\+|--|\+=|-=|\*=|/=|==|!=|<=|>=|&&|\|\||::|<<|>>|\S''', text)
        pairs, stack, levels = {}, [], []
        for position, token in enumerate(tokens):
            levels.append(len(stack))
            if token in ("(", "[", "{"):
                stack.append(position)
            elif token in (")", "]", "}") and stack:
                opening = stack.pop()
                pairs[opening] = position
                pairs[position] = opening

        def check_target(start):
            while start < len(tokens) and tokens[start] == "(":
                start += 1
            if start < len(tokens) and re.fullmatch(r"[A-Za-z_]\w*", tokens[start]):
                self.check_writable(tokens[start])

        def previous_operand(end):
            start = end
            while start in pairs and tokens[start] in (")", "]"):
                start = pairs[start]
                if start > 0 and (tokens[start - 1] in (")", "]") or
                                  re.fullmatch(r"[A-Za-z_]\w*", tokens[start - 1])):
                    start -= 1
                else:
                    break
            return start

        input_levels = set()
        for position, token in enumerate(tokens):
            level = levels[position]
            if token in ("=", "+=", "-=", "*=", "/=") and position > 0:
                check_target(previous_operand(position - 1))
            elif token in ("++", "--"):
                if position > 0 and (tokens[position - 1] in (")", "]") or
                                     re.fullmatch(r"[A-Za-z_]\w*", tokens[position - 1])):
                    check_target(previous_operand(position - 1))
                else:
                    check_target(position + 1)

            if token == "cin":
                qualified = position >= 2 and tokens[position - 2:position] == ["std", "::"]
                unqualified = (position == 0 or tokens[position - 1] != "::")
                if qualified or (unqualified and self.table.lookup("cin") is self.table.scopes[0]["cin"]):
                    input_levels.add(level)
            elif token == ">>" and level in input_levels:
                check_target(position + 1)
            elif token == ")" and level in input_levels:
                input_levels.discard(level)
                opening = pairs[position]
                if opening == 0 or not (tokens[opening - 1] in (")", "]") or
                                        re.fullmatch(r"[A-Za-z_]\w*", tokens[opening - 1])):
                    input_levels.add(level - 1)
            elif token in ("=", "+=", "-=", "*=", "/=", ",", "&&", "||", "<<",
                           "+", "-", "*", "/", "%", "==", "!=", "<", "<=", ">", ">=", ")", "]", "}"):
                input_levels.discard(level)

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
    def _check_element_accesses(self, text):
        if "[" not in text:
            return []
        # Выделяем обращения вне строк; сами индексы разбирает общий обработчик выражений.
        tokens = list(re.finditer(r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[A-Za-z_]\w*|\S''', text))
        stack, starts, spans = [], {}, []
        for position, token in enumerate(tokens):
            if token[0] in ("(", "["):
                stack.append(position)
            elif token[0] in (")", "]"):
                if not stack:
                    raise SemanticError("Незакрытые скобки в выражении")
                opening = stack.pop()
                start = opening
                previous = opening - 1
                if previous >= 0 and (previous in starts or re.fullmatch(r"[A-Za-z_]\w*", tokens[previous][0])):
                    start = starts.get(previous, previous)
                starts[position] = start
                if token[0] == "]":
                    begin, end = tokens[start].start(), token.end()
                    # Внешнее обращение включает проверки вложенных индексов и всей цепочки [].
                    while spans and spans[-1][0] >= begin:
                        spans.pop()
                    spans.append((begin, end))
        for begin, end in spans:
            try:
                parsed, source = self._parse_container_expression(text[begin:end])
                self._container_expression_info(parsed, source)
            except (SyntaxError, ValueError) as error:
                raise SemanticError(f"Неподдерживаемое обращение к элементу: {text[begin:end]}") from error
        return spans

    def eval_expr(self, expr_text):
        if not expr_text:
            return "unknown"
        text = expr_text.strip()
        self._check_const_writes(text)
        accesses = self._check_element_accesses(text)

        # cout / cin — не проверяем как обычное выражение
        if re.match(r"^(?:std\s*::\s*)?(?:cout|cin)\b", text):
            return "unknown"

        # присваивание
        assign = self._find_assign(text)
        if assign != -1:
            left = text[:assign].strip()
            right = text[assign + 1:].strip()
            sym = self.table.lookup(left)
            if any(end <= assign for _, end in accesses):
                try:
                    parsed, source = self._parse_container_expression(left)
                except (SyntaxError, ValueError) as error:
                    raise SemanticError(f"Неподдерживаемая левая часть присваивания: '{left}'") from error
                if not isinstance(parsed, ast.Subscript):
                    raise SemanticError(f"Слева от присваивания нужен элемент контейнера: '{left}'")
                left_type, _ = self._container_expression_info(parsed, source)
            elif sym is None:
                raise SemanticError(f"Присваивание необъявленной переменной '{left}'")
            else:
                if sym.container:
                    raise SemanticError(f"Нельзя присваивать контейнеру '{left}' целиком")
                left_type = sym.type
            rhs_type = self.eval_expr(right)
            self.check_assign(left_type, rhs_type, left)
            return left_type

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

        if accesses:
            try:
                parsed, source = self._parse_container_expression(text)
            except (SyntaxError, ValueError):
                # Логика C++ и ++/-- остаются в существующей обработке ниже.
                pass
            else:
                return self._container_expression_info(parsed, source)[0]

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
            if accesses:
                for argument in args_list:
                    self.eval_expr(argument)
            return sym.return_type or "unknown"

        # идентификатор
        if re.match(r"^[A-Za-z_]\w*$", text):
            sym = self.table.lookup(text)
            if sym is None:
                raise SemanticError(f"Использование необъявленного идентификатора '{text}'")
            if sym.container:
                raise SemanticError(f"В выражении нужен элемент контейнера '{text}'")
            return sym.type

        if accesses:
            # Имена и литералы внутри индексов уже проверены выше.
            for begin, end in reversed(accesses):
                text = text[:begin] + "0" + text[end:]

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
        for token in re.finditer(r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[\s\S]''', text):
            i, ch = token.start(), token[0]
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
        for ch in re.findall(r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[\s\S]''', s):
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
