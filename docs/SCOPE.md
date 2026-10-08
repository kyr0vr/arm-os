# ArmOS — Scope

*A Rather Mundane Operating System.* A personal, for-fun operating system for the
Raspberry Pi 5, built from the ground up: our own language, compiler, assembler,
linker, kernel, drivers, file system, codecs and GUI. No borrowed toolchain in the
final product.

Status: **draft v0** (2026-10-08). Nothing is built yet.

---

## 1. Definition of done

ArmOS is done when, on a real Pi 5, from power-on:

1. It boots into a **GUI launcher** with three functions: **Text**, **Music**, **Video**.
2. **Text** opens and reads `.txt` files from the SD card (scrolling, a real font).
3. **Music** plays `.mp3` files with sound out of the monitor over HDMI.
4. **Video** plays `.mp4` files (H.264 video + AAC audio) in sync.
5. Every byte of code that runs was produced by **our own toolchain**, and that
   toolchain's compiler is written in our own language and compiles itself.

Media goes onto the SD card from a Windows PC, so the card uses FAT32.

## 2. Decisions so far

| Topic | Ruling |
|---|---|
| Target | Raspberry Pi 5 (BCM2712, 4x Cortex-A76, AArch64) |
| Ground-up level | **Level C**: own language + compiler + assembler + linker, then self-hosting |
| Self-hosting | The compiler compiles itself **on the PC**. Compiling on ArmOS is a stretch goal after "done". |
| Language style | Flow-right pipes (`->`) with plain-word structure; `=` assigns. See [LANGUAGE.md](LANGUAGE.md) |
| Language name | **Open** — wants a backronym in the spirit of ArmOS (see §9) |
| Video subset | H.264 + AAC-LC in MP4, **720p30 target**; an ffmpeg recipe converts anything else (pending confirmation) |
| Audio out | HDMI audio (the Pi 5 has no headphone jack) |
| Input | **Open** — serial keys from the PC for v1, or a USB keyboard required for done (see §8) |
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

## 4. Hardware on hand

- Raspberry Pi 5, monitor, microSD card, SD reader for the PC, assorted wiring.
- **To confirm:** a 3.3 V serial path to the JST debug header (Debug Probe or JST-SH cable).
- **To confirm:** the monitor has speakers or an audio-out jack.

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

**Drivers**: PL011 UART, framebuffer, SDHCI, HDMI audio, (later) PCIe → RP1 → xHCI → HID.

**Userland**: compositor + launcher, text reader, MP3 player, MP4 player, font renderer.

## 6. Phases

Each phase ends with something visible on the Pi or the PC.

| # | Phase | Exit criterion |
|---|---|---|
| 0 | **Stage-0 compiler** in a host language (throwaway): functions, ints, pointers, if/while, `device`, `asm` | Compiles a test program to `.s` that GNU `as` accepts (temporary crutch) |
| 1 | **Alive** | Pi 5 prints "ArmOS" over serial and fills the screen with a color |
| 2 | **Own assembler + linker** | Phase 1 image rebuilt with zero outside tools; byte-compare against GNU output |
| 3 | **Serial chainloader** | New kernels load over the cable; no more SD swaps per build |
| 4 | **Kernel core** | Timer interrupts tick, MMU on, page allocator and heap pass tests, all 4 cores say hello |
| 5 | **Text console** | Bitmap font, scrolling console on HDMI, keyboard input over serial |
| 6 | **Storage** | SDHCI driver + FAT32 read; list and print a `.txt` from the card |
| 7 | **Processes** | EL0 apps, syscalls, scheduler; the console is an app |
| 8 | **GUI + Text** | Compositor, launcher with Text/Music/Video tiles, **Text reader done** |
| 9 | **Audio** | HDMI audio plays a test tone; MP3 decoder; **Music done** |
| 10 | **Video** | MP4 demux, AAC, H.264 (I/P/B, CABAC, deblock), NEON, A/V sync; **Video done** |
| 11 | **Self-host** | The compiler, rewritten in its own language, compiles itself byte-identically |
| 12 | *(stretch / or required — see §8)* **USB input** | PCIe + RP1 + xHCI + HID: a USB keyboard drives the GUI |

Phases 0–8 are a solid, showable milestone. Phase 10 is where most of the time goes.

Phase 11 can move earlier; the later it lands, the more code is written in the
language before the compiler is rewritten in it — which is a feature: by then we
know what the language really needs.

## 7. Risks, ranked

1. **H.264 in software** — the single largest piece of code. Mitigation: a defined
   subset, the ffmpeg recipe, and NEON lanes in the language from early on.
2. **HDMI audio** — sparse documentation outside Linux source. Mitigation: start it
   right after storage, as a spike, before the MP3 decoder exists.
3. **RP1/USB** — months by itself. Mitigation: serial input until the end.
4. **Optimizer quality** — a naive compiler may be too slow for 720p decode.
   Mitigation: inline `asm` and lane types so hot loops can be hand-tuned.
5. **Debugging blind** — mitigated by the debug UART from phase 1 and QEMU `virt` + GDB.

## 8. Open questions

1. **Input for "done"**: serial-driven GUI okay, or must a USB keyboard/mouse work?
2. **Video target**: 720p30 + ffmpeg recipe, or 1080p?
3. **Serial wiring**: what exactly is on hand for the JST debug header?
4. **Monitor audio**: speakers or audio-out?
5. **Stage-0 host language**: recommendation is **Python** — it is thrown away at
   phase 11, so speed of writing beats speed of running.
6. **Language name** (§9).

## 9. Name candidates for the language

ArmOS is **A Rather Mundane Operating System**. The language should be equally unexciting.

| Name | Stands for |
|---|---|
| **DULL** | Decidedly Unremarkable Low-level Language |
| **BLAND** | Basic Language for ARM, Nothing Dazzling |
| **TEPID** | The Entirely Passable Implementation Dialect |
| **PLAIN** | Practical Language for ARM, Infrequently Noticed |
| **BEIGE** | Basic Everyday Instructions, Generally Efficient |
| **NORM** | Not Overly Remarkable Machine-code |
| **ARML** | A Rather Mundane Language (the direct sibling of ArmOS) |

Source file extension follows the name (`.dull`, `.bland`, ...).

## 10. Out of scope (for "done")

Networking, Wi-Fi/Bluetooth, multi-user, security hardening, a GPU 3D driver,
writing to FAT32 (read-only is enough for playback), porting existing software.
