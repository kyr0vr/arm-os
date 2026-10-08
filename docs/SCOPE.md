# ArmOS — Scope

*A Rather Mundane Operating System.* A hobby operating system for the
Raspberry Pi 5, built from the ground up: our own language, compiler, assembler,
linker, kernel, drivers, file system, codecs and GUI. No borrowed toolchain in the
final product.

Status: **draft v0** (2026-10-08). Nothing is built yet.

---

## 1. Definition of done

ArmOS is done when, on a real Pi 5, from power-on:

1. It boots into a **GUI launcher** with three functions: **Text**, **Music**, **Video**,
   driven by a **USB keyboard and mouse** plugged into the Pi.
2. **Text** opens and reads `.txt` files from the SD card (scrolling, a real font).
3. **Music** plays `.mp3` files with sound out of the monitor over HDMI.
4. **Video** plays `.mp4` files (H.264 video + AAC audio) at **1080p30**, in sync.
5. Every byte of code that runs was produced by **our own toolchain**, and that
   toolchain's compiler is written in our own language and compiles itself.

Media goes onto the SD card from a Windows PC, so the card uses FAT32.

## 2. Decisions so far

| Topic | Ruling |
|---|---|
| Target | Raspberry Pi 5 (BCM2712, 4x Cortex-A76, AArch64) |
| Ground-up level | **Level C**: own language + compiler + assembler + linker, then self-hosting |
| Self-hosting | Early: right after the kernel core (phase 5). The compiler compiles itself **on the PC**; compiling on ArmOS is a stretch goal after "done". |
| Stage-0 compiler | **Python**. Supports only the DULL subset the real compiler needs. Kept in the repo as the from-nothing bootstrap after it is retired. |
| Language style | Flow-right pipes (`->`) with plain-word structure; `=` assigns. See [LANGUAGE.md](LANGUAGE.md) |
| Language name | **DULL** — Decidedly Unremarkable Low-level Language; files are `.dull` |
| Video subset | H.264 High profile (8-bit 4:2:0, up to level 4.1) + AAC-LC in MP4, **1080p30**; an ffmpeg recipe converts anything else |
| Audio out | HDMI audio to the monitor's speakers (the Pi 5 has no headphone jack) |
| Input | **USB keyboard and mouse** are required for done. Serial input from the PC is the stand-in until the USB stack lands. |
| Repo | `kyr0vr/arm-os` |

## 3. Hardware facts that shape the plan

- **Boot.** The EEPROM bootloader reads the FAT boot partition, applies `config.txt`
  and jumps to our image (`kernel_2712.img`) in 64-bit mode. We write no first-stage
  bootloader. On the Pi 5 the firmware lives in EEPROM (no `start*.elf` on the card);
  the boot partition holds `config.txt`, the device-tree blob (`bcm2712-rpi-5-b.dtb`)
  and our image. That firmware is the one thing we do not write, the same as a PC's BIOS.
- **Display.** The firmware can hand us a ready framebuffer (mailbox property call or
  a `simple-framebuffer` device-tree node). Pixels on HDMI come early.
- **Serial.** The Pi 5's usable early UART is the **3-pin JST debug header** between
  the HDMI ports (PL011, believed at `0x10_7d00_1000` — confirm from the DT).
  The GPIO 14/15 UART sits behind RP1 and is not available early.
  Needs a 3.3 V adapter: the Raspberry Pi Debug Probe (~$12) comes with the right cable.
- **RP1.** USB, Ethernet and GPIO live on a separate chip reached over PCIe. Anything
  touching them needs PCIe + RP1 bring-up first. This is the biggest driver wall.
- **SD card.** The SD host controller is on the main SoC (SDHCI). Storage is reachable
  without RP1.
- **No H.264 hardware.** The Pi 5 only decodes HEVC in hardware. H.264 is a software
  decoder written by us, which makes NEON (SIMD) support in the language mandatory.
- **HDMI audio.** The HDMI controller is on the SoC; the Linux `vc4_hdmi` driver is
  the reference for how its audio path and DMA work.
- **Emulation.** QEMU has no Pi 5 machine. We develop against QEMU `virt` (AArch64,
  GICv2/v3, PL011) behind a thin board layer, and run on the real Pi regularly.

## 4. Development hardware

- Raspberry Pi 5 with the official 27 W USB-C power supply
- microSD card + an SD card reader for the PC
- HDMI monitor with speakers (micro-HDMI to HDMI cable)
- USB keyboard and mouse
- **Raspberry Pi Debug Probe** — USB to 3.3 V UART, ships with the 3-pin JST-SH cable that
  fits the Pi 5 debug header. Any 3.3 V USB-serial adapter plus a JST-SH 1.0 mm 3-pin
  cable also works. Never a 5 V adapter.

