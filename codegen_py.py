import ast
import re


class PythonCodeGenerator:
    """Генератор Python-кода из синтаксического дерева C++."""

    DEFAULTS = {
        "int": "0", "float": "0.0", "double": "0.0",
        "char": "''", "bool": "False", "void": "None",
    }

    def __init__(self):
        self.lines = []
        self.indent = 0
        self.temp_count = 0
        self.var_types = {}
        self.used_names = set()
        self.array_builtins = None
        self.division_helper = None
        self.char_arrays = set()
        self.numeric_char_writes = set()

    # ---------- утилиты ----------
    def emit(self, line=""):
        if line == "":
            self.lines.append("")
        else:
            self.lines.append("    " * self.indent + line)

    def new_temp(self):
        self.temp_count += 1
        while f"_t{self.temp_count}" in self.used_names:
            self.temp_count += 1
        return f"_t{self.temp_count}"

    def size_expression(self, text, values, var_type):
        def pure(expression):
            tokens = re.findall(r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\+\+|--''', expression)
            if any(token in ("++", "--") for token in tokens):
                return False
            try:
                tree = ast.parse(self.normalize_array_expr(expression).strip(), mode="eval")
            except SyntaxError:
                return False
            return not any(isinstance(node, (ast.Call, ast.NamedExpr)) for node in ast.walk(tree))

        translated = self.translate_array_expr(text, integer_division=True)
        literals = all(self.array_literal(value.value, var_type) is not None for value in values)
        if literals or (pure(text) and all(pure(value.value) for value in values)):
            tree = ast.parse(translated, mode="eval").body
            if isinstance(tree, (ast.Name, ast.Constant, ast.Call, ast.Subscript)):
                return translated
            return f"({translated})"
        size = self.new_temp()
        self.emit(f"{size} = {translated}")
        return size

    def push(self):
        self.indent += 1

    def pop(self):
        self.indent -= 1

    # ---------- точка входа ----------
    def generate(self, tree, symbol_table=None):
        if symbol_table:
            self._load_types(symbol_table)

        pending, needs_array_casts = [tree], False
        while pending:
            node = pending.pop()
            self.used_names.update(re.findall(r"[A-Za-z_]\w*", str(node.value or "")))
            expression = node.value if isinstance(node.value, str) else ""
            while (assign := self._find_assign(expression)) != -1:
                left, right = expression[:assign].strip(), expression[assign + 1:].strip()
                try:
                    target = ast.parse(self.normalize_array_expr(left), mode="eval").body
                except SyntaxError:
                    target = None
                if isinstance(target, ast.Subscript):
                    while isinstance(target, ast.Subscript):
                        target = target.value
                    try:
                        value = ast.literal_eval(self.normalize_array_expr(right))
                    except (SyntaxError, ValueError):
                        value = None
                    if isinstance(target, ast.Name) and not (right.startswith("'") and isinstance(value, str) and len(value) == 1):
                        self.numeric_char_writes.add(target.id)
                expression = right
            if node.type == "Declaration":
                for child in node.children:
                    if child.type == "ArrayName" and sum(c.type == "Dimension" for c in child.children) in (1, 2):
                        initializer = next((c for c in child.children if c.type == "InitializerList"), None)
                        if initializer is not None:
                            values = [value for item in initializer.children
                                      for value in (item.children if item.type == "InitializerList" else [item])]
                            needs_array_casts |= any(self.array_literal(c.value, node.value) is None
                                                     for c in values)
                    elif child.type == "VectorName":
                        element_type = node.value[len("vector<"):-1]
                        initializer = next((c for c in child.children
                                            if c.type in ("InitializerList", "ConstructorArgs")), None)
                        if initializer is not None:
                            values = (initializer.children[1:] if initializer.type == "ConstructorArgs"
                                      else initializer.children)
                            needs_array_casts |= any(self.array_literal(c.value, element_type) is None
                                                     for c in values)
            pending.extend(node.children)

        # self.emit("# -*- coding: utf-8 -*-")
        # self.emit("# Сгенерировано транслятором C++ -> Python")
        # self.emit("")
        if needs_array_casts:
            self.array_builtins = self.new_temp()

        self.visit(tree)

        # точка входа
        has_main = any(
            c.type == "Function"
            and any(g.type == "FuncName" and g.value == "main" for g in c.children)
            for c in tree.children
        )
        if has_main:
            self.emit('if __name__ == "__main__":')
            self.push()
            self.emit("main()")
            self.pop()

        prelude = []
        if self.array_builtins is not None:
            prelude.extend([f"import builtins as {self.array_builtins}", ""])
        if self.division_helper is not None:
            absolute = f"{self.array_builtins}.abs" if "abs" in self.used_names else "abs"
            prelude.extend([
                f"def {self.division_helper}(a, b):",
                "    a, b = int(a), int(b)",
                f"    q = {absolute}(a) // {absolute}(b)",
                "    return q if (a >= 0) == (b > 0) else -q",
                "",
            ])
        self.lines[:0] = prelude
        return "\n".join(self.lines)

    def _load_types(self, table):
        for scope in table.scopes:
            for name, sym in scope.items():
                self.var_types[name] = sym.type
                if sym.type == "char" and sym.container == "array" and len(sym.dimensions) == 1:
                    self.char_arrays.add(name)

    # ---------- обход ----------
    def visit(self, node):
        if node is None:
            return
        method = getattr(self, f"gen_{node.type}", self.gen_generic)
        method(node)

    def gen_generic(self, node):
        for child in node.children:
            self.visit(child)

    def gen_Program(self, node):
        for child in node.children:
            self.visit(child)

    def gen_Preprocessor(self, node):
        # text = node.value
        # if "iostream" in text:
        #     self.emit("# #include <iostream> -> встроенный print()")
        # else:
        #     self.emit(f"# {text}")
        pass

    def gen_Block(self, node):
        saved_types = self.var_types.copy()
        saved_char_arrays = self.char_arrays.copy()
        for child in node.children:
            self.visit(child)
        self.var_types = saved_types
        self.char_arrays = saved_char_arrays

    # ---------- функции ----------
    def gen_Function(self, node):
        return_type, name, params = "void", "?", []
        param_types = {}
        for child in node.children:
            if child.type == "ReturnType":
                return_type = child.value.split()[-1]
            elif child.type == "FuncName":
                name = child.value
            elif child.type == "Parameters":
                params = [p.value for p in child.children]
                param_types = {p.value: p.param_type for p in child.children}

        self.var_types[name] = return_type
        saved_types = self.var_types.copy()
        saved_char_arrays = self.char_arrays.copy()
        self.var_types.update(param_types)
        self.char_arrays.difference_update(param_types)

        self.emit(f"def {name}({', '.join(params)}):")
        self.push()

        body = next((c for c in node.children if c.type == "Block"), None)
        if body and body.children:
            self.visit(body)
        else:
            self.emit("pass")

        if return_type and return_type != "void":
            last = self.lines[-1].strip() if self.lines else ""
            if not last.startswith("return"):
                self.emit("return None")

        self.pop()
        self.emit("")
        self.var_types = saved_types
        self.char_arrays = saved_char_arrays

    # ---------- объявления ----------
    def gen_Declaration(self, node):
        var_type = node.value
        for child in node.children:
            if child.type == "VarName":
                name = child.value
                self.var_types[name] = var_type
                self.char_arrays.discard(name)
                value_node = next((c for c in child.children if c.type == "Value"), None)
                if value_node:
                    expr = self.translate_expr(value_node.value)
                    self.emit(f"{name} = {expr}")
                else:
                    self.emit(f"{name} = {self.DEFAULTS.get(var_type, 'None')}")
            elif child.type == "ArrayName":
                rank = sum(c.type == "Dimension" for c in child.children)
                if rank == 1:
                    self.gen_array_1d(child, var_type)
                elif rank == 2:
                    self.gen_array_2d(child, var_type)
                self.var_types[child.value] = var_type
                if var_type == "char" and rank == 1:
                    self.char_arrays.add(child.value)
                else:
                    self.char_arrays.discard(child.value)
            elif child.type == "VectorName":
                self.gen_vector(child, var_type)
                self.var_types[child.value] = var_type[len("vector<"):-1]
                self.char_arrays.discard(child.value)

    def gen_vector(self, node, var_type):
        symbol = getattr(node, "symbol", None)
        element_type = symbol.type if symbol is not None else var_type[len("vector<"):-1]
        initializer = next((child for child in node.children
                            if child.type in ("InitializerList", "ConstructorArgs")), None)
        if initializer is None or not initializer.children:
            result = "[]"
        elif initializer.type == "InitializerList":
            values = initializer.children
            result = self.array_values(values, element_type, str(len(values)), len(values))
        else:
            arguments = initializer.children
            size = self.array_literal(arguments[0].value, "int")
            known_size = int(size) if size is not None else None
            if known_size is None:
                size = self.size_expression(arguments[0].value, arguments[1:], element_type)

            value = repr("\0") if element_type == "char" else self.DEFAULTS.get(element_type, "None")
            if len(arguments) == 2:
                value = self.array_literal(arguments[1].value, element_type)
            if known_size is not None and value is not None:
                result = f"[{', '.join([value] * known_size)}]"
            else:
                initial_value = (self.array_values(arguments[1:], element_type, "1", 1)
                                 if len(arguments) == 2 else f"[{value}]")
                result = f"{initial_value} * {size}"
        self.emit(f"{node.value} = {result}")

    def gen_array_1d(self, node, var_type):
        string = next((child for child in node.children if child.type == "Value"), None)
        symbol = getattr(node, "symbol", None)
        if symbol is not None:
            var_type = symbol.type
            dimension = symbol.dimensions[0]
            known_size = symbol.known_dimensions[0]
        else:
            dimension = next(child.value for child in node.children if child.type == "Dimension")
            known_size = (int(dimension, 8 if dimension.startswith("0") else 10)
                          if dimension is not None and dimension.isdecimal() else None)

        initializer = next((child for child in node.children if child.type == "InitializerList"), None)
        if string is not None:
            values = self.char_string_values(string.value)
        else:
            values = initializer.children if initializer is not None else []
        if dimension is None:
            known_size = len(values)
        if known_size is not None:
            size = str(known_size)
        else:
            size = self.size_expression(dimension, [] if string is not None else values, var_type)

        if string is not None:
            zero = repr("\0")
            if known_size is not None:
                values.extend([zero] * (known_size - len(values)))
            result = f"[{', '.join(values)}]"
            if known_size is None:
                result += f" + [{zero}] * ({size} - {len(values)})"
        else:
            result = self.array_values(values, var_type, size, known_size)
        self.emit(f"{node.value} = {result}")

    @staticmethod
    def char_string_values(literal):
        characters = re.findall(r'''\\(?:[0-7]{1,3}|x[0-9a-fA-F]+|u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8}|['"?\\abfnrtv])|[^\\\r\n]''', literal[1:-1])
        escapes = {"'": "'", '"': '"', "?": "?", "\\": "\\", "a": "\a", "b": "\b",
                   "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v"}
        values = []
        for character in characters:
            if character[0] != "\\":
                value = character
            elif character[1] in escapes:
                value = escapes[character[1]]
            elif character[1] in "01234567":
                value = chr(int(character[1:], 8))
            else:
                value = chr(int(character[2:], 16))
            values.append(repr(value))
        return values + [repr("\0")]

    def gen_array_2d(self, node, var_type):
        initializer = next((child for child in node.children if child.type == "InitializerList"), None)
        rows = initializer.children if initializer is not None else []
        symbol = getattr(node, "symbol", None)
        if symbol is not None:
            var_type = symbol.type
            dimensions, known_sizes = symbol.dimensions, list(symbol.known_dimensions)
        else:
            dimensions = [child.value for child in node.children if child.type == "Dimension"]
            known_sizes = [(int(value, 8 if value.startswith("0") else 10)
                            if value is not None and value.isdecimal() else None) for value in dimensions]
        if dimensions[0] is None:
            known_sizes[0] = len(rows)

        sizes = []
        for expression, known_size in zip(dimensions, known_sizes):
            if known_size is not None:
                sizes.append(str(known_size))
            else:
                translated = self.translate_array_expr(expression, integer_division=True)
                size = self.new_temp()
                self.emit(f"{size} = {translated}")
                sizes.append(size)

        row_values = [self.array_values(row.children, var_type, sizes[1], known_sizes[1], True)
                      for row in rows]
        empty_row = self.array_values([], var_type, sizes[1], known_sizes[1], True)
        if known_sizes[0] is not None:
            row_values.extend([empty_row] * (known_sizes[0] - len(rows)))
            result = f"[{', '.join(row_values)}]"
        else:
            item = self.new_temp()
            if row_values:
                result = (f"[{', '.join(row_values)}] + "
                          f"[{empty_row} for {item} in [0] * ({sizes[0]} - {len(rows)})]")
            else:
                result = f"[{empty_row} for {item} in [0] * {sizes[0]}]"
        self.emit(f"{node.value} = {result}")

    def array_values(self, values, var_type, size, known_size, expand_empty=False):
        default = repr("\0") if var_type == "char" else self.DEFAULTS.get(var_type, "None")
        if not values:
            if expand_empty and known_size is not None:
                return f"[{', '.join([default] * known_size)}]"
            return f"[{default}] * {size}"

        literals = [self.array_literal(value.value, var_type) for value in values]
        if all(value is not None for value in literals):
            if known_size is not None:
                literals.extend([default] * (known_size - len(literals)))
            result = f"[{', '.join(literals)}]"
        else:
            expressions = [self.translate_array_expr(value.value) for value in values]
            item = self.new_temp()
            builtins = self.array_builtins
            casts = {
                "int": f"{builtins}.int({builtins}.ord({item}) if {builtins}.isinstance({item}, {builtins}.str) else {item})",
                "float": f"{builtins}.float({item})",
                "double": f"{builtins}.float({item})",
                "bool": f"{builtins}.bool({item})",
                "char": f"{builtins}.chr({item}) if {builtins}.isinstance({item}, {builtins}.int) else {item}",
            }
            result = f"[{casts.get(var_type, item)} for {item} in [{', '.join(expressions)}]]"
        if known_size != len(literals):
            result += f" + [{default}] * ({size} - {len(values)})"
        return result

    def array_literal(self, text, var_type):
        if re.fullmatch(r'''(?:true|false|[+-]?\s*(?:0[xX][0-9a-fA-F]+|\d+(?:\.\d+)?)|'(?:\\.|[^'\\])')''', text.strip()) is None:
            return None
        try:
            value = ast.literal_eval(self.translate_array_expr(text))
            if var_type == "int":
                value = int(ord(value) if isinstance(value, str) else value)
            elif var_type in ("float", "double"):
                value = float(value)
            elif var_type == "bool":
                value = bool(value)
            elif var_type == "char":
                value = chr(value) if isinstance(value, int) else value
            else:
                return None
        except (SyntaxError, ValueError, TypeError, OverflowError):
            return None
        result = repr(value)
        return result if result not in ("inf", "-inf", "nan") else None

    def translate_array_expr(self, text, integer_division=False):
        text = self.normalize_array_expr(text)
        if integer_division:
            text = self.translate_integer_divisions(text)
        return self.translate_expr(text)

    @staticmethod
    def normalize_array_expr(text):
        # Запись восьмеричных чисел и escape-последовательности \? отличается в Python.
        return re.sub(r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\b0[0-9]+\b(?!\.)|\btrue\b|\bfalse\b''',
                      lambda match: ("'?'" if match[0] == r"'\?'" else
                                     match[0] if match[0][0] in "\"'" else
                                     "True" if match[0] == "true" else "False" if match[0] == "false" else
                                     "0o" + match[0][1:]), text)

    def translate_index_divisions(self, text):
        if "[" not in text or "/" not in text:
            return text
        stack, indices = [], []
        for token in re.finditer(r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\[|\]''', text):
            if token[0] == "[":
                stack.append(token.end())
            elif token[0] == "]" and stack:
                start = stack.pop()
                if not stack:
                    indices.append((start, token.start()))
        for start, end in reversed(indices):
            translated = self.translate_integer_divisions(text[start:end])
            text = text[:start] + translated + text[end:]
        return text

    def translate_integer_divisions(self, text):
        if "/" not in text:
            return text
        source = self.normalize_array_expr(text).strip()
        try:
            tree = ast.parse(source, mode="eval")
        except SyntaxError:
            return text
        if not any(isinstance(node, ast.Div) for node in ast.walk(tree)):
            return text
        owner, changed = self, False
        integral = {"int", "char", "bool"}

        def expression_type(node):
            if hasattr(node, "cpp_type"):
                return node.cpp_type
            if isinstance(node, ast.Constant):
                if type(node.value) is bool:
                    return "bool"
                if type(node.value) is int:
                    return "int"
                if type(node.value) is float:
                    return "float"
                literal = ast.get_source_segment(source, node) or ""
                return "char" if literal.startswith("'") and len(node.value) == 1 else "unknown"
            if isinstance(node, ast.Name):
                return owner.var_types.get(node.id, "unknown")
            if isinstance(node, ast.Subscript):
                return expression_type(node.value)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                return owner.var_types.get(node.func.id, "unknown")
            if isinstance(node, ast.Compare):
                return "bool"
            if isinstance(node, ast.UnaryOp):
                type_ = expression_type(node.operand)
                return "int" if type_ in integral else type_
            if isinstance(node, ast.BinOp):
                types = {expression_type(node.left), expression_type(node.right)}
                if types <= integral:
                    return "int"
                return "double" if "double" in types else "float" if "float" in types else "unknown"
            return "unknown"

        def promote(node):
            nonlocal changed
            type_ = expression_type(node)
            if type_ not in ("char", "bool"):
                return node
            changed = True
            if isinstance(node, ast.Constant):
                return ast.copy_location(ast.Constant(ord(node.value) if type_ == "char" else int(node.value)), node)
            if type_ == "char":
                if owner.array_builtins is None:
                    owner.array_builtins = owner.new_temp()
                item = owner.new_temp()
                builtins = owner.array_builtins
                result = ast.parse(
                    f"[{builtins}.ord({item}) if {builtins}.isinstance({item}, {builtins}.str) "
                    f"else {builtins}.int({item}) for {item} in [None]][0]", mode="eval").body
                result.value.generators[0].iter.elts[0] = node
            else:
                result = ast.Call(func=ast.Name(id="bool", ctx=ast.Load()), args=[node], keywords=[])
            result.cpp_type = "int"
            return ast.copy_location(result, node)

        class RewriteDivision(ast.NodeTransformer):
            def visit_Call(self, node):
                # Повторный обход сохраняет уже переведённое целочисленное выражение.
                if isinstance(node.func, ast.Name) and node.func.id in ("int", owner.division_helper):
                    node.cpp_type = "int"
                    return node
                return self.generic_visit(node)

            def visit_BinOp(self, node):
                nonlocal changed
                self.generic_visit(node)
                left_type, right_type = expression_type(node.left), expression_type(node.right)
                node.left, node.right = promote(node.left), promote(node.right)
                if isinstance(node.op, ast.Div) and left_type in integral and right_type in integral:
                    changed = True
                    if owner.division_helper is None:
                        name, suffix = "cpp_div", 1
                        while name in owner.used_names:
                            name = f"cpp_div_{suffix}"
                            suffix += 1
                        owner.division_helper = name
                        if "abs" in owner.used_names and owner.array_builtins is None:
                            owner.array_builtins = owner.new_temp()
                    result = ast.Call(func=ast.Name(id=owner.division_helper, ctx=ast.Load()),
                                      args=[node.left, node.right], keywords=[])
                    result.cpp_type = "int"
                    return ast.copy_location(result, node)
                return node

            def visit_UnaryOp(self, node):
                self.generic_visit(node)
                if isinstance(node.op, (ast.UAdd, ast.USub)):
                    node.operand = promote(node.operand)
                return node

            def visit_Compare(self, node):
                self.generic_visit(node)
                node.left = promote(node.left)
                node.comparators = [promote(value) for value in node.comparators]
                return node

        tree = RewriteDivision().visit(tree)
        return ast.unparse(ast.fix_missing_locations(tree.body)) if changed else text

    # ---------- if / else ----------
    def gen_If(self, node):
        cond = next((c for c in node.children if c.type == "Condition"), None)
        then_node = next((c for c in node.children if c.type == "Then"), None)
        else_node = next((c for c in node.children if c.type == "Else"), None)

        cond_py = self.translate_expr(cond.value) if cond else "False"
        self.emit(f"if {cond_py}:")
        self.push()
        if then_node and then_node.children:
            for ch in then_node.children:
                self.visit(ch)
        else:
            self.emit("pass")
        self.pop()

        if else_node and else_node.children:
            inner = else_node.children[0]
            if inner.type == "If":
                self._gen_elif(inner)
            else:
                self.emit("else:")
                self.push()
                for ch in else_node.children:
                    self.visit(ch)
                self.pop()

    def _gen_elif(self, node):
        cond = next((c for c in node.children if c.type == "Condition"), None)
        then_node = next((c for c in node.children if c.type == "Then"), None)
        else_node = next((c for c in node.children if c.type == "Else"), None)

        cond_py = self.translate_expr(cond.value) if cond else "False"
        self.emit(f"elif {cond_py}:")
        self.push()
        if then_node and then_node.children:
            for ch in then_node.children:
                self.visit(ch)
        else:
            self.emit("pass")
        self.pop()

        if else_node and else_node.children:
            inner = else_node.children[0]
            if inner.type == "If":
                self._gen_elif(inner)
            else:
                self.emit("else:")
                self.push()
                for ch in else_node.children:
                    self.visit(ch)
                self.pop()

    # ---------- while ----------
    def gen_While(self, node):
        cond = next((c for c in node.children if c.type == "Condition"), None)
        body = next((c for c in node.children if c.type != "Condition"), None)

        cond_py = self.translate_expr(cond.value) if cond else "False"
        self.emit(f"while {cond_py}:")
        self.push()
        if body and body.children:
            self.visit(body)
        else:
            self.emit("pass")
        self.pop()

    # ---------- do-while ----------
    def gen_DoWhile(self, node):
        body = next((c for c in node.children if c.type != "Condition"), None)
        cond = next((c for c in node.children if c.type == "Condition"), None)

        self.emit("while True:")
        self.push()
        if body and body.children:
            self.visit(body)
        cond_py = self.translate_expr(cond.value) if cond else "True"
        self.emit(f"if not ({cond_py}):")
        self.push()
        self.emit("break")
        self.pop()
        self.pop()

    # ---------- for ----------
    def gen_For(self, node):
        saved_types = self.var_types.copy()
        saved_char_arrays = self.char_arrays.copy()
        init = next((c for c in node.children if c.type == "Init"), None)
        cond = next((c for c in node.children if c.type == "Condition"), None)
        itr = next((c for c in node.children if c.type == "Iter"), None)
        body = next((c for c in node.children if c.type in ("Block", "If", "ExprStmt",
                                                              "While", "For", "DoWhile")), None)

        if init and init.value:
            declaration = re.match(r"^(int|float|double|char|bool|void|auto)\s+([A-Za-z_]\w*)", init.value)
            if declaration:
                self.var_types[declaration[2]] = declaration[1]
                self.char_arrays.discard(declaration[2])
            val = re.sub(r"^(int|float|double|char|bool|void|auto)\s+", "", init.value)
            self.translate_expr(val)

        cond_py = self.translate_expr(cond.value) if cond and cond.value else "True"
        self.emit(f"while {cond_py}:")
        self.push()
        if body and body.children:
            self.visit(body)
        if itr and itr.value:
            self.translate_expr(itr.value)
        if not (body and body.children):
            self.emit("pass")
        self.pop()
        self.var_types = saved_types
        self.char_arrays = saved_char_arrays

    # ---------- return ----------
    def gen_Return(self, node):
        for child in node.children:
            if child.type == "Value":
                expr = self.translate_expr(child.value)
                self.emit(f"return {expr}")
                return
        self.emit("return")

    # ---------- break / continue ----------
    def gen_Break(self, node):
        self.emit("break")

    def gen_Continue(self, node):
        self.emit("continue")

    # ---------- выражения-инструкции ----------
    def gen_ExprStmt(self, node):
        if node.value and node.value != "empty":
            result = self.translate_expr(node.value)
            if result and result.startswith("print"):
                self.emit(result)

    def gen_Empty(self, node):
        self.emit("pass")

    def char_array_output(self, text, translated):
        try:
            value = ast.parse(text, mode="eval").body
        except SyntaxError:
            return None
        if not isinstance(value, ast.Name) or value.id not in self.char_arrays:
            return None
        if value.id in self.numeric_char_writes:
            prefix = ""
            if {"chr", "isinstance"} & self.used_names:
                if self.array_builtins is None:
                    self.array_builtins = self.new_temp()
                prefix = self.array_builtins + "."
            translated = (f"({prefix}chr(char) if {prefix}isinstance(char, int) else char "
                          f"for char in {translated})")
        return f"''.join({translated}).split('\\0', 1)[0]"

    #  ПЕРЕВОД ВЫРАЖЕНИЯ C++ -> Python
    def translate_expr(self, expr_text):
        if not expr_text:
            return "None"

        text = expr_text.strip()
        text = self.translate_index_divisions(text)

        # cout << ... << endl
        if re.match(r"^(?:std\s*::\s*)?cout\b", text):
            parts = [p.strip() for p in re.split(r"<<", text)]
            args, has_endl, has_char_array = [], False, False
            for p in parts[1:]:
                if re.fullmatch(r"(?:std\s*::\s*)?endl", p):
                    has_endl = True
                else:
                    translated = self.translate_expr(p)
                    string = self.char_array_output(p, translated)
                    has_char_array |= string is not None
                    args.append(string if string is not None else translated)
            separator = ", sep=''" if has_char_array and len(args) > 1 else ""
            if has_endl:
                return f"print({', '.join(args)}{separator})" if args else "print()"
            return f"print({', '.join(args)}{separator}, end='')"

        # присваивание
        assign = self._find_assign(text)
        if assign != -1:
            left = text[:assign].strip()
            right = text[assign + 1:].strip()
            rhs = self.translate_expr(right)
            self.emit(f"{left} = {rhs}")
            return left

        # вызов функции
        m = re.match(r"^([A-Za-z_]\w*)\s*\((.*)\)$", text)
        if m:
            fname = m.group(1)
            args = [self.translate_expr(a) for a in self._split_args(m.group(2))]
            return f"{fname}({', '.join(args)})"

        # операторы и литералы
        text = self._replace_operators(text)
        return text

    @staticmethod
    def _replace_operators(text):
        result = []
        i = 0
        in_str = None
        while i < len(text):
            ch = text[i]
            if in_str:
                result.append(ch)
                if ch == in_str and (i == 0 or text[i - 1] != "\\"):
                    in_str = None
                i += 1
                continue
            if ch in "\"'":
                in_str = ch
                result.append(ch)
                i += 1
                continue

            if text.startswith("&&", i):
                result.append(" and ")
                i += 2
                continue
            if text.startswith("||", i):
                result.append(" or ")
                i += 2
                continue
            if ch == "!" and not text.startswith("!=", i):
                result.append(" not ")
                i += 1
                continue
            result.append(ch)
            i += 1

        s = "".join(result)
        s = re.sub(r"\btrue\b", "True", s)
        s = re.sub(r"\bfalse\b", "False", s)
        s = re.sub(r"[ \t]+", " ", s)
        return s.strip()

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
    def _split_args(s):
        args, depth, cur = [], 0, ""
        for ch in re.findall(r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[\s\S]''', s):
            if ch == "," and depth == 0:
                args.append(cur.strip())
                cur = ""
            else:
                if ch in "([{":
                    depth += 1
                if ch in ")]}":
                    depth -= 1
                cur += ch
        if cur.strip():
            args.append(cur.strip())
        return args
