"""Python API and format parser for the covered bitstring subset."""

from __future__ import annotations

from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
import io
import math
import re
import struct
import sys
from typing import Any, Iterable, Iterator

import numpy as np

from ._lib import addr, lib


_PARALLEL_BYTES = 4 * 1024 * 1024
_PARALLEL_TASKS = 4
_BITWISE_POOL = ThreadPoolExecutor(max_workers=_PARALLEL_TASKS)


def _parallel_ranges(size: int) -> list[tuple[int, int]]:
    chunk = (size + _PARALLEL_TASKS - 1) // _PARALLEL_TASKS
    chunk = (chunk + 63) & ~63
    return [
        (start, min(start + chunk, size))
        for start in range(0, size, chunk)
    ]


class Error(Exception):
    pass


class CreationError(Error, ValueError):
    pass


class InterpretError(Error, ValueError):
    pass


class ReadError(Error):
    pass


class ByteAlignError(Error):
    pass


class _Options:
    bytealigned = False
    lsb0 = False
    no_color = True
    mxfp_overflow = "saturate"


options = _Options()


def _array(data: bytes | bytearray | memoryview | np.ndarray) -> np.ndarray:
    if isinstance(data, np.ndarray):
        return np.ascontiguousarray(data, dtype=np.uint8).copy()
    return np.frombuffer(bytes(data), dtype=np.uint8).copy()


