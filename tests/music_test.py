"""The Music app end to end on QEMU: an MP3 on the SD card image, opened from the
launcher and played; everything the kernel's audio output "plays" (QEMU writes it to
build/kernel_virt/audio.pcm) must match ffmpeg's decode of the same file, at the
player's default volume of 80%.

Needs ffmpeg (with libmp3lame) on the PATH, and numpy.

Usage: python tests/music_test.py [--show]
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
import mp3_test  # noqa: E402

OUT = kernel_test.OUT
DISK = os.path.join(ROOT, "build", "disk", "music.img")
DOWN = "\x1b[B"
# Music, the song (after the docs folder), wait two seconds, a screenshot; the song
# then plays to its end and the player goes back to its list.
KEYS = "2" + DOWN + "\r" + "\x01\x01" + "\x02"


def main():
    show = "--show" in sys.argv
    ff = mp3_test.ffmpeg()
    os.makedirs(os.path.join(ROOT, "build", "mp3"), exist_ok=True)
    song = os.path.join(ROOT, "build", "mp3", "song.mp3")
    ref = os.path.join(ROOT, "build", "mp3", "song.ref.pcm")
    subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"aevalsrc=exprs='{mp3_test.TONES}|{mp3_test.NOISY}':s=44100:d=3", "-c:a", "libmp3lame",
                    "-b:a", "128k", "-metadata", "title=A Mundane Song", "-metadata", "artist=The Test Tones",
                    song], check=True)
    subprocess.run([ff, "-v", "error", "-y", "-i", song, "-f", "s16le", "-ac", "2", ref], check=True)
    elf, _ = toolchain.build_kernel(os.path.join(ROOT, "rt", "virt"), 0x4008_0000, OUT)
    subprocess.run([sys.executable, os.path.join(ROOT, "tests", "make_fat_image.py"), DISK,
                    "--add", "song.mp3", song], check=True, capture_output=True)
    with open(os.path.join(OUT, "keys.txt"), "wb") as f:
        f.write(KEYS.encode("latin-1"))
    for name in ("audio.pcm", "screen1.raw", "screen2.raw"):
        p = os.path.join(OUT, name)
        if os.path.exists(p):
            os.remove(p)
    cmd = [qemu.path(), "-M", "virt,gic-version=2,highmem=off", "-cpu", "cortex-a76", "-smp", "4",
           "-m", "256M", "-display", "none", "-monitor", "none", "-serial", "stdio",
           "-semihosting-config", "enable=on,target=native", "-kernel", elf,
           "-drive", f"file={DISK},if=none,format=raw,id=d0", "-device", "virtio-blk-device,drive=d0"]
    r = subprocess.run(cmd, capture_output=True, timeout=600, cwd=ROOT)
    out = r.stdout.decode("utf-8", "replace").replace("\r", "")
    if show:
        print(out)
    problems = []
    played = os.path.join(OUT, "audio.pcm")
    if not os.path.exists(played) or os.path.getsize(played) == 0:
        problems.append("nothing was played")
    else:
        ours = np.fromfile(played, dtype="<i2").astype(np.float64).reshape(-1, 2)
        want = np.fromfile(ref, dtype="<i2").astype(np.float64).reshape(-1, 2) * 0.8
        best = None
        for off in range(0, 3000):
            n = min(len(ours) - off, len(want)) - 2000
            if n <= 0:
                break
            d = ours[off:off + n] - want[:n]
            err = float((d * d).mean())
            if best is None or err < best[1]:
                best = (off, err, n)
        off, err, n = best
        db = 10 * np.log10(float((want[:n] ** 2).mean()) / max(err, 1e-9))
        seconds = len(ours) / 44100
        print(f"     played {seconds:.2f} s of sound; {db:.1f} dB against ffmpeg x 0.8 (offset {off})")
        if db < 50:
            problems.append(f"the sound differs from ffmpeg's ({db:.1f} dB)")
        if seconds < 2.9:
            problems.append(f"only {seconds:.2f} s of the 3 s song was played")
    for n, name in ((2, "music-playing.png"), (1, "music-list.png")):
        raw = os.path.join(OUT, f"screen{n}.raw")
        if os.path.exists(raw):
            kernel_test.to_png(raw, os.path.join(OUT, name))
        else:
            problems.append(f"no {name}")
    if r.returncode != 0:
        problems.append(f"QEMU exited {r.returncode}")
    if problems:
        print("FAIL music:", "; ".join(problems))
        if not show:
            print(out[-2000:])
        return 1
    print("ok   music: an MP3 from the SD card played through the kernel's audio, matching ffmpeg")
    return 0


if __name__ == "__main__":
    sys.exit(main())
