"""Command-line entry point: python stage0/dullc0.py program.dull -o program.s"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dullc.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
