from __future__ import annotations

from functools import lru_cache
import json
import math
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


def _upstream_err_name(body: str) -> str:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = ""
    script = (
        "from bitstring import *\n"
        "try:\n"
        "    " + body + "\n"
        "except Exception as e:\n"
        "    print(type(e).__name__)\n"
        "else:\n"
        "    print('NoError')\n"
    )
    process = subprocess.run(
        [sys.executable, "-c", script],
        cwd="/tmp",
        env=environment,
        capture_output=True,
        text=True,
    )
    return process.stdout.strip()


# NOTE: upstream raises ValueError where mojo raises CreationError/InterpretError
# (both subclass ValueError), ReadError where mojo raises ReadError, and plain
# Error where mojo raises Error. These tests assert the mojo class is a subclass
# of the upstream class, so parity is by error-class hierarchy, not message text.

def test_degenerate_empty_bits_parity():
    expected = upstream(
        "result=[Bits().bin,len(Bits()),Bits().hex,Bits().oct,Bits().bytes.hex(),"
        "Bits().tobytes().hex(),bool(Bits()),str(Bits()),repr(Bits())]"
    )
    actual = [
        mojo.Bits().bin, len(mojo.Bits()), mojo.Bits().hex, mojo.Bits().oct,
        mojo.Bits().bytes.hex(), mojo.Bits().tobytes().hex(),
        bool(mojo.Bits()), str(mojo.Bits()), repr(mojo.Bits()),
    ]
    assert actual == expected


def test_degenerate_empty_construction_parity():
    expected = upstream(
        "result=[Bits('').bin,Bits(b'').bin,Bits([]).bin,len(Bits('')),"
        "len(Bits(b'')),len(Bits([])),Bits(bytes=b'').bin]"
    )
    actual = [
        mojo.Bits("").bin, mojo.Bits(b"").bin, mojo.Bits([]).bin,
        len(mojo.Bits("")), len(mojo.Bits(b"")), len(mojo.Bits([])),
        mojo.Bits(bytes=b"").bin,
    ]
    assert actual == expected


def test_single_bit_and_single_element_parity():
    expected = upstream(
        "result=[Bits('0b1').bin,Bits('0b1').uint,Bits('0b1').bool,Bits('0b0').bool,"
        "Bits(uint=1,length=1).bin,Bits(uint=0,length=1).uint,Bits(5).bin,len(Bits(5)),"
        "Bits(length=5).bin,Bits([1,0,1,1]).bin,Bits((0,1)).bin]"
    )
    actual = [
        mojo.Bits("0b1").bin, mojo.Bits("0b1").uint, mojo.Bits("0b1").bool,
        mojo.Bits("0b0").bool, mojo.Bits(uint=1, length=1).bin,
        mojo.Bits(uint=0, length=1).uint, mojo.Bits(5).bin, len(mojo.Bits(5)),
        mojo.Bits(length=5).bin, mojo.Bits([1, 0, 1, 1]).bin,
        mojo.Bits((0, 1)).bin,
    ]
    assert actual == expected


def test_single_index_negative_parity():
    expected = upstream("x=Bits('0b101');result=[x[0],x[-1],x[-3],x[1]]")
    x = mojo.Bits("0b101")
    assert [x[0], x[-1], x[-3], x[1]] == expected


def test_hash_eq_bool_parity():
    expected = upstream(
        "result=[hash(Bits('0b101'))==hash(Bits('0b101')),"
        "len(set([Bits('0b101'),Bits('0b101'),Bits('0b010')])),"
        "Bits('0b101')=='0b101',Bits('0b101')==Bits('0b101'),"
        "Bits('0b101')=='0b010',Bits('0b101')==5,Bits('0b101')!=Bits('0b101'),"
        "bool(Bits()),bool(Bits('0b0')),bool(Bits('0b1'))]"
    )
    actual = [
        hash(mojo.Bits("0b101")) == hash(mojo.Bits("0b101")),
        len(set([mojo.Bits("0b101"), mojo.Bits("0b101"), mojo.Bits("0b010")])),
        mojo.Bits("0b101") == "0b101", mojo.Bits("0b101") == mojo.Bits("0b101"),
        mojo.Bits("0b101") == "0b010", mojo.Bits("0b101") == 5,
        mojo.Bits("0b101") != mojo.Bits("0b101"),
        bool(mojo.Bits()), bool(mojo.Bits("0b0")), bool(mojo.Bits("0b1")),
    ]
    assert actual == expected


