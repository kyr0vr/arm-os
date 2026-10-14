"""Send a kernel image to the ArmOS serial loader, then show what the kernel prints.

    python tools/serial_send.py build/pi5/kernel.img --addr 0x80000 --port COM4
    python tools/serial_send.py image.img --addr 0x40080000 --port socket://127.0.0.1:4555

--port takes a COM port or any pyserial URL (QEMU's serial over TCP uses socket://).
"""

import argparse
import struct
import sys
import time

import serial

READY = b"ArmOS loader: ready"
RECEIVING = b"ArmOS loader: receiving"
STARTING = b"ArmOS loader: checksum ok - starting kernel"
REBOOT = b"ARMR"
COMPLAINTS = (b"ArmOS loader: bad header", b"ArmOS loader: checksum mismatch")


def fnv1a(data):
    h = 0x811C9DC5
    for b in data:
        h = ((h ^ b) * 0x01000193) & 0xFFFFFFFF
    return h


class Link:
    """A serial connection that remembers everything it has read."""

    def __init__(self, port, echo=True):
        self.ser = serial.serial_for_url(port, baudrate=115200, timeout=0.05)
        self.seen = bytearray()
        self.echo = echo

    def pump(self):
        try:
            data = self.ser.read(4096)
        except serial.SerialException:
            self.closed = True       # the other end went away (e.g. QEMU exited)
            time.sleep(0.05)
            return b""
        if data:
            self.seen += data
            if self.echo:
                sys.stdout.write(data.decode("utf-8", "replace").replace("\r", ""))
                sys.stdout.flush()
        return data

    def wait_for(self, needles, timeout, start=0):
        """Wait until one of `needles` appears after offset `start`. Returns (needle, end) or (None, None)."""
        end_time = time.time() + timeout
        while True:
            for n in needles:
                i = self.seen.find(n, start)
                if i >= 0:
                    return n, i + len(n)
            if time.time() > end_time:
                return None, None
            self.pump()

    def write(self, data):
        self.ser.write(data)
        self.ser.flush()

    def close(self):
        self.ser.close()


def send(link, image, addr, wait_ready=120, bad_checksum=False):
    """Hand `image` to the loader. Returns True once the loader starts it."""
    print("[send] asking the Pi to reboot into the loader...", flush=True)
    start = len(link.seen)
    end_time = time.time() + wait_ready
    found = None
    while time.time() < end_time:
        link.write(REBOOT)          # a running ArmOS kernel reboots; the loader ignores it
        found, pos = link.wait_for([READY], 2, start=start)
        if found:
            break
    if not found:
        print("[send] the loader never said ready - power-cycle the Pi", flush=True)
        return False
    check = fnv1a(image) ^ (1 if bad_checksum else 0)
    link.write(b"ARMB" + struct.pack("<IQI", len(image), addr, check))
    found, pos = link.wait_for([RECEIVING, *COMPLAINTS], 10, pos)
    if found != RECEIVING:
        print(f"[send] loader did not accept the header ({found})", flush=True)
        return False
    t0 = time.time()
    link.write(image)
    found, pos = link.wait_for([STARTING, *COMPLAINTS], 30 + len(image) / 5000, pos)
    if found != STARTING:
        print(f"[send] transfer failed ({found})", flush=True)
        return False
    print(f"\n[send] {len(image)} bytes in {time.time() - t0:.1f}s - kernel started", flush=True)
    link.start_of_kernel = pos
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--addr", required=True, help="load address, e.g. 0x80000")
    ap.add_argument("--port", default="COM4")
    ap.add_argument("--watch", type=float, default=20, help="seconds to show kernel output")
    args = ap.parse_args()
    with open(args.image, "rb") as f:
        image = f.read()
    link = Link(args.port)
    try:
        if not send(link, image, int(args.addr, 0)):
            return 1
        end = time.time() + args.watch
        while time.time() < end:
            link.pump()
    finally:
        link.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
