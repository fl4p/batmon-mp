import io
import random
import struct

import numpy as np


def _UnsignedVarintEncoder():
    pack_int2byte = struct.Struct('>B').pack

    def EncodeSignedVarint(write, value):
        bits = value & 0x7f
        value >>= 7
        while value:
            write(pack_int2byte(0x80 | bits))
            bits = value & 0x7f
            value >>= 7
        return write(pack_int2byte(bits))

    return EncodeSignedVarint


UnsignedVarintEncode = _UnsignedVarintEncoder()


def _UnsignedVarintEncoderBuf():
    pack_int2byte = struct.Struct('>B').pack

    def EncodeSignedVarint(buf, pos, value):
        bits = value & 0x7f
        value >>= 7
        while value:
            buf[pos] = pack_int2byte(0x80 | bits)[0]
            pos += 1
            bits = value & 0x7f
            value >>= 7
        buf[pos] = pack_int2byte(bits)[0]
        return pos

    return EncodeSignedVarint


UnsignedVarintEncoderBuf = _UnsignedVarintEncoderBuf()

random.seed(1)
ints = [random.randint(0, 100) for _ in range(10000)]
ints_np = np.array(ints)

import pyximport  # cython

pyximport.install(
    setup_args={"include_dirs": np.get_include()},
    reload_support=True,
    language_level=3
)

import coding

bio = io.BytesIO()


def _write(buf: memoryview):
    bio.write(buf)


coding.varint_encode(ints_np, _write)

bio.seek(0)
cython_bytes = bio.read(-1)
print('bio len', len(cython_bytes))

cython_dec = coding.varint_decode_unsigned(cython_bytes, (1 << 64) - 1, int)

assert list(cython_dec) == list(ints_np)


def varintLen():
    buf = io.BytesIO()
    write = buf.write
    for i in ints:
        UnsignedVarintEncode(write, i)
    buf.seek(0)
    bytes = buf.read(-1)
    assert bytes == cython_bytes
    return len(bytes)


n = varintLen()
print('total varintlen', n)

import timeit

try:
    from lz4.block import compress as lz4_compress, decompress as lz4_decompress

    lz4_compressHC = lambda _str: lz4_compress(_str, mode='high_compression')
except ImportError as e:
    from lz4 import compress as lz4_compress, compressHC as lz4_compressHC, decompress as lz4_decompress

setting = """
import random, io


def writeToIO():
    buf = io.BytesIO()
    write = buf.write        
    for i in ints:
        UnsignedVarintEncode(write, i)
        
def writeToBuf():
    buf = bytearray(n)
    pos = 0      
    for i in ints:
        pos = UnsignedVarintEncoderBuf(buf, pos, i)

def cythonToIO():
    buf = io.BytesIO()
    coding.varint_encode(ints_np, buf.write)    
        
def arcticLz4():
    lz4_compressHC(ints_np.tobytes())
    
def varintLz4():
    buf = io.BytesIO()
    coding.varint_encode(ints_np, buf.write)    
    buf.seek(0)
    lz4_compressHC(buf.read(-1))
    
def cythonDecode():
    coding.varint_decode_unsigned(cython_bytes, (1 << 64) - 1, int )

"""

for fn in (
        #'writeToIO',
        # 'writeToBuf', # a bit slower
        'cythonToIO',
        #'arcticLz4',
        'varintLz4',
        'cythonDecode',
):
    ni = 1000
    t = timeit.timeit(fn + '()', setup=setting, number=ni, globals=globals())
    print(fn, ': t/it=', round(t / ni * 1e6, 0), 'us ', round(n / 1e3 / t, 2), 'kB/s')
