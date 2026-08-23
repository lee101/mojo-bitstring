"""ctypes bindings for the Mojo packed-bit kernels."""

from __future__ import annotations

import ctypes
import os

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIB = os.environ.get("MOJO_BITSTRING_LIB", os.path.join(ROOT, "dist", "libmojo-bitstring.so"))

I = ctypes.c_int64
U = ctypes.c_uint64

_SIGNATURES = {
    "mbs_count": ([I, I], I),
    "mbs_binary": ([I, I, I, I, I], None),
    "mbs_binary_range": ([I, I, I, I, I, I], None),
    "mbs_invert": ([I, I, I], None),
    "mbs_invert_range": ([I, I, I, I], None),
    "mbs_read_u64": ([I, I, I], U),
    "mbs_write_u64": ([I, I, I, U], None),
    "mbs_read_many_u64": ([I, I, I, I, I, I], None),
    "mbs_write_many_u64": ([I, I, I, I, I, I], None),
    "mbs_copy_bits": ([I, I, I, I, I], None),
    "mbs_find": ([I, I, I, I, I, I, I], I),
    "mbs_findall": ([I, I, I, I, I, I, I, I, I], I),
    "mbs_reverse": ([I, I, I], None),
    "mbs_fill": ([I, I, I], None),
}

_library: ctypes.CDLL | None = None


def lib() -> ctypes.CDLL:
    global _library
    if _library is None:
        if not os.path.exists(LIB):
            raise RuntimeError("Mojo library is not built; run `pixi run build`")
        _library = ctypes.CDLL(LIB)
        for name, (argtypes, restype) in _SIGNATURES.items():
            function = getattr(_library, name)
            function.argtypes = argtypes
            function.restype = restype
    return _library


def addr(array: np.ndarray, dtype: np.dtype) -> int:
    """Return an address only for an exact, live C-contiguous ABI buffer."""
    expected = np.dtype(dtype)
    if not isinstance(array, np.ndarray):
        raise TypeError("FFI buffers must be NumPy arrays")
    if array.dtype != expected or not array.dtype.isnative:
        raise TypeError(f"FFI buffer must have native dtype {expected}")
    if not array.flags.c_contiguous:
        raise ValueError("FFI buffer must be C-contiguous")
    if array.size == 0:
        raise ValueError("empty buffers must not cross the FFI boundary")
    address = int(array.ctypes.data)
    if address == 0:
        raise ValueError("FFI buffer has a null address")
    return address
