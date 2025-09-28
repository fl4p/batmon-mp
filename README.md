
https://github.com/brainelectronics/micropython-i2c-lcd



https://micropython-stubs.readthedocs.io/en/main/typing_mpy.html


# requirements

```


```

# micropython bugs
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
- expose is_connected + connect()
* subscribe
* uptime from bms frame

int.from_bytes(bytearray(b'\x9a\xce\xff\xff'), 'little', True)
4294954650
expected: -12646


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

```

mp:
current bytearray(b'\x9a\xce\xff\xff') little True -32 158 4
22 65% 22ß 4294955A 50V 3506 3649  ¯
current bytearray(b'\x9a\xce\xff\xff') little True -32 158 4
24 65% 22ß 4294955A 50V 3506 3649  ¯
current bytearray(b'`\xcf\xff\xff') little True -32 158 4


mb:
current bytearray(b'%\xd0\xff\xff') little True -32 158 4
INFO:__main__:Updating BMS data...
current bytearray(b'`\xcf\xff\xff') little True -32 158 4
INFO:__main__:Updating BMS data...
current bytearray(b'`\xcf\xff\xff') little True -32 158 4
INFO:__main__:Updating BMS data...
current bytearray(b'\x9a\xce\xff\xff') little True -32 158 4
INFO:__main__:Updating BMS data...
current bytearray(b'\x9a\xce\xff\xff') little True -32 158 4



read_file_to_pandas

322 19% 24ß 5A 51V 3583 3646  Þ
2324 19% 24ß 5A 51V 3584 3646  Þ
2327 19% 24ß 5A 51V 3584 3648  Þ
2329 19% 24ß 5A 51V 3584 3646  Þ
2331 19% 24ß 5A 51V 3584 3648  Þ
2333 19% 24ß 5A 51V 3584 3648  Þ
2335 19% 24ß 5A 51V 3584 3649  Î
2337 19% 24ß 5A 51V 3585 3649  Î

[jk-pak01-time,voltage,current,temp2,soc2,cell_min,cell_max-HeeBBHH.bin](dl/jk-pak01-time%2Cvoltage%2Ccurrent%2Ctemp2%2Csoc2%2Ccell_min%2Ccell_max-HeeBBHH.bin)
write flush 240 bytearray(b'\xfe\x08SR\xf1D\x7f&\xff\r=\x0e\x00\tSR\xf1H\x7f&\xff\r=\x0e\x02\tTRiK\x7f&\xff\r=\x0e\x04\tSR\xf1L\x7f&\xff\r>\x0e\x06\tSR-N\x7f&\x00\x0e>\x0e\x08\tTRiO\x7f&\xff\r>\x0e\n\tTRSP\x7f&\xff\r>\x0e\x0c\tTR\xf1P\x7f&\xff\r>\x0e\x0e\tTR\x8fQ\x7f&\x00\x0e@\x0e\x10\tTR-R\x7f&\xff\r>\x0e\x12\tTR\xcbR\x7f&\xff\r>\x0e\x14\tTRiS\x7f&\x00\x0e>\x0e\x17\tTR\x04T\x7f&\x00\x0e@\x0e\x19\tTRST\x7f&\x00\x0e>\x0e\x1b\tTR\xa2T\x7f&\x00\x0e@\x0e\x1d\tTR\xf1T\x7f&\x00\x0e@\x0e\x1f\tTR@U\x7f&\x00\x0eA\x0e!\tTR\x8fU\x7f&\x01\x0eA\x0e#\tTR\xdeU\x7f&\x00\x0eA\x0e%\tTR-V\x7f&\x00\x0e@\x0e')
write flush 240 bytearray(b'\xa5\tWRA^\x7f&\t\x0eG\x0e\xa7\tXRT^\x7f&\t\x0eH\x0e\xa9\tXRh^\x7f&\n\x0eH\x0e\xab\tXR|^\x7f&\n\x0eH\x0e\xad\tXR\x90^\x7f&\t\x0eH\x0e\xaf\tXR\xa3^\x7f&\t\x0eH\x0e\xb1\tXR\xb7^\x7f&\n\x0eG\x0e\xb3\tXR\xcb^\x7f&\n\x0eG\x0e\xb5\tXR\xdf^\x7f&\n\x0eH\x0e\xb7\tXR\xf2^\x7f&\n\x0eH\x0e\xb9\tXR\x06_\x7f&\n\x0eH\x0e\xbb\tXR\x1a_\x7f&\n\x0eH\x0e\xbd\tXR._\x7f(\n\x0eH\x0e\xc0\tXRA_\x7f(\n\x0eH\x0e\xc2\tXRU_\x7f(\x0b\x0eJ\x0e\xc4\tXRi_\x7f(\x0b\x0eH\x0e\xc6\tXR}_\x7f(\x0b\x0eH\x0e\xc8\tXR\x90_\x7f(\x0b\x0eJ\x0e\xca\tXR\xa4_\x7f(\x0b\x0eJ\x0e\xcc\tYR\xb8_\x7f(\x0b\x0eJ\x0e')
write flush 240 bytearray(b'\xce\tYR\xcc_\x7f(\x0b\x0eJ\x0e\xd0\tYR\xe0_\x7f(\x0b\x0eJ\x0e\xd2\tYR\xf3_\x7f(\x0b\x0eJ\x0e\xd4\tYR\x04`\x7f(\x0b\x0eJ\x0e\xd6\tYR\r`\x7f(\x0c\x0eJ\x0e\xd8\tYR\x17`\x7f(\x0b\x0eK\x0e\xdb\tYR!`\x7f(\x0c\x0eK\x0e\xdd\tYR+`\x7f(\x0c\x0eK\x0e\xdf\tYR5`\x7f(\x0b\x0eK\x0e\xe1\tYR?`\x7f(\x0c\x0eK\x0e\xe3\tYRI`\x7f(\x0c\x0eK\x0e\xe5\tYRS`\x7f(\x0c\x0eK\x0e\xe7\tYR\\`\x7f(\x0c\x0eK\x0e\xe9\tZRf`\x7f(\x0c\x0eK\x0e\xeb\tZRp`\x7f(\x0c\x0eK\x0e\xed\tZRz`\x7f(\x0c\x0eL\x0e\xef\tZR\x84`\x7f(\r\x0eL\x0e\xf1\tZR\x8e`\x7f(\r\x0eL\x0e\xf3\tZR\x98`\x7f(\r\x0eL\x0e\xf5\tZR\xa2`\x7f(\r\x0eL\x0e')
2552 20% 24ß 5A 51V 3596 3659  Î

```