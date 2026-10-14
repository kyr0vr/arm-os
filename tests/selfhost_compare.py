"""Check the DULL-written compiler (dullc/) against the stage-0 compiler (stage0/dullc).

Each stage must give identical results on every .dull file in the repo:
    tokens   the lexer's token stream
    ast      the parser's syntax tree
(and the same error message, for files that are meant to fail).

Usage: python tests/selfhost_compare.py <stage> [name-filter]
"""

import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

import host  # noqa: E402
import selfhost_dump  # noqa: E402

OUT = os.path.join(ROOT, "build", "selfhost")
STAGES = {"tokens": selfhost_dump.tokens, "ast": selfhost_dump.tree}


def sources():
    files = []
    for pattern in ["tests/*.dull", "tests/errors/*.dull", "kernel/*.dull", "rt/*/*.dull",
                    "lib/*.dull", "loader/*.dull", "dullc/*.dull"]:
        files += sorted(glob.glob(os.path.join(ROOT, pattern)))
    return files


def show_difference(rel, want, got):
    wl, gl = want.splitlines(), got.splitlines()
    i = next((k for k in range(min(len(wl), len(gl))) if wl[k] != gl[k]), min(len(wl), len(gl)))
    a = wl[i] if i < len(wl) else "(end)"
    b = gl[i] if i < len(gl) else "(end)"
    j = next((k for k in range(min(len(a), len(b))) if a[k] != b[k]), min(len(a), len(b)))
    lo = max(0, j - 60)
    print(f"FAIL {rel}: line {i + 1}, column {j + 1}")
    print(f"   stage 0: ...{a[lo:j + 80]}")
    print(f"   dullc:   ...{b[lo:j + 80]}")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in STAGES:
        print(__doc__)
        return 2
    stage = sys.argv[1]
    flt = sys.argv[2] if len(sys.argv) > 2 else ""
    os.makedirs(OUT, exist_ok=True)
    try:
        elf = host.build("dullc")
    except host.toolchain.BuildError as e:
        print(f"building dullc with stage 0 failed: {e}")
        return 1
    passed = failed = 0
    for path in sources():
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        if flt not in rel:
            continue
        want = STAGES[stage](path)
        out_file = os.path.join(OUT, rel.replace("/", "__") + "." + stage)
        if os.path.exists(out_file):
            os.remove(out_file)
        code, console = host.run(elf, ["dullc", stage, rel, os.path.relpath(out_file, ROOT).replace("\\", "/")])
        if code == 0:
            with open(out_file, encoding="utf-8", errors="replace") as f:
                got = f.read()
        else:
            got = console
        if got == want:
            passed += 1
        else:
            failed += 1
            show_difference(rel, want, got)
    print(f"\n{stage}: {passed} identical, {failed} different")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
