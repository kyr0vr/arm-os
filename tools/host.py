"""Build and run DULL tools on the PC, inside QEMU (semihosting for files and console).

    python tools/host.py run dullc tokens tests/hello.dull build/hello.tokens

Tools live in their own folder (dullc/ for the compiler) with main.dull as the entry;
they are built against rt/virt and lib/.
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import toolchain  # noqa: E402

QEMU = r"C:\Program Files\qemu\qemu-system-aarch64.exe"
RT = os.path.join(ROOT, "rt", "virt")
LIB = os.path.join(ROOT, "lib")
OUT = os.path.join(ROOT, "build", "host")


def build(tool, debug=True):
    """Build tools/<tool>/main.dull (stage 0 compiler). Gives the ELF path."""
    src = os.path.join(ROOT, tool, "main.dull")
    elf, _ = toolchain.build(src, RT, 0x4008_0000, OUT, tool, debug=debug, extra_includes=[LIB])
    return elf


def run(elf, args, timeout=600):
    """Run a built tool with `args`. Gives (exit status, console output)."""
    for a in args:
        if " " in a or "," in a:
            raise ValueError(f"arguments cannot contain spaces or commas: {a!r}")
    config = "enable=on,target=native" + "".join(f",arg={a}" for a in args)
    cmd = [QEMU, "-M", "virt", "-cpu", "cortex-a76", "-m", "1G", "-display", "none",
           "-monitor", "none", "-serial", "stdio", "-semihosting-config", config, "-kernel", elf]
    r = subprocess.run(cmd, capture_output=True, timeout=timeout, cwd=ROOT)
    out = (r.stdout + r.stderr).decode("utf-8", "replace").replace("\r\n", "\n")
    return r.returncode, out


def main():
    if len(sys.argv) < 3 or sys.argv[1] != "run":
        print(__doc__)
        return 2
    tool = sys.argv[2]
    try:
        elf = build(tool)
    except toolchain.BuildError as e:
        print(f"error: {e}")
        return 1
    code, out = run(elf, [tool] + sys.argv[3:])
    sys.stdout.write(out)
    return code


if __name__ == "__main__":
    sys.exit(main())
