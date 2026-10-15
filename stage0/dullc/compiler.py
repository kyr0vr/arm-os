"""Stage-0 DULL compiler: type checking and naive AArch64 code generation.

Code generation is simple. Every expression leaves its value in x0 (or x0/x1 for
two-register values). The locals used most (weighted by loop depth) live in the
callee-saved registers x19-x28, the rest in the stack frame. Operands that are such a
local or a constant are used where they are; other intermediate values wait in x9-x15
while the rest of the expression has no call in it, and on the stack otherwise.
Functions that call nothing also keep locals in x6-x8 and x17. Comparisons in
conditions branch directly, and p[i] with p and i in registers is one load or store.
"""

import os
import re

from .lexer import DullError
from .parser import Node, parse
from . import dtypes as T

BUILTIN_VOID = {"dsb": "dsb sy", "dmb": "dmb sy", "isb": "isb",
                "wfe": "wfe", "wfi": "wfi", "sev": "sev"}
ENTRY_SYMBOL = "dull_main"
TRAP_SYMBOL = "dull_trap"
LOOP_KINDS = ("while", "repeat", "hold", "for_range", "for_each", "stream")
SPARE_REGS = 3          # registers left for loop counters; the rest may go to named locals
FIRST_REG = 19
LAST_REG = 28
LEAF_REGS = [6, 7, 8, 17]   # free in a function that calls nothing (and has no asm)
CONDS = {"==": ("eq", "eq"), "!=": ("ne", "ne"), "<": ("lo", "lt"), ">": ("hi", "gt"),
         "<=": ("ls", "le"), ">=": ("hs", "ge")}
INVERSE = {"eq": "ne", "ne": "eq", "lo": "hs", "hs": "lo", "hi": "ls", "ls": "hi",
           "lt": "ge", "ge": "lt", "gt": "le", "le": "gt"}


# --------------------------------------------------------------------------
# Symbols
# --------------------------------------------------------------------------

class Sym:
    def __init__(self, kind, name, module, node=None, **kw):
        self.kind = kind      # func global fixed shape choice device module
        self.name = name
        self.module = module
        self.node = node
        self.__dict__.update(kw)


class Local:
    def __init__(self, name, ty, offset, readonly=False):
        self.kind = "local"
        self.name, self.ty, self.offset, self.readonly = name, ty, offset, readonly
        self.reg = None


class Module:
    def __init__(self, name, path, ast):
        self.name = name
        self.path = path
        self.ast = ast
        self.syms = {}
        self.file = os.path.basename(path)


class Ref:
    """What a name or field chain resolved to."""

    def __init__(self, kind, **kw):
        self.kind = kind      # local global fixed func module device reg devfield choice_type
                              # variant shape_type builtin
        self.__dict__.update(kw)


# --------------------------------------------------------------------------
# Program: loads modules, declares symbols, drives code generation
# --------------------------------------------------------------------------

