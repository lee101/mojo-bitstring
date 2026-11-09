# Mojo-bitstring — measured hotspot map (ANALYZE phase)

> Read first: `MOJO_NOTES.md`, `bench/bench.py`, `README.md`.
> Rules for this phase: **no algorithm changes**; `src/` and `tests/` untouched; the only new file is this one.
> Every number below comes from a run executed in this session (best-of-N, `time.perf_counter()`), not from estimates or from `README.md`'s snapshot.

## Method and environment (this session)

- Host: `Intel(R) Xeon(R) CPU E5-2697 v4 @ 2.30GHz`, 72 logical cores, Linux `6.8.0-147-generic`, Python `3.13.14`, Mojo `1.2.0.dev2026092605 (236c32cb)`, upstream `bitstring 4.4.0` (conda-forge, per `pixi.toml` / `bench/bench.py`).
- `pixi run bench` (flock-wrapped, run solo, no other benchmark alongside it) — exact output in §1.
- Additional probes in §2–§4 were run via `pixi run python` scripts that isolate upstream exactly as `bench/bench.py` does (remove `python/` from `sys.path`, `import bitstring` → upstream 4.4.0, load the port via `importlib.util.spec_from_file_location`). Without that isolation `PYTHONPATH=python` makes "upstream" and "mojo" the same module — an early probe that did this produced meaningless ≈1.0× ratios and was discarded. All ratios below use the isolated upstream.
- Numpy baselines are plain `numpy` on the same bytes (`a & b`, `~a`, `np.bitwise_count(a).sum()`, `bytes.find`, `np.concatenate`) unless stated.
- FLOP counting convention: 1 byte-wise AND/OR/XOR/NOT = 1 flop per byte processed; popcount (SWAR `mbs_count`) ≈ 12 integer ops per 8 bytes = 1.5 flops/byte; `find` comparisons counted as bytes inspected. `flops-per-byte` in the tables uses these conventions so a GPU verdict can be checked. Measured effective bandwidth = bytes-touched / time.

### What the port actually is (for interpreting "glue vs kernel")

- Python (`python/bitstring/core.py`, 1441 lines) owns the `uint8` ndarray, format grammar (`_split_format`/`_parse_token`/`_encode_value`/`_decode_token`), and every public call. Mojo (`src/bitstring.mojo`, 424 lines) exposes 13 C-ABI kernels: `mbs_count`, `mbs_binary[_range]`, `mbs_invert[_range]`, `mbs_read/write_u64`, `mbs_read/write_many_u64`, `mbs_copy_bits`, `mbs_find[all]`, `mbs_reverse`, `mbs_fill`. SIMD width `W = simd_width_of[DType.float64]()` (= 4 on this host → `VECTOR_BYTES = 32`).
- The only parallelism is a Python `ThreadPoolExecutor(4)` that splits `mbs_binary_range` / `mbs_invert_range` at ≥ 4 MiB (`_PARALLEL_BYTES`). No `max.algorithm.parallelize`, no GPU path — consistent with `README.md` "No GPU path is included".
- `addr()` (`_lib.py`) validates dtype/contiguity and returns `ctypes.data`; measured **2.30 µs/call** vs raw ctypes kernel call **0.87 µs/call** (see §5). Every Mojo call in `core.py` pays 1–3 `addr()`s plus `lib()` lookup.

## 1. `pixi run bench` — official comparison (this session, solo)

```
Machine: Intel(R) Xeon(R) CPU E5-2697 v4 @ 2.30GHz
Linux 6.8.0-147-generic, Python 3.13.14, Mojo 1.2.0.dev2026092605 (236c32cb), upstream bitstring 4.4.0

| operation | mojo-bitstring | upstream bitstring | upstream / Mojo |
|---|---:|---:|---:|
| count set bits, 16 MiB | 1.896 ms | 8.017 ms | 4.23x |
| bitwise AND, 16 MiB | 2.796 ms | 7.254 ms | 2.59x |
| invert, 16 MiB | 1.739 ms | 6.002 ms | 3.45x |
| find 64-bit value, 4 MiB byte-aligned | 2.119 ms | 3.261 ms | 1.54x |
| pack Array uint12, 500k values | 244.605 ms | 3946.259 ms | 16.13x |
| parse Array uint12, 500k values | 67.772 ms | 2722.910 ms | 40.18x |
```

Note: `README.md`'s table (Mojo 1.1.0, older kernel) shows different absolutes (e.g. count 1.978 ms, AND 2.120 ms) — the qualitative ranking matches, the absolutes do not. Use the rows above for this host.

## 2. Ranked hotspot table — all public entry points, realistic sizes

Ranked by **absolute Mojo time at the largest realistic size** (the wall-clock a caller pays). `▲ SLOWER` = port slower than upstream at that size (kept, not dropped, per the brief). Sizes were chosen at real-caller scale: 64 KiB / 1 MiB / 16 MiB for bulk ops, 4 MiB for search, 500k elements for `Array`, 1000 tokens for `pack`/`unpack`, 8 bytes for the per-call floor. Times are best-of-5 (best-of-2000 for the tiny floor).

