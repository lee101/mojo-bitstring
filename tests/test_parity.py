from __future__ import annotations

from functools import lru_cache
import json
import os
import subprocess
import sys

import numpy as np
import pytest

import bitstring as mojo


@lru_cache
def upstream(body: str):
    environment = os.environ.copy()
    environment["PYTHONPATH"] = ""
    script = (
        "import json\n"
        "from bitstring import *\n"
        + body
        + "\nprint(json.dumps(result, allow_nan=True))\n"
    )
    process = subprocess.run(
        [sys.executable, "-c", script],
        cwd="/tmp",
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(process.stdout)


@pytest.mark.parametrize(
    "expression",
    [
        "'0b00101101'",
        "'0x00affe'",
        "'0o07654'",
        "bytes(range(16))",
        "Bits(uint=1337, length=17)",
        "Bits(int=-1234, length=17)",
    ],
)
def test_construction_parity(expression):
    expected = upstream(
        f"x=Bits({expression})\nresult=[x.bin, len(x), x.tobytes().hex(), x.count(1)]"
    )
    namespace = {"Bits": mojo.Bits, "bytes": bytes, "range": range}
    x = eval(f"mojo.Bits({expression})", {"mojo": mojo, **namespace})
    assert [x.bin, len(x), x.tobytes().hex(), x.count(1)] == expected


@pytest.mark.parametrize("offset,length", [(0, 32), (3, 17), (8, 16), (13, 0)])
def test_bytes_offset_and_length(offset, length):
    raw = bytes.fromhex("12345678")
    expected = upstream(
        f"x=Bits(bytes=bytes.fromhex('12345678'), offset={offset}, length={length})\n"
        "result=[x.bin,x.tobytes().hex()]"
    )
    actual = mojo.Bits(bytes=raw, offset=offset, length=length)
    assert [actual.bin, actual.tobytes().hex()] == expected


def test_numeric_and_text_properties():
    expected = upstream(
        "result=[Bits('0x89abcdef').uint, Bits('0x89abcdef').int, "
        "Bits('0x78563412').uintle, Bits('0x78563412').intle, "
        "Bits('0b101010').bin, Bits('0o765').oct, Bits('0x00af').hex]"
    )
    actual = [
        mojo.Bits("0x89abcdef").uint,
        mojo.Bits("0x89abcdef").int,
        mojo.Bits("0x78563412").uintle,
        mojo.Bits("0x78563412").intle,
        mojo.Bits("0b101010").bin,
        mojo.Bits("0o765").oct,
        mojo.Bits("0x00af").hex,
    ]
    assert actual == expected


def test_native_float16_bool_and_predicates():
    expected = upstream(
        "x=Bits('0b101101');"
        "result=[Bits(uintne=0x1234,length=16).uintne,"
        "Bits(intne=-1234,length=16).intne,"
        "Bits(float=1.5,length=16).float,"
        "Bits(bool=True).bool,x.all(1,[0,2,3,5]),x.any(0),"
        "x.startswith('0b101'),x.endswith('0b101')]"
    )
    x = mojo.Bits("0b101101")
    actual = [
        mojo.Bits(uintne=0x1234, length=16).uintne,
        mojo.Bits(intne=-1234, length=16).intne,
        mojo.Bits(float=1.5, length=16).float,
        mojo.Bits(bool=True).bool,
        x.all(1, [0, 2, 3, 5]),
        x.any(0),
        x.startswith("0b101"),
        x.endswith("0b101"),
    ]
    assert actual == expected


def test_slicing_and_concatenation():
    expected = upstream(
        "x=Bits('0x0123456789')\n"
        "result=[x[3:31].bin,x[::-1].bin,x[1::3].bin,(x[:7]+x[17:]).bin,(x[:5]*3).bin]"
    )
    x = mojo.Bits("0x0123456789")
    actual = [x[3:31].bin, x[::-1].bin, x[1::3].bin, (x[:7] + x[17:]).bin, (x[:5] * 3).bin]
    assert actual == expected


def test_bitwise_invert_and_shifts():
    expected = upstream(
        "a=Bits('0x123456789abcdef0');b=Bits('0xff00ff00ff00ff00')\n"
        "result=[(a&b).hex,(a|b).hex,(a^b).hex,(~a).hex,(a<<13).hex,(a>>13).hex]"
    )
    a = mojo.Bits("0x123456789abcdef0")
    b = mojo.Bits("0xff00ff00ff00ff00")
    actual = [(a & b).hex, (a | b).hex, (a ^ b).hex, (~a).hex, (a << 13).hex, (a >> 13).hex]
    assert actual == expected


@pytest.mark.parametrize("size", [1, 31, 32, 33, 63, 64, 65, 257])
def test_bitwise_simd_tail_parity(size):
    left_raw = bytes((index * 37 + 11) & 0xFF for index in range(size))
    right_raw = bytes((index * 19 + 7) & 0xFF for index in range(size))
    left = mojo.Bits(left_raw)
    right = mojo.Bits(right_raw)
    expected = upstream(
        f"a=Bits(bytes.fromhex({left_raw.hex()!r}));"
        f"b=Bits(bytes.fromhex({right_raw.hex()!r}));"
        "result=[(a&b).tobytes().hex(),(a|b).tobytes().hex(),"
        "(a^b).tobytes().hex(),(~a).tobytes().hex()]"
    )
    actual = [
        (left & right).tobytes().hex(),
        (left | right).tobytes().hex(),
        (left ^ right).tobytes().hex(),
        (~left).tobytes().hex(),
    ]
    assert actual == expected


@pytest.mark.parametrize("size", [4 * 1024 * 1024 - 37, 4 * 1024 * 1024 + 37])
def test_bitwise_parallel_threshold_parity(size):
    left_raw = np.arange(size, dtype=np.uint8)
    right_raw = np.arange(size, dtype=np.uint8)[::-1].copy()
    left = mojo.Bits(left_raw)
    right = mojo.Bits(right_raw)
    assert (left & right).tobytes() == np.bitwise_and(left_raw, right_raw).tobytes()
    assert (~left).tobytes() == np.bitwise_not(left_raw).tobytes()


def test_count_large_parity():
    raw = bytes(range(256)) * 4096
    actual = mojo.Bits(raw)
    expected = upstream(
        "x=Bits(bytes(range(256))*4096)\nresult=[x.count(1),x.count(0)]"
    )
    assert [actual.count(1), actual.count(0)] == expected


def test_find_findall_rfind_and_membership():
    text = "0010110110110010110"
    expected = upstream(
        f"x=Bits(bin='{text}')\n"
        "result=[list(x.find('0b110')),list(x.rfind('0b110')),"
        "list(x.findall('0b110')),list(x.findall('0b11',start=3,end=16,count=2)),"
        "'0b1011' in x]"
    )
    x = mojo.Bits(bin=text)
    actual = [
        list(x.find("0b110")),
        list(x.rfind("0b110")),
        list(x.findall("0b110")),
        list(x.findall("0b11", start=3, end=16, count=2)),
        "0b1011" in x,
    ]
    assert actual == expected


def test_byte_aligned_search():
    x = mojo.Bits(bytes=b"ABABA")
    expected = upstream(
        "x=Bits(bytes=b'ABABA')\n"
        "result=[list(x.findall('0x4142')),list(x.findall('0b1',bytealigned=True))]"
    )
    actual = [list(x.findall("0x4142")), list(x.findall("0b1", bytealigned=True))]
    assert actual == expected


@pytest.mark.parametrize(
    "raw,needle",
    [
        (b"AAAAAA", b"AAA"),
        (b"ABCDEF", b"F"),
        (b"ABCDEF", b"ABCDEF"),
        (b"ABCDEF", b"ABCDEFG"),
        (b"ABCDABCDAB", b"ABCDAB"),
        (bytes(range(255)) + b"needle", b"needle"),
    ],
)
def test_byte_aligned_skip_search_parity(raw, needle):
    x = mojo.Bits(raw)
    expected = upstream(
        f"x=Bits({raw!r});n=Bits({needle!r});"
        "result=[list(x.find(n,bytealigned=True)),"
        "list(x.findall(n,bytealigned=True))]"
    )
    actual = [
        list(x.find(mojo.Bits(needle), bytealigned=True)),
        list(x.findall(mojo.Bits(needle), bytealigned=True)),
    ]
    assert actual == expected


def test_cut_split_and_join():
    expected = upstream(
        "x=Bits('0b0010010011')\n"
        "result=[[p.bin for p in x.cut(3)],[p.bin for p in x.split('0b100')],"
        "Bits('0b00').join(['0b1','0b11','0b111']).bin]"
    )
    x = mojo.Bits("0b0010010011")
    actual = [
        [p.bin for p in x.cut(3)],
        [p.bin for p in x.split("0b100")],
        mojo.Bits("0b00").join(["0b1", "0b11", "0b111"]).bin,
    ]
    assert actual == expected


@pytest.mark.parametrize(
    "fmt,values",
    [
        ("uint:10, hex:8, int:13, 0b11", (130, "3d", -23)),
        ("uintle:24, intbe:16, bool", (0xABCDEF, -1234, True)),
        ("float:32, floatle:64", (1.25, -123.5)),
        ("pad:3, uint:5, bytes:2", (17, b"AZ")),
        ("3*uint:7", (1, 64, 127)),
    ],
)
def test_pack_unpack_parity(fmt, values):
    value_repr = repr(values)
    unpack_fmt = fmt.replace("0b11", "bin:2")
    if "bytes" in fmt:
        expected = upstream(
            f"fmt={fmt!r};values={value_repr}\n"
            f"x=pack(fmt,*values)\ny=x.unpack({unpack_fmt!r})\n"
            "result=[x.bin,[v.hex() if isinstance(v,bytes) else v for v in y]]"
        )
        x = mojo.pack(fmt, *values)
        actual_values = [
            value.hex() if isinstance(value, bytes) else value
            for value in x.unpack(unpack_fmt)
        ]
        assert [x.bin, actual_values] == expected
        return
    expected = upstream(
        f"fmt={fmt!r};values={value_repr}\n"
        f"x=pack(fmt,*values)\nresult=[x.bin,x.unpack({unpack_fmt!r})]"
    )
    x = mojo.pack(fmt, *values)
    assert [x.bin, x.unpack(unpack_fmt)] == expected


def test_variable_length_unpack():
    x = mojo.pack("uint:10, hex:8, int:13, 0b11", 130, "3d", -23)
    expected = upstream(
        "x=pack('uint:10, hex:8, int:13, 0b11',130,'3d',-23)\n"
        "result=x.unpack('uint:10, hex, int:13, bin:2')"
    )
    assert x.unpack("uint:10, hex, int:13, bin:2") == expected


def test_keyword_length_and_literal_format():
    expected = upstream(
        "x=pack('2*uint:n, 0b11, pad:2',1,6,n=3);"
        "result=[x.bin,x.unpack('2*uint:n, bin:2, pad:2',n=3)]"
    )
    x = mojo.pack("2*uint:n, 0b11, pad:2", 1, 6, n=3)
    assert [x.bin, x.unpack("2*uint:n, bin:2, pad:2", n=3)] == expected


@pytest.mark.parametrize("value", [0, 1, 2, 12, 255, 65535])
def test_unsigned_exponential_golomb(value):
    expected = upstream(f"x=Bits(ue={value})\nresult=[x.bin,x.ue]")
    x = mojo.Bits(ue=value)
    assert [x.bin, x.ue] == expected


@pytest.mark.parametrize("value", [-100, -3, -1, 0, 1, 2, 99])
def test_signed_exponential_golomb(value):
    expected = upstream(f"x=Bits(se={value})\nresult=[x.bin,x.se]")
    x = mojo.Bits(se=value)
    assert [x.bin, x.se] == expected


def test_mutating_sequence_operations():
    expected = upstream(
        "x=BitArray('0b101001');x.append('0xf');x.prepend('0b00');"
        "x.insert('0b11',3);x.overwrite('0b000',7);del x[1:3]\nresult=x.bin"
    )
    x = mojo.BitArray("0b101001")
    x.append("0xf")
    x.prepend("0b00")
    x.insert("0b11", 3)
    x.overwrite("0b000", 7)
    del x[1:3]
    assert x.bin == expected


def test_mutable_slice_assignment():
    expected = upstream(
        "x=BitArray('0b101001');x[1:4]='0b11';x[::2]='0b010';result=x.bin"
    )
    x = mojo.BitArray("0b101001")
    x[1:4] = "0b11"
    x[::2] = "0b010"
    assert x.bin == expected


def test_set_invert_reverse_rotate():
    expected = upstream(
        "x=BitArray('0b00101100101');x.set(1,[0,3,-1]);x.invert([1,4,8]);"
        "x.reverse(2,9);x.rol(3,1,10);x.ror(2)\nresult=x.bin"
    )
    x = mojo.BitArray("0b00101100101")
    x.set(1, [0, 3, -1])
    x.invert([1, 4, 8])
    x.reverse(2, 9)
    x.rol(3, 1, 10)
    x.ror(2)
    assert x.bin == expected


def test_replace_overlapping_policy():
    expected = upstream(
        "x=BitArray('0b111110111');n=x.replace('0b11','0b001',count=3)\nresult=[x.bin,n]"
    )
    x = mojo.BitArray("0b111110111")
    n = x.replace("0b11", "0b001", count=3)
    assert [x.bin, n] == expected


@pytest.mark.parametrize("fmt", [None, 2, [1, 2], ">2hI"])
def test_byteswap(fmt):
    expected = upstream(
        f"x=BitArray('0x0011223344556677');n=x.byteswap({fmt!r})\nresult=[x.hex,n]"
    )
    x = mojo.BitArray("0x0011223344556677")
    n = x.byteswap(fmt)
    assert [x.hex, n] == expected


def test_stream_read_peek_align_and_readto():
    expected = upstream(
        "x=ConstBitStream('0b10100111'+'01011010'+'111');"
        "a=x.read('uint:3');b=x.peek('bin:4');c=x.read('bin:4');"
        "skipped=x.bytealign();d=x.readto('0b101');"
        "result=[a,b,c,skipped,d.bin,x.pos]"
    )
    x = mojo.ConstBitStream("0b1010011101011010111")
    actual = [x.read("uint:3"), x.peek("bin:4"), x.read("bin:4")]
    actual.append(x.bytealign())
    found = x.readto("0b101")
    actual.extend([found.bin, x.pos])
    assert actual == expected


def test_stream_readlist_and_position():
    expected = upstream(
        "x=ConstBitStream(pack('uint:4,int:6,bool,hex:8',9,-12,True,'af'));"
        "a=x.readlist('uint:4,int:6');p=x.pos;b=x.peeklist('bool,hex:8');"
        "result=[a,p,b,x.pos]"
    )
    x = mojo.ConstBitStream(mojo.pack("uint:4,int:6,bool,hex:8", 9, -12, True, "af"))
    a = x.readlist("uint:4,int:6")
    position = x.pos
    b = x.peeklist("bool,hex:8")
    assert [a, position, b, x.pos] == expected


@pytest.mark.parametrize("dtype,values", [("uint:5", [0, 1, 17, 31]), ("int:7", [-64, -1, 0, 63])])
def test_array_integer_parity(dtype, values):
    expected = upstream(
        f"x=Array({dtype!r},{values!r})\nresult=[x.tolist(),x.data.bin,len(x)]"
    )
    x = mojo.Array(dtype, values)
    assert [x.tolist(), x.data.bin, len(x)] == expected


@pytest.mark.parametrize(
    "dtype,values",
    [("bool", [False, True, True]), ("float:32", [1.5, -2.25, 0.0])],
)
def test_array_other_basic_types(dtype, values):
    expected = upstream(
        f"x=Array({dtype!r},{values!r});result=[x.tolist(),x.data.bin,len(x)]"
    )
    x = mojo.Array(dtype, values)
    assert [x.tolist(), x.data.bin, len(x)] == expected


@pytest.mark.parametrize(
    "dtype,value",
    [("uint:5", -1), ("uint:5", 32), ("int:5", -17), ("int:5", 16)],
)
def test_array_bulk_integer_range_is_not_silently_narrowed(dtype, value):
    with pytest.raises(mojo.CreationError):
        mojo.Array(dtype, [value])


def test_array_mutations():
    expected = upstream(
        "x=Array('uint:6',[1,2,3]);x.append(63);x.insert(1,17);"
        "p=x.pop();x.reverse();result=[x.tolist(),p]"
    )
    x = mojo.Array("uint:6", [1, 2, 3])
    x.append(63)
    x.insert(1, 17)
    popped = x.pop()
    x.reverse()
    assert [x.tolist(), popped] == expected


def test_dtype_pack_unpack():
    expected = upstream(
        "d=Dtype('int:12');x=d.build(-101);result=[x.bin,d.parse(x),d.bitlength]"
    )
    dtype = mojo.Dtype("int:12")
    x = dtype.build(-101)
    assert [x.bin, dtype.parse(x), dtype.bitlength] == expected


def test_file_output_and_bytes_padding(tmp_path):
    value = mojo.Bits("0b101011001")
    path = tmp_path / "bits.bin"
    with path.open("wb") as stream:
        value.tofile(stream)
    expected = upstream(
        "import io\nx=Bits('0b101011001');f=io.BytesIO();x.tofile(f);"
        "result=[x.tobytes().hex(),f.getvalue().hex()]"
    )
    assert [value.tobytes().hex(), path.read_bytes().hex()] == expected


def test_error_parity_categories():
    with pytest.raises(mojo.InterpretError):
        _ = mojo.Bits("0b101").hex
    with pytest.raises(mojo.CreationError):
        mojo.Bits(uint=8, length=3)
    with pytest.raises(mojo.ReadError):
        mojo.ConstBitStream("0b1").read("uint:2")
    with pytest.raises(ValueError):
        mojo.Bits("0b1").find("")
