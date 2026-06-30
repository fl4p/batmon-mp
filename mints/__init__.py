"""

TODO:
- fix sharding (see below)
- use delta-coding or delta-delta-coding + zig-zag
- use variable length integer coding (varints)
    https://github.com/protocolbuffers/protobuf/blob/main/python/google/protobuf/internal/encoder.py
    https://github.com/fmoo/python-varint/blob/master/varint.py
     Simple-8b (https://www.tigerdata.com/blog/time-series-compression-algorithms-explained#Simple-8b)
     https://arxiv.org/abs/2101.08784
- see https://tdengine.com/compressing-time-series-data/
- https://github.com/michaeljclark/vf128

COMPRESSION: see mints/COMPRESSION.md for the full design, measurements, and
  conclusions (columnar/MTS1 shards ~-22.6%, the lossless entropy floor, the
  tamp-vs-deflate-vs-pcodec analysis, and the impedance-safe current de-noising).
  Short version: shipping codec is columnar + delta + zigzag + varint + tamp; the
  remaining lossless codec wins are incremental; codec micro-tweaks are exhausted;
  the DOWNSAMPLER (daq/downsample.py) is the only knob with order-of-magnitude
  headroom.

"""
import os
import struct
# from typing import BinaryIO

# A full littlefs raises OSError(28). MicroPython's errno module omits the
# ENOSPC *name* (it's not in the default MICROPY_PY_ERRNO_LIST), so referencing
# errno.ENOSPC would itself raise AttributeError inside our except handler
# on-device. The value 28 is stable across Linux/macOS/newlib/ESP-IDF.
ENOSPC = 28

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

    def __init__(self, name, dtype, default_val=0, monotonic=False):
        assert dtype in DTypes
        self.name = name
        self.dtype = dtype
        self.default_val = default_val
        self.monotonic = monotonic


