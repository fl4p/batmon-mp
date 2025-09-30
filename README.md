# batmon-mp

Monitor your batteries over Bluetooth LE on MicroPython.
Includes HD44780 driver and time series storage for embedded flash storage.

# Install

If your board has wifi, copy `install.py` and run `import install.py` in the REPL.
If not, install the dependency using `mpremote mip ...`.
You'll find the list in `install.sh`.

Then copy these files to your device:

```
boot.py
conn.py
store.py
aiobmsble/*
lib/enum/*
```

Edit conn.py:

```
from aiobmsble.bms.jikong_bms import BMS  # adjust this import for your BMS

dev_name = "jk-pak01"   # BMS name
DESIGN_CAP = 24         # battery design capacity
```

Then reset the board and it should connect. See REPL for any errors.

This project is heavily WIP.

# Dev Notes

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