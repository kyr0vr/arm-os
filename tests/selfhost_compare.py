"""Check the DULL-written compiler (dullc/) against the stage-0 compiler (stage0/dullc).

Each stage must give identical results on every .dull file in the repo:
    tokens   the lexer's token stream (and the same error, for files that fail)

Usage: python tests/selfhost_compare.py tokens [name-filter]
"""

import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "stage0"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import host  # noqa: E402
from dullc.lexer import DullError, tokenize  # noqa: E402

OUT = os.path.join(ROOT, "build", "selfhost")
KIND_ORDER = ["NAME", "INT", "STR", "CHAR", "KW", "SYM", "NEWLINE", "INDENT", "DEDENT", "EOF"]


def sources():
    files = []
    for pattern in ["tests/*.dull", "tests/errors/*.dull", "kernel/*.dull", "rt/*/*.dull",
                    "lib/*.dull", "loader/*.dull", "dullc/*.dull"]:
        files += sorted(glob.glob(os.path.join(ROOT, pattern)))
    return files


def python_tokens(path):
    with open(path, encoding="utf-8") as f:
        src = f.read()
    try:
        toks = tokenize(src, os.path.basename(path))
    except DullError as e:
        return f"error: {e}\n"
    out = []
    for t in toks:
        line = f"{t.line} {t.kind}"
        if t.kind in ("INT", "CHAR"):
            line += f" {t.value}"
        elif t.kind == "STR":
            line += " " + t.value.hex()
        elif t.kind in ("NAME", "KW", "SYM"):
            line += f" {t.value}"
        out.append(line)
    return "\n".join(out) + "\n"


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("tokens",):
        print(__doc__)
        return 2
    stage = sys.argv[1]
    flt = sys.argv[2] if len(sys.argv) > 2 else ""
    os.makedirs(OUT, exist_ok=True)
    elf = host.build("dullc")
    passed = failed = 0
    for path in sources():
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        if flt not in rel:
            continue
        want = python_tokens(path)
        out_file = os.path.join(OUT, rel.replace("/", "__") + ".tokens")
        if os.path.exists(out_file):
            os.remove(out_file)
        code, console = host.run(elf, ["dullc", "tokens", rel, os.path.relpath(out_file, ROOT).replace("\\", "/")])
        if code == 0:
            with open(out_file, encoding="utf-8", errors="replace") as f:
                got = f.read()
        else:
            got = console
        if got == want:
            passed += 1
            continue
        failed += 1
        wl, gl = want.splitlines(), got.splitlines()
        i = next((k for k in range(min(len(wl), len(gl))) if wl[k] != gl[k]), min(len(wl), len(gl)))
        print(f"FAIL {rel}: first difference at line {i + 1}")
        print(f"   stage 0: {wl[i] if i < len(wl) else '(end)'}")
        print(f"   dullc:   {gl[i] if i < len(gl) else '(end)'}")
    print(f"\n{stage}: {passed} identical, {failed} different")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
