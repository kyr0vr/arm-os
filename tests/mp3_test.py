"""The MP3 decoder (lib/mp3.dull) against ffmpeg.

ffmpeg makes test MP3s (tones, clicks and noise that make the encoder use every kind
of block, stereo and joint stereo, mono, 44.1 and 48 kHz, CBR and VBR) and decodes
them; tools/mp3dec.dull decodes the same files on QEMU; the two must agree to within
rounding: a signal-to-noise ratio of at least 60 dB.

Needs ffmpeg (with libmp3lame) on the PATH, and numpy.

Usage: python tests/mp3_test.py
"""

import os
import shutil
import subprocess
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import qemu  # noqa: E402
import toolchain  # noqa: E402

OUT = os.path.join(ROOT, "build", "mp3")
NEED_DB = 60.0

TONES = ("0.3*sin(2*PI*220*t)+0.2*sin(2*PI*277*t)+0.15*sin(2*PI*330*t)*sin(2*PI*0.5*t)"
         "+0.5*exp(-30*mod(t,0.5))*sin(2*PI*1800*t)")
NOISY = "0.3*sin(2*PI*330*t)+0.2*sin(2*PI*440*t+1)+0.4*exp(-40*mod(t+0.25,0.5))*(random(0)-0.5)"

CASES = [
    # name, channels, rate, seconds, encoder options, left, right
    ("joint-stereo-128k", 2, 44100, 4, ["-b:a", "128k", "-joint_stereo", "1"], TONES, NOISY),
    ("stereo-192k-noise", 2, 44100, 2, ["-b:a", "192k", "-joint_stereo", "0"],
     "0.6*(random(0)-0.5)", "0.6*(random(1)-0.5)"),
    ("stereo-48k", 2, 48000, 2, ["-b:a", "160k"], TONES, NOISY),
    ("vbr", 2, 44100, 2, ["-q:a", "2"], NOISY, TONES),
    ("mono-32k", 1, 32000, 2, ["-b:a", "64k"], NOISY, None),
]


def ffmpeg():
    exe = shutil.which("ffmpeg")
    if not exe:
        raise SystemExit("mp3_test needs ffmpeg on the PATH")
    return exe


def make_case(ff, name, channels, rate, seconds, options, left, right):
    mp3 = os.path.join(OUT, name + ".mp3")
    ref = os.path.join(OUT, name + ".ref.pcm")
    exprs = left if channels == 1 else f"{left}|{right}"
    subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"aevalsrc=exprs='{exprs}':s={rate}:d={seconds}", "-c:a", "libmp3lame", *options, mp3],
                   check=True)
    # mono is copied to both sides (not mixed down by 3 dB, as plain -ac 2 would)
    subprocess.run([ff, "-v", "error", "-y", "-i", mp3, "-af", "pan=stereo|c0=c0|c1=c" + ("0" if channels == 1 else "1"),
                    "-f", "s16le", ref], check=True)
    return mp3, ref


def snr(ours, ref):
    """Best alignment (ffmpeg drops the encoder delay and the info frame) and the SNR there."""
    a = np.fromfile(ours, dtype="<i2").astype(np.float64).reshape(-1, 2)
    b = np.fromfile(ref, dtype="<i2").astype(np.float64).reshape(-1, 2)
    best = None
    for off in range(0, 3000):
        n = min(len(a) - off, len(b)) - 2000
        if n <= 0:
            break
        d = a[off:off + n] - b[:n]
        err = float((d * d).mean())
        if best is None or err < best[1]:
            best = (off, err, n)
    if best is None:
        return 0.0, 0
    off, err, n = best
    sig = float((b[:n] ** 2).mean())
    return 10 * np.log10(sig / max(err, 1e-9)), off


def main():
    ff = ffmpeg()
    os.makedirs(OUT, exist_ok=True)
    elf, _ = toolchain.build(os.path.join(ROOT, "tools", "mp3dec.dull"), toolchain.VIRT, 0x4008_0000, OUT,
                             "mp3dec", extra_includes=[toolchain.LIB])
    good = True
    for case in CASES:
        name = case[0]
        mp3, ref = make_case(ff, *case)
        ours = os.path.join(OUT, name + ".pcm")
        if os.path.exists(ours):
            os.remove(ours)
        code, out = qemu.run_tool(elf, ["mp3dec", toolchain.rel(mp3), toolchain.rel(ours)], timeout=1200)
        if code != 0 or not os.path.exists(ours):
            print(f"FAIL {name}: mp3dec exited {code}: {out.strip()}")
            good = False
            continue
        db, off = snr(ours, ref)
        ok = db >= NEED_DB
        good &= ok
        print(f"{'ok  ' if ok else 'FAIL'} {name}: {db:.1f} dB against ffmpeg (offset {off})")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
