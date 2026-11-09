# VERIFY phase — independent re-measurement

> Assumption: the README overstates until reproduced. No number in `README.md`
> was kept on faith: every figure below was measured in this session.
> Only `README.md` (one benchmark row) and this file changed; no source or test
> code was edited and no failing test was found to fix.

## Environment (this session)

- Host: `Intel(R) Xeon(R) CPU E5-2697 v4 @ 2.30GHz`, Linux
  `6.8.0-147-generic`, Python `3.13.14`,
  Mojo `1.2.0.dev2026092605 (236c32cb)`, upstream `bitstring 4.4.0`.
- Date: 2026-11-09.
- `pixi run build && pixi run test` — **135 passed in 22.70s**, exit 0
  (first run of the session; also green after all edits — see §8).
- `pixi run bench` (flock-wrapped, solo, sequential) was run five times
  end-to-end (R1, R2, R4, R5, R7), plus `pixi run python bench/bench.py`
  once (R3, identical code path without the flock), plus one independent
  per-row rerun script (R6, best-of-7, same seed 2026 inputs).

## 1. Reproduced — benchmark runs (raw output)

### R1 — `pixi run bench` (first)

```
Machine: Intel(R) Xeon(R) CPU E5-2697 v4 @ 2.30GHz
Linux 6.8.0-147-generic, Python 3.13.14, Mojo 1.2.0.dev2026092605 (236c32cb), upstream bitstring 4.4.0
Best of 5 runs; inputs are preconstructed unless the operation says pack.

| operation | mojo-bitstring | upstream bitstring | upstream / Mojo |
|---|---:|---:|---:|
| count set bits, 16 MiB | 1.901 ms | 8.345 ms | 4.39x |
| bitwise AND, 16 MiB | 2.826 ms | 7.792 ms | 2.76x |
| invert, 16 MiB | 1.524 ms | 6.150 ms | 4.03x |
| find 64-bit value, 4 MiB byte-aligned | 2.114 ms | 3.441 ms | 1.63x |
| pack Array uint12, 500k values | 249.917 ms | 3161.415 ms | 12.65x |
| parse Array uint12, 500k values | 66.499 ms | 2219.508 ms | 33.38x |
```

### R2 — `pixi run bench` (second)

```
| count set bits, 16 MiB | 2.041 ms | 7.948 ms | 3.89x |
| bitwise AND, 16 MiB | 2.506 ms | 6.983 ms | 2.79x |
| invert, 16 MiB | 1.540 ms | 5.905 ms | 3.83x |
| find 64-bit value, 4 MiB byte-aligned | 2.296 ms | 3.423 ms | 1.49x |
| pack Array uint12, 500k values | 251.751 ms | 3343.155 ms | 13.28x |
| parse Array uint12, 500k values | 70.171 ms | 2209.215 ms | 31.48x |
```

### R3 — `pixi run python bench/bench.py`

```
| count set bits, 16 MiB | 2.597 ms | 8.192 ms | 3.15x |
| bitwise AND, 16 MiB | 2.092 ms | 8.035 ms | 3.84x |
| invert, 16 MiB | 1.277 ms | 6.448 ms | 5.05x |
| find 64-bit value, 4 MiB byte-aligned | 2.576 ms | 3.915 ms | 1.52x |
| pack Array uint12, 500k values | 237.185 ms | 2974.449 ms | 12.54x |
| parse Array uint12, 500k values | 65.338 ms | 2144.034 ms | 32.81x |
```

### R4 — `pixi run bench` (third)

```
| count set bits, 16 MiB | 2.429 ms | 7.642 ms | 3.15x |
| bitwise AND, 16 MiB | 2.931 ms | 8.225 ms | 2.81x |
| invert, 16 MiB | 1.649 ms | 6.479 ms | 3.93x |
| find 64-bit value, 4 MiB byte-aligned | 2.383 ms | 3.449 ms | 1.45x |
| pack Array uint12, 500k values | 250.026 ms | 3371.254 ms | 13.48x |
| parse Array uint12, 500k values | 67.244 ms | 2257.020 ms | 33.56x |
```

### R5 — `pixi run bench` (fourth)

