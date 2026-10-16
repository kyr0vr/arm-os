"""AArch64 instruction encoding for the ArmOS assembler.

`encode(mnemonic, operands, ctx)` returns a 32-bit instruction word. Operands arrive as
already-split strings; `ctx` evaluates expressions and records relocations for operands
that name symbols.

Covers what the DULL compiler and the ArmOS boot code use, plus their close relatives.
"""

import re


class AsmError(Exception):
    pass


COND = {"eq": 0, "ne": 1, "cs": 2, "hs": 2, "cc": 3, "lo": 3, "mi": 4, "pl": 5, "vs": 6,
        "vc": 7, "hi": 8, "ls": 9, "ge": 10, "lt": 11, "gt": 12, "le": 13, "al": 14, "nv": 15}

# (op0, op1, CRn, CRm, op2)
SYSREGS = {
    "midr_el1": (3, 0, 0, 0, 0), "mpidr_el1": (3, 0, 0, 0, 5),
    "sctlr_el1": (3, 0, 1, 0, 0), "cpacr_el1": (3, 0, 1, 0, 2),
    "ttbr0_el1": (3, 0, 2, 0, 0), "ttbr1_el1": (3, 0, 2, 0, 1), "tcr_el1": (3, 0, 2, 0, 2),
    "spsr_el1": (3, 0, 4, 0, 0), "elr_el1": (3, 0, 4, 0, 1), "sp_el0": (3, 0, 4, 1, 0),
    "spsel": (3, 0, 4, 2, 0), "currentel": (3, 0, 4, 2, 2), "daif": (3, 3, 4, 2, 1),
    "esr_el1": (3, 0, 5, 2, 0), "far_el1": (3, 0, 6, 0, 0), "par_el1": (3, 0, 7, 4, 0),
    "mair_el1": (3, 0, 10, 2, 0), "vbar_el1": (3, 0, 12, 0, 0),
    "contextidr_el1": (3, 0, 13, 0, 1), "tpidr_el1": (3, 0, 13, 0, 4),
    "tpidr_el0": (3, 3, 13, 0, 2), "tpidrro_el0": (3, 3, 13, 0, 3),
    "cntfrq_el0": (3, 3, 14, 0, 0), "cntpct_el0": (3, 3, 14, 0, 1), "cntvct_el0": (3, 3, 14, 0, 2),
    "cntp_tval_el0": (3, 3, 14, 2, 0), "cntp_ctl_el0": (3, 3, 14, 2, 1), "cntp_cval_el0": (3, 3, 14, 2, 2),
    "cntv_tval_el0": (3, 3, 14, 3, 0), "cntv_ctl_el0": (3, 3, 14, 3, 1), "cntv_cval_el0": (3, 3, 14, 3, 2),
    "cntkctl_el1": (3, 0, 14, 1, 0),
    "sctlr_el2": (3, 4, 1, 0, 0), "hcr_el2": (3, 4, 1, 1, 0), "cptr_el2": (3, 4, 1, 1, 2),
    "spsr_el2": (3, 4, 4, 0, 0), "elr_el2": (3, 4, 4, 0, 1), "sp_el1": (3, 4, 4, 1, 0),
    "esr_el2": (3, 4, 5, 2, 0), "far_el2": (3, 4, 6, 0, 0), "vbar_el2": (3, 4, 12, 0, 0),
    "cnthctl_el2": (3, 4, 14, 1, 0), "cntvoff_el2": (3, 4, 14, 0, 3),
    "tpidr_el2": (3, 4, 13, 0, 2), "mair_el2": (3, 4, 10, 2, 0), "tcr_el2": (3, 4, 2, 0, 2),
    "ttbr0_el2": (3, 4, 2, 0, 0),
    "vpidr_el2": (3, 4, 0, 0, 0), "vmpidr_el2": (3, 4, 0, 0, 5), "isr_el1": (3, 0, 12, 1, 0),
    "id_aa64mmfr0_el1": (3, 0, 0, 7, 0), "ctr_el0": (3, 3, 0, 0, 1),
}

BARRIER_OPTS = {"sy": 15, "st": 14, "ld": 13, "ish": 11, "ishst": 10, "ishld": 9,
                "nsh": 7, "nshst": 6, "nshld": 5, "osh": 3, "oshst": 2, "oshld": 1}

HINTS = {"nop": 0, "yield": 1, "wfe": 2, "wfi": 3, "sev": 4, "sevl": 5}

# ---------------------------------------------------------------- registers

REG_RE = re.compile(r"^([xw])(\d+)$")


class Reg:
    __slots__ = ("num", "is64", "sp")

    def __init__(self, num, is64, sp=False):
        self.num, self.is64, self.sp = num, is64, sp


