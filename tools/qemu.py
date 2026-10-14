"""Running AArch64 programs on the PC with QEMU's `virt` machine and semihosting."""

import os
import shutil
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANDIDATES = [shutil.which("qemu-system-aarch64"), r"C:\Program Files\qemu\qemu-system-aarch64.exe"]


def path():
    for c in CANDIDATES:
        if c and os.path.isfile(c):
            return c
    raise SystemExit("qemu-system-aarch64 not found")


def run_tool(elf, args, timeout=900):
    """Run a DULL tool (an ELF built against rt/virt) with `args`, from the repo root.
    Gives (exit status, console output)."""
    for a in args:
        if " " in a or "," in a:
            raise ValueError(f"tool arguments cannot contain spaces or commas: {a!r}")
    config = "enable=on,target=native" + "".join(f",arg={a}" for a in args)
    cmd = [path(), "-M", "virt", "-cpu", "cortex-a76", "-m", "1G", "-display", "none",
           "-monitor", "none", "-serial", "stdio", "-semihosting-config", config, "-kernel", elf]
    r = subprocess.run(cmd, capture_output=True, timeout=timeout, cwd=ROOT)
    out = (r.stdout + r.stderr).decode("utf-8", "replace").replace("\r\n", "\n")
    return r.returncode, out
