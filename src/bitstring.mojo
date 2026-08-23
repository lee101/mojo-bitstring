"""MSB-first packed-bit kernels exposed through a stable C ABI."""

from std.sys.info import simd_width_of
from std.memory import Pointer

comptime BPtr = Pointer[UInt8, AnyOrigin[mut=True]]
comptime IPtr = Pointer[Int64, AnyOrigin[mut=True]]
comptime UPtr = Pointer[UInt64, AnyOrigin[mut=True]]
comptime W = simd_width_of[DType.float64]()
comptime VECTOR_BYTES = W * 8


def mask(index: Int) -> UInt8:
    return UInt8(1) << UInt8(7 - (index & 7))


def get_bit(data: BPtr, index: Int) -> Bool:
    return (data[unsafe_offset=index >> 3] & mask(index)) != 0


def put_bit(data: BPtr, index: Int, value: Bool):
    var byte_index = index >> 3
    var m = mask(index)
    if value:
        data[unsafe_offset=byte_index] |= m
    else:
        data[unsafe_offset=byte_index] &= ~m


def pop_count64(value: UInt64) -> Int:
    var v = value
    v -= (v >> 1) & UInt64(0x5555555555555555)
    v = (v & UInt64(0x3333333333333333)) + (
        (v >> 2) & UInt64(0x3333333333333333)
    )
    v = (v + (v >> 4)) & UInt64(0x0F0F0F0F0F0F0F0F)
    return Int((v * UInt64(0x0101010101010101)) >> 56)


def read_u64(data: BPtr, start: Int, width: Int) -> UInt64:
    var value = UInt64(0)
    for i in range(width):
        value = (value << 1) | UInt64(1 if get_bit(data, start + i) else 0)
    return value


def write_u64(data: BPtr, start: Int, width: Int, value: UInt64):
    for i in range(width):
        put_bit(
            data,
            start + i,
            ((value >> UInt64(width - i - 1)) & UInt64(1)) != 0,
        )


def equal_at(
    data: BPtr, pattern: BPtr, position: Int, pattern_bits: Int
) -> Bool:
    for i in range(pattern_bits):
        if get_bit(data, position + i) != get_bit(pattern, i):
            return False
    return True


def equal_bytes(
    data: BPtr, pattern: BPtr, byte_position: Int, count: Int
) -> Bool:
    var i = 0
    while i + 8 <= count:
        if (
            data.unsafe_offset(byte_position + i)
            .unsafe_bitcast[UInt64]()
            .unsafe_load[alignment=1]()
            != pattern.unsafe_offset(i)
            .unsafe_bitcast[UInt64]()
            .unsafe_load[alignment=1]()
        ):
            return False
        i += 8
    while i < count:
        if data[unsafe_offset=byte_position + i] != pattern[unsafe_offset=i]:
            return False
        i += 1
    return True


def find_aligned_bytes(
    data: BPtr,
    pattern: BPtr,
    first_byte: Int,
    last_byte: Int,
    count: Int,
) -> Int:
    if count == 1:
        var position = first_byte
        while position <= last_byte:
            if data[unsafe_offset=position] == pattern[unsafe_offset=0]:
                return position
            position += 1
        return -1

    var position = first_byte
    var pattern_last = count - 1
    while position <= last_byte:
        var probe = data[unsafe_offset=position + pattern_last]
        if probe == pattern[unsafe_offset=pattern_last] and equal_bytes(
            data, pattern, position, count
        ):
            return position

        var shift = count
        var pattern_position = pattern_last - 1
        while pattern_position >= 0:
            if pattern[unsafe_offset=pattern_position] == probe:
                shift = pattern_last - pattern_position
                break
            pattern_position -= 1
        position += shift
    return -1