def test_str_repr_parity():
    expected = upstream(
        "result=[str(Bits('0b101')),str(Bits('0xab')),str(Bits('0b1010')),str(Bits()),"
        "repr(Bits('0b101')),repr(Bits('0xab')),repr(BitArray('0b101')),"
        "repr(ConstBitStream('0b101')),repr(BitStream('0b101'))]"
    )
    actual = [
        str(mojo.Bits("0b101")), str(mojo.Bits("0xab")),
        str(mojo.Bits("0b1010")), str(mojo.Bits()),
        repr(mojo.Bits("0b101")), repr(mojo.Bits("0xab")),
        repr(mojo.BitArray("0b101")), repr(mojo.ConstBitStream("0b101")),
        repr(mojo.BitStream("0b101")),
    ]
    assert actual == expected


@pytest.mark.parametrize("expression", ["Bits().hex", "Bits().oct", "Bits().tobytes().hex()"])
def test_empty_hex_oct_tobytes_parity(expression):
    # expression evaluated via upstream() with Bits in scope
    expected = upstream(f"result={expression}")
    actual = eval(expression, {"Bits": mojo.Bits})
    assert actual == expected


def test_empty_count_find_parity():
    expected = upstream(
        "result=[Bits().count(1),Bits().count(0),list(Bits().find('0b1')),"
        "list(Bits().findall('0b1')),list(Bits().rfind('0b1')),('0b1' in Bits()),"
        "Bits().all(1),Bits().any(1),Bits().all(0),Bits().any(0),Bits()[0:0].bin]"
    )
    actual = [
        mojo.Bits().count(1), mojo.Bits().count(0),
        list(mojo.Bits().find("0b1")), list(mojo.Bits().findall("0b1")),
        list(mojo.Bits().rfind("0b1")), ("0b1" in mojo.Bits()),
        mojo.Bits().all(1), mojo.Bits().any(1),
        mojo.Bits().all(0), mojo.Bits().any(0), mojo.Bits()[0:0].bin,
    ]
    assert actual == expected


def test_duplicate_findall_parity():
    expected = upstream(
        "result=[list(Bits('0b1111').findall('0b11')),"
        "list(Bits('0b010010').findall('0b010')),"
        "list(Bits(b'AAAA').findall('0x4141',bytealigned=True))]"
    )
    actual = [
        list(mojo.Bits("0b1111").findall("0b11")),
        list(mojo.Bits("0b010010").findall("0b010")),
        list(mojo.Bits(b"AAAA").findall("0x4141", bytealigned=True)),
    ]
    assert actual == expected


def test_mismatched_shapes_parity():
    # binary op with unequal lengths -> ValueError both sides
    assert _upstream_err_name("Bits('0b101') & Bits('0b11')") == "ValueError"
    with pytest.raises(ValueError):
        _ = mojo.Bits("0b101") & mojo.Bits("0b11")
    with pytest.raises(ValueError):
        _ = mojo.Bits("0b101") | mojo.Bits("0b11")
    with pytest.raises(ValueError):
        _ = mojo.Bits("0b101") ^ mojo.Bits("0b11")


def test_float_tolerance_parity():
    # float32/float64 exact roundtrip via upstream bits
    for value, length in [(1.5, 16), (0.1, 32), (1 / 3, 64), (1e-300, 64)]:
        expected_bits = upstream(
            f"result=Bits(float={value!r},length={length}).bin"
        )
        actual_bits = mojo.Bits(float=value, length=length).bin
        assert actual_bits == expected_bits
        expected_float = upstream(
            f"result=Bits(float={value!r},length={length}).float"
        )
        actual_float = mojo.Bits(float=value, length=length).float
        tol = {16: 1e-3, 32: 1e-6, 64: 1e-12}[length]
        assert math.isclose(actual_float, expected_float, rel_tol=tol, abs_tol=1e-12)


def test_float_nan_inf_tolerance_parity():
    for value_name, value in [("nan", float("nan")), ("inf", float("inf")), ("-inf", float("-inf"))]:
        for length in [16, 32, 64]:
            expected_bits = upstream(
                f"result=Bits(float=float('{value_name}'),length={length}).bin"
            )
            actual_bits = mojo.Bits(float=value, length=length).bin
            assert actual_bits == expected_bits
            actual_float = mojo.Bits(float=value, length=length).float
            if math.isnan(value):
                assert math.isnan(actual_float)
            else:
                assert math.isinf(actual_float) and (actual_float > 0) == (value > 0)


def test_pack_float_tolerance_parity():
    for value, length in [(0.1, 32), (1 / 3, 64), (1.25, 32)]:
        expected_bits = upstream(
            f"result=pack('float:{length}',{value!r}).bin"
        )
        actual_bits = mojo.pack(f"float:{length}", value).bin
        assert actual_bits == expected_bits
        expected_round = upstream(
            f"result=pack('float:{length}',{value!r}).unpack('float:{length}')"
        )
        actual_round = mojo.pack(f"float:{length}", value).unpack(f"float:{length}")
        tol = 1e-6 if length == 32 else 1e-12
        assert len(actual_round) == len(expected_round) == 1
        assert math.isclose(actual_round[0], expected_round[0], rel_tol=tol, abs_tol=1e-12)


