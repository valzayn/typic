import re

# ЧТЕНИЕ ФАЙЛА
code = open("code3.cpp", encoding="utf-8").read()

# ЛЕКСИЧЕСКИЙ АНАЛИЗАТОР
patterns = {
    'PREPROCESSOR': r"#.*",
    'COMMENT': r"//.*|/\*[\s\S]*?\*/",
    'STRING': r'"(\\.|[^"\\])*"',
    'CHAR': r"'(\\.|[^'\\])'",
    'KEYWORDS': r"\b(if|else|while|for|return|int|float|double|char|bool|void|class|struct|public|private|protected|virtual|override|const|static|namespace|using|new|delete|try|catch|throw|switch|case|default|break|continue|do|auto|template|typename)\b",
    'NUMBER': r"\b(0[xX][0-9a-fA-F]+|\d+(\.\d+)?)\b",
    'OPERATOR': r"(::|>>|<<|\+\+|\-\-|\+=|-=|\*=|/=|==|!=|<=|>=|&&|\|\||[+\-*/%=<>!])",
    'IDENTIFIER': r"\b[a-zA-Z_][a-zA-Z0-9_]*\b",
    'DELIMITER': r"([{}[\]();,])",
}

tokens = []
pos = 0
code_len = len(code)

while pos < code_len:
    if code[pos].isspace():
        pos += 1
        continue

    match = None
    for token_type, pattern in patterns.items():
        regex = re.compile(pattern)
        match = regex.match(code, pos)

        if match:
            token_value = match.group(0)
            if token_type != "COMMENT":
                tokens.append((token_type, token_value))
            pos = match.end()
            break

    if not match:
        context_start = max(0, pos - 20)
        context_end = min(code_len, pos + 20)
        context = code[context_start:context_end]
        raise SyntaxError(f"Illegal character: '{code[pos]}' at position {pos}\nContext: ...{context}...")

tokens.append(("EOF", "EOF"))


# УЗЕЛ ДЕРЕВА
class Node:
    def __init__(self, type_, value=None, param_type=None):
        self.type = type_
        self.value = value
        self.param_type = param_type
        self.children = []

    def add(self, child):
        self.children.append(child)
        return child

    def print(self, indent=0):
        if self.type == "Parameters" and not self.children:
            return
        extra = ""
        if self.type == "Param" and self.param_type:
            extra = f" ({self.param_type})"
        print("  " * indent + f"{self.type}: {self.value if self.value else ''}{extra}")
        for child in self.children:
            child.print(indent + 1)