```
| count set bits, 16 MiB | 1.912 ms | 8.280 ms | 4.33x |
| bitwise AND, 16 MiB | 2.114 ms | 7.683 ms | 3.63x |
| invert, 16 MiB | 1.266 ms | 5.623 ms | 4.44x |
| find 64-bit value, 4 MiB byte-aligned | 2.109 ms | 3.240 ms | 1.54x |
| pack Array uint12, 500k values | 249.673 ms | 3339.285 ms | 13.37x |
| parse Array uint12, 500k values | 68.815 ms | 2284.067 ms | 33.19x |
```

### R6 — per-row rerun (independent script, best-of-7, seed 2026)

```
ALL OUTPUT PARITY ASSERTS PASSED
count set bits, 16 MiB: mojo best=1.886ms | upstream best=8.125ms | ratio=4.31x
bitwise AND, 16 MiB: mojo best=2.708ms | upstream best=7.322ms | ratio=2.70x
invert, 16 MiB: mojo best=1.530ms | upstream best=5.976ms | ratio=3.91x
find 64-bit value, 4 MiB byte-aligned: mojo best=2.220ms | upstream best=3.424ms | ratio=1.54x
pack Array uint12, 500k values: mojo best=251.185ms | upstream best=3378.287ms | ratio=13.45x
parse Array uint12, 500k values: mojo best=67.398ms | upstream best=2343.106ms | ratio=34.77x
```

Per-iteration distributions (ms, sorted):

```
count:     mojo [1.886, 1.963, 1.976, 1.999, 2.017, 2.129, 3.251] upstream [8.125, 8.182, 8.202, 8.204, 8.413, 8.504, 8.724]
AND:       mojo [2.708, 2.725, 2.75, 2.918, 3.046, 4.586, 5.461] upstream [7.322, 7.558, 7.998, 8.121, 8.284, 19.23, 19.974]
invert:    mojo [1.53, 1.657, 1.66, 1.681, 1.751, 1.934, 2.129] upstream [5.976, 6.107, 6.185, 6.334, 6.386, 19.388, 30.811]
find:      mojo [2.22, 2.233, 2.27, 2.326, 2.354, 2.391, 2.566] upstream [3.424, 3.44, 3.441, 3.506, 3.523, 3.679, 9.267]
pack 500k: mojo [251.185, 253.033, 254.08, 260.788, 264.247, 268.026, 272.451] upstream [3378.287, 3404.803, 3447.146, 3487.805, 3520.143, 3522.249, 3603.247]
parse 500k:mojo [67.398, 69.465, 71.616, 71.76, 71.96, 73.3, 75.201] upstream [2343.106, 2363.519, 2381.739, 2384.35, 2388.937, 2398.948, 2430.337]
```

### R7 — `pixi run bench` (final, after README edit)

```
Machine: Intel(R) Xeon(R) CPU E5-2697 v4 @ 2.30GHz
Linux 6.8.0-147-generic, Python 3.13.14, Mojo 1.2.0.dev2026092605 (236c32cb), upstream bitstring 4.4.0
Best of 5 runs; inputs are preconstructed unless the operation says pack.

| operation | mojo-bitstring | upstream bitstring | upstream / Mojo |
|---|---:|---:|---:|
| count set bits, 16 MiB | 2.483 ms | 8.536 ms | 3.44x |
| bitwise AND, 16 MiB | 2.403 ms | 7.578 ms | 3.15x |
| invert, 16 MiB | 1.371 ms | 6.032 ms | 4.40x |
| find 64-bit value, 4 MiB byte-aligned | 2.185 ms | 3.600 ms | 1.65x |
| pack Array uint12, 500k values | 252.292 ms | 3347.820 ms | 13.27x |
| parse Array uint12, 500k values | 69.226 ms | 2279.433 ms | 32.93x |
```

## 2. Reproduction check — each README row vs. measured

README baseline (pre-verify):

| operation | mojo-bitstring | upstream bitstring | upstream / Mojo |
|---|---:|---:|---:|
| count set bits, 16 MiB | 1.978 ms | 7.697 ms | 3.89x |
| bitwise AND, 16 MiB | 2.120 ms | 8.089 ms | 3.82x |
| invert, 16 MiB | 1.564 ms | 5.992 ms | 3.83x |
| find 64-bit value, 4 MiB byte-aligned | 2.306 ms | 3.281 ms | 1.42x |
| pack Array uint12, 500k values | 249.844 ms | 3230.849 ms | 12.93x |
| parse Array uint12, 500k values | 67.955 ms | 2173.370 ms | 31.98x |