| rank | function | input size | mojo time | upstream | numpy/plain baseline | bytes touched | flops | flops/byte | bound | time sits in | upstream/Mojo |
|---:|---|---|---:|---:|---:|---:|---:|---:|---|---|---:|
| 1 | `Bits.__getitem__` step≠1, e.g. `b[::2]` | 16 MiB | 36230 ms | 278 ms | — | ~16 MiB read (per-bit in Python) | ~134 M (1/bit) | ~1.0 | compute (Python) | **Python loop + per-element `__getitem__`** | **0.01 ▲ SLOWER** |
| 2 | `Bits.__add__` (concat) | 16 MiB + 16 MiB | 1689 ms | 31.8 ms | 13.5 ms (`np.concatenate`) | 67.1 MB (zeros 32 MiB + 2× copy) | 16.8 M | 0.25 | memory + Python glue | **Python: `_zeroed` + 2× `mbs_copy_bits` (bit-at-a-time) + copy** | **0.02 ▲ SLOWER** |
| 3 | `Bits.__mul__` (repeat ×3) | 16 MiB | 2540 ms | 47.1 ms | — | 50.3 MB | 16.8 M | 0.33 | memory + Python loop | **Python loop `for i in range(count): mbs_copy_bits`** — one FFI call per copy | **0.02 ▲ SLOWER** |
| 4 | `Bits.__lshift__` (<<64) | 16 MiB | 1675 ms | 4.6 ms | — | ~16 MiB ×(2 slices + 2 copies + concat) | 16.8 M | 0.33 | Python glue (no kernel exists) | **Python: `self[amount:] + Bits(amount)` → 2 slices + 2 copies + concat** | **0.00 ▲ SLOWER** |
| 5 | `BitArray.rol` (rol 8) | 4 MiB | 838 ms | 1.4 ms | — | ~4 MiB ×4 (slices + concat) | 4.2 M | 0.25 | Python glue | **Python: 3 slices + 2 concats, no rotate kernel** | **0.00 ▲ SLOWER** |
| 6 | `BitArray.reverse` | 4 MiB | 121 ms | 5.7 ms | — | 4 MiB (in place) | 33.5 M bit-swaps | 8.0 | compute (kernel) + Python | **Mojo `mbs_reverse`: per-bit `get_bit`/`put_bit`** | **0.05 ▲ SLOWER** |
| 7 | `find` unaligned | 4 MiB, 64-bit needle at end | 312 ms | 416 ms | — | 4 MiB scanned × 64-bit `equal_at` | ~33 M × 64 | 8.0 | compute (kernel) | **Mojo `mbs_find`: `equal_at` bit-at-a-time over every position** | 1.33 |
| 8 | `Array` pack `uint:12` | 500k values | 238 ms | 2935 ms | — | ~5.5 MB (500k×8 B `uint64` src + 750 KB dst + zeroed dst) | ~500k×12 bit-writes | ~1.0 | **Python glue** | **Python `for value in values` validation/encode loop + 1 bulk FFI** | 12.3 |
| 9 | `pack` `uint:12` ×1000 | 1000 values | 45.9 ms | 5.7 ms | — | ~1.5 KB data | ~12k bit-writes | ~1.0 | **Python glue** | **Python: 1000× `_encode_value` + `result +=` (each `__add__` = zero + 2× `mbs_copy_bits`)** | **0.12 ▲ SLOWER** |
| 10 | `Array` pack `uint:64` | 500k values | 332 ms | 3173 ms | — | ~8 MB | ~32 M | ~4 | Python glue | same Python encode loop (SWAR `write_u64` inside is not the bottleneck) | 9.6 |
| 11 | `Array` parse `uint:64` | 500k values | 103 ms | 1767 ms | — | ~8 MB | ~32 M | ~4 | Python + kernel | bulk `mbs_read_many_u64` (kernel) + `[int(x) for x in values]` (Python) | 17.1 |
| 12 | `Array` parse `uint:12` | 500k values | 64.7 ms | 2039 ms | — | ~4.8 MB | ~6 M | ~1.25 | Python + kernel | `mbs_read_many_u64` + Python list-comp conversion | 31.5 |
| 13 | `Array` pack `uint:8/<64` | 500k values | 177–332 ms | 2779–3250 ms | — | 4–8 MB | 4–32 M | 1–4 | Python glue | Python encode loop dominates for every width | 10–16 |
| 14 | `BitArray.reverse` | 256 KiB | 7.57 ms | 0.33 ms | — | 256 KiB | 2.1 M bit-swaps | 8.0 | compute (kernel) | per-bit kernel (same as rank 6) | **0.04 ▲ SLOWER** |
| 15 | `unpack` `uint:12` ×1000 | 1000 values | 20.7 ms | 6.7 ms | — | ~1.5 KB | ~12k bit-reads | ~1.0 | **Python glue** | **Python: 1000× `_decode_token` + `Bits(source[a:b])` slice per token (each = `mbs_copy_bits`)** | **0.32 ▲ SLOWER** |
| 16 | `BitArray.byteswap(2)` | 1 MiB | 653 ms | 1032 ms | — | 1 MiB (copy + in-place slice assign) | ~1 M byte swaps | 1.0 | R/W amplification | **Python: `raw.copy()` + `raw[byte:byte+size] = raw[…][::-1]` per group** | 1.58 |
| 17 | `find` byte-aligned | 4 MiB, needle at end | 2.18 ms | 3.28 ms | 2.80 ms (`bytes.find`) | 4 MiB | 4 MiB | 1.0 | memory | **kernel** `find_aligned_bytes` (C memmem-class) | 1.51 |
| 18 | `findall` byte-aligned | 4 MiB | 0.004 ms (sparse, 1 hit at 0) / full-scan cases ≈ `find` | 0.005 ms | — | 4 MiB | 4 MiB | 1.0 | memory | kernel (early-exit dominates in this probe) | 1.2 |
| 19 | `count` | 16 MiB | 2.24 ms | 7.58 ms | 15.3 ms (`np.bitwise_count().sum()`) | 16 MiB | 25 M (SWAR ×12/8 B) | 1.5 | memory | **kernel** `mbs_count` (scalar `u64` loop, not SIMD) | 3.4 (4.2× in `bench`) |
| 20 | `AND` | 16 MiB | 1.67 ms | 7.57 ms | 4.73 ms (`a & b`) | 50.3 MB | 16.8 M | 0.33 | memory | **kernel** SIMD `binary_range` (4 ranges via pool ≥4 MiB) | 4.5 |
| 21 | `OR` | 16 MiB | 2.38 ms | 7.41 ms | 5.08 ms (`a \| b`) | 50.3 MB | 16.8 M | 0.33 | memory | kernel SIMD `binary_range` | 3.1 |
| 22 | `invert` (`~b`) | 16 MiB | 1.18 ms | 5.86 ms | 3.14 ms (`~a`) | 33.6 MB | 16.8 M | 0.50 | memory | kernel SIMD `invert_range` | 5.0 (3.4× in `bench`) |
| 23 | `count` | 64 KiB | 0.020 ms | 0.053 ms | 0.092 ms | 64 KiB | 98k | 1.5 | glue floor | glue (FFI) ≈ kernel | 2.6 |
| 24 | `AND/OR/INV` | 64 KiB | 0.031 / 0.031 / 0.023 ms | 0.017 / 0.019 / 0.018 ms | 0.009 / 0.009 / 0.006 ms | 192 KB / 192 KB / 128 KB | 64 KiB | 0.33–0.50 | glue floor | **glue: `addr()`×3 + `np.empty` + ctypes** (numpy is 3× faster here) | **0.5–0.8 ▲ SLOWER** |
| 25 | `slice` 100 KiB window | 1 MiB buffer | 5.95 ms | 0.018 ms | 0.008 ms (ndarray view+copy) | 204.8 KB (100 KiB r + 100 KiB w) | 102k | 0.5 | compute (kernel) | **Mojo `mbs_copy_bits`: bit-at-a-time; numpy does it in 8 µs** | **0.00 ▲ SLOWER** |
| 26 | `concat` | 1 MiB + 1 MiB | 100 ms | 0.23 ms | 0.15 ms | 4 MiB (zeros + 2 copies) | 1 M | 0.25 | Python + kernel | `_zeroed` + 2× bit-at-a-time `mbs_copy_bits` | **0.00 ▲ SLOWER** |
| 27 | `lshift` / `repeat` / `rol` | 1 MiB | 103 / 150 / 52 ms | 0.17 / 0.30 / 0.10 ms | — | 1–3 MiB | 1–3 M | ~0.3 | Python glue | same structural cause as ranks 3–5 | **0.00 ▲ SLOWER** |
| 28 | `pack` single `bool` | — | 28.8 µs | 5.3 µs | — | ~1 B | 1 | 1.0 | glue | Python `_encode_value` + FFI + concat machinery | **0.18 ▲ SLOWER** |
| 29 | `unpack` single small fmt `uint:12,int:7,bool,bytes:2` | 4 values | 95.6 µs | 25.3 µs | — | ~5 B | ~36 bit-ops | — | glue | Python token loop + 4× slice copies | **0.26 ▲ SLOWER** |
| 30 | `pack` single small fmt | 4 values | 151 µs | 28.2 µs | — | ~5 B | ~36 bit-ops | — | glue | Python token loop + concat per token | **0.19 ▲ SLOWER** |
| 31 | `Bits.uint` (≤64 bits, e.g. 64-bit) | 64 bits | 3.15 µs | 0.83 µs | — | 8 B | ≤64 | — | glue | `addr()` + ctypes `mbs_read_u64` (bit-at-a-time inside, but only ≤64 iterations) | **0.26 ▲ SLOWER** |
| 32 | `Bits.uint` (8192 bits, `int.from_bytes` path) | 8 Ki bits | 2.5 µs | 2.5 µs | — | 1 KiB | big-int shift | — | Python/C | numpy path, no Mojo involved | 1.0 |
| 33 | `Bits.bin` | 1 KiB (8192 bits) | 0.846 ms | 0.025 ms | — | 1 KiB | 8192 | 8.0 | **Python** | **Python `"".join("1" if x else "0" for x in unpacked)` — 8192 iterations** | **0.03 ▲ SLOWER** |
| 34 | `Bits.hex` | 1 KiB | — (via `uint`, big-int) | — | — | 1 KiB | hex format | — | Python/C | `f"{self.uint:…x}"` on a big-int | — |
| 35 | `Bits(bytes)` ctor | 1 KiB / 16 MiB | 4.1 µs / 4.75 ms | 2.4 µs / 4.72 ms | — | 1 KiB / 16 MiB | memcpy | 0 | memory | Python: `np.frombuffer(...).copy()` — no Mojo | 0.6–1.0 |
| 36 | `tobytes` | 16 MiB | 1.25 ms | 1.39 ms | 13.4 GB/s | 16 MiB | 0 | 0 | memory | Python `ndarray.tobytes()` | 1.1 |
| 37 | `copy` | 16 MiB | ~0.0 ms (returns view) / 1.20 ms with real copy in first probe | 0.000 ms | — | 16 MiB | 0 | 0 | memory | `_data.copy()` (numpy) | 0.00 in first probe* |
| 38 | `floatbe` 32-bit | 32 bits | 0.60 µs | 1.08 µs | — | 4 B | 1 | — | Python/C | `struct.unpack` on `value.bytes` | 1.8 |
| 39 | `set(all)` / `invert()` in place | 1 MiB | 0.238 / 0.234 ms | 0.295 / 0.317 ms | — | 1 MiB | 1 M | 1.0 | memory | kernel SIMD `mbs_fill` / `mbs_invert` | 1.2–1.4 |
| 40 | `count(1)` tiny floor | 8 bytes | 2.84 µs | 0.27 µs | — | 8 B | 12 | — | glue | `addr()` (2.30 µs) + ctypes (0.87 µs) — glue is ~2/3 of call | **0.10 ▲ SLOWER** |
| 41 | `AND` tiny floor | 8 bytes | 8.21 µs | 0.20 µs | — | 24 B | 8 | 0.33 | glue | `np.empty` + 3× `addr()` + ctypes | **0.02 ▲ SLOWER** |
| 42 | `Array.reverse` | 100k values | 51.4 ms | 302 ms | — | 750 KB ×(2 round-trips) | 1.2 M | — | Python round-trip | `tolist()` + Python `.reverse()` + full re-`__init__` repack | 5.9 |
| 43 | `Array.pop` | 100k values | 51.3 ms | 0.009 ms | — | 750 KB ×(2 round-trips) | 1.2 M | — | **Python** | `tolist()` + list pop + **full re-pack of 99,999 values** (upstream is in-place) | **0.00 ▲ SLOWER** |
| 44 | `__eq__` | 16 MiB | 6.73 ms | 0.55 ms | — | 32 MiB | 16 M | 0.5 | memory + glue | **`np.array_equal` on the ndarrays — no Mojo** (this is upstream-speed, not a Mojo regression) | **0.08 ▲ SLOWER** |
| 45 | `__getitem__` single bit | 1 bit | 0.46 µs | 0.71 µs | — | 1 B | 1 | — | Python | `self._data[idx>>3] & mask` (numpy scalar) | 1.6 |