# ПАРСЕР
class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def current(self):
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return ("EOF", "EOF")

    def peek_next(self):
        if self.pos + 1 < len(self.tokens):
            return self.tokens[self.pos + 1]
        return ("EOF", "EOF")

    def next(self):
        self.pos += 1

    def match(self, type_=None, value_=None):
        t_type, t_value = self.current()
        if type_ and t_type != type_:
            raise SyntaxError(f"Expected type {type_}, got {t_type} '{t_value}' at token {self.pos}")
        if value_ and t_value != value_:
            raise SyntaxError(f"Expected '{value_}', got '{t_value}' at token {self.pos}")
        self.next()
        return t_type, t_value

    def parse(self):
        root = Node("Program")

        while self.current()[0] == "PREPROCESSOR":
            root.add(Node("Preprocessor", self.current()[1]))
            self.next()

        while self.current()[0] != "EOF":
            root.add(self.parse_top_level())

        return root

    def parse_top_level(self):
        t_type, value = self.current()

        if value in ("int", "float", "double", "char", "bool", "void", "auto") or \
           (value in ("const", "static", "virtual") and
            self.peek_next()[1] in ("int", "float", "double", "char", "bool", "void")):
            temp_pos = self.pos

            if self.tokens[temp_pos][1] in ("const", "static", "virtual"):
                temp_pos += 1

            temp_pos += 1

            if temp_pos < len(self.tokens) and self.tokens[temp_pos][0] == "IDENTIFIER":
                temp_pos += 1

                if temp_pos < len(self.tokens) and self.tokens[temp_pos][1] == "(":
                    return self.function_definition()

            return self.statement()

        return self.statement()

    def function_definition(self):
        func_node = Node("Function")

        return_type = []
        while self.current()[1] in ("const", "static", "virtual"):
            return_type.append(self.current()[1])
            self.next()

        return_type.append(self.current()[1])
        func_node.add(Node("ReturnType", " ".join(return_type)))
        self.next()

        func_node.add(Node("FuncName", self.current()[1]))
        self.next()

        self.match(value_="(")
        params_node = Node("Parameters")

        current_type = None
        while self.current()[1] != ")" and self.current()[0] != "EOF":
            t_type, t_value = self.current()

            if t_type == "KEYWORDS" and t_value in (
                "int", "float", "double", "char", "bool", "void", "auto",
                "const", "static", "virtual"
            ):
                current_type = t_value
                self.next()

            elif t_type == "IDENTIFIER":
                params_node.add(Node("Param", t_value, param_type=current_type))
                current_type = None
                self.next()

            elif t_value == ",":
                self.next()

            else:
                self.next()

        func_node.add(params_node)
        self.match(value_=")")

        if self.current()[1] == "{":
            func_node.add(self.block())

        return func_node

    def statement(self):
        t_type, value = self.current()

        if t_type == "PREPROCESSOR":
            self.next()
            return Node("Preprocessor", value)

        if value == "{":
            return self.block()
        elif value == "if":
            return self.if_stmt()
        elif value == "while":
            return self.while_stmt()
        elif value == "for":
            return self.for_stmt()
        elif value == "do":
            return self.do_while()
        elif value == "switch":
            return self.switch_stmt()
        elif value == "try":
            return self.try_catch()
        elif value in ("int", "float", "double", "char", "bool", "void", "auto"):
            return self.declaration()
        elif value in ("class", "struct"):
            return self.class_def()
        elif value == "namespace":
            return self.namespace_def()
        elif value == "template":
            return self.template_def()
        elif value == "return":
            return self.return_stmt()
        elif value in ("break", "continue"):
            node = Node(value.capitalize())
            self.next()
            if self.current()[1] == ";":
                self.next()
            return node
        elif value == ";":
            self.next()
            return Node("Empty")
        else:
            return self.expr_stmt()

    def block(self):
        node = Node("Block")
        self.match(value_="{")

        while self.current()[0] != "EOF" and self.current()[1] != "}":
            node.add(self.statement())

        if self.current()[1] == "}":
            self.match(value_="}")

        return node

    def if_stmt(self):
        node = Node("If")
        self.match(value_="if")
        self.match(value_="(")
        node.add(Node("Condition", self.expression()))
        self.match(value_=")")

        then_node = Node("Then")
        if self.current()[1] == "{":
            then_node.add(self.block())
        else:
            then_node.add(self.statement())
        node.add(then_node)

        if self.current()[1] == "else":
            self.next()
            else_node = Node("Else")
            if self.current()[1] == "if":
                else_node.add(self.if_stmt())
            elif self.current()[1] == "{":
                else_node.add(self.block())
            else:
                else_node.add(self.statement())
            node.add(else_node)

        return node

    def while_stmt(self):
        node = Node("While")
        self.match(value_="while")
        self.match(value_="(")
        node.add(Node("Condition", self.expression()))
        self.match(value_=")")
        node.add(self.statement())
        return node

    def for_stmt(self):
        node = Node("For")
        self.match(value_="for")
        self.match(value_="(")
        node.add(Node("Init", self.expression()))
        self.match(value_=";")
        node.add(Node("Condition", self.expression()))
        self.match(value_=";")
        node.add(Node("Iter", self.expression()))
        self.match(value_=")")
        node.add(self.statement())
        return node

    def do_while(self):
        node = Node("DoWhile")
        self.match(value_="do")
        node.add(self.statement())
        self.match(value_="while")
        self.match(value_="(")
        node.add(Node("Condition", self.expression()))
        self.match(value_=")")
        self.match(value_=";")
        return node

    def switch_stmt(self):
        node = Node("Switch")
        self.match(value_="switch")
        self.match(value_="(")
        node.add(Node("Expression", self.expression()))
        self.match(value_=")")
        self.match(value_="{")

        while self.current()[1] != "}" and self.current()[0] != "EOF":
            if self.current()[1] == "case":
                case_node = Node("Case")
                self.next()
                case_node.add(Node("Value", self.expression()))
                self.match(value_=":")
                while self.current()[1] not in ("case", "default", "}") and self.current()[0] != "EOF":
                    case_node.add(self.statement())
                node.add(case_node)
            elif self.current()[1] == "default":
                def_node = Node("Default")
                self.next()
                self.match(value_=":")
                while self.current()[1] not in ("case", "}") and self.current()[0] != "EOF":
                    def_node.add(self.statement())
                node.add(def_node)
            else:
                node.add(self.statement())

        self.match(value_="}")
        return node

    def try_catch(self):
        node = Node("TryCatch")
        self.match(value_="try")
        node.add(self.block())

        while self.current()[1] == "catch":
            catch_node = Node("Catch")
            self.next()
            self.match(value_="(")
            while self.current()[1] != ")":
                self.next()
            self.match(value_=")")
            catch_node.add(self.block())
            node.add(catch_node)

        return node

    def declaration(self):
        var_type = self.current()[1]
        node = Node("Declaration", var_type)
        self.next()

        while True:
            if self.current()[0] == "IDENTIFIER":
                var_node = Node("VarName", self.current()[1])

                if self.peek_next()[1] == "=":
                    self.next()
                    self.next()
                    var_node.add(Node("Value", self.expression()))
                    node.add(var_node)
                else:
                    self.next()
                    node.add(var_node)

                if self.current()[1] == ",":
                    self.next()
                    continue
                else:
                    break
            else:
                break

        if self.current()[1] == ";":
            self.next()

        return node

    def class_def(self):
        node = Node("Class", self.current()[1])
        self.next()

        if self.current()[0] == "IDENTIFIER":
            node.add(Node("Name", self.current()[1]))
            self.next()

        if self.current()[1] == ":":
            self.next()
            while self.current()[1] != "{" and self.current()[0] != "EOF":
                self.next()

        if self.current()[1] == "{":
            self.next()
            while self.current()[1] != "}" and self.current()[0] != "EOF":
                if self.current()[1] in ("public", "private", "protected"):
                    access = Node("Access", self.current()[1])
                    self.next()
                    self.match(value_=":")
                    node.add(access)
                else:
                    node.add(self.statement())
            self.match(value_="}")

        if self.current()[1] == ";":
            self.next()

        return node

    def namespace_def(self):
        node = Node("Namespace")
        self.match(value_="namespace")
        if self.current()[0] == "IDENTIFIER":
            node.add(Node("Name", self.current()[1]))
            self.next()
        node.add(self.block())
        return node

    def template_def(self):
        node = Node("Template")
        self.match(value_="template")
        self.match(value_="<")
        while self.current()[1] != ">" and self.current()[0] != "EOF":
            self.next()
        self.match(value_=">")
        node.add(self.statement())
        return node

    def return_stmt(self):
        node = Node("Return")
        self.match(value_="return")
        if self.current()[1] != ";":
            node.add(Node("Value", self.expression()))
        self.match(value_=";")
        return node

    def expr_stmt(self):
        expr = self.expression()
        node = Node("ExprStmt", expr if expr else "empty")
        if self.current()[1] == ";":
            self.next()
        return node

    def expression(self):
        parts = []
        depth = 0

        while self.current()[0] != "EOF":
            t_type, value = self.current()

            if value in (";", "}", ")", ":", ",") and depth == 0:
                break

            if value in ("(", "[", "{"):
                depth += 1
            elif value in (")", "]", "}"):
                depth -= 1
                if depth < 0:
                    break

            parts.append(value)
            self.next()

        return " ".join(parts) if parts else None