Median of the seven measured runs (R1–R7) vs. README:

| operation | median mojo (Δ) | median upstream (Δ) | median ratio (Δ) | verdict |
|---|---:|---:|---:|---|
| count set bits, 16 MiB | 2.041 ms (+3%) | 8.192 ms (+6%) | 3.89x (+0%) | **reproduced** |
| bitwise AND, 16 MiB | 2.506 ms (+18%) | 7.683 ms (−5%) | 2.81x (−26%) | **corrected** (see below) |
| invert, 16 MiB | 1.524 ms (−3%) | 6.032 ms (+1%) | 4.03x (+5%) | **reproduced** |
| find 64-bit value, 4 MiB byte-aligned | 2.220 ms (−4%) | 3.441 ms (+5%) | 1.54x (+8%) | **reproduced** |
| pack Array uint12, 500k values | 250.026 ms (+0%) | 3343.155 ms (+3%) | 13.28x (+3%) | **reproduced** |
| parse Array uint12, 500k values | 67.398 ms (−1%) | 2257.020 ms (+4%) | 33.19x (+4%) | **reproduced** |

Five of six rows reproduce within 20% on both sides and on the ratio.
The **bitwise AND** row does not: the median Mojo time is 2.506 ms
(+18%, inside 20% on its own) but the median ratio is 2.81x, 26% below
the README's 3.82x, because upstream measured slightly faster than the
old snapshot while Mojo measured slower. Every measured AND ratio is
2.70x–3.84x; only R3 (2.092 ms / 8.035 ms) matched the old line.

**What changed:** per the rule "a figure that does not reproduce
within 20% gets corrected in the README to the number you measured",
the AND row in `README.md` now reads **2.506 ms | 7.683 ms | 2.81x**,
the median of the seven measured runs in this session (all on the
same host and inputs as `bench/bench.py`). No other number, ratio, or
row was changed. The final run R7 (2.403 ms | 7.578 ms | 3.15x) is
within 5% of that corrected line on the Mojo side and within 2% on
the upstream side, so the corrected row reproduces in the final run
too. The row still shows the port faster than upstream; nothing was
reworded to make it look better.

Two other rows crossed 20% in *individual* runs but not in the median
(count Mojo 2.597 ms in R3, +31%; invert Mojo 1.266 ms in R5, −19%;
etc.). That is normal best-of-5 variance on a shared host for the
small rows; the median across runs is the reproducible figure.

## 3. Benchmark audit — same input, no skipped work

Review of `bench/bench.py` and the kernels it calls:

- **Same input for both sides.** All six rows use one
  `np.random.default_rng(2026)` stream: the same 16 MiB
  `left_raw`/`right_raw` bytes build both `mojo.Bits` and
  `upstream.Bits`; the same 4 MiB `search_raw` with the same 8-byte
  needle (`de ad be ef ca fe ba be`) at the tail; the same 500k-value
  `values` array builds both `Array("uint:12", …)` objects.
  Preconstructed inputs (except *pack*, which constructs by definition)
  stay preconstructed on both sides. The per-row rerun (R6)
  additionally asserted byte-identity (`mojo_left.tobytes() ==
  ref_left.tobytes() == left_raw`, same for right/search) and
  value-identity of the Array before timing.
- **No skipped work on either side.** `bench.py` asserts output
  equality before timing (`count`, `&`, `~`, `find`, `tolist`), and
  R6 re-asserted them. Each lambda performs the genuine operation:
  `count(1)` → `mbs_count`; `&`/`~` → full-buffer `mbs_binary` /
  `mbs_invert` over all 16 MiB (the ≥ 4 MiB parallel split goes
  through the same `mbs_binary_range` / `mbs_invert_range` kernels
  over `_parallel_ranges`, not a shortcut); `find(..., bytealigned=True)`
  with a byte-multiple pattern takes the real `mbs_find` /
  `find_aligned_bytes` path in Mojo (`python/bitstring/core.py`
  `find` → `lib().mbs_find`, `src/bitstring.mojo`
  `find_aligned_bytes`), not a Python `bytes.find`; *pack* goes
  through `mbs_write_many_u64` and *parse* through
  `mbs_read_many_u64` over all 500k values. No row replaces the kernel
  with a precomputed result, cached answer, or smaller input.
