"""The ArmOS linker: objects from the assembler -> a flat image (and a minimal ELF).

Reads the small subset of GNU linker-script syntax our link.ld files use:

    ENTRY(sym)
    SECTIONS {
        . = <expr>;
        .name [(NOLOAD)] : [ALIGN(n)] { *(pattern) ... sym = .; . = ALIGN(n); ... }
        . = ALIGN(n);
        . += <expr>;
        sym = .;
    }

Input sections are placed in pattern order, then file order, like lld. Gaps inside
code are filled the way lld fills them, so images come out byte-identical.
"""

import fnmatch
import re
import struct

from .encode import AsmError

# lld pads gaps inside executable output sections with this trap instruction (brk #0x...).
CODE_FILL = None  # decided by comparison with lld; None means zero fill


class LinkError(AsmError):
    pass


# ---------------------------------------------------------------- linker script

def parse_script(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    entry = "_start"
    m = re.search(r"ENTRY\(\s*([\w.$]+)\s*\)", text)
    if m:
        entry = m.group(1)
    m = re.search(r"SECTIONS\s*\{(.*)\}\s*$", text, flags=re.S)
    if not m:
        raise LinkError("linker script has no SECTIONS { }")
    body = m.group(1)
    cmds = []
    i = 0
    tok = re.compile(r"\s*(?:"
                     r"(?P<osec>\.[\w.]+)\s*(?P<noload>\(NOLOAD\))?\s*:\s*(?:ALIGN\((?P<oalign>[^)]*)\))?\s*\{(?P<inner>[^}]*)\}"
                     r"|(?P<assign>[\w.$]+)\s*(?P<op>\+?=)\s*(?P<expr>[^;]+);"
                     r")", re.S)
    while i < len(body):
        if body[i:].strip() == "":
            break
        mm = tok.match(body, i)
        if not mm:
            raise LinkError(f"cannot read linker script near: {body[i:i + 40]!r}")
        if mm.group("osec"):
            inner = []
            for part in re.finditer(r"\*\(([^)]*)\)|([\w.$]+)\s*(\+?=)\s*([^;]+);", mm.group("inner")):
                if part.group(1) is not None:
                    inner.append(("in", part.group(1).split()))
                else:
                    inner.append(("set", part.group(2), part.group(3), part.group(4).strip()))
            cmds.append(("section", mm.group("osec"), bool(mm.group("noload")), mm.group("oalign"), inner))
        else:
            cmds.append(("set", mm.group("assign"), mm.group("op"), mm.group("expr").strip()))
        i = mm.end()
    return entry, cmds


def eval_expr(text, dot, symbols):
    t = text.strip()

    def align(m):
        n = eval_expr(m.group(1), dot, symbols)
        return str((dot + n - 1) // n * n)
    t = re.sub(r"ALIGN\(([^()]*)\)", align, t)
    t = t.replace(".", str(dot)) if re.fullmatch(r"\s*\.\s*", t) else re.sub(r"(?<![\w$])\.(?![\w$])", str(dot), t)
    for name in sorted(symbols, key=len, reverse=True):
        t = re.sub(rf"(?<![\w.$]){re.escape(name)}(?![\w.$])", str(symbols[name]), t)
    if not re.fullmatch(r"[\s0-9a-fA-FxX+\-*/()<>|&~]*", t):
        raise LinkError(f"cannot evaluate {text!r} in the linker script")
    return int(eval(t, {"__builtins__": {}}, {}))


# ---------------------------------------------------------------- relocation

def patch(img, off, kind, S, P, where):
    word = struct.unpack_from("<I", img, off)[0] if kind != "abs64" else None

    def fits(v, bits):
        return -(1 << (bits - 1)) <= v < (1 << (bits - 1))

    if kind in ("jump26", "call26"):
        d = S - P
        if d % 4 or not fits(d >> 2, 26):
            raise LinkError(f"{where}: branch target out of range")
        word |= (d >> 2) & 0x3FFFFFF
    elif kind == "condbr19":
        d = S - P
        if d % 4 or not fits(d >> 2, 19):
            raise LinkError(f"{where}: conditional branch target out of range")
        word |= ((d >> 2) & 0x7FFFF) << 5
    elif kind == "tstbr14":
        d = S - P
        if d % 4 or not fits(d >> 2, 14):
            raise LinkError(f"{where}: test-and-branch target out of range")
        word |= ((d >> 2) & 0x3FFF) << 5
    elif kind == "ld_prel19":
        d = S - P
        if d % 4 or not fits(d >> 2, 19):
            raise LinkError(f"{where}: literal out of range")
        word |= ((d >> 2) & 0x7FFFF) << 5
    elif kind == "adr21":
        d = S - P
        if not fits(d, 21):
            raise LinkError(f"{where}: adr target out of range")
        word |= ((d & 3) << 29) | (((d >> 2) & 0x7FFFF) << 5)
    elif kind == "adrp":
        d = (S >> 12) - (P >> 12)
        if not fits(d, 21):
            raise LinkError(f"{where}: adrp target out of range")
        word |= ((d & 3) << 29) | (((d >> 2) & 0x7FFFF) << 5)
    elif kind == "add_lo12":
        word |= (S & 0xFFF) << 10
    elif kind == "abs64":
        struct.pack_into("<Q", img, off, S & 0xFFFF_FFFF_FFFF_FFFF)
        return
    elif kind == "abs32":
        struct.pack_into("<I", img, off, S & 0xFFFFFFFF)
        return
    else:
        raise LinkError(f"{where}: unknown relocation {kind}")
    struct.pack_into("<I", img, off, word)


# ---------------------------------------------------------------- the linker

class Image:
    def __init__(self, base, data, memsize, entry, symbols):
        self.base = base          # address of data[0]
        self.data = data          # bytes of all loadable, non-NOBITS content
        self.memsize = memsize    # bytes from base to the end of .bss
        self.entry = entry
        self.symbols = symbols

    def elf(self):
        """A minimal ELF64 executable with one loadable segment (enough for QEMU -kernel)."""
        offset = 0x1000
        ehdr = struct.pack("<4sBBBBB7sHHIQQQIHHHHHH",
                           b"\x7fELF", 2, 1, 1, 0, 0, bytes(7),
                           2, 183, 1, self.entry, 64, 0, 0, 64, 56, 1, 0, 0, 0)
        phdr = struct.pack("<IIQQQQQQ", 1, 7, offset, self.base, self.base,
                           len(self.data), max(self.memsize, len(self.data)), 0x1000)
        head = ehdr + phdr
        return head + bytes(offset - len(head)) + self.data


def link(objects, script_text):
    entry_name, cmds = parse_script(script_text)
    placed = set()
    layout = []           # (address, input section, object)
    out_sections = []     # (name, start, end, nobits)
    symbols = {}          # script-defined
    dot = 0

    # ---- addresses
    for cmd in cmds:
        if cmd[0] == "set":
            _, name, op, expr = cmd
            v = eval_expr(expr, dot, symbols)
            if name == ".":
                dot = dot + v if op == "+=" else v
            else:
                symbols[name] = v
            continue
        _, oname, noload, oalign, inner = cmd
        inputs = []
        for item in inner:
            if item[0] == "in":
                for pattern in item[1]:
                    for obj in objects:
                        for sec in obj.sections.values():
                            if id(sec) in placed or not fnmatch.fnmatchcase(sec.name, pattern):
                                continue
                            placed.add(id(sec))
                            inputs.append((item, obj, sec))
        align = eval_expr(oalign, 0, symbols) if oalign else 1
        align = max([align] + [s.align for _, _, s in inputs])
        dot = (dot + align - 1) // align * align
        start = dot
        nobits = noload or (inputs and all(s.nobits for _, _, s in inputs))
        # walk the inner commands in order, placing input sections and setting symbols
        consumed = iter(inputs)
        pending = list(inputs)
        for item in inner:
            if item[0] == "in":
                for patt_item, obj, sec in [x for x in pending if x[0] is item]:
                    dot = (dot + sec.align - 1) // sec.align * sec.align
                    layout.append((dot, sec, obj))
                    dot += sec.size
            else:
                _, name, op, expr = item
                v = eval_expr(expr, dot, symbols)
                if name == ".":
                    dot = dot + v if op == "+=" else v
                else:
                    symbols[name] = v
        out_sections.append((oname, start, dot, nobits, any(s.code for _, _, s in inputs)))

    unplaced = [f"{o.path}:{s.name}" for o in objects for s in o.sections.values()
                if id(s) not in placed and s.size]
    if unplaced:
        raise LinkError("sections the linker script does not place: " + ", ".join(unplaced))

    # ---- symbols
    addr_of = {}
    for addr, sec, obj in layout:
        addr_of[id(sec)] = addr
    globals_ = dict(symbols)
    locals_ = {}
    for obj in objects:
        loc = {}
        for name, sym in obj.symbols.items():
            a = addr_of[id(sym.section)] + sym.value if sym.section is not None else sym.value
            if sym.is_global:
                if name in globals_:
                    raise LinkError(f"`{name}` is defined in more than one file")
                globals_[name] = a
            loc[name] = a
        locals_[id(obj)] = loc
    for obj in objects:
        for alias, target in obj.aliases.items():
            v = locals_[id(obj)].get(target, globals_.get(target))
            if v is None:
                raise LinkError(f"{obj.path}: `.set {alias}` names unknown `{target}`")
            locals_[id(obj)][alias] = v
            if alias in obj.globals:
                globals_[alias] = v

    def lookup(obj, name, where):
        v = locals_[id(obj)].get(name)
        if v is None:
            v = globals_.get(name)
        if v is None:
            raise LinkError(f"{where}: undefined symbol `{name}`")
        return v

    # ---- image
    loadable = [(a, s, o) for a, s, o in layout if not s.nobits and s.size]
    base = layout[0][0] if layout else 0
    file_end = max((a + s.size for a, s, o in loadable), default=base)
    img = bytearray(file_end - base)
    for oname, start, end, nobits, code in out_sections:
        if CODE_FILL is not None and code and not nobits:
            for p in range(start - base, min(end, file_end) - base, 4):
                img[p:p + 4] = CODE_FILL
    for addr, sec, obj in loadable:
        img[addr - base:addr - base + sec.size] = sec.data
    for addr, sec, obj in loadable:
        for off, kind, name, addend, line in sec.relocs:
            where = f"{obj.path}:{line}"
            S = lookup(obj, name, where) + addend
            patch(img, addr - base + off, kind, S, addr + off, where)
    mem_end = max((end for _, _, end, _, _ in out_sections), default=base)
    entry = globals_.get(entry_name, base)
    return Image(base, bytes(img), mem_end - base, entry, globals_)