def _zeroed(nbits: int) -> np.ndarray:
    return np.zeros((nbits + 7) // 8, dtype=np.uint8)


def _mask_padding(data: np.ndarray, nbits: int) -> None:
    remaining = nbits & 7
    if remaining and data.size:
        data[-1] &= np.uint8((0xFF << (8 - remaining)) & 0xFF)


def _normal_range(length: int, start: int | None, end: int | None) -> tuple[int, int]:
    first, stop, _ = slice(start, end, 1).indices(length)
    return first, stop


def _uint_piece(value: int, length: int, signed: bool = False) -> tuple[np.ndarray, int]:
    if length is None or length < 0:
        raise CreationError("a non-negative length is required")
    if signed:
        if length == 0:
            raise CreationError("signed integers require a positive length")
        low, high = -(1 << (length - 1)), (1 << (length - 1)) - 1
        if not low <= value <= high:
            raise CreationError(f"{value} is outside the signed {length}-bit range")
        value &= (1 << length) - 1
    elif value < 0 or value >= (1 << length):
        raise CreationError(f"{value} is outside the unsigned {length}-bit range")
    data = _zeroed(length)
    if length <= 64 and length:
        lib().mbs_write_u64(addr(data, np.uint8), 0, length, value)
    elif length:
        raw = value.to_bytes((length + 7) // 8, "big")
        shift = len(raw) * 8 - length
        integer = int.from_bytes(raw, "big") << shift
        data[:] = np.frombuffer(integer.to_bytes(len(raw), "big"), dtype=np.uint8)
    return data, length


def _from_text(text: str, base: int, unit: int) -> tuple[np.ndarray, int]:
    value = text.strip().lower().replace("_", "")
    prefixes = {2: "0b", 8: "0o", 16: "0x"}
    if value.startswith(prefixes[base]):
        value = value[2:]
    if not value:
        return _zeroed(0), 0
    try:
        integer = int(value, base)
    except ValueError as exc:
        raise CreationError(f"invalid base-{base} bitstring") from exc
    return _uint_piece(integer, len(value) * unit)


class Bits:
    """Immutable, densely packed, MSB-first sequence of bits."""

    __slots__ = ("_data", "_len", "_pos")

    def __init__(
        self,
        auto: Any = None,
        /,
        length: int | None = None,
        offset: int | None = None,
        pos: int | None = None,
        **kwargs,
    ):
        del pos
        if kwargs:
            if auto is not None or len(kwargs) != 1:
                raise CreationError("use exactly one initializer")
            name, value = next(iter(kwargs.items()))
            if name == "bytes":
                raw = _array(value)
                source = self._from_data(raw, raw.size * 8)
                first = 0 if offset is None else int(offset)
                nbits = source._len - first if length is None else int(length)
                if first < 0 or nbits < 0 or first + nbits > source._len:
                    raise CreationError("length and offset exceed the data")
                result = source[first : first + nbits]
                self._data, self._len = result._data.copy(), result._len
                return
            piece = _encode_value(name, length, value)
            self._data, self._len = piece._data.copy(), piece._len
            return
        if auto is None:
            nbits = 0 if length is None else int(length)
            if nbits < 0:
                raise CreationError("length cannot be negative")
            self._data, self._len = _zeroed(nbits), nbits
            return
        if isinstance(auto, Bits):
            source = auto
        elif isinstance(auto, str):
            source = _parse_auto_string(auto)
        elif isinstance(auto, int):
            if length is not None:
                raise CreationError("integer positional initializer is already a length")
            if auto < 0:
                raise CreationError("length cannot be negative")
            self._data, self._len = _zeroed(auto), auto
            return
        elif isinstance(auto, (bytes, bytearray, memoryview, np.ndarray)):
            raw = _array(auto)
            source = self._from_data(raw, raw.size * 8)
        elif isinstance(auto, Iterable):
            text = "".join("1" if bool(x) else "0" for x in auto)
            source = self._from_pair(*_from_text(text, 2, 1))
        else:
            raise TypeError(f"cannot initialize Bits from {type(auto).__name__}")
        first = 0 if offset is None else int(offset)
        if first < 0 or first > source._len:
            raise CreationError("offset is outside the data")
        nbits = source._len - first if length is None else int(length)
        if nbits < 0 or first + nbits > source._len:
            raise CreationError("length and offset exceed the data")
        result = source[first : first + nbits] if first or nbits != source._len else source
        self._data, self._len = result._data.copy(), result._len

    @classmethod
    def _from_data(cls, data: np.ndarray, nbits: int):
        obj = cls.__new__(cls)
        obj._data = np.ascontiguousarray(data, dtype=np.uint8)
        obj._len = int(nbits)
        _mask_padding(obj._data, obj._len)
        if "Stream" in cls.__name__:
            obj._pos = 0
        return obj

    @classmethod
    def _from_pair(cls, data: np.ndarray, nbits: int):
        return cls._from_data(data, nbits)

    @property
    def len(self) -> int:
        return self._len

    @property
    def bin(self) -> str:
        if not self._len:
            return ""
        unpacked = np.unpackbits(self._data)[: self._len]
        return "".join("1" if x else "0" for x in unpacked)

    @property
    def hex(self) -> str:
        if self._len & 3:
            raise InterpretError("bit length must be a multiple of four")
        if not self._len:
            return ""
        return f"{self.uint:0{self._len // 4}x}"

    @property
    def oct(self) -> str:
        if self._len % 3:
            raise InterpretError("bit length must be a multiple of three")
        if not self._len:
            return ""
        return f"{self.uint:0{self._len // 3}o}"

    @property
    def bytes(self) -> bytes:
        if self._len & 7:
            raise InterpretError("bit length must be a multiple of eight")
        return self._data.tobytes()

    def tobytes(self) -> bytes:
        return self._data.tobytes()

    def tofile(self, file: io.BufferedWriter) -> None:
        file.write(self.tobytes())

    @property
    def uint(self) -> int:
        if not self._len:
            raise InterpretError("cannot interpret an empty bitstring")
        if self._len <= 64:
            return int(lib().mbs_read_u64(addr(self._data, np.uint8), 0, self._len))
        return int.from_bytes(self._data, "big") >> (self._data.size * 8 - self._len)

    @property
    def int(self) -> int:
        value = self.uint
        return value - (1 << self._len) if value & (1 << (self._len - 1)) else value

    @property
    def uintbe(self) -> int:
        return int.from_bytes(self.bytes, "big")

    @property
    def intbe(self) -> int:
        return int.from_bytes(self.bytes, "big", signed=True)

    @property
    def uintle(self) -> int:
        return int.from_bytes(self.bytes, "little")

    @property
    def intle(self) -> int:
        return int.from_bytes(self.bytes, "little", signed=True)

    uintne = property(lambda self: self.uintle if sys.byteorder == "little" else self.uintbe)
    intne = property(lambda self: self.intle if sys.byteorder == "little" else self.intbe)

    @property
    def float(self) -> float:
        return _unpack_float(self, ">")

    @property
    def floatbe(self) -> float:
        return _unpack_float(self, ">")

    @property
    def floatle(self) -> float:
        return _unpack_float(self, "<")

    floatne = property(lambda self: _unpack_float(self, "="))

    @property
    def bool(self) -> bool:
        if self._len != 1:
            raise InterpretError("bool requires exactly one bit")
        return bool(self.uint)

    @property
    def ue(self) -> int:
        value, used = _decode_ue(self, 0)
        if used != self._len:
            raise InterpretError("bitstring is not exactly one ue code")
        return value

    @property
    def se(self) -> int:
        value = self.ue
        return (value + 1) // 2 if value & 1 else -(value // 2)

    def count(self, value: Any) -> int:
        ones = (
            int(lib().mbs_count(addr(self._data, np.uint8), self._data.size))
            if self._data.size
            else 0
        )
        return ones if bool(value) else self._len - ones

    def all(self, value: Any, pos: Iterable[int] | None = None) -> bool:
        positions = range(self._len) if pos is None else pos
        target = bool(value)
        return all(self[i] == target for i in positions)

    def any(self, value: Any, pos: Iterable[int] | None = None) -> bool:
        positions = range(self._len) if pos is None else pos
        target = bool(value)
        return any(self[i] == target for i in positions)

    def find(
        self,
        bs: Any,
        /,
        start: int | None = None,
        end: int | None = None,
        bytealigned: bool | None = None,
    ) -> tuple[int] | tuple[()]:
        pattern = Bits(bs)
        if not pattern:
            raise ValueError("cannot search for an empty bitstring")
        first, stop = _normal_range(self._len, start, end)
        aligned = options.bytealigned if bytealigned is None else bytealigned
        if not self._data.size:
            return ()
        result = int(
            lib().mbs_find(
                addr(self._data, np.uint8),
                self._len,
                addr(pattern._data, np.uint8),
                pattern._len,
                first,
                stop,
                int(aligned),
            )
        )
        if result < 0:
            return ()
        if hasattr(self, "_pos"):
            self._pos = result
        return (result,)

    def findall(
        self,
        bs: Any,
        start: int | None = None,
        end: int | None = None,
        count: int | None = None,
        bytealigned: bool | None = None,
    ) -> Iterator[int]:
        pattern = Bits(bs)
        if not pattern:
            raise ValueError("cannot search for an empty bitstring")
        first, stop = _normal_range(self._len, start, end)
        aligned = options.bytealigned if bytealigned is None else bytealigned
        limit = math.inf if count is None else max(0, int(count))
        step = 8 if aligned else 1
        chunk_capacity = 65_536
        position = first
        emitted = 0
        while position + pattern._len <= stop and emitted < limit:
            capacity = min(chunk_capacity, int(limit - emitted)) if limit != math.inf else chunk_capacity
            result = np.empty(capacity, dtype=np.int64)
            found = int(
                lib().mbs_findall(
                    addr(self._data, np.uint8),
                    self._len,
                    addr(pattern._data, np.uint8),
                    pattern._len,
                    position,
                    stop,
                    int(aligned),
                    addr(result, np.int64),
                    capacity,
                )
            )
            for value in result[:found]:
                yield int(value)
            emitted += found
            if found < capacity:
                break
            position = int(result[found - 1]) + step

    def rfind(
        self,
        bs: Any,
        /,
        start: int | None = None,
        end: int | None = None,
        bytealigned: bool | None = None,
    ) -> tuple[int] | tuple[()]:
        result = None
        for result in self.findall(bs, start, end, bytealigned=bytealigned):
            pass
        if result is None:
            return ()
        if hasattr(self, "_pos"):
            self._pos = result
        return (result,)

    def startswith(self, prefix: Any, start: int | None = None, end: int | None = None) -> bool:
        first, stop = _normal_range(self._len, start, end)
        value = Bits(prefix)
        return value._len <= stop - first and self[first : first + value._len] == value

    def endswith(self, suffix: Any, start: int | None = None, end: int | None = None) -> bool:
        first, stop = _normal_range(self._len, start, end)
        value = Bits(suffix)
        return value._len <= stop - first and self[stop - value._len : stop] == value

    def cut(
        self, bits: int, start: int | None = None, end: int | None = None, count: int | None = None
    ) -> Iterator["Bits"]:
        if bits <= 0:
            raise ValueError("bits must be positive")
        first, stop = _normal_range(self._len, start, end)
        produced = 0
        while first < stop and (count is None or produced < count):
            yield self[first : min(first + bits, stop)]
            first += bits
            produced += 1

    def split(
        self,
        delimiter: Any,
        start: int | None = None,
        end: int | None = None,
        count: int | None = None,
        bytealigned: bool | None = None,
    ) -> Iterator["Bits"]:
        delim = Bits(delimiter)
        first, stop = _normal_range(self._len, start, end)
        yielded = 0
        cursor = first
        for position in self.findall(delim, first, stop, bytealigned=bytealigned):
            if count is not None and yielded >= count:
                break
            yield self[cursor:position]
            yielded += 1
            cursor = position
        if count is None or yielded < count:
            yield self[cursor:stop]

    def join(self, sequence: Iterable[Any]):
        pieces = [Bits(item) for item in sequence]
        if not pieces:
            return self.__class__()
        combined: Bits = pieces[0]
        for piece in pieces[1:]:
            combined = combined + self + piece
        return self.__class__(combined)

    def unpack(self, fmt: str | list[str | int], **kwargs) -> list[Any]:
        return _unpack_from(self, 0, fmt, kwargs)[0]

    def copy(self):
        return self.__class__(self)

    def pp(self, *args, **kwargs) -> None:
        del args, kwargs
        print(str(self))

    def __len__(self) -> int:
        return self._len

    def __bool__(self) -> bool:
        return self._len != 0

    def __getitem__(self, key):
        if isinstance(key, int):
            index = key + self._len if key < 0 else key
            if index < 0 or index >= self._len:
                raise IndexError("bit index out of range")
            return bool(self._data[index >> 3] & (1 << (7 - (index & 7))))
        if not isinstance(key, slice):
            raise TypeError("indices must be integers or slices")
        start, stop, step = key.indices(self._len)
        if step == 1:
            nbits = max(0, stop - start)
            data = _zeroed(nbits)
            if nbits:
                lib().mbs_copy_bits(
                    addr(self._data, np.uint8), start, addr(data, np.uint8), 0, nbits
                )
            return self.__class__._from_data(data, nbits)
        indices = range(start, stop, step)
        values = np.fromiter((self[i] for i in indices), dtype=np.uint8)
        data = np.packbits(values)
        return self.__class__._from_data(data, values.size)

    def __add__(self, other):
        right = Bits(other)
        data = _zeroed(self._len + right._len)
        if self._len:
            lib().mbs_copy_bits(
                addr(self._data, np.uint8), 0, addr(data, np.uint8), 0, self._len
            )
        if right._len:
            lib().mbs_copy_bits(
                addr(right._data, np.uint8),
                0,
                addr(data, np.uint8),
                self._len,
                right._len,
            )
        return self.__class__._from_data(data, self._len + right._len)

    def __radd__(self, other):
        return self.__class__(other) + self

    def __mul__(self, count: int):
        count = int(count)
        if count <= 0:
            return self.__class__()
        data = _zeroed(self._len * count)
        for i in range(count):
            if self._len:
                lib().mbs_copy_bits(
                    addr(self._data, np.uint8),
                    0,
                    addr(data, np.uint8),
                    i * self._len,
                    self._len,
                )
        return self.__class__._from_data(data, self._len * count)

    __rmul__ = __mul__

    def _binary(self, other: Any, operation: int):
        right = other if isinstance(other, Bits) else Bits(other)
        if right._len != self._len:
            raise ValueError("bitstrings must have equal length")
        data = np.empty((self._len + 7) // 8, dtype=np.uint8)
        if data.size:
            library = lib()
            left_addr = addr(self._data, np.uint8)
            right_addr = addr(right._data, np.uint8)
            data_addr = addr(data, np.uint8)
            if data.size < _PARALLEL_BYTES:
                library.mbs_binary(
                    left_addr, right_addr, data_addr, data.size, operation
                )
            else:
                futures = [
                    _BITWISE_POOL.submit(
                        library.mbs_binary_range,
                        left_addr,
                        right_addr,
                        data_addr,
                        start,
                        stop,
                        operation,
                    )
                    for start, stop in _parallel_ranges(data.size)
                ]
                for future in futures:
                    future.result()
        _mask_padding(data, self._len)
        return self.__class__._from_data(data, self._len)

    def __and__(self, other):
        return self._binary(other, 0)

    def __or__(self, other):
        return self._binary(other, 1)

    def __xor__(self, other):
        return self._binary(other, 2)

    __rand__ = __and__
    __ror__ = __or__
    __rxor__ = __xor__

    def __invert__(self):
        if not self._len:
            raise Error("cannot invert an empty bitstring")
        data = np.empty((self._len + 7) // 8, dtype=np.uint8)
        library = lib()
        source_addr = addr(self._data, np.uint8)
        data_addr = addr(data, np.uint8)
        if data.size < _PARALLEL_BYTES:
            library.mbs_invert(source_addr, data_addr, data.size)
        else:
            futures = [
                _BITWISE_POOL.submit(
                    library.mbs_invert_range,
                    source_addr,
                    data_addr,
                    start,
                    stop,
                )
                for start, stop in _parallel_ranges(data.size)
            ]
            for future in futures:
                future.result()
        _mask_padding(data, self._len)
        return self.__class__._from_data(data, self._len)

    def __lshift__(self, amount: int):
        if amount < 0:
            raise ValueError("shift cannot be negative")
        if not self._len:
            raise ValueError("cannot shift an empty bitstring")
        amount = min(amount, self._len)
        return self.__class__(self[amount:] + Bits(amount))

    def __rshift__(self, amount: int):
        if amount < 0:
            raise ValueError("shift cannot be negative")
        if not self._len:
            raise ValueError("cannot shift an empty bitstring")
        amount = min(amount, self._len)
        return self.__class__(Bits(amount) + self[: self._len - amount])

    def __contains__(self, item: Any) -> bool:
        return bool(self.find(item))

    def __eq__(self, other: Any) -> bool:
        try:
            right = Bits(other)
        except (TypeError, ValueError, Error):
            return False
        return self._len == right._len and np.array_equal(self._data, right._data)

    def __hash__(self) -> int:
        return hash((self._len, self._data.tobytes()))

    def __str__(self) -> str:
        if self._len == 0:
            return ""
        if self._len % 4 == 0:
            return "0x" + self.hex
        return "0b" + self.bin

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}('{self}')"


class BitArray(Bits):
    """Mutable Bits variant."""

    __hash__ = None

    def _assign(self, value: Bits) -> None:
        self._data, self._len = value._data.copy(), value._len
        if hasattr(self, "_pos"):
            self._pos = min(self._pos, self._len)

    def append(self, bs: Any) -> None:
        self._assign(Bits(self) + bs)

    def prepend(self, bs: Any) -> None:
        self._assign(Bits(bs) + self)

    def insert(self, bs: Any, pos: int) -> None:
        position = pos + self._len if pos < 0 else pos
        if position < 0 or position > self._len:
            raise ValueError("insert position out of range")
        self._assign(self[:position] + Bits(bs) + self[position:])

    def overwrite(self, bs: Any, pos: int) -> None:
        value = Bits(bs)
        position = pos + self._len if pos < 0 else pos
        if position < 0 or position + value._len > self._len:
            raise ValueError("overwrite exceeds bitstring")
        self._assign(self[:position] + value + self[position + value._len :])

    def delete(self, bits: int, pos: int) -> None:
        position = pos + self._len if pos < 0 else pos
        if bits < 0 or position < 0 or position + bits > self._len:
            raise ValueError("delete range out of bounds")
        self._assign(self[:position] + self[position + bits :])

    def replace(
        self,
        old: Any,
        new: Any,
        start: int | None = None,
        end: int | None = None,
        count: int | None = None,
        bytealigned: bool | None = None,
    ) -> int:
        before = Bits(old)
        after = Bits(new)
        positions: list[int] = []
        next_allowed = -1
        for position in self.findall(before, start, end, bytealigned=bytealigned):
            if position < next_allowed:
                continue
            positions.append(position)
            next_allowed = position + before._len
            if count is not None and len(positions) >= count:
                break
        if not positions:
            return 0
        pieces: list[Bits] = []
        cursor = 0
        for position in positions:
            if position < cursor:
                continue
            pieces.extend((self[cursor:position], after))
            cursor = position + before._len
        pieces.append(self[cursor:])
        result = Bits()
        for piece in pieces:
            result += piece
        self._assign(result)
        return len(positions)

    def reverse(self, start: int | None = None, end: int | None = None) -> None:
        first, stop = _normal_range(self._len, start, end)
        if stop > first:
            lib().mbs_reverse(addr(self._data, np.uint8), first, stop)

    def set(self, value: Any, pos: int | Iterable[int] | None = None) -> None:
        target = bool(value)
        if pos is None:
            if self._data.size:
                lib().mbs_fill(
                    addr(self._data, np.uint8), self._data.size, int(target)
                )
                _mask_padding(self._data, self._len)
            return
        positions = [pos] if isinstance(pos, int) else pos
        for position in positions:
            index = position + self._len if position < 0 else position
            if index < 0 or index >= self._len:
                raise IndexError("bit index out of range")
            mask = np.uint8(1 << (7 - (index & 7)))
            if target:
                self._data[index >> 3] |= mask
            else:
                self._data[index >> 3] &= np.uint8(~mask)

    def invert(self, pos: int | Iterable[int] | None = None) -> None:
        if pos is None:
            if self._data.size:
                address = addr(self._data, np.uint8)
                lib().mbs_invert(address, address, self._data.size)
                _mask_padding(self._data, self._len)
            return
        positions = [pos] if isinstance(pos, int) else pos
        for position in positions:
            index = position + self._len if position < 0 else position
            if index < 0 or index >= self._len:
                raise IndexError("bit index out of range")
            self._data[index >> 3] ^= np.uint8(1 << (7 - (index & 7)))

    def rol(self, bits: int, start: int | None = None, end: int | None = None) -> None:
        first, stop = _normal_range(self._len, start, end)
        width = stop - first
        if not width:
            raise Error("cannot rotate an empty bitstring")
        amount = bits % width
        self._assign(self[:first] + self[first + amount : stop] + self[first : first + amount] + self[stop:])

    def ror(self, bits: int, start: int | None = None, end: int | None = None) -> None:
        first, stop = _normal_range(self._len, start, end)
        width = stop - first
        if not width:
            raise Error("cannot rotate an empty bitstring")
        self.rol((-bits) % width, first, stop)

    def byteswap(
        self,
        fmt: int | Iterable[int] | str | None = None,
        start: int | None = None,
        end: int | None = None,
        repeat: bool = True,
    ) -> int:
        first, stop = _normal_range(self._len, start, end)
        if first & 7 or stop & 7:
            raise ByteAlignError("byteswap range must be byte aligned")
        if fmt is None or fmt == 0:
            sizes = [(stop - first) // 8]
        elif isinstance(fmt, int):
            if fmt < 0:
                raise ValueError("fmt cannot be negative")
            sizes = [fmt]
        elif isinstance(fmt, str):
            codes = re.findall(r"(\d*)([xcbBhHiIlLqQefd])", fmt.lstrip("@=<>!"))
            widths = {"x": 1, "c": 1, "b": 1, "B": 1, "h": 2, "H": 2, "i": 4,
                      "I": 4, "l": 4, "L": 4, "q": 8, "Q": 8, "e": 2, "f": 4, "d": 8}
            sizes = [widths[code] for count, code in codes for _ in range(int(count or 1))]
        else:
            sizes = [int(x) for x in fmt]
        group = sum(sizes) * 8
        if group == 0:
            return 0
        repetitions = (stop - first) // group if repeat else min(1, (stop - first) // group)
        raw = self._data.copy()
        byte = first // 8
        for _ in range(repetitions):
            for size in sizes:
                raw[byte : byte + size] = raw[byte : byte + size][::-1]
                byte += size
        self._data = raw
        return repetitions

    def __setitem__(self, key, value) -> None:
        if isinstance(key, int):
            self.set(value, key)
            return
        replacement = Bits(value)
        start, stop, step = key.indices(self._len)
        if step == 1:
            self._assign(self[:start] + replacement + self[stop:])
            return
        positions = list(range(start, stop, step))
        if len(positions) != replacement._len:
            raise ValueError("extended slice length mismatch")
        for position, bit in zip(positions, replacement):
            self.set(bit, position)

    def __delitem__(self, key) -> None:
        if isinstance(key, int):
            self.delete(1, key)
            return
        start, stop, step = key.indices(self._len)
        if step == 1:
            self._assign(self[:start] + self[stop:])
            return
        remove = set(range(start, stop, step))
        self._assign(Bits([self[i] for i in range(self._len) if i not in remove]))

    def __ior__(self, other):
        self._assign(self | other)
        return self

    def __iand__(self, other):
        self._assign(self & other)
        return self

    def __ixor__(self, other):
        self._assign(self ^ other)
        return self

    def __ilshift__(self, amount):
        self._assign(self << amount)
        return self

    def __irshift__(self, amount):
        self._assign(self >> amount)
        return self

    def __iadd__(self, other):
        self.append(other)
        return self

    def __imul__(self, count):
        self._assign(self * count)
        return self


class _StreamMixin:
    __slots__ = ()

    @property
    def pos(self) -> int:
        return self._pos

    @pos.setter
    def pos(self, value: int) -> None:
        position = int(value)
        if position < 0 or position > self._len:
            raise ValueError("position is outside the bitstring")
        self._pos = position

    @property
    def bytepos(self) -> int:
        if self._pos & 7:
            raise ByteAlignError("position is not byte aligned")
        return self._pos // 8

    @bytepos.setter
    def bytepos(self, value: int) -> None:
        self.pos = int(value) * 8

    def read(self, fmt: int | str):
        if isinstance(fmt, int):
            if fmt < 0 or self._pos + fmt > self._len:
                raise ReadError("read exceeds the bitstring")
            result = Bits(self[self._pos : self._pos + fmt])
            self._pos += fmt
            return result
        values, position = _unpack_from(self, self._pos, [fmt], {})
        self._pos = position
        return values[0]

    def readlist(self, fmt: str | list[int | str], **kwargs) -> list[Any]:
        values, position = _unpack_from(self, self._pos, fmt, kwargs)
        self._pos = position
        return values

    def peek(self, fmt: int | str):
        position = self._pos
        result = self.read(fmt)
        self._pos = position
        return result

    def peeklist(self, fmt: str | list[int | str], **kwargs) -> list[Any]:
        position = self._pos
        result = self.readlist(fmt, **kwargs)
        self._pos = position
        return result

    def readto(self, bs: Any, /, bytealigned: bool | None = None):
        pattern = Bits(bs)
        start = self._pos
        found = self.find(pattern, start, bytealigned=bytealigned)
        if not found:
            raise ReadError("substring not found")
        stop = found[0] + pattern._len
        result = self.__class__(self[start:stop])
        self._pos = stop
        result._pos = 0
        return result

    def bytealign(self) -> int:
        skipped = (-self._pos) & 7
        if self._pos + skipped > self._len:
            skipped = self._len - self._pos
        self._pos += skipped
        return skipped


class ConstBitStream(_StreamMixin, Bits):
    __slots__ = ()

    def __init__(self, auto: Any = None, /, length=None, offset=None, pos: int = 0, **kwargs):
        Bits.__init__(self, auto, length=length, offset=offset, **kwargs)
        self.pos = pos


class BitStream(_StreamMixin, BitArray):
    __slots__ = ()

    def __init__(self, auto: Any = None, /, length=None, offset=None, pos: int = 0, **kwargs):
        BitArray.__init__(self, auto, length=length, offset=offset, **kwargs)
        self.pos = pos

    def insert(self, bs: Any, pos: int | None = None) -> None:
        position = self._pos if pos is None else pos
        BitArray.insert(self, bs, position)
        self._pos = position + len(Bits(bs))

    def overwrite(self, bs: Any, pos: int | None = None) -> None:
        position = self._pos if pos is None else pos
        BitArray.overwrite(self, bs, position)
        self._pos = position + len(Bits(bs))


@dataclass(frozen=True)
class _Token:
    name: str
    length: int | str | None = None
    value: Any = None


_ALIASES = {
    "u": "uint",
    "i": "int",
    "f": "float",
    "b": "bin",
    "h": "hex",
    "o": "oct",
}


def _split_format(fmt: str | list[str | int], kwargs: dict[str, Any]) -> list[_Token | int]:
    items: list[str | int] = []
    source = [fmt] if isinstance(fmt, str) else fmt
    for item in source:
        if isinstance(item, int):
            items.append(item)
        else:
            items.extend(part.strip() for part in item.split(",") if part.strip())
    result: list[_Token | int] = []
    for item in items:
        if isinstance(item, int):
            result.append(item)
            continue
        repetition = 1
        match = re.match(r"^(\d+)\*(.+)$", item)
        if match:
            repetition, item = int(match.group(1)), match.group(2).strip()
        token = _parse_token(item, kwargs)
        result.extend([token] * repetition)
    return result


def _parse_token(text: str, kwargs: dict[str, Any]) -> _Token:
    if text.lower().startswith(("0b", "0x", "0o")):
        prefix = text[:2].lower()
        return _Token({"0b": "bin", "0x": "hex", "0o": "oct"}[prefix], None, text[2:])
    left, separator, value_text = text.partition("=")
    left = left.strip()
    value: Any = value_text.strip() if separator else None
    if value in kwargs:
        value = kwargs[value]
    if ":" in left:
        name, length_text = (part.strip() for part in left.split(":", 1))
    else:
        match = re.match(r"^([A-Za-z_]+)(\d+)$", left)
        if match:
            name, length_text = match.group(1), match.group(2)
        else:
            name, length_text = left, ""
    name = _ALIASES.get(name.lower(), name.lower())
    if not length_text:
        length: int | str | None = None
    elif length_text in kwargs:
        length = int(kwargs[length_text])
    else:
        try:
            length = int(length_text)
        except ValueError:
            length = length_text
    if value is None and name in kwargs:
        value = kwargs[name]
    return _Token(name, length, value)


def _parse_auto_string(text: str) -> Bits:
    stripped = text.strip()
    if stripped.lower().startswith("0b") and "," not in stripped:
        return Bits._from_pair(*_from_text(stripped, 2, 1))
    if stripped.lower().startswith("0x") and "," not in stripped:
        return Bits._from_pair(*_from_text(stripped, 16, 4))
    if stripped.lower().startswith("0o") and "," not in stripped:
        return Bits._from_pair(*_from_text(stripped, 8, 3))
    return Bits(pack(stripped))


def _float_piece(value: float, length: int, endian: str) -> Bits:
    code = {16: "e", 32: "f", 64: "d"}.get(length)
    if code is None:
        raise CreationError("float length must be 16, 32 or 64")
    return Bits(bytes=struct.pack(endian + code, float(value)))


def _unpack_float(value: Bits, endian: str) -> float:
    code = {16: "e", 32: "f", 64: "d"}.get(value._len)
    if code is None:
        raise InterpretError("float length must be 16, 32 or 64")
    return struct.unpack(endian + code, value.bytes)[0]


def _encode_ue(value: int) -> Bits:
    if value < 0:
        raise CreationError("ue cannot encode a negative value")
    code_num = value + 1
    payload = f"{code_num:b}"
    return Bits(bin="0" * (len(payload) - 1) + payload)


def _encode_value(name: str, length: int | None, value: Any) -> Bits:
    name = _ALIASES.get(name.lower(), name.lower())
    if name == "bin":
        data, nbits = _from_text(str(value), 2, 1)
        result = Bits._from_pair(data, nbits)
    elif name == "hex":
        data, nbits = _from_text(str(value), 16, 4)
        result = Bits._from_pair(data, nbits)
    elif name == "oct":
        data, nbits = _from_text(str(value), 8, 3)
        result = Bits._from_pair(data, nbits)
    elif name in ("uint", "int"):
        if length is None:
            raise CreationError(f"{name} requires a length")
        result = Bits._from_pair(*_uint_piece(int(value), length, name == "int"))
    elif name in ("uintbe", "uintle", "uintne", "intbe", "intle", "intne"):
        if length is None or length & 7:
            raise CreationError(f"{name} requires a whole-byte length")
        endian = "little" if name.endswith("le") or (name.endswith("ne") and sys.byteorder == "little") else "big"
        signed = name.startswith("int")
        try:
            raw = int(value).to_bytes(length // 8, endian, signed=signed)
        except OverflowError as exc:
            raise CreationError(str(exc)) from exc
        result = Bits(bytes=raw)
    elif name in ("float", "floatbe", "floatle", "floatne"):
        if length is None:
            raise CreationError("float requires a length")
        endian = "<" if name.endswith("le") else "=" if name.endswith("ne") else ">"
        result = _float_piece(float(value), length, endian)
    elif name == "bool":
        result = Bits._from_pair(*_uint_piece(int(bool(value)), 1))
    elif name in ("bits", "bytes"):
        result = Bits(value if name == "bits" else bytes(value))
    elif name == "pad":
        result = Bits(int(length or 0))
    elif name == "ue":
        result = _encode_ue(int(value))
    elif name == "se":
        integer = int(value)
        mapped = 2 * integer - 1 if integer > 0 else -2 * integer
        result = _encode_ue(mapped)
    else:
        raise CreationError(f"unsupported format token {name!r}")
    if length is not None and name in ("bin", "hex", "oct", "bits", "bytes"):
        expected = length * 8 if name == "bytes" else length
        if result._len != expected:
            raise CreationError(f"{name} value has {result._len} bits, expected {expected}")
    return result


def _decode_ue(source: Bits, position: int) -> tuple[int, int]:
    zeros = 0
    while position + zeros < source._len and not source[position + zeros]:
        zeros += 1
    if position + zeros >= source._len:
        raise ReadError("unterminated exponential-Golomb code")
    used = zeros * 2 + 1
    if position + used > source._len:
        raise ReadError("truncated exponential-Golomb code")
    code_num = source[position + zeros : position + used].uint
    return code_num - 1, used


def _decode_token(source: Bits, position: int, token: _Token, remaining: int) -> tuple[Any, int]:
    name = token.name
    length = token.length
    if isinstance(length, str):
        raise ValueError(f"unknown length identifier {length!r}")
    if name in ("ue", "se"):
        value, used = _decode_ue(source, position)
        if name == "se":
            value = (value + 1) // 2 if value & 1 else -(value // 2)
        return value, used
    if name == "bool":
        length = 1
    elif name == "bytes" and length is not None:
        length *= 8
    if length is None:
        length = remaining
    if length < 0 or position + length > source._len:
        raise ReadError("read exceeds the bitstring")
    piece = Bits(source[position : position + length])
    if name == "uint":
        value = piece.uint
    elif name == "int":
        value = piece.int
    elif name in ("uintbe", "uintle", "uintne", "intbe", "intle", "intne"):
        value = getattr(piece, name)
    elif name in ("float", "floatbe", "floatle", "floatne"):
        value = getattr(piece, name)
    elif name == "bool":
        value = piece.bool
    elif name == "bin":
        value = piece.bin
    elif name == "hex":
        value = piece.hex
    elif name == "oct":
        value = piece.oct
    elif name == "bytes":
        value = piece.bytes
    elif name == "bits":
        value = piece
    elif name == "pad":
        value = None
    else:
        raise InterpretError(f"unsupported format token {name!r}")
    return value, length


def _unpack_from(
    source: Bits, position: int, fmt: str | list[str | int], kwargs: dict[str, Any]
) -> tuple[list[Any], int]:
    tokens = _split_format(fmt, kwargs)
    initial_position = position
    fixed = sum(
        item
        if isinstance(item, int)
        else (
            1
            if item.name == "bool"
            else int(item.length or 0) * (8 if item.name == "bytes" else 1)
        )
        for item in tokens
        if isinstance(item, int) or item.name not in ("ue", "se")
    )
    variable = [item for item in tokens if isinstance(item, _Token) and item.length is None
                and item.name not in ("ue", "se", "bool")]
    if len(variable) > 1:
        raise Error("only one token may consume the remaining bits")
    variable_width = source._len - initial_position - fixed if variable else None
    if variable_width is not None and variable_width < 0:
        raise ReadError("format requires more bits than are available")
    values: list[Any] = []
    for item in tokens:
        if isinstance(item, int):
            width = item
            if position + width > source._len:
                raise ReadError("read exceeds the bitstring")
            values.append(Bits(source[position : position + width]))
            position += width
            continue
        remaining = source._len - position
        if item in variable:
            remaining = variable_width
        value, used = _decode_token(source, position, item, remaining)
        position += used
        if item.name != "pad":
            values.append(value)
    return values, position


def pack(fmt: str | list[str], *values, **kwargs) -> BitStream:
    tokens = _split_format(fmt, kwargs)
    supplied = iter(values)
    result = Bits()
    for item in tokens:
        if isinstance(item, int):
            raise CreationError("integer format items are only valid when reading")
        value = item.value
        if value is None and item.name != "pad":
            try:
                value = next(supplied)
            except StopIteration as exc:
                raise CreationError("not enough values for format") from exc
        result += _encode_value(item.name, item.length if isinstance(item.length, int) else None, value)
    try:
        next(supplied)
    except StopIteration:
        pass
    else:
        raise CreationError("too many values for format")
    return BitStream(result)


class Dtype:
    def __init__(self, token: str):
        parsed = _split_format(token, {})
        if len(parsed) != 1 or isinstance(parsed[0], int):
            raise ValueError("dtype must contain exactly one token")
        self._token = parsed[0]
        self.name = self._token.name
        self.bitlength = 1 if self.name == "bool" else self._token.length

    def build(self, value: Any) -> Bits:
        return self.pack(value)

    def pack(self, value: Any) -> Bits:
        return _encode_value(self.name, self.bitlength, value)

    def parse(self, value: Any) -> Any:
        return self.unpack(value)

    def unpack(self, value: Any) -> Any:
        bits = Bits(value)
        return _decode_token(bits, 0, self._token, bits._len)[0]

    def __repr__(self) -> str:
        return f"Dtype('{self.name}{self.bitlength or ''}')"


class Array:
    """Fixed-width packed array using bulk Mojo integer reads and writes."""

    def __init__(self, dtype: str | Dtype, initializer=None, trailing_bits=None):
        self.dtype = dtype if isinstance(dtype, Dtype) else Dtype(dtype)
        if not isinstance(self.dtype.bitlength, int) or self.dtype.bitlength <= 0:
            raise ValueError("Array dtype must have a fixed positive length")
        if initializer is None:
            values: list[Any] = []
        elif isinstance(initializer, int):
            values = [0] * initializer
        elif isinstance(initializer, Array):
            values = initializer.tolist()
        elif isinstance(initializer, Bits):
            self.data = BitArray(initializer)
            self.trailing_bits = Bits(trailing_bits) if trailing_bits is not None else Bits()
            return
        elif isinstance(initializer, (bytes, bytearray, memoryview)):
            self.data = BitArray(bytes=initializer)
            self.trailing_bits = Bits(trailing_bits) if trailing_bits is not None else Bits()
            return
        else:
            values = list(initializer)
        width = self.dtype.bitlength
        self.data = BitArray(len(values) * width)
        integer_kind = self.dtype.name in ("uint", "int")
        if integer_kind and width <= 64 and values:
            encoded_values: list[int] = []
            for value in values:
                integer = int(value)
                if self.dtype.name == "uint":
                    low, high = 0, (1 << width) - 1
                else:
                    low, high = -(1 << (width - 1)), (1 << (width - 1)) - 1
                if not low <= integer <= high:
                    raise CreationError(
                        f"{integer} is outside the {self.dtype.name} {width}-bit range"
                    )
                encoded_values.append(integer & ((1 << width) - 1))
            encoded = np.asarray(encoded_values, dtype=np.uint64)
            lib().mbs_write_many_u64(
                addr(self.data._data, np.uint8),
                0,
                width,
                len(values),
                width,
                addr(encoded, np.uint64),
            )
        else:
            position = 0
            for value in values:
                piece = self.dtype.pack(value)
                self.data.overwrite(piece, position)
                position += width
        self.trailing_bits = Bits(trailing_bits) if trailing_bits is not None else Bits()

    def __len__(self) -> int:
        return len(self.data) // self.dtype.bitlength

    def tolist(self) -> list[Any]:
        count = len(self)
        width = self.dtype.bitlength
        if self.dtype.name in ("uint", "int") and width <= 64 and count:
            values = np.empty(count, dtype=np.uint64)
            lib().mbs_read_many_u64(
                addr(self.data._data, np.uint8),
                0,
                width,
                count,
                width,
                addr(values, np.uint64),
            )
            if self.dtype.name == "uint":
                return [int(x) for x in values]
            sign = 1 << (width - 1)
            modulus = 1 << width
            return [int(x) - modulus if int(x) & sign else int(x) for x in values]
        return [
            self.dtype.unpack(self.data[i * width : (i + 1) * width])
            for i in range(count)
        ]

    def append(self, value: Any) -> None:
        self.data.append(self.dtype.pack(value))

    def extend(self, values: Iterable[Any]) -> None:
        for value in values:
            self.append(value)

    def insert(self, index: int, value: Any) -> None:
        self.data.insert(self.dtype.pack(value), index * self.dtype.bitlength)

    def pop(self, index: int = -1) -> Any:
        values = self.tolist()
        value = values.pop(index)
        self.__init__(self.dtype, values, self.trailing_bits)
        return value

    def reverse(self) -> None:
        values = self.tolist()
        values.reverse()
        self.__init__(self.dtype, values, self.trailing_bits)

    def byteswap(self) -> None:
        if self.dtype.bitlength & 7:
            raise ValueError("dtype must be byte aligned")
        self.data.byteswap(self.dtype.bitlength // 8)

    def __getitem__(self, key):
        values = self.tolist()
        if isinstance(key, slice):
            return Array(self.dtype, values[key])
        return values[key]

    def __setitem__(self, key, value) -> None:
        values = self.tolist()
        values[key] = value
        self.__init__(self.dtype, values, self.trailing_bits)

    def __iter__(self):
        return iter(self.tolist())

    def __repr__(self) -> str:
        return f"Array('{self.dtype.name}{self.dtype.bitlength}', {self.tolist()!r})"
