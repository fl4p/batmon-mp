# mints compression — design, measurements, and conclusions

Single source of truth for how the time-series store compresses data, what was
tried, what the numbers are, and what is *not* worth doing. Supersedes the
scattered notes in `mints/__init__.py` (the TODO/investigation block) and the
README's "Efficient time series storage" section.

TL;DR:
- The shipping codec is **columnar + delta + zigzag + varint + tamp (LZ)**. It is
  close enough to the lossless floor that remaining codec wins are incremental,
  not order-of-magnitude.
- The data is **near its lossless entropy floor**. `current` and `minmax_idx` are
  real, irreducible entropy. Codec micro-tweaks are exhausted — don't re-run that search.
- The **downsampler** (`daq/downsample.py`) is the only lever with
  order-of-magnitude headroom. Point retention concerns there first.
- Everything below (better compressor, current de-noising) is second-order to the
  downsampler.

---

## 1. The data

Schema for the reference device (JKPferdestall):
`time,voltage,current,temp2,soc2,cell_min,cell_max,minmax_idx` packed as `HHhBBHHB`
= **13 bytes/frame**. Quantization happens in the producer (`batmon.py`), not the
store: V/I ×100, temp `(t+40)*2`→u8, soc×2→u8, cells in mV, and the two cell
indices packed into one byte (`max_idx*n + min_idx`). `time` is u16 of
seconds-since-boot/10 and is `monotonic=True`.

Two real samples used for all numbers here (`data/pferdestall/`):
- **active** — `2025-11/...HHhBBHHB.bin`, 76 413 rows, 993 369 B. Heavy load variation.
- **idle** — `recovered-2026-06-29/...HHhBBHHB.bin`, 55 926 rows, 727 040 B. Mostly resting.

`ratio` below = compressed_bytes / raw_bytes (lower is better). raw = rows × 13.

---

## 2. The shipping codec

Hot tier (`.bin`): fixed-width `struct` frames, append-only, 256 B buffered writes.
Cold tier (`.tamp` shards via `mints/shard.py`): when the hot file exceeds ~256 KB
it is rewritten **column-major** (`ShardStore.write_file`, magic `MTS1`):

1. **Transpose** — each column's stream is contiguous (stride 1, not 13). This is
   the single biggest structural win; see §3.
2. **Delta** per column. Columns marked `monotonic` (e.g. `time`) use unsigned
   delta with wrap handling; all others zigzag the signed delta.
3. **Varint** (`mints/coding.py`).
4. **tamp** LZ pass, **window=12** (4 KB). tamp was chosen originally for tiny-RAM
   targets; see §5 for why window=12 and why tamp specifically.

The reader (`ShardStoreReader`) detects the `MTS1` magic and decodes column-major;
it still reads legacy row-major shards for backward compatibility.

Measured end-to-end ratio (columnar + tamp): **0.426 active, 0.195 idle**.
vs the old row-major scheme (0.514 active, 0.296 idle): **−17% active,
−34% idle**, ~−22.5% overall across all samples in `data/`.

> Implementation note: generic MicroPython has **no `struct.Struct`** (only
> module-level `pack`/`unpack`/`calcsize`). `mints/shard.py` builds per-column
> `pack` closures over `struct.pack`. Using `struct.Struct` was the root cause of
> the on-device compaction crash that wedged the logger — see the project memory.

---

## 3. Why columnar wins (and is the *only* structural win)

Transposing makes like-valued bytes adjacent, so even a tiny LZ window finds
matches. The advantage **grows** at small windows like tamp's. Everything else
tested fails once the LZ pass runs:

| variant | active ratio | verdict |
|---|---|---|
| row-major delta+zigzag+varint+tamp | ~0.514 | baseline (old) |
| **columnar** delta+zigzag+varint+tamp | **0.426** | **ship** |
| double-delta (delta-of-delta) | worse | amplifies noise |
| cross-column decorrelation | no change | — |
| byte-shuffle | ties | not worth complexity |
| frame-of-reference bit-packing | worse | breaks byte alignment |
| column reorder | negligible | — |
| split `minmax_idx` into 2 cols | worse | cell flips ~60%/sample |
| RLE / change-bitmap | no better | LZ already catches it |
| per-column-separate tamp streams | ≈ concat | no gain |
| cell-max-as-spread, time delta-of-delta | worse | — |