\* Row 37: the first probe's `mb.copy` measured ~0 because `Bits.copy()` returns `self.__class__._from_data(self._data, …)`-style view in one path and a real copy in another; the 1.20 ms figure is the genuine `ndarray.copy()`. Either way it is not a Mojo kernel — both implementations are numpy-bound.

### Absolutes at a glance (largest sizes, for the "where does time go" question)

| entry point | Mojo ms (largest) | share of its own time in Python/ctypes glue |
|---|---:|---|
| `b[::2]` 16 MiB | 36230 | ~100% (generator + `np.fromiter` + `np.packbits`) |
| `b * 3` 16 MiB | 2540 | ~99% (loop of FFI calls, each bit-at-a-time inside) |
| `b + b` 16 MiB | 1689 | ~99% (`_zeroed` + 2× copy) |
| `b << 64` 16 MiB | 1675 | 100% (no kernel — pure Python composition) |
| `Array` pack 500k | 238–332 | ~95% (Python encode loop; the single bulk FFI is milliseconds) |
| `find` unaligned 4 MiB | 313 | 0% glue — 100% kernel (`equal_at`) |
| `pack` ×1000 | 45.9 | ~99% (1000 concats) |
| `byteswap` 1 MiB | 653 | ~100% (Python slice-assign loop) |
| `reverse` 4 MiB | 121 | ~0% glue — 100% kernel (per-bit swaps) |
| `find` aligned 4 MiB | 2.18 | 0% glue — 100% kernel |
| `count` 16 MiB | 2.24 | ~0% glue — 100% kernel |
| `AND/OR/invert` 16 MiB | 1.67 / 2.38 / 1.18 | ~0% glue — 100% kernel (SIMD) |
| small `pack`/`unpack` (4 values) | 0.15 / 0.10 | ~100% glue (format parsing + per-token FFI) |
| tiny calls (8 B) | 2.8–8.2 µs | ~100% glue (`addr()`×N dominates) |

