"""The self-hosting check: DULL's compiler compiles itself, and stays the same.

  generation 1: stage 0 (Python) compiles dullc/            -> dullc1
  generation 2: dullc1 compiles dullc/ (assembly gen2.s)    -> dullc2
  generation 3: dullc2 compiles dullc/ (assembly gen3.s)

gen2.s and gen3.s must be identical (a fixed point), and equal to stage 0's output.
Usage: python tests/selfhost_fixpoint.py
"""

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "stage0"))

import host  # noqa: E402
import toolchain  # noqa: E402
from dullc import compile_file  # noqa: E402

OUT = os.path.join(ROOT, "build", "fixpoint")
RT = os.path.join(ROOT, "rt", "virt")


def compile_with(elf, out_s):
    rel = os.path.relpath(out_s, ROOT).replace("\\", "/")
    t0 = time.time()
    code, console = host.run(elf, ["dullc", "compile", "dullc/main.dull", rel, "rt/virt", "lib"])
    took = time.time() - t0
    if code != 0:
        raise SystemExit(f"dullc failed:\n{console}")
    with open(out_s, encoding="utf-8") as f:
        return f.read(), took


def link(asm_path, name):
    script = toolchain.link_script(RT, 0x4008_0000)
    elf, _ = toolchain.assemble_and_link([os.path.join(RT, "start.s"), asm_path], script, OUT, name)
    return elf


def main():
    os.makedirs(OUT, exist_ok=True)
    stage0 = compile_file(os.path.join(ROOT, "dullc", "main.dull"), [RT, os.path.join(ROOT, "lib")])
    gen1_s = os.path.join(OUT, "gen1.s")
    with open(gen1_s, "w", encoding="utf-8", newline="\n") as f:
        f.write(stage0)
    dullc1 = link(gen1_s, "dullc1")
    gen2, t2 = compile_with(dullc1, os.path.join(OUT, "gen2.s"))
    dullc2 = link(os.path.join(OUT, "gen2.s"), "dullc2")
    gen3, t3 = compile_with(dullc2, os.path.join(OUT, "gen3.s"))
    lines = stage0.count("\n")
    print(f"dullc compiled itself in {t2:.1f}s (generation 2) and {t3:.1f}s (generation 3); "
          f"{lines} lines of assembly")
    ok = gen2 == stage0 and gen3 == gen2
    print("ok   fixed point: stage 0 = generation 2 = generation 3" if ok else
          f"FAIL stage0==gen2: {gen2 == stage0}, gen2==gen3: {gen3 == gen2}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
