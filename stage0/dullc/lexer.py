"""Lexer for DULL: turns source text into tokens, including INDENT/DEDENT."""

from dataclasses import dataclass


class DullError(Exception):
    def __init__(self, msg, file=None, line=None):
        super().__init__(msg)
        self.msg = msg
        self.file = file
        self.line = line

    def __str__(self):
        if self.file is not None and self.line is not None:
            return f"{self.file}:{self.line}: {self.msg}"
        return self.msg


KEYWORDS = {
    "to", "gives", "give", "new", "fixed", "shape", "choice", "device", "at",
    "is", "not", "and", "or", "if", "else", "while", "repeat", "hold", "until",
    "for", "each", "in", "stop", "skip", "after", "stream", "true", "false",
    "nothing", "maybe", "ptr", "addr", "deref", "span", "lanes", "of", "fix",
    "on", "core", "asm", "use", "as", "through",
}

# Longest first so the scanner is greedy.
SYMBOLS = [
    "<<=", ">>=",
    "->", "+%", "-%", "*%", "+|", "-|", "<<", ">>", "<=", ">=",
    "+=", "-=", "*=", "/=", "&=", "|=", "^=",
    "+", "-", "*", "/", "%", "&", "|", "^", "~", "<", ">", "=",
    "(", ")", "[", "]", ",", ".", ":",
]

# A line ending in one of these continues on the next line.
CONTINUES = {
    "->", "+%", "-%", "*%", "+|", "-|", "<<", ">>", "<=", ">=", "+", "-", "*",
    "/", "%", "&", "|", "^", "<", ">", "=", ",", "(", "[", "and", "or", "not",
    "is", "+=", "-=", "*=", "/=", "&=", "|=", "^=", "<<=", ">>=",
}


@dataclass
class Token:
    kind: str      # NAME INT STR CHAR KW SYM NEWLINE INDENT DEDENT EOF
    value: object
    line: int

    def __repr__(self):
        return f"{self.kind}({self.value!r})@{self.line}"


ESCAPES = {"n": 10, "t": 9, "r": 13, "0": 0, "\\": 92, '"': 34, "'": 39}


def _unescape(body, file, line):
    out = bytearray()
    i = 0
    while i < len(body):
        c = body[i]
        if c != "\\":
            out += c.encode("utf-8")
            i += 1
            continue
        if i + 1 >= len(body):
            raise DullError("string ends in a lone backslash", file, line)
        e = body[i + 1]
        if e == "x":
            hexpart = body[i + 2:i + 4]
            if len(hexpart) != 2:
                raise DullError("\\x needs two hex digits", file, line)
            out.append(int(hexpart, 16))
            i += 4
        elif e in ESCAPES:
            out.append(ESCAPES[e])
            i += 2
        else:
            raise DullError(f"unknown escape \\{e}", file, line)
    return bytes(out)


def tokenize(src, file="<input>"):
    tokens = []
    indents = [0]
    depth = 0           # open ( and [ — newlines inside them are ignored
    continuing = False  # previous line ended in a continuation token
    lines = src.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    for lineno, raw in enumerate(lines, start=1):
        # Measure indentation.
        col = 0
        while col < len(raw) and raw[col] == " ":
            col += 1
        if col < len(raw) and raw[col] == "\t":
            raise DullError("tabs are not allowed; indent with 4 spaces", file, lineno)
        rest = raw[col:]
        if rest == "" or rest.startswith("--"):
            continue

        if depth == 0 and not continuing:
            if col > indents[-1]:
                indents.append(col)
                tokens.append(Token("INDENT", None, lineno))
            else:
                while col < indents[-1]:
                    indents.pop()
                    tokens.append(Token("DEDENT", None, lineno))
                if col != indents[-1]:
                    raise DullError("indentation does not match any outer block", file, lineno)

        i = col
        line_tokens_start = len(tokens)
        while i < len(raw):
            c = raw[i]
            if c == " ":
                i += 1
                continue
            if c == "\t":
                raise DullError("tabs are not allowed", file, lineno)
            if raw.startswith("--", i):
                break
            if c.isalpha() or c == "_":
                j = i
                while j < len(raw) and (raw[j].isalnum() or raw[j] == "_"):
                    j += 1
                word = raw[i:j]
                if not word.isascii():
                    raise DullError("identifiers must be ASCII", file, lineno)
                tokens.append(Token("KW" if word in KEYWORDS else "NAME", word, lineno))
                i = j
                continue
            if c.isdigit():
                j = i
                if raw.startswith(("0x", "0X"), i):
                    j = i + 2
                    while j < len(raw) and (raw[j] in "0123456789abcdefABCDEF_"):
                        j += 1
                    text = raw[i + 2:j].replace("_", "")
                    base = 16
                elif raw.startswith(("0b", "0B"), i):
                    j = i + 2
                    while j < len(raw) and raw[j] in "01_":
                        j += 1
                    text = raw[i + 2:j].replace("_", "")
                    base = 2
                else:
                    while j < len(raw) and (raw[j].isdigit() or raw[j] == "_"):
                        j += 1
                    if j < len(raw) and raw[j] == "." and j + 1 < len(raw) and raw[j + 1].isdigit():
                        raise DullError("floats are not supported by the stage-0 compiler", file, lineno)
                    text = raw[i:j].replace("_", "")
                    base = 10
                if text == "":
                    raise DullError("malformed number", file, lineno)
                if j < len(raw) and (raw[j].isalnum() or raw[j] == "_"):
                    raise DullError(f"malformed number {raw[i:j + 1]!r}", file, lineno)
                tokens.append(Token("INT", int(text, base), lineno))
                i = j
                continue
            if c == '"':
                j = i + 1
                while j < len(raw) and raw[j] != '"':
                    j += 2 if raw[j] == "\\" else 1
                if j >= len(raw):
                    raise DullError("unterminated string", file, lineno)
                tokens.append(Token("STR", _unescape(raw[i + 1:j], file, lineno), lineno))
                i = j + 1
                continue
            if c == "'":
                j = i + 1
                while j < len(raw) and raw[j] != "'":
                    j += 2 if raw[j] == "\\" else 1
                if j >= len(raw):
                    raise DullError("unterminated character", file, lineno)
                b = _unescape(raw[i + 1:j], file, lineno)
                if len(b) != 1:
                    raise DullError("a character literal must be exactly one byte", file, lineno)
                tokens.append(Token("CHAR", b[0], lineno))
                i = j + 1
                continue
            for s in SYMBOLS:
                if raw.startswith(s, i):
                    tokens.append(Token("SYM", s, lineno))
                    if s in "([":
                        depth += 1
                    elif s in ")]":
                        depth = max(0, depth - 1)
                    i += len(s)
                    break
            else:
                raise DullError(f"unexpected character {c!r}", file, lineno)

        if len(tokens) == line_tokens_start:
            continue
        last = tokens[-1]
        continuing = last.kind in ("SYM", "KW") and last.value in CONTINUES
        if depth == 0 and not continuing:
            tokens.append(Token("NEWLINE", None, lineno))

    end = len(lines)
    if depth != 0:
        raise DullError("unclosed ( or [ at end of file", file, end)
    if tokens and tokens[-1].kind not in ("NEWLINE", "DEDENT"):
        tokens.append(Token("NEWLINE", None, end))
    while len(indents) > 1:
        indents.pop()
        tokens.append(Token("DEDENT", None, end))
    tokens.append(Token("EOF", None, end))
    return tokens
