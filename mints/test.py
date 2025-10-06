import math
import os
import random
import struct

from mints import Store, Col
from mints.coding import ZigZagEncode, ZigZagDecode


def test_store():
    store = Store('test', [
        Col('time', 'i16'),
        Col('voltage', 'f16'),
        Col('current', 'f16'),
        Col('soc2', 'u8'),
        Col('cell_min', 'u16'),
        Col('cell_max', 'u16'),
    ])

    for i in range(0, 2000):
        store.add_sample(
            dict(time=i, voltage=12 + math.sin(i / 5), current=math.sin(i / 5), soc2=abs(math.sin(i / 50)) * 100 * 2,
                 cell_min=3340, cell_max=5446))

    # store.compress_data_file()
    # store.read()

    for _ in range(0, 3):
        for i in range(0, 20000):
            store.add_sample(
                dict(time=i, voltage=12 + math.sin(i / 5), current=math.sin(i / 5),
                     soc2=abs(math.sin(i / 50)) * 100 * 2,
                     cell_min=3340, cell_max=5446))


def test_pack():
    fmt = 'heeBHH'
    assert struct.calcsize(fmt) == len(struct.pack(fmt, *bytearray(len(fmt))))

    inp = [12, 53.4563, -12.0345]
    res = struct.unpack('hee', struct.pack('hee', *inp))
    assert max(abs((inp[i] - res[i]) / inp[i]) for i in range(0, len(inp))) < 0.1, (inp, res)

    for i in range(1, 1000):
        inp = [i, 48 + i / 1000, 6 * i / 1000, 25 + int(i / 1000 * 20), 25 + int(i / 1000 * 40), 2000 + i, 2033 + i]
        res = struct.unpack('HeeBBHH', struct.pack('HeeBBHH', *inp))
        assert max(abs((inp[i] - res[i]) / inp[i]) for i in range(0, len(inp))) < 0.1, (inp, res)

def test_zigzag_coding():
    ints = [random.randint(-2**31, 2**31-1) for _ in range(0, 2000)]
    for i in ints:
        assert ZigZagDecode(ZigZagEncode(i)) == i

def test_compress_file():
    from mints.coding import compress_file, decompress_file

    for n in [1, 2, 3, 4, 5, 6, 7, 8, random.randint(1, 10000)]:
        l = list(random.randint(0, 255) for _ in range(n))
        b = bytes(l)
        fn = '_test_compress_file.bin'
        with open(fn, 'wb') as f:
            f.write(b)
        compress_file(fn, fn + '.tamp')
        decompress_file(fn + '.tamp', fn + '2', max_len=n)
        with open(fn + '2', 'rb') as f:
            assert_array_equal(b, f.read()[:len(b)])
    os.unlink('_test_compress_file.bin')
    os.unlink('_test_compress_file.bin.tamp')
    os.unlink('_test_compress_file.bin2')


def assert_array_equal(a, b):
    import numpy
    numpy.testing.assert_array_equal(a, b)
    if len(b) > len(a):
        print(len(b) - len(a), 'overhang:', b[len(a):])
    assert len(a) == len(b), (len(a), len(b))
    assert bytes(a) == bytes(b)


if __name__ == '__main__':
    # test_pack()
    test_zigzag_coding()
    #test_compress_file()
    # test_store()

"""
from store import Store, Col
s = Store([Col('time', 'i16'), Col('voltage', 'f16'), ])
s.add_sample(dict(time=12.1, voltage=50.4))
"""