def reg(text, allow_sp=False, allow_zr=True):
    t = text.strip().lower()
    if t in ("sp", "wsp"):
        if not allow_sp:
            raise AsmError(f"sp is not allowed here: {text}")
        return Reg(31, t == "sp", sp=True)
    if t in ("xzr", "wzr"):
        if not allow_zr:
            raise AsmError(f"the zero register is not allowed here: {text}")
        return Reg(31, t == "xzr")
    m = REG_RE.match(t)
    if not m or int(m.group(2)) > 30:
        raise AsmError(f"expected a register, found {text!r}")
    return Reg(int(m.group(2)), m.group(1) == "x")


def is_reg(text):
    t = text.strip().lower()
    return t in ("sp", "wsp", "xzr", "wzr") or bool(REG_RE.match(t))


def same_width(*regs):
    if len({r.is64 for r in regs}) != 1:
        raise AsmError("registers must all be x or all be w")


# ---------------------------------------------------------------- immediates

def bitmask_imm(value, size):
    """Encode `value` as an AArch64 logical immediate. Returns (N, immr, imms) or None."""
    full = (1 << size) - 1
    value &= full
    if value == 0 or value == full:
        return None
    e = size
    while e > 2:
        half = e // 2
        m = (1 << half) - 1
        if (value & m) != ((value >> half) & m):
            break
        e = half
    elem = value & ((1 << e) - 1)
    ones = bin(elem).count("1")
    run = (1 << ones) - 1
    for r in range(e):
        rot = ((run >> r) | (run << (e - r))) & ((1 << e) - 1)
        if rot == elem:
            immr = r
            break
    else:
        return None
    n = 1 if e == 64 else 0
    imms = ((~(e * 2 - 1)) & 0x3F) | (ones - 1)
    return n, immr, imms


def shift_operand(text):
    """'lsl #3' -> ('lsl', 3)."""
    m = re.match(r"^(lsl|lsr|asr|ror)\s+#?(.+)$", text.strip().lower())
    if not m:
        raise AsmError(f"expected a shift like `lsl #3`, found {text!r}")
    return m.group(1), m.group(2)


# ---------------------------------------------------------------- the encoder

