"""Text dumps of the stage-0 compiler's intermediate results, in the formats the
DULL-written compiler prints, so tests/selfhost_compare.py can compare them."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "stage0"))

from dullc.lexer import DullError, tokenize  # noqa: E402
from dullc.parser import parse  # noqa: E402


def tokens(path):
    with open(path, encoding="utf-8") as f:
        src = f.read()
    try:
        toks = tokenize(src, os.path.basename(path))
    except DullError as e:
        return f"error: {e}\n"
    out = []
    for t in toks:
        line = f"{t.line} {t.kind}"
        if t.kind in ("INT", "CHAR"):
            line += f" {t.value}"
        elif t.kind == "STR":
            line += " " + t.value.hex()
        elif t.kind in ("NAME", "KW", "SYM"):
            line += f" {t.value}"
        out.append(line)
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- syntax trees

def w(s):
    if isinstance(s, str):
        s = s.encode("utf-8")
    return '"' + s.hex() + '"'


def ch(x):
    return "-" if x is None else dump(x)


def lst(xs, f=None):
    if xs is None:
        return "-"
    return "[" + " ".join((f or dump)(x) for x in xs) + "]"


def param(line, name, ty):
    return f"(param {line} {w(name)} {ch(ty)})"


def dump(n):
    k = n.kind
    head = f"({k} {n.line}"
    if k == "file":
        body = [w(n.path), lst(n.decls)]
    elif k == "use":
        body = [w(n.module), w(n.alias)]
    elif k in ("fixed", "new"):
        body = [w(n.name), ch(n.type), ch(n.value)]
    elif k == "global":
        body = [w(n.name), ch(n.type), ch(n.value), "1" if getattr(n, "elsewhere", False) else "0"]
    elif k == "shape":
        body = [w(n.name), lst(n.fields, lambda f: param(f[2], f[0], f[1]))]
    elif k == "choice":
        body = [w(n.name), lst(n.variants, lambda v: param(v[1], v[0], None))]
    elif k == "device":
        body = [w(n.name), ch(n.base), lst(n.regs)]
    elif k == "reg":
        body = [w(n.name), ch(n.offset), ch(n.type),
                lst(n.fields, lambda f: f"(bitfield {f[3]} {w(f[0])} {ch(f[1])} {ch(f[2])})")]
    elif k == "func":
        body = [w(n.name), ch(n.ret), lst(n.params, lambda p: param(p[2], p[0], p[1])), lst(n.body),
                "1" if getattr(n, "elsewhere", False) else "0"]
    elif k in ("t_ptr", "t_span", "t_maybe"):
        body = [ch(n.inner)]
    elif k == "t_array":
        body = [ch(n.count), ch(n.inner)]
    elif k == "t_name":
        body = [w(n.name), w(n.module) if n.module is not None else "-"]
    elif k == "while":
        body = [ch(n.cond), lst(n.body)]
    elif k == "repeat":
        body = [lst(n.body)]
    elif k == "hold":
        body = [ch(n.cond)]
    elif k == "give":
        body = [ch(n.value)]
    elif k in ("stop", "skip"):
        body = []
    elif k == "after":
        body = [ch(n.expr)]
    elif k == "stream":
        body = [ch(n.chain)]
    elif k == "expr_stmt":
        body = [ch(n.expr)]
    elif k == "asm":
        body = ["[" + " ".join(w(line) for line in n.lines) + "]"]
    elif k == "if":
        body = [lst(n.arms, lambda a: f"(arm {n.line} {ch(a[0])} {lst(a[1])})"), lst(n.otherwise)]
    elif k == "for_range":
        body = [w(n.var), "1" if n.inclusive else "0", ch(n.start), ch(n.end), lst(n.body)]
    elif k == "for_each":
        body = [w(n.var), ch(n.seq), lst(n.body)]
    elif k == "assign":
        body = [w(n.op), ch(n.target), ch(n.value)]
    elif k in ("binary", "compare", "logic"):
        body = [w(n.op), ch(n.left), ch(n.right)]
    elif k == "int":
        body = [str(n.value), "1" if getattr(n, "char", False) else "0"]
    elif k == "str":
        body = [w(n.value)]
    elif k == "name":
        body = [w(n.name)]
    elif k == "bool":
        body = ["1" if n.value else "0"]
    elif k == "nothing":
        body = []
    elif k == "array_lit":
        body = [lst(n.items)]
    elif k == "call":
        body = [ch(n.func), lst(n.args), "1" if getattr(n, "piped", False) else "0"]
    elif k == "index":
        body = [ch(n.value), ch(n.index)]
    elif k == "cast":
        body = [ch(n.value), ch(n.to)]
    elif k == "bits":
        body = [ch(n.value), ch(n.hi), ch(n.lo)]
    elif k == "slice":
        body = [ch(n.value), ch(n.lo), ch(n.hi)]
    elif k == "field":
        body = [w(n.name), ch(n.value)]
    elif k == "unary":
        body = [w(n.op), ch(n.operand)]
    elif k in ("deref", "addr_of"):
        body = [ch(n.operand)]
    elif k == "size_of":
        body = [ch(n.of)]
    elif k == "unwrap":
        body = [w(n.action), ch(n.value), ch(n.fallback)]
    else:
        raise ValueError(f"no dump for {k}")
    return head + "".join(" " + b for b in body) + ")"


def tree(path):
    with open(path, encoding="utf-8") as f:
        src = f.read()
    try:
        t = parse(src, os.path.basename(path))
    except DullError as e:
        return f"error: {e}\n"
    return dump(t) + "\n"
