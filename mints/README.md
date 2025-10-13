# MinTS

This is a time series storage for embedded systems for MicroPython, primarely intended for long term data logging.
It will also work in ordinary (non-embedded) python environments.

Querying data and indexing is currently not implemented and probably out of scope of this project.
It rather expects the user to transfer the collected data from the embedded flash for further analysis
on another computer. There your can use `Store.read_file_to_pandas()` to read the file into a pandas DataFrame.

It employs common compression techniques, where only value changes are stored (delta or differential coding).
These delta values are then encoded with a variable length integer code, after a ZigZag transform, which optimizes
coding of the sign. A final huffman code tries to further reduce the bit-rate. All compression is lossless.

## Example

first create a `Store` object with path to write to and all columns:

```
from mints Store, Col
store = Store('/battery_log', [
    Col('time', 'u16', monotonic=True),  # this can overflow, see below
    Col('voltage', 'f16'),
    Col('current', 'f16'),
    Col('soc', 'u8'),
])

```

check the `DTypes` in `__init__.py` to see all supported types.
Prefer integer types as they compress much better (see below).

Then you can add samples:

```
store.add_sample(dict(
    time=int(time.time()),
    voltage=0,
    current=0,
    soc=0.
))
```

Here time will overflow after 32768 (2**15) seconds (9.1h). This is not a problem because the `read_file_to_pandas()`
will handle the overflown time index and create a monotonic index. Just make sure to pass `monotonic=True` to the
`Col()` constructor. If you need unix timestamping (with ntp sync over wifi or so) use `u32`.

Samples will be added row-wise to a fixed frame length file. Once that reaches a certain size, it compresses integers
with delta, varint/VQL and zigzag coding an passes the buffer through `tamp` compression lib.
float compression is possible, but not yet implemented (need to evaluate [vf128](https://github.com/michaeljclark/vf128)
and μ-law coding for lossy floating point compression).

more examples in

* [test](test)
* see https://github.com/fl4p/batmon-mp/blob/master/batmon.py

## Features

* supports `int8`, `uint8`, `int16` , `uint16`, `int32` , `uint32`, `float16`, `float32` data types
* convert stored data into `pandas.DataFrame`
* sharding splits the storage file in multiple chunks (with compression)
* uses common compression methods: delta, zigzag, varint and huffman ([tamp](https://github.com/BrianPugh/tamp/)
  provides the huffman code)
* usual compression ratio is 20 % of (`len(compressed)/len(raw input)`)

## Usage Considerations

For minimum size usage consider these points:

* Avoid `float16` and `float32` as these types currently don't benefit from delta and varint coding and poorly compress
* Use integer types with pre-scaling to get a fixed decimal precision
* Value changes between subsequent samples in the range [-64, 63] are encoded as a single byte
* For time index use the `monotonic=True`. this disables zigzag coding and doubles the range of 1-byte coded numbers (up
  to 127)
* Time is just another observation and since we don't use indexes here it is just like any other column
* `uint16` for storing the timestamp is enough for most of the use cases. Integer overflow is internally handled
* Think about what precision do you really need. For many applications a time resolution of 10 seconds is enough.
  this keeps the encoded timestamps 1 byte long for sampling intervals up to 1270 seconds.
  If you sample every 21 minutes, the timestamp is encoded within a single byte
* You might want to try different values for `TAMP_WINDOW`, which controls the window size of the huffman code

## Example: Battery Management System

TODO

## References

* protobuf
* https://tdengine.com/compressing-time-series-data/
* https://github.com/BrianPugh/tamp/