class Encoder:
    def __init__(self, ctx):
        self.ctx = ctx    # .imm(text) -> int ; .reloc(kind, text) -> int (placeholder value)

    def imm(self, text):
        t = text.strip()
        if t.startswith("#"):
            t = t[1:]
        return self.ctx.imm(t)

    def encode(self, mn, ops):
        mn = mn.lower()
        if mn.startswith("b.") and mn[2:] in COND:
            return self.b_cond(COND[mn[2:]], ops)
        from . import neon
        word = neon.encode(mn, ops, lambda t: self.ctx.imm(t))
        if word is not None:
            return word
        fn = getattr(self, "i_" + mn, None)
        if fn is None:
            raise AsmError(f"unknown instruction `{mn}`")
        return fn(ops)

    def need(self, ops, n, mn):
        if len(ops) != n:
            raise AsmError(f"`{mn}` takes {n} operands, found {len(ops)}")

    # ---- moves
    def i_mov(self, ops):
        self.need(ops, 2, "mov")
        if is_reg(ops[1]):
            d = reg(ops[0], allow_sp=True)
            s = reg(ops[1], allow_sp=True)
            same_width(d, s)
            if d.sp or s.sp:
                return self.addsub_imm(0, 0, d, s, 0, 0)
            return self.logical_reg(1, d, Reg(31, d.is64), s, "lsl", 0, 0)
        d = reg(ops[0], allow_sp=True)
        v = self.imm(ops[1])
        size = 64 if d.is64 else 32
        u = v & ((1 << size) - 1)
        for hw in range(size // 16):
            if u & ~(0xFFFF << (16 * hw)) & ((1 << size) - 1) == 0:
                return self.movewide(2, d, (u >> (16 * hw)) & 0xFFFF, hw)
        nu = ~v & ((1 << size) - 1)
        for hw in range(size // 16):
            if nu & ~(0xFFFF << (16 * hw)) & ((1 << size) - 1) == 0:
                return self.movewide(0, d, (nu >> (16 * hw)) & 0xFFFF, hw)
        bm = bitmask_imm(u, size)
        if bm is not None:
            n, immr, imms = bm
            return ((1 << 31) if d.is64 else 0) | 0x32000000 | (n << 22) | (immr << 16) | \
                (imms << 10) | (31 << 5) | d.num
        raise AsmError(f"cannot load {v:#x} with one mov; use movz/movk")

    def movewide(self, opc, d, imm16, hw):
        if d.sp:
            raise AsmError("cannot move a constant into sp")
        if not 0 <= imm16 <= 0xFFFF:
            raise AsmError(f"{imm16:#x} does not fit in 16 bits")
        if not d.is64 and hw > 1:
            raise AsmError("w registers only take lsl #0 or #16")
        return ((1 << 31) if d.is64 else 0) | (opc << 29) | 0x12800000 | (hw << 21) | (imm16 << 5) | d.num

    def wide(self, opc, ops, mn):
        d = reg(ops[0])
        v = self.imm(ops[1])
        hw = 0
        if len(ops) == 3:
            kind, amount = shift_operand(ops[2])
            if kind != "lsl":
                raise AsmError(f"`{mn}` only shifts with lsl")
            sh = self.ctx.imm(amount)
            if sh % 16:
                raise AsmError("the shift must be 0, 16, 32 or 48")
            hw = sh // 16
        return self.movewide(opc, d, v, hw)

    def i_movz(self, ops):
        return self.wide(2, ops, "movz")

    def i_movn(self, ops):
        return self.wide(0, ops, "movn")

    def i_movk(self, ops):
        return self.wide(3, ops, "movk")

    # ---- add / sub
    def addsub_imm(self, op, s, d, n, imm12, sh):
        if not 0 <= imm12 <= 0xFFF:
            raise AsmError(f"immediate {imm12} does not fit in 12 bits")
        return ((1 << 31) if d.is64 else 0) | (op << 30) | (s << 29) | 0x11000000 | (sh << 22) | \
            (imm12 << 10) | (n.num << 5) | d.num

    def addsub(self, op, s, ops, mn):
        if len(ops) not in (3, 4):
            raise AsmError(f"`{mn}` takes 3 or 4 operands")
        d = reg(ops[0], allow_sp=(s == 0))
        n = reg(ops[1], allow_sp=True)
        third = ops[2].strip()
        if third.startswith(":lo12:"):
            value = self.ctx.reloc("add_lo12", third[6:])
            return self.addsub_imm(op, s, d, n, value, 0)
        if not is_reg(third):
            v = self.imm(third)
            sh = 0
            if len(ops) == 4:
                kind, amount = shift_operand(ops[3])
                if kind != "lsl" or self.ctx.imm(amount) not in (0, 12):
                    raise AsmError("an add/sub immediate can only shift by lsl #12")
                sh = 1 if self.ctx.imm(amount) == 12 else 0
            if v < 0:
                return self.addsub_imm(1 - op, s, d, n, -v, sh)
            return self.addsub_imm(op, s, d, n, v, sh)
        m = reg(third)
        same_width(d, n, m)
        if d.sp or n.sp:
            # extended register form, UXTX/UXTW with optional shift
            amount = 0
            if len(ops) == 4:
                kind, a = shift_operand(ops[3])
                if kind != "lsl":
                    raise AsmError("with sp only `lsl` works")
                amount = self.ctx.imm(a)
            option = 3 if d.is64 else 2
            return ((1 << 31) if d.is64 else 0) | (op << 30) | (s << 29) | 0x0B200000 | (m.num << 16) | \
                (option << 13) | (amount << 10) | (n.num << 5) | d.num
        kind, amount = "lsl", 0
        if len(ops) == 4:
            kind, a = shift_operand(ops[3])
            amount = self.ctx.imm(a)
        shift = {"lsl": 0, "lsr": 1, "asr": 2}[kind]
        return ((1 << 31) if d.is64 else 0) | (op << 30) | (s << 29) | 0x0B000000 | (shift << 22) | \
            (m.num << 16) | (amount << 10) | (n.num << 5) | d.num

    def i_add(self, ops):
        return self.addsub(0, 0, ops, "add")

    def i_adds(self, ops):
        return self.addsub(0, 1, ops, "adds")

    def i_sub(self, ops):
        return self.addsub(1, 0, ops, "sub")

    def i_subs(self, ops):
        return self.addsub(1, 1, ops, "subs")

    def i_cmp(self, ops):
        first = reg(ops[0], allow_sp=True)
        return self.addsub(1, 1, ["xzr" if first.is64 else "wzr"] + ops, "cmp")

    def i_cmn(self, ops):
        first = reg(ops[0], allow_sp=True)
        return self.addsub(0, 1, ["xzr" if first.is64 else "wzr"] + ops, "cmn")

    def i_neg(self, ops):
        d = reg(ops[0])
        return self.addsub(1, 0, [ops[0], "xzr" if d.is64 else "wzr"] + ops[1:], "neg")

    # ---- logical
    def logical_reg(self, opc, d, n, m, kind, amount, invert):
        shift = {"lsl": 0, "lsr": 1, "asr": 2, "ror": 3}[kind]
        return ((1 << 31) if d.is64 else 0) | (opc << 29) | 0x0A000000 | (shift << 22) | (invert << 21) | \
            (m.num << 16) | (amount << 10) | (n.num << 5) | d.num

    def logical(self, opc, ops, mn, invert=0):
        if len(ops) not in (3, 4):
            raise AsmError(f"`{mn}` takes 3 or 4 operands")
        d = reg(ops[0], allow_sp=(opc != 3 and not is_reg(ops[2])))
        n = reg(ops[1])
        if not is_reg(ops[2]):
            if invert:
                raise AsmError(f"`{mn}` has no immediate form")
            size = 64 if d.is64 else 32
            bm = bitmask_imm(self.imm(ops[2]), size)
            if bm is None:
                raise AsmError(f"{ops[2]} cannot be encoded as a logical immediate")
            nbit, immr, imms = bm
            return ((1 << 31) if d.is64 else 0) | (opc << 29) | 0x12000000 | (nbit << 22) | (immr << 16) | \
                (imms << 10) | (n.num << 5) | d.num
        m = reg(ops[2])
        same_width(d, n, m)
        kind, amount = "lsl", 0
        if len(ops) == 4:
            kind, a = shift_operand(ops[3])
            amount = self.ctx.imm(a)
        return self.logical_reg(opc, d, n, m, kind, amount, invert)

    def i_and(self, ops):
        return self.logical(0, ops, "and")

    def i_orr(self, ops):
        return self.logical(1, ops, "orr")

    def i_eor(self, ops):
        return self.logical(2, ops, "eor")

    def i_ands(self, ops):
        return self.logical(3, ops, "ands")

    def i_bic(self, ops):
        return self.logical(0, ops, "bic", invert=1)

    def i_orn(self, ops):
        return self.logical(1, ops, "orn", invert=1)

    def i_tst(self, ops):
        first = reg(ops[0])
        return self.logical(3, ["xzr" if first.is64 else "wzr"] + ops, "tst")

    def i_mvn(self, ops):
        d = reg(ops[0])
        return self.logical(1, [ops[0], "xzr" if d.is64 else "wzr"] + ops[1:], "mvn", invert=1)

    # ---- bitfield
    def bitfield(self, opc, d, n, immr, imms):
        same_width(d, n)
        sf = 1 if d.is64 else 0
        return (sf << 31) | (opc << 29) | 0x13000000 | (sf << 22) | (immr << 16) | (imms << 10) | \
            (n.num << 5) | d.num

    def shift_imm_or_reg(self, ops, mn, kind):
        self.need(ops, 3, mn)
        d = reg(ops[0])
        n = reg(ops[1])
        if is_reg(ops[2]):
            m = reg(ops[2])
            same_width(d, n, m)
            op2 = {"lsl": 0, "lsr": 1, "asr": 2, "ror": 3}[kind]
            return ((1 << 31) if d.is64 else 0) | 0x1AC02000 | (m.num << 16) | (op2 << 10) | (n.num << 5) | d.num
        size = 64 if d.is64 else 32
        sh = self.imm(ops[2])
        if not 0 <= sh < size:
            raise AsmError(f"shift {sh} is out of range")
        if kind == "lsl":
            return self.bitfield(2, d, n, (-sh) % size, size - 1 - sh)
        if kind == "lsr":
            return self.bitfield(2, d, n, sh, size - 1)
        if kind == "asr":
            return self.bitfield(0, d, n, sh, size - 1)
        raise AsmError("ror by an immediate is not supported")

    def i_lsl(self, ops):
        return self.shift_imm_or_reg(ops, "lsl", "lsl")

    def i_lsr(self, ops):
        return self.shift_imm_or_reg(ops, "lsr", "lsr")

    def i_asr(self, ops):
        return self.shift_imm_or_reg(ops, "asr", "asr")

    def i_ubfx(self, ops):
        self.need(ops, 4, "ubfx")
        d, n = reg(ops[0]), reg(ops[1])
        lsb, width = self.imm(ops[2]), self.imm(ops[3])
        return self.bitfield(2, d, n, lsb, lsb + width - 1)

    def i_sbfx(self, ops):
        self.need(ops, 4, "sbfx")
        d, n = reg(ops[0]), reg(ops[1])
        lsb, width = self.imm(ops[2]), self.imm(ops[3])
        return self.bitfield(0, d, n, lsb, lsb + width - 1)

    def i_bfi(self, ops):
        self.need(ops, 4, "bfi")
        d, n = reg(ops[0]), reg(ops[1])
        size = 64 if d.is64 else 32
        lsb, width = self.imm(ops[2]), self.imm(ops[3])
        return self.bitfield(1, d, n, (-lsb) % size, width - 1)

    def i_bfxil(self, ops):
        d, n = reg(ops[0]), reg(ops[1])
        lsb, width = self.imm(ops[2]), self.imm(ops[3])
        return self.bitfield(1, d, n, lsb, lsb + width - 1)

    def extend(self, ops, mn, opc, bits):
        self.need(ops, 2, mn)
        d, n = reg(ops[0]), reg(ops[1])
        if opc == 2:   # uxt*: 32-bit form
            if d.is64:
                raise AsmError(f"`{mn}` writes a w register")
            return self.bitfield(2, d, n, 0, bits - 1)
        if n.is64:
            raise AsmError(f"`{mn}` reads a w register")
        return self.bitfield(0, d, Reg(n.num, d.is64), 0, bits - 1)

    def i_sxtb(self, ops):
        return self.extend(ops, "sxtb", 0, 8)

    def i_sxth(self, ops):
        return self.extend(ops, "sxth", 0, 16)

    def i_sxtw(self, ops):
        d = reg(ops[0])
        if not d.is64:
            raise AsmError("`sxtw` writes an x register")
        return self.extend(ops, "sxtw", 0, 32)

    def i_uxtb(self, ops):
        return self.extend(ops, "uxtb", 2, 8)

    def i_uxth(self, ops):
        return self.extend(ops, "uxth", 2, 16)

    # ---- multiply / divide
    def i_madd(self, ops):
        self.need(ops, 4, "madd")
        d, n, m, a = (reg(o) for o in ops)
        same_width(d, n, m, a)
        return ((1 << 31) if d.is64 else 0) | 0x1B000000 | (m.num << 16) | (a.num << 10) | (n.num << 5) | d.num

    def i_msub(self, ops):
        self.need(ops, 4, "msub")
        d, n, m, a = (reg(o) for o in ops)
        same_width(d, n, m, a)
        return ((1 << 31) if d.is64 else 0) | 0x1B008000 | (m.num << 16) | (a.num << 10) | (n.num << 5) | d.num

    def i_mul(self, ops):
        self.need(ops, 3, "mul")
        d = reg(ops[0])
        return self.i_madd(ops + ["xzr" if d.is64 else "wzr"])

    def mulh(self, base, ops, mn):
        self.need(ops, 3, mn)
        d, n, m = (reg(o) for o in ops)
        if not (d.is64 and n.is64 and m.is64):
            raise AsmError(f"`{mn}` works on x registers")
        return base | (m.num << 16) | (31 << 10) | (n.num << 5) | d.num

    def i_smulh(self, ops):
        return self.mulh(0x9B400000, ops, "smulh")

    def i_umulh(self, ops):
        return self.mulh(0x9BC00000, ops, "umulh")

    def div(self, o1, ops, mn):
        self.need(ops, 3, mn)
        d, n, m = (reg(o) for o in ops)
        same_width(d, n, m)
        return ((1 << 31) if d.is64 else 0) | 0x1AC00800 | (m.num << 16) | (o1 << 10) | (n.num << 5) | d.num

    def i_udiv(self, ops):
        return self.div(0, ops, "udiv")

    def i_sdiv(self, ops):
        return self.div(1, ops, "sdiv")

    # ---- conditional select
    def csel_family(self, base, ops, mn):
        self.need(ops, 4, mn)
        d, n, m = reg(ops[0]), reg(ops[1]), reg(ops[2])
        same_width(d, n, m)
        c = COND.get(ops[3].strip().lower())
        if c is None:
            raise AsmError(f"unknown condition {ops[3]!r}")
        return ((1 << 31) if d.is64 else 0) | base | (m.num << 16) | (c << 12) | (n.num << 5) | d.num

    def i_csel(self, ops):
        return self.csel_family(0x1A800000, ops, "csel")

    def i_csinc(self, ops):
        return self.csel_family(0x1A800400, ops, "csinc")

    def i_csinv(self, ops):
        return self.csel_family(0x5A800000, ops, "csinv")

    def i_csneg(self, ops):
        return self.csel_family(0x5A800400, ops, "csneg")

    def i_cset(self, ops):
        self.need(ops, 2, "cset")
        d = reg(ops[0])
        c = COND.get(ops[1].strip().lower())
        if c is None or c >= 14:
            raise AsmError(f"bad condition {ops[1]!r}")
        zr = "xzr" if d.is64 else "wzr"
        inv = [k for k, v in COND.items() if v == (c ^ 1)][0]
        return self.csel_family(0x1A800400, [ops[0], zr, zr, inv], "cset")

    def i_csetm(self, ops):
        d = reg(ops[0])
        c = COND[ops[1].strip().lower()]
        zr = "xzr" if d.is64 else "wzr"
        inv = [k for k, v in COND.items() if v == (c ^ 1)][0]
        return self.csel_family(0x5A800000, [ops[0], zr, zr, inv], "csetm")

    # ---- branches
    def i_b(self, ops):
        self.need(ops, 1, "b")
        return 0x14000000 | self.ctx.reloc("jump26", ops[0])

    def i_bl(self, ops):
        self.need(ops, 1, "bl")
        return 0x94000000 | self.ctx.reloc("call26", ops[0])

    def b_cond(self, c, ops):
        self.need(ops, 1, "b.cond")
        return 0x54000000 | (self.ctx.reloc("condbr19", ops[0]) << 5) | c

    def i_cbz(self, ops):
        self.need(ops, 2, "cbz")
        t = reg(ops[0])
        return ((1 << 31) if t.is64 else 0) | 0x34000000 | (self.ctx.reloc("condbr19", ops[1]) << 5) | t.num

    def i_cbnz(self, ops):
        self.need(ops, 2, "cbnz")
        t = reg(ops[0])
        return ((1 << 31) if t.is64 else 0) | 0x35000000 | (self.ctx.reloc("condbr19", ops[1]) << 5) | t.num

    def tb(self, base, ops, mn):
        self.need(ops, 3, mn)
        t = reg(ops[0])
        bit = self.imm(ops[1])
        if not 0 <= bit < (64 if t.is64 else 32):
            raise AsmError(f"bit {bit} out of range")
        return ((bit >> 5) << 31) | base | ((bit & 31) << 19) | (self.ctx.reloc("tstbr14", ops[2]) << 5) | t.num

    def i_tbz(self, ops):
        return self.tb(0x36000000, ops, "tbz")

    def i_tbnz(self, ops):
        return self.tb(0x37000000, ops, "tbnz")

    def i_br(self, ops):
        self.need(ops, 1, "br")
        return 0xD61F0000 | (reg(ops[0]).num << 5)

    def i_blr(self, ops):
        self.need(ops, 1, "blr")
        return 0xD63F0000 | (reg(ops[0]).num << 5)

    def i_ret(self, ops):
        r = reg(ops[0]).num if ops else 30
        return 0xD65F0000 | (r << 5)

    def i_eret(self, ops):
        return 0xD69F03E0

    # ---- address generation
    def i_adrp(self, ops):
        self.need(ops, 2, "adrp")
        d = reg(ops[0])
        v = self.ctx.reloc("adrp", ops[1])
        return 0x90000000 | ((v & 3) << 29) | (((v >> 2) & 0x7FFFF) << 5) | d.num

    def i_adr(self, ops):
        self.need(ops, 2, "adr")
        d = reg(ops[0])
        v = self.ctx.reloc("adr21", ops[1])
        return 0x10000000 | ((v & 3) << 29) | (((v >> 2) & 0x7FFFF) << 5) | d.num

    # ---- loads and stores
    LS = {
        # mnemonic: (size, opc, rt must be 64?)  opc: 00 store, 01 load, 10 signed->64, 11 signed->32
        "strb": (0, 0), "ldrb": (0, 1), "strh": (1, 0), "ldrh": (1, 1),
        "ldrsb": (0, None), "ldrsh": (1, None), "ldrsw": (2, 2),
        "str": (None, 0), "ldr": (None, 1),
    }

    def parse_mem(self, ops):
        """ops after Rt -> (base Reg, kind, offset or Reg, extra)."""
        first = ops[0].strip()
        if not first.startswith("["):
            return None
        inside_ops = []
        text = ", ".join(o.strip() for o in ops)
        m = re.match(r"^\[([^\]]*)\](!?)\s*(?:,\s*(.*))?$", text)
        if not m:
            raise AsmError(f"bad memory operand {text!r}")
        inside = [p.strip() for p in m.group(1).split(",")]
        writeback = m.group(2) == "!"
        post = m.group(3)
        base = reg(inside[0], allow_sp=True)
        if not base.is64:
            raise AsmError("addresses use x registers")
        if post is not None:
            return base, "post", self.imm(post), None
        if len(inside) == 1:
            return base, ("pre" if writeback else "off"), 0, None
        if is_reg(inside[1]):
            idx = reg(inside[1])
            extra = inside[2] if len(inside) > 2 else None
            return base, "reg", idx, extra
        off = self.imm(inside[1])
        return base, ("pre" if writeback else "off"), off, None

    def load_store(self, mn, ops):
        if len(ops) < 2:
            raise AsmError(f"`{mn}` needs a register and an address")
        size, opc = self.LS[mn]
        t = reg(ops[0])
        if size is None:
            size = 3 if t.is64 else 2
        if opc is None:      # ldrsb / ldrsh: opc depends on target width
            opc = 2 if t.is64 else 3
        elif mn in ("ldrb", "strb", "ldrh", "strh") and t.is64:
            raise AsmError(f"`{mn}` uses a w register")
        if mn == "ldrsw" and not t.is64:
            raise AsmError("`ldrsw` loads into an x register")
        mem = self.parse_mem(ops[1:])
        if mem is None:
            if mn != "ldr":
                raise AsmError(f"`{mn}` needs an address in [ ]")
            v = self.ctx.reloc("ld_prel19", ops[1])
            return (0x58000000 if t.is64 else 0x18000000) | (v << 5) | t.num
        base, kind, off, extra = mem
        if kind == "off":
            scale = 1 << size
            if off >= 0 and off % scale == 0 and off // scale <= 0xFFF:
                return (size << 30) | 0x39000000 | (opc << 22) | ((off // scale) << 10) | (base.num << 5) | t.num
            if -256 <= off <= 255:     # ldur / stur
                return (size << 30) | 0x38000000 | (opc << 22) | ((off & 0x1FF) << 12) | (base.num << 5) | t.num
            raise AsmError(f"offset {off} cannot be encoded")
        if kind in ("pre", "post"):
            if not -256 <= off <= 255:
                raise AsmError(f"offset {off} out of range for pre/post index")
            idx = 3 if kind == "pre" else 1
            return (size << 30) | 0x38000000 | (opc << 22) | ((off & 0x1FF) << 12) | (idx << 10) | \
                (base.num << 5) | t.num
        if kind == "reg":
            idx = off
            s = 0
            option = 3 if idx.is64 else 2
            if extra:
                kindx, amt = shift_operand(extra)
                if kindx != "lsl":
                    raise AsmError("register offsets only shift with lsl")
                a = self.ctx.imm(amt)
                if a not in (0, size):
                    raise AsmError(f"the shift must be 0 or {size}")
                s = 1 if a == size and a else 0
            return (size << 30) | 0x38200800 | (opc << 22) | (idx.num << 16) | (option << 13) | (s << 12) | \
                (base.num << 5) | t.num
        raise AsmError("bad address")

    def unscaled(self, opc, ops, mn):
        t = reg(ops[0])
        base, kind, off, _ = self.parse_mem(ops[1:])
        if kind != "off" or not -256 <= off <= 255:
            raise AsmError(f"`{mn}` takes [Xn, #-256..255]")
        size = 3 if t.is64 else 2
        return (size << 30) | 0x38000000 | (opc << 22) | ((off & 0x1FF) << 12) | (base.num << 5) | t.num

    def i_ldur(self, ops):
        return self.unscaled(1, ops, "ldur")

    def i_stur(self, ops):
        return self.unscaled(0, ops, "stur")

    def i_ldr(self, ops):
        return self.load_store("ldr", ops)

    def i_str(self, ops):
        return self.load_store("str", ops)

    def i_ldrb(self, ops):
        return self.load_store("ldrb", ops)

    def i_strb(self, ops):
        return self.load_store("strb", ops)

    def i_ldrh(self, ops):
        return self.load_store("ldrh", ops)

    def i_strh(self, ops):
        return self.load_store("strh", ops)

    def i_ldrsb(self, ops):
        return self.load_store("ldrsb", ops)

    def i_ldrsh(self, ops):
        return self.load_store("ldrsh", ops)

    def i_ldrsw(self, ops):
        return self.load_store("ldrsw", ops)

    def pair(self, load, ops, mn):
        if len(ops) < 3:
            raise AsmError(f"`{mn}` needs two registers and an address")
        t1, t2 = reg(ops[0]), reg(ops[1])
        same_width(t1, t2)
        base, kind, off, _ = self.parse_mem(ops[2:])
        if kind == "reg":
            raise AsmError(f"`{mn}` cannot use a register offset")
        scale = 8 if t1.is64 else 4
        if off % scale:
            raise AsmError(f"offset {off} must be a multiple of {scale}")
        imm7 = off // scale
        if not -64 <= imm7 <= 63:
            raise AsmError(f"offset {off} out of range")
        idx = {"post": 1, "off": 2, "pre": 3}[kind]
        opc = 2 if t1.is64 else 0
        return (opc << 30) | 0x28000000 | (idx << 23) | (load << 22) | ((imm7 & 0x7F) << 15) | \
            (t2.num << 10) | (base.num << 5) | t1.num

    def i_ldp(self, ops):
        return self.pair(1, ops, "ldp")

    def i_stp(self, ops):
        return self.pair(0, ops, "stp")

    # ---- system
    def sysreg(self, text):
        t = text.strip().lower()
        if t in SYSREGS:
            return SYSREGS[t]
        m = re.match(r"^s([0-3])_([0-7])_c(\d+)_c(\d+)_([0-7])$", t)
        if m:
            return tuple(int(g) for g in m.groups())
        raise AsmError(f"unknown system register {text!r}")

    def i_mrs(self, ops):
        self.need(ops, 2, "mrs")
        t = reg(ops[0])
        op0, op1, crn, crm, op2 = self.sysreg(ops[1])
        return 0xD5300000 | ((op0 - 2) << 19) | (op1 << 16) | (crn << 12) | (crm << 8) | (op2 << 5) | t.num

    def i_msr(self, ops):
        self.need(ops, 2, "msr")
        name = ops[0].strip().lower()
        if name in ("daifset", "daifclr", "spsel"):
            op2 = {"daifset": 6, "daifclr": 7, "spsel": 5}[name]
            op1 = 3 if name != "spsel" else 0
            return 0xD500401F | (op1 << 16) | ((self.imm(ops[1]) & 15) << 8) | (op2 << 5)
        t = reg(ops[1])
        op0, op1, crn, crm, op2 = self.sysreg(ops[0])
        return 0xD5100000 | ((op0 - 2) << 19) | (op1 << 16) | (crn << 12) | (crm << 8) | (op2 << 5) | t.num

    def barrier(self, op2, ops, mn):
        opt = 15
        if ops:
            o = ops[0].strip().lower()
            if o in BARRIER_OPTS:
                opt = BARRIER_OPTS[o]
            else:
                opt = self.imm(o)
        return 0xD503301F | (opt << 8) | (op2 << 5)

    def i_dsb(self, ops):
        return self.barrier(4, ops, "dsb")

    def i_dmb(self, ops):
        return self.barrier(5, ops, "dmb")

    def i_isb(self, ops):
        return self.barrier(6, ops if ops else ["sy"], "isb")

    def hint(self, n):
        return 0xD503201F | (n << 5)

    def i_nop(self, ops):
        return self.hint(0)

    def i_yield(self, ops):
        return self.hint(1)

    def i_wfe(self, ops):
        return self.hint(2)

    def i_wfi(self, ops):
        return self.hint(3)

    def i_sev(self, ops):
        return self.hint(4)

    def i_sevl(self, ops):
        return self.hint(5)

    def exc(self, base, ops):
        v = self.imm(ops[0]) if ops else 0
        if not 0 <= v <= 0xFFFF:
            raise AsmError("the immediate must fit in 16 bits")
        return base | (v << 5)

    def i_svc(self, ops):
        return self.exc(0xD4000001, ops)

    def i_hvc(self, ops):
        return self.exc(0xD4000002, ops)

    def i_smc(self, ops):
        return self.exc(0xD4000003, ops)

    def i_brk(self, ops):
        return self.exc(0xD4200000, ops)

    def i_hlt(self, ops):
        return self.exc(0xD4400000, ops)

    # ---- exclusive and acquire/release (spinlocks)
    def excl(self, base32, ops, mn, status=False):
        if status:
            self.need(ops, 3, mn)
            s, t = reg(ops[0]), reg(ops[1])
            if s.is64:
                raise AsmError(f"`{mn}` status register is a w register")
            rest = ops[2:]
        else:
            self.need(ops, 2, mn)
            t = reg(ops[0])
            s = None
            rest = ops[1:]
        base, kind, off, _ = self.parse_mem(rest)
        if kind != "off" or off != 0:
            raise AsmError(f"`{mn}` takes a plain [Xn] address")
        word = base32 | ((1 << 30) if t.is64 else 0) | (base.num << 5) | t.num
        if s is not None:
            word = (word & ~(0x1F << 16)) | (s.num << 16)
        return word

    def i_ldxr(self, ops):
        return self.excl(0x885F7C00, ops, "ldxr")

    def i_ldaxr(self, ops):
        return self.excl(0x885FFC00, ops, "ldaxr")

    def i_stxr(self, ops):
        return self.excl(0x88007C00, ops, "stxr", status=True)

    def i_stlxr(self, ops):
        return self.excl(0x8800FC00, ops, "stlxr", status=True)

    def i_ldar(self, ops):
        return self.excl(0x88DFFC00, ops, "ldar")

    def i_stlr(self, ops):
        return self.excl(0x889FFC00, ops, "stlr")

    def i_clrex(self, ops):
        return 0xD503305F | (15 << 8)

    # ---- cache and TLB maintenance (SYS aliases)
    def sys(self, op1, crn, crm, op2, rt=31):
        return 0xD5080000 | (op1 << 16) | (crn << 12) | (crm << 8) | (op2 << 5) | rt

    def i_tlbi(self, ops):
        op = ops[0].strip().lower()
        table = {"vmalle1": (0, 8, 7, 0), "vmalle1is": (0, 8, 3, 0), "alle2": (4, 8, 7, 0),
                 "alle2is": (4, 8, 3, 0), "vae1": (0, 8, 7, 1), "vae1is": (0, 8, 3, 1)}
        if op not in table:
            raise AsmError(f"unsupported `tlbi {op}`")
        rt = reg(ops[1]).num if len(ops) > 1 else 31
        return self.sys(*table[op], rt)

    def i_dc(self, ops):
        self.need(ops, 2, "dc")
        op = ops[0].strip().lower()
        table = {"civac": (3, 7, 14, 1), "cvac": (3, 7, 10, 1), "cvau": (3, 7, 11, 1),
                 "ivac": (0, 7, 6, 1), "zva": (3, 7, 4, 1), "cisw": (0, 7, 14, 2), "isw": (0, 7, 6, 2)}
        if op not in table:
            raise AsmError(f"unsupported `dc {op}`")
        return self.sys(*table[op], reg(ops[1]).num)

    def i_ic(self, ops):
        op = ops[0].strip().lower()
        table = {"iallu": (0, 7, 5, 0), "ialluis": (0, 7, 1, 0)}
        if op not in table:
            raise AsmError(f"unsupported `ic {op}`")
        op1, crn, crm, op2 = table[op]
        return 0xD508001F | (op1 << 16) | (crn << 12) | (crm << 8) | (op2 << 5)
