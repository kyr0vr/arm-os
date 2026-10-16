"""Advanced SIMD (NEON) instructions for the ArmOS assembler: the integer vector
operations the video code uses. `encode(mn, ops, imm)` gives the instruction word, or
None if `mn` is not one of these. `imm(text)` evaluates an immediate.

Vector registers are written with their arrangement: v3.16b, v0.4s. Register lists
for loads and stores arrive split at their commas ({v0.16b, v1.16b}) and are joined
again here.
"""

import re

from .encode import AsmError, reg

ARR = {"8b": (0, 0), "16b": (1, 0), "4h": (0, 1), "8h": (1, 1), "2s": (0, 2), "4s": (1, 2),
       "1d": (0, 3), "2d": (1, 3)}                       # arrangement -> (Q, size)

# Rd, Rn, Rm all alike
SAME = {"add": 0x0E208400, "sub": 0x2E208400, "mul": 0x0E209C00, "mla": 0x0E209400,
        "mls": 0x2E209400, "smax": 0x0E206400, "smin": 0x0E206C00, "umax": 0x2E206400,
        "umin": 0x2E206C00, "urhadd": 0x2E201400, "uhadd": 0x2E200400,
        "zip1": 0x0E003800, "zip2": 0x0E007800, "uzp1": 0x0E001800, "uzp2": 0x0E005800,
        "trn1": 0x0E002800, "trn2": 0x0E006800}
# bitwise: bytes only, the size field is part of the opcode
BITWISE = {"and": 0x0E201C00, "orr": 0x0EA01C00, "eor": 0x2E201C00, "bic": 0x0E601C00}
# Rd wide, Rn and Rm narrow (the `2` forms use the upper halves)
LONG = {"uaddl": 0x2E200000, "saddl": 0x0E200000, "usubl": 0x2E202000, "ssubl": 0x0E202000,
        "umull": 0x2E20C000, "smull": 0x0E20C000, "umlal": 0x2E208000, "smlal": 0x0E208000,
        "umlsl": 0x2E20A000, "smlsl": 0x0E20A000}
# Rd wide, Rn wide, Rm narrow
WIDE = {"uaddw": 0x2E201000, "saddw": 0x0E201000, "usubw": 0x2E203000, "ssubw": 0x0E203000}
# shift by an immediate, same arrangement; field = 2 * esize - shift (right) or esize + shift (left)
SHIFT_RIGHT = {"ushr": 0x2F000400, "sshr": 0x0F000400, "urshr": 0x2F002400, "srshr": 0x0F002400,
               "usra": 0x2F001400, "ssra": 0x0F001400}
SHIFT_LEFT = {"shl": 0x0F005400}
# Rd wide from Rn narrow, field = esize(narrow) + shift
SHIFT_LONG = {"ushll": 0x2F00A400, "sshll": 0x0F00A400}
# Rd narrow from Rn wide, field = 2 * esize(narrow) - shift
SHIFT_NARROW = {"shrn": 0x0F008400, "rshrn": 0x0F008C00, "sqshrun": 0x2F008400, "sqrshrun": 0x2F008C00,
                "sqshrn": 0x0F009400, "sqrshrn": 0x0F009C00, "uqshrn": 0x2F009400, "uqrshrn": 0x2F009C00}
# Rd narrow from Rn wide, no shift
NARROW = {"xtn": 0x0E212800, "sqxtn": 0x0E214800, "uqxtn": 0x2E214800, "sqxtun": 0x2E212800}
# Rd, Rn alike
UNARY = {"neg": 0x2E20B800, "abs": 0x0E20B800}
# loads and stores of whole registers: opcode by (instruction, register count)
STRUCT = {("ld1", 1): 7, ("ld1", 2): 10, ("ld1", 3): 6, ("ld1", 4): 2, ("ld2", 2): 8, ("ld3", 3): 4,
          ("ld4", 4): 0, ("st1", 1): 7, ("st1", 2): 10, ("st1", 3): 6, ("st1", 4): 2, ("st2", 2): 8,
          ("st3", 3): 4, ("st4", 4): 0}

VREG_RE = re.compile(r"^v(\d+)\.(\w+)$")


def vreg(text):
    """'v3.16b' -> (3, Q, size)."""
    m = VREG_RE.match(text.strip().lower())
    if not m or int(m.group(1)) > 31 or m.group(2) not in ARR:
        raise AsmError(f"expected a vector register like v0.16b, found {text!r}")
    q, size = ARR[m.group(2)]
    return int(m.group(1)), q, size


def is_vreg(text):
    return bool(VREG_RE.match(text.strip().lower()))


def need(ops, n, mn):
    if len(ops) != n:
        raise AsmError(f"`{mn}` takes {n} operands, found {len(ops)}")


def split2(mn):
    """'umull2' -> ('umull', 1); 'umull' -> ('umull', 0)."""
    if mn.endswith("2") and mn[:-1] in LONG or mn[:-1] in WIDE or mn[:-1] in SHIFT_LONG \
            or mn[:-1] in SHIFT_NARROW or mn[:-1] in NARROW or mn[:-1] in ("uxtl", "sxtl"):
        return mn[:-1], 1
    return mn, 0