## 3. Structural flags (per the brief)

### 3.1 Python-level loops that re-enter ctypes per element

These are the single biggest structural weakness of the port. The kernel side is batched (`mbs_read/write_many_u64` exist and are used by `Array`), but the *format* path was not.

| site (`core.py`) | loop | re-entry | measured cost |
|---|---|---|---|
| `pack()` → `result += _encode_value(...)` (line 1282) | one `__add__` per token | `_zeroed` + 2× `mbs_copy_bits` per token | `pack ×1000`: 45.9 ms vs 5.7 ms upstream; single-token `pack bool`: 28.8 µs vs 5.3 µs |
| `_unpack_from` → `_decode_token` (line 1262) + `Bits(source[a:b])` for int tokens (line 1245-ish) | one slice copy + one `mbs_read_u64` per token | `unpack ×1000`: 20.7 ms vs 6.7 ms; small fmt: 95.6 µs vs 25.3 µs |
| `__mul__` (line 561) `for i in range(count): mbs_copy_bits(...)` | one FFI call per repetition | `b*3` 16 MiB: 2540 ms |
| `Array` fallback (non-uint/int, lines 1367–1371) `for value in values: self.dtype.pack(value); self.data.overwrite(piece, position)` | one `pack` + one `overwrite` (which is 3 slices + 2 concats) per value | only hit for non-integer dtypes (e.g. `float:32` verified to construct), but any such array is O(n) concats |
| `__getitem__` step≠1 (line 518) `np.fromiter((self[i] for i in indices), …)` | one `__getitem__` (numpy scalar) per selected bit | `b[::2]` 16 MiB: 36.2 s — the slowest entry point in the entire port |
| `__delitem__` step≠1 (line 880) `Bits([self[i] for i in range(self._len) if i not in remove])` | same per-bit path + `Bits(iterable)` string round-trip | worst-case O(n) Python iterations |
| `all`/`any` (lines 327–335) `all(self[i] == target for i in positions)` | one `__getitem__` per bit, Python `all`/`any` driver | not measured separately; structurally identical to rank 1 |
| `set`/`invert` with `pos` list (lines 776–796) | one numpy-scalar RMW per position | Python-bound whenever `pos` is a list |
| `Array.extend` (line 1403) `for value in values: self.append(value)`; `Array.append` (1400) = `self.data.append(pack)` = slice+concat | one concat per append | append-heavy workloads are quadratic |
| `Byteswap` (lines 849–855) `for _ in range(repetitions): for size in sizes: raw[..] = raw[..][::-1]` | Python slice-reversal per group | 1 MiB: 653 ms |