def binary_range(
    a: BPtr,
    b: BPtr,
    dst: BPtr,
    start: Int,
    stop: Int,
    operation: Int,
):
    var i = start
    if operation == 0:
        while i + VECTOR_BYTES <= stop:
            dst.unsafe_offset(i).unsafe_bitcast[UInt64]().unsafe_store[
                alignment=1
            ](
                0,
                a.unsafe_offset(i)
                .unsafe_bitcast[UInt64]()
                .unsafe_load[width=W, alignment=1]()
                & b.unsafe_offset(i)
                .unsafe_bitcast[UInt64]()
                .unsafe_load[width=W, alignment=1](),
            )
            i += VECTOR_BYTES
        while i < stop:
            dst[unsafe_offset=i] = a[unsafe_offset=i] & b[unsafe_offset=i]
            i += 1
    elif operation == 1:
        while i + VECTOR_BYTES <= stop:
            dst.unsafe_offset(i).unsafe_bitcast[UInt64]().unsafe_store[
                alignment=1
            ](
                0,
                a.unsafe_offset(i)
                .unsafe_bitcast[UInt64]()
                .unsafe_load[width=W, alignment=1]()
                | b.unsafe_offset(i)
                .unsafe_bitcast[UInt64]()
                .unsafe_load[width=W, alignment=1](),
            )
            i += VECTOR_BYTES
        while i < stop:
            dst[unsafe_offset=i] = a[unsafe_offset=i] | b[unsafe_offset=i]
            i += 1
    else:
        while i + VECTOR_BYTES <= stop:
            dst.unsafe_offset(i).unsafe_bitcast[UInt64]().unsafe_store[
                alignment=1
            ](
                0,
                a.unsafe_offset(i)
                .unsafe_bitcast[UInt64]()
                .unsafe_load[width=W, alignment=1]()
                ^ b.unsafe_offset(i)
                .unsafe_bitcast[UInt64]()
                .unsafe_load[width=W, alignment=1](),
            )
            i += VECTOR_BYTES
        while i < stop:
            dst[unsafe_offset=i] = a[unsafe_offset=i] ^ b[unsafe_offset=i]
            i += 1


def invert_range(src: BPtr, dst: BPtr, start: Int, stop: Int):
    var i = start
    while i + VECTOR_BYTES <= stop:
        dst.unsafe_offset(i).unsafe_bitcast[UInt64]().unsafe_store[alignment=1](
            0,
            ~src.unsafe_offset(i)
            .unsafe_bitcast[UInt64]()
            .unsafe_load[width=W, alignment=1](),
        )
        i += VECTOR_BYTES
    while i < stop:
        dst[unsafe_offset=i] = ~src[unsafe_offset=i]
        i += 1


@export("mbs_count")
def mbs_count(src_addr: Int, nbytes: Int) abi("C") -> Int:
    var src = BPtr(unsafe_from_address=src_addr)
    var total = 0
    var i = 0
    while i + 8 <= nbytes:
        total += pop_count64(
            src.unsafe_offset(i)
            .unsafe_bitcast[UInt64]()
            .unsafe_load[alignment=1]()
        )
        i += 8
    while i < nbytes:
        var v = src[unsafe_offset=i]
        while v != 0:
            v &= v - 1
            total += 1
        i += 1
    return total


@export("mbs_binary")
def mbs_binary(
    a_addr: Int, b_addr: Int, dst_addr: Int, nbytes: Int, operation: Int
) abi("C"):
    var a = BPtr(unsafe_from_address=a_addr)
    var b = BPtr(unsafe_from_address=b_addr)
    var dst = BPtr(unsafe_from_address=dst_addr)
    binary_range(a, b, dst, 0, nbytes, operation)


@export("mbs_binary_range")
def mbs_binary_range(
    a_addr: Int,
    b_addr: Int,
    dst_addr: Int,
    start: Int,
    stop: Int,
    operation: Int,
) abi("C"):
    binary_range(
        BPtr(unsafe_from_address=a_addr),
        BPtr(unsafe_from_address=b_addr),
        BPtr(unsafe_from_address=dst_addr),
        start,
        stop,
        operation,
    )


@export("mbs_invert")
def mbs_invert(src_addr: Int, dst_addr: Int, nbytes: Int) abi("C"):
    var src = BPtr(unsafe_from_address=src_addr)
    var dst = BPtr(unsafe_from_address=dst_addr)
    invert_range(src, dst, 0, nbytes)


@export("mbs_invert_range")
def mbs_invert_range(
    src_addr: Int, dst_addr: Int, start: Int, stop: Int
) abi("C"):
    invert_range(
        BPtr(unsafe_from_address=src_addr),
        BPtr(unsafe_from_address=dst_addr),
        start,
        stop,
    )


@export("mbs_read_u64")
def mbs_read_u64(src_addr: Int, start: Int, width: Int) abi("C") -> UInt64:
    return read_u64(BPtr(unsafe_from_address=src_addr), start, width)


@export("mbs_write_u64")
def mbs_write_u64(
    dst_addr: Int, start: Int, width: Int, value: UInt64
) abi("C"):
    write_u64(BPtr(unsafe_from_address=dst_addr), start, width, value)


@export("mbs_read_many_u64")
def mbs_read_many_u64(
    src_addr: Int,
    start: Int,
    width: Int,
    count: Int,
    stride: Int,
    dst_addr: Int,
) abi("C"):
    var src = BPtr(unsafe_from_address=src_addr)
    var dst = UPtr(unsafe_from_address=dst_addr)
    for i in range(count):
        dst[unsafe_offset=i] = read_u64(src, start + i * stride, width)


