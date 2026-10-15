"""Generate lib/mp3tables.dull: the constant tables of the MP3 decoder (lib/mp3.dull).

The Huffman decoding tables and the scale factor band widths come from minimp3
(public domain, CC0; tools/mp3_minimp3_tables.json). Everything else is computed
here from the MPEG-1 Layer III definitions, in fixed point:

  Q30 = value x 2^30 (coefficients), stored as i32.

    python tools/make_mp3_tables.py
"""

import json
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = json.load(open(os.path.join(ROOT, "tools", "mp3_minimp3_tables.json")))
Q30 = 1 << 30

# The synthesis window: the standard's D[] x 65536 for i = 0..256, mirrored to 512.
ENWINDOW = [0, -1, -1, -1, -1, -1, -1, -2, -2, -2, -2, -3, -3, -4, -4, -5, -5, -6, -7, -7, -8, -9, -10,
            -11, -13, -14, -16, -17, -19, -21, -24, -26, -29, -31, -35, -38, -41, -45, -49, -53, -58, -63,
            -68, -73, -79, -85, -91, -97, -104, -111, -117, -125, -132, -139, -147, -154, -161, -169, -176,
            -183, -190, -196, -202, -208, 213, 218, 222, 225, 227, 228, 228, 227, 224, 221, 215, 208, 200,
            189, 177, 163, 146, 127, 106, 83, 57, 29, -2, -36, -72, -111, -153, -197, -244, -294, -347,
            -401, -459, -519, -581, -645, -711, -779, -848, -919, -991, -1064, -1137, -1210, -1283, -1356,
            -1428, -1498, -1567, -1634, -1698, -1759, -1817, -1870, -1919, -1962, -2001, -2032, -2057,
            -2075, -2085, -2087, -2080, -2063, 2037, 2000, 1952, 1893, 1822, 1739, 1644, 1535, 1414, 1280,
            1131, 970, 794, 605, 402, 185, -45, -288, -545, -814, -1095, -1388, -1692, -2006, -2330, -2663,
            -3004, -3351, -3705, -4063, -4425, -4788, -5153, -5517, -5879, -6237, -6589, -6935, -7271,
            -7597, -7910, -8209, -8491, -8755, -8998, -9219, -9416, -9585, -9727, -9838, -9916, -9959,
            -9966, -9935, -9863, -9750, -9592, -9389, -9139, -8840, -8492, -8092, -7640, -7134, 6574, 5959,
            5288, 4561, 3776, 2935, 2037, 1082, 70, -998, -2122, -3300, -4533, -5818, -7154, -8540, -9975,
            -11455, -12980, -14548, -16155, -17799, -19478, -21189, -22929, -24694, -26482, -28289,
            -30112, -31947, -33791, -35640, -37489, -39336, -41176, -43006, -44821, -46617, -48390,
            -50137, -51853, -53534, -55178, -56778, -58333, -59838, -61289, -62684, -64019, -65290,
            -66494, -67629, -68692, -69679, -70590, -71420, -72169, -72835, -73415, -73908, -74313,
            -74630, -74856, -74992, 75038]


def q30(x):
    return int(round(x * Q30))


def window512():
    assert len(ENWINDOW) == 257
    known = {abs(v) for v in ENWINDOW}
    assert all(abs(v) in known for v in SRC["g_win"]), "window does not match minimp3's"
    d = [0] * 512
    for i in range(257):
        v = ENWINDOW[i]
        d[i] = v
        if i & 63:
            v = -v
        if i:
            d[512 - i] = v
    return d


def bands():
    """Long and short band boundaries for MPEG-1 44.1, 48, 32 kHz (minimp3 rows 5-7)."""
    long_b, short_b = [], []
    for row in (5, 6, 7):
        w = SRC["g_scf_long"][row * 23:row * 23 + 22]
        b = [0]
        for x in w:
            b.append(b[-1] + x)
        assert b[-1] == 576
        long_b += b                                   # 23 per rate
        s = SRC["g_scf_short"][row * 40:row * 40 + 39]
        sw = [s[3 * i] for i in range(13)]
        b = [0]
        for x in sw:
            b.append(b[-1] + x)
        assert b[-1] == 192
        short_b += b                                  # 14 per rate
    return long_b, short_b


def pow43():
    """n^(4/3) for n = 0..8206 as a mantissa in [0.5, 1) (Q30) and a power of two."""
    mant, expo = [], []
    for n in range(8207):
        if n == 0:
            mant.append(0)
            expo.append(0)
            continue
        m, e = math.frexp(n ** (4.0 / 3.0))
        mq = q30(m)
        if mq >= Q30:                                 # rounding pushed it to 1.0
            mq >>= 1
            e += 1
        mant.append(mq)
        expo.append(e)
    return mant, expo