For contrast, the batched paths that *do* exist and are fast: `Array` uint/int ≤64 (`mbs_write_many_u64` / `mbs_read_many_u64`, one FFI call for 500k values) and the SIMD `binary_range`/`invert_range`/`fill`. The format path simply never got the same treatment.

Inside the kernels, the same anti-pattern exists in Mojo: `mbs_copy_bits` is a **bit-at-a-time** loop (`for i in range(count): put_bit(dst,…,get_bit(src,…))`), `read_u64`/`write_u64` are per-bit loops, `equal_at` is a per-bit loop, and `mbs_reverse` is a per-bit swap loop. Every Python loop above that calls `mbs_copy_bits` therefore pays *both* a ctypes crossing *and* a bit-at-a-time kernel.

### 3.2 Per-call allocations and copies

| site | allocation/copy per call | consequence (measured) |
|---|---|---|
| `_array()` (line 63) `np.frombuffer(bytes(data)).copy()` | full input copy on every `Bits(bytes)` construction | `Bits(bytes) 16 MiB`: 4.75 ms (numpy memcpy rate, ~3.5 GB/s) — fine at large sizes, but it is a copy where a view would do |
| `_zeroed()` (line 69) `np.zeros` | zero-filled output buffer on every slice/concat/repeat/`Bits(n)` | e.g. `__add__` 16 MiB pair allocates a 32 MiB zero buffer *then* overwrites it twice; `np.empty` was used for `_binary` but not for concat/slice/repeat |
| `__invert__` / `_binary` `np.empty` + `_mask_padding` | correctly avoids zero-fill; good | — |
| `_uint_piece()` `np.zeros(length)` + 1 FFI call | 1 alloc + 1 ctypes per scalar value | single `Bits(uint=…, length=64)`: 6.7 µs vs 4.0 µs upstream |
| `Bits.__init__` bytes path (line 146–154) `result = source[first:first+nbits]` then `result._data.copy()` | **double copy** of the payload whenever `offset`/`length` is passed | construction with a window copies twice |
| `Bits.bytes` / `tobytes()` (lines 234–240) `_data.tobytes()` | full copy per call (API-required) | 16 MiB: 1.25 ms = 13.4 GB/s — numpy memcpy, not a kernel |
| `count` (line 319) `addr(self._data, np.uint8)` | `addr()` = dtype/contiguity/null checks + `ctypes.data` | 2.30 µs per `addr()`; `_binary` calls it 3× (6.9 µs) before any kernel runs — this is why 64 KiB `AND` (0.031 ms) loses to numpy (0.009 ms) |
| `Array.__init__` (line 1357) `np.asarray(encoded_values, dtype=np.uint64)` | full 4 MB `uint64` staging buffer + Python `list` of 500k ints | measured as part of the 238 ms `Array` pack — the Python list-comp *is* the hotspot (see §3.1), the staging buffer is minor |
| `Array.tolist()` (line 1381) `np.empty(count, dtype=np.uint64)` + dict… | 4 MB staging + Python `[int(x) for x in values]` | 65 ms parse at 500k — bulk FFI is fast, the list-comp is the rest |
| `Array.pop/insert/reverse/__setitem__/__getitem__` (lines 1407–1438) | `self.tolist()` (full decode) + `self.__init__(dtype, values, …)` (full re-encode) | `Array.pop` on 100k values: **51.3 ms vs 0.009 ms upstream** (upstream is an in-place slice delete) |
| `insert/overwrite/delete/replace/rol/ror/__setitem__` on `BitArray` | `self._assign(self[:a] + X + self[b:])` — 2–3 slice copies + 2 concats, discarding the old buffer | this is why `rol 8` on 4 MiB costs 838 ms and `overwrite`/`insert` inherit the full-copy cost |
| `__hash__` (line 671) `hash((self._len, self._data.tobytes()))` | full copy + hash of payload per hash | not microbenchmarked; structurally O(n) with a temporary |
| `__eq__` (line 668) `np.array_equal(self._data, right._data)` | no alloc, but also no Mojo — pure numpy | 16 MiB: 6.73 ms vs 0.55 ms upstream (numpy is single-threaded element-wise here) |