def test_pack_float_nan_inf_bits_parity():
    for value_name, value in [("nan", float("nan")), ("inf", float("inf"))]:
        expected_bits = upstream(f"result=pack('float:32',float('{value_name}')).bin")
        actual_bits = mojo.pack("float:32", value).bin
        assert actual_bits == expected_bits


def test_array_float_tolerance_parity():
    for values in [[1.5, -2.25], [0.1, 1 / 3]]:
        expected = upstream(
            f"x=Array('float:32',{values!r})\nresult=[x.tolist(),x.data.bin]"
        )
        actual = mojo.Array("float:32", values)
        assert actual.data.bin == expected[1]
        assert len(actual.tolist()) == len(expected[0])
        for got, want in zip(actual.tolist(), expected[0]):
            assert math.isclose(got, want, rel_tol=1e-6, abs_tol=1e-12)


def test_array_float_nan_inf_parity():
    expected_bits = upstream(
        "result=Array('float:32',[float('nan'),float('inf')]).data.bin"
    )
    actual = mojo.Array("float:32", [float("nan"), float("inf")])
    assert actual.data.bin == expected_bits
    first, second = actual.tolist()
    assert math.isnan(first) and math.isinf(second)


def test_float_subnormal_and_precision_parity():
    expected = upstream("result=[Bits(float=5e-324,length=64).float]")
    actual = mojo.Bits(float=5e-324, length=64).float
    assert actual == expected[0]
    assert actual == 5e-324


def test_degenerate_error_parity_valueerrors():
    # Each pair: upstream raises ValueError, mojo raises ValueError (or subclass).
    cases = [
        ("Bits('0b101')*-1", lambda: mojo.Bits("0b101") * -1),
        ("list(Bits('0b101').cut(0))", lambda: list(mojo.Bits("0b101").cut(0))),
        ("list(Bits('0b101').cut(-1))", lambda: list(mojo.Bits("0b101").cut(-1))),
        ("list(Bits('0b101').split(''))", lambda: list(mojo.Bits("0b101").split(""))),
        ("Bits('0b101') << -1", lambda: mojo.Bits("0b101") << -1),
        ("Bits('0b101') >> -1", lambda: mojo.Bits("0b101") >> -1),
        ("ConstBitStream('0b101').read(-1)", lambda: mojo.ConstBitStream("0b101").read(-1)),
        ("Bits('0b101').find('')", lambda: mojo.Bits("0b101").find("")),
    ]
    for upstream_body, mojo_fn in cases:
        assert _upstream_err_name(upstream_body) == "ValueError"
        with pytest.raises(ValueError):
            mojo_fn()


def test_degenerate_error_parity_readerror():
    assert _upstream_err_name("ConstBitStream('0b1').read('uint:2')") == "ReadError"
    with pytest.raises(mojo.ReadError):
        mojo.ConstBitStream("0b1").read("uint:2")
    assert _upstream_err_name("Bits('0b101').unpack('uint:5')") == "ReadError"
    with pytest.raises(mojo.ReadError):
        mojo.Bits("0b101").unpack("uint:5")


def test_degenerate_error_parity_creation_value():
    for upstream_body, mojo_fn in [
        ("Bits(uint=8,length=3)", lambda: mojo.Bits(uint=8, length=3)),
        ("Bits(int=4,length=3)", lambda: mojo.Bits(int=4, length=3)),
        ("pack('uint:3',8)", lambda: mojo.pack("uint:3", 8)),
        ("pack('uint:3',-1)", lambda: mojo.pack("uint:3", -1)),
        ("pack('int:3',4)", lambda: mojo.pack("int:3", 4)),
        ("Bits(ue=-1)", lambda: mojo.Bits(ue=-1)),
    ]:
        assert _upstream_err_name(upstream_body) == "ValueError"
        with pytest.raises(ValueError):
            mojo_fn()


def test_degenerate_error_parity_interpret_value():
    for upstream_body, mojo_fn in [
        ("Bits('0b101').hex", lambda: mojo.Bits("0b101").hex),
        ("Bits().uint", lambda: mojo.Bits().uint),
        ("Bits('0b101').bytes", lambda: mojo.Bits("0b101").bytes),
        ("Bits().bool", lambda: mojo.Bits().bool),
    ]:
        # upstream raises ValueError; mojo raises InterpretError (subclass of ValueError)
        assert _upstream_err_name(upstream_body) == "ValueError"
        with pytest.raises(mojo.InterpretError):
            mojo_fn()


def test_degenerate_error_parity_index():
    assert _upstream_err_name("Bits('0b101')[3]") == "IndexError"
    with pytest.raises(IndexError):
        _ = mojo.Bits("0b101")[3]
    assert _upstream_err_name("Bits('0b101')[-4]") == "IndexError"
    with pytest.raises(IndexError):
        _ = mojo.Bits("0b101")[-4]


