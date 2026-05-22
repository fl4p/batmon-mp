# Shard Auto-Prune Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `mints/` self-recover when flash fills by deleting the oldest cold-tier `.tamp` shard and retrying the write, with monotonically increasing shard numbering so a pruned index is never reused.

**Architecture:** Add three private helpers to `Store` (`_shard_index`, `_next_shard_index`, `_prune_oldest_shard`) built on the existing `get_shard_files()`. Replace the first-free index scan in `compress_data_file` with `max+1` numbering, and wrap both the shard-creation write and the hot-file `flush` write in a prune-and-retry loop that fires only on `OSError(errno.ENOSPC)`.

**Tech Stack:** MicroPython (host-tested under CPython via pytest), `struct`, `os`, `tamp`.

**Spec:** `docs/superpowers/specs/2026-05-22-shard-auto-prune-design.md`

**Conventions (read before starting):**
- Tests live in `mints/test/test.py`, run with `pytest` from the repo root (package-relative imports `from .. import Store, Col`). They write/clean up files in the current working directory.
- Code must run under MicroPython: no `int.from_bytes(signed=True)`, no `bytearray.clear`, limited f-strings. `min(seq, key=...)`, `max(gen)`, and the `errno` module are all available on MicroPython — fine to use.
- Shard filenames: `{name}-{cols}-{fmt}.NN.tamp`. The prefix is `self._fn[:-3]` (strips `"bin"`, keeps the trailing `.`). The in-progress shard ends in `.tamp.tmp`, which `get_shard_files()` (suffix `.tamp`) correctly excludes.

---

## Task 1: Shard-index helpers + monotonic numbering primitive

**Files:**
- Modify: `mints/__init__.py` (add `import errno`; add three methods to `Store` after `get_shard_files`, around line 131)
- Test: `mints/test/test.py`

- [ ] **Step 1: Write the failing test**

Add to `mints/test/test.py`. Also add `import errno` near the top of the file (after `import struct`), and add `file_exists` to the existing `from .. import Store, Col` line so it reads `from .. import Store, Col, file_exists`.

```python
def test_shard_prune_helpers():
    import glob
    store = Store('ptest', [Col('time', 'u16', monotonic=True), Col('v', 'u16')])
    prefix = store._fn[:-3]  # 'ptest-time,v-HH.'
    # shards with a gap (no 09..99) and across the 99->100 filename-width boundary
    for i in (8, 100):
        with open(prefix + '%02i.tamp' % i, 'wb') as f:
            f.write(b'\x00')
    try:
        assert store._shard_index(prefix + '08.tamp') == 8
        assert store._shard_index(prefix + '100.tamp') == 100
        # next index ignores gaps and uses the numeric max, not lexical
        assert store._next_shard_index() == 101
        # prune removes the numeric minimum (08), not lexical ('100' < '08')
        assert store._prune_oldest_shard() is True
        assert not file_exists(prefix + '08.tamp')
        assert file_exists(prefix + '100.tamp')
        assert store._prune_oldest_shard() is True   # removes 100
        assert store._prune_oldest_shard() is False  # nothing left
        assert store._next_shard_index() == 0
    finally:
        for fn in glob.glob('ptest-*'):
            os.unlink(fn)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest mints/test/test.py::test_shard_prune_helpers -v`
Expected: FAIL with `AttributeError: 'Store' object has no attribute '_shard_index'`.

- [ ] **Step 3: Write minimal implementation**

In `mints/__init__.py`, add `import errno` after the existing `import struct` (line 37):

```python
import os
import struct
import errno
```

