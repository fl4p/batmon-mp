# MinTS

This is a time series storage for embedded systems for MicroPython, primarely intended for long term data logging.
It will also work in ordinary (non-embedded) python environments.
Querying data and indexing is currently not implemented and probably out of scope of this project.
It rather expects the user to transfer the collected data from the embedded flash for further analysis
on another computer.

It employs common compression techniques, where only value changes are stored (delta or differential coding).
These delta values are then encoded with a variable length integer code, after a ZigZag transform, which optimizes
coding of the sign. A final huffman code tries to further reduce the bit-rate. All compression is lossless.

## Features

* supports `int8`, `uint8`, `int16` , `uint16`, `int32` , `uint32`, `float16`, `float32` data types
* convert stored data into `pandas.DataFrame`
* sharding splits the storage file in multiple chunks (with compression)
* uses common compression methods: delta, zigzag, varint and huffman ([tamp](https://github.com/BrianPugh/tamp/)
  provides the huffman code)
* usual compression ratio is 20 %

## Usage Considerations

For minimum size usage consider these points:

* Avoid `float16` and `float32` as these types currently don't benefit from delta and varint coding and poorly compress
* Use integer types with pre-scaling to get a fixed decimal precision
* Value changes between subsequent samples in the range [-64, 63] are encoded as a single byte
* For time index use the `monotonic=True`. this disables zigzag coding and doubles the range of 1-byte coded numbers (up
  to 127)
* Time is just another observation and since we don't use indexing here it is just like any other column
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

# Compile to C code
```
cython mints/test/test.py
python_root=/Users/fab/miniconda3
gcc -Os -I $python_root/include/python3.13 -o mints_test mints/test/test.c \
    -L$python_root/lib -lpython3.13  -lm -lutil -ldl
```