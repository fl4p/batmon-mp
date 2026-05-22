"""
Validate the mints shard auto-prune against a device's REAL flash littlefs by
actually FILLING the flash until ENOSPC, then watching the store recover.

WARNING — destructive while it runs: it fills the entire flash filesystem to
ENOSPC (in a /prunetest subdir) and removes everything afterwards, restoring the
exact starting free space. Run ONLY on a board with no data you care about. It is
slow (writes the whole partition once) and is NOT a pytest/CI test; the committed
RAM-backed test is mints/test/run_lfs_micropython.py.

Run from the repo root (mount supplies mints + lib/tamp; data goes to the real
flash, not the host):

    mpremote connect <port> mount . run mints/test/run_flash_prune_esp32.py

Both paths are exercised against the genuine SPI-flash + littlefs + tamp:
  - compress_data_file(): ENOSPC mid shard-creation -> prune oldest -> retry.
  - flush(): ENOSPC mid hot-file append -> prune oldest -> retry.

Note: littlefs statvfs `bavail` is conservative (it withholds reserve blocks), so
filling must continue until a write truly raises ENOSPC, not until statvfs reads
low -- otherwise the reserve absorbs the write and no ENOSPC is seen.
"""
import sys
import os

REPO = os.getcwd()  # /remote under `mpremote mount`
for p in (REPO, REPO + '/lib'):
    if p not in sys.path:
        sys.path.insert(0, p)

import errno
from mints import Store, Col, ENOSPC

DIR = '/prunetest'


def _free():
    s = os.statvfs('.')
    return s[1] * s[4]


def fill_full(name):
    """Write a filler file until a write genuinely raises ENOSPC (truly full)."""
    buf = b'\x00' * 4096
    written = 0
    f = open(name, 'wb')
    try:
        while True:
            try:
                f.write(buf)
                f.flush()
                written += 4096
            except OSError:
                break
    finally:
        f.close()
    return written


def vval(i):
    # poorly-compressible 16-bit value so the shard needs real data blocks
    x = (i * 2654435761 + 1013904223) & 0xFFFFFFFF
    x ^= x >> 15
    return x & 0xFFFF


def _seed_shards(prefix, n, size=16 * 1024):
    for i in range(n):
        with open(prefix + '%02i.tamp' % i, 'wb') as f:
            f.write(b'\x00' * size)


def _count_prunes(store):
    cnt = [0]
    real = store._prune_oldest_shard

    def wrapped():
        cnt[0] += 1
        return real()

    store._prune_oldest_shard = wrapped
    return cnt


def test_compress():
    N = 5000
    SEEDED = 4
    store = Store('cmp', [Col('time', 'u16', monotonic=True), Col('v', 'u16')])
    prefix = store._fn[:-3]
    for i in range(N):
        store.add_sample(dict(time=i % 65535, v=vval(i)))
    store.flush()
    bin_size = os.stat(store._fn)[6]
    assert bin_size >= 16 * 1024, 'hot file too small: ' + str(bin_size)
    _seed_shards(prefix, SEEDED)

    prunes = _count_prunes(store)
    fill_full('filler.bin')
    idx = store._next_shard_index()
    store.compress_data_file()

    assert prunes[0] >= 1, 'compress did not prune on a full flash'
    new_shard = prefix + '%02i.tamp' % idx
    assert new_shard in os.listdir('.'), 'new shard missing: ' + new_shard
    assert store._fn not in os.listdir('.'), 'hot file not removed'
    assert os.stat(new_shard)[6] > 0, 'shard empty'
    os.remove('filler.bin')
    print('  COMPRESS recovery OK on real flash: .bin', bin_size, '-> shard',
          os.stat(new_shard)[6], 'B, pruned', prunes[0], 'shard(s), retried')


def test_flush():
    SEEDED = 4
    store = Store('flu', [Col('time', 'u16', monotonic=True), Col('v', 'u16')])
    _seed_shards(store._fn[:-3], SEEDED)

    prunes = _count_prunes(store)
    fill_full('filler2.bin')

    forced = False
    for i in range(200000):
        store.add_sample(dict(time=i % 65535, v=i % 65535))
        if prunes[0] >= 1:
            forced = True
            break
    store.flush()

    assert forced, 'flush never hit ENOSPC on a full flash'
    sz = os.stat(store._fn)[6]
    assert sz > 0 and sz % store._frame_size == 0, 'bad hot-file size ' + str(sz)
    print('  FLUSH recovery OK on real flash: pruned', prunes[0],
          'shard(s), retry wrote', sz, 'bytes')


def cleanup():
    os.chdir('/')
    try:
        for f in os.listdir(DIR):
            os.remove(DIR + '/' + f)
        os.rmdir(DIR)
    except OSError as e:
        print('cleanup note:', e)


def main():
    print('REAL-FLASH prune test on', sys.platform,
          '.'.join(str(v) for v in sys.implementation.version),
          '- mints.ENOSPC =', ENOSPC)
    start_free = os.statvfs('/')
    start_free = start_free[1] * start_free[4]
    print('flash free at start:', start_free, 'bytes')
    try:
        os.mkdir(DIR)
    except OSError:
        pass
    os.chdir(DIR)
    try:
        test_compress()
        test_flush()
        print('REAL-FLASH PRUNE TEST PASSED')
    finally:
        cleanup()
        end = os.statvfs('/')
        print('cleaned up; flash free now:', end[1] * end[4], 'bytes')


main()