def test_degenerate_empty_uintle_parity():
    assert _upstream_err_name("Bits().uintle") == "ValueError"
    with pytest.raises(ValueError):
        _ = mojo.Bits().uintle
    assert _upstream_err_name("Bits().intle") == "ValueError"
    with pytest.raises(ValueError):
        _ = mojo.Bits().intle


def test_degenerate_bytealign_eof_parity():
    assert _upstream_err_name(
        "x=ConstBitStream('0b101');x.pos=3;x.bytealign()"
    ) == "ValueError"
    stream = mojo.ConstBitStream("0b101")
    stream.pos = 3
    with pytest.raises(ValueError):
        stream.bytealign()


def test_degenerate_rol_ror_negative_parity():
    assert _upstream_err_name("x=BitArray('0b100');x.rol(-1)") == "ValueError"
    with pytest.raises(ValueError):
        mojo.BitArray("0b100").rol(-1)
    assert _upstream_err_name("x=BitArray('0b100');x.ror(-1)") == "ValueError"
    with pytest.raises(ValueError):
        mojo.BitArray("0b100").ror(-1)


def test_degenerate_overwrite_beyond_parity():
    # upstream overwrite past end extends the bitstring
    expected = upstream(
        "x=BitArray('0b101');x.overwrite('0b11',2);result=[x.bin,len(x)]"
    )
    actual = mojo.BitArray("0b101")
    actual.overwrite("0b11", 2)
    assert [actual.bin, len(actual)] == expected


def test_degenerate_byteswap_unaligned_parity():
    expected = upstream(
        "x=BitArray('0b101');n=x.byteswap();result=[x.bin,n]"
    )
    actual = mojo.BitArray("0b101")
    count = actual.byteswap()
    assert [actual.bin, count] == expected


def test_shift_beyond_and_zero_parity():
    expected = upstream(
        "result=[(Bits('0b101')<<10).bin,(Bits('0b101')>>10).bin,"
        "(Bits('0b101')<<0).bin,(Bits('0b101')>>0).bin]"
    )
    actual = [
        (mojo.Bits("0b101") << 10).bin, (mojo.Bits("0b101") >> 10).bin,
        (mojo.Bits("0b101") << 0).bin, (mojo.Bits("0b101") >> 0).bin,
    ]
    assert actual == expected


def test_cut_variants_parity():
    expected = upstream(
        "result=[[p.bin for p in Bits('0b101').cut(1)],"
        "[p.bin for p in Bits('0b101').cut(10)],"
        "[p.bin for p in Bits('0b101010').cut(2,count=2)],"
        "[p.bin for p in Bits().cut(3)]]"
    )
    actual = [
        [p.bin for p in mojo.Bits("0b101").cut(1)],
        [p.bin for p in mojo.Bits("0b101").cut(10)],
        [p.bin for p in mojo.Bits("0b101010").cut(2, count=2)],
        [p.bin for p in mojo.Bits().cut(3)],
    ]
    assert actual == expected


def test_split_variants_parity():
    expected = upstream(
        "result=[[p.bin for p in Bits('0b10111').split('0b1')],"
        "[p.bin for p in Bits('0b101').split('0b111')],"
        "[p.bin for p in Bits().split('0b1')],"
        "[p.bin for p in Bits('0b10010').split('0b100')],"
        "[p.bin for p in Bits('0b10101').split('0b1',count=1)]]"
    )
    actual = [
        [p.bin for p in mojo.Bits("0b10111").split("0b1")],
        [p.bin for p in mojo.Bits("0b101").split("0b111")],
        [p.bin for p in mojo.Bits().split("0b1")],
        [p.bin for p in mojo.Bits("0b10010").split("0b100")],
        [p.bin for p in mojo.Bits("0b10101").split("0b1", count=1)],
    ]
    assert actual == expected


def test_join_variants_parity():
    expected = upstream(
        "result=[Bits('0b00').join([]).bin,Bits().join(['0b1','0b0']).bin,"
        "Bits('0b00').join(['0b1']).bin]"
    )
    actual = [
        mojo.Bits("0b00").join([]).bin,
        mojo.Bits().join(["0b1", "0b0"]).bin,
        mojo.Bits("0b00").join(["0b1"]).bin,
    ]
    assert actual == expected