**Do not re-run this micro-tweak search.** It was done exhaustively (2026-05,
re-confirmed 2026-06-30 on the real files above). The data is near its lossless
floor — see §4.

---

## 4. The lossless floor (entropy analysis)

Order-0 entropy of each column's delta stream = the best a per-column entropy
coder (ANS/range coder, the pcodec approach) could achieve. Active file:

| column | entropy B/row | varint B/row | distinct deltas |
|---|---|---|---|
| time | 0.571 | 1.018 | 215 |
| voltage | 0.653 | 1.002 | 246 |
| **current** | **1.142** | 1.517 | **6475** |
| temp | 0.150 | 1.000 | 90 |
| soc | 0.121 | 1.032 | 126 |
| cell_min | 0.721 | 1.009 | 353 |
| cell_max | 0.647 | 1.001 | 202 |
| **minmax_idx** | **0.730** | 1.000 | 123 |
| **TOTAL** | **4.735 (ratio 0.364)** | 8.580 | |

`current` (24%) and `minmax_idx` (15%) dominate and are **real entropy**: current
has ~6.4 A stdev between samples (sensor noise + real ripple); the min/max cell
pointer flips ~60% of samples. The other six columns are already ≤0.73 B/row.

Reference compressors on the columnar varint stream:

| codec | active ratio | idle ratio | notes |
|---|---|---|---|
| order-0 ANS floor (per-col deltas) | 0.364 | 0.184 | theoretical best for delta-ANS |
| columnar + **tamp** (ship) | 0.426 | 0.195 | LZ, no entropy coding |
| columnar + deflate (LZ+Huffman) | 0.376 | 0.169 | |
| columnar + lzma | 0.347 | 0.151 | strong context model |

We ship at 0.426 active. The remaining active gap to deflate is ~5 raw percentage
points (~12% relative to MTS1), and the gap to lzma is ~8 raw points (~19%
relative). That is real, but it is not a second columnar-sized win and it needs a
different *compressor* (§5). The absolute entropy is real, so the downsampler
remains the only order-of-magnitude lever.

---

## 5. Compressor choice: tamp vs deflate vs lzma vs "cook our own"

**Can we beat tamp?** Yes, modestly. **Should we?** Not now.

- **tamp** — pure LZ, window=12 optimal (w13+ measured worse on this data),
  viper-optimized on-device, tiny RAM. The shipping choice.
- **deflate (~−12% active vs MTS1; ~−27% active vs old row-major)** — LZ77 **+** Huffman, i.e. it already *is* the
  "LZ + entropy coding" combo. Decodes **natively in the browser**
  (`DecompressionStream`), which would also fix the web app's missing shard
  decoder. **Blocker:** the on-device MicroPython build exposes `deflate.DeflateIO`
  as **decompress-only** (no streaming compressor), and `install.py` pulls tamp's
  compressor-only package. Switching needs a separate spike: confirm/add a
  streaming deflate compressor on the ESP32 build, measure heap/time on-device,
  then flip extension + header + browser decoder together. **Backlog, not this patch.**
- **lzma (−33%)** — best ratio but too heavy for the device. Reference only.
- **Custom pcodec-style codec (delta → adaptive bins → ANS)?** Measured ceiling =
  the order-0 ANS floor: **0.364 active / 0.184 idle**. That's only ~deflate-level,
  and it **loses to deflate/lzma on the idle file** (0.184 vs 0.169/0.151) because
  a pure delta-ANS coder can't exploit the cross-row LZ matches that long rest
  periods create. pcodec shines on raw structured float arrays; our producer
  already does the quantization/delta that captures pcodec's int-mult/float-mult
  modes, so there's little left for it. The combo we'd actually want (LZ + entropy)
  **already exists and is called deflate**. Verdict: **don't build a bespoke codec**
  — it ties deflate at best, loses on idle data, and costs 3× maintenance
  (Python + MicroPython-without-viper + JS).

**Conclusion:** keep tamp+columnar now. If a codec upgrade is ever worth it, it's
the **deflate spike** (better ratio + browser-native decode), not a custom codec.

