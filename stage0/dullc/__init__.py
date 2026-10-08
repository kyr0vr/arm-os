"""The DULL stage-0 compiler (Python). Retired once DULL compiles itself."""

from .compiler import Program
from .lexer import DullError


def compile_file(path, include_dirs=(), debug=True):
    return Program(include_dirs, debug).compile(path)