def test_count_all_any_parity():
    expected = upstream(
        "x=Bits('0b10101');result=[x.count(1),x.count(0),x.count(True),x.count(False),"
        "x.count(2),Bits().count(1),Bits().count(0)]"
    )
    x = mojo.Bits("0b10101")
    assert [x.count(1), x.count(0), x.count(True), x.count(False), x.count(2),
            mojo.Bits().count(1), mojo.Bits().count(0)] == expected
    expected2 = upstream(
        "x=Bits('0b1010');result=[x.all(1),x.all(1,[0,2]),x.any(1,[1,3]),x.any(0,[0,2]),"
        "Bits().all(1),Bits().any(1),Bits().all(0),Bits().any(0)]"
    )
    y = mojo.Bits("0b1010")
    assert [y.all(1), y.all(1, [0, 2]), y.any(1, [1, 3]), y.any(0, [0, 2]),
            mojo.Bits().all(1), mojo.Bits().any(1),
            mojo.Bits().all(0), mojo.Bits().any(0)] == expected2


def test_startswith_endswith_parity():
    expected = upstream(
        "result=[Bits('0b101').startswith(''),Bits().startswith(''),"
        "Bits('0b101').startswith('0b101'),Bits('0b101').startswith('0b1011'),"
        "Bits('0b101').endswith(''),Bits().endswith(''),"
        "Bits('0b101').startswith('0b01',1),Bits('0b101').endswith('0b01',0,2)]"
    )
    b = mojo.Bits("0b101")
    actual = [
        b.startswith(""), mojo.Bits().startswith(""),
        b.startswith("0b101"), b.startswith("0b1011"),
        b.endswith(""), mojo.Bits().endswith(""),
        b.startswith("0b01", 1), b.endswith("0b01", 0, 2),
    ]
    assert actual == expected


def test_tobytes_parity():
    expected = upstream(
        "result=[Bits('0b101').tobytes().hex(),Bits().tobytes().hex(),"
        "Bits('0x1234').tobytes().hex(),Bits('0b101011001').tobytes().hex()]"
    )
    actual = [
        mojo.Bits("0b101").tobytes().hex(), mojo.Bits().tobytes().hex(),
        mojo.Bits("0x1234").tobytes().hex(),
        mojo.Bits("0b101011001").tobytes().hex(),
    ]
    assert actual == expected


def test_copy_parity():
    expected = upstream(
        "result=[Bits('0b101').copy().bin,type(Bits('0b101').copy()).__name__,"
        "BitArray('0b101').copy().bin]"
    )
    actual = [
        mojo.Bits("0b101").copy().bin,
        type(mojo.Bits("0b101").copy()).__name__,
        mojo.BitArray("0b101").copy().bin,
    ]
    assert actual == expected


def test_slice_negative_step_and_empty_parity():
    expected = upstream(
        "result=[Bits('0b101011')[::-1].bin,Bits('0b101')[5:2].bin,"
        "Bits('0b101011')[0:6:3].bin,Bits('0b101011')[1::3].bin]"
    )
    actual = [
        mojo.Bits("0b101011")[::-1].bin, mojo.Bits("0b101")[5:2].bin,
        mojo.Bits("0b101011")[0:6:3].bin, mojo.Bits("0b101011")[1::3].bin,
    ]
    assert actual == expected


def test_stream_pos_bytepos_parity():
    expected = upstream(
        "x=ConstBitStream('0b101');x.pos=2;result=[x.pos];"
        "y=ConstBitStream('0b10101010');result.append(y.bytepos);"
        "z=ConstBitStream('0b101010101010');z.bytepos=1;result.append(z.pos)"
    )
    x = mojo.ConstBitStream("0b101")
    x.pos = 2
    actual = [x.pos]
    y = mojo.ConstBitStream("0b10101010")
    actual.append(y.bytepos)
    z = mojo.ConstBitStream("0b101010101010")
    z.bytepos = 1
    actual.append(z.pos)
    assert actual == expected


def test_stream_read_int_type_parity():
    expected = upstream(
        "x=ConstBitStream('0b101');y=x.read(3);"
        "result=[y.bin,type(y).__name__,isinstance(y,ConstBitStream),x.pos]"
    )
    x = mojo.ConstBitStream("0b101")
    y = x.read(3)
    actual = [y.bin, type(y).__name__, isinstance(y, mojo.ConstBitStream), x.pos]
    assert actual == expected
    expected2 = upstream(
        "x=BitStream('0b101');y=x.read(3);result=[y.bin,type(y).__name__]"
    )
    x2 = mojo.BitStream("0b101")
    y2 = x2.read(3)
    assert [y2.bin, type(y2).__name__] == expected2


def test_stream_peek_no_advance_parity():
    expected = upstream(
        "x=ConstBitStream('0b1010');a=x.peek('uint:3');result=[a,x.pos];"
        "b=x.peeklist('uint:3');result.append([b,x.pos])"
    )
    x = mojo.ConstBitStream("0b1010")
    a = x.peek("uint:3")
    actual = [a, x.pos, [x.peeklist("uint:3"), x.pos]]
    assert actual == expected