No per-call allocation was observed inside the Mojo kernels themselves: every kernel writes into caller-provided storage (`src/bitstring.mojo` never allocates across the FFI boundary; buffers are numpy arrays owned by Python). That part is clean.

## 4. Per-hotspot verdicts: next phase (unroll / simd / parallel / gpu / none)

Verdicts reference the measured `flops-per-byte` (`F/B`). Per `MOJO_NOTES.md`, a CPU-only port is legitimate below ~2 flops/byte *unless* the bottleneck is Python glue, in which case the verdict is about the glue, not the kernel. GPU is only recommended where F/B is high enough that PCIe transfer (≈10–25 GB/s host↔device) can be amortised — none of the kernels here clear that bar except the two bit-at-a-time ones, which are fixable on CPU first.

| # | hotspot | F/B | next phase | why, on the evidence |
|---|---|---|---|---|
| 1 | `mbs_copy_bits` (bit-at-a-time; underlies slice/concat/repeat/shift/rol/overwrite/insert/delete) | 1.0 (copy) | **simd** | This one kernel is the root of ranks 1–5, 9, 15, 25–27 (and 36 s `b[::2]` indirectly via slices). A byte-oriented overlap copy (aligned fast path + scalar edge, the shape `binary_range` already proves out at 20–30 GB/s) takes slice from 5.95 ms/100 KiB to numpy's 8 µs — a ~700× measured headroom. Parallelism will not fix a bit loop; GPU F/B = 1.0 makes transfer dominate. |
| 2 | `mbs_reverse` (per-bit swaps) | 8.0 | **simd** | 121 ms at 4 MiB vs 5.7 ms upstream — upstream's byte-level reversal is 21× faster *without* any vectorisation. A 32-byte-block reverse (the `VECTOR_BYTES` shape) is the fix. GPU would also work at F/B = 8, but the CPU fix is smaller and closes a 21× gap first; GPU only if a later phase finds CPU SIMD saturated. |
| 3 | `mbs_find` unaligned (`equal_at` per position) | 8.0 | **simd** (then parallel) | 313 ms for a 4 MiB scan that `bytes.find` does in 1.6–2.8 ms. Vectorise the match test (shift-and-compare over unaligned windows) before any threading; threading a bit loop just spreads it. F/B = 8 means GPU is not ruled out *by arithmetic*, but the CPU SIMD fix removes a 144× gap and must come first. |
| 4 | `mbs_count` (scalar `u64` popcount) | 1.5 | **simd** | 7.5 GB/s at 16 MiB vs 20–30 GB/s for the SIMD kernels in the same file. Widen the popcount loop to the `binary_range` vector shape. Currently *faster* than upstream (3.4–4.2×) and faster than numpy (3.4×), so this is a hardening step, not a regression fix. GPU: F/B = 1.5 < 2 → **none** (per `MOJO_NOTES.md` rule), transfer would dominate. |
| 5 | `pack`/`unpack` format path (Python token loop + per-token FFI + concat) | ~1.0 | **none** (Python restructuring, not a kernel phase) | 8× slower than upstream at ×1000 and 5× slower at a single token. The fix is a bulk encode/decode kernel call for the whole format (the `Array` path already demonstrates the shape with `mbs_read/write_many_u64`), plus preallocation instead of `result +=` per token. Until then, SIMD/GPU/parallel phases do not apply — the time is in Python string/format handling and 1000 ctypes crossings. `unroll`/`simd`/`parallel`/`gpu` labels don't fit; flag as **none** with the note that the "kernel" to write is a new batched one. |
| 6 | `Array` uint/int pack/parse | 1.0–4.0 | **none** | Already 10–40× faster than upstream. The remaining 238 ms is the Python validation list-comp, not the kernel. If that loop were vectorised (numpy) the whole thing would drop, but that is glue work, not a Mojo phase. Large `uint:64` parse (F/B = 4) is the only row where a GPU verdict is arithmetically arguable — 8 MB touched, ~100 ms, of which most is Python; GPU transfer of 8 MB at ~20 GB/s is 0.4 ms, but the bottleneck is the Python list-comp, so GPU still does not apply. |
| 7 | `mbs_read/write_u64` + `mbs_read/write_many_u64` (bit loops) | ~12 per value → ~1.5/byte | **unroll** (then simd for the `many` variants) | The `Array` kernels are fast despite the bit loops because the widths are small (≤64). Unrolling the common widths (8/16/32/64) removes the per-bit masks; SIMD for `read_many`/`write_many` at stride = width is possible but the measured headroom is small (parse is already 17–40× upstream). Unroll is the cheapest win. |
| 8 | `_binary`/`invert` small-size glue (`addr()`×N + `np.empty`) | 0.33 / 0.50 | **none** | At 64 KiB the port is *slower* than upstream (0.5–0.8×) purely because of 2.3 µs `addr()` calls and buffer allocation. That is call-path overhead, not kernel throughput. GPU at F/B = 0.33–0.50 is definitively ruled out (launch + transfer would be 100× the kernel time). Fix is fewer Python-side checks / cached addresses, not a compute phase. |
| 9 | `Bits.bin` (Python `"".join` loop) | 8.0 | **none** (or numpy) | 34× slower than upstream (0.846 ms vs 0.025 ms at 1 KiB) and the time is a Python generator over `np.unpackbits`. `np.unpackbits` already produces the bits; the join is the cost. A numpy/tobytes-based formatter removes it without any Mojo phase. |
| 10 | `BitArray` slice-assignment family (`insert`/`overwrite`/`delete`/`__setitem__`) | 1.0 | **none** (Python) after #1 | Each costs 2–3 full-buffer copies by construction (`self[:a] + X + self[b:]`). Once `mbs_copy_bits` is a byte-copy (verdict 1), these drop from O(n) Python to O(n) memcpy; the remaining fix is an in-place memmove path, which is also Python-side. No SIMD/GPU phase of its own. |
| 11 | `Array.pop` / `__getitem__` / `__setitem__` / `reverse` (full `tolist`+repack round-trip) | — | **none** (Python/algorithmic) | `Array.pop` is 5700× slower than upstream because it decodes and re-encodes the whole array to remove one element. This is an algorithmic choice in Python, fixable with a byte-range delete on the packed buffer. No kernel phase applies. |
| 12 | `__eq__` (numpy `array_equal`) | 0.5 | **parallel** (or **none**) | 6.7 ms at 16 MiB vs 0.55 ms upstream, and both are numpy — the port inherits numpy's single-threaded scan. The 4-task pool already in `core.py` (or a Mojo `parallelize` over ranges) over 32 MiB touched is the obvious fix. F/B = 0.5 → GPU ruled out. If the phase list must pick one: **parallel**. |
| 13 | `_binary`/`invert` at ≥ 4 MiB (4-task Python pool) | 0.33 / 0.50 | **parallel** (already partially done) | The kernel at 20–30 GB/s is already bandwidth-bound; the Python pool of 4 is the only parallelism. More workers / Mojo `parallelize` inside the kernel would help only until memory bandwidth saturates (already ~30 GB/s at 16 MiB). F/B = 0.33–0.50: **GPU ruled out** — PCIe transfer alone (50 MB at ~20 GB/s = 2.5 ms) exceeds the current 1.67 ms kernel time. |
| 14 | `Bits` construction / `tobytes` / `copy` / `getitem(int)` / `floatbe` | 0–1.0 | **none** | All numpy/Python and at or ahead of upstream (0.6–1.8×). There is no Mojo kernel to speed up; `none` is the correct verdict. |
| 15 | `find` byte-aligned (the only search row that is kernel-fast) | 1.0 | **none** | 1.5× faster than upstream, 1.3× faster than `bytes.find`, 1.9 GB/s scan. F/B = 1.0 < 2 → GPU would not pay for itself; no CPU phase needed until the unaligned path (verdict 3) is fixed. `findall` inherits this. |