class Store:

    @staticmethod
    def reject_corrupt_frames(df, soc_jump=4.0, temp_lo=-40.0, temp_hi=85.0):
        """Drop torn/garbled batmon frames using physical invariants only.

        Corruption shows up as a single frame where several channels are
        simultaneously implausible (e.g. current=+289 A while SoC drops 80->12->80 %
        and with no voltage/IR response). The reliable tell is SoC: battery_level is
        coulomb-counted, so it is physically smooth and cannot jump by more than
        `soc_jump` % from its local median in one sample. Current *magnitude* is never
        used, so genuine pulsed-load discharge spikes (which show a correlated voltage
        and cell-voltage sag) are preserved.

        Two-pass, gated on the batmon schema: pass 1 removes hard-corrupt frames
        (all-zero `soc2`, out-of-range `temp2`) so they cannot poison the rolling
        reference; pass 2 flags the SoC discontinuities on what remains. No-op (returns
        df unchanged) unless both `soc2` and `temp2` columns are present.
        """
        if not {'soc2', 'temp2'}.issubset(df.columns):
            return df
        import numpy as np
        import pandas
        soc2 = df['soc2'].to_numpy()
        temp = df['temp2'].to_numpy() / 2.0 - 40.0
        # df's index ('time') is non-unique, so work with a positional mask.
        keep = (soc2 != 0) & (temp >= temp_lo) & (temp <= temp_hi)
        kept_pos = np.flatnonzero(keep)
        soc = pandas.Series((soc2[kept_pos]) / 2.0)
        med = soc.rolling(7, center=True, min_periods=1).median()
        smooth = (soc - med).abs().to_numpy() <= soc_jump
        keep[kept_pos[~smooth]] = False
        return df[keep]

    @staticmethod
    def read_file_to_pandas(file_path, reject_outliers=False):
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
        df = pandas.DataFrame(rows, columns=cols).set_index(cols[0])
        # gate: opt-in so existing compression/export callers see raw frames
        if reject_outliers:
            df = Store.reject_corrupt_frames(df)
        return df

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
        self._fh: BinaryIO | None = None
        names = ','.join(c.name for c in columns)
        self._fn = f'{name}-{names}-{self._frame_fmt}.bin'
        try:
            self._fsize = os.stat(self._fn)[6]
        except OSError:
            self._fsize = 0

    def get_shard_files(self):
        files = os.listdir('.')
        bn = self._fn[:-3]
        return [f for f in files if f.startswith(bn) and f.endswith('.tamp')]

    def _shard_index(self, fn):
        # fn is '{prefix}NN.tamp' where prefix == self._fn[:-3]; NN parsed numerically
        bn = self._fn[:-3]
        return int(fn[len(bn):-len('.tamp')])

    def _next_shard_index(self):
        shards = self.get_shard_files()
        if not shards:
            return 0
        return max(self._shard_index(f) for f in shards) + 1

    def _prune_oldest_shard(self):
        # delete the lowest-index .tamp shard; return False if there are none
        shards = self.get_shard_files()
        if not shards:
            return False
        oldest = min(shards, key=self._shard_index)
        print('store pruning oldest shard', oldest)
        os.unlink(oldest)
        return True

    def compress_data_file(self):
        # create a new compressed shard of the current data file
        fsize = os.stat(self._fn)[6]
        assert fsize >= 1024 * 16, "data file too small to compress " + str(fsize)

        # monotonic: always one past the highest existing index, so a pruned
        # (lower) index is never reused even after old shards are deleted
        idx = self._next_shard_index()
        tamp_fn = self._fn[:-3] + '%02i.tamp' % idx
        tmp_fn = tamp_fn + '.tmp'

        print('store creating new shard', tamp_fn, 'fsize', fsize)

        if self._fh:
            self._fh.close()
            self._fh = None

        # struct.Struct is absent from generic MicroPython builds; use the
        # module-level struct.unpack (as ShardStoreReader already does).
        fmt = self._frame_fmt
        read_frame = lambda b: struct.unpack(fmt, b)
        from mints.shard import ShardStore

        while True:
            shard = None
            try:
                if hasattr(ShardStore, 'write_file'):
                    ShardStore.write_file(self.columns, self._fn, fmt, self._frame_size, tmp_fn)
                else:
                    shard = ShardStore(self.columns, tmp_fn)
                    with open(self._fn, 'rb') as fh:
                        while len(frame := fh.read(self._frame_size)) == self._frame_size:
                            shard.add_sample(read_frame(frame))
                    shard.close()
                    shard = None
                os.rename(tmp_fn, tamp_fn)
                break
            except Exception as e:
                # Drop the partial/zero-byte in-progress shard on ANY failure so a
                # crashed attempt can't leak an orphan .tmp -- which both wastes
                # flash and is invisible to pruning (get_shard_files matches only
                # .tamp). This is what left a 0-byte ...00.tamp.tmp in the field.
                if shard is not None:
                    try:
                        shard.close()
                    except Exception:
                        pass
                try:
                    os.unlink(tmp_fn)
                except OSError:
                    pass
                # flash full: free the oldest shard and retry; idx is unchanged
                # because pruning only removes a lower index. For anything else
                # (e.g. MemoryError), or a full disk with nothing left to prune,
                # re-raise -- flush() treats compaction as best-effort and keeps
                # the hot file for the next attempt.
                if getattr(e, 'errno', None) != ENOSPC or not self._prune_oldest_shard():
                    raise

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
                if not isinstance(v, int):
                    if v != v:  # type-safe nan check
                        v = col.default_val
                    v = int(v)
                # Clamp to the column's integer range so struct.pack can never
                # overflow. Out-of-range raises struct.error on CPython but
                # silently wraps (corrupting the value) on MicroPython, so the
                # store must guard it rather than relying on the producer.
                bits = int(col.dtype[1:])
                if t == 'u':
                    lo, hi = 0, (1 << bits) - 1
                else:
                    lo, hi = -(1 << (bits - 1)), (1 << (bits - 1)) - 1
                if v < lo:
                    v = lo
                elif v > hi:
                    v = hi
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

        n = self._write_buf_pos
        pos = self._fsize  # intended append offset == current end of file
        while True:
            try:
                # seek(pos) before each attempt makes a retry overwrite any
                # partial bytes from a failed write (fixed-width frames)
                fh.seek(pos)
                written = fh.write(self._write_buf[:n])  # TODO use memoryview
                fh.flush()  # in case we lose power
                break
            except OSError as e:
                # flash full: free the oldest shard and retry the write; if
                # nothing is left to prune (or a different error), re-raise.
                if getattr(e, 'errno', None) != ENOSPC or not self._prune_oldest_shard():
                    raise
        # os.fsync()
        self._fsize = pos + written
        self._write_buf_pos = 0

        if sharding:
            if self._fsize > (1024 * 256):
                # Compaction is a best-effort background optimisation, not part of
                # the write path. If it fails (MemoryError under BLE heap pressure,
                # or a full disk with nothing to prune) we log and keep the hot
                # file -- the next flush retries. It must NOT propagate: a transient
                # compaction error escaping add_sample is what tore down the BMS
                # link in the field (it bubbled past batmon's `except OSError`).
                try:
                    self.compress_data_file()
                except Exception as e:
                    print('store compaction failed, will retry:', e)

    def close(self):
        self.flush()
        self._fh.close()
