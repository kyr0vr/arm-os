"""Build the ArmOS kernel image for the Raspberry Pi 5.

    python tools/build_pi5.py              # writes build/pi5/boot/
    python tools/build_pi5.py --card E:    # also copies the boot files to an SD card

The boot folder holds everything the card needs: config.txt and kernel_2712.img.
"""

import argparse
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "stage0"))

from dullc import DullError, compile_file  # noqa: E402

RT = os.path.join(ROOT, "rt", "pi5")
OUT = os.path.join(ROOT, "build", "pi5")
BOOT = os.path.join(OUT, "boot")

CONFIG_TXT = """\
# ArmOS boot configuration for the Raspberry Pi 5
kernel=kernel_2712.img
arm_64bit=1
kernel_address=0x80000
os_check=0
enable_uart=1
uart_2ndstage=1
hdmi_force_hotplug=1
framebuffer_depth=32
"""


def zig(*args):
    r = subprocess.run([sys.executable, "-m", "ziglang", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"zig {args[0]} failed:\n{r.stderr}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--card", help="SD card drive to copy the boot files to, e.g. E:")
    ap.add_argument("--release", action="store_true")
    args = ap.parse_args()

    os.makedirs(BOOT, exist_ok=True)
    try:
        asm = compile_file(os.path.join(ROOT, "kernel", "main.dull"), [RT], debug=not args.release)
    except DullError as e:
        raise SystemExit(f"error: {e}")
    s = os.path.join(OUT, "kernel.s")
    with open(s, "w", encoding="utf-8", newline="\n") as f:
        f.write(asm)
    tgt = ["-target", "aarch64-freestanding-none", "-mcpu=cortex_a76"]
    zig("cc", *tgt, "-c", os.path.join(RT, "start.s"), "-o", os.path.join(OUT, "start.o"))
    zig("cc", *tgt, "-c", s, "-o", os.path.join(OUT, "kernel.o"))
    elf = os.path.join(OUT, "kernel.elf")
    zig("ld.lld", "-T", os.path.join(RT, "link.ld"), os.path.join(OUT, "start.o"),
        os.path.join(OUT, "kernel.o"), "-o", elf)
    img = os.path.join(BOOT, "kernel_2712.img")
    zig("objcopy", "-O", "binary", elf, img)
    with open(os.path.join(BOOT, "config.txt"), "w", encoding="ascii", newline="\n") as f:
        f.write(CONFIG_TXT)
    print(f"built {img} ({os.path.getsize(img)} bytes)")

    if args.card:
        dest = args.card if args.card.endswith(("\\", "/")) else args.card + "\\"
        if not os.path.isdir(dest):
            raise SystemExit(f"{dest} is not a drive I can see")
        for name in ("config.txt", "kernel_2712.img"):
            shutil.copyfile(os.path.join(BOOT, name), os.path.join(dest, name))
        print(f"copied config.txt and kernel_2712.img to {dest}")


if __name__ == "__main__":
    main()
