"""

TODO:
- delete old shards if disk is full (notice by OSError)
- fix sharding (see below)
- use delta-coding or delta-delta-coding + zig-zag
- use variable length integer coding (varints)
    https://github.com/protocolbuffers/protobuf/blob/main/python/google/protobuf/internal/encoder.py
    https://github.com/fmoo/python-varint/blob/master/varint.py
     Simple-8b (https://www.tigerdata.com/blog/time-series-compression-algorithms-explained#Simple-8b)
     https://arxiv.org/abs/2101.08784
- see https://tdengine.com/compressing-time-series-data/

"""
import math
import os
import struct
from typing import BinaryIO

DTypes = dict(
    # https://docs.python.org/3/library/struct.html#format-characters
    i8='b',
    u8='B',
    i16='h',
    u16='H',
    i32='i',
    u32='I',
    f64='d',
    f32='f',
    f16='e'
)


def util_to_hex_str(ba):
    return ' '.join(f'{x:02x}' for x in ba)


def file_exists(path: str) -> bool:
    try:
        os.stat(path)
        return True
    except OSError:
        return False


class Col:

    def __init__(self, name, dtype, default_val=0):
        assert dtype in DTypes
        self.name = name
        self.dtype = dtype
        self.default_val = default_val


def compress_file(input_file, output_file, window=8, buf_size=128):
    import tamp
    import time
    t0 = time.time()
    bw = 0
    with tamp.open(output_file, "wb", window=window) as dst:
        with open(input_file, "rb") as src:
            while len(b := src.read(buf_size)) > 0:
                bw += dst.write(b)
    t1 = time.time()
    # assert bw == os.stat(output_file)[6]
    inp_size = os.stat(input_file)[6]
    print('ratio', round(os.stat(output_file)[6] / inp_size, 2), 'took', round(t1 - t0, 2), 'sec',
          round(inp_size / (t1 - t0) * 1e-3, 2), 'KB/s')
    return bw