- **Ratio ≥ 1 on all six rows, in every run.** The port is faster
  than upstream on all six README rows in all seven measurements
  (R1–R7). There was therefore no slower row to keep *in this table*.
  The slower-than-upstream entry points found by the ANALYZE phase
  (slicing step≠1, concat, repeat, shift, rotate, reverse, small-input
  glue, etc.) are **not** in this benchmark table and were not added
  or reworded here; they remain documented in `bench/analysis.md` §6
  and were left untouched.
- **Best-of-N, not fabricated.** `bench.py` uses `best_time` with
  `time.perf_counter()`, best of 5. R6's independent best-of-7 script
  reproduced the same ordering and magnitudes, so the table's "best of
  five" claim is accurate.

## 4. Test-parity audit — `git log -p -- tests/`

- `git log --oneline --all -- tests/` shows three commits: the initial
  import (`a7ed0be`), the accel pass (`97c5f7a`), and the test phase
  (`fdef703`). `bench/bench.py` has never changed since the import.
- **Removed assertions:** the only `-assert` line in the entire history
  is the accel-phase rewrite in `test_bitwise_parallel_threshold_parity`,
  which replaced a single `(left & right)` assertion with
  `(left & right)` **plus** `(~left)` — i.e. it added an assertion, it
  did not remove or weaken one. No `pytest.approx`, no tolerance, and
  no `raises` was deleted or loosened.
- **Loosened tolerances:** none found. The only tolerances in the
  current suite are the `math.isclose(..., rel_tol=tol)` checks in
  `test_float_tolerance_parity` / `test_float_nan_inf_tolerance_parity` /
  `test_pack_float_tolerance_parity` / `test_array_float_tolerance_parity`,
  which assert byte-exact packed bits (`assert actual_bits ==
  expected_bits`) and only use a tolerance when comparing the decoded
  float value — and all four tests were *added* by the test phase, so
  there was no stricter prior assertion to loosen.
- **Nothing restored:** there were no removed/loosened assertions to
  restore. No test file was modified in this phase.

## 5. What you could not reproduce / notes

- **Exact absolutes vary run-to-run** (see §1–§2). The README table
  already says so ("timings on a shared machine vary … reproducible
  snapshot"). Individual best-of-5 runs can drift ~±25–30% on the
  small rows (notably bitwise AND, which is also the most sensitive
  to thread-pool warmup: R6's AND iterations were
  [2.708 … 5.461] ms while count/invert were tight). The median
  across runs is what reproduces. No single run in this session
  matched the README to three decimals, and that is expected — it is
  not a failure.
- **The bitwise AND README figure (2.120 ms | 8.089 ms | 3.82x) did
  not reproduce within 20%** (median ratio 2.81x, −26%) and was
  corrected to the measured median (see §2). All other figures
  reproduced within 20% on both sides and the ratio, so they stand.
- **Slower rows are not in this table.** The README benchmark table's
  six rows are all faster than upstream. That is true of those six
  kernels on these inputs; it is not a claim about the whole API.
  The port is slower on several non-benchmarked entry points
  (documented in `bench/analysis.md` §6); those rows were not
  dropped, reworded, or added to the README table here.

## 6. What changed in this phase

- `README.md`: one benchmark row only — *bitwise AND, 16 MiB*
  `2.120 ms | 8.089 ms | 3.82x` → `2.506 ms | 7.683 ms | 2.81x`
  (median of the seven measured runs in this session). **No other
  benchmark number, ratio, or row was changed.** The environment
  line was already correct (Linux `6.8.0-147-generic`, Mojo
  `1.2.0.dev2026092605 (236c32cb)`) and is unchanged.
- `bench/verify.md`: this file.
- No code, kernel, benchmark, or test file was modified: no failing
  test demonstrated a bug, so per the rules no code change was made.

## 7. Final verification

- `pixi run build && pixi run test` after all edits — green:
  **135 passed in 24.27s**, exit code 0 (first run of the session was
  135 passed in 22.70s).
