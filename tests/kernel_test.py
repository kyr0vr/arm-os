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
    "fetch      show the boot screen again",
    "Memory: ",
    "Uptime: ",
    "CPU: Cortex-A76 (4)",
    "hello from armos",
    "not a command: not-a-command",
    "the console scrolled",
    "Disk: virtio disk, 65 MB",
    'Files: FAT32 "ARMOS TEST ", 512-byte clusters, from sector 2048',
    "55 hello.txt",
    "26 A Longer File Name.txt",
    "<dir> docs/",
    "2400 notes.txt",
    "Hello from a FAT32 disk!",
    "This is ArmOS reading a file.",
    "Long file names work too.",
    "note 059: a rather mundane line of text",
    "line 00399 of a big file that crosses many clusters",
    "no such file: nope.txt",
    "hello from an app, running at EL0 in its own memory",
    "my arguments: one two three",
    "3 MB of heap: written and read back",
    "running in the background",
    "spin a: round 3 of 3",
    "spin b: round 3 of 3",
    "app crash was stopped: bad memory access at",
    "[crash ended with code 139]",
    "the shell is still here",
    "my arguments: from the SD card",
]


def to_png(raw, png):
    from PIL import Image
    with open(raw, "rb") as f:
        data = f.read()
    Image.frombytes("RGB", (1920, 1080), data, "raw", "BGRX").save(png)


DISK = os.path.join(ROOT, "build", "disk", "test.img")


def run(machine, label, show):
    elf, _ = toolchain.build_kernel(os.path.join(ROOT, "rt", "virt"), 0x4008_0000, OUT)
    subprocess.run([sys.executable, os.path.join(ROOT, "tests", "make_fat_image.py"), DISK,
                    "--add", "apps/hello.app", os.path.join(OUT, "apps", "hello.img")],
                   check=True, capture_output=True)
    for n in (0, 1):
        p = os.path.join(OUT, f"screen{n}.raw")
        if os.path.exists(p):
            os.remove(p)
    cmd = [qemu.path(), "-M", machine, "-cpu", "cortex-a76", "-smp", "4", "-m", "128M",
           "-display", "none", "-monitor", "none", "-serial", "stdio",
           "-semihosting-config", "enable=on,target=native", "-kernel", elf,
           "-drive", f"file={DISK},if=none,format=raw,id=d0", "-device", "virtio-blk-device,drive=d0"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=300, cwd=ROOT)
    except subprocess.TimeoutExpired:
        print(f"FAIL {label}: timed out")
        return False
    out = r.stdout.decode("utf-8", "replace").replace("\r", "")
    if show:
        print(out)
    missing = [e for e in EXPECT if e not in out]
    # two busy apps took turns: b got going before a finished
    if "spin b: round 1" in out and "spin a: round 3" in out and \
            out.index("spin b: round 1") > out.index("spin a: round 3"):
        missing.append("spin a and spin b taking turns")
    # after `exit` a new shell started and ran `uptime`
    if out.count("Uptime: ") < 2:
        missing.append("a new shell after exit")
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
