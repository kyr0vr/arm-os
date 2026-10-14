"""End-to-end test of the serial loader on QEMU `virt`.

Boots the loader, sends it a kernel with a wrong checksum (it must refuse and ask
again), then the real one, and checks the kernel runs: tests/hello.dull must print
its greeting and exit with status 7.

Usage: python tests/loader_test.py
"""

import os
import socket
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import serial_send  # noqa: E402
import toolchain  # noqa: E402

RT = os.path.join(ROOT, "rt", "virt")
OUT = os.path.join(ROOT, "build", "loader_test")
QEMU = r"C:\Program Files\qemu\qemu-system-aarch64.exe"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    loader_elf, _ = toolchain.build(os.path.join(ROOT, "loader", "loader.dull"), RT,
                                    0x4200_0000, OUT, "loader")
    _, kernel_img = toolchain.build(os.path.join(ROOT, "tests", "hello.dull"), RT,
                                    0x4008_0000, OUT, "hello")
    with open(kernel_img, "rb") as f:
        image = f.read()

    port = free_port()
    qemu = subprocess.Popen(
        [QEMU, "-M", "virt", "-cpu", "cortex-a76", "-m", "128M", "-display", "none",
         "-monitor", "none", "-serial", f"tcp:127.0.0.1:{port},server=on,wait=on",
         "-semihosting-config", "enable=on,target=native", "-kernel", loader_elf],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    link = None
    try:
        for _ in range(50):
            try:
                link = serial_send.Link(f"socket://127.0.0.1:{port}", echo=False)
                break
            except Exception:
                time.sleep(0.1)
        assert link is not None, "could not connect to QEMU's serial port"

        assert not serial_send.send(link, image, 0x4008_0000, wait_ready=20, bad_checksum=True), \
            "the loader accepted a bad checksum"
        assert b"checksum mismatch" in link.seen, "no complaint about the bad checksum"
        assert serial_send.send(link, image, 0x4008_0000, wait_ready=20), "the loader refused a good kernel"

        deadline = time.time() + 20
        while qemu.poll() is None and time.time() < deadline:
            link.pump()
        link.pump()
        out = link.seen[link.start_of_kernel:].decode("utf-8", "replace")
        assert qemu.poll() == 7, f"kernel exit status {qemu.poll()}, expected 7\n{out}"
        assert "hello from DULL" in out and "42" in out, f"kernel output missing:\n{out}"
    finally:
        if link is not None:
            link.close()
        if qemu.poll() is None:
            qemu.kill()
    print("ok   loader: refused a bad checksum, then loaded and ran hello.dull")
    return 0


if __name__ == "__main__":
    sys.exit(main())