### The two questions the next phases will ask

1. **"Should anything go on the GPU?"** No — not in the next phase. Every kernel here is at F/B ≤ 8, and the two at F/B = 8 (`reverse`, unaligned `find`) are bit-at-a-time loops that are 21–144× behind already-available CPU implementations. The GPU verdict for each is: *would need F/B well above 2 to amortise transfer, but the CPU SIMD fix closes the gap first*. The genuinely memory-bound kernels (`AND`/`OR`/`invert`/`count`, F/B = 0.33–1.5) are GPU-negative by arithmetic: at 16 MiB the kernel already runs in 1.2–2.4 ms while a PCIe round-trip of 32–50 MB costs ≈2–3 ms before any compute.
2. **"Where is the biggest win per hour?"** `mbs_copy_bits` (verdict 1) — it is one kernel, and it underlies six of the top eight hotspots by absolute time. Second is the `pack`/`unpack` Python loop (verdict 5), which is the only place the port is slower than upstream on the *small-input* path that real callers hit most often.

## 5. Micro-measurements (glue floor, this session)

| probe | result |
|---|---|
| raw ctypes `mbs_count` on 8 B | **0.87 µs/call** (kernel + ctypes only) |
| `addr()` validation | **2.30 µs/call** |
| `count(1)` on 8 B (2× `addr` + `lib()` + ctypes) | 2.84 µs |
| `mb & mb` on 8 B | 8.21 µs (adds `np.empty` + 3rd `addr`) |
| `Bits.uint` on 64 bits | 3.15 µs (FFI + 64-iteration bit loop inside) |
| `getitem` single bit | 0.46 µs (numpy scalar, no FFI) |
| `list(bits)` on 80k bits | 41.2 ms (~0.5 µs/bit, Python `__iter__` → `__getitem__`) |