def imdct():
    win = [[0.0] * 36 for _ in range(4)]
    for i in range(36):
        win[0][i] = math.sin(math.pi / 36 * (i + 0.5))
    for i in range(18):
        win[1][i] = math.sin(math.pi / 36 * (i + 0.5))
    for i in range(18, 24):
        win[1][i] = 1.0
    for i in range(24, 30):
        win[1][i] = math.sin(math.pi / 12 * (i - 18 + 0.5))
    for i in range(6, 12):
        win[3][i] = math.sin(math.pi / 12 * (i - 6 + 0.5))
    for i in range(12, 18):
        win[3][i] = 1.0
    for i in range(18, 36):
        win[3][i] = math.sin(math.pi / 36 * (i + 0.5))
    long_cos = [q30(math.cos(math.pi / 72 * (2 * i + 1 + 18) * (2 * k + 1))) for i in range(36) for k in range(18)]
    short_cos = [q30(math.cos(math.pi / 24 * (2 * i + 1 + 6) * (2 * k + 1))) for i in range(12) for k in range(6)]
    short_win = [q30(math.sin(math.pi / 12 * (i + 0.5))) for i in range(12)]
    windows = [q30(win[b][i]) for b in range(4) for i in range(36)]
    return long_cos, short_cos, short_win, windows


def array(name, kind, values, per_line=16):
    lines = [f"fixed {name} [{len(values)}] {kind} = ["]
    for i in range(0, len(values), per_line):
        chunk = ", ".join(str(v) for v in values[i:i + per_line])
        lines.append("    " + chunk + ("," if i + per_line < len(values) else "]"))
    return "\n".join(lines)


def main():
    long_b, short_b = bands()
    mant, expo = pow43()
    long_cos, short_cos, short_win, windows = imdct()
    ci = [-0.6, -0.535, -0.33, -0.185, -0.095, -0.041, -0.0142, -0.0037]
    cs = [q30(1 / math.sqrt(1 + c * c)) for c in ci]
    ca = [q30(c / math.sqrt(1 + c * c)) for c in ci]
    synth = [q30(math.cos((16 + i) * (2 * k + 1) * math.pi / 64)) for i in range(64) for k in range(32)]
    quarter = [q30(2 ** (r / 4)) for r in range(4)]
    out = [
        "-- Tables for the MP3 decoder (lib/mp3.dull). Generated by tools/make_mp3_tables.py - do not edit.",
        "--",
        "-- The Huffman tables (huff, quad_a, quad_b, huff_start, linbits) and the scale factor",
        "-- band widths come from minimp3 by lieff (https://github.com/lieff/minimp3), public",
        "-- domain (CC0 1.0). The rest is computed from the MPEG-1 Layer III definitions.",
        "-- Q30 means value x 2^30.",
        "",
        array("huff", "i16", SRC["tabs"]),
        "",
        array("quad_a", "u8", SRC["tab32"]),
        "",
        array("quad_b", "u8", SRC["tab33"]),
        "",
        "-- where each of the 32 big-value tables starts in `huff`",
        array("huff_start", "u16", SRC["tabindex"]),
        "",
        array("linbits", "u8", SRC["g_linbits"]),
        "",
        "-- band boundaries for 44.1, 48 and 32 kHz: 23 long ones, then 14 short ones, per rate",
        array("long_bands", "u16", long_b, 23),
        "",
        array("short_bands", "u16", short_b, 14),
        "",
        "-- n^(4/3) = pow43_m[n] / 2^30 x 2^pow43_e[n]",
        array("pow43_m", "i32", mant, 12),
        "",
        array("pow43_e", "i8", expo, 32),
        "",
        "-- 2^(r/4), Q30",
        array("quarter", "i32", quarter),
        "",
        "-- antialias butterflies, Q30",
        array("alias_s", "i32", cs),
        "",
        array("alias_a", "i32", ca),
        "",
        "-- 36-point IMDCT [i * 18 + k] and the four block windows [type * 36 + i], Q30",
        array("long_cos", "i32", long_cos, 9),
        "",
        array("windows", "i32", windows, 9),
        "",
        "-- 12-point IMDCT for short blocks [i * 6 + k] and its window, Q30",
        array("short_cos", "i32", short_cos, 6),
        "",
        array("short_win", "i32", short_win, 6),
        "",
        "-- synthesis: cos((16 + i)(2k + 1) pi / 64) [i * 32 + k], Q30",
        array("synth_cos", "i32", synth, 8),
        "",
        "-- the synthesis window D[] x 65536",
        array("window", "i32", window512(), 16),
        "",
    ]
    path = os.path.join(ROOT, "lib", "mp3tables.dull")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out))
    print("wrote", path)


if __name__ == "__main__":
    main()