Then add these three methods to `Store`, immediately after `get_shard_files` (after line 131):

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest mints/test/test.py::test_shard_prune_helpers -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mints/__init__.py mints/test/test.py
git commit -m "feat(mints): shard-index helpers and monotonic numbering primitive"
```

---

## Task 2: Prune-and-retry on shard creation (`compress_data_file`)

**Files:**
- Modify: `mints/__init__.py` — replace the body of `compress_data_file` (lines 133-166)
- Test: `mints/test/test.py`

- [ ] **Step 1: Write the failing test**

Add to `mints/test/test.py`:

```python
def test_prune_and_retry_on_shard_creation():
    import glob
    store = Store('rtest', [Col('time', 'u16', monotonic=True), Col('v', 'u16')])

    def fill_and_shard(n=5000):
        # n*4 bytes (HH frame) > the 16 KiB compress assert threshold
        for i in range(n):
            store.add_sample(dict(time=i % 65535, v=i % 65535))
        store.flush()
        store.compress_data_file()

    try:
        fill_and_shard()   # creates shard index 00
        fill_and_shard()   # creates shard index 01
        assert sorted(store._shard_index(f) for f in store.get_shard_files()) == [0, 1]

        # inject a single ENOSPC on the shard rename, then let the retry succeed
        real_rename = os.rename
        calls = {'n': 0}

        def flaky_rename(a, b):
            if calls['n'] == 0:
                calls['n'] += 1
                raise OSError(errno.ENOSPC, 'no space')
            return real_rename(a, b)

        os.rename = flaky_rename
        try:
            fill_and_shard()  # wants index 02; rename fails once -> prune 00 -> retry
        finally:
            os.rename = real_rename

        assert calls['n'] == 1  # the failure actually happened
        # oldest (00) pruned, new (02) created, numbering never reused 00
        assert sorted(store._shard_index(f) for f in store.get_shard_files()) == [1, 2]
    finally:
        if store._fh:
            store._fh.close()
        for fn in glob.glob('rtest-*'):
            os.unlink(fn)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest mints/test/test.py::test_prune_and_retry_on_shard_creation -v`
Expected: FAIL — current `compress_data_file` does not catch `OSError`, so the injected `OSError(ENOSPC)` propagates out of `fill_and_shard`.

- [ ] **Step 3: Write minimal implementation**

Replace the entire `compress_data_file` method (current lines 133-166) with:

```python
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

        read_frame = struct.Struct(self._frame_fmt).unpack
        from mints.shard import ShardStore

        while True:
            shard = None
            try:
                shard = ShardStore(self.columns, tmp_fn)
                with open(self._fn, 'rb') as fh:
                    while len(frame := fh.read(self._frame_size)) == self._frame_size:
                        shard.add_sample(read_frame(frame))
                shard.close()
                shard = None
                os.rename(tmp_fn, tamp_fn)
                break
            except OSError as e:
                # close + drop the partial in-progress shard before retrying
                if shard is not None:
                    try:
                        shard.close()
                    except OSError:
                        pass
                try:
                    os.unlink(tmp_fn)
                except OSError:
                    pass
                # flash full: free the oldest shard and retry; idx is unchanged
                # because pruning only removes a lower index. If nothing is left
                # to prune (or it's a different error), re-raise.
                if getattr(e, 'errno', None) != errno.ENOSPC or not self._prune_oldest_shard():
                    raise

        os.unlink(self._fn)
        self._fsize = 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest mints/test/test.py::test_prune_and_retry_on_shard_creation -v`
Expected: PASS.

Also run the existing storage tests to confirm no regression:
Run: `pytest mints/test/test.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add mints/__init__.py mints/test/test.py
git commit -m "feat(mints): prune oldest shard and retry on ENOSPC during compression"
```

---

## Task 3: Prune-and-retry on hot-file `flush`

**Files:**
- Modify: `mints/__init__.py` — replace the body of `flush` (lines 257-272)
- Test: `mints/test/test.py`

- [ ] **Step 1: Write the failing test**

Add to `mints/test/test.py`:

```python
def test_prune_and_retry_on_flush():
    import glob, mints
    store = Store('ftest', [Col('time', 'u16', monotonic=True), Col('v', 'u16')])
    prefix = store._fn[:-3]
    # two existing shards to prune from
    for i in (0, 1):
        with open(prefix + '%02i.tamp' % i, 'wb') as f:
            f.write(b'x' * 1024)

    real_open = open
    state = {'raised': False}

    class FlakyFile:
        def __init__(self, f):
            self._f = f

        def write(self, b):
            if not state['raised']:
                state['raised'] = True
                raise OSError(errno.ENOSPC, 'no space')
            return self._f.write(b)

        def __getattr__(self, k):
            return getattr(self._f, k)  # delegate seek/flush/tell/read/close

    def flaky_open(fn, mode='r', *a, **k):
        f = real_open(fn, mode, *a, **k)
        return FlakyFile(f) if fn == store._fn else f

    mints.open = flaky_open
    try:
        # the write-buffer fills well before 500 frames, forcing a flush whose
        # first write raises ENOSPC -> prune oldest (00) -> seek back -> retry
        for i in range(500):
            store.add_sample(dict(time=i, v=i))
        store.flush()
    finally:
        mints.open = real_open
        if store._fh:
            store._fh.close()

    assert state['raised'] is True               # the ENOSPC actually fired
    assert sorted(store._shard_index(f) for f in store.get_shard_files()) == [1]  # 00 pruned
    assert os.stat(store._fn)[6] > 0             # data really landed in the .bin
    for fn in glob.glob('ftest-*'):
        os.unlink(fn)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest mints/test/test.py::test_prune_and_retry_on_flush -v`
Expected: FAIL — current `flush` does not catch `OSError`, so the injected `OSError(ENOSPC)` propagates and no shard is pruned.

- [ ] **Step 3: Write minimal implementation**

Replace the entire `flush` method (current lines 257-272) with:

```python
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
                if getattr(e, 'errno', None) != errno.ENOSPC or not self._prune_oldest_shard():
                    raise
        # os.fsync()
        self._fsize = pos + written
        self._write_buf_pos = 0

        if sharding:
            if self._fsize > (1024 * 256):
                self.compress_data_file()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest mints/test/test.py::test_prune_and_retry_on_flush -v`
Expected: PASS.

Run the full suite to confirm no regression:
Run: `pytest mints/test/test.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Add the new tests to `_main()` and commit**

