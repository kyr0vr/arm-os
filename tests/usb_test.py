"""USB input on QEMU: a USB keyboard and mouse on an xHCI controller, driven from
here through QEMU's control socket (QMP) as if someone were using them.

Types on the keyboard, moves and clicks the mouse, and checks what comes back over
the serial line; F12 on the keyboard makes the kernel save the screen
(build/kernel_virt/usb-<n>.png).

Usage: python tests/usb_test.py [--show]
"""

import json
import os
import socket
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

import qemu  # noqa: E402
import toolchain  # noqa: E402
import kernel_test  # noqa: E402

OUT = kernel_test.OUT
PORT = 45454


class Machine:
    def __init__(self, elf):
        keys = os.path.join(OUT, "keys.txt")
        if os.path.exists(keys):
            os.remove(keys)                    # no scripted keys: input comes from USB
        for n in range(2, 12):
            p = os.path.join(OUT, f"screen{n}.raw")
            if os.path.exists(p):
                os.remove(p)
        cmd = [qemu.path(), "-M", "virt,gic-version=2,highmem=off", "-cpu", "cortex-a76", "-smp", "4",
               "-m", "128M", "-display", "none", "-monitor", "none", "-serial", "stdio",
               "-semihosting-config", "enable=on,target=native", "-kernel", elf,
               "-drive", f"file={kernel_test.DISK},if=none,format=raw,id=d0",
               "-device", "virtio-blk-device,drive=d0",
               "-device", "qemu-xhci", "-device", "usb-kbd", "-device", "usb-mouse",
               "-qmp", f"tcp:127.0.0.1:{PORT},server=on,wait=off"]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=ROOT)
        self.out = bytearray()
        threading.Thread(target=self._read, daemon=True).start()
        self.qmp = None

    def _read(self):
        while True:
            b = self.proc.stdout.read(1)
            if not b:
                return
            self.out.extend(b)

    def text(self):
        return self.out.decode("utf-8", "replace").replace("\r", "")

    def wait_for(self, what, seconds=120):
        end = time.time() + seconds
        while time.time() < end:
            if what in self.text():
                return True
            time.sleep(0.1)
        return False

    def connect(self):
        self.qmp = socket.create_connection(("127.0.0.1", PORT), timeout=10)
        self.f = self.qmp.makefile("rw")
        self.f.readline()                      # greeting
        self.call("qmp_capabilities")

    def call(self, command, **arguments):
        msg = {"execute": command}
        if arguments:
            msg["arguments"] = arguments
        self.f.write(json.dumps(msg) + "\n")
        self.f.flush()
        while True:
            reply = json.loads(self.f.readline())
            if "return" in reply or "error" in reply:
                return reply

    def events(self, *events):
        self.call("input-send-event", events=list(events))

    def key(self, qcode, down):
        self.events({"type": "key", "data": {"down": down, "key": {"type": "qcode", "data": qcode}}})

    def tap(self, qcode, shift=False):
        if shift:
            self.key("shift", True)
        self.key(qcode, True)
        time.sleep(0.03)
        self.key(qcode, False)
        if shift:
            self.key("shift", False)
        time.sleep(0.04)

    def type(self, text):
        names = {" ": "spc", "\n": "ret", "-": "minus", ".": "dot", "/": "slash", "&": ("7", True)}
        for ch in text:
            if ch in names:
                n = names[ch]
                if isinstance(n, tuple):
                    self.tap(*n)
                else:
                    self.tap(n)
            elif ch.isupper():
                self.tap(ch.lower(), shift=True)
            else:
                self.tap(ch)

    def move(self, dx, dy):
        self.events({"type": "rel", "data": {"axis": "x", "value": dx}},
                    {"type": "rel", "data": {"axis": "y", "value": dy}})
        time.sleep(0.15)

    def click(self, button="left"):
        self.events({"type": "btn", "data": {"down": True, "button": button}})
        time.sleep(0.05)
        self.events({"type": "btn", "data": {"down": False, "button": button}})
        time.sleep(0.3)

    def shot(self):
        self.tap("f12")
        time.sleep(0.5)

    def stop(self):
        try:
            self.call("quit")
        except OSError:
            pass
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def main():
    show = "--show" in sys.argv
    elf, _ = toolchain.build_kernel(os.path.join(ROOT, "rt", "virt"), 0x4008_0000, OUT)
    subprocess.run([sys.executable, os.path.join(ROOT, "tests", "make_fat_image.py"), kernel_test.DISK,
                    "--add", "apps/hello.app", os.path.join(OUT, "apps", "hello.img")],
                   check=True, capture_output=True)
    m = Machine(elf)
    problems = []
    try:
        if not m.wait_for("usb: 1 keyboard(s), 1 mouse/mice"):
            problems.append("the keyboard and mouse were not found")
            raise RuntimeError
        time.sleep(3)                          # the launcher draws itself
        m.connect()
        m.shot()                               # 2: the launcher, the pointer in the middle
        m.move(-600, 0)                        # onto the Text tile
        m.shot()                               # 3: Text lit up under the pointer
        m.click()                              # open it
        time.sleep(2)
        m.shot()                               # 4: the folder list
        for _ in range(4):
            m.tap("down")
        m.tap("ret")                           # big.txt
        time.sleep(2)
        for _ in range(5):
            m.events({"type": "btn", "data": {"down": True, "button": "wheel-down"}})
            m.events({"type": "btn", "data": {"down": False, "button": "wheel-down"}})
            time.sleep(0.1)
        time.sleep(1)
        m.shot()                               # 5: big.txt, scrolled by the wheel
        m.click("right")                       # back to the list
        m.tap("q")                             # out to the launcher
        time.sleep(1)
        m.tap("4")                             # the Console tile
        time.sleep(2)
        m.type("echo Typed on a USB keyboard\n")
        time.sleep(1)
        m.type("ps\n")
        time.sleep(1)
        m.shot()                               # 6: the shell
        for what in ["Typed on a USB keyboard", "launcher", "shell"]:
            if what not in m.text().split("usb: 1 keyboard(s)")[-1]:
                problems.append(f"missing on serial: {what!r}")
    except RuntimeError:
        pass
    finally:
        m.stop()
    out = m.text()
    if show:
        print(out)
    names = {2: "usb-launcher.png", 3: "usb-hover.png", 4: "usb-text-list.png", 5: "usb-wheel.png",
             6: "usb-shell.png"}
    pics = {}
    for n, name in names.items():
        raw = os.path.join(OUT, f"screen{n}.raw")
        if not os.path.exists(raw):
            problems.append(f"no screenshot {name}")
            continue
        kernel_test.to_png(raw, os.path.join(OUT, name))
        pics[n] = open(raw, "rb").read()
    for a, b in ((2, 3), (3, 4), (4, 5), (5, 6)):
        if a in pics and b in pics and pics[a] == pics[b]:
            problems.append(f"{names[a]} and {names[b]} are the same picture")
    if problems:
        print("FAIL usb input:", "; ".join(problems))
        if not show:
            print(out[-3000:])
        return 1
    print("ok   usb input: keyboard typing, mouse pointing, clicking and wheel on QEMU")
    return 0


if __name__ == "__main__":
    sys.exit(main())
