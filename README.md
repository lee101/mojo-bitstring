# mojo-bitstring

`mojo-bitstring` is a standalone Mojo port of the compute-heavy core of
[`bitstring`](https://github.com/scott-griffiths/bitstring). It keeps packed data in
MSB-first byte arrays and presents familiar Python names and call signatures:
`Bits`, `BitArray`, `ConstBitStream`, `BitStream`, `Array`, `Dtype`, and `pack`.

This is a compatible covered subset, not a re-export of the Python package. The
Mojo library performs popcount, bitwise transforms, bit copying, integer
extraction/insertion, bulk fixed-width array packing/parsing, reversal, filling,
and bit-pattern search.

## Coverage

The implemented subset includes:

- construction from binary, hexadecimal, octal, bytes, integers, iterables, and
  other bitstrings, including byte offsets and lengths;
- `uint`, `int`, big/little/native-endian integers, 16/32/64-bit floats, booleans,
  bytes, and signed/unsigned exponential-Golomb codes;
- format-based `pack`, `unpack`, `read`, `readlist`, `peek`, and `peeklist`, with
  repetition, literals, padding, keyword lengths, and a final stretchy token;
- immutable slicing, concatenation, repetition, shifts, bitwise operations,
  count, search, split, cut, join, prefix/suffix tests, and file output;
- mutable append, prepend, insert, overwrite, slice assignment/deletion,
  replacement, set, invert, reverse, rotate, and byte swap;
- stream positions, byte alignment, and `readto`;
- fixed-width integer and other basic `Array` types, with bulk Mojo paths for
  signed and unsigned integers up to 64 bits.

Not covered are `lsb0` indexing semantics, file-backed/memory-mapped
initializers, `uie`/`sie`, bfloat and MX/FP8 formats, the full compact-struct
grammar, pretty-print formatting options, and the full arithmetic API of
upstream `Array`. `options.lsb0` is present for source compatibility but changing
it does not alter indexing. Code relying on those features should continue to
use upstream `bitstring`.

Parity tests run against the real `bitstring 4.4.0` conda-forge package in an
isolated subprocess, so importing this package under the same module name cannot
accidentally make the comparison self-referential.

## Install and run

The supported development installation uses Pixi:

```bash
pixi install
pixi run build
pixi run test
```

The build produces `dist/libmojo-bitstring.so`. The activated Pixi environment
sets `PYTHONPATH=python`, so examples can be run directly:

```bash
pixi run python - <<'PY'
from bitstring import Array, ConstBitStream, pack

packet = pack("uint:12, int:7, bool, bytes:2", 0xABC, -12, True, b"OK")
stream = ConstBitStream(packet)
print(stream.readlist("uint:12, int:7, bool, bytes:2"))

samples = Array("uint:12", [0, 1, 2048, 4095])
print(samples.tolist(), samples.data.bin)
PY
```

This prints:

```text
[2748, -12, True, b'OK']
[0, 1, 2048, 4095] 000000000000000000000001100000000000111111111111
```

## Benchmarks

Measured on an Intel Xeon E5-2697 v4 at 2.30 GHz, Linux 6.8.0-136-generic,
Python 3.13.14, Mojo `1.1.0.dev2026081105 (e929a99e)`, and upstream
`bitstring 4.4.0`. These are the best of five runs from `pixi run bench`;
inputs are preconstructed unless the operation says pack. A ratio above 1
means Mojo is faster.

| operation | mojo-bitstring | upstream bitstring | upstream / Mojo |
|---|---:|---:|---:|
| count set bits, 16 MiB | 1.978 ms | 7.697 ms | 3.89x |
| bitwise AND, 16 MiB | 2.120 ms | 8.089 ms | 3.82x |
| invert, 16 MiB | 1.564 ms | 5.992 ms | 3.83x |
| find 64-bit value, 4 MiB byte-aligned | 2.306 ms | 3.281 ms | 1.42x |
| pack Array uint12, 500k values | 249.844 ms | 3230.849 ms | 12.93x |
| parse Array uint12, 500k values | 67.955 ms | 2173.370 ms | 31.98x |

The table is the direct output of the final benchmark run. Timings on a shared
machine vary, so the table is a reproducible snapshot rather than a general
performance guarantee.

## How it works

Python owns each buffer as a contiguous NumPy `uint8` array. Bits are numbered
MSB-first, and unused low bits in the final byte are always zero. That is the
same logical layout users see through `.bin` and `.tobytes()`, so the wrapper
does not maintain a second unpacked representation.

The Python layer passes buffer addresses across `ctypes` as 64-bit integers.
The single Mojo compilation unit reconstructs
`UnsafePointer[..., AnyOrigin[mut=True]]` values inside non-parametric C ABI
exports. Output storage is always allocated by Python; Mojo neither retains
pointers nor allocates cross-language memory. This keeps ownership simple and
makes large operations one FFI call. Small orchestration tasks and format
validation stay in Python, while repeated fixed-width fields use bulk Mojo
kernels rather than one FFI call per value.

Bitwise transforms use unaligned 64-bit SIMD vectors with scalar remainder
loops. Inputs at or above 4 MiB are split into four independent Mojo SIMD ranges
through a persistent CPU worker pool; smaller inputs stay serial to avoid task
dispatch overhead. Existing `Bits` operands pass directly to Mojo without a
defensive full-buffer copy, and result buffers are not zero-filled before
kernels that overwrite every byte.

No GPU path is included. The targeted packed-bit transforms and search perform
well below two operations per byte moved, so host-device transfers and kernel
launches would dominate rather than accelerate them.

## Development

```bash
pixi run build
pixi run test
pixi run bench
```

The benchmark task holds `/tmp/mojo-bench.lock` to avoid overlapping machine
jobs. The project is MIT licensed.