class Program:
    def __init__(self, include_dirs=(), debug=True):
        self.include_dirs = list(include_dirs)
        self.debug = debug
        self.modules = {}       # abspath -> Module
        self.by_name = {}       # module name -> Module
        self.out = []           # text section lines
        self.rodata = []
        self.data = []
        self.bss = []
        self.label_n = 0
        self.strings = {}       # bytes -> label
        self.strdata = []       # string bytes, kept apart so they never land inside an array

    # ---- errors / labels ----
    def label(self, stem="L"):
        self.label_n += 1
        return f".L{stem}{self.label_n}"

    def string_label(self, data, nul=False):
        key = (data, nul)
        if key not in self.strings:
            lab = self.label("str")
            self.strings[key] = lab
            body = data + (b"\0" if nul else b"")
            self.strdata.append(f"{lab}:")
            for i in range(0, max(len(body), 1), 16):
                chunk = body[i:i + 16]
                if chunk:
                    self.strdata.append("    .byte " + ", ".join(str(b) for b in chunk))
        return self.strings[key]

    # ---- loading ----
    def find_module(self, name, from_dir):
        for d in [from_dir] + self.include_dirs:
            p = os.path.join(d, name + ".dull")
            if os.path.isfile(p):
                return os.path.abspath(p)
        return None

    def load(self, path, line_ref=None):
        path = os.path.abspath(path)
        if path in self.modules:
            return self.modules[path]
        with open(path, encoding="utf-8") as f:
            src = f.read()
        ast = parse(src, os.path.basename(path))
        name = os.path.splitext(os.path.basename(path))[0]
        if name in self.by_name:
            raise DullError(f"two different modules are both called `{name}`")
        mod = Module(name, path, ast)
        self.modules[path] = mod
        self.by_name[name] = mod
        for d in ast.decls:
            if d.kind == "use":
                target = self.find_module(d.module, os.path.dirname(path))
                if target is None:
                    raise DullError(f"cannot find module `{d.module}`", mod.file, d.line)
                used = self.load(target)
                self.declare(mod, d.alias, Sym("module", d.alias, mod, d, target=used), d)
        return mod

    def declare(self, mod, name, sym, node):
        if name in mod.syms:
            raise DullError(f"`{name}` is declared twice", mod.file, node.line)
        mod.syms[name] = sym

    # ---- declaration pass ----
    def declare_all(self):
        for mod in self.modules.values():
            for d in mod.ast.decls:
                k = d.kind
                if k == "use":
                    continue
                outside = getattr(d, "elsewhere", False)
                if k == "func":
                    self.declare(mod, d.name, Sym("func", d.name, mod, d,
                                                  symbol=d.name if outside else f"{mod.name}.{d.name}"), d)
                elif k == "global":
                    self.declare(mod, d.name, Sym("global", d.name, mod, d,
                                                  symbol=d.name if outside else f"{mod.name}.{d.name}"), d)
                elif k == "fixed":
                    self.declare(mod, d.name, Sym("fixed", d.name, mod, d,
                                                  symbol=f"{mod.name}.{d.name}"), d)
                elif k == "shape":
                    self.declare(mod, d.name, Sym("shape", d.name, mod, d,
                                                  ty=T.Shape(d.name, f"{mod.name}.{d.name}")), d)
                elif k == "choice":
                    variants = {}
                    for i, (vn, vl) in enumerate(d.variants):
                        if vn in variants:
                            raise DullError(f"variant `{vn}` appears twice", mod.file, vl)
                        variants[vn] = i
                    self.declare(mod, d.name, Sym("choice", d.name, mod, d,
                                                  ty=T.Choice(d.name, f"{mod.name}.{d.name}", variants)), d)
                elif k == "device":
                    self.declare(mod, d.name, Sym("device", d.name, mod, d), d)
        # Resolve everything that does not depend on function bodies.
        for mod in self.modules.values():
            for sym in list(mod.syms.values()):
                if sym.kind == "shape":
                    self.layout_shape(sym)
        for mod in self.modules.values():
            for sym in list(mod.syms.values()):
                if sym.kind == "func":
                    self.resolve_sig(sym)
                elif sym.kind == "fixed":
                    self.resolve_fixed(sym)
                elif sym.kind == "device":
                    self.resolve_device(sym)
        for mod in self.modules.values():
            for sym in list(mod.syms.values()):
                if sym.kind == "global":
                    self.resolve_global(sym)

    def err(self, mod, node, msg):
        raise DullError(msg, mod.file, node.line)

    # ---- types ----
    def resolve_type(self, node, mod, allow_void=False):
        k = node.kind
        if k == "t_name":
            if node.module is None:
                n = node.name
                if n in T.INTS:
                    return T.INTS[n]
                if n == "bool":
                    return T.BOOL
                if n == "string":
                    return T.STRING()
                if n in ("f32", "f64"):
                    self.err(mod, node, "floats are not supported by the stage-0 compiler")
                sym = mod.syms.get(n)
            else:
                m = mod.syms.get(node.module)
                if m is None or m.kind != "module":
                    self.err(mod, node, f"unknown module `{node.module}`")
                sym = m.target.syms.get(node.name)
            if sym is None or sym.kind not in ("shape", "choice"):
                self.err(mod, node, f"unknown type `{node.name}`")
            if sym.kind == "shape":
                return sym.ty
            return sym.ty
        if k == "t_ptr":
            return T.Ptr(self.resolve_type(node.inner, mod))
        if k == "t_span":
            inner = self.resolve_type(node.inner, mod)
            if inner.repr == "mem" and isinstance(inner, T.Array):
                pass
            return T.Span(inner)
        if k == "t_maybe":
            inner = self.resolve_type(node.inner, mod)
            if not T.maybe_ok(inner):
                self.err(mod, node, f"the stage-0 compiler only supports `maybe` of numbers, "
                                    f"bools, choices and pointers (not `{inner}`); use `maybe ptr`")
            return T.Maybe(inner)
        if k == "t_array":
            n = self.const_eval(node.count, mod)
            if n is None or n <= 0:
                self.err(mod, node, "an array size must be a positive constant")
            return T.Array(self.resolve_type(node.inner, mod), n)
        self.err(mod, node, "bad type")

    def layout_shape(self, sym, stack=()):
        st = sym.ty
        if st.done:
            return
        if sym in stack:
            self.err(sym.module, sym.node, f"shape `{sym.name}` contains itself")
        off = 0
        align = 1
        for fname, fnode, fline in sym.node.fields:
            if fname in st.fields:
                raise DullError(f"field `{fname}` appears twice", sym.module.file, fline)
            fty = self.resolve_type(fnode, sym.module)
            inner = fty
            while isinstance(inner, T.Array):
                inner = inner.inner
            if isinstance(inner, T.Shape) and not inner.done:
                owner = self.shape_sym(inner)
                self.layout_shape(owner, stack + (sym,))
                fty = self.resolve_type(fnode, sym.module)
            a = max(fty.align, 1)
            off = (off + a - 1) // a * a
            st.fields[fname] = (fty, off)
            st.order.append(fname)
            off += fty.size
            align = max(align, a)
        st.size = max((off + align - 1) // align * align, 1)
        st.align = align
        st.done = True

    def shape_sym(self, ty):
        for mod in self.modules.values():
            for s in mod.syms.values():
                if s.kind == "shape" and s.ty is ty:
                    return s
        raise AssertionError("shape without symbol")

    def resolve_sig(self, sym):
        d = sym.node
        params = []
        seen = set()
        for pname, pty, pline in d.params:
            if pname in seen:
                raise DullError(f"parameter `{pname}` appears twice", sym.module.file, pline)
            seen.add(pname)
            t = self.resolve_type(pty, sym.module)
            if t.repr == "mem":
                raise DullError(f"`{t}` cannot be passed by value; pass a `ptr {t}`",
                                sym.module.file, pline)
            params.append((pname, t))
        ret = T.VOID
        if d.ret is not None:
            ret = self.resolve_type(d.ret, sym.module)
            if ret.repr == "mem":
                self.err(sym.module, d, f"`{ret}` cannot be given back by value; give a `ptr {ret}`")
        regs = sum(2 if t.repr == "pair" else 1 for _, t in params)
        if regs > 8:
            self.err(sym.module, d, "too many parameters (at most 8 registers' worth)")
        sym.params = params
        sym.ret = ret

    # ---- constants ----
    def const_eval(self, e, mod, scope_lookup=None):
        """Evaluate a constant expression to a Python int, or None if not constant."""
        k = e.kind
        if k == "int":
            return e.value
        if k == "bool":
            return 1 if e.value else 0
        if k == "size_of":
            return self.resolve_type(e.of, mod).size
        if k in ("name", "field"):
            ref = self.try_resolve_static(e, mod, scope_lookup)
            if ref is None:
                return None
            if ref.kind == "fixed" and ref.sym.const is not None:
                return ref.sym.const
            if ref.kind == "variant":
                return ref.value
            return None
        if k == "unary":
            v = self.const_eval(e.operand, mod, scope_lookup)
            if v is None:
                return None
            if e.op == "-":
                return -v
            if e.op == "~":
                return ~v
            return None
        if k == "cast":
            v = self.const_eval(e.value, mod, scope_lookup)
            if v is None:
                return None
            to = self.resolve_type(e.to, mod)
            if isinstance(to, T.Int):
                return wrap(v, to)
            if isinstance(to, T.Bool):
                return 1 if v else 0
            return None
        if k == "binary":
            a = self.const_eval(e.left, mod, scope_lookup)
            if a is None:
                return None
            b = self.const_eval(e.right, mod, scope_lookup)
            if b is None:
                return None
            op = {"+%": "+", "-%": "-", "*%": "*", "+|": "+", "-|": "-"}.get(e.op, e.op)
            if op == "+":
                r = a + b
            elif op == "-":
                r = a - b
            elif op == "*":
                r = a * b
            elif op == "/":
                if b == 0:
                    raise DullError("division by zero in a constant", mod.file, e.line)
                r = abs(a) // abs(b) * (1 if (a >= 0) == (b >= 0) else -1)
            elif op == "%":
                if b == 0:
                    raise DullError("division by zero in a constant", mod.file, e.line)
                r = a - b * (abs(a) // abs(b) * (1 if (a >= 0) == (b >= 0) else -1))
            elif op == "<<":
                r = a << b
            elif op == ">>":
                r = a >> b
            elif op == "&":
                r = a & b
            elif op == "|":
                r = a | b
            elif op == "^":
                r = a ^ b
            else:
                return None
            ty = e.ty if isinstance(e.ty, T.Int) else None
            if ty is not None:
                if e.op in ("+%", "-%", "*%", "<<", "~"):
                    r = wrap(r, ty)
                elif e.op in ("+|", "-|"):
                    r = min(max(r, ty.min), ty.max)
                elif e.op in ("&", "|", "^"):
                    r = wrap(r, ty)
            return r
        if k == "bits":
            v = self.const_eval(e.value, mod, scope_lookup)
            hi = self.const_eval(e.hi, mod, scope_lookup)
            lo = self.const_eval(e.lo, mod, scope_lookup)
            if None in (v, hi, lo):
                return None
            return (v >> lo) & ((1 << (hi - lo + 1)) - 1)
        return None

    def try_resolve_static(self, e, mod, scope_lookup=None):
        """Resolve a name/field chain that does not involve run-time values."""
        if e.kind == "name":
            if scope_lookup is not None and scope_lookup(e.name) is not None:
                return None
            sym = mod.syms.get(e.name)
            if sym is None:
                return None
            return self.sym_ref(sym)
        if e.kind == "field":
            base = self.try_resolve_static(e.value, mod, scope_lookup)
            if base is None:
                return None
            return self.member_ref(base, e, mod)
        return None

    def sym_ref(self, sym):
        k = sym.kind
        if k == "module":
            return Ref("module", module=sym.target)
        if k == "shape":
            return Ref("shape_type", ty=sym.ty)
        if k == "choice":
            return Ref("choice_type", ty=sym.ty)
        return Ref(k, sym=sym)

    def member_ref(self, base, e, mod):
        if base.kind == "module":
            sym = base.module.syms.get(e.name)
            if sym is None or sym.kind == "module":
                raise DullError(f"module `{base.module.name}` has no `{e.name}`", mod.file, e.line)
            return self.sym_ref(sym)
        if base.kind == "choice_type":
            if e.name not in base.ty.variants:
                raise DullError(f"`{base.ty}` has no variant `{e.name}`", mod.file, e.line)
            return Ref("variant", ty=base.ty, value=base.ty.variants[e.name])
        if base.kind == "device":
            dev = base.sym
            if e.name not in dev.regs:
                raise DullError(f"device `{dev.name}` has no register `{e.name}`", mod.file, e.line)
            return Ref("reg", dev=dev, reg=dev.regs[e.name])
        if base.kind == "reg":
            reg = base.reg
            if e.name not in reg["fields"]:
                raise DullError(f"register `{reg['name']}` has no field `{e.name}`", mod.file, e.line)
            hi, lo = reg["fields"][e.name]
            return Ref("devfield", dev=base.dev, reg=reg, hi=hi, lo=lo)
        return None

    def resolve_fixed(self, sym):
        d = sym.node
        mod = sym.module
        sym.const = None
        sym.data_label = None
        ty = self.resolve_type(d.type, mod) if d.type is not None else None
        v = d.value
        if v.kind == "array_lit":
            if not isinstance(ty, T.Array):
                self.err(mod, d, "a fixed array needs a type, e.g. `fixed t [4] u32 = [...]`")
            if len(v.items) != ty.count:
                self.err(mod, d, f"expected {ty.count} values, found {len(v.items)}")
            lab = sym.symbol
            self.rodata.append("    .balign 8")
            self.rodata.append(f"{lab}:")
            for item in v.items:
                self.emit_const_item(self.rodata, item, ty.inner, mod)
            sym.ty = ty
            sym.data_label = lab
            return
        if v.kind == "str":
            if ty is not None and not isinstance(ty, T.Span):
                self.err(mod, d, f"a string cannot be a `{ty}`")
            sym.ty = T.STRING()
            sym.str_value = v.value
            return
        c = self.const_eval(v, mod)
        if c is None:
            self.err(mod, d, "a `fixed` value must be a constant")
        if ty is None:
            if v.kind == "bool":
                ty = T.BOOL
            else:
                ref = self.try_resolve_static(v, mod) if v.kind in ("name", "field") else None
                if ref is not None and ref.kind == "variant":
                    ty = ref.ty
                elif ref is not None and ref.kind == "fixed":
                    ty = ref.sym.ty
                else:
                    ty = T.INTLIT
        if isinstance(ty, T.Int) and not (ty.min <= c <= ty.max):
            self.err(mod, d, f"{c} does not fit in `{ty}`")
        if not isinstance(ty, (T.Int, T.IntLit, T.Bool, T.Choice)):
            self.err(mod, d, f"`fixed` cannot hold a `{ty}`")
        sym.ty = ty
        sym.const = c

    def emit_const_item(self, out, item, ty, mod):
        if item.kind == "str" and isinstance(ty, T.Span):
            lab = self.string_label(item.value)
            out.append(f"    .xword {lab}")
            out.append(f"    .xword {len(item.value)}")
            return
        c = self.const_eval(item, mod)
        if c is None:
            raise DullError("expected a constant", mod.file, item.line)
        if isinstance(ty, T.Int) and not (ty.min <= c <= ty.max):
            raise DullError(f"{c} does not fit in `{ty}`", mod.file, item.line)
        if not isinstance(ty, (T.Int, T.Bool, T.Choice)):
            raise DullError(f"cannot write a constant `{ty}` here", mod.file, item.line)
        c &= (1 << (ty.size * 8)) - 1
        directive = {1: ".byte", 2: ".hword", 4: ".word", 8: ".xword"}[ty.size]
        out.append(f"    {directive} {c}")

    def resolve_device(self, sym):
        d = sym.node
        mod = sym.module
        sym.base_const = self.const_eval(d.base, mod)
        sym.base_global = None
        if sym.base_const is None:
            ref = self.try_resolve_static(d.base, mod)
            if ref is None or ref.kind not in ("global", "fixed"):
                self.err(mod, d, "a device address must be a constant or a global")
            sym.base_global = ref.sym
        sym.regs = {}
        for r in d.regs:
            if r.name in sym.regs:
                self.err(mod, r, f"register `{r.name}` appears twice")
            off = self.const_eval(r.offset, mod)
            if off is None:
                self.err(mod, r, "a register offset must be a constant")
            rty = self.resolve_type(r.type, mod)
            if not isinstance(rty, T.Int):
                self.err(mod, r, "a register must have an integer type")
            if off % rty.size:
                self.err(mod, r, f"register `{r.name}` is not aligned to its size")
            fields = {}
            for fname, hi, lo, fl in r.fields:
                h = self.const_eval(hi, mod)
                l = self.const_eval(lo, mod)
                if h is None or l is None or not (0 <= l <= h < rty.bits):
                    raise DullError(f"bad bit range for `{fname}`", mod.file, fl)
                fields[fname] = (h, l)
            sym.regs[r.name] = {"name": r.name, "offset": off, "ty": rty, "fields": fields}

    def resolve_global(self, sym):
        d = sym.node
        mod = sym.module
        ty = self.resolve_type(d.type, mod) if d.type is not None else None
        v = d.value
        if ty is None:
            if v.kind == "str":
                ty = T.STRING()
            elif v.kind == "bool":
                ty = T.BOOL
            else:
                self.err(mod, d, f"global `{d.name}` needs a type")
        sym.ty = ty
        lab = sym.symbol
        if getattr(d, "elsewhere", False):
            return
        if v is None:
            self.bss.append(f"    .balign {max(ty.align, 8) if ty.repr != 'word' else max(ty.align, 1)}")
            self.bss.append(f"{lab}:")
            self.bss.append(f"    .zero {max(ty.size, 1)}")
            return
        out = self.data
        out.append(f"    .balign 8")
        out.append(f"{lab}:")
        if v.kind == "array_lit":
            if not isinstance(ty, T.Array) or len(v.items) != ty.count:
                self.err(mod, d, "array value does not match the global's type")
            for item in v.items:
                self.emit_const_item(out, item, ty.inner, mod)
        elif v.kind == "str":
            self.emit_const_item(out, v, ty, mod)
        elif v.kind == "nothing" and isinstance(ty, T.Maybe):
            out.append(f"    .zero {ty.size}")
        elif isinstance(ty, T.Maybe):
            self.emit_const_item(out, v, ty.inner, mod)
            if ty.repr == "pair":
                out.append(f"    .zero {8 - ty.inner.size}" if ty.inner.size < 8 else "")
                out.append("    .xword 1")
        else:
            self.emit_const_item(out, v, ty, mod)

    # ---- driver ----
    def compile(self, root_path):
        root = self.load(root_path)
        self.declare_all()
        main = root.syms.get("main")
        if main is None or main.kind != "func":
            raise DullError(f"{root.file}: no `to main` function")
        if main.params:
            raise DullError("`main` takes no parameters", root.file, main.node.line)
        for mod in self.modules.values():
            for d in mod.ast.decls:
                if d.kind == "func" and d.body is not None:
                    FuncGen(self, mod, mod.syms[d.name]).generate()
        lines = [f"// generated by the DULL stage-0 compiler from {root.file}", ".text"]
        lines.append(f".global {ENTRY_SYMBOL}")
        lines.append(f".set {ENTRY_SYMBOL}, {main.symbol}")
        lines += self.out
        if self.rodata or self.strdata:
            lines.append('.section .rodata,"a"')
            lines += self.rodata
            lines += self.strdata
        if self.data:
            lines.append('.data')
            lines += [l for l in self.data if l]
        if self.bss:
            lines.append('.bss')
            lines += self.bss
        return "\n".join(lines) + "\n"


def wrap(v, ty):
    v &= (1 << ty.bits) - 1
    if ty.signed and v >> (ty.bits - 1):
        v -= 1 << ty.bits
    return v


def imm_ops(reg, value):
    """movz/movn/movk sequence loading a 64-bit constant."""
    v = value & 0xFFFF_FFFF_FFFF_FFFF
    chunks = [(v >> (16 * i)) & 0xFFFF for i in range(4)]
    inv = [(~v >> (16 * i)) & 0xFFFF for i in range(4)]
    if sum(1 for c in inv if c) < sum(1 for c in chunks if c):
        first = True
        ops = []
        for i, c in enumerate(inv):
            if c or (first and i == 3):
                if first:
                    ops.append(f"movn {reg}, #{c}, lsl #{16 * i}")
                    first = False
                else:
                    ops.append(f"movk {reg}, #{chunks[i]}, lsl #{16 * i}")
        if first:
            ops.append(f"movn {reg}, #0")
        return ops
    ops = []
    first = True
    for i, c in enumerate(chunks):
        if c:
            ops.append(f"{'movz' if first else 'movk'} {reg}, #{c}, lsl #{16 * i}")
            first = False
    if first:
        ops.append(f"movz {reg}, #0")
    return ops


# --------------------------------------------------------------------------
# Per-function code generation
# --------------------------------------------------------------------------

def load_op(ty):
    """The instruction (and target register) loading a word value of `ty` into x0."""
    if isinstance(ty, T.Int):
        return {(8, False): "ldrb w0", (8, True): "ldrsb x0", (16, False): "ldrh w0",
                (16, True): "ldrsh x0", (32, False): "ldr w0", (32, True): "ldrsw x0",
                (64, False): "ldr x0", (64, True): "ldr x0"}[(ty.bits, ty.signed)]
    if isinstance(ty, T.Bool):
        return "ldrb w0"
    if isinstance(ty, T.Choice):
        return "ldr w0"
    return "ldr x0"


def has_asm(node):
    """Does `node` hold an asm statement?"""
    if isinstance(node, (list, tuple)):
        return any(has_asm(x) for x in node)
    if not isinstance(node, Node):
        return False
    if node.kind == "asm":
        return True
    return any(has_asm(v) for k, v in vars(node).items() if k not in ("kind", "line", "ty"))


def has_call(node):
    """Does expression `node` call anything (which could change x9-x15)?"""
    if isinstance(node, (list, tuple)):
        return any(has_call(x) for x in node)
    if not isinstance(node, Node):
        return False
    if node.kind == "call":
        return True
    return any(has_call(v) for k, v in vars(node).items() if k not in ("kind", "line", "ty"))


def free_cast(src, to):
    """Is a cast between these number types free (the value already fits)?"""
    if not isinstance(src, T.Int) or not isinstance(to, T.Int):
        return False
    if src.signed == to.signed:
        return src.bits <= to.bits
    return not src.signed and src.bits < to.bits


def imm_fits(op, c):
    """Can constant `c` be the immediate second operand of `op`?"""
    if op in ("+", "-", "+%", "-%", "cmp"):
        return 0 <= c <= 4095
    if op in ("<<", ">>"):
        return 0 <= c <= 63
    return False


class Scope:
    def __init__(self):
        self.names = {}
        self.afters = []
        self.regs = []


def scan_uses(node, depth, weights, declared, escaped):
    """How much each name is used (a use at loop depth d counts 16^d), which names are
    declared, and which have their address taken (so must stay in memory)."""
    if isinstance(node, (list, tuple)):
        for x in node:
            scan_uses(x, depth, weights, declared, escaped)
        return
    if not isinstance(node, Node):
        return
    k = node.kind
    if k == "asm":
        for line in node.lines:
            for m in re.finditer(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", line):
                escaped.add(m.group(1))
        return
    if k == "addr_of" and node.operand.kind == "name":
        escaped.add(node.operand.name)
    if k == "name":
        weights[node.name] = weights.get(node.name, 0) + (1 << (4 * min(depth, 4)))
    if k == "new":
        declared.add(node.name)
    if k in ("for_range", "for_each"):
        declared.add(node.var)
    if k in LOOP_KINDS:
        depth += 1
    for key, v in vars(node).items():
        if key not in ("kind", "line", "ty"):
            scan_uses(v, depth, weights, declared, escaped)


class Loop:
    def __init__(self, cont, brk, scope_index):
        self.cont, self.brk, self.scope_index = cont, brk, scope_index


class FuncGen:
    def __init__(self, prog, mod, sym):
        self.prog = prog
        self.mod = mod
        self.sym = sym
        self.lines = []
        self.scopes = []
        self.loops = []
        self.frame = 0
        self.depth = 0          # 16-byte pushes currently on the stack
        self.traps = []
        self.end_label = prog.label("ret")
        self.free_regs = list(range(FIRST_REG, LAST_REG + 1))
        self.top_reg = 0
        self.hot = set()
        self.escaped = set()
        self.tdepth = 0          # x9.. holding intermediate values

    # ---- small helpers ----
    def e(self, s):
        self.lines.append("    " + s)

    def lab(self, name):
        self.lines.append(f"{name}:")

    def err(self, node, msg):
        raise DullError(msg, self.mod.file, node.line)

    def imm(self, reg, value):
        for op in imm_ops(reg, value):
            self.e(op)

    def push(self, repr_):
        if repr_ == "pair":
            self.e("stp x0, x1, [sp, #-16]!")
        else:
            self.e("str x0, [sp, #-16]!")
        self.depth += 1

    def pop(self, r0="x0", r1=None):
        if r1 is not None:
            self.e(f"ldp {r0}, {r1}, [sp], #16")
        else:
            self.e(f"ldr {r0}, [sp], #16")
        self.depth -= 1

    def trap(self, node, what):
        lab = self.prog.label("trap")
        msg = f"{self.mod.file}:{node.line}: {what}".encode()
        self.traps.append((lab, self.prog.string_label(msg, nul=True)))
        return lab

    def alloc(self, ty):
        size = max(ty.size, 1)
        align = max(ty.align, 8) if ty.repr != "word" else max(ty.align, 1)
        self.frame = (self.frame + size + align - 1) // align * align
        return self.frame

    def addr_local(self, offset, reg="x0"):
        if offset <= 4095:
            self.e(f"sub {reg}, x29, #{offset}")
        else:
            self.imm("x16", offset)
            self.e(f"sub {reg}, x29, x16")

    def addr_symbol(self, sym, reg="x0"):
        self.e(f"adrp {reg}, {sym}")
        self.e(f"add {reg}, {reg}, :lo12:{sym}")

    def lookup_local(self, name):
        for s in reversed(self.scopes):
            if name in s.names:
                return s.names[name]
        return None

    def declare_local(self, name, ty, node, readonly=False):
        scope = self.scopes[-1]
        if name in scope.names:
            self.err(node, f"`{name}` is already declared in this block")
        if self.mod.syms.get(name) is not None and self.mod.syms[name].kind == "module":
            self.err(node, f"`{name}` is the name of a module")
        loc = Local(name, ty, self.alloc(ty), readonly)
        scope.names[name] = loc
        if ty.repr == "word" and name not in self.escaped and (name in self.hot or name.startswith(" ")) \
                and self.free_regs:
            loc.reg = self.free_regs.pop(0)
            self.top_reg = max(self.top_reg, loc.reg)
            scope.regs.append(loc.reg)
        return loc

    def pop_scope(self):
        s = self.scopes.pop()
        self.free_regs += s.regs
        self.free_regs.sort()

    def store_local(self, loc):
        """Store x0 into local `loc`."""
        if loc.reg is not None:
            self.e(f"mov x{loc.reg}, x0")
        elif loc.offset <= 256 and loc.ty.repr == "word":
            self.store_lv(("at", loc.ty, f"[x29, #-{loc.offset}]"))
        else:
            self.addr_local(loc.offset, "x2")
            self.store_x0_to_x2(loc.ty)

    def local_operand(self, loc, want):
        """The register holding local `loc`: its own, or `want` after loading it."""
        if loc.reg is not None:
            return f"x{loc.reg}"
        if loc.offset <= 256 and loc.ty.repr == "word":
            self.load_lv(("at", loc.ty, f"[x29, #-{loc.offset}]"))
        else:
            self.addr_local(loc.offset)
            self.load_from_x0(loc.ty)
        if want != "x0":
            self.e(f"mov {want}, x0")
        return want

    def const_of(self, e):
        """The value of `e` if it is a constant number, bool or choice, else None."""
        t = e.ty
        if isinstance(t, (T.Int, T.Bool, T.Choice)) and e.kind not in ("call",):
            c = self.prog.const_eval(e, self.mod, self.lookup_local)
            if c is not None:
                if isinstance(t, T.Int):
                    if e.kind == "binary" and e.op not in ("+%", "-%", "*%", "+|", "-|", "&", "|", "^", "<<") \
                            and not (t.min <= c <= t.max):
                        self.err(e, f"{c} does not fit in `{t}`")
                    c = wrap(c, t)
                return int(c)
        return None

    def reg_local(self, e):
        if e.kind == "name" and getattr(e, "ref", None) is not None and e.ref.kind == "local":
            return e.ref.loc.reg
        return None

    def is_simple(self, e):
        """Can `e` be loaded into any register without touching others?"""
        if isinstance(e.ty, (T.IntLit, T.NothingLit)):
            return False
        if self.reg_local(e) is not None or self.const_of(e) is not None:
            return True
        return e.kind == "cast" and isinstance(e.ty, (T.Int, T.Ptr)) and getattr(e.value.ty, "repr", None) == "word" \
            and self.is_simple(e.value)

    def simple_into(self, e, reg):
        r = self.reg_local(e)
        if r is not None:
            self.e(f"mov {reg}, x{r}")
            return
        c = self.const_of(e)
        if c is not None:
            self.imm(reg, c)
            return
        self.simple_into(e.value, reg)
        if isinstance(e.ty, T.Int) and not free_cast(e.value.ty, e.ty):
            self.normalize(e.ty, reg[1:])

    def can_hold(self, e):
        """Can x0 wait in a register while `e` is worked out?"""
        return self.tdepth < 7 and not has_call(e)

    def hold(self):
        t = f"x{9 + self.tdepth}"
        self.e(f"mov {t}, x0")
        self.tdepth += 1
        return t

    def release(self):
        self.tdepth -= 1

    def simple_operand(self, e, reg, op):
        """A simple value as an operand: its register, an immediate, or loaded into `reg`."""
        r = self.reg_local(e)
        if r is not None:
            return f"x{r}"
        c = self.const_of(e)
        if c is not None and op is not None and imm_fits(op, c):
            return f"#{c}"
        self.simple_into(e, reg)
        return reg

    def operands(self, left, right, op=None):
        """Evaluate two word values for `op`; gives the registers (or immediate) holding them."""
        if self.is_simple(right):
            r = self.reg_local(left)
            if r is not None:
                a = f"x{r}"
            else:
                self.value(left)
                a = "x0"
            return a, self.simple_operand(right, "x1", op)
        if self.is_simple(left):
            self.value(right)
            return self.simple_operand(left, "x1", None), "x0"
        if self.can_hold(right):
            self.value(left)
            t = self.hold()
            self.value(right)
            self.release()
            return t, "x0"
        self.value(left)
        self.push("word")
        self.value(right)
        self.e("mov x1, x0")
        self.pop("x0")
        return "x0", "x1"

    # ---- loads and stores ----
    def load_from_x0(self, ty):
        """x0 holds an address; load a value of `ty` into x0 (/x1)."""
        if ty.repr == "mem":
            return
        if ty.repr == "pair":
            self.e("mov x2, x0")
            self.e("ldp x0, x1, [x2]")
            return
        self.e(f"{load_op(ty)}, [x0]")

    def store_x0_to_x2(self, ty):
        """Store the value in x0 (/x1) to the address in x2."""
        if ty.repr == "pair":
            self.e("stp x0, x1, [x2]")
            return
        if ty.repr == "mem":
            self.copy_mem(ty.size)
            return
        size = ty.size
        op = {1: "strb w0", 2: "strh w0", 4: "str w0", 8: "str x0"}[size]
        self.e(f"{op}, [x2]")

    def copy_mem(self, size):
        """Copy `size` bytes from [x0] to [x2]."""
        top = self.prog.label("cp")
        done = self.prog.label("cpd")
        self.imm("x3", size)
        self.lab(top)
        self.e(f"cbz x3, {done}")
        self.e("ldrb w4, [x0], #1")
        self.e("strb w4, [x2], #1")
        self.e("sub x3, x3, #1")
        self.e(f"b {top}")
        self.lab(done)

    def zero_mem(self, size):
        """Zero `size` bytes at [x0] (8-aligned)."""
        if size <= 64:
            for k in range(0, size - size % 8, 8):
                self.e(f"str xzr, [x0, #{k}]")
            for k in range(size - size % 8, size):
                self.e(f"strb wzr, [x0, #{k}]")
            return
        top = self.prog.label("z")
        done = self.prog.label("zd")
        wide = size % 8 == 0
        self.imm("x3", size // 8 if wide else size)
        self.lab(top)
        self.e(f"cbz x3, {done}")
        self.e("str xzr, [x0], #8" if wide else "strb wzr, [x0], #1")
        self.e("sub x3, x3, #1")
        self.e(f"b {top}")
        self.lab(done)

    def normalize(self, ty, reg="0"):
        """Bring x<reg> back to the canonical 64-bit form of `ty`."""
        if not isinstance(ty, T.Int) or ty.bits == 64:
            return
        r = reg
        if ty.signed:
            self.e({8: f"sxtb x{r}, w{r}", 16: f"sxth x{r}, w{r}", 32: f"sxtw x{r}, w{r}"}[ty.bits])
        else:
            self.e({8: f"uxtb w{r}, w{r}", 16: f"uxth w{r}, w{r}", 32: f"mov w{r}, w{r}"}[ty.bits])

    # ---- the function ----
    def generate(self):
        sym = self.sym
        prog = self.prog
        self.scopes.append(Scope())
        weights, declared = {}, set()
        scan_uses(sym.node.body, 0, weights, declared, self.escaped)
        for pname, _ in sym.params:
            declared.add(pname)
        if not has_call(sym.node.body) and not has_asm(sym.node.body):
            self.free_regs = LEAF_REGS + self.free_regs
        cands = sorted((n for n in declared if weights.get(n, 0) and n not in self.escaped),
                       key=lambda n: (-weights[n], n))
        self.hot = set(cands[:len(self.free_regs) - SPARE_REGS])
        param_locals = []
        for (pname, pty), (_, _, pline) in zip(sym.params, sym.node.params):
            node = Node("param", pline)
            param_locals.append(self.declare_local(pname, pty, node))
        body_start = len(self.lines)
        slots = []
        reg = 0
        for loc in param_locals:
            slots.append(reg)
            reg += 2 if loc.ty.repr == "pair" else 1
        # the ones in memory first, then the register moves backwards, so no argument
        # register is overwritten (x6, x7) before it is read
        for loc, reg in zip(param_locals, slots):
            if loc.reg is not None:
                continue
            self.addr_local(loc.offset, "x16")
            if loc.ty.repr == "pair":
                self.e(f"stp x{reg}, x{reg + 1}, [x16]")
            else:
                op = {1: "strb w", 2: "strh w", 4: "str w", 8: "str x"}[loc.ty.size]
                self.e(f"{op}{reg}, [x16]")
        for loc, reg in reversed(list(zip(param_locals, slots))):
            if loc.reg is not None:
                self.e(f"mov x{loc.reg}, x{reg}")
        self.block(sym.node.body, new_scope=False)
        self.run_afters(0)
        if sym.ret is not T.VOID:
            self.e(f"b {self.trap(sym.node, f'`{sym.name}` ended without `give`')}")
        self.pop_scope()
        frame = (self.frame + 15) // 16 * 16
        saved = list(range(FIRST_REG, self.top_reg + 1, 2))
        head = [f".balign 4", f".global {sym.symbol}", f".type {sym.symbol}, %function", f"{sym.symbol}:"]
        head += [f"    stp x{r}, x{r + 1}, [sp, #-16]!" for r in saved]
        head += ["    stp x29, x30, [sp, #-16]!", "    mov x29, sp"]
        if frame:
            if frame <= 4095:
                head.append(f"    sub sp, sp, #{frame}")
            else:
                head += ["    " + op for op in imm_ops("x16", frame)]
                head.append("    sub sp, sp, x16")
        body = self.lines[body_start:]
        out = head + body
        out.append(f"{self.end_label}:")
        out += ["    mov sp, x29", "    ldp x29, x30, [sp], #16"]
        out += [f"    ldp x{r}, x{r + 1}, [sp], #16" for r in reversed(saved)]
        out.append("    ret")
        for lab, msg in self.traps:
            out.append(f"{lab}:")
            out.append(f"    adrp x0, {msg}")
            out.append(f"    add x0, x0, :lo12:{msg}")
            out.append(f"    bl {TRAP_SYMBOL}")
        prog.out += out

    # ---- statements ----
    def block(self, stmts, new_scope=True):
        if new_scope:
            self.scopes.append(Scope())
        for s in stmts:
            self.stmt(s)
        if new_scope:
            self.run_afters(len(self.scopes) - 1, only_innermost=True)
            self.pop_scope()

    def run_afters(self, down_to, only_innermost=False):
        """Emit pending `after` code for scopes [down_to .. innermost], innermost first."""
        indices = [len(self.scopes) - 1] if only_innermost else \
            list(range(len(self.scopes) - 1, down_to - 1, -1))
        for i in indices:
            for a in reversed(self.scopes[i].afters):
                saved = self.scopes
                self.scopes = self.scopes[:i + 1]
                self.scopes[i] = self._scope_upto(saved[i], a)
                self.expr_for_effect(a)
                self.scopes = saved

    def _scope_upto(self, scope, after_node):
        # An `after` sees the names declared before it in its block.
        s = Scope()
        s.names = after_node.visible
        return s

    def any_afters(self, down_to):
        return any(self.scopes[i].afters for i in range(down_to, len(self.scopes)))

    def stmt(self, s):
        k = s.kind
        getattr(self, "s_" + k)(s)

    def s_new(self, s):
        ty = self.prog.resolve_type(s.type, self.mod) if s.type is not None else None
        if s.value is None:
            loc = self.declare_local(s.name, ty, s)
            if loc.reg is not None:
                self.e(f"mov x{loc.reg}, #0")
                return
            self.addr_local(loc.offset)
            self.zero_mem(ty.size)
            return
        if s.value.kind == "array_lit":
            if not isinstance(ty, T.Array):
                self.err(s, "an array value needs an array type, e.g. `new a [3] u8 = [1, 2, 3]`")
            if len(s.value.items) != ty.count:
                self.err(s, f"expected {ty.count} values, found {len(s.value.items)}")
            loc = self.declare_local(s.name, ty, s)
            for i, item in enumerate(s.value.items):
                self.value_as(item, ty.inner)
                self.addr_local(loc.offset - i * ty.inner.size, "x2")
                self.store_x0_to_x2(ty.inner)
            return
        vt = self.infer(s.value, ty)
        if ty is None:
            if isinstance(vt, T.IntLit):
                self.err(s, f"cannot work out the type of `{s.name}`; write `new {s.name} u32 = ...` "
                            f"(or another type)")
            if isinstance(vt, T.NothingLit):
                self.err(s, f"cannot work out the type of `{s.name}`; write `new {s.name} maybe ... = nothing`")
            if vt is T.VOID:
                self.err(s, "this gives nothing back, so it cannot be stored")
            ty = vt
        self.value_as(s.value, ty)
        loc = self.declare_local(s.name, ty, s)
        if loc.reg is not None:
            self.e(f"mov x{loc.reg}, x0")
        elif ty.repr == "mem":
            self.addr_local(loc.offset, "x2")
            self.copy_mem(ty.size)
        else:
            self.addr_local(loc.offset, "x2")
            self.store_x0_to_x2(ty)

    def value_as(self, e, ty):
        """Evaluate `e` as a value of type `ty` (checking and converting)."""
        vt = self.infer(e, ty)
        self.check_assign(e, vt, ty)
        self.value(e)
        self.coerce(vt, ty)

    def check_assign(self, node, src, dst):
        if src == dst:
            return
        if isinstance(dst, T.Maybe) and (src == dst.inner or isinstance(src, T.NothingLit)):
            return
        if isinstance(src, T.IntLit) and isinstance(dst, T.Int):
            return
        self.err(node, f"expected `{dst}`, found `{src}`")

    def coerce(self, src, dst):
        if isinstance(dst, T.Maybe) and src == dst.inner and dst.repr == "pair":
            self.e("mov x1, #1")

    def s_assign(self, s):
        lv_ty = self.infer(s.target, None)
        self.check_writable(s.target)
        if not self.is_lvalue(s.target):
            self.err(s, "cannot assign to this")
        if s.op == "=":
            if lv_ty.repr == "mem":
                self.value_as(s.value, lv_ty)
                self.push("word")
                lv = self.addr(s.target)
                self.e("mov x2, x0")
                self.pop("x0")
                self.copy_mem(lv_ty.size)
                return
            r = self.reg_local(s.target)
            if r is not None:
                vt = self.infer(s.value, lv_ty)
                if self.is_simple(s.value):
                    self.check_assign(s.value, vt, lv_ty)
                    self.simple_into(s.value, f"x{r}")
                    return
                self.value_as(s.value, lv_ty)
                self.e(f"mov x{r}, x0")
                return
            if lv_ty.repr == "word":
                vt = self.infer(s.value, lv_ty)
                if self.is_simple(s.value):
                    self.check_assign(s.value, vt, lv_ty)
                    lv = self.access(s.target)
                    if lv[0] != "at":
                        self.e("mov x2, x0")
                    self.simple_into(s.value, "x0")
                    self.store_lv(lv)
                    return
            self.value_as(s.value, lv_ty)
            if lv_ty.repr == "word" and self.accessible(s.target):
                self.store_lv(self.access(s.target))
                return
            if lv_ty.repr == "word" and self.can_hold(s.target):
                t = self.hold()
                lv = self.addr(s.target)
                self.release()
                self.e("mov x2, x0")
                self.e(f"mov x0, {t}")
                self.store_lv(lv)
                return
            self.push(lv_ty.repr)
            lv = self.addr(s.target)
            self.e("mov x2, x0")
            if lv_ty.repr == "pair":
                self.pop("x0", "x1")
            else:
                self.pop("x0")
            self.store_lv(lv)
            return
        op = s.op[:-1]
        if not isinstance(lv_ty, T.Int):
            self.err(s, f"`{s.op}` needs a number")
        fake = Node("binary", s.line, op=op, left=Node("lvtmp", s.line), right=s.value)
        fake.left.ty = lv_ty
        rt = self.binary_type(fake, lv_ty)
        if rt != lv_ty:
            self.err(s, f"`{s.op}` would change the type to `{rt}`")
        lv = self.addr(s.target)
        if lv[0] == "reg":
            if self.is_simple(s.value):
                b = self.simple_operand(s.value, "x1", op)
            else:
                self.value(s.value)
                b = "x0"
            self.binop(fake, op, lv_ty, fake.right.ty, f"x{lv[2]}", b)
            self.e(f"mov x{lv[2]}, x0")
            return
        if self.is_simple(s.value):
            self.e("mov x4, x0")
            self.load_lv(lv)
            b = self.simple_operand(s.value, "x1", op)
            self.binop(fake, op, lv_ty, fake.right.ty, "x0", b)
            self.e("mov x2, x4")
            self.store_lv(lv)
            return
        if self.tdepth < 6 and not has_call(s.value):
            ta = self.hold()
            self.load_lv(lv)
            tb = self.hold()
            self.value(s.value)
            self.release()
            self.release()
            self.binop(fake, op, lv_ty, fake.right.ty, tb, "x0")
            self.e(f"mov x2, {ta}")
            self.store_lv(lv)
            return
        self.push("word")
        self.load_lv(lv)
        self.push("word")
        self.value(s.value)
        self.e("mov x1, x0")
        self.pop("x0")
        self.binop(fake, op, lv_ty, fake.right.ty)
        self.pop("x2")
        self.store_lv(lv)

    def check_writable(self, target):
        if target.kind == "name":
            ref = target.ref
            if ref.kind == "fixed":
                self.err(target, f"`{target.name}` is fixed and cannot change")
            if ref.kind == "local" and ref.loc.readonly:
                self.err(target, f"`{target.name}` cannot be assigned here")
        if target.kind in ("index", "field", "bits") and hasattr(target, "value"):
            base = target.value
            if base.kind == "name" and getattr(base, "ref", None) is not None and base.ref.kind == "fixed":
                self.err(target, f"`{base.name}` is fixed and cannot change")

    def s_expr_stmt(self, s):
        e = s.expr
        if e.kind not in ("call", "unwrap"):
            self.err(s, "this value is not used; did you mean to assign it?")
        self.expr_for_effect(e)

    def expr_for_effect(self, e):
        self.infer(e, None)
        self.value(e)

    def cond(self, e, false_label):
        t = self.infer(e, T.BOOL)
        if not isinstance(t, T.Bool):
            self.err(e, f"a condition must be a bool, found `{t}`")
        self.jump_unless(e, false_label)

    def jump_unless(self, e, target):
        """Branch to `target` when bool `e` is false."""
        if e.kind == "logic" and e.op == "and":
            self.jump_unless(e.left, target)
            self.jump_unless(e.right, target)
        elif e.kind == "logic":
            past = self.prog.label("or")
            self.jump_if(e.left, past)
            self.jump_unless(e.right, target)
            self.lab(past)
        elif e.kind == "unary" and e.op == "not":
            self.jump_if(e.operand, target)
        elif e.kind == "compare" and not isinstance(e.left.ty, T.Maybe):
            self.compare_jump(e, target, False)
        else:
            self.value(e)
            self.e(f"cbz w0, {target}")

    def jump_if(self, e, target):
        """Branch to `target` when bool `e` is true."""
        if e.kind == "logic" and e.op == "and":
            past = self.prog.label("and")
            self.jump_unless(e.left, past)
            self.jump_if(e.right, target)
            self.lab(past)
        elif e.kind == "logic":
            self.jump_if(e.left, target)
            self.jump_if(e.right, target)
        elif e.kind == "unary" and e.op == "not":
            self.jump_unless(e.operand, target)
        elif e.kind == "compare" and not isinstance(e.left.ty, T.Maybe):
            self.compare_jump(e, target, True)
        else:
            self.value(e)
            self.e(f"cbnz w0, {target}")

    def compare_jump(self, e, target, when):
        a, b = self.operands(e.left, e.right, "cmp")
        self.e(f"cmp {a}, {b}")
        lt = e.left.ty
        c = CONDS[e.op][1 if isinstance(lt, T.Int) and lt.signed else 0]
        if not when:
            c = INVERSE[c]
        self.e(f"b.{c} {target}")

    def s_if(self, s):
        end = self.prog.label("fi")
        for cond, body in s.arms:
            if len(body) == 1 and body[0].kind in ("stop", "skip") and self.loops and not self.depth \
                    and not self.any_afters(self.loops[-1].scope_index):
                t = self.infer(cond, T.BOOL)
                if not isinstance(t, T.Bool):
                    self.err(cond, f"a condition must be a bool, found `{t}`")
                loop = self.loops[-1]
                self.jump_if(cond, loop.brk if body[0].kind == "stop" else loop.cont)
                continue
            nxt = self.prog.label("el")
            self.cond(cond, nxt)
            self.block(body)
            self.e(f"b {end}")
            self.lab(nxt)
        if s.otherwise is not None:
            self.block(s.otherwise)
        self.lab(end)

    def loop_body(self, body, cont, brk):
        self.loops.append(Loop(cont, brk, len(self.scopes)))
        self.block(body)
        self.loops.pop()

    def s_while(self, s):
        top = self.prog.label("wh")
        end = self.prog.label("we")
        self.lab(top)
        self.cond(s.cond, end)
        self.loop_body(s.body, top, end)
        self.e(f"b {top}")
        self.lab(end)

    def s_repeat(self, s):
        top = self.prog.label("rp")
        end = self.prog.label("re")
        self.lab(top)
        self.loop_body(s.body, top, end)
        self.e(f"b {top}")
        self.lab(end)

    def s_hold(self, s):
        top = self.prog.label("hd")
        end = self.prog.label("hde")
        self.lab(top)
        t = self.infer(s.cond, T.BOOL)
        if not isinstance(t, T.Bool):
            self.err(s, "`hold until` needs a bool")
        self.jump_if(s.cond, end)
        self.e("yield")
        self.e(f"b {top}")
        self.lab(end)

    def s_for_range(self, s):
        st = self.infer(s.start, None)
        et = self.infer(s.end, st if isinstance(st, T.Int) else None)
        if isinstance(st, T.IntLit) and isinstance(et, T.Int):
            st = self.infer(s.start, et)
        if isinstance(st, T.IntLit) and isinstance(et, T.IntLit):
            st = self.infer(s.start, T.U64)
            et = self.infer(s.end, T.U64)
        if not isinstance(st, T.Int) or st != et:
            self.err(s, f"a range needs two numbers of the same type, found `{st}` and `{et}`")
        ty = st
        self.scopes.append(Scope())
        end_loc = self.declare_local(f" end{self.prog.label_n}", ty, s)
        if self.is_simple(s.start):
            self.value(s.end)
            self.store_local(end_loc)
            self.simple_into(s.start, "x0")
        else:
            self.value(s.start)
            self.push("word")
            self.value(s.end)
            self.store_local(end_loc)
            self.pop("x0")
        var = self.declare_local(s.var, ty, s, readonly=True)
        self.store_local(var)
        top = self.prog.label("fr")
        step = self.prog.label("fs")
        done = self.prog.label("fd")
        cond_gt = "gt" if ty.signed else "hi"
        if s.inclusive:
            self.compare_locals(var, end_loc)
            self.e(f"b.{cond_gt} {done}")
        self.lab(top)
        if not s.inclusive:
            self.compare_locals(var, end_loc)
            self.e(f"b.{'ge' if ty.signed else 'hs'} {done}")
        self.loop_body(s.body, step, done)
        self.lab(step)
        if s.inclusive:
            self.compare_locals(var, end_loc)
            self.e(f"b.eq {done}")
        if var.reg is not None:
            self.e(f"add x{var.reg}, x{var.reg}, #1")
            self.normalize(ty, str(var.reg))
        else:
            self.addr_local(var.offset, "x2")
            self.e("mov x0, x2")
            self.load_from_x0(ty)
            self.e("add x0, x0, #1")
            self.normalize(ty)
            self.store_x0_to_x2(ty)
        self.e(f"b {top}")
        self.lab(done)
        self.pop_scope()

    def compare_locals(self, a, b):
        ra = self.local_operand(a, "x1")
        rb = self.local_operand(b, "x0")
        self.e(f"cmp {ra}, {rb}")

    def s_for_each(self, s):
        st = self.infer(s.seq, None)
        if isinstance(st, T.Array):
            elem = st.inner
        elif isinstance(st, T.Span):
            elem = st.inner
        else:
            self.err(s, f"cannot loop over a `{st}`; loop over a span, array or string")
        if elem.repr == "mem":
            self.err(s, f"the stage-0 compiler cannot copy `{elem}` items in a loop; loop over indexes")
        self.scopes.append(Scope())
        ptr_loc = self.declare_local(f" ptr{self.prog.label_n}", T.U64, s)
        len_loc = self.declare_local(f" len{self.prog.label_n}", T.U64, s)
        idx_loc = self.declare_local(f" idx{self.prog.label_n}", T.U64, s)
        if isinstance(st, T.Array):
            if not self.is_lvalue(s.seq):
                self.err(s, "can only loop over a stored array")
            self.addr(s.seq)
            self.imm("x1", st.count)
        else:
            self.value(s.seq)
        self.store_local(ptr_loc)
        self.e("mov x0, x1")
        self.store_local(len_loc)
        self.e("mov x0, #0")
        self.store_local(idx_loc)
        var = self.declare_local(s.var, elem, s, readonly=True)
        top = self.prog.label("fe")
        step = self.prog.label("fes")
        done = self.prog.label("fed")
        self.lab(top)
        ri = self.local_operand(idx_loc, "x1")
        rl = self.local_operand(len_loc, "x0")
        self.e(f"cmp {ri}, {rl}")
        self.e(f"b.hs {done}")
        base = self.local_operand(ptr_loc, "x2")
        index = self.local_operand(idx_loc, "x0")
        self.scale_add(elem.size, base, index)
        self.load_from_x0(elem)
        self.store_local(var)
        self.loop_body(s.body, step, done)
        self.lab(step)
        if idx_loc.reg is not None:
            self.e(f"add x{idx_loc.reg}, x{idx_loc.reg}, #1")
        else:
            self.addr_local(idx_loc.offset, "x2")
            self.e("ldr x0, [x2]")
            self.e("add x0, x0, #1")
            self.e("str x0, [x2]")
        self.e(f"b {top}")
        self.lab(done)
        self.pop_scope()

    def scale_add(self, size, base="x2", index="x0"):
        """x0 = base + index * size."""
        if size & (size - 1) == 0:
            shift = size.bit_length() - 1
            self.e(f"add x0, {base}, {index}, lsl #{shift}")
        else:
            self.imm("x16", size)
            self.e(f"madd x0, {index}, x16, {base}")

    def s_give(self, s):
        ret = self.sym.ret
        if s.value is None:
            if ret is not T.VOID and not isinstance(ret, T.Maybe):
                self.err(s, f"`{self.sym.name}` must give a `{ret}`")
            if isinstance(ret, T.Maybe):
                self.e("mov x0, #0")
                self.e("mov x1, #0")
        else:
            if ret is T.VOID:
                self.err(s, f"`{self.sym.name}` gives nothing back")
            self.value_as(s.value, ret)
        self.leave_function(ret)

    def leave_function(self, ret):
        if self.any_afters(0):
            self.push("pair")
            saved_depth = self.depth
            self.run_afters(0)
            self.depth = saved_depth
            self.pop("x0", "x1")
        self.e(f"b {self.end_label}")

    def s_stop(self, s):
        self.jump_loop(s, "stop")

    def s_skip(self, s):
        self.jump_loop(s, "skip")

    def jump_loop(self, node, which):
        if not self.loops:
            self.err(node, f"`{which}` outside a loop")
        loop = self.loops[-1]
        if self.depth:
            self.e(f"add sp, sp, #{16 * self.depth}")
        saved = self.depth
        self.depth = 0
        self.run_afters(loop.scope_index)
        self.depth = saved
        self.e(f"b {loop.brk if which == 'stop' else loop.cont}")

    def s_after(self, s):
        s.expr.visible = dict(self.scopes[-1].names)
        self.infer(s.expr, None)
        if s.expr.kind != "call":
            self.err(s, "`after` needs a call, e.g. `after free(buf)`")
        self.scopes[-1].afters.append(s.expr)

    def s_stream(self, s):
        stages = []
        node = s.chain
        while node.kind == "call" and getattr(node, "piped", False):
            stages.append(node)
            node = node.args[0]
        if not stages:
            self.err(s, "`stream` needs a pipe chain, e.g. `stream next(f) -> decode -> play`")
        source = node
        stages.reverse()
        top = self.prog.label("st")
        end = self.prog.label("ste")
        self.lab(top)
        self.loops.append(Loop(top, end, len(self.scopes)))
        self.scopes.append(Scope())
        n = self.prog.label_n
        src_t = self.infer(source, None)
        if not isinstance(src_t, T.Maybe):
            self.err(s, f"a stream starts with a call that gives `maybe ...`, found `{src_t}`")
        prev = f" chunk{n}_0"
        self.s_new(Node("new", s.line, name=prev, type=None,
                        value=Node("unwrap", s.line, value=source, action="stop", fallback=None)))
        for i, stage in enumerate(stages):
            stage.args[0] = Node("name", stage.line, name=prev)
            stage.piped = False
            t = self.infer(stage, None)
            last = i == len(stages) - 1
            if last:
                if isinstance(t, T.Maybe):
                    self.expr_for_effect(Node("unwrap", stage.line, value=stage, action="skip", fallback=None))
                else:
                    self.expr_for_effect(stage)
            else:
                name = f" chunk{n}_{i + 1}"
                value = stage
                if isinstance(t, T.Maybe):
                    value = Node("unwrap", stage.line, value=stage, action="skip", fallback=None)
                self.s_new(Node("new", stage.line, name=name, type=None, value=value))
                prev = name
        self.run_afters(len(self.scopes) - 1, only_innermost=True)
        self.pop_scope()
        self.loops.pop()
        self.e(f"b {top}")
        self.lab(end)

    def s_asm(self, s):
        import re
        bound = []
        for line in s.lines:
            for m in re.finditer(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", line):
                if m.group(1) not in bound:
                    bound.append(m.group(1))
        if len(bound) > 7:
            self.err(s, "at most 7 bound names per `asm` statement")
        regs = {}
        for i, name in enumerate(bound):
            node = Node("name", s.line, name=name)
            t = self.infer(node, None)
            if not self.is_lvalue(node) or t.repr != "word":
                self.err(s, f"`{{{name}}}` must be a variable holding a number, bool or pointer")
            r = 9 + i
            small = t.size <= 4
            regs[name] = (f"w{r}" if small else f"x{r}", node, t, r)
            self.addr(node)
            self.load_from_x0(t)
            self.e(f"mov x{r}, x0")
        for line in s.lines:
            text = re.sub(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", lambda m: regs[m.group(1)][0], line)
            self.e(text)
        for name in bound:
            regname, node, t, r = regs[name]
            if self.is_readonly(node):
                continue
            self.e(f"mov x0, x{r}")
            self.normalize(t)
            self.push("word")
            lv = self.addr(node)
            self.e("mov x2, x0")
            self.pop("x0")
            self.store_lv(lv)

    def is_readonly(self, node):
        ref = node.ref
        return ref.kind == "fixed" or (ref.kind == "local" and ref.loc.readonly)

    # ---- name resolution ----
    def resolve(self, e):
        """Resolve a name or field chain. Returns a Ref, or None for a run-time value field."""
        if e.kind == "name":
            loc = self.lookup_local(e.name)
            if loc is not None:
                return Ref("local", loc=loc)
            sym = self.mod.syms.get(e.name)
            if sym is not None:
                return self.prog.sym_ref(sym)
            if e.name in BUILTIN_VOID or e.name in ("read_sysreg", "write_sysreg"):
                return Ref("builtin", name=e.name)
            self.err(e, f"unknown name `{e.name}`")
        if e.kind == "field":
            base = e.value
            if base.kind in ("name", "field"):
                bref = self.resolve(base)
                base.ref = bref
                if bref is not None and bref.kind in ("module", "choice_type", "device", "reg"):
                    return self.prog.member_ref(bref, e, self.mod)
            return None
        return None

    # ---- type inference ----
    def infer(self, e, want):
        t = self._infer(e, want)
        e.ty = t
        return t

    def _infer(self, e, want):
        k = e.kind
        if k == "lvtmp":
            return e.ty
        if k == "int":
            if isinstance(want, T.Maybe) and isinstance(want.inner, T.Int):
                want = want.inner
            if isinstance(want, T.Int):
                if not (want.min <= e.value <= want.max):
                    self.err(e, f"{e.value} does not fit in `{want}`")
                return want
            return T.INTLIT
        if k == "bool":
            return T.BOOL
        if k == "str":
            return T.STRING()
        if k == "nothing":
            if isinstance(want, T.Maybe):
                return want
            return T.NOTHING
        if k == "size_of":
            self.prog.resolve_type(e.of, self.mod)
            if isinstance(want, T.Int):
                return want
            return T.INTLIT
        if k == "array_lit":
            self.err(e, "an array value can only initialize an array variable")
        if k in ("name", "field"):
            ref = self.resolve(e)
            e.ref = ref
            if ref is None:
                return self.infer_value_field(e)
            return self.ref_type(e, ref, want)
        if k == "call":
            return self.infer_call(e, want)
        if k == "index":
            bt = self.infer(e.value, None)
            if isinstance(bt, T.Int):
                it = self.infer(e.index, None)
                if isinstance(it, T.IntLit):
                    self.infer(e.index, T.U64)
                elif not isinstance(it, T.Int):
                    self.err(e, "a bit index must be a number")
                return T.unsigned_of(bt)
            it = self.infer(e.index, T.U64)
            if not isinstance(it, T.Int):
                self.err(e, f"an index must be a number, found `{it}`")
            if isinstance(bt, (T.Array, T.Span, T.Ptr)):
                return bt.inner
            self.err(e, f"cannot index a `{bt}`")
        if k == "bits":
            bt = self.infer(e.value, None)
            if not isinstance(bt, T.Int):
                self.err(e, f"bit ranges need a number, found `{bt}`")
            hi = self.prog.const_eval(e.hi, self.mod, self.lookup_local)
            lo = self.prog.const_eval(e.lo, self.mod, self.lookup_local)
            if hi is None or lo is None:
                self.err(e, "the stage-0 compiler needs constant bit ranges")
            if not (0 <= lo <= hi < bt.bits):
                self.err(e, f"bit range [{hi}:{lo}] is outside a `{bt}`")
            e.hi_c, e.lo_c = hi, lo
            return T.unsigned_of(bt)
        if k == "slice":
            bt = self.infer(e.value, None)
            for part in (e.lo, e.hi):
                pt = self.infer(part, T.U64)
                if not isinstance(pt, T.Int):
                    self.err(e, "slice bounds must be numbers")
            if isinstance(bt, T.Span):
                return bt
            if isinstance(bt, T.Array):
                return T.Span(bt.inner)
            self.err(e, f"cannot slice a `{bt}`")
        if k == "unary":
            if e.op == "not":
                t = self.infer(e.operand, T.BOOL)
                if not isinstance(t, T.Bool):
                    self.err(e, f"`not` needs a bool, found `{t}`")
                return T.BOOL
            t = self.infer(e.operand, want if isinstance(want, T.Int) else None)
            if isinstance(t, T.IntLit):
                return t
            if not isinstance(t, T.Int):
                self.err(e, f"`{e.op}` needs a number, found `{t}`")
            if e.op == "-" and not t.signed:
                self.err(e, f"cannot negate an unsigned `{t}`; use `0 -% x` to wrap")
            return t
        if k == "deref":
            t = self.infer(e.operand, None)
            if not isinstance(t, T.Ptr):
                self.err(e, f"`deref` needs a pointer, found `{t}`")
            return t.inner
        if k == "addr_of":
            t = self.infer(e.operand, None)
            if not self.is_lvalue(e.operand) or self.is_bits_lvalue(e.operand):
                self.err(e, "`addr of` needs a variable, field or element")
            return T.Ptr(t)
        if k == "cast":
            to = self.prog.resolve_type(e.to, self.mod)
            t = self.infer(e.value, None)
            if isinstance(t, T.IntLit):
                t = self.infer(e.value, T.U64 if not isinstance(to, T.Int) else to)
            ok = (isinstance(to, (T.Int, T.Bool)) and isinstance(t, (T.Int, T.Bool, T.Choice))) or \
                 (isinstance(to, T.Choice) and isinstance(t, T.Int)) or \
                 (isinstance(to, T.Ptr) and isinstance(t, (T.Ptr, T.Int))) or \
                 (isinstance(to, T.Int) and isinstance(t, T.Ptr)) or \
                 (isinstance(to, T.Span) and isinstance(t, T.Array) and to.inner == t.inner) or \
                 (isinstance(to, T.Span) and isinstance(t, T.Span) and to.inner == t.inner)
            if not ok:
                self.err(e, f"cannot convert `{t}` to `{to}`")
            if isinstance(to, T.Span) and isinstance(t, T.Array) and not self.is_lvalue(e.value):
                self.err(e, "only a stored array can become a span")
            return to
        if k == "binary":
            return self.binary_type(e, want)
        if k == "compare":
            return self.compare_type(e)
        if k == "logic":
            for side in (e.left, e.right):
                t = self.infer(side, T.BOOL)
                if not isinstance(t, T.Bool):
                    self.err(e, f"`{e.op}` needs bools, found `{t}`")
            return T.BOOL
        if k == "unwrap":
            t = self.infer(e.value, None)
            if not isinstance(t, T.Maybe):
                self.err(e, f"`else` unwraps a `maybe`, but this is a `{t}`")
            if e.action == "value":
                ft = self.infer(e.fallback, t.inner)
                self.check_assign(e.fallback, ft, t.inner)
            elif e.action == "give" and e.fallback is not None:
                ft = self.infer(e.fallback, self.sym.ret)
                self.check_assign(e.fallback, ft, self.sym.ret)
            return t.inner
        self.err(e, f"cannot use `{k}` here")

    def ref_type(self, e, ref, want):
        k = ref.kind
        if k == "local":
            return ref.loc.ty
        if k == "global":
            return ref.sym.ty
        if k == "fixed":
            t = ref.sym.ty
            if isinstance(t, T.IntLit) and isinstance(want, T.Int):
                if not (want.min <= ref.sym.const <= want.max):
                    self.err(e, f"`{ref.sym.name}` ({ref.sym.const}) does not fit in `{want}`")
                return want
            return t
        if k == "variant":
            return ref.ty
        if k == "reg":
            return ref.reg["ty"]
        if k == "devfield":
            return T.unsigned_of(ref.reg["ty"])
        if k == "func":
            self.err(e, f"`{e.name if e.kind == 'name' else e.name}` is a function; call it with ()")
        if k == "module":
            self.err(e, "a module is not a value")
        if k == "device":
            self.err(e, "a device is not a value; use one of its registers")
        if k in ("shape_type", "choice_type"):
            self.err(e, "a type is not a value")
        if k == "builtin":
            self.err(e, f"`{ref.name}` is a built-in; call it with ()")
        self.err(e, "cannot use this as a value")

    def infer_value_field(self, e):
        bt = self.infer(e.value, None)
        if isinstance(bt, T.Ptr) and isinstance(bt.inner, (T.Shape, T.Span)):
            bt = bt.inner
        if isinstance(bt, T.Shape):
            if e.name not in bt.fields:
                self.err(e, f"`{bt}` has no field `{e.name}`")
            return bt.fields[e.name][0]
        if isinstance(bt, T.Span):
            if e.name == "len":
                return T.U64
            if e.name == "ptr":
                return T.Ptr(bt.inner)
            self.err(e, f"a span only has `.ptr` and `.len`, not `.{e.name}`")
        if isinstance(bt, T.Array) and e.name == "len":
            e.const_len = bt.count
            return T.U64
        self.err(e, f"`{bt}` has no fields")

    def infer_call(self, e, want):
        f = e.func
        if f.kind not in ("name", "field"):
            self.err(e, "can only call a named function")
        ref = self.resolve(f)
        f.ref = ref
        if ref is None:
            self.err(e, "can only call a named function")
        if ref.kind == "builtin":
            e.builtin = ref.name
            if ref.name in BUILTIN_VOID:
                if e.args:
                    self.err(e, f"`{ref.name}()` takes nothing")
                return T.VOID
            if ref.name == "read_sysreg":
                if len(e.args) != 1 or e.args[0].kind != "name":
                    self.err(e, "`read_sysreg` takes a system register name, e.g. read_sysreg(CurrentEL)")
                return T.U64
            if ref.name == "write_sysreg":
                if len(e.args) != 2 or e.args[0].kind != "name":
                    self.err(e, "`write_sysreg` takes a register name and a value")
                t = self.infer(e.args[1], T.U64)
                if not isinstance(t, T.Int):
                    self.err(e, "`write_sysreg` needs a number")
                return T.VOID
        if ref.kind != "func":
            self.err(e, "this is not a function")
        sym = ref.sym
        e.builtin = None
        e.sym = sym
        if len(e.args) != len(sym.params):
            self.err(e, f"`{sym.name}` takes {len(sym.params)} value(s), given {len(e.args)}")
        for arg, (pname, pty) in zip(e.args, sym.params):
            at = self.infer(arg, pty)
            self.check_assign(arg, at, pty)
        return sym.ret

    def binary_type(self, e, want):
        op = e.op
        if op in ("<<", ">>"):
            lt = self.infer(e.left, want if isinstance(want, T.Int) else None)
            rt = self.infer(e.right, T.U64)
            if not isinstance(rt, T.Int):
                self.err(e, "a shift amount must be a number")
            if isinstance(lt, T.IntLit):
                return lt
            if not isinstance(lt, T.Int):
                self.err(e, f"`{op}` needs a number, found `{lt}`")
            return lt
        lw = want if isinstance(want, (T.Int, T.Ptr)) else None
        lt = self.infer(e.left, lw if isinstance(lw, T.Int) else None)
        if isinstance(lt, T.Ptr):
            if op not in ("+", "-"):
                self.err(e, f"`{op}` does not work on pointers")
            rt = self.infer(e.right, T.U64)
            if not isinstance(rt, T.Int):
                self.err(e, "a pointer can only move by a number")
            return lt
        rt = self.infer(e.right, lt if isinstance(lt, T.Int) else (lw if isinstance(lw, T.Int) else None))
        if isinstance(lt, T.IntLit) and isinstance(rt, T.Int):
            lt = self.infer(e.left, rt)
        if isinstance(lt, T.IntLit) and isinstance(rt, T.IntLit):
            return T.INTLIT
        if not isinstance(lt, T.Int) or lt != rt:
            self.err(e, f"`{op}` needs two numbers of the same type, found `{lt}` and `{rt}`")
        return lt

    def compare_type(self, e):
        lt = self.infer(e.left, None)
        if isinstance(lt, T.Maybe) or isinstance(lt, T.NothingLit):
            rt = self.infer(e.right, lt if isinstance(lt, T.Maybe) else None)
            if e.op not in ("==", "!=") or not (isinstance(e.right.ty, (T.Maybe, T.NothingLit))
                                                and (e.right.kind == "nothing" or e.left.kind == "nothing")):
                self.err(e, "a `maybe` can only be compared with `is nothing` / `is not nothing`")
            if isinstance(lt, T.NothingLit):
                self.infer(e.left, rt)
            return T.BOOL
        rt = self.infer(e.right, lt if not isinstance(lt, T.IntLit) else None)
        if isinstance(lt, T.IntLit) and isinstance(rt, T.Int):
            lt = self.infer(e.left, rt)
        if isinstance(lt, T.IntLit) and isinstance(rt, T.IntLit):
            lt = self.infer(e.left, T.I64)
            rt = self.infer(e.right, T.I64)
        if lt != rt:
            self.err(e, f"cannot compare `{lt}` with `{rt}`")
        if e.op not in ("==", "!=") and not isinstance(lt, (T.Int, T.Ptr)):
            self.err(e, f"`{e.op}` needs numbers")
        if lt.repr != "word":
            self.err(e, f"cannot compare `{lt}` values with `is`")
        return T.BOOL

    # ---- lvalues ----
    def is_lvalue(self, e):
        k = e.kind
        if k == "name":
            return e.ref is not None and e.ref.kind in ("local", "global") or \
                (e.ref is not None and e.ref.kind == "fixed" and getattr(e.ref.sym, "data_label", None))
        if k == "field":
            if e.ref is not None:
                return e.ref.kind in ("reg", "devfield", "global") or \
                    (e.ref.kind == "fixed" and bool(getattr(e.ref.sym, "data_label", None)))
            bt = e.value.ty
            if isinstance(bt, T.Ptr):
                return True
            if getattr(e, "const_len", None) is not None:
                return False
            return self.is_lvalue(e.value)
        if k == "index":
            bt = e.value.ty
            if isinstance(bt, T.Int):
                return self.is_lvalue(e.value) and self.prog.const_eval(e.index, self.mod, self.lookup_local) is not None
            if isinstance(bt, T.Array):
                return self.is_lvalue(e.value)
            return True
        if k == "deref":
            return True
        if k == "bits":
            return self.is_lvalue(e.value)
        return False

    def is_bits_lvalue(self, e):
        if e.kind == "bits":
            return True
        if e.kind == "index" and isinstance(e.value.ty, T.Int):
            return True
        if e.kind == "field" and e.ref is not None and e.ref.kind == "devfield":
            return True
        return False

    def addr(self, e):
        """Leave the address of lvalue `e` in x0. Returns an lvalue descriptor."""
        k = e.kind
        if k == "name":
            ref = e.ref
            if ref.kind == "local":
                if ref.loc.reg is not None:
                    return ("reg", e.ty, ref.loc.reg)
                self.addr_local(ref.loc.offset)
            elif ref.kind == "global":
                self.addr_symbol(ref.sym.symbol)
            elif ref.kind == "fixed":
                self.addr_symbol(ref.sym.data_label)
            return ("mem", e.ty)
        if k == "field":
            ref = e.ref
            if ref is not None and ref.kind in ("reg", "devfield"):
                dev = ref.dev
                off = ref.reg["offset"]
                if dev.base_const is not None:
                    self.imm("x0", dev.base_const + off)
                else:
                    g = dev.base_global
                    if g.kind == "fixed":
                        self.imm("x0", g.const + off)
                    else:
                        self.addr_symbol(g.symbol)
                        self.e("ldr x0, [x0]")
                        if off:
                            self.imm("x16", off)
                            self.e("add x0, x0, x16")
                if ref.kind == "devfield":
                    return ("bits", ref.reg["ty"], ref.hi, ref.lo)
                return ("mem", e.ty)
            if ref is not None and ref.kind == "global":
                self.addr_symbol(ref.sym.symbol)
                return ("mem", e.ty)
            if ref is not None and ref.kind == "fixed":        # another module's fixed array
                self.addr_symbol(ref.sym.data_label)
                return ("mem", e.ty)
            bt = e.value.ty
            if isinstance(bt, T.Ptr):
                self.value(e.value)
                shape = bt.inner
            else:
                self.addr(e.value)
                shape = bt
            if isinstance(shape, T.Span):
                off = 0 if e.name == "ptr" else 8
            else:
                off = shape.fields[e.name][1]
            if off:
                self.add_imm(off)
            return ("mem", e.ty)
        if k == "index":
            bt = e.value.ty
            if isinstance(bt, T.Int):
                n = self.prog.const_eval(e.index, self.mod, self.lookup_local)
                inner = self.addr(e.value)
                return self.sub_bits(inner, bt, n, n, e)
            c = self.const_of(e.index)
            if c is not None and isinstance(bt, (T.Ptr, T.Array)) and 0 <= c * bt.inner.size <= 4095 \
                    and (isinstance(bt, T.Ptr) or c < bt.count):
                if isinstance(bt, T.Ptr):
                    self.value(e.value)
                else:
                    self.addr(e.value)
                if c:
                    self.e(f"add x0, x0, #{c * bt.inner.size}")
                return ("mem", e.ty)
            if isinstance(bt, T.Array):
                self.addr(e.value)
                simple = self.is_simple(e.index)
                held = not simple and self.can_hold(e.index)
                base = "x2"
                if simple:
                    self.e("mov x2, x0")
                    self.simple_into(e.index, "x0")
                elif held:
                    base = self.hold()
                    self.value(e.index)
                    self.release()
                else:
                    self.push("word")
                    self.value(e.index)
                if self.prog.debug:
                    self.imm("x1", bt.count)
                    self.e("cmp x0, x1")
                    self.e(f"b.hs {self.trap(e, 'index out of range')}")
                if not simple and not held:
                    self.pop("x2")
                self.scale_add(bt.inner.size, base)
                return ("mem", e.ty)
            if isinstance(bt, T.Span):
                self.value(e.value)
                if self.is_simple(e.index):
                    self.e("mov x2, x0")
                    self.e("mov x3, x1")
                    self.simple_into(e.index, "x0")
                else:
                    self.push("pair")
                    self.value(e.index)
                    self.pop("x2", "x3")
                if self.prog.debug:
                    self.e("cmp x0, x3")
                    self.e(f"b.hs {self.trap(e, 'index out of range')}")
                self.scale_add(bt.inner.size)
                return ("mem", e.ty)
            if isinstance(bt, T.Ptr):
                base, index = "x2", "x0"
                if self.is_simple(e.index):
                    if self.is_simple(e.value):
                        base = self.simple_operand(e.value, "x2", None)
                    else:
                        self.value(e.value)
                        base = "x0"
                    index = self.simple_operand(e.index, "x1", None)
                elif self.is_simple(e.value):
                    self.value(e.index)
                    base = self.simple_operand(e.value, "x2", None)
                elif self.can_hold(e.index):
                    self.value(e.value)
                    base = self.hold()
                    self.value(e.index)
                    self.release()
                else:
                    self.value(e.value)
                    self.push("word")
                    self.value(e.index)
                    self.pop("x2")
                self.scale_add(bt.inner.size, base, index)
                return ("mem", e.ty)
        if k == "deref":
            self.value(e.operand)
            return ("mem", e.ty)
        if k == "bits":
            inner = self.addr(e.value)
            return self.sub_bits(inner, e.value.ty, e.hi_c, e.lo_c, e)
        self.err(e, "cannot take the address of this")

    def frame_local(self, e):
        """The local in the frame (near x29) that name `e` is, or None."""
        if e.kind == "name" and getattr(e, "ref", None) is not None and e.ref.kind == "local":
            loc = e.ref.loc
            if loc.reg is None and loc.offset <= 256 and loc.ty.repr == "word":
                return loc
        return None

    def plus_const(self, e):
        """For i + c (i simple, c a constant 0-4095): c, else None."""
        if e.kind == "binary" and e.op == "+" and isinstance(e.ty, T.Int) and self.is_simple(e.left):
            c = self.const_of(e.right)
            if c is not None and 0 <= c <= 4095:
                return c
        return None

    def accessible(self, e):
        """Can `e` be loaded or stored with one instruction (leaving x0 alone): a local in
        the frame, or p[i] / p[i + c] with p and i simple and a word-sized element?"""
        if self.frame_local(e) is not None:
            return True
        return e.kind == "index" and isinstance(e.value.ty, T.Ptr) and e.ty.repr == "word" \
            and e.ty.size in (1, 2, 4, 8) and self.is_simple(e.value) \
            and (self.is_simple(e.index) or self.plus_const(e.index) is not None)

    def access(self, e):
        """The lvalue of `e`, as an address operand if `accessible` (leaving x0 alone)."""
        if not self.accessible(e):
            return self.addr(e)
        loc = self.frame_local(e)
        if loc is not None:
            return ("at", e.ty, f"[x29, #-{loc.offset}]")
        size = e.ty.size
        base = self.simple_operand(e.value, "x2", None)
        c = self.const_of(e.index)
        if c is not None and 0 <= c <= 4095:
            return ("at", e.ty, f"[{base}, #{c * size}]")
        c = self.plus_const(e.index)
        if c is not None:
            index = self.simple_operand(e.index.left, "x1", None)
            if size == 1:
                self.e(f"add x16, {base}, {index}")
            else:
                self.e(f"add x16, {base}, {index}, lsl #{size.bit_length() - 1}")
            return ("at", e.ty, f"[x16, #{c * size}]")
        index = self.simple_operand(e.index, "x1", None)
        if size == 1:
            return ("at", e.ty, f"[{base}, {index}]")
        return ("at", e.ty, f"[{base}, {index}, lsl #{size.bit_length() - 1}]")

    def sub_bits(self, inner, base_ty, hi, lo, node):
        if inner[0] in ("bits", "rbits"):
            bty, ihi, ilo = inner[1], inner[2], inner[3]
            if hi > ihi - ilo:
                self.err(node, "bit range is wider than the field")
            if inner[0] == "rbits":
                return ("rbits", bty, ilo + hi, ilo + lo, inner[4])
            return ("bits", bty, ilo + hi, ilo + lo)
        if inner[0] == "reg":
            return ("rbits", base_ty, hi, lo, inner[2])
        return ("bits", base_ty, hi, lo)

    def add_imm(self, off, reg="x0"):
        if off <= 4095:
            self.e(f"add {reg}, {reg}, #{off}")
        else:
            self.imm("x16", off)
            self.e(f"add {reg}, {reg}, x16")

    def load_lv(self, lv):
        """x0 holds the lvalue's address; load its value."""
        if lv[0] == "mem":
            self.load_from_x0(lv[1])
            return
        if lv[0] == "reg":
            self.e(f"mov x0, x{lv[2]}")
            return
        if lv[0] == "at":
            self.e(f"{load_op(lv[1])}, {lv[2]}")
            return
        if lv[0] == "rbits":
            self.e(f"ubfx x0, x{lv[4]}, #{lv[3]}, #{lv[2] - lv[3] + 1}")
            return
        _, bty, hi, lo = lv
        self.load_from_x0(T.unsigned_of(bty))
        self.e(f"ubfx x0, x0, #{lo}, #{hi - lo + 1}")

    def store_lv(self, lv):
        """Store x0 (/x1) into the lvalue whose address is in x2."""
        if lv[0] == "mem":
            self.store_x0_to_x2(lv[1])
            return
        if lv[0] == "reg":
            self.e(f"mov x{lv[2]}, x0")
            return
        if lv[0] == "at":
            self.e({1: "strb w0", 2: "strh w0", 4: "str w0", 8: "str x0"}[lv[1].size] + f", {lv[2]}")
            return
        if lv[0] == "rbits":
            self.e(f"bfi x{lv[4]}, x0, #{lv[3]}, #{lv[2] - lv[3] + 1}")
            self.normalize(lv[1], str(lv[4]))
            return
        _, bty, hi, lo = lv
        ut = T.unsigned_of(bty)
        self.e("mov x5, x0")
        self.e("mov x0, x2")
        self.load_from_x0(ut)
        self.e(f"bfi x0, x5, #{lo}, #{hi - lo + 1}")
        self.store_x0_to_x2(ut)

    # ---- values ----
    def value(self, e):
        t = e.ty
        if isinstance(t, T.IntLit):
            self.err(e, "cannot work out the type of this number; add a type, e.g. `as u32`")
        if isinstance(t, T.NothingLit):
            self.err(e, "cannot work out which `maybe` this `nothing` is")
        c = self.const_of(e)
        if c is not None:
            self.imm("x0", c)
            return
        k = e.kind
        getattr(self, "v_" + k)(e)

    def v_int(self, e):
        self.imm("x0", e.value)

    def v_bool(self, e):
        self.imm("x0", 1 if e.value else 0)

    def v_str(self, e):
        lab = self.prog.string_label(e.value)
        self.addr_symbol(lab)
        self.imm("x1", len(e.value))

    def v_nothing(self, e):
        self.e("mov x0, #0")
        if e.ty.repr == "pair":
            self.e("mov x1, #0")

    def v_lvtmp(self, e):
        pass

    def v_name(self, e):
        ref = e.ref
        if ref.kind == "fixed":
            sym = ref.sym
            if getattr(sym, "str_value", None) is not None:
                lab = self.prog.string_label(sym.str_value)
                self.addr_symbol(lab)
                self.imm("x1", len(sym.str_value))
                return
            if sym.data_label:
                self.addr_symbol(sym.data_label)
                return
        lv = self.access(e)
        self.load_lv(lv)

    def v_field(self, e):
        if getattr(e, "const_len", None) is not None:
            self.imm("x0", e.const_len)
            return
        if e.ref is None and not self.is_lvalue(e):
            bt = e.value.ty
            if isinstance(bt, T.Span):
                self.value(e.value)
                if e.name == "len":
                    self.e("mov x0, x1")
                return
            self.err(e, "cannot read a field of this value")
        if e.ref is not None and e.ref.kind == "fixed":
            return self.v_name(Node("name", e.line, name=e.name, ref=e.ref, ty=e.ty))
        lv = self.addr(e)
        self.load_lv(lv)

    def v_index(self, e):
        bt = e.value.ty
        if isinstance(bt, T.Int) and not self.is_lvalue(e):
            self.value(e.value)
            self.push("word")
            self.value(e.index)
            self.e("mov x1, x0")
            self.pop("x0")
            self.e("lsr x0, x0, x1")
            self.e("and x0, x0, #1")
            return
        lv = self.access(e)
        self.load_lv(lv)

    def v_bits(self, e):
        if self.is_lvalue(e):
            lv = self.addr(e)
            self.load_lv(lv)
            return
        self.value(e.value)
        self.e(f"ubfx x0, x0, #{e.lo_c}, #{e.hi_c - e.lo_c + 1}")

    def v_deref(self, e):
        lv = self.addr(e)
        self.load_lv(lv)

    def v_addr_of(self, e):
        lv = self.addr(e.operand)
        if lv[0] != "mem":
            self.err(e, "cannot take the address of a bit field")

    def v_size_of(self, e):
        self.imm("x0", self.prog.resolve_type(e.of, self.mod).size)

    def v_slice(self, e):
        bt = e.value.ty
        if isinstance(bt, T.Array):
            self.addr(e.value)
            self.imm("x1", bt.count)
        else:
            self.value(e.value)
        self.push("pair")
        self.value(e.lo)
        self.push("word")
        self.value(e.hi)
        self.e("mov x4, x0")          # hi
        self.pop("x3")                # lo
        self.pop("x0", "x1")          # ptr, len
        if self.prog.debug:
            lab = self.trap(e, "slice out of range")
            self.e("cmp x3, x4")
            self.e(f"b.hi {lab}")
            self.e("cmp x4, x1")
            self.e(f"b.hi {lab}")
        self.e("sub x1, x4, x3")
        self.e("mov x2, x0")
        self.e("mov x0, x3")
        self.scale_add(bt.inner.size)

    def v_call(self, e):
        if e.builtin in BUILTIN_VOID:
            self.e(BUILTIN_VOID[e.builtin])
            return
        if e.builtin == "read_sysreg":
            self.e(f"mrs x0, {e.args[0].name}")
            return
        if e.builtin == "write_sysreg":
            self.value(e.args[1])
            self.e(f"msr {e.args[0].name}, x0")
            return
        sym = e.sym
        pushed = []
        later = []
        r = 0
        args = list(zip(e.args, sym.params))
        # the last argument that has to be worked out goes straight to its register(s)
        last = None
        for i, (arg, (pname, pty)) in enumerate(args):
            if not (pty.repr == "word" and self.is_simple(arg)):
                last = i
        for i, (arg, (pname, pty)) in enumerate(args):
            if pty.repr == "word" and self.is_simple(arg):
                later.append((arg, r))
            else:
                self.value(arg)
                self.coerce(arg.ty, pty)
                if i == last:
                    if r != 0 and pty.repr == "pair":
                        self.e(f"mov x{r + 1}, x1")
                    if r != 0:
                        self.e(f"mov x{r}, x0")
                else:
                    self.push(pty.repr)
                    pushed.append((pty.repr, r))
            r += 2 if pty.repr == "pair" else 1
        for rep, reg in reversed(pushed):
            if rep == "pair":
                self.pop(f"x{reg}", f"x{reg + 1}")
            else:
                self.pop(f"x{reg}")
        for arg, reg in later:
            self.simple_into(arg, f"x{reg}")
        self.e(f"bl {sym.symbol}")

    def v_unary(self, e):
        t = e.ty
        if e.op == "not":
            self.value(e.operand)
            self.e("eor x0, x0, #1")
            return
        self.value(e.operand)
        if e.op == "~":
            self.e("mvn x0, x0")
            self.normalize(t)
            return
        self.e("mov x1, x0")
        self.e("mov x0, #0")
        self.binop(e, "-", t, t)

    def v_cast(self, e):
        to = e.ty
        src = e.value.ty
        self.value(e.value)
        if isinstance(to, T.Bool):
            self.e("cmp x0, #0")
            self.e("cset x0, ne")
        elif isinstance(to, T.Int):
            if not free_cast(src, to):
                self.normalize(to)
        elif isinstance(to, T.Choice):
            self.e("mov w0, w0")
        elif isinstance(to, T.Span) and isinstance(src, T.Array):
            self.imm("x1", src.count)

    def v_binary(self, e):
        t = e.ty
        if isinstance(t, T.Ptr):
            a, b = self.operands(e.left, e.right)
            size = t.inner.size
            if size != 1:
                if size & (size - 1) == 0:
                    self.e(f"lsl x16, {b}, #{size.bit_length() - 1}")
                else:
                    self.imm("x16", size)
                    self.e(f"mul x16, {b}, x16")
                b = "x16"
            self.e(f"add x0, {a}, {b}" if e.op == "+" else f"sub x0, {a}, {b}")
            return
        if e.op in ("/", "%") and isinstance(t, T.Int) and not t.signed:
            c = self.const_of(e.right)
            if c is not None and c >= 2 and c & (c - 1) == 0:
                # unsigned division by a power of two: a shift or a mask
                r = self.reg_local(e.left)
                a = f"x{r}"
                if r is None:
                    self.value(e.left)
                    a = "x0"
                if e.op == "/":
                    self.e(f"lsr x0, {a}, #{c.bit_length() - 1}")
                else:
                    self.e(f"and x0, {a}, #{c - 1}")
                return
        a, b = self.operands(e.left, e.right, e.op)
        self.binop(e, e.op, t, e.right.ty, a, b)

    def binop(self, node, op, t, rt, a="x0", b="x1"):
        """x0 = a op b for type t (both canonical; b may be an immediate for the ops
        `operands` allows it for)."""
        dbg = self.prog.debug
        s = t.signed
        if op in ("&", "|", "^"):
            self.e({"&": "and", "|": "orr", "^": "eor"}[op] + f" x0, {a}, {b}")
            return
        if op == "<<":
            self.e(f"lsl x0, {a}, {b}")
            self.normalize(t)
            return
        if op == ">>":
            self.e(("asr" if s else "lsr") + f" x0, {a}, {b}")
            return
        if op in ("+%", "-%", "*%"):
            self.e({"+%": "add", "-%": "sub", "*%": "mul"}[op] + f" x0, {a}, {b}")
            self.normalize(t)
            return
        if op in ("+|", "-|"):
            self.e(f"mov x16, {a}")
            self.e(f"mov x1, {b}")
            self.e("mov x0, x16")
            self.saturate(op, t)
            return
        if op in ("/", "%"):
            if dbg:
                self.e(f"cbz {b}, {self.trap(node, 'division by zero')}")
            self.e(("sdiv" if s else "udiv") + f" x2, {a}, {b}")
            if op == "/":
                # canonical operands give a canonical quotient (but for MIN / -1,
                # an overflow)
                self.e("mov x0, x2")
                if dbg and s and t.bits < 64:
                    self.check_range(node, t)
            else:
                self.e(f"msub x0, x2, {b}, {a}")
            return
        if op in ("+", "-", "*"):
            if t.bits == 64:
                if op == "*":
                    if dbg:
                        if s:
                            self.e(f"smulh x2, {a}, {b}")
                            self.e(f"mul x0, {a}, {b}")
                            self.e("cmp x2, x0, asr #63")
                            self.e(f"b.ne {self.trap(node, 'integer overflow')}")
                        else:
                            self.e(f"umulh x2, {a}, {b}")
                            self.e(f"mul x0, {a}, {b}")
                            self.e(f"cbnz x2, {self.trap(node, 'integer overflow')}")
                    else:
                        self.e(f"mul x0, {a}, {b}")
                    return
                ins = "adds" if op == "+" else "subs"
                if dbg:
                    self.e(f"{ins} x0, {a}, {b}")
                    cond = "vs" if s else ("cs" if op == "+" else "cc")
                    self.e(f"b.{cond} {self.trap(node, 'integer overflow')}")
                else:
                    self.e(f"{ins[:-1]} x0, {a}, {b}")
                return
            # a result that fits (checked in debug builds; overflow is an error, not a
            # wrap, so release builds may assume it) is already canonical
            self.e({"+": "add", "-": "sub", "*": "mul"}[op] + f" x0, {a}, {b}")
            if dbg:
                self.check_range(node, t)
            return
        raise AssertionError(op)

    def check_range(self, node, t):
        """Trap unless the exact 64-bit result in x0 fits in narrow type t."""
        lab = self.trap(node, "integer overflow")
        if t.signed:
            ext = {8: "sxtb x2, w0", 16: "sxth x2, w0", 32: "sxtw x2, w0"}[t.bits]
            self.e(ext)
            self.e("cmp x2, x0")
            self.e(f"b.ne {lab}")
        else:
            self.e(f"lsr x2, x0, #{t.bits}")
            self.e(f"cbnz x2, {lab}")

    def saturate(self, op, t):
        s = t.signed
        if t.bits == 64:
            if s:
                ins = "adds" if op == "+|" else "subs"
                self.e(f"{ins} x2, x0, x1")
                self.e("asr x3, x1, #63")
                mask = "0x7fffffffffffffff" if op == "+|" else "0x8000000000000000"
                self.e(f"eor x3, x3, #{mask}")
                self.e("csel x0, x3, x2, vs")
            elif op == "+|":
                self.e("adds x0, x0, x1")
                self.e("csinv x0, x0, xzr, cc")
            else:
                self.e("subs x0, x0, x1")
                self.e("csel x0, x0, xzr, cs")
            return
        self.e(("add" if op == "+|" else "sub") + " x0, x0, x1")
        self.imm("x2", t.max)
        self.e("cmp x0, x2")
        self.e("csel x0, x2, x0, gt")
        self.imm("x2", t.min)
        self.e("cmp x0, x2")
        self.e("csel x0, x2, x0, lt")

    def v_compare(self, e):
        lt = e.left.ty
        if isinstance(lt, T.Maybe):
            other = e.left if e.right.kind == "nothing" else e.right
            self.value(other)
            reg = "x1" if lt.repr == "pair" else "x0"
            self.e(f"cmp {reg}, #0")
            self.e(f"cset x0, {'eq' if e.op == '==' else 'ne'}")
            return
        a, b = self.operands(e.left, e.right, "cmp")
        self.e(f"cmp {a}, {b}")
        signed = isinstance(lt, T.Int) and lt.signed
        cond = {"==": "eq", "!=": "ne",
                "<": "lt" if signed else "lo", ">": "gt" if signed else "hi",
                "<=": "le" if signed else "ls", ">=": "ge" if signed else "hs"}[e.op]
        self.e(f"cset x0, {cond}")

    def v_logic(self, e):
        end = self.prog.label("lg")
        self.value(e.left)
        self.e(f"{'cbz' if e.op == 'and' else 'cbnz'} x0, {end}")
        self.value(e.right)
        self.lab(end)

    def v_unwrap(self, e):
        mt = e.value.ty
        none = self.prog.label("un")
        done = self.prog.label("ud")
        self.value(e.value)
        self.e(f"cbz {'x1' if mt.repr == 'pair' else 'x0'}, {none}")
        self.e(f"b {done}")
        self.lab(none)
        saved = self.depth
        if e.action == "value":
            self.value(e.fallback)
            self.coerce(e.fallback.ty, mt.inner)
        elif e.action == "give":
            ret = self.sym.ret
            if e.fallback is not None:
                self.value(e.fallback)
                self.coerce(e.fallback.ty, ret)
            elif isinstance(ret, T.Maybe):
                self.e("mov x0, #0")
                self.e("mov x1, #0")
            elif ret is not T.VOID:
                self.err(e, f"`else give` needs a value: `{self.sym.name}` gives a `{ret}`")
            self.leave_function(ret)
        else:
            self.jump_loop(e, e.action)
        self.depth = saved
        self.lab(done)