In `mints/test/test.py`, extend `_main()` so a direct (non-pytest) run also exercises the new paths:

```python
def _main():
    test_pack()
    test_zigzag_coding()
    test_varint_coding()
    # test_compress_file()
    test_store()
    test_shard_store()
    test_shard_prune_helpers()
    test_prune_and_retry_on_shard_creation()
    test_prune_and_retry_on_flush()
```

```bash
git add mints/__init__.py mints/test/test.py
git commit -m "feat(mints): prune oldest shard and retry on ENOSPC during flush"
```

---

## Task 4: Clean up stale TODOs

**Files:**
- Modify: `mints/__init__.py` (module docstring TODO list, lines 3-4)
- Modify: `README.md` if it carries the same TODO (grep first)

- [ ] **Step 1: Remove the now-resolved TODO**

In the module docstring at the top of `mints/__init__.py`, delete the line:
```
- delete old shards if disk is full (notice by OSError)
```
The old inline TODOs inside `compress_data_file` ("TODO start from the top..." / "instead of str(i) use the index, monotonic") were removed when the method was rewritten in Task 2 — confirm none remain.

- [ ] **Step 2: Check README for the same TODO**

Run: `grep -n "delete old shards" README.md mints/README.md`
If found, remove the corresponding line.

- [ ] **Step 3: Commit**

```bash
git add mints/__init__.py README.md mints/README.md
git commit -m "docs(mints): drop TODO resolved by shard auto-prune"
```

---

## Self-review notes

- **Spec coverage:** §1 monotonic numbering → Task 1 (`_next_shard_index`) + Task 2 (used in `compress_data_file`). §2 reactive prune-and-retry, both paths → Task 2 (shard creation) + Task 3 (flush). §3 limit behavior (re-raise when `_prune_oldest_shard()` returns `False`) → covered by the `or not self._prune_oldest_shard(): raise` clause in both loops. Testing items 1-4 → `test_shard_prune_helpers` (numbering/min/gap/width-boundary) + the two retry tests.
- **Type consistency:** `_shard_index`, `_next_shard_index`, `_prune_oldest_shard` names used identically across Tasks 1-3. `errno.ENOSPC` filter identical in both loops.
- **MicroPython safety:** `min(..., key=...)`, `max(generator)`, `getattr(e, 'errno', None)`, and `import errno` are all MicroPython-supported. No CPython-only constructs introduced.
- **Assumption (from spec):** littlefs raises `ENOSPC` rather than silently doing a partial write for the ≤256 B page-aligned buffer; the `seek(pos)` before each attempt makes a retry safe even if a partial write did occur.