def test_stream_bytealign_variants_parity():
    expected = upstream(
        "x=ConstBitStream('0b10101010');result=[[x.bytealign(),x.pos]];"
        "y=ConstBitStream();result.append([y.bytealign(),y.pos])"
    )
    x = mojo.ConstBitStream("0b10101010")
    actual = [[x.bytealign(), x.pos]]
    y = mojo.ConstBitStream()
    actual.append([y.bytealign(), y.pos])
    assert actual == expected


def test_stream_readto_variants_parity():
    expected = upstream(
        "x=ConstBitStream('0b10100101');result=[[x.readto('0b101').bin,x.pos]];"
        "y=ConstBitStream('0b101');result.append([y.readto('0b101').bin,y.pos])"
    )
    x = mojo.ConstBitStream("0b10100101")
    actual = [[x.readto("0b101").bin, x.pos]]
    y = mojo.ConstBitStream("0b101")
    actual.append([y.readto("0b101").bin, y.pos])
    assert actual == expected


def test_stream_find_sets_pos_parity():
    expected = upstream(
        "x=ConstBitStream('0b10101');x.find('0b01');result=[x.pos];"
        "y=ConstBitStream('0b10101');y.rfind('0b01');result.append(y.pos);"
        "z=ConstBitStream('0b101');z.pos=2;z.find('0b111');result.append(z.pos)"
    )
    x = mojo.ConstBitStream("0b10101")
    x.find("0b01")
    actual = [x.pos]
    y = mojo.ConstBitStream("0b10101")
    y.rfind("0b01")
    actual.append(y.pos)
    z = mojo.ConstBitStream("0b101")
    z.pos = 2
    z.find("0b111")
    actual.append(z.pos)
    assert actual == expected


def test_bitstream_insert_overwrite_default_pos_parity():
    expected = upstream(
        "x=BitStream('0b101');x.pos=1;x.insert('0b11');result=[[x.bin,x.pos]];"
        "y=BitStream('0b1011');y.pos=1;y.overwrite('0b00');result.append([y.bin,y.pos])"
    )
    x = mojo.BitStream("0b101")
    x.pos = 1
    x.insert("0b11")
    actual = [[x.bin, x.pos]]
    y = mojo.BitStream("0b1011")
    y.pos = 1
    y.overwrite("0b00")
    actual.append([y.bin, y.pos])
    assert actual == expected


def test_pack_variants_parity():
    expected = upstream(
        "result=[pack('bool',True).bin,pack('bool',0).bin,"
        "pack('pad:3').bin,pack('uint:2,pad:2',2).bin,"
        "pack('ue',5).bin,pack('se',-3).bin,pack('ue,se',0,0).bin,"
        "pack('uintbe:16',0x1234).bin,pack('uintbe:16',0x1234).unpack('uintbe:16'),"
        "pack('floatle:32',1.5).bin,pack(['uint:3','bool'],5,True).bin,"
        "pack('0b101, 0x3').bin,pack('bits:3','0b101').bin,"
        "pack('intne:16',-1234).bin,pack('uintne:16',0x1234).bin,"
        "pack('floatne:32',1.5).bin,pack('floatne:32',1.5).unpack('floatne:32')]"
    )
    actual = [
        mojo.pack("bool", True).bin, mojo.pack("bool", 0).bin,
        mojo.pack("pad:3").bin, mojo.pack("uint:2,pad:2", 2).bin,
        mojo.pack("ue", 5).bin, mojo.pack("se", -3).bin,
        mojo.pack("ue,se", 0, 0).bin,
        mojo.pack("uintbe:16", 0x1234).bin,
        mojo.pack("uintbe:16", 0x1234).unpack("uintbe:16"),
        mojo.pack("floatle:32", 1.5).bin,
        mojo.pack(["uint:3", "bool"], 5, True).bin,
        mojo.pack("0b101, 0x3").bin, mojo.pack("bits:3", "0b101").bin,
        mojo.pack("intne:16", -1234).bin,
        mojo.pack("uintne:16", 0x1234).bin,
        mojo.pack("floatne:32", 1.5).bin,
        mojo.pack("floatne:32", 1.5).unpack("floatne:32"),
    ]
    assert actual == expected


def test_unpack_variants_parity():
    expected = upstream(
        "result=[[Bits('0b101010').unpack(['uint:3','uint:3'])[0],"
        "Bits('0b101010111').unpack(['uint:3',6])[0],"
        "Bits('0b101010111').unpack(['uint:3',6])[1].bin,"
        "Bits('0b101010').unpack('uint:3, bin'),"
        "Bits(pack('ue,ue',1,2)).unpack('ue,ue'),"
        "Bits('0b101').unpack('bool,bool,bool'),"
        "Bits('0b001011000').unpack('3*uint:3')]]"
    )[0]
    actual = [
        mojo.Bits("0b101010").unpack(["uint:3", "uint:3"])[0],
        mojo.Bits("0b101010111").unpack(["uint:3", 6])[0],
        mojo.Bits("0b101010111").unpack(["uint:3", 6])[1].bin,
        mojo.Bits("0b101010").unpack("uint:3, bin"),
        mojo.Bits(mojo.pack("ue,ue", 1, 2)).unpack("ue,ue"),
        mojo.Bits("0b101").unpack("bool,bool,bool"),
        mojo.Bits("0b001011000").unpack("3*uint:3"),
    ]
    assert actual == expected