---

## 6. Reducing the `current` entropy sink (impedance-safe)

`current` is the only column with real headroom (1.14 B/row). The impedance/SoH
pipeline (separate `pv/bat-impedance` repo) consumes current for exactly two things,
both robust to per-sample quantization noise:

1. **ΔI at load steps** → `R = ΔV/ΔI`. Steps are large (~14 A) and **voltage's
   10 mV resolution is the R bottleneck**, not current (at 6 A, one 10 mV LSB ≈ 30%
   of a 5 mΩ drop). Current was never the limiting factor.
2. **Current integral** (coulomb counting → Qmax/SoC/SoH). Robust as long as
   rounding is **unbiased** — round-to-nearest error averages out over the window.

So current can be snapped to a coarser grid with lossy storage that is still
acceptable for the downstream purpose.
Measured on the active file:

| current grid | entropy B/row | charge err | step ΔI err (max) |
|---|---|---|---|
| ×100 / 0.01 A (today) | 1.142 | — | — |
| **×10 / 0.1 A** | **0.796 (−30%)** | **0.36%** | **0.1 A** |
| ×20 / 0.05 A | 0.902 (−21%) | 0.13% | 0.04 A |
| ×5 / 0.2 A | 0.688 (−40%) | 0.41% | 0.2 A |

(Qmax/SoH need ~1% — so 0.1 A is comfortably safe. Companding and deadband filters
measured *worse*: companding keeps fine steps where most samples sit; deadband
raises charge error.)

**The catch — the codec doesn't reward it.** The 30% entropy drop lives in the
delta-symbol *distribution*; varint ignores magnitude-vs-distinctness and tamp/
deflate only recover a sliver via byte patterns. End-to-end:

| current grid | tamp+columnar | deflate |
|---|---|---|
| ×100 (today) | 0.426 | 0.376 |
| **snap 0.1 A** | **0.413 (−4.2%)** | 0.359 (−4.5%) |
| snap 0.2 A | 0.402 (−7%) | 0.349 (−7%) |

Idle file: snapping barely moves it. So the realized win is
**~2–4% in practice** (full ~7% only under a true integer-ANS coder, which §5 says
isn't worth building).

**Recommendation — the safe, free version (no format change):** snap current to
the 0.1 A grid *in the producer* (`batmon.py`, round to nearest 10 centi-amps
before `add_sample`). Storage stays centi-amp i16 and consumers still ÷100, so old
×100 files and new files both read correctly. **Do not rescale storage to ×10** —
the ×100 factor is implicit in the consumers (browser, bat-impedance), *not* in the
schema filename, so rescaling would silently misread every historical file unless a
version marker is added. Fold the snap in next time `batmon.py` is touched; it's a
one-liner worth ~3%, not a needle-mover on its own.

---

## 7. Lever ranking (where to spend effort)

1. **Downsampler** (`daq/downsample.py`) — **order-of-magnitude** retention. The
   `DOWNSAMPLE_BOOST` knob (`none`/`trimmed`/`full`) + step-gate + rest-heartbeat
   already deliver ~6–8×. This is the lever.
2. **Columnar shards (MTS1)** — −22.6%. Done, shipped.
3. **deflate spike** — ~−12% active vs MTS1, ~−27% active vs old row-major,
   and browser-native decode. Backlog; needs an on-device streaming compressor (§5).
4. **current 0.1 A snap** — ~−3%. Safe/free; fold into `batmon.py` opportunistically.
5. **Custom entropy codec** — not worth it (§5).

Anything beyond the downsampler is second-order. Further gains past the §4 floor
require **lossy quantization** — a product decision, not a codec one.

---

## 8. Cross-implementation sync

The same binary format is parsed in three places — any format change must stay in sync:
- `mints/` (Python, on-device writer + host reader)
- `etc/web/www/struct.mjs` + `index.html` (browser). **Note:** the web app today
  only decodes fixed-width `.bin` frames — it has **no shard decoder** (no `tamp.js`),
  so `.tamp` shards currently arrive raw. Aligning the browser needs either a
  `tamp.js` port or the deflate switch (§5).
- `pv/bat-impedance` (offline analysis reader; assumes current ÷100 — see §6).
