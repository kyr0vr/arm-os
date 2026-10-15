"""Generate lib/aactables.dull: the constant tables of the AAC decoder (lib/aac.dull).

The Huffman codebooks and scale factor bands come from the PacketVideo AAC decoder
(Apache 2.0; tools/aac_pv_tables.json, notice repeated in the output). The rest is
computed here: x^(4/3), the sine and KBD windows, the twiddles and output order of
the fast IMDCT (an N/4-point FFT), the TNS coefficients.

Fixed point: Q30 = value x 2^30, Q24 = value x 2^24.

    python tools/make_aac_tables.py
"""

import json
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = json.load(open(os.path.join(ROOT, "tools", "aac_pv_tables.json")))


def q(x, bits):
    return int(round(x * (1 << bits)))


def trie(codes):
    """A binary trie over the codewords: node i has children nodes[2i] / nodes[2i + 1];
    a child >= 0 is another node, -(value + 1) a leaf."""
    nodes = [0, 0]
    for value, (code, length) in enumerate(codes):
        node = 0
        for bitpos in range(length - 1, -1, -1):
            b = (code >> bitpos) & 1
            slot = node * 2 + b
            if bitpos == 0:
                assert nodes[slot] == 0
                nodes[slot] = -(value + 1)
            else:
                if nodes[slot] == 0:
                    nodes.append(0)
                    nodes.append(0)
                    nodes[slot] = len(nodes) // 2 - 1
                node = nodes[slot]
    return nodes


def kbd(n, alpha):
    half = n // 2
    w = []
    for k in range(half + 1):
        x = math.pi * alpha * math.sqrt(max(0.0, 1.0 - (2.0 * k / half - 1.0) ** 2))
        # I0 by its series
        s, term, j = 1.0, 1.0, 1
        while term > 1e-17 * s:
            term *= (x / (2 * j)) ** 2
            s += term
            j += 1
        w.append(s)
    c = [0.0]
    for v in w:
        c.append(c[-1] + v)
    return [math.sqrt(c[k + 1] / c[half + 1]) for k in range(half)]


