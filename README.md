# batmon-mp

*This project is heavily WIP.*

Monitor and data logger for your batteries using Bluetooth LE on MicroPython.
Includes HD44780 driver for live monitoring and a data logger that writes to the flash storage.

This project basically consists of 4 standalone programs:

* INA228 battery monitor (`shunt.py`)
    * high precision 20-bit battery monitor (current & voltage)
    * SoC gauge
* BLE device repeater  (`clone.py`)
    * extent Bluetooth range by "repeating" / "cloning" a device
    * supports GATT writes (central→peripheral) and notifications (peripheral→central)
* BMS Data logger (`batmon.py`)
    * uses a port of `aiobmsble` to connect to various BMS over BLE
    * displays battery data on HD44780 LCD
    * stores highly compressed data to flash memory
* BLE file server (`ble_filesrv.py`)
    * download and view history in your Browser (Android, Windows, Linux, macOS)
    * [web app](https://fl4p.github.io/batmon-mp/etc/web/www/)

# Install

Install the MicroPython image on the microcontroller (for example using Thonny). For ESP8266 i had issues with deploying
using Thonny, following
the [guide](https://docs.micropython.org/en/latest/esp8266/tutorial/intro.html#deploying-the-firmware) here worked.

### If your board has Wi-Fi:

If your board has Wi-Fi, create the file `wifi-secret.json` (locally in the `batmon-mp` directory where this readme is):

```
["<wifi network name>", "<wifi password>"]
```

Then copy `install.py`, `util.py` and the newly created file and run `install.py`:

```
mpremote cp install.py :
mpremote cp util.py :
mpremote cp wifi-secret.json :
mpremote run install.py
```

### If your board does not have WiFi:

Install the dependencies using `mpremote mip install aioble abc logging types github:brainelectronics/micropython-i2c-lcd github:josverl/micropython-stubs/mip/typing.json github:brianpugh/tamp/package-compressor.json`.
You'll find the full list in `install.py`.

## Copy files

Then copy these files to your device:

```
mpremote cp service.py clone.py batmon.py :
mpremote cp -r mints/ aiobmsble/ bleak/ lib/enum/ :
```

```
mpremote cp boot.py :boot2.py
mpremote run boot2.py
```

Edit `batmon.py`:

```
from aiobmsble.bms.jikong_bms import BMS  # adjust this import for your BMS

dev_name = "jk-pak01"   # BMS name
DESIGN_CAP = 24         # battery design capacity
```

Then reset the board and it should connect. See REPL for any errors.

For developing you can use `mpremote mount` to avoid the need to upload files each time they change:

```
mpremote mount .
```

## Data Logging

Using an optimized time series storage engine, the program records the following battery data:

* timestamp (uint16)
* voltage (float16)
* current (float16)
* temperature (uint8)
* soc (uint8)
* min cell voltage in mV (uint16)
* max cell voltage in mV (uint16)
* index of min & max cell (uint8)

The resulting data frame has 13 bytes.
The sampling rate slows down when current is close to zero and will increase with rising current
or if voltage or soc reported by the BMS change significantly.
If the database file reaches a certain size (~256kB) it is compressed
and the program creates a new storage files (sharding).
You can copy these shards any time from the device.
With a 2 MB flash memory, it can capture up to 1 year of battery data. This strongly depends on battery usage.

With an ESP32 you'll get a battery logger for just about $2.

## Efficient time series storage

When comparing embedded flash storage with ordinary SSDs we find two main differences:
it is small and it wears out quickly.
Most flashes have a block size of 256 bytes. Only a full block can be erased, that means, if only one byte is written to
a
block, and we want to write another, the whole block needs to be erased first and then re-writing the already present
byte and
the new byte. Flash cells have a lifetime of around 100k erases.

https://github.com/micropython/micropython/tree/master/lib/oofatfs

* oofatfs uses `disk_write` (defined
  here https://github.com/micropython/micropython/blob/master/extmod/vfs_fat_diskio.c)
* `disk_write` uses
  `mp_vfs_blockdev_write` https://github.com/micropython/micropython/blob/master/extmod/vfs_blockdev.c#L90
* https://elm-chan.org/fsw/ff/
  https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-guides/file-system-considerations.html

* buffer data in memory until we can write a block
* varint coding most effective with delta coding
* for non-monotonic series, prior to varint apply zigZagcoding to delta values to move the sign to the end

# Dev Notes

## mpremote

```
# mount – mount the local directory on the remote device:
$ mpremote mount [options] <local-dir>



```

## micropython bugs

```
>>> f"{a.f(':')}"
Traceback (most recent call last):
  File "<stdin>", line 1
SyntaxError: invalid syntax



[*[1]]

bytearray.clear not impl


bytearray.copy
bytearray.decode(errors="replace")


async def loop():
     for i in range(1,10):
         asyncio.sleep(1)
         print('sleep..')
         
         
        
ble_bms:
[x]- expose is_connected + connect()
[x] subscribe

* uptime from bms frame
* jk use charge/cap to find soc
* cycle_capacity vs capacity vs charge confusion?
* balance current not correct?
* now way to check if data has arrived (JK)
* cycle_capacity: int | float  # [Wh]
* jk design_capacity missing
* jikong uptime

https://github.com/micropython/micropython/blob/e3ef68215605938c906196ae37120950d0eb6105/py/objint.c#L398
https://docs.micropython.org/en/latest/genrst/builtin_types.html#to-bytes-method-doesn-t-implement-signed-parameter
int.from_bytes(bytearray(b'\x9a\xce\xff\xff'), 'little', True)
4294954650
expected: -12646
https://github.com/micropython/micropython/issues/15399



```

# Micropython dev

https://github.com/JetBrains/intellij-micropython
https://docs.micropython.org/en/latest/reference/packages.html
https://github.com/micropython/micropython-lib/blob/master/micropython/bluetooth/aioble/examples/temp_client.py
https://github.com/ekspla/micropython_aioble_examples
https://randomnerdtutorials.com/getting-started-thonny-micropython-python-ide-esp32-esp8266/

# Compression

zstd
https://manishrjain.com/compression-algo-moving-data
https://cran.r-project.org/web/packages/brotli/vignettes/brotli-2015-09-22.pdf

current issue:

# TODO

- send udp pakets (influxdb line proto)
    - issue influxdb v1 needs timestamp
- clone bms to act as a proxy
- store: delta+varint coding + zigzag?