def shift_amount(text, imm):
    t = text.strip()
    if not t.startswith("#"):
        raise AsmError(f"expected a shift like #3, found {text!r}")
    return imm(t[1:])


ELEM_RE = re.compile(r"^v(\d+)\.([bhsd])\[(\d+)\]$")


def velem(text):
    """'v3.s[1]' -> (3, size, index)."""
    m = ELEM_RE.match(text.strip().lower())
    if not m or int(m.group(1)) > 31:
        raise AsmError(f"expected a vector element like v0.s[1], found {text!r}")
    size = "bhsd".index(m.group(2))
    index = int(m.group(3))
    if index >= 16 >> size:
        raise AsmError(f"element index {index} out of range")
    return int(m.group(1)), size, index


def encode(mn, ops, imm):
    if mn.lower() == "umov":
        need(ops, 2, "umov")
        r = reg(ops[0])
        n, size, index = velem(ops[1])
        if (size == 3) != r.is64:
            raise AsmError("`umov`: x for a d element, w otherwise")
        imm5 = ((index << 1) | 1) << size
        return 0x0E003C00 | ((1 if size == 3 else 0) << 30) | (imm5 << 16) | (n << 5) | r.num
    if not ops or not (is_vreg(ops[0]) or ops[0].strip().startswith("{")):
        return None
    mn = mn.lower()
    base, upper = split2(mn)
    if mn == "mov" and ops and is_vreg(ops[0]):
        need(ops, 2, mn)
        d, q, size = vreg(ops[0])
        n, q2, _ = vreg(ops[1])
        return BITWISE["orr"] | (q << 30) | (n << 16) | (n << 5) | d
    if mn in SAME or mn in BITWISE:
        need(ops, 3, mn)
        d, q, size = vreg(ops[0])
        n, qn, sn = vreg(ops[1])
        m, qm, sm = vreg(ops[2])
        if (q, size) != (qn, sn) or (q, size) != (qm, sm):
            raise AsmError(f"`{mn}` needs three registers of one arrangement")
        if mn in BITWISE:
            if size != 0:
                raise AsmError(f"`{mn}` works on bytes (8b or 16b)")
            return BITWISE[mn] | (q << 30) | (m << 16) | (n << 5) | d
        if size == 3 and mn not in ("add", "sub", "zip1", "zip2", "uzp1", "uzp2", "trn1", "trn2"):
            raise AsmError(f"`{mn}` has no 64-bit lanes")
        return SAME[mn] | (q << 30) | (size << 22) | (m << 16) | (n << 5) | d
    if mn in UNARY:
        need(ops, 2, mn)
        d, q, size = vreg(ops[0])
        n, qn, sn = vreg(ops[1])
        if (q, size) != (qn, sn):
            raise AsmError(f"`{mn}` needs two registers of one arrangement")
        return UNARY[mn] | (q << 30) | (size << 22) | (n << 5) | d
    if base in LONG or base in WIDE:
        need(ops, 3, mn)
        d, qd, sd = vreg(ops[0])
        n, qn, sn = vreg(ops[1])
        m, qm, sm = vreg(ops[2])
        size = sd - 1
        if qd != 1 or size < 0 or qm != upper or sm != size or \
                (base in LONG and (qn, sn) != (qm, sm)) or (base in WIDE and (qn, sn) != (qd, sd)):
            raise AsmError(f"`{mn}`: the arrangements do not fit together")
        table = LONG if base in LONG else WIDE
        return table[base] | (upper << 30) | (size << 22) | (m << 16) | (n << 5) | d
    if mn in SHIFT_RIGHT or mn in SHIFT_LEFT:
        need(ops, 3, mn)
        d, q, size = vreg(ops[0])
        n, qn, sn = vreg(ops[1])
        if (q, size) != (qn, sn):
            raise AsmError(f"`{mn}` needs two registers of one arrangement")
        esize = 8 << size
        sh = shift_amount(ops[2], imm)
        if mn in SHIFT_LEFT:
            if not 0 <= sh < esize:
                raise AsmError(f"shift {sh} out of range")
            field = esize + sh
            word = SHIFT_LEFT[mn]
        else:
            if not 1 <= sh <= esize:
                raise AsmError(f"shift {sh} out of range")
            field = 2 * esize - sh
            word = SHIFT_RIGHT[mn]
        return word | (q << 30) | (field << 16) | (n << 5) | d
    if base in SHIFT_LONG or base in ("uxtl", "sxtl"):
        word = SHIFT_LONG.get(base) or SHIFT_LONG["ushll" if base == "uxtl" else "sshll"]
        if base in ("uxtl", "sxtl"):
            need(ops, 2, mn)
            sh = 0
        else:
            need(ops, 3, mn)
            sh = shift_amount(ops[2], imm)
        d, qd, sd = vreg(ops[0])
        n, qn, sn = vreg(ops[1])
        if qd != 1 or sd != sn + 1 or qn != upper or sn > 2:
            raise AsmError(f"`{mn}`: the arrangements do not fit together")
        esize = 8 << sn
        if not 0 <= sh < esize:
            raise AsmError(f"shift {sh} out of range")
        return word | (upper << 30) | ((esize + sh) << 16) | (n << 5) | d
    if base in SHIFT_NARROW or base in NARROW:
        d, qd, sd = vreg(ops[0])
        n, qn, sn = vreg(ops[1])
        if qn != 1 or sn != sd + 1 or qd != upper or sd > 2:
            raise AsmError(f"`{mn}`: the arrangements do not fit together")
        if base in NARROW:
            need(ops, 2, mn)
            return NARROW[base] | (upper << 30) | (sd << 22) | (n << 5) | d
        need(ops, 3, mn)
        esize = 8 << sd
        sh = shift_amount(ops[2], imm)
        if not 1 <= sh <= esize:
            raise AsmError(f"shift {sh} out of range")
        return SHIFT_NARROW[base] | (upper << 30) | ((2 * esize - sh) << 16) | (n << 5) | d
    if mn == "ext":
        need(ops, 4, mn)
        d, q, size = vreg(ops[0])
        n, qn, sn = vreg(ops[1])
        m, qm, sm = vreg(ops[2])
        if size != 0 or (q, size) != (qn, sn) or (q, size) != (qm, sm):
            raise AsmError("`ext` needs three byte registers of one arrangement")
        k = shift_amount(ops[3], imm)
        if not 0 <= k < (16 if q else 8):
            raise AsmError(f"ext index {k} out of range")
        return 0x2E000000 | (q << 30) | (m << 16) | (k << 11) | (n << 5) | d
    if mn == "dup":
        need(ops, 2, mn)
        d, q, size = vreg(ops[0])
        r = reg(ops[1])
        if size == 3 and not r.is64 or size < 3 and r.is64:
            raise AsmError("`dup` from a register: x for 64-bit lanes, w otherwise")
        imm5 = 1 << size
        return 0x0E000C00 | (q << 30) | (imm5 << 16) | (r.num << 5) | d
    if mn == "movi":
        need(ops, 2, mn)
        d, q, size = vreg(ops[0])
        v = shift_amount(ops[1], imm)
        if not 0 <= v <= 255 or size == 3:
            raise AsmError("`movi` takes a byte value (0-255) for 8-, 16- or 32-bit lanes")
        word = {0: 0x0F00E400, 1: 0x0F008400, 2: 0x0F000400}[size]
        return word | (q << 30) | ((v >> 5) << 16) | ((v & 31) << 5) | d
    if mn in ("ld1", "ld2", "ld3", "ld4", "st1", "st2", "st3", "st4"):
        return structure(mn, ops, imm)
    return None