def sine(n):
    return [math.sin(math.pi / n * (k + 0.5)) for k in range(n // 2)]


def imdct_map(N):
    """For each output sample: which post-twiddled FFT output (k), real (0) or imaginary
    (1) part, and its sign: k << 2 | part << 1 | negative."""
    import random
    n2, n4 = N // 2, N // 4
    random.seed(1)
    X = [random.gauss(0, 1) for _ in range(n2)]
    n0 = (N / 2 + 1) / 2
    ref = [sum(X[k] * math.cos(2 * math.pi / N * (n + n0) * (k + 0.5)) for k in range(n2)) for n in range(N)]
    z = []
    for k in range(n4):
        c = math.cos(2 * math.pi * (k + 1 / 8) / N)
        s = math.sin(2 * math.pi * (k + 1 / 8) / N)
        z.append(complex(X[2 * k] * c + X[n2 - 1 - 2 * k] * s, X[n2 - 1 - 2 * k] * c - X[2 * k] * s))
    # plain DFT is fine here
    zz = [sum(z[j] * complex(math.cos(2 * math.pi * j * k / n4), -math.sin(2 * math.pi * j * k / n4))
              for j in range(n4)) for k in range(n4)]
    y = []
    for k in range(n4):
        c = math.cos(2 * math.pi * (k + 1 / 8) / N)
        s = math.sin(2 * math.pi * (k + 1 / 8) / N)
        v = zz[k]
        y.append(complex(v.real * c + v.imag * s, v.imag * c - v.real * s))
    out = []
    for n in range(N):
        best, err = None, 1e9
        for k in range(n4):
            for part, v in ((0, y[k].real), (1, y[k].imag)):
                for neg in (0, 1):
                    e = abs((-v if neg else v) - ref[n])
                    if e < err:
                        best, err = (k << 2) | (part << 1) | neg, e
        assert err < 1e-6, (N, n, err)
        out.append(best)
    return out


def array(name, kind, values, per_line=16):
    lines = [f"fixed {name} [{len(values)}] {kind} = ["]
    for i in range(0, len(values), per_line):
        chunk = ", ".join(str(v) for v in values[i:i + per_line])
        lines.append("    " + chunk + ("," if i + per_line < len(values) else "]"))
    return "\n".join(lines)


def main():
    # Huffman tries, one after the other; start of each book
    keys = [str(i) for i in range(1, 12)] + ["scl"]
    nodes, starts = [], []
    for k in keys:
        t = trie(T["books"][k])
        starts.append(len(nodes) // 2)
        base = len(nodes) // 2
        nodes += [v + base if v > 0 else v for v in t]
    # scale factor bands: band end offsets, for each sampling rate index 0-11
    long_names = ["sfb_96_1024", "sfb_96_1024", "sfb_64_1024", "sfb_48_1024", "sfb_48_1024", "sfb_32_1024",
                  "sfb_24_1024", "sfb_24_1024", "sfb_16_1024", "sfb_16_1024", "sfb_16_1024", "sfb_8_1024"]
    short_names = ["sfb_64_128", "sfb_64_128", "sfb_64_128", "sfb_48_128", "sfb_48_128", "sfb_48_128",
                   "sfb_24_128", "sfb_24_128", "sfb_16_128", "sfb_16_128", "sfb_16_128", "sfb_8_128"]
    long_bands, long_count, short_bands, short_count = [], [], [], []
    for i in range(12):
        lb = T["bands"][long_names[i]]
        sb = T["bands"][short_names[i]]
        long_count.append(len(lb))
        short_count.append(len(sb))
        long_bands += [0] + lb + [1024] * (51 - len(lb))
        short_bands += [0] + sb + [128] * (15 - len(sb))
    # x^(4/3) = m / 2^30 x 2^e for x = 0..8191
    pm, pe = [], []
    for x in range(8192):
        if x == 0:
            pm.append(0)
            pe.append(0)
            continue
        m, e = math.frexp(x ** (4.0 / 3.0))
        mq = q(m, 30)
        if mq >= 1 << 30:
            mq >>= 1
            e += 1
        pm.append(mq)
        pe.append(e)
    quarter = [q(2 ** (r / 4), 30) for r in range(4)]
    # windows (first halves; the second half is the mirror image), Q24
    sine_long = [q(v, 24) for v in sine(2048)]
    sine_short = [q(v, 24) for v in sine(256)]
    kbd_long = [q(v, 24) for v in kbd(2048, 4)]
    kbd_short = [q(v, 24) for v in kbd(256, 6)]
    # IMDCT twiddles cos/sin(2 pi (k + 1/8) / N), Q30, and FFT twiddles
    tw_long = []
    for k in range(512):
        a = 2 * math.pi * (k + 1 / 8) / 2048
        tw_long += [q(math.cos(a), 30), q(math.sin(a), 30)]
    tw_short = []
    for k in range(64):
        a = 2 * math.pi * (k + 1 / 8) / 256
        tw_short += [q(math.cos(a), 30), q(math.sin(a), 30)]
    fft512 = []
    for k in range(256):
        a = 2 * math.pi * k / 512
        fft512 += [q(math.cos(a), 30), q(math.sin(a), 30)]
    map_long = imdct_map(2048)
    map_short = imdct_map(256)
    # TNS: sin(v / iqfac) for v = -8..7, coef_res 0 and 1, Q30
    tns = []
    for res in (0, 1):
        iq = ((1 << (res + 2)) - 0.5) / (math.pi / 2)
        iqm = ((1 << (res + 2)) + 0.5) / (math.pi / 2)
        for v in range(-8, 8):
            tns.append(q(math.sin(v / (iq if v >= 0 else iqm)), 30))
    license_lines = ["-- " + line if line else "--" for line in T["_license"].splitlines()]
    out = [
        "-- Tables for the AAC decoder (lib/aac.dull). Generated by tools/make_aac_tables.py - do not edit.",
        "--",
        "-- The Huffman codebooks and the scale factor bands come from the PacketVideo AAC",
        "-- decoder in the Android Open Source Project:",
        "--",
        *license_lines,
        "--",
        "-- Everything else is computed. Q30 = value x 2^30, Q24 = value x 2^24.",
        "",
        "-- Huffman tries: node i's children are huff[2i] and huff[2i + 1]; a child >= 0 is",
        "-- a node, -(value + 1) a leaf. Books 1-11, then the scale factor book.",
        array("huff", "i16", nodes, 24),
        "",
        array("huff_start", "u16", starts),
        "",
        "-- scale factor band starts for each sampling rate index: 52 long, 16 short per rate",
        array("long_bands", "u16", long_bands, 26),
        "",
        array("long_count", "u8", long_count),
        "",
        array("short_bands", "u16", short_bands, 16),
        "",
        array("short_count", "u8", short_count),
        "",
        "-- x^(4/3) = pow43_m[x] / 2^30 x 2^pow43_e[x]",
        array("pow43_m", "i32", pm, 12),
        "",
        array("pow43_e", "i8", pe, 32),
        "",
        array("quarter", "i32", quarter),
        "",
        "-- windows, first half, Q24",
        array("sine_long", "i32", sine_long, 12),
        "",
        array("kbd_long", "i32", kbd_long, 12),
        "",
        array("sine_short", "i32", sine_short, 12),
        "",
        array("kbd_short", "i32", kbd_short, 12),
        "",
        "-- fast IMDCT: twiddles cos, sin of 2 pi (k + 1/8) / N (Q30), FFT twiddles of the",
        "-- 512-point FFT (the 64-point one uses every 8th), and where each output sample",
        "-- comes from: k << 2 | imaginary << 1 | negative",
        array("tw_long", "i32", tw_long, 8),
        "",
        array("tw_short", "i32", tw_short, 8),
        "",
        array("fft_tw", "i32", fft512, 8),
        "",
        array("map_long", "u16", map_long),
        "",
        array("map_short", "u16", map_short),
        "",
        "-- TNS reflection coefficients: [res * 16 + value + 8], Q30",
        array("tns_coef", "i32", tns, 8),
        "",
    ]
    path = os.path.join(ROOT, "lib", "aactables.dull")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out))
    print("wrote", path, "-", len(nodes) // 2, "trie nodes")


if __name__ == "__main__":
    main()
