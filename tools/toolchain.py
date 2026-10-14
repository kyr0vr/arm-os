"""Shared build steps: DULL -> .s (stage 0), then assemble, link and make a raw image.

Assembling and linking use clang/lld from the `ziglang` package for now; phase 2
replaces them with our own assembler and linker.
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "stage0"))

from dullc import DullError, compile_file  # noqa: E402,F401

TARGET = ["-target", "aarch64-freestanding-none", "-mcpu=cortex_a76"]


def zig(*args):
    r = subprocess.run([sys.executable, "-m", "ziglang", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"zig {args[0]} failed:\n{r.stderr}")


def build(source, rt_dir, base, out_dir, name, debug=True, extra_includes=()):
    """Compile `source` against runtime `rt_dir`, linked at `base`.
    Returns (elf_path, img_path)."""
    os.makedirs(out_dir, exist_ok=True)
    asm = compile_file(source, [rt_dir, *extra_includes], debug=debug)
    s = os.path.join(out_dir, name + ".s")
    with open(s, "w", encoding="utf-8", newline="\n") as f:
        f.write(asm)
    start_o = os.path.join(out_dir, name + "_start.o")
    obj = os.path.join(out_dir, name + ".o")
    zig("cc", *TARGET, "-c", os.path.join(rt_dir, "start.s"), "-o", start_o)
    zig("cc", *TARGET, "-c", s, "-o", obj)
    with open(os.path.join(rt_dir, "link.ld"), encoding="utf-8") as f:
        script = f.read().replace("@BASE@", hex(base))
    ld = os.path.join(out_dir, name + ".ld")
    with open(ld, "w", encoding="utf-8", newline="\n") as f:
        f.write(script)
    elf = os.path.join(out_dir, name + ".elf")
    zig("ld.lld", "-T", ld, start_o, obj, "-o", elf)
    img = os.path.join(out_dir, name + ".img")
    zig("objcopy", "-O", "binary", elf, img)
    return elf, img
