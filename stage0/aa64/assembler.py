"""The ArmOS AArch64 assembler: assembly text -> an in-memory object (sections,
symbols, relocations) for the linker.

Supports the GNU-style syntax the DULL compiler and the boot code use.
"""

import re

from .encode import AsmError, Encoder

NOP = 0xD503201F


class Section:
    def __init__(self, name, code, nobits):
        self.name = name
        self.code = code
        self.nobits = nobits
        self.data = bytearray()
        self.size = 0          # also counts .bss bytes, which have no data
        self.align = 4 if code else 1
        self.relocs = []       # (offset, kind, symbol, addend, line)


class Symbol:
    def __init__(self, name, section, value):
        self.name = name
        self.section = section     # None: absolute constant
        self.value = value
        self.is_global = False


class Object:
    def __init__(self, path):
        self.path = path
        self.sections = {}
        self.symbols = {}
        self.aliases = {}          # name -> other symbol name (.set a, b)
        self.globals = set()


def section_kind(name, flags=None):
    code = name == ".text" or name.startswith(".text.") or (flags is not None and "x" in flags)
    nobits = name == ".bss" or name.startswith(".bss.")
    return code, nobits


# ---------------------------------------------------------------- text helpers

def strip_comment(line):
    out = []
    in_str = False
    i = 0
    while i < len(line):
        c = line[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < len(line):
                out.append(line[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif line.startswith("//", i):
                break
            out.append(c)
        i += 1
    return "".join(out).strip()


def split_operands(text):
    """Split on commas that are not inside [ ], ( ) or a string."""
    ops, depth, cur, in_str = [], 0, [], False
    for c in text:
        if in_str:
            cur.append(c)
            if c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c in "[(":
            depth += 1
        elif c in "])":
            depth -= 1
        if c == "," and depth == 0:
            ops.append("".join(cur).strip())
            cur = []
        else:
            cur.append(c)
    if "".join(cur).strip():
        ops.append("".join(cur).strip())
    return ops


ESC = {"n": 10, "t": 9, "r": 13, "0": 0, "\\": 92, '"': 34, "'": 39, "a": 7, "b": 8, "f": 12, "v": 11}


def parse_string(text):
    t = text.strip()
    if len(t) < 2 or t[0] != '"' or t[-1] != '"':
        raise AsmError(f"expected a quoted string, found {text!r}")
    body = t[1:-1]
    out = bytearray()
    i = 0
    while i < len(body):
        c = body[i]
        if c != "\\":
            out += c.encode("utf-8")
            i += 1
            continue
        e = body[i + 1]
        if e == "x":
            j = i + 2
            while j < len(body) and body[j] in "0123456789abcdefABCDEF":
                j += 1
            out.append(int(body[i + 2:j], 16) & 0xFF)
            i = j
        elif e in "01234567" and e != "0" or (e == "0" and i + 2 < len(body) and body[i + 2] in "01234567"):
            j = i + 1
            while j < len(body) and j < i + 4 and body[j] in "01234567":
                j += 1
            out.append(int(body[i + 1:j], 8) & 0xFF)
            i = j
        else:
            out.append(ESC[e])
            i += 2
    return bytes(out)


SYM_RE = re.compile(r"^[A-Za-z_.$][A-Za-z0-9_.$]*$")
NUMLABEL_DEF = re.compile(r"^(\d+):")
NUMLABEL_REF = re.compile(r"(?<![\w#.$])(\d+)([bf])(?![\w.$])")


class Expr:
    """Tiny expression evaluator: integers, constants, + - * / % << >> & | ^ ~ ( )."""

    TOK = re.compile(r"\s*(0[xX][0-9a-fA-F_]+|0[bB][01_]+|\d[\d_]*|<<|>>|[A-Za-z_.$][\w.$]*|.)")

    def __init__(self, text, consts):
        self.toks = [t for t in self.TOK.findall(text) if t.strip()]
        self.i = 0
        self.consts = consts

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else None

    def take(self):
        t = self.peek()
        self.i += 1
        return t

    def parse(self):
        v = self.binop(0)
        if self.peek() is not None:
            raise AsmError(f"unexpected {self.peek()!r} in expression")
        return v

    LEVELS = [["|"], ["^"], ["&"], ["<<", ">>"], ["+", "-"], ["*", "/", "%"]]

    def binop(self, lvl):
        if lvl == len(self.LEVELS):
            return self.unary()
        v = self.binop(lvl + 1)
        while self.peek() in self.LEVELS[lvl]:
            op = self.take()
            r = self.binop(lvl + 1)
            v = {"|": v | r, "^": v ^ r, "&": v & r, "<<": v << r, ">>": v >> r, "+": v + r,
                 "-": v - r, "*": v * r, "/": int(v / r) if r else 0, "%": v % r if r else 0}[op]
        return v

    def unary(self):
        t = self.take()
        if t is None:
            raise AsmError("expression ends too early")
        if t == "-":
            return -self.unary()
        if t == "~":
            return ~self.unary()
        if t == "+":
            return self.unary()
        if t == "(":
            v = self.binop(0)
            if self.take() != ")":
                raise AsmError("missing )")
            return v
        if t[0].isdigit():
            t = t.replace("_", "")
            if t[:2].lower() == "0x":
                return int(t, 16)
            if t[:2].lower() == "0b":
                return int(t[2:], 2)
            return int(t, 10)
        if t in self.consts:
            return self.consts[t]
        raise AsmError(f"{t!r} is not a constant")


# ---------------------------------------------------------------- the assembler

class Assembler:
    def __init__(self, path):
        self.obj = Object(path)
        self.consts = {}
        self.sec = None
        self.lineno = 0
        self.pass_no = 1

    def err(self, msg):
        return AsmError(f"{self.obj.path}:{self.lineno}: {msg}")

    # ---- preprocessing: .rept and numeric labels
    def preprocess(self, text):
        raw = text.replace("\r\n", "\n").split("\n")
        lines = []
        stack = []
        for n, line in enumerate(raw, start=1):
            s = strip_comment(line)
            low = s.lower()
            if low.startswith(".rept"):
                count = Expr(s[5:], self.consts).parse()
                stack.append((count, []))
                continue
            if low.startswith(".endr"):
                if not stack:
                    raise AsmError(f"{self.obj.path}:{n}: .endr without .rept")
                count, body = stack.pop()
                target = stack[-1][1] if stack else lines
                for _ in range(count):
                    target.extend(body)
                continue
            (stack[-1][1] if stack else lines).append((n, s))
        if stack:
            raise AsmError(f"{self.obj.path}: .rept without .endr")
        # numeric local labels -> unique names
        defs = {}
        for idx, (n, s) in enumerate(lines):
            m = NUMLABEL_DEF.match(s)
            if m:
                defs.setdefault(m.group(1), []).append(idx)
        out = []
        for idx, (n, s) in enumerate(lines):
            m = NUMLABEL_DEF.match(s)
            if m:
                k = defs[m.group(1)].index(idx)
                s = f".Lnum{m.group(1)}_{k}:" + s[m.end():]

            def ref(mm, idx=idx, n=n):
                num, d = mm.group(1), mm.group(2)
                cand = defs.get(num, [])
                if d == "b":
                    before = [i for i in cand if i <= idx]
                    if not before:
                        raise AsmError(f"{self.obj.path}:{n}: no label {num}: before here")
                    return f".Lnum{num}_{cand.index(before[-1])}"
                after = [i for i in cand if i > idx]
                if not after:
                    raise AsmError(f"{self.obj.path}:{n}: no label {num}: after here")
                return f".Lnum{num}_{cand.index(after[0])}"

            # Rewrite `1b` / `1f` in an instruction's operands (after any leading labels).
            labels = ""
            body = s
            while True:
                lm = re.match(r"^([A-Za-z_.$][\w.$]*)\s*:(?!:)\s*", body)
                if not lm:
                    break
                labels += body[:lm.end()]
                body = body[lm.end():]
            parts = body.split(None, 1)
            if len(parts) == 2 and not parts[0].startswith("."):
                body = parts[0] + " " + NUMLABEL_REF.sub(ref, parts[1])
            out.append((n, (labels + " " + body).strip()))
        return out

    # ---- sections and symbols
    def switch(self, name, flags=None):
        if name not in self.obj.sections:
            code, nobits = section_kind(name, flags)
            self.obj.sections[name] = Section(name, code, nobits)
        self.sec = self.obj.sections[name]

    def here(self):
        return self.sec.size

    def define(self, name):
        if self.pass_no == 1:
            if name in self.obj.symbols or name in self.consts:
                raise self.err(f"`{name}` is defined twice")
            self.obj.symbols[name] = Symbol(name, self.sec, self.here())
        else:
            sym = self.obj.symbols[name]
            if sym.value != self.here() or sym.section is not self.sec:
                raise self.err(f"`{name}` moved between passes")

    # ---- emitting
    def emit(self, data):
        if self.sec.nobits:
            if any(data):
                raise self.err("cannot put data in .bss")
            self.sec.size += len(data)
            return
        if self.pass_no == 2:
            self.sec.data += data
        self.sec.size += len(data)

    def emit_word(self, word):
        self.emit((word & 0xFFFFFFFF).to_bytes(4, "little"))

    # ---- encoder context
    def imm(self, text):
        return Expr(text, self.consts).parse()

    def reloc(self, kind, text):
        t = text.strip()
        m = re.match(r"^([A-Za-z_.$][\w.$]*)\s*(?:([+-])\s*(.+))?$", t)
        if not m:
            raise self.err(f"expected a symbol, found {text!r}")
        name = m.group(1)
        addend = 0
        if m.group(2):
            addend = self.imm(m.group(3)) * (1 if m.group(2) == "+" else -1)
        if name in self.consts and kind not in ("abs64", "abs32"):
            raise self.err(f"`{name}` is a constant, not an address")
        if self.pass_no == 2:
            self.sec.relocs.append((self.here(), kind, name, addend, self.lineno))
        return 0

    # ---- one statement
    def statement(self, s):
        while True:
            m = re.match(r"^([A-Za-z_.$][\w.$]*)\s*:(?!:)", s)
            if not m:
                break
            if self.sec is None:
                self.switch(".text")
            self.define(m.group(1))
            s = s[m.end():].strip()
        if not s:
            return
        parts = s.split(None, 1)
        word = parts[0]
        rest = parts[1] if len(parts) > 1 else ""
        if word.startswith("."):
            return self.directive(word.lower(), rest)
        if self.sec is None:
            self.switch(".text")
        if not self.sec.code:
            raise self.err(f"instruction `{word}` outside a code section")
        if self.sec.size % 4:
            raise self.err("instruction is not 4-byte aligned")
        word_value = 0
        if self.pass_no == 2:
            word_value = Encoder(self).encode(word, split_operands(rest))
        self.emit_word(word_value)

    def directive(self, d, rest):
        ops = split_operands(rest)
        if d in (".text", ".data", ".bss"):
            return self.switch(d)
        if d == ".section":
            name = ops[0]
            flags = parse_string(ops[1]).decode() if len(ops) > 1 and ops[1].startswith('"') else None
            return self.switch(name, flags)
        if d in (".global", ".globl"):
            for o in ops:
                self.obj.globals.add(o)
            return
        if d in (".type", ".size", ".file", ".ident", ".cfi_startproc", ".cfi_endproc", ".p2alignl"):
            return
        if d in (".set", ".equ"):
            name, value = ops[0], ops[1]
            if SYM_RE.match(value) and not value[0].isdigit():
                try:
                    v = self.imm(value)
                except AsmError:
                    self.obj.aliases[name] = value
                    return
                self.consts[name] = v
                return
            if self.pass_no == 1:
                self.consts[name] = self.imm(value)
            return
        if self.sec is None:
            self.switch(".text")
        if d in (".balign", ".p2align", ".align"):
            n = self.imm(ops[0])
            if d in (".p2align", ".align"):
                n = 1 << n
            if n & (n - 1):
                raise self.err(".balign needs a power of two")
            self.sec.align = max(self.sec.align, n)
            pad = (-self.here()) % n
            if self.sec.code and len(ops) == 1:
                lead = pad % 4
                self.emit(bytes(lead))
                for _ in range(pad // 4):
                    self.emit_word(NOP)
            else:
                fill = self.imm(ops[1]) & 0xFF if len(ops) > 1 else 0
                self.emit(bytes([fill]) * pad)
            return
        sizes = {".byte": 1, ".hword": 2, ".short": 2, ".2byte": 2, ".word": 4, ".long": 4, ".4byte": 4,
                 ".xword": 8, ".quad": 8, ".dword": 8, ".8byte": 8}
        if d in sizes:
            size = sizes[d]
            for o in ops:
                o = o.strip()
                try:
                    v = self.imm(o)
                except AsmError:
                    if size not in (4, 8):
                        raise
                    self.reloc("abs64" if size == 8 else "abs32", o)
                    v = 0
                self.emit((v & ((1 << (8 * size)) - 1)).to_bytes(size, "little"))
            return
        if d in (".zero", ".space", ".skip"):
            n = self.imm(ops[0])
            fill = self.imm(ops[1]) & 0xFF if len(ops) > 1 else 0
            self.emit(bytes([fill]) * n)
            return
        if d in (".ascii", ".asciz", ".string"):
            for o in ops:
                b = parse_string(o)
                self.emit(b + (b"\0" if d != ".ascii" else b""))
            return
        raise self.err(f"unknown directive `{d}`")

    # ---- driver
    def run(self, text):
        lines = self.preprocess(text)
        for self.pass_no in (1, 2):
            for sec in self.obj.sections.values():
                sec.size = 0
                sec.data = bytearray()
                sec.relocs = []
            self.sec = None
            if self.pass_no == 2:
                self.consts = dict(self.consts)
            for self.lineno, s in lines:
                try:
                    self.statement(s)
                except AsmError as e:
                    msg = str(e)
                    if not msg.startswith(self.obj.path + ":"):
                        msg = f"{self.obj.path}:{self.lineno}: {msg}"
                    raise AsmError(msg) from None
        for name in self.obj.globals:
            if name in self.obj.symbols:
                self.obj.symbols[name].is_global = True
        return self.obj


def assemble(text, path="<asm>"):
    return Assembler(path).run(text)
