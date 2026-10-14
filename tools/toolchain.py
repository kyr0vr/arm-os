"""Shared build steps: DULL source -> image.

Three back ends:
  "dull"  the DULL toolchain (dullc/: compiler, assembler and linker, all in DULL),
          running on the PC inside QEMU - the default
  "own"   the stage-0 tools in Python (stage0/dullc + stage0/aa64) - the bootstrap
  "llvm"  stage-0 compiler + clang/lld from the `ziglang` package - only for checking

The DULL toolchain is bootstrapped from nothing by stage 0 (see dullc_elf()).
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "stage0"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import aa64  # noqa: E402
import qemu  # noqa: E402
from dullc import DullError, compile_file  # noqa: E402,F401

TARGET = ["-target", "aarch64-freestanding-none", "-mcpu=cortex_a76"]
KERNEL = os.path.join(ROOT, "kernel")
VIRT = os.path.join(ROOT, "rt", "virt")
LIB = os.path.join(ROOT, "lib")
DEFAULT_BACKEND = os.environ.get("ARMOS_BACKEND", "dull")


class ToolError(RuntimeError):
    pass


BuildError = (DullError, aa64.AsmError, RuntimeError)


def zig(*args):
    r = subprocess.run([sys.executable, "-m", "ziglang", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"zig {args[0]} failed:\n{r.stderr}")


def link_script(rt_dir, base):
    with open(os.path.join(rt_dir, "link.ld"), encoding="utf-8") as f:
        return f.read().replace("@BASE@", hex(base))


def rel(path):
    return os.path.relpath(os.path.abspath(path), ROOT).replace("\\", "/")


# ---------------------------------------------------------------- the DULL toolchain

def _newest(patterns):
    import glob
    t = 0
    for p in patterns:
        for f in glob.glob(os.path.join(ROOT, p)):
            t = max(t, os.path.getmtime(f))
    return t


def dullc_elf():
    """The DULL toolchain, built by itself.

    Generation 1 is built by stage 0 (Python); generation 1 then builds generation 2
    with only DULL tools. Generation 2 is what the "dull" back end runs. Both are
    rebuilt when dullc/, lib/ or rt/virt change."""
    out = os.path.join(ROOT, "build", "dull")
    gen2 = os.path.join(out, "dullc2.elf")
    sources = ["dullc/*.dull", "lib/*.dull", "rt/virt/*"]
    if os.path.exists(gen2) and os.path.getmtime(gen2) >= _newest(sources):
        return gen2
    os.makedirs(out, exist_ok=True)
    gen1, _ = build(os.path.join(ROOT, "dullc", "main.dull"), VIRT, 0x4008_0000, out, "dullc1",
                    extra_includes=[LIB], backend="own")
    _dull_build(gen1, os.path.join(ROOT, "dullc", "main.dull"), VIRT, 0x4008_0000,
                os.path.join(out, "dullc2"), True, [LIB], [])
    return gen2


def _dull_build(tool, source, rt_dir, base, prefix, debug, includes, extra_asm):
    args = ["dullc", "build", rel(source) if source else "-", rel(os.path.join(rt_dir, "link.ld")),
            hex(base), rel(prefix)]
    for d in [rt_dir, *includes]:
        args += ["-I", rel(d)]
    for s in [os.path.join(rt_dir, "start.s"), *extra_asm]:
        args += ["-S", rel(s)]
    if not debug:
        args.append("--release")
    code, out = qemu.run_tool(tool, args)
    if code != 0:
        raise ToolError(out.strip() or f"dullc exited with status {code}")
    return prefix + ".elf", prefix + ".img"


# ---------------------------------------------------------------- building

def build(source, rt_dir, base, out_dir, name, debug=True, extra_includes=(), backend=None,
          extra_asm=()):
    """Compile `source` against runtime `rt_dir`, linked at `base`.
    Returns (elf_path, img_path)."""
    backend = backend or DEFAULT_BACKEND
    os.makedirs(out_dir, exist_ok=True)
    if backend == "dull":
        return _dull_build(dullc_elf(), source, rt_dir, base, os.path.join(out_dir, name), debug,
                           list(extra_includes), list(extra_asm))
    asm = compile_file(source, [rt_dir, *extra_includes], debug=debug)
    s = os.path.join(out_dir, name + ".s")
    with open(s, "w", encoding="utf-8", newline="\n") as f:
        f.write(asm)
    return assemble_and_link([os.path.join(rt_dir, "start.s"), *extra_asm, s], link_script(rt_dir, base),
                             out_dir, name, backend)


APP_RT = os.path.join(ROOT, "rt", "app")
APPS = os.path.join(ROOT, "apps")
APP_BASE = 0x40_0000_0000             # where apps live in their address space (kernel/proc.dull)


def build_apps(out_dir, debug=True, backend=None):
    """Every app in apps/, built against rt/app. Returns {name: img_path}."""
    images = {}
    for f in sorted(os.listdir(APPS)):
        if f.endswith(".dull"):
            name = f[:-5]
            _, img = build(os.path.join(APPS, f), APP_RT, APP_BASE, out_dir, name, debug=debug,
                           extra_includes=[LIB], backend=backend)
            images[name] = img
    return images


def apps_asm(images, path):
    """An assembly file holding the app images as `apps_table`, for the kernel to link in."""
    lines = ["// Generated by tools/toolchain.py: the built-in apps.", ".section .rodata",
             ".balign 16", ".global apps_table", "apps_table:", f"    .quad {len(images)}"]
    for i, name in enumerate(images):
        lines.append(f"    .quad app_name_{i}, {len(name)}, app_image_{i}, {os.path.getsize(images[name])}")
    for i, name in enumerate(images):
        lines.append(f"app_name_{i}: .ascii \"{name}\"")
    for i, name in enumerate(images):
        with open(images[name], "rb") as f:
            data = f.read()
        lines += [".balign 16", f"app_image_{i}:"]
        for k in range(0, len(data), 32):
            lines.append("    .byte " + ", ".join(str(b) for b in data[k:k + 32]))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return path


def build_kernel(rt_dir, base, out_dir, name="kernel", debug=True, backend=None):
    """The ArmOS kernel (kernel/main.dull + kernel/arch.s) for the board in `rt_dir`,
    with the apps in apps/ built in."""
    app_dir = os.path.join(out_dir, "apps")
    table = apps_asm(build_apps(app_dir, debug=debug, backend=backend), os.path.join(app_dir, "apps.s"))
    return build(os.path.join(KERNEL, "main.dull"), rt_dir, base, out_dir, name, debug=debug,
                 extra_includes=[KERNEL, LIB], backend=backend,
                 extra_asm=[os.path.join(KERNEL, "arch.s"), table])


def assemble_and_link(sources, script, out_dir, name, backend=None):
    """Assemble .s files and link them with `script` (link.ld text, base filled in)."""
    backend = backend or DEFAULT_BACKEND
    os.makedirs(out_dir, exist_ok=True)
    elf = os.path.join(out_dir, name + ".elf")
    img = os.path.join(out_dir, name + ".img")
    if backend == "dull":
        ld = os.path.join(out_dir, name + ".ld")
        with open(ld, "w", encoding="utf-8", newline="\n") as f:
            f.write(script)
        args = ["dullc", "build", "-", rel(ld), "0", rel(os.path.join(out_dir, name))]
        for s in sources:
            args += ["-S", rel(s)]
        code, out = qemu.run_tool(dullc_elf(), args)
        if code != 0:
            raise ToolError(out.strip() or f"dullc exited with status {code}")
        return elf, img
    if backend == "own":
        objects = []
        for path in sources:
            with open(path, encoding="utf-8") as f:
                objects.append(aa64.assemble(f.read(), os.path.basename(path)))
        image = aa64.link(objects, script)
        with open(img, "wb") as f:
            f.write(image.data)
        with open(os.path.join(out_dir, name + ".map"), "w", encoding="utf-8", newline="\n") as f:
            for sym, addr in sorted(image.symbols.items(), key=lambda kv: kv[1]):
                f.write(f"{addr:016x} {sym}\n")
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
