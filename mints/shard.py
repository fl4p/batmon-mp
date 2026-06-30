import struct

from mints import Col, DTypes
from mints.coding import ZigZagEncode, SignedVarintEncode, UnsignedVarintEncode, SignedVarintDecode, ZigZagDecode, \
    UnsignedVarintDecode

TAMP_WINDOW = 12
COLUMNAR_MAGIC = b'MTS1'


def _pack_funcs(columns):
    # struct.Struct is absent from generic MicroPython builds; build per-column
    # pack closures over the module-level struct.pack instead.
    return [(lambda fmt: lambda v: struct.pack(fmt, v))(DTypes[col.dtype])
            for col in columns]


def _write_encoded_value(write, col, pack_func, value, prev):
    if not is_varint_type(col.dtype):
        return prev, write(pack_func(value))

    d = value - prev
    prev = value
    if col.monotonic:
        if d < 0:
            # Preserve the existing shard semantics for wrapping counters:
            # readers reconstruct the next monotonic value, not the wrapped raw.
            prev = value - 1
            d = 1
        return prev, UnsignedVarintEncode(write, d)

    d = ZigZagEncode(d)
    return prev, SignedVarintEncode(write, d)


def _read_encoded_value(buf, bp, col, prev):
    if not is_varint_type(col.dtype):
        s = struct.calcsize(DTypes[col.dtype])
        return struct.unpack(DTypes[col.dtype], buf[bp:bp + s])[0], bp + s, prev

    if col.monotonic:
        d, bp = UnsignedVarintDecode(buf, bp)
    else:
        d, bp = SignedVarintDecode(buf, bp)
        d = ZigZagDecode(d)
    value = prev + d
    return value, bp, value


class ShardStoreReader:
    def __init__(self, columns: list[Col], file_path):
        self.columns = columns

        import tamp
        self._fh = tamp.open(file_path, "rb")

    def read_all(self):
        # read = lambda b: self._fh.read(b)
        buf = self._fh.read(-1)
        if buf[:len(COLUMNAR_MAGIC)] == COLUMNAR_MAGIC:
            return self._read_all_columnar(buf, len(COLUMNAR_MAGIC))
        return self._read_all_row_major(buf)

    def _read_all_row_major(self, buf):
        cols = self.columns
        row_prev = [0] * len(cols)
        bp = 0
        rows = []
        while bp < len(buf):
            row = dict()
            for i in range(len(cols)):
                col = cols[i]
                row[col.name], bp, row_prev[i] = _read_encoded_value(buf, bp, col, row_prev[i])
            rows.append(row)
        return rows

    def _read_all_columnar(self, buf, bp):
        cols = self.columns
        row_count, bp = UnsignedVarintDecode(buf, bp)
        rows = [dict() for _ in range(row_count)]

        for i in range(len(cols)):
            col = cols[i]
            prev = 0
            for j in range(row_count):
                value, bp, prev = _read_encoded_value(buf, bp, col, prev)
                rows[j][col.name] = value

        if bp != len(buf):
            raise ValueError('trailing bytes in columnar shard')
        return rows

    def close(self):
        self._fh.close()


class ShardStore:
    def __init__(self, columns: list[Col], output_file, tamp_window=TAMP_WINDOW):
        self.columns = columns
        self._row_prev = [0] * len(columns)
        import tamp
        self._fh = tamp.open(output_file, "wb", window=tamp_window)

        self._pack_funcs = _pack_funcs(columns)

    @classmethod
    def write_file(cls, columns: list[Col], input_file, frame_fmt, frame_size, output_file, tamp_window=TAMP_WINDOW):
        """Write a column-major shard from a fixed-width hot data file.

        Current BMS data compresses materially better when each column's
        delta/varint stream is contiguous before the tamp LZ pass. This helper
        keeps RAM bounded by scanning the source file once per column.
        """
        import os
        import tamp

        row_count = os.stat(input_file)[6] // frame_size
        pack_funcs = _pack_funcs(columns)
        unpack_frame = lambda b: struct.unpack(frame_fmt, b)

        with tamp.open(output_file, "wb", window=tamp_window) as fh:
            write = fh.write
            write(COLUMNAR_MAGIC)
            UnsignedVarintEncode(write, row_count)

            for i in range(len(columns)):
                col = columns[i]
                prev = 0
                with open(input_file, 'rb') as src:
                    for _ in range(row_count):
                        frame = src.read(frame_size)
                        value = unpack_frame(frame)[i]
                        prev, _ = _write_encoded_value(write, col, pack_funcs[i], value, prev)

    def add_sample(self, row: tuple):
        # write = lambda b: self._fh.write(b)
        write = self._fh.write
        n_written = 0

        cols = self.columns
        pack_funcs = self._pack_funcs
        row_prev = self._row_prev

        assert len(row) == len(cols)

        for i in range(len(cols)):
            col = cols[i]
            row_prev[i], n = _write_encoded_value(write, col, pack_funcs[i], row[i], row_prev[i])
            n_written += n

    def close(self):
        self._fh.close()


def is_varint_type(dtype):
    if dtype[0] == 'f':  # or dtype == 'i8' or dtype == 'u8':
        return False
    return True