@export("mbs_write_many_u64")
def mbs_write_many_u64(
    dst_addr: Int,
    start: Int,
    width: Int,
    count: Int,
    stride: Int,
    src_addr: Int,
) abi("C"):
    var dst = BPtr(unsafe_from_address=dst_addr)
    var src = UPtr(unsafe_from_address=src_addr)
    for i in range(count):
        write_u64(dst, start + i * stride, width, src[unsafe_offset=i])


@export("mbs_copy_bits")
def mbs_copy_bits(
    src_addr: Int, src_start: Int, dst_addr: Int, dst_start: Int, count: Int
) abi("C"):
    var src = BPtr(unsafe_from_address=src_addr)
    var dst = BPtr(unsafe_from_address=dst_addr)
    for i in range(count):
        put_bit(dst, dst_start + i, get_bit(src, src_start + i))


@export("mbs_find")
def mbs_find(
    src_addr: Int,
    src_bits: Int,
    pattern_addr: Int,
    pattern_bits: Int,
    start: Int,
    stop: Int,
    byte_aligned: Int,
) abi("C") -> Int:
    var src = BPtr(unsafe_from_address=src_addr)
    var pattern = BPtr(unsafe_from_address=pattern_addr)
    var last = min(stop, src_bits) - pattern_bits
    if last < start:
        return -1
    var step = 8 if byte_aligned != 0 else 1
    var position = start
    if byte_aligned != 0 and (position & 7) != 0:
        position += 8 - (position & 7)
    if byte_aligned != 0 and (pattern_bits & 7) == 0:
        var pattern_bytes = pattern_bits >> 3
        var found = find_aligned_bytes(
            src, pattern, position >> 3, last >> 3, pattern_bytes
        )
        return found << 3 if found >= 0 else -1
    while position <= last:
        if equal_at(src, pattern, position, pattern_bits):
            return position
        position += step
    return -1


@export("mbs_findall")
def mbs_findall(
    src_addr: Int,
    src_bits: Int,
    pattern_addr: Int,
    pattern_bits: Int,
    start: Int,
    stop: Int,
    byte_aligned: Int,
    result_addr: Int,
    capacity: Int,
) abi("C") -> Int:
    var src = BPtr(unsafe_from_address=src_addr)
    var pattern = BPtr(unsafe_from_address=pattern_addr)
    var result = IPtr(unsafe_from_address=result_addr)
    var last = min(stop, src_bits) - pattern_bits
    if last < start:
        return 0
    var step = 8 if byte_aligned != 0 else 1
    var position = start
    var found = 0
    if byte_aligned != 0 and (position & 7) != 0:
        position += 8 - (position & 7)
    if byte_aligned != 0 and (pattern_bits & 7) == 0:
        var pattern_bytes = pattern_bits >> 3
        var byte_position = position >> 3
        var last_byte = last >> 3
        while byte_position <= last_byte and found < capacity:
            var match_position = find_aligned_bytes(
                src, pattern, byte_position, last_byte, pattern_bytes
            )
            if match_position < 0:
                break
            result[unsafe_offset=found] = Int64(match_position << 3)
            found += 1
            byte_position = match_position + 1
        return found
    while position <= last and found < capacity:
        if equal_at(src, pattern, position, pattern_bits):
            result[unsafe_offset=found] = Int64(position)
            found += 1
        position += step
    return found


@export("mbs_reverse")
def mbs_reverse(src_addr: Int, start: Int, stop: Int) abi("C"):
    var src = BPtr(unsafe_from_address=src_addr)
    var left = start
    var right = stop - 1
    while left < right:
        var a = get_bit(src, left)
        var b = get_bit(src, right)
        put_bit(src, left, b)
        put_bit(src, right, a)
        left += 1
        right -= 1


@export("mbs_fill")
def mbs_fill(dst_addr: Int, nbytes: Int, value: Int) abi("C"):
    var dst = BPtr(unsafe_from_address=dst_addr)
    var byte = UInt8(255 if value != 0 else 0)
    var i = 0
    var vec = SIMD[DType.uint64, W](
        UInt64(0xFFFFFFFFFFFFFFFF) if value != 0 else UInt64(0)
    )
    while i + VECTOR_BYTES <= nbytes:
        dst.unsafe_bitcast[UInt64]().unsafe_store[alignment=1](i >> 3, vec)
        i += VECTOR_BYTES
    while i < nbytes:
        dst[unsafe_offset=i] = byte
        i += 1
