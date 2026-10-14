# dullc — the DULL toolchain, written in DULL

`dullc` is the DULL compiler, assembler and linker in one program, written in DULL
and compiled by itself. It runs on the PC inside QEMU (`virt` machine) and reaches
the PC's files through Arm semihosting (`rt/virt/sys.dull`).

```
dullc build <root.dull> <link.ld> <base> <out> [-I dir]... [-S file.s]... [--release]
dullc compile <root.dull> <out.s> [include dirs...] [--release]
dullc tokens <file.dull> <out.txt>        (checks the lexer)
dullc ast <file.dull> <out.txt>           (checks the parser)
```

`build` compiles `root.dull`, assembles the `-S` files (the runtime's `start.s`
first) and the compiled program, and links them with `link.ld` (its `@BASE@` replaced
by `base`) into `out.img` (flat image), `out.elf` and `out.s`. A root of `-` skips the
compile and only assembles and links.

You normally do not run it by hand: `tools/toolchain.py` does, and every build in the
repo (`tools/build_pi5.py`, `tests/run.py`, ...) goes through it.

## Modules

| Module | Job |
|---|---|
| `main` | command line |
| `diag` | errors: `error: file:line: message`, then exit |
| `lexer`, `parser`, `ast` | source -> tokens -> syntax tree |
| `wide` | 128-bit integers for constant expressions |
| `types` | DULL's types |
| `program` | modules, symbols, declarations, constants, data |
| `gen` | type checking and code generation for function bodies |
| `asmtext`, `encode`, `assembler` | assembly text -> objects |
| `linker` | objects + `link.ld` -> image and ELF |

## How it is checked

It is a faithful port of the stage-0 tools in `stage0/` (Python), so every result can
be compared with theirs:

- `python tests/selfhost_compare.py tokens|ast|asm` — identical tokens and syntax
  trees for every `.dull` file, identical assembly (or the same error) for every program
- `python tests/selfhost_fixpoint.py` — dullc compiles itself, and the result compiles
  itself again to the same output
- `python tests/toolchain_compare.py` — images from the DULL toolchain, the stage-0
  tools and clang + lld are byte-identical for every program

## Bootstrapping

DULL needs a DULL compiler to build. From a fresh checkout `tools/toolchain.py` does it
automatically: stage 0 (Python) builds `dullc` once (generation 1), and that builds
`dullc` again with only DULL code (generation 2, `build/dull/dullc2.elf`), which is
what every build then uses. The two are byte-identical.
