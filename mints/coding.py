import os
import struct
import time

VARINT_MAX_BITS = 32


def ZigZagEncode(value: int):
    """
    Encode signed integers so that they can be stored more efficiently using varint coding.
    :param value:
    :return:
    """
    if value >= 0:
        return value << 1
    return (value << 1) ^ -1


def ZigZagDecode(value: int):
    if not value & 0x1:
        return value >> 1
    return (value >> 1) ^ -1


def _VarintEncoder(signed=True):
    pack_int2byte = struct.Struct('>B').pack

    def EncodeSignedVarint(write, value):
        if signed and value < 0:
            value += (1 << VARINT_MAX_BITS)
        bits = value & 0x7f
        value >>= 7
        while value:
            write(pack_int2byte(0x80 | bits))
            bits = value & 0x7f
            value >>= 7
        return write(pack_int2byte(bits))

    return EncodeSignedVarint


def _SignedVarintDecoder(bits, result_type):
    signbit = 1 << (bits - 1)
    mask = (1 << bits) - 1

    def DecodeVarint(buffer, pos):
        result = 0
        shift = 0
        while 1:
            b = buffer[pos]
            result |= ((b & 0x7f) << shift)
            pos += 1
            if not (b & 0x80):
                result &= mask
                result = (result ^ signbit) - signbit
                result = result_type(result)
                return (result, pos)
            shift += 7
            if shift >= VARINT_MAX_BITS:
                raise ValueError('Too many bytes when decoding varint.')

    return DecodeVarint


SignedVarintEncode = _VarintEncoder(signed=True)
SignedVarintDecode = _SignedVarintDecoder(VARINT_MAX_BITS, int)


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
    # fsize = os.stat(output_file)[6]
    # TODO fix
    # assert bw == fsize-19 or bw == fsize-18, (bw, fsize, fsize-bw)
    inp_size = os.stat(input_file)[6]
    print('ratio', round(os.stat(output_file)[6] / inp_size, 2), 'took', round(t1 - t0, 2), 'sec',
          round(inp_size / (t1 - t0) * 1e-3, 2), 'KB/s')
    return bw


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
    # print('decompress ratio', round(os.stat(out_file)[6] / os.stat(input_file)[6], 2), 'took', round(t1 - t0, 2), 'sec')
