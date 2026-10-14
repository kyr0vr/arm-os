"""Boot the ArmOS kernel on QEMU virt (4 cores, GICv2) and check its self-report.

Runs twice: starting at EL1 (QEMU's default) and starting at EL2 (virtualization=on,
like the Raspberry Pi 5), so the drop to EL1 is exercised too. The kernel draws into
a pretend screen in RAM; the second run saves it, and this script turns it into
build/kernel_virt/boot-screen.png and shell-screen.png.

Usage: python tests/kernel_test.py [--show]
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import qemu  # noqa: E402
import toolchain  # noqa: E402

OUT = os.path.join(ROOT, "build", "kernel_virt")

EXPECT = [
    "kernel runs at EL1",
    "ok    running at EL1",
    "ok    a test breakpoint was caught and stepped over",
    "ok    the page allocator has memory",
    "ok    MMU and data cache enabled",
    "ok    page allocator: alloc, free, reuse",
    "ok    heap: 9 sizes, zeroed, no overlaps, reuse",
    "ok    timer interrupts arrive on time",
    "core 1 says hello",
    "core 2 says hello",
    "core 3 says hello",
    "ok    all four cores running",
    "boot screen: 100% drawn",
    "kernel core: all checks passed",
    "root@armos:~$ help",
    "fetch    show the boot screen again",
    "Memory: ",
    "Uptime: ",
    "CPU: Cortex-A76 (4)",
    "hello from armos",
    "not a command: not-a-command",
    "the console scrolled",
]


def to_png(raw, png):
    from PIL import Image
    with open(raw, "rb") as f:
        data = f.read()
    Image.frombytes("RGB", (1920, 1080), data, "raw", "BGRX").save(png)


def run(machine, label, show):
    elf, _ = toolchain.build_kernel(os.path.join(ROOT, "rt", "virt"), 0x4008_0000, OUT)
    for n in (0, 1):
        p = os.path.join(OUT, f"screen{n}.raw")
        if os.path.exists(p):
            os.remove(p)
    cmd = [qemu.path(), "-M", machine, "-cpu", "cortex-a76", "-smp", "4", "-m", "128M",
           "-display", "none", "-monitor", "none", "-serial", "stdio",
           "-semihosting-config", "enable=on,target=native", "-kernel", elf]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=300, cwd=ROOT)
    except subprocess.TimeoutExpired:
        print(f"FAIL {label}: timed out")
        return False
    out = r.stdout.decode("utf-8", "replace").replace("\r", "")
    if show:
        print(out)
    missing = [e for e in EXPECT if e not in out]
    if r.returncode != 0 or missing:
        print(f"FAIL {label}: exit {r.returncode}, missing {missing}")
        if not show:
            print(out)
        return False
    for n, name in ((0, "boot-screen.png"), (1, "shell-screen.png")):
        raw = os.path.join(OUT, f"screen{n}.raw")
        if os.path.exists(raw):
            to_png(raw, os.path.join(OUT, name))
    print(f"ok   {label}")
    return True


def main():
    show = "--show" in sys.argv
    good = run("virt,gic-version=2", "kernel on QEMU virt, starting at EL1", show)
    good &= run("virt,gic-version=2,virtualization=on", "kernel on QEMU virt, starting at EL2", show)
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
