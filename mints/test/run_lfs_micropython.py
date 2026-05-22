"""
On-target validation of the shard auto-prune flash-full recovery, using a REAL
littlefs (vfs.VfsLfs2) on a RAM block device. The host pytest suite only injects
a synthetic OSError; this exercises the genuine ENOSPC path that the device hits.

It is NOT a pytest test (it needs `vfs`/littlefs, absent on host CPython), so the
filename avoids the `test_*` / `*_test` patterns pytest collects. Run it with the
MicroPython unix port from the repo root:

    micropython mints/test/run_lfs_micropython.py

Exits non-zero (via an uncaught AssertionError) on failure.

Covers, on a real full filesystem:
  - errno fact: a full littlefs raises OSError(28) and `errno.ENOSPC` is NOT a
    defined name -> guards the regression where mints referenced errno.ENOSPC and
    crashed inside its own except handler.
  - Store.flush() catches the real ENOSPC, prunes the oldest shard, and the retry
    write succeeds (unlink reclaims space immediately on littlefs).
  - monotonic numbering helpers work against a real os.listdir.

The compress/sharding path is intentionally NOT exercised here: it pulls in `tamp`
(viper-compiled, not loadable on the unix port) and never triggers anyway because
the tiny filesystem can't reach the 256 KiB shard threshold.
"""
import sys
import os

# import the mints package from the repo (cwd will be the littlefs mount, so an
# absolute path is required). Assumes `micropython mints/test/run_lfs_micropython.py`
# is launched from the repo root.
REPO = os.getcwd()
sys.path.insert(0, REPO)

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


def mount_fresh_lfs():
    bdev = RAMBlockDev(512, 128)   # 64 KiB filesystem
    vfs.VfsLfs2.mkfs(bdev)
    fs = vfs.VfsLfs2(bdev)
    vfs.mount(fs, '/lfs')
    os.chdir('/lfs')
    return bdev


def test_errno_facts():
    # The name our code must NOT depend on:
    assert not hasattr(errno, 'ENOSPC'), \
        "this MicroPython build unexpectedly defines errno.ENOSPC"
    # The numeric value a full littlefs actually raises:
    caught = None
    try:
        with open('probe.bin', 'wb') as f:
            for _ in range(10000):
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


def test_flush_prunes_and_retries_on_real_lfs():
    from mints import Store, Col

    store = Store('lfs', [Col('time', 'u16', monotonic=True), Col('v', 'u16')])
    prefix = store._fn[:-3]

    # seed several real shard files the pruner can reclaim
    SEEDED = 6
    for i in range(SEEDED):
        with open(prefix + '%02i.tamp' % i, 'wb') as f:
            f.write(b'\x00' * 512)

    assert store._next_shard_index() == SEEDED  # monotonic max+1 over real listdir

    # count real prunes; stop feeding right after the first so the fs (now full)
    # doesn't cascade-prune every seeded shard
    prunes = [0]
    real_prune = store._prune_oldest_shard

    def counting_prune():
        prunes[0] += 1
        return real_prune()

    store._prune_oldest_shard = counting_prune

    # add samples until a real ENOSPC forces exactly one prune+retry
    forced = False
    for i in range(200000):
        store.add_sample(dict(time=i % 65535, v=i % 65535))
        if prunes[0] >= 1:
            forced = True
            break
    store.flush()  # land any buffered tail (may itself hit the full fs and prune again)

    assert forced, "filesystem never filled — could not force an ENOSPC prune"
    assert prunes[0] >= 1, "no prune happened despite a full filesystem"
    assert prunes[0] < SEEDED, "exhausted all shards — feed loop did not stop in time"

    # pruning must remove the OLDEST indices first, in order
    remaining = sorted(store._shard_index(f) for f in store.get_shard_files())
    expected = list(range(prunes[0], SEEDED))
    assert remaining == expected, \
        ("expected remaining " + str(expected) + " got " + str(remaining))

    # the hot file holds real, frame-aligned data written across the retry
    sz = os.stat(store._fn)[6]
    assert sz > 0 and sz % store._frame_size == 0, ("bad hot-file size " + str(sz))
    store.close()
    print("  flush recovery OK: forced real ENOSPC, pruned " + str(prunes[0])
          + " oldest shard(s) in order, retry wrote " + str(sz) + " bytes ("
          + str(sz // store._frame_size) + " frames)")


def main():
    mount_fresh_lfs()
    print("running mints littlefs ENOSPC tests on", sys.implementation.name,
          '.'.join(str(v) for v in sys.implementation.version))
    test_errno_facts()
    test_flush_prunes_and_retries_on_real_lfs()
    print("ALL LFS TESTS PASSED")


main()
