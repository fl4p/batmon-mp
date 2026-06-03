"""
On-target validation of the shard auto-prune flash-full recovery, using a REAL
littlefs (vfs.VfsLfs2) on a RAM block device. The host pytest suite only injects
a synthetic OSError; this exercises the genuine ENOSPC path the device hits.

It is NOT a pytest test (it needs `vfs`/littlefs, absent on host CPython), so the
filename avoids the `test_*` / `*_test` patterns pytest collects.

Run on the MicroPython unix port (covers errno facts + the flush path; the
compress test SKIPs because the vendored `tamp` is viper-compiled and won't load
on the unix port):

    micropython mints/test/run_lfs_micropython.py

Run on a real ESP32 (additionally covers the compress/shard ENOSPC path, since
viper `tamp` compiles on-device). Mount the repo so `mints` + `lib/tamp` import,
data goes to an in-RAM littlefs so the device's real flash is never touched:

    mpremote connect <port> mount . run mints/test/run_lfs_micropython.py

Exits non-zero (via an uncaught AssertionError) on failure.

Covers, on a real full filesystem:
  - errno fact: a full littlefs raises OSError(28) and `errno.ENOSPC` is NOT a
    defined name -> guards the regression where mints referenced errno.ENOSPC and
    crashed inside its own except handler.
  - Store.flush() catches the real ENOSPC, prunes oldest-first, retry write
    succeeds (unlink reclaims space immediately on littlefs).
  - Store.compress_data_file() catches a real ENOSPC mid shard-creation, drops the
    partial .tamp.tmp, prunes, retries, and produces a readable shard (ESP32 only).
  - monotonic numbering helpers work against a real os.listdir.
"""
import sys
import os

# Make the repo importable. Under `mpremote mount .` the cwd is the mount root and
# is already on sys.path; under the unix port we are launched from the repo root.
# Add both the repo and its lib/ (vendored tamp) so imports resolve after we chdir
# into the RAM littlefs for data files.
REPO = os.getcwd()
for p in (REPO, REPO + '/lib'):
    if p not in sys.path:
        sys.path.insert(0, p)

import errno
import vfs


class RAMBlockDev:
    """Minimal extended-interface block device backing a littlefs in RAM."""

    def __init__(self, block_size, num_blocks):
        self.block_size = block_size
        self.data = bytearray(block_size * num_blocks)

    def readblocks(self, n, buf, off=0):
        addr = n * self.block_size + off
        for i in range(len(buf)):
            buf[i] = self.data[addr + i]

    def writeblocks(self, n, buf, off=0):
        addr = n * self.block_size + off
        for i in range(len(buf)):
            self.data[addr + i] = buf[i]

    def ioctl(self, op, arg):
        if op == 4:   # block count
            return len(self.data) // self.block_size
        if op == 5:   # block size
            return self.block_size
        if op == 6:   # erase
            return 0


MNT = '/lfs_test'


def fresh_lfs(kb=64, block_size=4096):
    """(Re)mount an empty RAM littlefs at MNT and chdir into it."""
    try:
        os.chdir('/')
        vfs.umount(MNT)
    except Exception:
        pass
    num_blocks = (kb * 1024) // block_size
    bdev = RAMBlockDev(block_size, num_blocks)
    vfs.VfsLfs2.mkfs(bdev)
    vfs.mount(vfs.VfsLfs2(bdev), MNT)
    os.chdir(MNT)


def _free_bytes():
    s = os.statvfs('.')
    return s[1] * s[4]   # f_frsize * f_bavail


def _fill_until_low(name, margin):
    """Consume free space (in a throwaway file) until <= margin bytes remain."""
    chunk = b'\x00' * 512
    with open(name, 'wb') as f:
        while _free_bytes() > margin:
            try:
                f.write(chunk)
                f.flush()
            except OSError:
                break


def test_errno_facts():
    # The name our code must NOT depend on:
    assert not hasattr(errno, 'ENOSPC'), \
        "this MicroPython build unexpectedly defines errno.ENOSPC"
    # The numeric value a full littlefs actually raises:
    caught = None
    try:
        with open('probe.bin', 'wb') as f:
            for _ in range(100000):
                f.write(b'x' * 1024)
                f.flush()
    except OSError as e:
        caught = getattr(e, 'errno', None)
    os.remove('probe.bin')
    assert caught == 28, ("expected ENOSPC==28 from full littlefs, got " + str(caught))
    # mints must agree on the constant it compares against:
    from mints import ENOSPC
    assert ENOSPC == caught, ("mints.ENOSPC=" + str(ENOSPC) + " != real " + str(caught))
    print("  errno facts OK: ENOSPC absent as name, real value 28, mints.ENOSPC matches")


