"""Shared build steps: DULL -> .s (stage-0 compiler) -> image.

Two back ends turn assembly into an image:
  "own"   ArmOS's own assembler and linker (stage0/aa64) — the default
  "llvm"  clang + lld from the `ziglang` package — kept only to check "own" against
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "stage0"))

import aa64  # noqa: E402
from dullc import DullError, compile_file  # noqa: E402,F401

TARGET = ["-target", "aarch64-freestanding-none", "-mcpu=cortex_a76"]
BuildError = (DullError, aa64.AsmError, RuntimeError)


def zig(*args):
    r = subprocess.run([sys.executable, "-m", "ziglang", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"zig {args[0]} failed:\n{r.stderr}")


def link_script(rt_dir, base):
    with open(os.path.join(rt_dir, "link.ld"), encoding="utf-8") as f:
        return f.read().replace("@BASE@", hex(base))


def build(source, rt_dir, base, out_dir, name, debug=True, extra_includes=(), backend="own"):
    """Compile `source` against runtime `rt_dir`, linked at `base`.
    Returns (elf_path, img_path)."""
    os.makedirs(out_dir, exist_ok=True)
    asm = compile_file(source, [rt_dir, *extra_includes], debug=debug)
    s = os.path.join(out_dir, name + ".s")
    with open(s, "w", encoding="utf-8", newline="\n") as f:
        f.write(asm)
    return assemble_and_link([os.path.join(rt_dir, "start.s"), s], link_script(rt_dir, base),
                             out_dir, name, backend)


def assemble_and_link(sources, script, out_dir, name, backend="own"):
    elf = os.path.join(out_dir, name + ".elf")
    img = os.path.join(out_dir, name + ".img")
    if backend == "own":
        objects = []
        for path in sources:
            with open(path, encoding="utf-8") as f:
                objects.append(aa64.assemble(f.read(), os.path.basename(path)))
        image = aa64.link(objects, script)
        with open(img, "wb") as f:
            f.write(image.data)
        with open(elf, "wb") as f:
            f.write(image.elf())
        return elf, img
    objs = []
    for path in sources:
        o = os.path.join(out_dir, os.path.splitext(os.path.basename(path))[0] + f"_{name}.o")
        zig("cc", *TARGET, "-c", path, "-o", o)
        objs.append(o)
    ld = os.path.join(out_dir, name + ".ld")
    with open(ld, "w", encoding="utf-8", newline="\n") as f:
        f.write(script)
    zig("ld.lld", "--no-relax", "-T", ld, *objs, "-o", elf)
    zig("objcopy", "-O", "binary", elf, img)
    return elf, img