def test_array_empty_single_dup_parity():
    expected = upstream(
        "result=[Array('uint:5',[]).tolist(),len(Array('uint:5',[])),"
        "Array('uint:5',[]).data.bin,Array('uint:5',[3]).tolist(),"
        "Array('uint:5',[3]).data.bin,Array('uint:5',[7,7,7]).tolist(),"
        "Array('uint:5',3).tolist(),len(Array('uint:5',3))]"
    )
    actual = [
        mojo.Array("uint:5", []).tolist(), len(mojo.Array("uint:5", [])),
        mojo.Array("uint:5", []).data.bin, mojo.Array("uint:5", [3]).tolist(),
        mojo.Array("uint:5", [3]).data.bin, mojo.Array("uint:5", [7, 7, 7]).tolist(),
        mojo.Array("uint:5", 3).tolist(), len(mojo.Array("uint:5", 3)),
    ]
    assert actual == expected


def test_array_uint64_int64_parity():
    expected = upstream(
        "result=[Array('uint:64',[18446744073709551615]).tolist(),"
        "Array('uint:64',[18446744073709551615]).data.bin,"
        "Array('int:64',[-9223372036854775808]).tolist(),"
        "Array('uint:65',[1]).tolist()]"
    )
    actual = [
        mojo.Array("uint:64", [18446744073709551615]).tolist(),
        mojo.Array("uint:64", [18446744073709551615]).data.bin,
        mojo.Array("int:64", [-9223372036854775808]).tolist(),
        mojo.Array("uint:65", [1]).tolist(),
    ]
    assert actual == expected


def test_array_from_bits_bytes_array_parity():
    expected = upstream(
        "result=[Array('uint:4',Bits('0b00010011')).tolist(),"
        "Array('uint:8',b'AB').tolist(),"
        "Array('uint:5',Array('uint:5',[1,2])).tolist()]"
    )
    actual = [
        mojo.Array("uint:4", mojo.Bits("0b00010011")).tolist(),
        mojo.Array("uint:8", b"AB").tolist(),
        mojo.Array("uint:5", mojo.Array("uint:5", [1, 2])).tolist(),
    ]
    assert actual == expected


def test_array_extend_setitem_slice_iter_parity():
    expected = upstream(
        "x=Array('uint:5',[1]);x.extend([2,3]);result=[x.tolist()];"
        "y=Array('uint:5',[1,2]);y[0]=9;result.append(y.tolist());"
        "z=Array('uint:5',[1,2,3]);result.append(z[0:2].tolist());"
        "result.append(list(Array('uint:5',[1,2])));result.append(z[-1])"
    )
    x = mojo.Array("uint:5", [1])
    x.extend([2, 3])
    actual = [x.tolist()]
    y = mojo.Array("uint:5", [1, 2])
    y[0] = 9
    actual.append(y.tolist())
    z = mojo.Array("uint:5", [1, 2, 3])
    actual.append(z[0:2].tolist())
    actual.append(list(mojo.Array("uint:5", [1, 2])))
    actual.append(z[-1])
    assert actual == expected


def test_array_trailing_byteswap_parity():
    expected = upstream(
        "result=[Array('uint:4',[1],trailing_bits='0b111').tolist(),"
        "Array('uint:4',[1],trailing_bits='0b111').trailing_bits.bin];"
        "x=Array('uint:16',[0x1122]);x.byteswap();result.append(x.tolist())"
    )
    actual = [
        mojo.Array("uint:4", [1], trailing_bits="0b111").tolist(),
        mojo.Array("uint:4", [1], trailing_bits="0b111").trailing_bits.bin,
    ]
    x = mojo.Array("uint:16", [0x1122])
    x.byteswap()
    actual.append(x.tolist())
    assert actual == expected


def test_dtype_bool_float_ue_parity():
    expected = upstream(
        "d=Dtype('bool');result=[[d.build(True).bin,d.parse(Bits('0b1')),d.bitlength]];"
        "e=Dtype('float:32');result.append([e.build(1.5).bin,e.parse(Bits(float=1.5,length=32))]);"
        "f=Dtype('ue');result.append([f.build(3).bin,f.parse(Bits(ue=3))])"
    )
    actual = []
    d = mojo.Dtype("bool")
    actual.append([d.build(True).bin, d.parse(mojo.Bits("0b1")), d.bitlength])
    e = mojo.Dtype("float:32")
    actual.append([e.build(1.5).bin, e.parse(mojo.Bits(float=1.5, length=32))])
    f = mojo.Dtype("ue")
    actual.append([f.build(3).bin, f.parse(mojo.Bits(ue=3))])
    assert actual == expected


