# arm-os
a rather mundane operating system

A from-scratch OS for the Raspberry Pi 5, with its own language and toolchain.

- [Scope](docs/SCOPE.md) - what done means, phases, risks, open questions
- [Language spec v0.2](docs/LANGUAGE.md) - DULL, the systems language ArmOS is written in
- [dullc](dullc/README.md) - the DULL compiler, assembler and linker, written in DULL
- [Stage 0](stage0/README.md) - the Python tools that bootstrap dullc, and how to run the tests

## Running it on a Raspberry Pi 5

You need a Raspberry Pi Debug Probe on the Pi's 3-pin UART header and a FAT32 microSD card.

1. Once: `python tools/build_pi5.py --loader --card F:` puts the serial loader on the card (use your card's drive letter).
2. Every build: `python tools/build_pi5.py --send COM4` builds the kernel, sends it over the cable and shows what it prints.
   A running ArmOS kernel reboots into the loader on request, so the card stays in the Pi.