## 5. Architecture

```
  PC (Windows)                                   Pi 5
  ────────────────────────────                   ───────────────────────────────
  source  ──► compiler ──► .s ──► assembler      SD card (FAT32)
                                     │             ├─ firmware + config.txt
                                     ▼             ├─ kernel_2712.img  (ArmOS)
                                  linker ──────►   └─ /media  .txt .mp3 .mp4
                                                         │
  serial cable ◄───────── chainloader / console ─────────┘
```

**Toolchain** (all ours): lexer → parser → checker → IR → AArch64 codegen →
assembler (text `.s` → machine code + relocations) → linker (objects → flat kernel
image, later our own executable format for apps).

**Kernel**: EL2 → EL1 drop, exception vectors, MMU + page tables, GIC interrupts,
generic timer, physical page allocator, heap, 4-core SMP, scheduler, EL0 user mode,
syscalls.

**Drivers**: PL011 UART, framebuffer, SDHCI, PCIe → RP1 → xHCI → USB HID, HDMI audio.

**Userland**: compositor + launcher, text reader, MP3 player, MP4 player, font renderer.

## 6. Phases

Each phase ends with something visible on the Pi or the PC.

| # | Phase | Exit criterion |
|---|---|---|
| 0 | **Stage-0 compiler** in Python: functions, ints, pointers, shapes, spans, if/while, `device`, `asm` | Compiles a test program to `.s` that GNU `as` accepts (temporary crutch) |
| 1 | **Alive** | Pi 5 prints "ArmOS" over serial and fills the screen with a color |
| 2 | **Own assembler + linker** | Phase 1 image rebuilt with zero outside tools; byte-compare against GNU output |
| 3 | **Serial chainloader** | New kernels load over the cable; no more SD swaps per build |
| 4 | **Kernel core** | Timer interrupts tick, MMU on, page allocator and heap pass tests, all 4 cores say hello |
| 5 | **Self-host** | The compiler, rewritten in DULL, compiles itself byte-identically; stage 0 is retired |
| 6 | **Text console** | Bitmap font, scrolling console on HDMI, keyboard input over serial |
| 7 | **Storage** | SDHCI driver + FAT32 read; list and print a `.txt` from the card |
| 8 | **Processes** | EL0 apps, syscalls, scheduler; the console is an app |
| 9 | **GUI + Text** | Compositor, launcher with Text/Music/Video tiles, **Text reader done** (serial keys) |
| 10 | **USB input** | PCIe root complex → RP1 → xHCI → USB HID: a USB keyboard and mouse drive the GUI |
| 11 | **Audio** | HDMI audio plays a test tone; MP3 decoder; **Music done** |
| 12 | **Video** | MP4 demux, AAC, H.264 (I/P/B, CABAC, deblock), NEON, 4-core decode, A/V sync; **Video done** |

Phases 0–9 are a solid, showable milestone. Phase 12 is where most of the time goes.

Self-hosting comes right after the kernel core: by then the boot code and kernel
basics, written in DULL, have shaken out the language, and from phase 6 on every
line of ArmOS is built by the DULL compiler. Stage 0 stays in the repo so DULL can
always be rebuilt from nothing.

Phase 10 can run in parallel with 11 and 12: USB and media share no code.

## 7. Risks, ranked

1. **H.264 at 1080p30 in software** — the single largest piece of code, and it has to
   be fast: roughly 62 million pixels a second across four cores. Mitigation: a defined
   subset, the ffmpeg recipe, NEON lanes in the language from early on, slice- or
   row-parallel decode, and hand-written `asm` for the hottest loops.
2. **HDMI audio** — sparse documentation outside Linux source. Mitigation: start it
   right after storage, as a spike, before the MP3 decoder exists.
3. **RP1/USB** — months by itself, and RP1's register documentation is partial.
   Mitigation: serial input as a stand-in, the Linux `rp1` and `xhci` drivers as reference.
4. **Optimizer quality** — a naive compiler will be too slow for 1080p decode.
   Mitigation: inline `asm` and lane types so hot loops can be hand-tuned.
5. **Debugging blind** — mitigated by the debug UART from phase 1 and QEMU `virt` + GDB.

## 8. Open questions

None blocking. Language-level questions live in [LANGUAGE.md §18](LANGUAGE.md#18-open-questions).

## 9. The language name

ArmOS is **A Rather Mundane Operating System**. Its language is equally unexciting:
**DULL**, the *Decidedly Unremarkable Low-level Language*. See [LANGUAGE.md](LANGUAGE.md).

## 10. Out of scope (for "done")

Networking, Wi-Fi/Bluetooth, multi-user, security hardening, a GPU 3D driver,
writing to FAT32 (read-only is enough for playback), porting existing software.
