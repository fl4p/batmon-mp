import os
import time

from store import Store

funcs = {}

import zlib

funcs['zlib_w10'] = lambda d: zlib.compress(d, wbits=10)
funcs['zlib_w15'] = lambda d: zlib.compress(d, wbits=15)

import lzma

funcs['lzma_fXZ'] = lambda d: lzma.compress(d, format=lzma.FORMAT_XZ)
funcs['lzma_fA'] = lambda d: lzma.compress(d, format=lzma.FORMAT_ALONE)
funcs['lzma_pEX'] = lambda d: lzma.compress(d, preset=lzma.PRESET_EXTREME)


import brotli
funcs['brotli_q11'] = lambda d: brotli.compress(d, quality=11)
#funcs['brotli_q11'] = lambda d: brotli.compress(d, quality=11)

import snappy
funcs['snappy'] = lambda d: snappy.compress(d)

try:
    # https://github.com/BrianPugh/tamp
    import tamp

    funcs['tamp_w8'] = lambda d: tamp.compress(d, window=8)
    funcs['tamp_w9'] = lambda d: tamp.compress(d, window=9)
    funcs['tamp_w10'] = lambda d: tamp.compress(d, window=10)
    funcs['tamp_w11'] = lambda d: tamp.compress(d, window=11)
    funcs['tamp_w15'] = lambda d: tamp.compress(d, window=15)
except ImportError:
    print("tamp module not available")
    pass



def compress_file(input_file, window=8, buf_size=128):
    import tamp
    t0 = time.time()
    with tamp.open("test.tamp", "wb", window=window) as dst:
        with open(input_file, "rb") as src:
            while len(b := src.read(buf_size)) > 0:
                dst.write(b)
    t1 = time.time()
    print('compress ratio', round(os.stat("test.tamp")[6] / os.stat(input_file)[6], 2), 'took', round(t1 - t0, 2),
          'sec')


def decompress_file(input_file, out_file, buf_size=128, max_len=0):
    import tamp
    t0 = time.time()
    n = 0
    with tamp.open(input_file, "rb") as src:
        # print('src.w_bits=', src.w_bits)
        with open(out_file, "wb") as dst:
            while len(b := src.read(buf_size)) > 0:
                n += len(b)
                dst.write(b)  # THIS is broken on macos!!
                if max_len and n >= max_len:
                    print('Reached max_len', n)
                    break
                time.sleep(0.01)
    t1 = time.time()
    print('decompress ratio', round(os.stat(out_file)[6] / os.stat(input_file)[6], 2), 'took', round(t1 - t0, 2), 'sec')


inp_file = '../dl/jk-pak01-time,voltage,current,temp2,soc2,cell_min,cell_max-HeeBBHH.bin'
# inp_file = 'jk-pak01-time,voltage,current,temp2,soc2,cell_min,cell_max-HeeBBHH.bin'
# inp_file = 'conn.py'
compress_file(inp_file)
decompress_file("test.tamp", "test.bin", buf_size=1024 * 4, max_len=os.stat(inp_file).st_size)
assert open('test.bin', 'rb').read()[:os.stat(inp_file).st_size] == open(inp_file, 'rb').read()

# compress_file('jk-pak01-time,voltage,current,temp2,soc2,cell_min,cell_max-HeeBBHH.bin')

with open(inp_file, 'rb') as f:
    dat = f.read(-1)

print('input len', len(dat))



for name, func in funcs.items():
    t0 = time.perf_counter()
    c = func(dat)
    dt = time.perf_counter() - t0
    print('%12s' % name, round(len(c) / len(dat), 5), 'ticks=', round(dt, 6) )



import io
buf = io.BytesIO()
Store.read_file_to_pandas(inp_file).to_parquet(buf, engine='pyarrow', compression='snappy')
#buf.seek(0)
print('pyarrow', buf.tell()/len(dat))