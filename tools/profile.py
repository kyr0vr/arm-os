"""Turn the profiler's output (lines "prof <offset> <count>" on the serial console,
from sys.profile_stop) into time per function of an app.

    python tools/profile.py <app> <serial log> [--release]   e.g. video build/prof/pi.log

Pass --release when the kernel was built with --release. It builds the app with the Python back end to get a symbol map (all back ends make
the same image), then adds up the samples per function.
"""

import bisect
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import toolchain  # noqa: E402


def main():
    app, log = sys.argv[1], sys.argv[2]
    release = "--release" in sys.argv
    out = os.path.join(ROOT, "build", "prof")
    toolchain.build(os.path.join(ROOT, "apps", app + ".dull"), toolchain.APP_RT, toolchain.APP_BASE, out, app,
                    debug=not release, extra_includes=[toolchain.LIB], backend="own")
    syms = []
    with open(os.path.join(out, app + ".map"), encoding="utf-8") as f:
        for line in f:
            addr, name = line.split()
            a = int(addr, 16) - toolchain.APP_BASE
            if 0 <= a < 1 << 24 and not name.startswith(".L") and not name.startswith("__"):
                syms.append((a, name))
    syms.sort()
    starts = [a for a, _ in syms]
    counts = {}
    total = 0
    with open(log, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = re.match(r"\s*prof 0x([0-9a-fA-F]+) (\d+)", line)
            if not m:
                continue
            off, n = int(m.group(1), 16), int(m.group(2))
            i = bisect.bisect_right(starts, off) - 1
            name = syms[i][1] if i >= 0 else "?"
            counts[name] = counts.get(name, 0) + n
            total += n
    print(f"{total} samples (1 per ms)")
    for name, n in sorted(counts.items(), key=lambda kv: -kv[1])[:int(os.environ.get("TOP", "30"))]:
        print(f"{100.0 * n / total:6.1f}%  {n:7d}  {name}")


if __name__ == "__main__":
    main()
