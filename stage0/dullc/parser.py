"""Parser for DULL: tokens -> AST.

Every AST node is a `Node` with a `kind` string, a `line`, and kind-specific fields.
"""

from .lexer import DullError, tokenize


class Node:
    def __init__(self, kind, line, **fields):
        self.kind = kind
        self.line = line
        self.ty = None
        self.__dict__.update(fields)

    def __repr__(self):
        items = {k: v for k, v in self.__dict__.items() if k not in ("kind", "line", "ty")}
        return f"{self.kind}{items}"


ASSIGN_OPS = {"=", "+=", "-=", "*=", "/=", "&=", "|=", "^=", "<<=", ">>="}

# Binary precedence, low to high. `and`/`or`/`else`/`->` are handled separately.
BINARY_LEVELS = [
    ["|"],
    ["^"],
    ["&"],
    ["<<", ">>"],
    ["+", "-", "+%", "-%", "+|", "-|"],
    ["*", "/", "%", "*%"],
]
COMPARE = {"<", ">", "<=", ">="}


class Parser:
    def __init__(self, src, file):
        self.file = file
        self.toks = tokenize(src, file)
        self.pos = 0

    # ---- token helpers ----
    @property
    def tok(self):
        return self.toks[self.pos]

    def peek(self, n=1):
        return self.toks[min(self.pos + n, len(self.toks) - 1)]

    def err(self, msg, line=None):
        raise DullError(msg, self.file, line if line is not None else self.tok.line)

    def at(self, kind, value=None):
        t = self.tok
        return t.kind == kind and (value is None or t.value == value)

    def at_kw(self, word):
        return self.at("KW", word)

    def at_sym(self, s):
        return self.at("SYM", s)

    def take(self):
        t = self.tok
        self.pos += 1
        return t

    def expect(self, kind, value=None, what=None):
        if not self.at(kind, value):
            want = what or (repr(value) if value is not None else kind.lower())
            got = self.tok.value if self.tok.value is not None else self.tok.kind.lower()
            self.err(f"expected {want}, found {got!r}")
        return self.take()

    def expect_name(self, what="a name"):
        return self.expect("NAME", what=what).value

    def expect_newline(self):
        if self.at("EOF"):
            return
        self.expect("NEWLINE", what="end of line")

    # ---- file ----
    def parse_file(self):
        decls = []
        while not self.at("EOF"):
            if self.at("NEWLINE"):
                self.take()
                continue
            decls.append(self.top_decl())
        return Node("file", 1, decls=decls, path=self.file)

    def top_decl(self):
        t = self.tok
        if t.kind == "KW":
            if t.value == "use":
                return self.use_decl()
            if t.value == "fixed":
                return self.fixed_decl()
            if t.value == "new":
                n = self.new_stmt()
                n.kind = "global"
                return n
            if t.value == "shape":
                return self.shape_decl()
            if t.value == "choice":
                return self.choice_decl()
            if t.value == "device":
                return self.device_decl()
            if t.value == "to":
                return self.func_decl()
        self.err("expected a top-level declaration (to, new, fixed, shape, choice, device, use)")

    def use_decl(self):
        line = self.take().line
        name = self.expect_name("a module name")
        alias = name
        if self.at_kw("as"):
            self.take()
            alias = self.expect_name("a module alias")
        self.expect_newline()
        return Node("use", line, module=name, alias=alias)

    def fixed_decl(self):
        line = self.take().line
        name = self.expect_name()
        ty = None
        if not self.at_sym("="):
            ty = self.type_expr()
        self.expect("SYM", "=")
        value = self.expr()
        self.expect_newline()
        return Node("fixed", line, name=name, type=ty, value=value)

    def shape_decl(self):
        line = self.take().line
        name = self.expect_name("a shape name")
        self.expect_newline()
        self.expect("INDENT", what="indented fields")
        fields = []
        while not self.at("DEDENT"):
            fline = self.tok.line
            fname = self.expect_name("a field name")
            fty = self.type_expr()
            self.expect_newline()
            fields.append((fname, fty, fline))
        self.take()
        return Node("shape", line, name=name, fields=fields)

    def choice_decl(self):
        line = self.take().line
        name = self.expect_name("a choice name")
        self.expect_newline()
        self.expect("INDENT", what="indented variants")
        variants = []
        while not self.at("DEDENT"):
            vline = self.tok.line
            vname = self.expect_name("a variant name")
            if self.at_sym("("):
                self.err("choices carrying data are not supported by the stage-0 compiler")
            self.expect_newline()
            variants.append((vname, vline))
        self.take()
        return Node("choice", line, name=name, variants=variants)

    def device_decl(self):
        line = self.take().line
        name = self.expect_name("a device name")
        self.expect("KW", "at")
        base = self.expr()
        self.expect_newline()
        regs = []
        self.expect("INDENT", what="indented registers")
        while not self.at("DEDENT"):
            rline = self.tok.line
            rname = self.expect_name("a register name")
            self.expect("KW", "at")
            offset = self.expr()
            rty = self.type_expr()
            self.expect_newline()
            fields = []
            if self.at("INDENT"):
                self.take()
                while not self.at("DEDENT"):
                    fl = self.tok.line
                    fname = self.expect_name("a field name")
                    self.expect("KW", "is")
                    which = self.expect_name("bit or bits")
                    if which == "bit":
                        hi = lo = self.expr()
                    elif which == "bits":
                        hi = self.expr_no_range()
                        self.expect("SYM", ":")
                        lo = self.expr()
                    else:
                        self.err("expected `bit N` or `bits H:L`")
                    self.expect_newline()
                    fields.append((fname, hi, lo, fl))
                self.take()
            regs.append(Node("reg", rline, name=rname, offset=offset, type=rty, fields=fields))
        self.take()
        return Node("device", line, name=name, base=base, regs=regs)

    def func_decl(self):
        line = self.take().line
        name = self.expect_name("a function name")
        params = []
        if self.at_sym("("):
            self.take()
            if not self.at_sym(")"):
                while True:
                    pline = self.tok.line
                    pname = self.expect_name("a parameter name")
                    pty = self.type_expr()
                    params.append((pname, pty, pline))
                    if self.at_sym(","):
                        self.take()
                        continue
                    break
            self.expect("SYM", ")")
        ret = None
        if self.at_kw("gives"):
            self.take()
            ret = self.type_expr()
        self.expect_newline()
        body = self.block()
        return Node("func", line, name=name, params=params, ret=ret, body=body)

    # ---- types ----
    def type_expr(self):
        t = self.tok
        if t.kind == "KW" and t.value in ("ptr", "span", "maybe"):
            self.take()
            return Node("t_" + t.value, t.line, inner=self.type_expr())
        if t.kind == "KW" and t.value == "fix":
            self.err("fixed-point types are not supported by the stage-0 compiler")
        if self.at_sym("["):
            self.take()
            count = self.expr()
            self.expect("SYM", "]")
            return Node("t_array", t.line, count=count, inner=self.type_expr())
        if t.kind == "INT" and self.peek().kind == "KW" and self.peek().value == "lanes":
            self.err("lane types are not supported by the stage-0 compiler")
        if t.kind == "NAME":
            self.take()
            if self.at_sym("."):
                self.take()
                member = self.expect_name("a type name")
                return Node("t_name", t.line, module=t.value, name=member)
            return Node("t_name", t.line, module=None, name=t.value)
        self.err("expected a type")

    # ---- statements ----
    def block(self):
        self.expect("INDENT", what="an indented block")
        stmts = []
        while not self.at("DEDENT") and not self.at("EOF"):
            stmts.append(self.stmt())
        self.expect("DEDENT")
        return stmts

    def stmt(self):
        t = self.tok
        if t.kind == "KW":
            v = t.value
            if v == "new":
                return self.new_stmt()
            if v == "if":
                return self.if_stmt()
            if v == "while":
                self.take()
                cond = self.expr()
                self.expect_newline()
                return Node("while", t.line, cond=cond, body=self.block())
            if v == "repeat":
                self.take()
                self.expect_newline()
                return Node("repeat", t.line, body=self.block())
            if v == "hold":
                self.take()
                self.expect("KW", "until")
                cond = self.expr()
                self.expect_newline()
                return Node("hold", t.line, cond=cond)
            if v == "for":
                return self.for_stmt()
            if v == "give":
                self.take()
                value = None
                if not self.at("NEWLINE") and not self.at("EOF"):
                    value = self.expr()
                self.expect_newline()
                return Node("give", t.line, value=value)
            if v in ("stop", "skip"):
                self.take()
                self.expect_newline()
                return Node(v, t.line)
            if v == "after":
                self.take()
                e = self.expr()
                self.expect_newline()
                return Node("after", t.line, expr=e)
            if v == "stream":
                self.take()
                e = self.expr()
                self.expect_newline()
                return Node("stream", t.line, chain=e)
            if v == "asm":
                return self.asm_stmt()
            if v == "on":
                self.err("`on core` is not supported by the stage-0 compiler")
        e = self.expr()
        if self.at("SYM") and self.tok.value in ASSIGN_OPS:
            op = self.take().value
            value = self.expr()
            self.expect_newline()
            return Node("assign", t.line, target=e, op=op, value=value)
        self.expect_newline()
        return Node("expr_stmt", t.line, expr=e)

    def new_stmt(self):
        line = self.take().line
        name = self.expect_name("a variable name")
        ty = None
        if not self.at_sym("=") and not self.at("NEWLINE"):
            ty = self.type_expr()
        value = None
        if self.at_sym("="):
            self.take()
            value = self.expr()
        if ty is None and value is None:
            self.err(f"`new {name}` needs a type or a value")
        self.expect_newline()
        return Node("new", line, name=name, type=ty, value=value)

    def if_stmt(self):
        line = self.take().line
        arms = []
        cond = self.expr()
        self.expect_newline()
        arms.append((cond, self.block()))
        otherwise = None
        while self.at_kw("else"):
            self.take()
            if self.at_kw("if"):
                self.take()
                c = self.expr()
                self.expect_newline()
                arms.append((c, self.block()))
                continue
            self.expect_newline()
            otherwise = self.block()
            break
        return Node("if", line, arms=arms, otherwise=otherwise)

    def for_stmt(self):
        line = self.take().line
        self.expect("KW", "each")
        var = self.expect_name("a loop variable")
        self.expect("KW", "in")
        start = self.expr()
        if self.at_kw("until") or self.at_kw("through"):
            inclusive = self.take().value == "through"
            end = self.expr()
            self.expect_newline()
            return Node("for_range", line, var=var, start=start, end=end,
                        inclusive=inclusive, body=self.block())
        self.expect_newline()
        return Node("for_each", line, var=var, seq=start, body=self.block())

    def asm_stmt(self):
        line = self.take().line
        lines = []
        if self.at("STR"):
            lines.append(self.take().value)
            self.expect_newline()
        else:
            self.expect_newline()
            self.expect("INDENT", what="indented asm lines")
            while not self.at("DEDENT"):
                lines.append(self.expect("STR", what="a quoted asm line").value)
                self.expect_newline()
            self.take()
        return Node("asm", line, lines=[b.decode("utf-8") for b in lines])

    # ---- expressions ----
    def expr(self):
        left = self.unwrap()
        while self.at_sym("->"):
            line = self.take().line
            target = self.postfix()
            if target.kind == "call":
                target.args.insert(0, left)
                target.piped = True
                left = target
            else:
                left = Node("call", line, func=target, args=[left], piped=True)
        return left

    def unwrap(self):
        e = self.logic_or()
        if self.at_kw("else"):
            line = self.take().line
            if self.at_kw("give"):
                self.take()
                value = None
                if not self.at("NEWLINE") and not self.at_sym(")"):
                    value = self.expr()
                return Node("unwrap", line, value=e, action="give", fallback=value)
            if self.at_kw("stop") or self.at_kw("skip"):
                return Node("unwrap", line, value=e, action=self.take().value, fallback=None)
            return Node("unwrap", line, value=e, action="value", fallback=self.logic_or())
        return e

    def logic_or(self):
        left = self.logic_and()
        while self.at_kw("or"):
            line = self.take().line
            left = Node("logic", line, op="or", left=left, right=self.logic_and())
        return left

    def logic_and(self):
        left = self.logic_not()
        while self.at_kw("and"):
            line = self.take().line
            left = Node("logic", line, op="and", left=left, right=self.logic_not())
        return left

    def logic_not(self):
        if self.at_kw("not"):
            line = self.take().line
            return Node("unary", line, op="not", operand=self.logic_not())
        return self.compare()

    def compare(self):
        left = self.binary(0)
        if self.at_kw("is"):
            line = self.take().line
            negate = False
            if self.at_kw("not"):
                self.take()
                negate = True
            right = self.binary(0)
            return Node("compare", line, op="!=" if negate else "==", left=left, right=right)
        if self.at("SYM") and self.tok.value in COMPARE:
            op = self.take().value
            line = self.tok.line
            return Node("compare", line, op=op, left=left, right=self.binary(0))
        return left

    def binary(self, level):
        if level == len(BINARY_LEVELS):
            return self.cast()
        left = self.binary(level + 1)
        while self.at("SYM") and self.tok.value in BINARY_LEVELS[level]:
            t = self.take()
            right = self.binary(level + 1)
            left = Node("binary", t.line, op=t.value, left=left, right=right)
        return left

    def cast(self):
        e = self.prefix()
        while self.at_kw("as"):
            line = self.take().line
            e = Node("cast", line, value=e, to=self.type_expr())
        return e

    def prefix(self):
        t = self.tok
        if t.kind == "SYM" and t.value in ("-", "~"):
            self.take()
            return Node("unary", t.line, op=t.value, operand=self.prefix())
        if t.kind == "KW" and t.value == "deref":
            self.take()
            return Node("deref", t.line, operand=self.prefix())
        if t.kind == "KW" and t.value == "addr":
            self.take()
            self.expect("KW", "of")
            return Node("addr_of", t.line, operand=self.prefix())
        if t.kind == "KW" and t.value == "not":
            self.take()
            return Node("unary", t.line, op="not", operand=self.prefix())
        return self.postfix()

    def expr_no_range(self):
        return self.binary(0)

    def postfix(self):
        e = self.primary()
        while True:
            if self.at_sym("("):
                line = self.take().line
                args = []
                if e.kind == "name" and e.name == "size_of":
                    args.append(self.type_expr())
                    self.expect("SYM", ")")
                    e = Node("size_of", line, of=args[0])
                    continue
                if not self.at_sym(")"):
                    while True:
                        args.append(self.expr())
                        if self.at_sym(","):
                            self.take()
                            continue
                        break
                self.expect("SYM", ")")
                e = Node("call", line, func=e, args=args)
            elif self.at_sym("["):
                line = self.take().line
                first = self.expr_no_range()
                if self.at_sym(":"):
                    self.take()
                    lo = self.expr_no_range()
                    self.expect("SYM", "]")
                    e = Node("bits", line, value=e, hi=first, lo=lo)
                elif self.at_kw("until"):
                    self.take()
                    hi = self.expr_no_range()
                    self.expect("SYM", "]")
                    e = Node("slice", line, value=e, lo=first, hi=hi)
                else:
                    self.expect("SYM", "]")
                    e = Node("index", line, value=e, index=first)
            elif self.at_sym("."):
                line = self.take().line
                name = self.expect_name("a field name")
                e = Node("field", line, value=e, name=name)
            else:
                return e

    def primary(self):
        t = self.tok
        if t.kind == "INT":
            self.take()
            return Node("int", t.line, value=t.value)
        if t.kind == "CHAR":
            self.take()
            return Node("int", t.line, value=t.value, char=True)
        if t.kind == "STR":
            self.take()
            return Node("str", t.line, value=t.value)
        if t.kind == "NAME":
            self.take()
            return Node("name", t.line, name=t.value)
        if t.kind == "KW":
            if t.value in ("true", "false"):
                self.take()
                return Node("bool", t.line, value=t.value == "true")
            if t.value == "nothing":
                self.take()
                return Node("nothing", t.line)
        if t.kind == "SYM" and t.value == "(":
            self.take()
            e = self.expr()
            self.expect("SYM", ")")
            return e
        if t.kind == "SYM" and t.value == "[":
            self.take()
            items = []
            if not self.at_sym("]"):
                while True:
                    items.append(self.expr())
                    if self.at_sym(","):
                        self.take()
                        continue
                    break
            self.expect("SYM", "]")
            return Node("array_lit", t.line, items=items)
        got = t.value if t.value is not None else t.kind.lower()
        self.err(f"expected an expression, found {got!r}")


def parse(src, file="<input>"):
    return Parser(src, file).parse_file()
