"""Run the stage-0 compiler test suite.

Each tests/*.dull program is compiled, assembled and linked with the QEMU `virt`
runtime, then run under qemu-system-aarch64. Its header comments say what must happen:

    -- expect: a line the program must print (in order; repeat for more lines)
    -- exit: 3                  exit status (default 0)
    -- trap: integer overflow   the program must stop with this trap message
    -- release                  compile without debug traps

Each tests/errors/*.dull must fail to compile:

    -- error: text that must appear in the error message

Usage: python tests/run.py [name-filter]
"""

import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "stage0"))

from dullc import DullError, compile_file  # noqa: E402

RT = os.path.join(ROOT, "rt", "virt")
BUILD = os.path.join(ROOT, "build", "tests")
QEMU_CANDIDATES = [
    shutil.which("qemu-system-aarch64"),
    r"C:\Program Files\qemu\qemu-system-aarch64.exe",
]


def qemu_path():
    for c in QEMU_CANDIDATES:
        if c and os.path.isfile(c):
            return c
    raise SystemExit("qemu-system-aarch64 not found")


def zig(*args):
    r = subprocess.run([sys.executable, "-m", "ziglang", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"zig {args[0]} failed:\n{r.stderr}")


def headers(path):
    h = {"expect": [], "exit": 0, "trap": None, "release": False, "error": None}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.startswith("--"):
                continue
            body = line[2:].strip()
            key, _, val = body.partition(":")
            key = key.strip()
            if key == "expect":
                h["expect"].append(val[1:] if val.startswith(" ") else val)
            elif key == "exit":
                h["exit"] = int(val)
            elif key == "trap":
                h["trap"] = val.strip()
            elif key == "error":
                h["error"] = val.strip()
            elif body == "release":
                h["release"] = True
    return h


def build_runtime():
    obj = os.path.join(BUILD, "start.o")
    zig("cc", "-target", "aarch64-freestanding-none", "-c", os.path.join(RT, "start.s"), "-o", obj)
    return obj


def run_program(path, h, start_obj, qemu):
    name = os.path.splitext(os.path.basename(path))[0]
    asm = compile_file(path, [RT], debug=not h["release"])
    s = os.path.join(BUILD, name + ".s")
    o = os.path.join(BUILD, name + ".o")
    elf = os.path.join(BUILD, name + ".elf")
    with open(s, "w", encoding="utf-8", newline="\n") as f:
        f.write(asm)
    zig("cc", "-target", "aarch64-freestanding-none", "-c", s, "-o", o)
    zig("ld.lld", "-T", os.path.join(RT, "link.ld"), start_obj, o, "-o", elf)
    cmd = [qemu, "-M", "virt", "-cpu", "cortex-a76", "-m", "128M", "-display", "none",
           "-monitor", "none", "-serial", "stdio", "-semihosting-config",
           "enable=on,target=native", "-kernel", elf]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=20)
    except subprocess.TimeoutExpired:
        return None, "timed out (program hung)"
    out = r.stdout.decode("utf-8", "replace").replace("\r\n", "\n")
    return r.returncode, out + r.stderr.decode("utf-8", "replace").replace("\r\n", "\n")


def main():
    flt = sys.argv[1] if len(sys.argv) > 1 else ""
    os.makedirs(BUILD, exist_ok=True)
    qemu = qemu_path()
    start_obj = build_runtime()
    tdir = os.path.join(ROOT, "tests")
    passed = failed = 0

    for fn in sorted(os.listdir(tdir)):
        if not fn.endswith(".dull") or flt not in fn:
            continue
        path = os.path.join(tdir, fn)
        h = headers(path)
        try:
            code, out = run_program(path, h, start_obj, qemu)
        except (DullError, RuntimeError) as e:
            print(f"FAIL {fn}: {e}")
            failed += 1
            continue
        problems = []
        if code is None:
            problems.append(out)
        else:
            lines = out.split("\n")
            if h["trap"] is not None:
                if code != 101 or f"trap: " not in out or h["trap"] not in out:
                    problems.append(f"expected trap {h['trap']!r}, got exit {code}:\n{out}")
            else:
                if code != h["exit"]:
                    problems.append(f"exit {code}, expected {h['exit']}")
                got = [l.rstrip() for l in lines if l.strip() != ""]
                if got != h["expect"]:
                    problems.append("output differs:\n  expected: " + repr(h["expect"]) +
                                    "\n  got:      " + repr(got))
        if problems:
            print(f"FAIL {fn}: " + "\n".join(problems))
            failed += 1
        else:
            print(f"ok   {fn}")
            passed += 1

    edir = os.path.join(tdir, "errors")
    for fn in sorted(os.listdir(edir)) if os.path.isdir(edir) else []:
        if not fn.endswith(".dull") or flt not in fn:
            continue
        path = os.path.join(edir, fn)
        h = headers(path)
        try:
            compile_file(path, [RT])
            print(f"FAIL errors/{fn}: compiled, but should have failed with {h['error']!r}")
            failed += 1
        except DullError as e:
            if h["error"] and h["error"] in str(e):
                print(f"ok   errors/{fn}")
                passed += 1
            else:
                print(f"FAIL errors/{fn}: wrong error: {e}")
                failed += 1

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
