"""The H.264 decoder (lib/h264.dull) against ffmpeg, bit for bit.

ffmpeg (libx264) makes small test clips covering intra-only and P-only streams, B
frames with spatial and temporal direct prediction, several slices per picture,
cropping, quantization matrices and many reference frames; tools/h264dec.dull
decodes them on QEMU; every frame must equal ffmpeg's decode exactly.

Needs ffmpeg (with libx264) on the PATH, and numpy.

Usage: python tests/h264_test.py [case ...]
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

OUT = os.path.join(ROOT, "build", "h264")

# name, source, size, seconds, encoder options
CASES = [
    ("intra", "testsrc2", "176x144", 0.2, ["-x264-params", "keyint=1:scenecut=0"]),
    ("intra-detail", "mandelbrot", "320x240", 0.1, ["-preset", "slow", "-crf", "12", "-x264-params", "keyint=1"]),
    ("p-frames", "testsrc2", "176x144", 0.4, ["-bf", "0", "-refs", "3"]),
    ("b-frames", "testsrc2", "176x144", 0.5, []),
    ("temporal-direct", "testsrc2", "176x144", 0.3, ["-x264-params", "direct=temporal"]),
    ("slices", "testsrc2", "176x144", 0.3, ["-x264-params", "slices=3"]),
    ("cropped", "testsrc2", "176x120", 0.3, []),
    ("matrices", "testsrc2", "176x144", 0.3, ["-x264-params", "cqm=jvt"]),
    ("high-quality", "testsrc2", "160x96", 0.3, ["-crf", "4", "-x264-params", "ref=5:b-adapt=2:bframes=4"]),
    ("weighted", "testsrc2", "176x144", 0.5, ["-vf", "fade=in:0:12", "-x264-params", "weightp=2"]),
]


def ffmpeg():
    exe = shutil.which("ffmpeg")
    if not exe:
        raise SystemExit("h264_test needs ffmpeg on the PATH")
    return exe


def make_case(ff, name, source, size, seconds, options):
    mp4 = os.path.join(OUT, name + ".mp4")
    ref = os.path.join(OUT, name + ".ref.yuv")
    subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", f"{source}=size={size}:rate=30", "-t", str(seconds),
                    "-c:v", "libx264", "-profile:v", "high", *options, "-pix_fmt", "yuv420p", mp4], check=True)
    subprocess.run([ff, "-v", "error", "-y", "-i", mp4, "-f", "rawvideo", "-pix_fmt", "yuv420p", ref], check=True)
    return mp4, ref


def compare(ours, ref, size):
    w, h = (int(v) for v in size.split("x"))
    frame = w * h * 3 // 2
    a = np.fromfile(ours, dtype=np.uint8)
    b = np.fromfile(ref, dtype=np.uint8)
    if len(a) != len(b):
        return f"{len(a) // frame} frames, ffmpeg has {len(b) // frame}"
    for i in range(len(b) // frame):
        fa, fb = a[i * frame:(i + 1) * frame], b[i * frame:(i + 1) * frame]
        if not np.array_equal(fa, fb):
            k = int(np.argmax(fa != fb))
            plane, x, y = "Y", 0, 0
            if k < w * h:
                x, y = k % w, k // w
            elif k < w * h * 5 // 4:
                plane, k2 = "U", k - w * h
                x, y = (k2 % (w // 2)) * 2, (k2 // (w // 2)) * 2
            else:
                plane, k2 = "V", k - w * h * 5 // 4
                x, y = (k2 % (w // 2)) * 2, (k2 // (w // 2)) * 2
            return f"frame {i} differs: {plane} first at macroblock ({x // 16}, {y // 16})"
    return None


def main():
    wanted = [a for a in sys.argv[1:] if not a.startswith("-")]
    ff = ffmpeg()
    os.makedirs(OUT, exist_ok=True)
    elf, _ = toolchain.build(os.path.join(ROOT, "tools", "h264dec.dull"), toolchain.VIRT, 0x4008_0000, OUT,
                             "h264dec", extra_includes=[toolchain.LIB])
    good = True
    for case in CASES:
        name, size = case[0], case[2]
        if wanted and name not in wanted:
            continue
        mp4, ref = make_case(ff, *case)
        ours = os.path.join(OUT, name + ".yuv")
        if os.path.exists(ours):
            os.remove(ours)
        code, out = qemu.run_tool(elf, ["h264dec", toolchain.rel(mp4), toolchain.rel(ours)], timeout=1800)
        if code != 0 or not os.path.exists(ours):
            print(f"FAIL {name}: h264dec exited {code}: {out.strip()[-500:]}")
            good = False
            continue
        problem = compare(ours, ref, size)
        frames = os.path.getsize(ref) // (int(size.split("x")[0]) * int(size.split("x")[1]) * 3 // 2)
        if problem:
            print(f"FAIL {name}: {problem}")
            good = False
        else:
            print(f"ok   {name}: {frames} frames identical to ffmpeg")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
