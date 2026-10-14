"""Build ArmOS for the Raspberry Pi 5, and get it onto the Pi.

Everyday use (the serial loader is on the SD card):

    python tools/build_pi5.py --send COM4          # build the kernel, send it over the cable, show its output

Setting up a card:

    python tools/build_pi5.py --loader --card F:   # put the serial loader on the card (once)
    python tools/build_pi5.py --card F:            # or put the kernel itself on the card

Without --card or --send it only builds, into build/pi5/.
"""

import argparse
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import toolchain  # noqa: E402

RT = os.path.join(ROOT, "rt", "pi5")
OUT = os.path.join(ROOT, "build", "pi5")
KERNEL_BASE = 0x8_0000         # where kernels run
LOADER_BASE = 0x200_0000       # 32 MB: the loader stays out of the kernel's way

CONFIG_TXT = """\
# ArmOS boot configuration for the Raspberry Pi 5
kernel=kernel_2712.img
arm_64bit=1
kernel_address={base}
os_check=0
enable_uart=1
uart_2ndstage=1
hdmi_force_hotplug=1
framebuffer_depth=32
"""


def copy_to_card(card, img, base):
    dest = card if card.endswith(("\\", "/")) else card + "\\"
    if not os.path.isdir(dest):
        raise SystemExit(f"{dest} is not a drive I can see")
    shutil.copyfile(img, os.path.join(dest, "kernel_2712.img"))
    with open(os.path.join(dest, "config.txt"), "w", encoding="ascii", newline="\n") as f:
        f.write(CONFIG_TXT.format(base=hex(base)))
    print(f"copied kernel_2712.img and config.txt to {dest}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loader", action="store_true", help="build the serial loader instead of the kernel")
    ap.add_argument("--card", help="SD card drive to copy the boot files to, e.g. F:")
    ap.add_argument("--send", metavar="PORT", help="send the kernel through the serial loader, e.g. COM4")
    ap.add_argument("--watch", type=float, default=15, help="seconds of kernel output to show after --send")
    ap.add_argument("--release", action="store_true")
    args = ap.parse_args()

    if args.loader:
        source, base, name = os.path.join(ROOT, "loader", "loader.dull"), LOADER_BASE, "loader"
    else:
        source, base, name = os.path.join(ROOT, "kernel", "main.dull"), KERNEL_BASE, "kernel"
    try:
        if args.loader:
            _, img = toolchain.build(source, RT, base, OUT, name, debug=not args.release)
        else:
            _, img = toolchain.build_kernel(RT, base, OUT, name, debug=not args.release)
    except toolchain.BuildError as e:
        raise SystemExit(f"error: {e}")
    print(f"built {img} ({os.path.getsize(img)} bytes, runs at {hex(base)})")

    if args.card:
        copy_to_card(args.card, img, base)

    if args.send:
        if args.loader:
            raise SystemExit("--send sends a kernel; the loader goes on the card with --card")
        import serial_send
        with open(img, "rb") as f:
            image = f.read()
        link = serial_send.Link(args.send)
        try:
            if not serial_send.send(link, image, base):
                raise SystemExit(1)
            end = time.time() + args.watch
            while time.time() < end:
                link.pump()
        finally:
            link.close()
        print()


if __name__ == "__main__":
    main()
