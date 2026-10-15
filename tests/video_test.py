"""The Video app end to end on QEMU: an MP4 (H.264 + AAC) on the SD card image,
opened from the launcher and played; the sound that came out must match ffmpeg's
decode of the file, a screenshot during playback must show the picture, and
`video bench` in the shell must report its decoding speed.

Needs ffmpeg (with libx264) on the PATH, and numpy.

Usage: python tests/video_test.py [--show]
"""

import os
import shutil
import subprocess
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

import qemu  # noqa: E402
import toolchain  # noqa: E402
import kernel_test  # noqa: E402

OUT = kernel_test.OUT
DISK = os.path.join(ROOT, "build", "disk", "video.img")
DOWN = "\x1b[B"
# Video, the clip (after the docs folder), two seconds in a screenshot; then the
# clip ends, back to the list (q), the launcher (q), the shell (4) and a bench run.
KEYS = ("3" + DOWN + "\r" + "\x01\x01" + "\x02" + "\x01\x01\x01" + "qq" + "4"
        + "video bench clip.mp4\n")


def main():
    show = "--show" in sys.argv
    ff = shutil.which("ffmpeg")
    if not ff:
        raise SystemExit("video_test needs ffmpeg on the PATH")
    os.makedirs(os.path.join(ROOT, "build", "h264"), exist_ok=True)
    clip = os.path.join(ROOT, "build", "h264", "clip.mp4")
    ref = os.path.join(ROOT, "build", "h264", "clip.ref.pcm")
    subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=176x144:rate=30", "-f", "lavfi",
                    "-i", "sine=frequency=440:sample_rate=44100", "-t", "3", "-c:v", "libx264", "-profile:v", "high",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-aac_pns", "0", "-b:a", "128k", "-ac", "2", clip],
                   check=True)
    subprocess.run([ff, "-v", "error", "-y", "-i", clip, "-vn", "-f", "s16le", "-ac", "2", ref], check=True)
    elf, _ = toolchain.build_kernel(os.path.join(ROOT, "rt", "virt"), 0x4008_0000, OUT)
    subprocess.run([sys.executable, os.path.join(ROOT, "tests", "make_fat_image.py"), DISK,
                    "--add", "clip.mp4", clip], check=True, capture_output=True)
    with open(os.path.join(OUT, "keys.txt"), "wb") as f:
        f.write(KEYS.encode("latin-1"))
    for name in ("audio.pcm", "screen1.raw", "screen2.raw"):
        p = os.path.join(OUT, name)
        if os.path.exists(p):
            os.remove(p)
    cmd = [qemu.path(), "-M", "virt,gic-version=2,highmem=off", "-cpu", "cortex-a76", "-smp", "4",
           "-m", "512M", "-display", "none", "-monitor", "none", "-serial", "stdio",
           "-semihosting-config", "enable=on,target=native", "-kernel", elf,
           "-drive", f"file={DISK},if=none,format=raw,id=d0", "-device", "virtio-blk-device,drive=d0"]
    r = subprocess.run(cmd, capture_output=True, timeout=900, cwd=ROOT)
    out = r.stdout.decode("utf-8", "replace").replace("\r", "")
    if show:
        print(out)
    problems = []
    played = os.path.join(OUT, "audio.pcm")
    if not os.path.exists(played) or os.path.getsize(played) == 0:
        problems.append("no sound was played")
    else:
        ours = np.fromfile(played, dtype="<i2").astype(np.float64).reshape(-1, 2)
        want = np.fromfile(ref, dtype="<i2").astype(np.float64).reshape(-1, 2)
        best = None
        for off in range(0, 4096):
            n = min(len(ours) - off, len(want)) - 1000
            if n <= 0:
                break
            d = ours[off:off + n] - want[:n]
            err = float((d * d).mean())
            if best is None or err < best[1]:
                best = (off, err, n)
        off, err, n = best
        db = 10 * np.log10(float((want[:n] ** 2).mean()) / max(err, 1e-9))
        print(f"     sound: {len(ours) / 44100:.2f} s played, {db:.1f} dB against ffmpeg")
        if db < 60:
            problems.append(f"the sound differs from ffmpeg's ({db:.1f} dB)")
    shot = os.path.join(OUT, "screen2.raw")
    if os.path.exists(shot):
        kernel_test.to_png(shot, os.path.join(OUT, "video-playing.png"))
        px = np.fromfile(shot, dtype=np.uint8).reshape(1080, 1920, 4)
        if px[200:900, 300:1600, :3].std() < 20:
            problems.append("the screenshot shows no picture")
    else:
        problems.append("no screenshot")
    for line in out.splitlines():
        if line.startswith("video:") or line.startswith("bench:"):
            print("     " + line)
    if "video:" not in out:
        problems.append("the player did not report")
    if "bench: 176x144" not in out:
        problems.append("no bench result")
    if problems:
        print("FAIL video:", "; ".join(problems))
        if not show:
            print(out[-2500:])
        return 1
    print("ok   video: an MP4 from the SD card played with picture and sound")
    return 0


if __name__ == "__main__":
    sys.exit(main())
