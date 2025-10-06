import struct

from mints import Col, DTypes
from mints.coding import ZigZagEncode, SignedVarintEncode, UnsignedVarintEncode, SignedVarintDecode, ZigZagDecode, \
    UnsignedVarintDecode


class ShardStoreReader:
    def __init__(self, columns: list[Col], file_path):
        self.columns = columns

        import tamp
        self._fh = tamp.open(file_path, "rb")

    def read_all(self):
        # read = lambda b: self._fh.read(b)
        cols = self.columns

        row_prev = [0] * len(cols)

        buf = self._fh.read(-1)
        bp = 0

        rows = []
        while bp < len(buf):
            row = dict()
            for i in range(len(cols)):
                col = cols[i]
                if not is_varint_type(col.dtype):
                    s = struct.calcsize(DTypes[col.dtype])
                    row[col.name] = struct.unpack(DTypes[col.dtype], buf[bp:bp + s])[0]  # ordinary pack
                    bp += s
                else:
                    if col.monotonic:
                        d, bp = UnsignedVarintDecode(buf, bp)
                    else:
                        d, bp = SignedVarintDecode(buf, bp)
                        d = ZigZagDecode(d)
                    row[col.name] = row_prev[i] + d
                    row_prev[i] = row[col.name]
            rows.append(row)
        return rows

    def close(self):
        self._fh.close()


class ShardStore:
    def __init__(self, columns: list[Col], output_file, tamp_window=8):
        self.columns = columns
        self._row_prev = [0] * len(columns)
        import tamp
        self._fh = tamp.open(output_file, "wb", window=tamp_window)

    def add_sample(self, row: tuple):
        write = lambda b: self._fh.write(b)
        n_written = 0

        cols = self.columns
        row_prev = self._row_prev

        assert len(row) == len(cols)
        for i in range(len(cols)):
            col = cols[i]
            if not is_varint_type(col.dtype):
                n_written += write(struct.pack(DTypes[col.dtype], row[i]))  # ordinary pack
            else:
                d = row[i] - row_prev[i]
                row_prev[i] = row[i]
                if col.monotonic:
                    if d < 0:
                        row_prev[i] += -d + 1
                        d = 1
                    n_written += UnsignedVarintEncode(write, d)
                else:
                    d = ZigZagEncode(d)
                    n_written += SignedVarintEncode(write, d)

    def close(self):
        self._fh.close()


def is_varint_type(dtype):
    if dtype[0] == 'f':  # or dtype == 'i8' or dtype == 'u8':
        return False
    return True
