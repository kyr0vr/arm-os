"""ArmOS's own AArch64 assembler and linker (stage 0, Python)."""

from .assembler import assemble
from .encode import AsmError
from .linker import LinkError, link