def structure(mn, ops, imm):
    """ld1 {v0.16b, v1.16b}, [x0] / [x0], #32 / [x0], x2."""
    regs = []
    i = 0
    text = ops[0].strip()
    if not text.startswith("{"):
        raise AsmError(f"`{mn}` needs a register list like {{v0.16b}}")
    while True:
        part = ops[i].strip()
        i += 1
        last = part.endswith("}")
        regs.append(part.strip("{}").strip())
        if last:
            break
        if i >= len(ops):
            raise AsmError("unclosed register list")
    rest = ops[i:]
    vs = [vreg(r) for r in regs]
    first, q, size = vs[0]
    for k, (v, qk, sk) in enumerate(vs):
        if (qk, sk) != (q, size) or v != (first + k) % 32:
            raise AsmError("the registers in the list must follow on and share one arrangement")
    key = (mn, len(vs))
    if key not in STRUCT:
        raise AsmError(f"`{mn}` does not take {len(vs)} registers")
    if size == 3 and q == 0 and mn[2] != "1":
        raise AsmError(f"`{mn}` has no 1d form")
    if not rest or not rest[0].strip().startswith("[") or not rest[0].strip().endswith("]"):
        raise AsmError(f"`{mn}` needs an address like [x0]")
    base = reg(rest[0].strip()[1:-1], allow_sp=True)
    if not base.is64:
        raise AsmError("addresses use x registers")
    load = mn.startswith("ld")
    word = (q << 30) | (STRUCT[key] << 12) | (size << 10) | (base.num << 5) | first
    if len(rest) == 1:
        return word | (0x0C400000 if load else 0x0C000000)
    if len(rest) != 2:
        raise AsmError(f"`{mn}`: too many operands")
    post = rest[1].strip()
    if post.startswith("#"):
        n = imm(post[1:])
        if n != len(vs) * (16 if q else 8):
            raise AsmError(f"`{mn}` can only step by the bytes it moves ({len(vs) * (16 if q else 8)})")
        return word | (0x0CDF0000 if load else 0x0C9F0000)
    m = reg(post, allow_zr=False)
    if not m.is64:
        raise AsmError("the step register must be an x register")
    return word | (0x0CC00000 if load else 0x0C800000) | (m.num << 16)
