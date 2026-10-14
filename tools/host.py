"""Build and run DULL tools on the PC, inside QEMU (semihosting for files and console).

    python tools/host.py run dullc tokens tests/hello.dull build/hello.tokens

Tools live in their own folder (dullc/ for the compiler) with main.dull as the entry;
they are built against rt/virt and lib/.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import qemu  # noqa: E402
import toolchain  # noqa: E402

RT = os.path.join(ROOT, "rt", "virt")
LIB = os.path.join(ROOT, "lib")
OUT = os.path.join(ROOT, "build", "host")


def build(tool, debug=True):
    """Build <tool>/main.dull with the stage-0 tools (so a broken DULL toolchain can
    still be tested). Gives the ELF path."""
    src = os.path.join(ROOT, tool, "main.dull")
    elf, _ = toolchain.build(src, RT, 0x4008_0000, OUT, tool, debug=debug, extra_includes=[LIB],
                             backend="own")
    return elf


def run(elf, args, timeout=900):
    """Run a built tool with `args`. Gives (exit status, console output)."""
    return qemu.run_tool(elf, args, timeout)


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
