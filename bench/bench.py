"""Benchmark the covered kernels against upstream bitstring 4.4."""

from __future__ import annotations

import importlib.util
import math
import os
import platform
import subprocess
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE = os.path.join(ROOT, "python", "bitstring")
PYTHON_ROOT = os.path.dirname(PACKAGE)
sys.path = [
    path for path in sys.path
    if os.path.abspath(path or os.curdir) != os.path.abspath(PYTHON_ROOT)
]
import bitstring as upstream  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "mojo_bitstring_port",
    os.path.join(PACKAGE, "__init__.py"),
    submodule_search_locations=[PACKAGE],
)
assert spec and spec.loader
mojo = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mojo
spec.loader.exec_module(mojo)


def best_time(function, repeat: int = 5) -> tuple[float, object]:
    best = math.inf
    result = None
    for _ in range(repeat):
        start = time.perf_counter()
        result = function()
        best = min(best, time.perf_counter() - start)
    return best, result


def cpu_name() -> str:
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as stream:
            for line in stream:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown CPU"


def mojo_version() -> str:
    result = subprocess.run(
        ["mojo", "--version"], check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def main() -> None:
    rng = np.random.default_rng(2026)
    size = 16 * 1024 * 1024
    left_raw = rng.integers(0, 256, size=size, dtype=np.uint8).tobytes()
    right_raw = rng.integers(0, 256, size=size, dtype=np.uint8).tobytes()
    mojo_left, mojo_right = mojo.Bits(left_raw), mojo.Bits(right_raw)
    ref_left, ref_right = upstream.Bits(left_raw), upstream.Bits(right_raw)

    search_raw = bytearray(left_raw[: 4 * 1024 * 1024])
    needle = b"\xde\xad\xbe\xef\xca\xfe\xba\xbe"
    search_raw[-len(needle) :] = needle
    mojo_search, ref_search = mojo.Bits(search_raw), upstream.Bits(search_raw)

    values = rng.integers(0, 4096, size=500_000, dtype=np.uint16)
    mojo_array = mojo.Array("uint:12", values)
    ref_array = upstream.Array("uint:12", values)

    assert mojo_left.count(1) == ref_left.count(1)
    assert (mojo_left & mojo_right).tobytes() == (ref_left & ref_right).tobytes()
    assert (~mojo_left).tobytes() == (~ref_left).tobytes()
    assert mojo_search.find(mojo.Bits(needle), bytealigned=True) == ref_search.find(
        upstream.Bits(needle), bytealigned=True
    )
    assert mojo_array.tolist() == ref_array.tolist()

    cases = [
        ("count set bits, 16 MiB", lambda: mojo_left.count(1), lambda: ref_left.count(1)),
        ("bitwise AND, 16 MiB", lambda: mojo_left & mojo_right, lambda: ref_left & ref_right),
        ("invert, 16 MiB", lambda: ~mojo_left, lambda: ~ref_left),
        (
            "find 64-bit value, 4 MiB byte-aligned",
            lambda: mojo_search.find(mojo.Bits(needle), bytealigned=True),
            lambda: ref_search.find(upstream.Bits(needle), bytealigned=True),
        ),
        (
            "pack Array uint12, 500k values",
            lambda: mojo.Array("uint:12", values),
            lambda: upstream.Array("uint:12", values),
        ),
        ("parse Array uint12, 500k values", mojo_array.tolist, ref_array.tolist),
    ]

    print(f"Machine: {cpu_name()}")
    print(
        f"Linux {platform.release()}, Python {platform.python_version()}, "
        f"{mojo_version()}, upstream bitstring {upstream.__version__}"
    )
    print("Best of 5 runs; inputs are preconstructed unless the operation says pack.")
    print()
    print("| operation | mojo-bitstring | upstream bitstring | upstream / Mojo |")
    print("|---|---:|---:|---:|")
    for name, mojo_function, upstream_function in cases:
        mojo_seconds, _ = best_time(mojo_function)
        upstream_seconds, _ = best_time(upstream_function)
        print(
            f"| {name} | {mojo_seconds * 1e3:.3f} ms | "
            f"{upstream_seconds * 1e3:.3f} ms | {upstream_seconds / mojo_seconds:.2f}x |"
        )


if __name__ == "__main__":
    main()
