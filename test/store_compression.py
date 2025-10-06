import struct
from io import BytesIO

from store import Store

from mints.coding import ZigZagDecode, ZigZagEncode


def main():
    inp_file = '../dl/jk-pak01-time,voltage,current,temp2,soc2,cell_min,cell_max-HeeBBHH.bin'

    df = Store.read_file_to_pandas(inp_file)
    df = df.reset_index()
    df['time'] = df['idx']
    df = df.drop(columns=['idx'])

    fmt = 'HeeBBHH'

    for ci in range(len(df.columns)):
        col = df.columns[ci]
        buf = bytearray()
        for i in range(df.shape[0]):
            buf += struct.pack(fmt[ci], df.iloc[i, ci])

        # bin_file = f'test_col_{col}.bin'
        # with open(bin_file, 'wb') as f:
        #    f.write(buf)

        comp_size = len(compress_bytes(buf))
        # comp_size = compress_file(f'test_col_{col}.bin', '_test.tamp')
        print('column', col, 'has ', len(buf), ' bytes', 'compressed to', comp_size, '(',
              round(100 * comp_size / len(buf)),
              '%')

        # delta coding
        if df.dtypes.iloc[ci].name.startswith('int'):
            buf2 = BytesIO()
            l = 0
            deltas = []
            w = 0
            for i in range(df.shape[0]):
                v = df.iloc[i, ci]
                deltas.append(v - l)
                d = ZigZagEncode(v - l)
                w+=_EncodeSignedVarint(buf2.write, d)
                # buf += struct.pack(fmt[ci], v - l)
                l = v
            buf2.seek(0)
            buf2 = buf2.read()
            n = len(buf2)
            #assert w == n, (w,n)
            i = 0
            deltas.reverse()
            while i < n:
                r, i = _DecodeSignedVarint(buf2, i)
                d = ZigZagDecode(r)
                assert d == deltas.pop()
            print('   ', 'delta+zigzag+varint', n, '(', round(100 * n / len(buf)), '%', '+tamp',
                  round(100 * len(compress_bytes(buf2)) / len(buf)), '%')
            print(buf2[:20])

        print(list(df.iloc[0:20, ci]))







def compress_bytes(inp: bytearray, window=8, buf_size=128):
    import tamp
    import time
    t0 = time.time()
    bw = 0
    dst_bytes = BytesIO()
    src = BytesIO(inp)
    with tamp.open(dst_bytes, "wb", window=window) as dst:
        while len(b := src.read(buf_size)) > 0:
            bw += dst.write(b)
    dst_bytes.seek(0)
    return dst_bytes.read(-1)


main()
