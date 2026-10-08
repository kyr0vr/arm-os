import argparse
import sys

from . import DullError, compile_file


def main():
    ap = argparse.ArgumentParser(prog="dullc", description="DULL stage-0 compiler: .dull -> AArch64 .s")
    ap.add_argument("source")
    ap.add_argument("-o", "--output", help="output .s file (default: stdout)")
    ap.add_argument("-I", dest="include", action="append", default=[],
                    help="extra folder to search for `use`d modules")
    ap.add_argument("--release", action="store_true",
                    help="no overflow, bounds or division traps")
    args = ap.parse_args()
    try:
        asm = compile_file(args.source, args.include, debug=not args.release)
    except DullError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="\n") as f:
            f.write(asm)
    else:
        sys.stdout.write(asm)
    return 0


if __name__ == "__main__":
    sys.exit(main())
