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

    # ---------- утилиты ----------
    def emit(self, line=""):
        if line == "":
            self.lines.append("")
        else:
            self.lines.append("    " * self.indent + line)

    def new_temp(self):
        self.temp_count += 1
        return f"_t{self.temp_count}"

    def push(self):
        self.indent += 1

    def pop(self):
        self.indent -= 1

    # ---------- точка входа ----------
    def generate(self, tree, symbol_table=None):
        if symbol_table:
            self._load_types(symbol_table)

        self.emit("# -*- coding: utf-8 -*-")
        self.emit("# Сгенерировано транслятором C++ -> Python")
        self.emit("")

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

        return "\n".join(self.lines)

    def _load_types(self, table):
        for scope in table.scopes:
            for name, sym in scope.items():
                self.var_types[name] = sym.type

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
        text = node.value
        if "iostream" in text:
            self.emit("# #include <iostream> -> встроенный print()")
        else:
            self.emit(f"# {text}")

    def gen_Block(self, node):
        for child in node.children:
            self.visit(child)

    # ---------- функции ----------
    def gen_Function(self, node):
        return_type, name, params = "void", "?", []
        for child in node.children:
            if child.type == "ReturnType":
                return_type = child.value.split()[-1]
            elif child.type == "FuncName":
                name = child.value
            elif child.type == "Parameters":
                params = [p.value for p in child.children]

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

    # ---------- объявления ----------
    def gen_Declaration(self, node):
        var_type = node.value
        for child in node.children:
            if child.type == "VarName":
                name = child.value
                value_node = next((c for c in child.children if c.type == "Value"), None)
                if value_node:
                    expr = self.translate_expr(value_node.value)
                    self.emit(f"{name} = {expr}")
                else:
                    self.emit(f"{name} = {self.DEFAULTS.get(var_type, 'None')}")

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
        init = next((c for c in node.children if c.type == "Init"), None)
        cond = next((c for c in node.children if c.type == "Condition"), None)
        itr = next((c for c in node.children if c.type == "Iter"), None)
        body = next((c for c in node.children if c.type in ("Block", "If", "ExprStmt",
                                                              "While", "For", "DoWhile")), None)

        if init and init.value:
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

    #  ПЕРЕВОД ВЫРАЖЕНИЯ C++ -> Python
    def translate_expr(self, expr_text):
        if not expr_text:
            return "None"

        text = expr_text.strip()

        # cout << ... << endl
        if text.lstrip().startswith("cout"):
            parts = [p.strip() for p in re.split(r"<<", text)]
            args, has_endl = [], False
            for p in parts[1:]:
                if p == "endl":
                    has_endl = True
                else:
                    args.append(self.translate_expr(p))
            if has_endl:
                return f"print({', '.join(args)})" if args else "print()"
            return f"print({', '.join(args)}, end='')"

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
    def _split_args(s):
        args, depth, cur = [], 0, ""
        for ch in s:
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