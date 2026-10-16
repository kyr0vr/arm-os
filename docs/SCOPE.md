# ArmOS — Scope

*A Rather Mundane Operating System.* A hobby operating system for the
Raspberry Pi 5, built from the ground up: our own language, compiler, assembler,
linker, kernel, drivers, file system, codecs and GUI. No borrowed toolchain in the
final product.

Status: **draft v0** (2026-10-08). Phases 0 to 11 are done: the stage-0 compiler and its tests are in `stage0/` and `tests/`; the first kernel boots on a real Pi 5 (`kernel/`, `rt/pi5/`, built with `tools/build_pi5.py`).

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
| Running DULL tools on the PC | DULL compiles to AArch64, so the self-hosted compiler runs on the PC inside **QEMU** (`virt` machine), reading and writing files through semihosting. |
| Toolchain | **DULL** (`dullc/`), running on the PC in QEMU. The Python stage-0 tools (`stage0/`) are kept only to bootstrap it from nothing. Supports only the DULL subset the real compiler needs. Kept in the repo as the from-nothing bootstrap after it is retired. |
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
- **Learned in phase 1 (confirmed on hardware):**
  - The firmware starts our image at **EL2** with the MMU off, at `0x80000` (`kernel_address=0x80000`, `os_check=0`; no device tree file needed).
  - The debug UART at `0x10_7d00_1000` is already running at 115200 baud when we start.
  - The mailbox is at `0x10_7c01_3880`. The firmware **ignores the depth tag** and uses `framebuffer_depth` from `config.txt` (default 16); set it to 32.
  - Pixel order 0 means blue is the first byte in memory, so a pixel reads as `0x00RRGGBB`.
  - The firmware only offers a screen if it saw a monitor at boot; `hdmi_force_hotplug=1` drives HDMI regardless.
  - (Phase 3) The firmware **starts the image at `0x80000` whatever `kernel_address` says**, although its log reports the requested address. The boot code copies itself to its link address when the two differ.
  - (Phase 3) Rebooting works through the power-management watchdog at `0x10_7d20_0000`.
  - (Phase 4) Cores start through PSCI `CPU_ON` with `smc`; their MPIDRs are `0x000`, `0x100`, `0x200`, `0x300`.
  - (Phase 4) The GIC-400 (distributor `0x10_7fff_9000`, CPU interface `0x10_7fff_a000`) delivers the EL1 virtual timer (interrupt 27) to the non-secure kernel with no extra setup.
  - (Phase 4) The firmware gives the ARM cores just under 1 GB of low RAM (mailbox tag `0x10005`); the screen buffer sits in it and is mapped uncached.
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
| 0 | **Stage-0 compiler** in Python: functions, ints, pointers, shapes, spans, if/while, `device`, `asm` | ✅ Test programs compile, assemble (clang/lld via `ziglang`, a temporary crutch) and run correctly on an emulated Cortex-A76 |
| 1 | **Alive** | ✅ Pi 5 prints "ArmOS" over serial and paints the screen red / green / blue |
| 2 | **Own assembler + linker** | ✅ `stage0/aa64` builds every image; all 24 programs plus an instruction zoo are byte-identical to clang + lld (`tests/toolchain_compare.py`), and the Pi 5 kernel boots from it |
| 3 | **Serial chainloader** | ✅ `tools/build_pi5.py --send COM4` builds a kernel, reboots the Pi into the loader over the cable and runs the new kernel; no SD swaps |
| 4 | **Kernel core** | ✅ EL2 -> EL1, exception vectors, MMU + caches (168x faster), page allocator + heap self-tests, GIC + 100 Hz timer, all 4 cores via PSCI - on the Pi 5 and on QEMU (`tests/kernel_test.py`) |
| 5 | **Self-host** | ✅ `dullc/`: compiler, assembler and linker in DULL; compiles itself to a fixed point; every image byte-identical to stage 0 and clang + lld; all builds now use it, stage 0 only bootstraps |
| 6 | **Text console** | ✅ ArmOS Mono bitmap font, the designed boot screen drawn live (progress arrow with glow, facts read from the hardware), a scrolling console and a tiny shell taking keys over serial - on the Pi and in QEMU (screenshots) |
| 7 | **Storage** | ✅ SD card driver (SDHCI, polled, 4-bit, 25 MHz) and read-only FAT32 with long file names: `disk`, `ls`, `cat` read the real card on the Pi; QEMU tests the same code on a generated FAT32 image over virtio |
| 8 | **Processes** | ✅ Apps at EL0 in their own address spaces, 18 system calls, a preemptive round-robin scheduler (1 ms ticks, 10 ms turns); the shell is an app; built-in apps plus `.app` files from the SD card; a crashing app is stopped and the rest carries on - on the Pi and in QEMU |
| 9 | **GUI + Text** | ✅ Compositor (each graphical app draws its own full-screen surface; the foreground one is shown, the one underneath comes back), anti-aliased shapes in apps and kernel-drawn ArmOS Mono text, a launcher with Text / Music / Video / Console tiles, and the **Text reader**: folders and .txt files on the SD card, word-wrapped reading, line and page scrolling (serial keys) |
| 10 | **USB input** | ✅ PCIe → RP1 (left set up by the firmware with `pciex4_reset=0`, found by its chip ID) → both DWC3 xHCI controllers → HID boot protocol: USB keyboards (US layout, key repeat) and mice drive the GUI, with a pointer drawn by the compositor and click / right-click / wheel in the apps; plugging in and out works. Tested on the Pi and in QEMU (`tests/usb_test.py` types and clicks through QEMU's control socket). No USB hubs yet |
| 11 | **Audio** | ✅ HDMI audio on the Pi 5 (MAI interface fed IEC958 subframes by core 3, which does nothing else), a fixed-point MP3 decoder in DULL (`lib/mp3.dull`: MPEG-1 Layer III, mono/stereo/joint stereo, CBR/VBR, ID3 tags; within 92-100 dB of ffmpeg, `tests/mp3_test.py`) and **Music done**: browse, play/pause, seek, volume, next/previous, a level display; `tests/music_test.py` plays a song from the SD image through the kernel's audio on QEMU and compares it with ffmpeg. Not yet: intensity stereo, MPEG-2 low sample rates |
| 12 | **Video** | ✅ MP4 demux, AAC LC (89 dB vs ffmpeg), H.264 High profile CABAC (I/P/B, direct, weighted, 8x8, deblocking; bit-exact vs ffmpeg on ten streams), the Video app with A/V sync and seeking. 1920x1080 at 30 fps plays in real time on the Pi (300 of 300 pictures on the test clip): register allocation in both compilers, NEON for the pixel work (both assemblers), the parser on one core while two helper cores derive motion, rebuild, deblock and convert, and pictures drawn straight onto the screen |

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
