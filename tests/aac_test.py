"""The AAC decoder (lib/aac.dull) against ffmpeg.

ffmpeg's AAC encoder makes test files (tones, clicks and noise: long and short
windows, mid/side and intensity stereo, TNS; mono, 44.1 and 48 kHz, low and high
bit rates); tools/aacdec.dull decodes them on QEMU; the result must match ffmpeg's
own decode to within fixed-point rounding (at least 70 dB).

Needs ffmpeg on the PATH, and numpy.

Usage: python tests/aac_test.py
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

OUT = os.path.join(ROOT, "build", "aac")
NEED_DB = 70.0
SRC = ("0.3*sin(2*PI*440*t)+0.4*exp(-30*mod(t,0.3))*(random(0)-0.5)|"
       "0.3*sin(2*PI*330*t)+0.4*exp(-30*mod(t+0.15,0.3))*(random(1)-0.5)")
CASES = [
    # name, rate, channels, options
    ("stereo-128k", 44100, 2, ["-b:a", "128k"]),
    ("mono-96k", 44100, 1, ["-b:a", "96k"]),
    ("stereo-48k", 48000, 2, ["-b:a", "160k"]),
    ("low-rate", 44100, 2, ["-b:a", "48k"]),
    ("intensity", 44100, 2, ["-b:a", "64k", "-aac_is", "1"]),
    ("tns", 44100, 2, ["-b:a", "128k", "-aac_tns", "1"]),
]


def main():
    ff = shutil.which("ffmpeg")
    if not ff:
        raise SystemExit("aac_test needs ffmpeg on the PATH")
    os.makedirs(OUT, exist_ok=True)
    elf, _ = toolchain.build(os.path.join(ROOT, "tools", "aacdec.dull"), toolchain.VIRT, 0x4008_0000, OUT,
                             "aacdec", extra_includes=[toolchain.LIB])
    good = True
    for name, rate, channels, options in CASES:
        mp4 = os.path.join(OUT, name + ".mp4")
        ref = os.path.join(OUT, name + ".ref.pcm")
        ours = os.path.join(OUT, name + ".pcm")
        # noise substitution off: it is random, so no two decoders agree on it
        subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", f"aevalsrc=exprs='{SRC}':s={rate}:d=2",
                        "-ac", str(channels), "-c:a", "aac", "-aac_pns", "0", *options, mp4], check=True)
        subprocess.run([ff, "-v", "error", "-y", "-i", mp4, "-af", f"pan=stereo|c0=c0|c1=c{channels - 1}",
                        "-f", "s16le", ref], check=True)
        if os.path.exists(ours):
            os.remove(ours)
        code, out = qemu.run_tool(elf, ["aacdec", toolchain.rel(mp4), toolchain.rel(ours)], timeout=1200)
        if code != 0 or not os.path.exists(ours):
            print(f"FAIL {name}: aacdec exited {code}: {out.strip()}")
            good = False
            continue
        a = np.fromfile(ours, dtype="<i2").astype(np.float64).reshape(-1, 2)
        b = np.fromfile(ref, dtype="<i2").astype(np.float64).reshape(-1, 2)
        best = None
        for off in range(0, 4096):
            n = min(len(a) - off, len(b)) - 1000
            if n <= 0:
                break
            d = a[off:off + n] - b[:n]
            err = float((d * d).mean())
            if best is None or err < best[1]:
                best = (off, err, n)
        off, err, n = best
        db = 10 * np.log10(float((b[:n] ** 2).mean()) / max(err, 1e-9))
        ok = db >= NEED_DB
        good &= ok
        print(f"{'ok  ' if ok else 'FAIL'} {name}: {db:.1f} dB against ffmpeg (offset {off})")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
