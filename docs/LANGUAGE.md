# ArmOS Language — Spec v0

Working name: **TBD** (see [SCOPE.md §9](SCOPE.md#9-name-candidates-for-the-language)).
This document calls it "the language". Status: **draft v0** (2026-10-08) — everything
here may change once real code is written in it.

---

## 1. Goals

- **A systems language**: raw memory, no garbage collector, no hidden runtime.
- **Clearly its own thing**: plain words for structure, terse symbols for math,
  `->` pipes as the signature move.
- **Hardware is first-class**: register maps, bit ranges, SIMD lanes and fixed-point
  numbers are syntax, not library tricks.
- **Simple enough to write twice**: once in the stage-0 host language, once in itself.

## 2. A taste

```
-- the Pi 5 debug UART

device uart at 0x10_7d00_1000
    data  at 0x00 u32
    flags at 0x18 u32
        tx_full is bit 5

to send (b u8)
    hold until uart.flags.tx_full is 0
    uart.data = b

to print (text string)
    for each ch in text
        ch -> send
```

```
fixed kbps  [16] u32 = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0]
fixed rates [4]  u32 = [44100, 48000, 32000, 0]

shape frame
    bitrate     u32
    sample_rate u32
    padded      bool
    length      u32

to read_frame (raw u32) gives maybe frame
    if raw[31:21] is not 0x7FF
        give nothing

    new f frame
    f.bitrate     = kbps[raw[15:12]] * 1000
    f.sample_rate = rates[raw[11:10]]
    f.padded      = raw[9] is 1
    f.length      = 144 * f.bitrate / f.sample_rate + (f.padded as u32)
    give f
```

```
to play (path string)
    new file = open(path) or give
    on core 2
        file -> mp3.decode -> resample(48000) -> hdmi.audio
```

## 3. Lexical structure

- **Encoding**: UTF-8 source. Identifiers are ASCII.
- **Comments**: `--` to end of line. No block comments.
- **Indentation**: blocks are indented by **4 spaces**. Tabs are an error.
  The lexer emits `INDENT` / `DEDENT` tokens, Python-style.
- **Line continuation**: a line ending in an operator, `,`, `(` or `[` continues on the next.
- **Identifiers**: `[a-z_][a-z0-9_]*`. Type names follow the same rule (`frame`, `u32`).
  Names are single words; use `_` to join (`read_frame`).
- **Integers**: `42`, `0x7FF`, `0b1010`, `1_000_000`. Underscores anywhere after the first digit.
- **Floats**: `1.5`, `3.0e-4`.
- **Strings**: `"text"` with `\n \t \\ \" \x41` escapes. Type `string` (§4).
- **Characters**: `'a'` is a `u8`.

### Keywords (reserved)

```
to gives give new fixed shape choice device at is not and or
if else while repeat hold until for each in stop skip
true false nothing maybe ptr addr span lanes of fix
on core asm use as
```

## 4. Types

| Type | Meaning |
|---|---|
| `u8 u16 u32 u64` | unsigned integers; wrap on overflow |
| `i8 i16 i32 i64` | signed integers; two's complement, wrap on overflow |
| `f32 f64` | IEEE floats |
| `bool` | `true` / `false`, one byte |
| `fix 16.16` | fixed-point: 16 integer bits, 16 fraction bits (any split, total 8/16/32/64) |
| `[N] T` | fixed-size array of N elements |
| `span T` | pointer + length view of memory |
| `string` | a `span u8` holding UTF-8 |
| `ptr T` | raw pointer to T |
| `N lanes of T` | SIMD vector, e.g. `8 lanes of u16` (maps to one 128-bit NEON register) |
| `maybe T` | a T or `nothing` |
| `shape` | named struct |
| `choice` | named enum, optionally carrying data |

No implicit conversions between numeric types. Convert with `as`: `x as u64`.
Integer literals take the type they are used as.

## 5. Declarations

```
new count u32 = 0          -- variable with type
new count = 0              -- type inferred (defaults to i64 for bare literals)
new f frame                -- zero-initialized
fixed max_files u32 = 64   -- compile-time constant
```

Top-level `new` is a global; top-level `fixed` is a constant.

### Shapes and choices

```
shape point
    x i32
    y i32

choice codec
    mp3
    aac
    h264

choice event
    key (code u8)
    tick
    quit
```

## 6. Functions

```
to add (a i32, b i32) gives i32
    give a + b

to halt
    repeat
        asm "wfe"
```

- `gives T` declares the return type; omitted means nothing is returned.
- `give expr` returns. A bare `give` returns from a function that gives nothing, or
  gives `nothing` from a function that gives `maybe T`.
- Calls: `add(1, 2)`.

## 7. Pipes: `->`

`->` passes the value on its left as the **first argument** of the call on its right.

```
ch -> send                   -- send(ch)
x -> clamp(0, 255)           -- clamp(x, 0, 255)
a -> f -> g(1)               -- g(f(a), 1)
```

Pipes are plain calls in v0. **Later**: when the right side is a *stream* (a
producer/consumer function), a pipe chain becomes a running pipeline
(`file -> mp3.decode -> hdmi.audio`). Stream semantics are deferred to v1.

## 8. Statements and control flow

```
x = 5                        -- assignment (= is never equality)
x += 1                       -- also -= *= /= &= |= ^= <<= >>=

if x is 0
    ...
else if x > 10
    ...
else
    ...

while x < 10
    x += 1

repeat                       -- forever
    ...

hold until uart.flags.tx_full is 0     -- spin-wait (emits a relaxed loop)

for each i in 0 until 10     -- 0..9   (exclusive)
for each i in 1 through 10   -- 1..10  (inclusive)
for each ch in text          -- over a span / array / string

stop                         -- break
skip                         -- continue
```

## 9. Operators

| Precedence (high → low) | Operators |
|---|---|
| postfix | `f(x)`  `a[i]`  `a[h:l]`  `s.field` |
| prefix | `-x`  `~x`  `not x`  `at p`  `addr of x` |
| conversion | `x as T` |
| multiply | `*  /  %` |
| add | `+  -  +\|  -\|` (the last two saturate) |
| shift | `<<  >>` |
| bitwise | `&` then `^` then `\|` |
| compare | `is  is not  <  >  <=  >=` |
| logic | `not`, then `and`, then `or` |
| pipe | `->` (lowest) |

`>>` is arithmetic on signed types, logical on unsigned.

### Bit ranges

`x[h:l]` reads bits `h` down to `l` (inclusive) as an unsigned value. `x[n]` on an
integer reads one bit. Both are also assignable:

```
reg[11:8] = 0b0101
```

Indexing an array or span with one number (`a[i]`) is element access; the type of
the left side decides which meaning applies.

## 10. Pointers and memory

```
new p ptr u32 = addr of count
at p = 7                     -- write through the pointer
new v = at p                 -- read through it
p[3]                         -- element 3 past p
q.field                      -- fields auto-dereference through a ptr to a shape
```

No bounds checks on `ptr`. **Spans** are bounds-checked in debug builds.
Memory is managed by hand; the kernel provides allocators as ordinary functions.

## 11. Devices

A `device` is a memory-mapped register block. Every field access is a single
volatile load or store of exactly the declared width, in program order.

```
device gic_dist at 0x10_7fff_9000
    ctrl   at 0x000 u32
        enable_grp0 is bit 0
        enable_grp1 is bit 1
    typer  at 0x004 u32
        lines   is bits 4:0
        cpus    is bits 7:5
```

- `name at OFFSET TYPE` declares a register.
- Indented `name is bit N` / `name is bits H:L` declare fields within it.
- Writing a field does read-modify-write of its register. Writing the register
  writes all of it.
- `device name at ADDR` may also take the address at runtime:
  `device uart at uart_base` where `uart_base` is a `fixed` or a `new` global.

Addresses here are illustrative; real ones come from the Pi 5 device tree.

## 12. Errors: `maybe` and `or`

```
to find (name string) gives maybe file
    ...

new f = find("song.mp3") or give        -- on nothing: return
new f = find("song.mp3") or skip        -- on nothing: next loop iteration
new f = find("song.mp3") or default_f   -- on nothing: use a fallback

if find("song.mp3") is nothing
    print("missing")
```

`or` on a `maybe` unwraps it; `or` on two `bool`s is logical or.

## 13. SIMD lanes and fixed-point

```
new a 8 lanes of i16 = load_lanes(src)
new b 8 lanes of i16 = load_lanes(src + 8)
store_lanes(dst, (a + b + 1) >> 1)      -- element-wise, one NEON op each

new gain fix 16.16 = 0.75
sample = (sample as fix 16.16 * gain) as i16
```

Arithmetic on lanes is element-wise. Lane widths must total 64 or 128 bits.
`fix` arithmetic keeps its format; multiply rounds to nearest.

## 14. Cores and assembly

```
on core 2                    -- run the block on core 2 (kernel-provided; see below)
    decode_loop()

asm "dsb sy"                 -- one instruction
asm                          -- a block
    "mrs x0, CurrentEL"
    "lsr x0, x0, #2"
```

`on core N` lowers to a call into the kernel's `core_run(N, block)`; the language
only defines the syntax. `asm` text goes straight to our assembler; v0 has no
operand binding — `asm` blocks use the AArch64 calling convention by hand.

## 15. Modules

One file is one module. `use name` brings in `name.<ext>` from the same folder or
the library path; its top-level names are reached as `name.thing`.

```
use uart
use mp3 as audio_mp3
```

No visibility keywords in v0: everything at top level is public.

## 16. Calling convention and layout

- **AAPCS64**, so `asm`, the firmware and any hand-written assembly interoperate.
- Shapes are laid out in declaration order with natural alignment.
- `bool` is one byte; `maybe T` is T plus a one-byte tag (pointers use null instead).

## 17. Grammar sketch (EBNF-ish)

```
file        = { top_decl } ;
top_decl    = use | fixed | new | shape | choice | device | func ;
func        = "to" IDENT [ "(" params ")" ] [ "gives" type ] NEWLINE block ;
params      = param { "," param } ;
param       = IDENT type ;
block       = INDENT { stmt } DEDENT ;
stmt        = new | assign | if | while | repeat | hold | for | give
            | "stop" | "skip" | on_core | asm | expr NEWLINE ;
new         = "new" IDENT [ type ] [ "=" expr ] NEWLINE ;
assign      = lvalue assign_op expr NEWLINE ;
if          = "if" expr NEWLINE block { "else" "if" expr NEWLINE block }
              [ "else" NEWLINE block ] ;
while       = "while" expr NEWLINE block ;
repeat      = "repeat" NEWLINE block ;
hold        = "hold" "until" expr NEWLINE ;
for         = "for" "each" IDENT "in" ( range | expr ) NEWLINE block ;
range       = expr ( "until" | "through" ) expr ;
give        = "give" [ expr ] NEWLINE ;
type        = IDENT | "[" INT "]" type | "span" type | "ptr" type
            | "maybe" type | INT "lanes" "of" type | "fix" INT "." INT ;
expr        = pipe ;
pipe        = logic_or { "->" call_target } ;
```

## 18. Open questions

1. Name and file extension.
2. Do pipes into streams (§7) ship in v1, or does the media pipeline use plain calls?
3. Generics: none in v0. Needed for containers later? (Probably a small template form.)
4. Should `hold until` take an optional timeout (`hold until x within 1000 us`)?
5. Strings: is `string` = `span u8` enough, or do we want an owned string type?
6. How should `asm` bind operands to variables (v1)?
