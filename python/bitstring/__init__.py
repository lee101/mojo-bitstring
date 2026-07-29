"""Mojo-accelerated subset of the bitstring API."""

from .core import (
    Array,
    BitArray,
    Bits,
    BitStream,
    ByteAlignError,
    ConstBitStream,
    CreationError,
    Dtype,
    Error,
    InterpretError,
    ReadError,
    options,
    pack,
)

ConstBitArray = Bits
BitString = BitStream
ConstBitArrayError = Error
__version__ = "0.1.0"

__all__ = [
    "Array",
    "BitArray",
    "Bits",
    "BitStream",
    "BitString",
    "ByteAlignError",
    "ConstBitArray",
    "ConstBitStream",
    "CreationError",
    "Dtype",
    "Error",
    "InterpretError",
    "ReadError",
    "options",
    "pack",
]