class Store:

    @staticmethod
    def read_file_to_pandas(file_path):
        bn = file_path.replace('\\', '/').split('/')[-1].split('.')[-2].split('-')
        assert len(bn) >= 3
        name = '-'.join(bn[:-2])
        col_names, fmt = bn[-2:]
        frame_size = struct.calcsize(fmt)
        rows = []
        t = 0
        t_off = 0
        with open(file_path, 'rb') as fh:
            while len(frame := fh.read(frame_size)) == frame_size:
                if set(frame) == {0}:
                    continue
                row = list(struct.unpack(fmt, frame))
                row.append(row[0])  # keep the original index value
                if row[0] + t_off < t:
                    t_off = t - row[0] + 1
                row[0] += t_off
                t = row[0]
                rows.append(row)
        import pandas
        cols = col_names.split(',')
        cols.append('idx')  # original index value
        return pandas.DataFrame(rows, columns=cols).set_index(cols[0])

    def __init__(self, name, columns: list[Col], buf_num_frames=None):
        FLASH_PAGE_SIZE = 256

        self.column_names = set(c.name for c in columns)
        assert '-' not in str(self.column_names)
        assert (len(self.column_names) == len(columns))
        self.columns = columns
        self._frame_fmt = ''.join(DTypes[c.dtype] for c in columns)
        self._frame_size = len(struct.pack(self._frame_fmt, *bytearray(len(columns))))  # struct.calcsize( TODO
        if buf_num_frames is None:
            buf_num_frames = int(FLASH_PAGE_SIZE / self._frame_size) - 1

        self._write_buf = bytearray(self._frame_size * buf_num_frames)
        self._write_buf_pos = 0

        print('frame fmt', self._frame_fmt, 'len', self._frame_size, 'buf_num_frames', buf_num_frames)
        self._fh: BinaryIO = None
        names = ','.join(c.name for c in columns)
        self._fn = f'{name}-{names}-{self._frame_fmt}.bin'
        try:
            self._fsize = os.stat(self._fn)[6]
        except OSError:
            self._fsize = 0

    def compress_data_file(self):
        # create a new compressed shard of the current data file
        fsize = os.stat(self._fn)[6]
        assert fsize >= 1024 * 16, "data file too small to compress " + str(fsize)

        # TODO start from the top as old shards might have been deleted
        # instead of str(i) use the index, monotic, need to remeber it
        i = 0
        while file_exists(tamp_fn := self._fn[:-3] + '%02i.tamp' % i):
            i += 1

        print('store creating new shard', tamp_fn, 'fsize', fsize)

        if self._fh:
            self._fh.close()
            self._fh = None

        compress_file(self._fn, tamp_fn + '.tmp', window=8)
        os.rename(tamp_fn + '.tmp', tamp_fn)
        os.unlink(self._fn)
        self._fsize = 0

    def open(self):
        fn = self._fn

        try:
            fsize = os.stat(self._fn)[6]
        except OSError:
            fsize = 0

        self._fsize = fsize

        # because we want to read the last row don't use mode 'a+b' here
        # instead we seek to the file end after opening
        self._fh = open(fn, 'r+b' if fsize else 'w+b')  # https://stackoverflow.com/a/58925279/2950527

        print('store opened ', self._fn, 'fsize=', fsize, 'with', fsize / self._frame_size, 'rows')

        pad = fsize % self._frame_size
        if pad != 0:
            print('file size is not a multiple of frame size, padding..', fsize, self._frame_size)
            self._fh.seek(fsize)
            self._fh.write(b'\x00' * pad)
            self._fh.flush()
        else:
            if fsize >= self._frame_size:
                print('seeking to end', fsize - self._frame_size)
                self._fh.seek(fsize - self._frame_size)
                buf = self._fh.read(self._frame_size)
                last_row = struct.unpack(self._frame_fmt, buf)
                print('last row', buf, last_row)
            self._fh.seek(fsize)

    def add_sample(self, row: dict):
        for r in row.keys():
            assert r in self.column_names

        def _ensure_dtype(v, col):
            if v is None:
                v = col.default_val
            t = col.dtype[0]
            if t == 'i' or t == 'u':
                assert t == 'i' or v >= 0
                if not isinstance(v, int):
                    if v != v:  # type-safe nan check
                        v = col.default_val
                    v = int(v)
            return v

        vals = (_ensure_dtype(row.get(col.name), col) for col in self.columns)
        try:
            frame = struct.pack(self._frame_fmt, *vals)
            # res = struct.unpack(self._frame_fmt, frame)
            # assert max(abs((vals[i] - res[i]) / (abs(vals[i])+1e-6)) for i in range(0, len(vals))) < 0.1, (vals, res)
        except TypeError as e:
            vals = list(_ensure_dtype(row.get(col.name), col) for col in self.columns)
            print(e, repr(vals), self._frame_fmt)
            raise

        assert (len(frame) == self._frame_size)
        self._write_buf[self._write_buf_pos:self._write_buf_pos + self._frame_size] = frame
        self._write_buf_pos += self._frame_size

        if self._write_buf_pos == len(self._write_buf):
            self.flush(sharding=True)
        else:
            assert self._write_buf_pos < len(self._write_buf)

    def read(self):
        if self._fh is None:
            self.open()
        else:
            self._fh.flush()
        pos = self._fh.tell()
        self._fh.seek(0)
        while len(frame := self._fh.read(self._frame_size)) == self._frame_size:
            print(struct.unpack(self._frame_fmt, frame))
        self._fh.seek(pos)

    def flush(self, sharding=False):
        fh = self._fh
        if fh is None:
            if self._write_buf_pos == 0:
                return
            self.open()
            fh = self._fh
        # print('write flush', self._write_buf_pos, self._write_buf[:self._write_buf_pos])
        self._fsize += fh.write(self._write_buf[:self._write_buf_pos])  # TODO use memoryview
        fh.flush()  # in case we loose power
        # os.fsync()
        self._write_buf_pos = 0

        if sharding:
            if self._fsize > (1024 * 256):
                self.compress_data_file()

    def close(self):
        self.flush()
        self._fh.close()


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


if __name__ == '__main__':
    test_pack()
    test_store()
"""
from store import Store, Col
s = Store([Col('time', 'i16'), Col('voltage', 'f16'), ])
s.add_sample(dict(time=12.1, voltage=50.4))
"""
