# DULL stage-0 compiler

The first DULL compiler, written in Python. It turns `.dull` source into AArch64
assembly text (`.s`). Its only job is to compile enough DULL to write the real
compiler in DULL; after that it is retired and kept only so DULL can always be
rebuilt from nothing.

It is deliberately naive: every value goes through `x0`/`x1` and the stack, and every
local lives in the stack frame. Correct first, fast never.

## Use

```
python stage0/dullc0.py program.dull -o program.s [-I folder]... [--release]
```

- `-I folder` adds a folder to search for `use`d modules (the using file's own folder is searched first).
- `--release` drops the debug traps (overflow, index, slice and division checks).
- The root module must have `to main`. Its symbol is also exported as `dull_main`.

## Platform hooks

Generated code expects the platform to provide:

| Symbol | Called with | Purpose |
|---|---|---|
| `dull_main` | — | (provided by the compiler) the program's `main` |
| `dull_trap` | `x0` = NUL-terminated message | a debug check failed; must not return |

`rt/virt/` provides both for QEMU's `virt` machine, plus `io.dull` for console output.

## Running the tests

Needs Python 3, the `ziglang` package (for `clang`/`lld` as the temporary assembler and
linker — replaced by our own in phase 2) and `qemu-system-aarch64`.

```
pip install ziglang
python tests/run.py            # everything
python tests/run.py maybe      # tests whose file name contains "maybe"
```

Each test is compiled, linked with `rt/virt`, and run on an emulated Cortex-A76.
Test files state their expected output in header comments (see `tests/run.py`).

## What stage 0 supports

Everything in [the spec](../docs/LANGUAGE.md) **except**:

- floats (`f32`, `f64`), fixed-point (`fix`) and SIMD lanes
- `choice` variants carrying data (plain variants work)
- `on core`
- `maybe` of anything but numbers, bools, choices and pointers — use `maybe ptr T`
- passing or giving back shapes and arrays by value — pass a `ptr`
- non-constant bit ranges (`x[h:l]` with variable `h`/`l`; single bits `x[n]` may be variable when read)
- more than 8 registers' worth of parameters (a span or `maybe` number takes 2)

## Layout and calling convention

- Parameters in `x0`–`x7`; spans and `maybe` numbers take two registers (pointer/value, then length/flag).
- Results in `x0` (and `x1` for two-register values).
- `maybe ptr T` is one register: `nothing` is the null pointer.
- Shapes use natural alignment in declaration order; choices are 4 bytes.
- Symbols are `module.name`, e.g. `io.print`.
