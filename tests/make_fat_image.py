"""Build a small FAT32 disk image for testing ArmOS's file system code on QEMU.

An MBR with one FAT32 partition (type 0x0C) at sector 2048, one sector per cluster,
holding: hello.txt, "A Longer File Name.txt" (a long name), docs/notes.txt, and
big.txt (spans many clusters, to test following the cluster chain), plus any
`--add <name> <file>` (one folder level deep at most).

    python tests/make_fat_image.py [out.img] [--add apps/hello.app build/.../hello.img]
"""

import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PART_START = 2048
PART_SECTORS = 131072            # 64 MB
RESERVED = 32
FATS = 2
SPC = 1                          # sectors per cluster

FILES = {
    "hello.txt": b"Hello from a FAT32 disk!\nThis is ArmOS reading a file.\n",
    "A Longer File Name.txt": b"Long file names work too.\n",
    "docs/notes.txt": b"".join(b"note %03d: a rather mundane line of text\n" % i for i in range(60)),
    "big.txt": b"".join(b"line %05d of a big file that crosses many clusters\n" % i for i in range(400)),
}


def fat_size_sectors():
    clusters = PART_SECTORS // SPC
    return (clusters * 4 + 511) // 512


class Image:
    def __init__(self):
        self.fat_sectors = fat_size_sectors()
        self.data_start = RESERVED + FATS * self.fat_sectors      # relative to the partition
        self.fat = [0x0FFFFFF8, 0x0FFFFFFF]                        # clusters 0 and 1
        self.clusters = {}                                         # cluster -> bytes

    def alloc(self, data):
        """Store `data` in a fresh cluster chain; give the first cluster."""
        n = max(1, (len(data) + 511) // 512)
        first = len(self.fat)
        for i in range(n):
            c = first + i
            self.fat.append(c + 1 if i < n - 1 else 0x0FFFFFFF)
            self.clusters[c] = data[i * 512:(i + 1) * 512].ljust(512, b"\0")
        return first


def short_entry(name83, attr, cluster, size, nt=0):
    return struct.pack("<11sBBBHHHHHHHI", name83, attr, nt, 0, 0, 0, 0, cluster >> 16, 0, 0,
                       cluster & 0xFFFF, size)


def checksum(name83):
    s = 0
    for b in name83:
        s = (((s & 1) << 7) | (s >> 1)) + b
        s &= 0xFF
    return s


def lfn_entries(long_name, name83):
    units = [ord(c) for c in long_name] + [0]
    while len(units) % 13:
        units.append(0xFFFF)
    parts = [units[i:i + 13] for i in range(0, len(units), 13)]
    out = []
    ck = checksum(name83)
    for seq in range(len(parts), 0, -1):
        p = parts[seq - 1]
        order = seq | (0x40 if seq == len(parts) else 0)
        e = bytearray(32)
        e[0] = order
        e[11] = 0x0F
        e[13] = ck
        for i, off in enumerate([1, 3, 5, 7, 9, 14, 16, 18, 20, 22, 24, 28, 30]):
            struct.pack_into("<H", e, off, p[i])
        out.append(bytes(e))
    return out


def name_83(name, n):
    base, _, ext = name.rpartition(".")
    if not base:
        base, ext = ext, ""
    simple = base.isalnum() and len(base) <= 8 and len(ext) <= 3 and base == base.lower()
    if simple:
        return (base.upper().ljust(8) + ext.upper().ljust(3)).encode(), False
    stem = "".join(c for c in base.upper() if c.isalnum())[:6]
    return (f"{stem}~{n}".ljust(8) + ext.upper()[:3].ljust(3)).encode(), True


def build_dir(img, entries, parent=0, self_cluster=None):
    """entries: list of (name, is_dir, cluster, size). Give the directory's bytes."""
    out = []
    if self_cluster is not None:
        out.append(short_entry(b".          ", 0x10, self_cluster, 0))
        out.append(short_entry(b"..         ", 0x10, parent, 0))
    else:
        out.append(short_entry(b"ARMOS TEST ", 0x08, 0, 0))     # the volume label
    for i, (name, is_dir, cluster, size) in enumerate(entries):
        n83, long = name_83(name, i + 1)
        if long:
            out += lfn_entries(name, n83)
        nt = 0 if long else 0x18                               # lower-case base and extension
        out.append(short_entry(n83, 0x10 if is_dir else 0x20, cluster, size, nt))
    return b"".join(out)


def main():
    args = sys.argv[1:]
    files = dict(FILES)
    while "--add" in args:                     # --add <name on the disk> <file on the PC>
        i = args.index("--add")
        with open(args[i + 2], "rb") as f:
            files[args[i + 1]] = f.read()
        del args[i:i + 3]
    path = args[0] if args else os.path.join(ROOT, "build", "disk", "test.img")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img = Image()
    root_cluster = img.alloc(b"")              # cluster 2: filled in at the end
    folders = {}                               # folder name -> (cluster, entries)
    for name in files:
        if "/" in name and name.split("/")[0] not in folders:
            folders[name.split("/")[0]] = (img.alloc(b""), [])
    root_entries = []
    for name, data in files.items():
        c = img.alloc(data)
        if "/" in name:
            top, leaf = name.split("/", 1)
            folders[top][1].append((leaf, False, c, len(data)))
        else:
            root_entries.append((name, False, c, len(data)))
    for top, (cluster, entries) in folders.items():
        root_entries.append((top, True, cluster, 0))
        img.clusters[cluster] = build_dir(img, entries, 0, cluster).ljust(512, b"\0")
    rootdir = build_dir(img, root_entries)
    assert len(rootdir) <= 512
    img.clusters[root_cluster] = rootdir.ljust(512, b"\0")

    disk = bytearray((PART_START + PART_SECTORS) * 512)
    # MBR
    mbr = bytearray(512)
    struct.pack_into("<B3sB3sII", mbr, 0x1BE, 0x00, b"\xfe\xff\xff", 0x0C, b"\xfe\xff\xff", PART_START, PART_SECTORS)
    mbr[510:512] = b"\x55\xaa"
    disk[0:512] = mbr
    # boot sector
    bs = bytearray(512)
    bs[0:3] = b"\xeb\x58\x90"
    bs[3:11] = b"ARMOS   "
    struct.pack_into("<HBHBHHBHHHII", bs, 11, 512, SPC, RESERVED, FATS, 0, 0, 0xF8, 0, 63, 255, PART_START, PART_SECTORS)
    struct.pack_into("<IHHIHH", bs, 36, img.fat_sectors, 0, 0, root_cluster, 1, 6)
    bs[64] = 0x80
    bs[66] = 0x29
    struct.pack_into("<I", bs, 67, 0x12345678)
    bs[71:82] = b"ARMOS TEST "
    bs[82:90] = b"FAT32   "
    bs[510:512] = b"\x55\xaa"
    p0 = PART_START * 512
    disk[p0:p0 + 512] = bs
    disk[p0 + 6 * 512:p0 + 7 * 512] = bs
    # FATs
    fat = b"".join(struct.pack("<I", v) for v in img.fat)
    for k in range(FATS):
        off = p0 + (RESERVED + k * img.fat_sectors) * 512
        disk[off:off + len(fat)] = fat
    # data
    for c, data in img.clusters.items():
        off = p0 + (img.data_start + (c - 2) * SPC) * 512
        disk[off:off + 512] = data
    with open(path, "wb") as f:
        f.write(disk)
    print(f"wrote {path}: {len(disk) // (1024 * 1024)} MB, {len(img.fat)} clusters used")


if __name__ == "__main__":
    main()