def test_array_repr_parity():
    expected = upstream("result=[repr(Array('uint:5',[1,2]))]")
    actual = [repr(mojo.Array("uint:5", [1, 2]))]
    assert actual == expected


def test_bits_kwargs_parity():
    expected = upstream(
        "result=[Bits(uint=5,length=3).bin,Bits(uintbe=0x1234,length=16).uintbe,"
        "Bits(intle=-1234,length=16).intle,Bits(floatle=1.5,length=32).floatle,"
        "Bits(bytes=b'AB').bin,Bits(bits='0b101').bin,Bits(bool=False).bin,"
        "Bits(ue=5).bin,Bits(se=-3).bin,Bits(bytes=b'AB',offset=0,length=8).bin]"
    )
    actual = [
        mojo.Bits(uint=5, length=3).bin,
        mojo.Bits(uintbe=0x1234, length=16).uintbe,
        mojo.Bits(intle=-1234, length=16).intle,
        mojo.Bits(floatle=1.5, length=32).floatle,
        mojo.Bits(bytes=b"AB").bin, mojo.Bits(bits="0b101").bin,
        mojo.Bits(bool=False).bin, mojo.Bits(ue=5).bin, mojo.Bits(se=-3).bin,
        mojo.Bits(bytes=b"AB", offset=0, length=8).bin,
    ]
    assert actual == expected


def test_find_rfind_range_parity():
    expected = upstream(
        "result=[list(Bits('0b10101').find('0b101',start=2)),"
        "list(Bits('0b10101').findall('0b1',start=1,end=4)),"
        "list(Bits('0b10101').rfind('0b1',0,3)),"
        "list(Bits(b'AB').find('0x41',bytealigned=True)),"
        "list(Bits(b'AAAA').findall('0x41',bytealigned=True))]"
    )
    actual = [
        list(mojo.Bits("0b10101").find("0b101", start=2)),
        list(mojo.Bits("0b10101").findall("0b1", start=1, end=4)),
        list(mojo.Bits("0b10101").rfind("0b1", 0, 3)),
        list(mojo.Bits(b"AB").find("0x41", bytealigned=True)),
        list(mojo.Bits(b"AAAA").findall("0x41", bytealigned=True)),
    ]
    assert actual == expected


def test_mut_insert_edge_parity():
    expected = upstream(
        "x=BitArray('0b10');x.insert('0b1',0);result=[x.bin];"
        "y=BitArray('0b10');y.insert('0b1',2);result.append(y.bin);"
        "z=BitArray('0b10');z.insert('0b1',-1);result.append(z.bin)"
    )
    x = mojo.BitArray("0b10")
    x.insert("0b1", 0)
    actual = [x.bin]
    y = mojo.BitArray("0b10")
    y.insert("0b1", 2)
    actual.append(y.bin)
    z = mojo.BitArray("0b10")
    z.insert("0b1", -1)
    actual.append(z.bin)
    assert actual == expected


def test_mut_reverse_set_invert_edge_parity():
    expected = upstream(
        "x=BitArray('0b1011');x.reverse();result=[x.bin];"
        "y=BitArray();y.reverse();result.append(y.bin);"
        "z=BitArray('0b000');z.set(1,[0,2]);result.append(z.bin);"
        "a=BitArray('0b101');a.invert([0,2]);result.append(a.bin);"
        "b=BitArray('0b101');b.set(1);result.append(b.bin)"
    )
    x = mojo.BitArray("0b1011")
    x.reverse()
    actual = [x.bin]
    y = mojo.BitArray()
    y.reverse()
    actual.append(y.bin)
    z = mojo.BitArray("0b000")
    z.set(1, [0, 2])
    actual.append(z.bin)
    a = mojo.BitArray("0b101")
    a.invert([0, 2])
    actual.append(a.bin)
    b = mojo.BitArray("0b101")
    b.set(1)
    actual.append(b.bin)
    assert actual == expected


def test_mut_rol_ror_edge_parity():
    expected = upstream(
        "x=BitArray('0b100');x.rol(5);result=[x.bin];"
        "y=BitArray('0b100');y.ror(1);result.append(y.bin);"
        "z=BitArray('0b1011');z.rol(1,1,3);result.append(z.bin)"
    )
    x = mojo.BitArray("0b100")
    x.rol(5)
    actual = [x.bin]
    y = mojo.BitArray("0b100")
    y.ror(1)
    actual.append(y.bin)
    z = mojo.BitArray("0b1011")
    z.rol(1, 1, 3)
    actual.append(z.bin)
    assert actual == expected