def test_flush_prunes_and_retries():
    from mints import Store, Col

    store = Store('lfs', [Col('time', 'u16', monotonic=True), Col('v', 'u16')])
    prefix = store._fn[:-3]

    # seed several real shard files the pruner can reclaim
    SEEDED = 6
    for i in range(SEEDED):
        with open(prefix + '%02i.tamp' % i, 'wb') as f:
            f.write(b'\x00' * 512)

    assert store._next_shard_index() == SEEDED  # monotonic max+1 over real listdir

    # count real prunes; stop feeding right after the first so the full fs
    # doesn't cascade-prune every seeded shard
    prunes = [0]
    real_prune = store._prune_oldest_shard

    def counting_prune():
        prunes[0] += 1
        return real_prune()

    store._prune_oldest_shard = counting_prune

    forced = False
    for i in range(200000):
        store.add_sample(dict(time=i % 65535, v=i % 65535))
        if prunes[0] >= 1:
            forced = True
            break
    store.flush()  # land any buffered tail (may itself hit the full fs and prune again)

    assert forced, "filesystem never filled -- could not force an ENOSPC prune"
    assert prunes[0] >= 1, "no prune happened despite a full filesystem"
    assert prunes[0] < SEEDED, "exhausted all shards -- feed loop did not stop in time"

    # pruning must remove the OLDEST indices first, in order
    remaining = sorted(store._shard_index(f) for f in store.get_shard_files())
    expected = list(range(prunes[0], SEEDED))
    assert remaining == expected, \
        ("expected remaining " + str(expected) + " got " + str(remaining))

    sz = os.stat(store._fn)[6]
    assert sz > 0 and sz % store._frame_size == 0, ("bad hot-file size " + str(sz))
    store.close()
    print("  flush recovery OK: forced real ENOSPC, pruned " + str(prunes[0])
          + " oldest shard(s) in order, retry wrote " + str(sz) + " bytes ("
          + str(sz // store._frame_size) + " frames)")


def test_compress_prunes_and_retries():
    # The shard compressor needs `tamp` (viper). On the unix port it won't load,
    # so SKIP there; on a real ESP32 it compiles and this exercises the genuine
    # ENOSPC-during-shard-creation retry path.
    try:
        import tamp  # noqa: F401
    except Exception as e:
        print("  compress recovery SKIPPED (tamp unavailable here: "
              + e.__class__.__name__ + ")")
        return

    from mints import Store, Col
    from mints.shard import ShardStoreReader

    # poorly-compressible 16-bit value: a tiny shard would be inlined into
    # littlefs directory metadata and fit even on a "full" fs, never triggering
    # ENOSPC. High entropy forces the shard to need real data blocks.
    def vval(i):
        x = (i * 2654435761 + 1013904223) & 0xFFFFFFFF
        x ^= x >> 15
        return x & 0xFFFF

    N = 5000
    store = Store('cmp', [Col('time', 'u16', monotonic=True), Col('v', 'u16')])
    prefix = store._fn[:-3]

    # build a hot file comfortably over the 16 KiB compress floor (N*4 bytes)
    for i in range(N):
        store.add_sample(dict(time=i % 65535, v=vval(i)))
    store.flush()
    bin_size = os.stat(store._fn)[6]
    assert bin_size >= 16 * 1024, "hot file too small to compress: " + str(bin_size)

    # seed shards big enough that one prune frees more than a shard's worth
    SEEDED = 4
    for i in range(SEEDED):
        with open(prefix + '%02i.tamp' % i, 'wb') as f:
            f.write(b'\x00' * (16 * 1024))

    prunes = [0]
    real_prune = store._prune_oldest_shard

    def counting_prune():
        prunes[0] += 1
        return real_prune()

    store._prune_oldest_shard = counting_prune

    # Leave less than one littlefs block free so the shard's first block
    # allocation fails -> guaranteed ENOSPC regardless of the (large, ~14 KB)
    # shard size. Exercises the except path for real: close the partial shard,
    # unlink the .tmp, prune, retry.
    _fill_until_low('filler.bin', 256)

    idx = store._next_shard_index()        # == SEEDED
    store.compress_data_file()             # must recover via prune+retry

    assert prunes[0] >= 1, "compress did not hit ENOSPC / prune on a near-full fs"
    # the new shard was created with the monotonic index and the hot file is gone
    new_shard = prefix + '%02i.tamp' % idx
    assert new_shard in os.listdir('.'), ("new shard missing: " + new_shard)
    assert store._fn not in os.listdir('.'), "hot file not removed after compress"
    shard_size = os.stat(new_shard)[6]
    assert shard_size > 0, "new shard is empty after the ENOSPC retry"

    # Verify round-trip ONLY where a tamp decompressor exists. On-device tamp is
    # compressor-only by design (install.py installs the compressor package;
    # decompression happens off-device), so reading back raises NameError there.
    # The host pytest test_shard_store already covers the byte-level round-trip.
    verified = "write-only (no on-device decompressor)"
    try:
        reader = ShardStoreReader(store.columns, new_shard)
        rows = reader.read_all()
        reader.close()
        assert len(rows) == N, ("shard row count " + str(len(rows)) + " != " + str(N))
        for k in (0, N // 2, N - 1):
            assert rows[k]['time'] == k and rows[k]['v'] == vval(k), \
                ("shard data corrupted at row " + str(k) + " across the ENOSPC retry")
        verified = str(N) + " rows read back intact"
    except (NameError, ImportError, SyntaxError):
        pass
    print("  compress recovery OK: .bin " + str(bin_size) + "B -> shard "
          + str(shard_size) + "B, pruned " + str(prunes[0]) + " shard(s), retried; "
          + verified)


def main():
    print("running mints littlefs ENOSPC tests on", sys.implementation.name,
          '.'.join(str(v) for v in sys.implementation.version), "/", sys.platform)
    fresh_lfs(kb=64)
    test_errno_facts()
    fresh_lfs(kb=64)
    test_flush_prunes_and_retries()
    fresh_lfs(kb=256)
    test_compress_prunes_and_retries()
    print("ALL LFS TESTS PASSED")


main()
