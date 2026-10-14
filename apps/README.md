# ArmOS apps

Every `.dull` file here is an app. Apps run at EL0, each in its own address space,
and reach the kernel only through system calls. The build (`tools/toolchain.py`)
compiles each one against `rt/app` and builds them all into the kernel, so they
can be started by name from the shell. An app image copied to the SD card can be
started by its path too (`apps/hello.app`, or just `apps/hello`).

| App | What it does |
|---|---|
| `launcher` | The first app: Text, Music, Video and Console tiles |
| `text` | The text reader: folders and .txt files on the SD card, word-wrapped |
| `shell` | The shell: reads keys, runs its own commands, starts other apps |
| `hello` | Says hello, prints its arguments, checks 3 MB of heap |
| `spin` | `spin <name> <rounds>`: keeps the CPU busy, to show apps taking turns |
| `crash` | Reads kernel memory; the kernel stops it and everything else goes on |

In the shell, `name args` runs an app and waits for it; `name args &` leaves it
running in the background. `ps` lists what is running and `kill pid` stops an app.

## Writing one

```
use sys

to main gives u64
    sys.print("hello\n")
    give 0                  -- the exit code
```

`rt/app/sys.dull` wraps every system call (the terminal, keys, time, files on the
SD card, starting and waiting for apps, more memory). `rt/app/mem.dull` provides
`mem.alloc`, so `lib/` (vec, buf, map, line, text) works in apps.

Graphical apps use `rt/app/gfx.dull`: `gfx.open()` gets a screen-sized surface, the
app draws rectangles, rounded rectangles, discs, triangles and quads into it itself
(anti-aliased), text is drawn by the kernel in ArmOS Mono (25 px, bold, 22 px small,
46 px large), and `gfx.present` shows a finished area. The app started last is in
front; when it ends, whatever was under it comes back. `rt/app/keys.dull` turns the
escape sequences of arrow and paging keys into single codes.

## The image

`rt/app/start.s` puts a header first: `"DULX"`, a version word, the address where
the app's memory ends (with `.bss`) and its entry point. Apps are linked at
`0x40_0000_0000`; the kernel maps the image there, the heap right after it and a
256 KB stack at the top of that GB.

## System calls

`svc #0` with the number in `x8`, arguments in `x0`-`x5`, the answer in `x0`.

| # | Call | # | Call |
|---|---|---|---|
| 0 | exit(code) | 9 | kill(pid) |
| 1 | write(text, length, color, bold) | 10 | dir(path, index, entry, cap) |
| 2 | key() - waits | 11 | read(path, offset, buffer, count) |
| 3 | sleep(ms) | 12 | clear() |
| 4 | yield() | 13 | fetch() - the boot screen |
| 5 | time() - ms since boot | 14 | reboot() |
| 6 | info(kind, buffer, cap) | 15 | args(buffer, cap) |
| 7 | spawn(name, args, background) | 16 | grow(bytes) - more heap |
| 8 | wait(pid) - waits | 17 | process(index, buffer, cap) |
| 18 | key_within(ms) | 19 | surface(size) - the app's screen surface |
| 20 | text(x \| y << 16, text, length, color, style) | 21 | present(x \| y << 32, w \| h << 32) |
| 22 | font(style) - advance \| height << 32 | | |
