# Design: auto-prune oldest mints shards when flash is full

Date: 2026-05-22
Component: `mints/` time-series storage engine (`mints/__init__.py`)

## Problem

The mints store accumulates cold-tier `.tamp` shards forever. On a device with
fixed flash, writes eventually fail with `OSError(ENOSPC)`. The store should
self-recover by deleting the oldest shard(s) and retrying, so the device keeps
logging recent data unattended. This is the long-standing TODO at the top of
`mints/__init__.py` ("delete old shards if disk is full (notice by OSError)")
and the inline TODO in `compress_data_file`.

## Constraints / context

- Runs under MicroPython on ESP32/ESP8266. No CPython-only APIs.
- Shards are named `{name}-{cols}-{fmt}.NN.tamp`, where `NN` is the index
  produced by `'%02i' % i`. `get_shard_files()` returns them by prefix match.
- The only consumers of shard filenames are `ble_filesrv.py` (`list`/`read`,
  both purely filename-based) and the browser web app (downloads by name).
  Neither assumes contiguous indices, low indices, or lexical ordering, so the
  numbering scheme can change freely.
- The only code that assumed first-free indexing is `compress_data_file`
  itself, which this design replaces.

## Decisions (from brainstorming)

- **Detection: reactive** — catch `OSError` (ENOSPC) on write; do not poll
  `os.statvfs`.
- **Prune amount: one oldest shard, then retry; repeat** until the write
  succeeds or no shards remain.
- **Both write paths are handled**: shard creation (`compress_data_file`) and
  the hot-file append (`flush`).

## Design

### 1. Monotonic shard numbering

`compress_data_file` currently picks the next index by scanning from `0` for the
first free slot. Once shards are deleted, a freed low index is reused, breaking
chronological order. Replace with "max existing index + 1".

New helpers on `Store`, all built on the existing `get_shard_files()`:

- `_shard_index(filename) -> int` — parse the `NN` between the prefix
  (`self._fn[:-3]`, i.e. `{name}-{cols}-{fmt}.`) and the `.tamp` suffix, as an
  `int`.
- `_next_shard_index() -> int` — `max(indices) + 1`, or `0` when there are no
  shards.
- `_prune_oldest_shard() -> bool` — `os.unlink` the shard with the **minimum**
  index; return `False` when no shards exist (nothing left to prune).

Indices are parsed and compared numerically, so the existing `'%02i'` format is
kept and simply widens to 3+ digits past 99 with no ordering bug and no
filename-format change.

### 2. Reactive prune-and-retry

**Detecting ENOSPC (validated on real littlefs, MicroPython 1.27 unix port):**
A full `VfsLfs2` raises `OSError` with `errno == 28`, and `os.unlink` reclaims the
freed blocks immediately so the retry write succeeds. Crucially, MicroPython's
`errno` module does **not** define the name `ENOSPC` (it's absent from the default
`MICROPY_PY_ERRNO_LIST`), so referencing `errno.ENOSPC` raises `AttributeError`
*inside* the except handler on-device. Therefore the code defines a module-level
constant `ENOSPC = 28` (the value is stable across Linux/macOS/newlib/ESP-IDF) and
compares against it rather than importing `errno`. A real-littlefs regression test
lives at `mints/test/run_lfs_micropython.py` (run with the MicroPython unix port).

A single retry pattern wraps each risky write:

```
while True:
    try:
        <do the write>
        break
    except OSError as e:
        if getattr(e, 'errno', None) != ENOSPC or not self._prune_oldest_shard():
            raise
        # space freed; loop and retry
```

Filtering on `ENOSPC` (the module constant `= 28`) ensures unrelated I/O errors
do not trigger data deletion — they re-raise immediately.

**`compress_data_file`** — wrap the shard build (`ShardStore` write loop) plus
the `os.rename` in the retry loop. On `OSError`, first `os.unlink` the partial
`…NN.tamp.tmp` (ignore failure if absent), then prune and retry. Because the
in-progress file ends in `.tmp` (not `.tamp`), `get_shard_files()` never returns
it, so pruning cannot delete the shard being written. The index is computed once
via `_next_shard_index()` before the loop; it does not change across retries
(pruning only removes older, lower indices).

**`flush`** — wrap the `fh.write(self._write_buf[:n])` call. Frames are
fixed-width and appended; to stay retry-safe, capture the intended append offset
`pos = self._fsize`, `fh.seek(pos)` before each attempt, and set
`self._fsize = pos + written` from the bytes actually returned. Seeking back to
`pos` overwrites any partial bytes left by a failed attempt. Assumption:
littlefs raises `ENOSPC` rather than silently doing a partial write for the
small (≤256 B) page-aligned buffer used here.

### 3. Behavior at the limit

If a write fails and `_prune_oldest_shard()` returns `False` (flash full, no
shards left), the `OSError` re-raises and propagates to `boot.py`, which resets
the device — the existing unattended-recovery contract. No new failure mode is
introduced.

## Testing

Add to `mints/test/test.py` (pytest from repo root, host CPython):

1. **Prune-and-retry on shard creation**: force `OSError(ENOSPC)` on the shard
   write (e.g. monkeypatch `ShardStore` / the tamp open, or wrap so it raises on
   first call), seed several existing shards, and assert the oldest shard is
   deleted and the write then succeeds.
2. **Monotonic numbering after prune**: after a prune, assert new shard indices
   keep increasing and never reuse a freed index.
3. **`_next_shard_index` ignores gaps**: with shards `{02, 05}` present, assert
   it returns `06`.
4. **`_prune_oldest_shard` picks the numeric minimum**, including across the
   99→100 width boundary (e.g. `{08, 100}` prunes `08`).

`test_store` already drives multiple shard cycles, so the fill harness exists.

## Out of scope

- Proactive `os.statvfs` free-space checks.
- Pruning down to a free-space target (only one shard per retry).
- Any change to the shard binary format or the web/JS reader.
- Compression-ratio work — see the COMPRESSION INVESTIGATION note; the
  downsampler, not the codec, is the lever for flash pressure.
