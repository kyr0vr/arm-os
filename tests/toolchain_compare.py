"""Check ArmOS's own assemblers and linkers against clang + lld.

Builds every program three ways - clang + lld, the stage-0 tools (Python) and the
DULL toolchain - and requires the images to match byte for byte:
all runnable tests (QEMU virt), the kernel for both boards, both loaders, and
tests/asm/zoo.s, a file exercising every instruction form we encode.

Usage: python tests/toolchain_compare.py [name-filter]
"""

import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import toolchain  # noqa: E402

OUT = os.path.join(ROOT, "build", "compare")


def jobs():
    virt = os.path.join(ROOT, "rt", "virt")
    pi5 = os.path.join(ROOT, "rt", "pi5")
    tdir = os.path.join(ROOT, "tests")
    for fn in sorted(os.listdir(tdir)):
        if fn.endswith(".dull"):
            yield fn[:-5], os.path.join(tdir, fn), virt, 0x4008_0000
    yield "pi5_kernel", None, pi5, 0x8_0000
    yield "virt_kernel", None, virt, 0x4008_0000
    yield "pi5_loader", os.path.join(ROOT, "loader", "loader.dull"), pi5, 0x200_0000
    yield "virt_loader", os.path.join(ROOT, "loader", "loader.dull"), virt, 0x4200_0000


def first_difference(a, b):
    for i in range(min(len(a), len(b))):
        if a[i] != b[i]:
            return i
    return min(len(a), len(b))


BACKENDS = ("llvm", "own", "dull")


def compare(name, build_one):
    paths = {}
    for backend in BACKENDS:
        out = os.path.join(OUT, backend)
        try:
            _, img = build_one(out, backend)
        except toolchain.BuildError as e:
            return f"{backend} build failed: {e}"
        with open(img, "rb") as f:
            paths[backend] = f.read()
    if paths["dull"] != paths["own"]:
        a, b = paths["own"], paths["dull"]
        i = first_difference(a, b)
        return (f"DULL toolchain differs from stage 0 ({len(b)} vs {len(a)} bytes) at offset {i:#x}")
    a, b = paths["llvm"], paths["own"]
    if a == b:
        return None
    i = first_difference(a, b)
    w = i // 4 * 4

    def word(x):
        return f"{struct.unpack_from('<I', x, w)[0]:08x}" if w + 4 <= len(x) else "--------"
    return (f"images differ (llvm {len(a)} bytes, own {len(b)} bytes); first at offset {i:#x}: "
            f"llvm {word(a)} own {word(b)}")


def main():
    flt = sys.argv[1] if len(sys.argv) > 1 else ""
    failed = passed = 0
    for name, src, rt, base in jobs():
        if flt not in name:
            continue
        if src is None:
            problem = compare(name, lambda out, backend, rt=rt, base=base, name=name:
                              toolchain.build_kernel(rt, base, out, name, backend=backend))
        else:
            problem = compare(name, lambda out, backend, src=src, rt=rt, base=base, name=name:
                              toolchain.build(src, rt, base, out, name, backend=backend,
                                              extra_includes=[os.path.join(ROOT, "lib")]))
        print(f"{'ok  ' if problem is None else 'FAIL'} {name}" + ("" if problem is None else f": {problem}"))
        failed += problem is not None
        passed += problem is None
    zoo = os.path.join(ROOT, "tests", "asm", "zoo.s")
    if os.path.exists(zoo) and flt in "zoo":
        script = "ENTRY(_start)\nSECTIONS\n{\n    . = 0x40080000;\n    .text : { *(.text*) }\n" \
                 "    .rodata : ALIGN(16) { *(.rodata*) }\n    .data : ALIGN(16) { *(.data*) }\n}\n"
        problem = compare("zoo", lambda out, backend: toolchain.assemble_and_link([zoo], script, out, "zoo", backend))
        print(f"{'ok  ' if problem is None else 'FAIL'} zoo" + ("" if problem is None else f": {problem}"))
        failed += problem is not None
        passed += problem is None
    print(f"\n{passed} identical, {failed} different")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
