"""Boot the ArmOS kernel on QEMU virt (4 cores, GICv2) and check its self-report.

Runs twice: starting at EL1 (QEMU's default) and starting at EL2 (virtualization=on,
like the Raspberry Pi 5), so the drop to EL1 is exercised too. The kernel draws into
a pretend screen in RAM; screenshots taken during the run (the boot screen, the
launcher, the text reader, the shell) become PNGs in build/kernel_virt/.

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
    "usb:   keyboard ready",
    "usb:   mouse ready",
    "usb: 1 keyboard(s), 1 mouse/mice",
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

# What the kernel reads as typed keys (rt/virt/board.dull): the launcher, the text
# reader, then the shell. Bytes 2-7 save a screenshot (screen<n>.raw) instead.
RIGHT, DOWN, HOME = "\x1b[C", "\x1b[B", "\x1b[H"
KEYS = ("\x02"                          # the launcher
        + "1" + "\x03"                   # Text: the folder list
        + DOWN * 4 + "\r" + "\x04"       # big.txt
        + "  G" + "\x05"                 # two pages on, then the end
        + "q" + HOME + "\r" + DOWN + "\r" + "\x07"   # docs/essay.txt, word-wrapped
        + "q\x08qq"                      # out to the launcher
        + "4"                             # the Console tile: the shell
        + "help\nmem\nuptime\ncpu\necho hello from armos\nnot-a-command\nhelp\nhelp\n"
        "echo the console scrolled\ndisk\nls\nls docs\ncat hello.txt\n"
        "cat a longer file name.txt\ncat docs/notes.txt\ncat big.txt\ncat nope.txt\n"
        "hello one two three\nps\nspin a 3 &\nspin b 3 &\nps\nsleep 2000\ncrash\n"
        "echo the shell is still here\napps/hello.app from the SD card\n\x06exit\n")


def amber_pixels(raw):
    """How many pixels are the ArmOS amber (BGRX bytes)."""
    return raw.count(bytes([0x1F, 0x9A, 0xFF]))


def run(machine, label, show):
    elf, _ = toolchain.build_kernel(os.path.join(ROOT, "rt", "virt"), 0x4008_0000, OUT)
    subprocess.run([sys.executable, os.path.join(ROOT, "tests", "make_fat_image.py"), DISK,
                    "--add", "apps/hello.app", os.path.join(OUT, "apps", "hello.img")],
                   check=True, capture_output=True)
    with open(os.path.join(OUT, "keys.txt"), "wb") as f:
        f.write(KEYS.encode("latin-1"))
    for n in range(8):
        p = os.path.join(OUT, f"screen{n}.raw")
        if os.path.exists(p):
            os.remove(p)
    cmd = [qemu.path(), "-M", machine, "-cpu", "cortex-a76", "-smp", "4", "-m", "128M",
           "-display", "none", "-monitor", "none", "-serial", "stdio",
           "-semihosting-config", "enable=on,target=native", "-kernel", elf,
           "-drive", f"file={DISK},if=none,format=raw,id=d0", "-device", "virtio-blk-device,drive=d0",
           "-device", "qemu-xhci", "-device", "usb-kbd", "-device", "usb-mouse"]
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
    if r.returncode != 0 or missing:
        print(f"FAIL {label}: exit {r.returncode}, missing {missing}")
        if not show:
            print(out)
        return False
    shots = {0: "boot-screen.png", 2: "launcher.png", 3: "text-list.png", 4: "text-reader.png",
             5: "text-reader-end.png", 7: "text-wrapped.png", 6: "shell-screen.png",
             1: "back-in-launcher.png"}
    for n, name in shots.items():
        raw = os.path.join(OUT, f"screen{n}.raw")
        if not os.path.exists(raw):
            print(f"FAIL {label}: no {name}")
            return False
        to_png(raw, os.path.join(OUT, name))
    # the GUI screens are pictures: check they are there and differ where they must
    pics = {n: open(os.path.join(OUT, f"screen{n}.raw"), "rb").read() for n in shots}
    if pics[1] != pics[2] and amber_pixels(pics[1]) < 1000:
        print(f"FAIL {label}: the launcher did not come back after the shell")
        return False
    for a, b in ((2, 3), (3, 4), (4, 5), (5, 7), (7, 6)):
        if pics[a] == pics[b]:
            print(f"FAIL {label}: {shots[a]} and {shots[b]} are the same picture")
            return False
    print(f"ok   {label}")
    return True


def main():
    show = "--show" in sys.argv
    good = run("virt,gic-version=2,highmem=off", "kernel on QEMU virt, starting at EL1", show)
    good &= run("virt,gic-version=2,highmem=off,virtualization=on", "kernel on QEMU virt, starting at EL2", show)
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
