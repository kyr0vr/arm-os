"""DULL types as the stage-0 compiler sees them."""


class Type:
    # How a value of this type lives in registers:
    #   "word" - one 64-bit register (x0)
    #   "pair" - two registers (x0, x1)
    #   "mem"  - only in memory; an expression of this type yields its address in x0
    repr = "word"
    size = 8
    align = 8

    def __eq__(self, other):
        return isinstance(other, Type) and self.key() == other.key()

    def __hash__(self):
        return hash(self.key())

    def key(self):
        return (type(self).__name__,)


class Int(Type):
    def __init__(self, name, bits, signed):
        self.name, self.bits, self.signed = name, bits, signed
        self.size = self.align = bits // 8

    def key(self):
        return ("int", self.name)

    def __str__(self):
        return self.name

    @property
    def min(self):
        return -(1 << (self.bits - 1)) if self.signed else 0

    @property
    def max(self):
        return (1 << (self.bits - 1)) - 1 if self.signed else (1 << self.bits) - 1


INTS = {}
for _bits in (8, 16, 32, 64):
    INTS[f"u{_bits}"] = Int(f"u{_bits}", _bits, False)
    INTS[f"i{_bits}"] = Int(f"i{_bits}", _bits, True)
U8, U32, U64, I64 = INTS["u8"], INTS["u32"], INTS["u64"], INTS["i64"]


def unsigned_of(t):
    return INTS["u" + str(t.bits)]


class Bool(Type):
    size = align = 1

    def key(self):
        return ("bool",)

    def __str__(self):
        return "bool"


BOOL = Bool()


class Void(Type):
    size = align = 0

    def key(self):
        return ("void",)

    def __str__(self):
        return "nothing"


VOID = Void()


class IntLit(Type):
    """An integer literal that has not been given a type yet."""

    def key(self):
        return ("intlit",)

    def __str__(self):
        return "untyped number"


INTLIT = IntLit()


class NothingLit(Type):
    def key(self):
        return ("nothinglit",)

    def __str__(self):
        return "nothing"


NOTHING = NothingLit()


class Ptr(Type):
    def __init__(self, inner):
        self.inner = inner

    def key(self):
        return ("ptr", self.inner.key())

    def __str__(self):
        return f"ptr {self.inner}"


class Span(Type):
    repr = "pair"
    size = 16

    def __init__(self, inner, is_string=False):
        self.inner = inner
        self.is_string = is_string

    def key(self):
        return ("span", self.inner.key())

    def __str__(self):
        return "string" if self.is_string else f"span {self.inner}"


def STRING():
    return Span(U8, is_string=True)


class Maybe(Type):
    def __init__(self, inner):
        self.inner = inner
        if isinstance(inner, Ptr):
            self.repr = "word"     # nothing is the null pointer
            self.size = 8
        else:
            self.repr = "pair"     # x0 = value, x1 = 1 if present
            self.size = 16

    def key(self):
        return ("maybe", self.inner.key())

    def __str__(self):
        return f"maybe {self.inner}"


class Array(Type):
    repr = "mem"

    def __init__(self, inner, count):
        self.inner, self.count = inner, count
        self.size = inner.size * count
        self.align = inner.align

    def key(self):
        return ("array", self.inner.key(), self.count)

    def __str__(self):
        return f"[{self.count}] {self.inner}"


class Shape(Type):
    repr = "mem"

    def __init__(self, name, symbol):
        self.name = name
        self.symbol = symbol
        self.fields = {}     # name -> (type, offset)
        self.order = []
        self.size = 0
        self.align = 1
        self.done = False

    def key(self):
        return ("shape", self.symbol)

    def __str__(self):
        return self.name


class Choice(Type):
    size = align = 4

    def __init__(self, name, symbol, variants):
        self.name = name
        self.symbol = symbol
        self.variants = variants  # name -> index

    def key(self):
        return ("choice", self.symbol)

    def __str__(self):
        return self.name


def is_int(t):
    return isinstance(t, Int)


def is_scalar(t):
    return isinstance(t, (Int, Bool, Choice, Ptr))


def maybe_ok(inner):
    return is_scalar(inner)
