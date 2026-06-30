# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A **MicroPython** battery-monitoring and data-logging project that runs on ESP32/ESP8266
microcontrollers. Most code is deployed to and executes *on the device*; a smaller set of
host-side tooling (`bleak/` shim, `etc/host/`, the browser web app) lets parts run/test on desktop
CPython. The repo is heavily WIP.

It bundles four independent on-device programs (see README.md for user-facing detail):
- `shunt.py` — INA228 high-precision current/voltage monitor + SoC gauge
- `clone.py` — BLE repeater that clones a peripheral's GATT services to extend range
- `batmon.py` — connects to a BMS over BLE, drives an HD44780 LCD, logs compressed data to flash
- `ble_filesrv.py` — serves logged data files over BLE for browser download

## Deploy & run on device

Deployment is via `mpremote` (no build step). Two install paths:
- `./install-with-wifi.sh` — board has Wi-Fi; runs `install.py` on-device to format LittleFS and
  `mip install` deps from the network.
- `./install-without-wifi.sh` — installs deps from host, copies files.

Common workflow:
```bash
mpremote mount .          # mount local dir on device — edit locally, no re-upload per change
mpremote run boot.py      # run the entry point
mpremote cp <file> :      # copy a single file to device
```
Dependencies (aioble, logging, abc, tamp, lcd driver, typing stubs) are listed in `install.py`
and vendored as `.mpy`/packages under `lib/`.

## Tests

Tests live in `test/` and `mints/test/` and run with **pytest from the repo root** (they use
package-relative imports like `from .. import Store`). pytest is not in `.venv`; install it into
the environment you run from.
```bash
pytest                              # all tests
pytest mints/test/test.py           # the storage-engine tests
pytest mints/test/test.py::test_store
```

## Architecture

### Service model and entry point
`boot.py` is the device entry point. It instantiates one or more services and runs them: the
**last** service blocks (foreground), earlier ones start in the background. Any unhandled
exception triggers `machine.reset()` after a delay — the device is expected to run unattended and
self-recover. Which services run is selected by editing the `services` list in `boot.py`.

All four programs implement `BaseService` (`service.py`): an abstract `async start(background, args)`
/ `async stop()` pair. This is the seam between `boot.py` and each program.

### BLE stack: the bleak shim (key indirection)
`aiobmsble/` is a vendored port of the Home Assistant `aiobmsble` library, containing protocol
implementations for **many BMS brands** under `aiobmsble/bms/` (jikong, daly, ant, jbd, seplos, …).
That library is written against the desktop **`bleak`** API. To run it unmodified on-device,
`bleak/` is a **MicroPython shim that reimplements the `bleak` API on top of `aioble`** (e.g.
`BleakScanner.find_device_by_name` wraps `aioble.scan`). So: BMS protocol code imports `bleak` →
`bleak/` shim → `aioble` → on-device BLE. To support a new BMS, change the
`from aiobmsble.bms.<x> import BMS` line and `dev_name`/`DESIGN_CAP` in `batmon.py`.

### Time-series storage engine (`mints/`)
Custom flash-optimized columnar store; this is the heart of the data logger. Design notes in
README ("Efficient time series storage") and `mints/__init__.py`.

- **Schema is encoded in the filename**: `{name}-{col1,col2,...}-{structfmt}.bin`. No separate
  header. `Store.read_file_to_pandas` reconstructs schema purely from the name. `Col`/`DTypes`
  map names like `u16`/`i16`/`f16` to `struct` format chars.
- **Hot tier (`.bin`)**: fixed-width `struct`-packed frames, append-only. Writes are buffered to a
  256-byte (flash-page-aligned) buffer and flushed per fill — minimizes flash-block erases (cells
  wear out ~100k erases). Crash-resilient: only the unflushed tail is lost; complete frames remain
  parseable.
- **Cold tier (`.tamp` shards)**: when the hot file exceeds ~256 KB, `compress_data_file()` rewrites
  it via `ShardStore`/`ShardStoreReader` (`mints/shard.py`) using delta-coding, zig-zag for signed
  columns, varint (`mints/coding.py`), then a `tamp` LZ pass, and starts a fresh hot file
  ("sharding"). Columns marked `monotonic=True` (e.g. `time`) skip zig-zag.
- The **same binary format is parsed in the browser** by `etc/web/www/struct.mjs` for the download
  web app. Any format change must stay in sync across `mints/` (Python) and `etc/web/www/` (JS).

Domain quantization happens in the producer (`batmon.py`), not the store: voltage/current ×100,
`temp→(t+40)*2` into u8, `soc×2` into u8, cells in mV, and two cell indices packed into one byte
(`max_idx*n + min_idx`). Note: `time` is a u16 of seconds-since-boot/10. There is **no RTC**, so
absolute wall-clock time is unavailable by design — a reset (which is not expected during normal
operation) is an unbounded, unrecoverable gap regardless of format. The store therefore only
guarantees monotonic ordering within a continuous run; the `+1` step on a backwards `time` value is
the intended handling, not a defect.

### Data acquisition (`daq/`)
- `daq/ina228.py` — INA228 driver.
- `daq/downsample.py` — `Downsampler`: adaptive sampling. Stores a point only when current jumps,
  SoC changes, or voltage moves significantly; otherwise stretches the interval (slower logging
  near zero current). `batmon.py`/`shunt.py` gate every `store.add_sample` through it.
  After a real **current step** (≥`BOOST_STEP_FRAC`·design_cap, ~14 A) it opens a *boost window*
  that oversamples the voltage relaxation tail for the offline impedance/SoH fits (the separate
  `pv/bat-impedance` repo); SoC/voltage-only changes store a single sample but do **not** boost
  (that spurious boosting was the main flash-retention sink). The boost size is the
  retention⇄impedance knob: **`DOWNSAMPLE_BOOST`** in `batmon.py` picks a `BOOST_PROFILES` preset —
  `'full'` (~67 samples/event, full V(t) tail), `'trimmed'` (~17 samples/~150 s, impedance-grade,
  the current default) or `'none'` (1 sample/event, longest retention, no relaxation tail → no R
  estimate). The rest-tier heartbeat (`REST_HEARTBEAT`, ~6 min) is kept fast enough to preserve the
  OCV/Qmax rest anchors the SoH pipeline needs.

## Conventions & gotchas

- Code must run under **MicroPython**, which lacks many CPython features. README "micropython bugs"
  lists known traps actively hit here: no `int.from_bytes(..., signed=True)`, no `bytearray.clear`,
  limited f-string parsing, etc. Prefer the patterns already used in-tree over idiomatic CPython.
- BLE constants/IRQ codes are duplicated as `const(...)` across `clone.py`/`ble_filesrv.py` — match
  the existing style rather than refactoring into a shared module (import cost matters on-device).
- `.bin*`, `.tamp`, `.mpy`, and secret files (`wifi-secret.json`, `ble_secrets.json`) are
  gitignored. `lib/` vendored deps are also gitignored.