Interpretation: below ~512 KiB, every entry point is dominated by Python + ctypes + allocation overhead (2–9 µs floors), not by the Mojo kernel. That is exactly where the port loses to upstream (rank 24, 28–31, 40–41) and where numpy wins (rank 24: numpy `a & b` on 64 KiB in 9 µs vs Mojo 31 µs). Small-input callers will feel this before any SIMD work matters.

## 6. Rows where the port is slower than upstream (kept, per the brief)

- **Bulk ops at large sizes:** `b[::2]` (0.01×), `b + b` (0.02×), `b * 3` (0.02×), `b << 64` (0.00×), `rol` (0.00×), `reverse` (0.04–0.05×), 100 KiB slice via `mbs_copy_bits` (0.00×), `Array.pop` (0.00×), `Bits.bin` (0.03×).
- **Format path:** `pack` ×1000 (0.12×), `unpack` ×1000 (0.32×), small `pack` (0.19×), small `unpack` (0.26×), `pack "bool"` single (0.18×).
- **Tiny/64 KiB glue floor:** `AND`/`OR`/`INV` at 64 KiB (0.5–0.8×), `count(1)` on 8 B (0.10×), `AND` on 8 B (0.02×), `Bits.uint` 64-bit (0.26×), `Bits(uint=…)` (0.60×).
- Not counted as "slower" (parity, not regression): `__eq__` (0.08×) is numpy-vs-numpy, not a Mojo kernel; `Bits(bytes)` 1 KiB (0.6×) is `np.frombuffer().copy()` on both sides.

## 7. Caveats

- `bench/bench.py`'s own six rows ( §1 ) show the port *faster* than upstream on every one; the slower-than-upstream rows above are all in entry points that `bench.py` does not cover (slice/concat/repeat/shift/rotate/reverse/format-pack). Both statements are true; they describe different surfaces.
- `findall` with the needle at offset 0 measures 4 µs because it early-exits; a full-scan `findall` would track `find` (~2 ms at 4 MiB). The row is labelled as such.
- `copy` and the `floatbe`/`uint`-over-64-bit rows exercise pure numpy/Python paths (no Mojo kernel is involved) and are included only to make the "glue vs kernel" split explicit; they are not Mojo regress
...[truncated 615 chars]