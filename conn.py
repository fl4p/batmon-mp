import logging
import random
import time

from aiobmsble.bms.jikong_bms import BMS
from bleak import BleakScanner
from store import Store, Col

# logging.basicConfig(level=logging.DEBUG)
logger: logging.Logger = logging.getLogger(__name__)

import asyncio

from lcd_i2c import LCD
from machine import I2C, Pin

# PCF8574 on 0x50
I2C_ADDR = 0x27  # DEC 39, HEX 0x27
NUM_ROWS = 2
NUM_COLS = 16
i2c = I2C(0, scl=Pin(2), sda=Pin(1), freq=800000)
lcd = LCD(addr=I2C_ADDR, cols=NUM_COLS, rows=NUM_ROWS, i2c=i2c)

dev_name = "jk-pak01"


def argmax(a):
    ind = 0
    max_ele = a[0]

    for i in range(1, len(a)):
        if a[i] > max_ele:
            max_ele = a[i]
            ind = i
    return ind


def argmin(a):
    ind = 0
    max_ele = a[0]

    for i in range(1, len(a)):
        if a[i] < max_ele:
            max_ele = a[i]
            ind = i
    return ind


async def close():
    lcd.clear()
    lcd.home()
    lcd.print('Interrupt')

    if bms:
        print('disconnecting bms..')
        await bms.disconnect()


bms: BMS = None


async def main() -> None:
    global bms

    lcd.begin()
    lcd.clear()
    lcd.print("Hello World!")

    store = Store(dev_name, [
        Col('time', 'u16'),
        Col('voltage', 'f16'),
        Col('current', 'f16'),
        Col('temp2', 'u8'),  # y = (x+40)*2, so temperates [-40, 88] can stored
        Col('soc2', 'u8'),
        Col('cell_min', 'u16'),
        Col('cell_max', 'u16'),
        Col('cell_idx', 'u8'),
    ])

    async def connect_bms():
        lcd.set_cursor(col=0, row=1)
        lcd.print("Connecting " + dev_name)
        lcd.blink()

        device = await BleakScanner.find_device_by_name(dev_name)
        if device is None:
            logger.error("Device '%s' not found.", dev_name)
            lcd.set_cursor(col=0, row=1)
            lcd.print('Device not found')

        else:
            return device

    connect_tries = 0
    while True:
        try:
            device = await connect_bms()

            if not device:
                await asyncio.sleep(10)
                connect_tries += 1
                if connect_tries > 3:
                    raise Exception("Connection timed out")
                else:
                    continue

            lcd.set_cursor(col=0, row=1)
            lcd.print("Found " + dev_name + "    ")
            logger.info("Found device: %s (%s)", device.name, device.address)

            bms = BMS(ble_device=device, keep_alive=True)
            await bms._connect()
            print('connected bms!')

            lcd.set_cursor(col=0, row=1)
            lcd.print("Connected!")
            lcd.no_blink()
            lcd.no_cursor()
            lcd.home()

            lcd.backlight()
            lcd_bl_state = True
            t0 = time.time()

            def set_backlight(on):
                nonlocal lcd_bl_state
                if on == lcd_bl_state: return
                lcd.backlight() if on else lcd.no_backlight()
                lcd_bl_state = on

            status_chars = 175, 188, 194  # https://www.seetron.com/bpk000/bpk000prog.html
            status_chars_empty = 222, 206

            si = 0.0

            current_acc = 0
            current_acc_n = 0

            data = await bms.async_update()
            cell_num = int(data['cell_count'])
            assert cell_num == len(data['cell_voltages'])
            assert cell_num > 0 and cell_num <= 16
            # we use a single byte to store index of min&max cell, and 16*16=256

            while bms._client.is_connected:
                logger.info("Updating BMS data...")
                data = await bms.async_update()
                now = time.time()
                # TODO use bms time !
                # print("BMS data: %s", str(data))

                soc = data['battery_level']
                current = data['current']
                cells = data['cell_voltages']

                sc = status_chars if soc > 20 else status_chars_empty

                if soc < 15 and current < -4:
                    set_backlight(not lcd_bl_state)  # blink low soc
                else:
                    set_backlight(current > 1 or current < -10 or now - t0 < 120)  # pos => charging

                cell_min = min(cells) * 1000
                cell_max = max(cells) * 1000
                cell_min_idx = argmin(cells)
                cell_max_idx = argmax(cells)

                temp_mean = sum(data['temp_values']) / (
                        len(data['temp_values']) + 1e-9)  # regularization to prevent `ZeroDivisionError:

                show_idx = int(si) % 6 == 0 or int(si - 1) % 6 == 0
                line0 = "%.0f%% %.0f\xDF%s%s%.0fA %.0fV" % (
                    soc, temp_mean,
                    ' ' if current >= +0 else '',
                    '.' if abs(current) < 0.95 else '',
                    current if abs(current) >= 0.95 else (current * 10), data['voltage'])
                line1 = "%4d %4d  %s" % (
                    cell_min if not show_idx else cell_min_idx,
                    cell_max if not show_idx else cell_max_idx,
                    chr(sc[int(si / 5) % len(sc)]))

                print(round(now), line0, line1, 'I=', current)

                current_acc += current
                current_acc_n += 1

                if current_acc_n == 4:
                    current = current_acc / current_acc_n
                    current_acc_n = 0
                    current_acc = 0
                    try:
                        store.add_sample(dict(
                            time=int(now),
                            voltage=data['voltage'],
                            current=current,
                            temp2=((max(-40, temp_mean) + 40) * 2),
                            soc2=(data['battery_level'] * 2),
                            cell_min=cell_min,
                            cell_max=cell_max,
                            cell_idx=cell_max * cell_num + cell_min,
                        ))
                    except OSError as e:
                        print('could not write sample store, full disk?', e)

                lcd.clear()
                lcd.print(line0)
                lcd.set_cursor(col=0, row=1)
                lcd.print(line1)
                lcd.home()

                await asyncio.sleep(2)
                si += random.random() * 2

            print('disconnected bms!')
        except KeyboardInterrupt as ex:
            logger.error("Exception occurred: %s", ex)

            lcd.clear()
            lcd.home()
            lcd.print("err: %s" % ex)
            await asyncio.sleep(30)
            # break


if __name__ == "__main__":
    asyncio.run(main())
