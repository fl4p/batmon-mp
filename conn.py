import logging
import random
import time

# import influxdb
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
store: Store | None = None

dev_name = "jk-pak01"
DESIGN_CAP = 24


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
    store and store.flush()

    lcd.clear()
    lcd.home()
    lcd.print('Interrupt')

    if bms:
        print('disconnecting bms..')
        await bms.disconnect()


bms: BMS = None


async def main() -> None:
    global bms, store

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
        Col('minmax_idx', 'u8'),
    ])

    async def connect_bms():
        lcd.backlight()
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
            prev_current_mean = -9e9
            prev_voltage = -1
            prev_soc = -1

            data = await bms.async_update()
            cell_num = int(data['cell_count'])
            assert cell_num == len(data['cell_voltages'])
            assert cell_num > 0 and cell_num <= 16
            # we use a single byte to store index of min&max cell, and 16*16=256
            print('cell_num:', cell_num)

            prev_data = {}
            t_last_change = time.time()

            while bms._client.is_connected:
                logger.info("Updating BMS data...")
                data = await bms.async_update()
                now = time.time()

                if prev_data != data:
                    t_last_change = now
                    prev_data = data

                if now - t_last_change > 60:
                    print('data have not change for 60s, assume broken link')
                    break

                # TODO use bms time !
                # print("BMS data: %s", str(data))

                soc = data['battery_level']
                current = data['current']
                voltage = data['voltage']
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

                print(round(now), line0, line1,
                      'soc=', soc,  # data.get("cycle_charge", 0) / data.get("design_capacity", 1) * 100
                      'I=', current)

                current_acc += current
                current_acc_n += 1

                # TODO average current ewma
                # - power jumps

                def rel_err(a, b, reg=1e-3):
                    return abs(a - b) / (abs(b) + reg)

                # if current significantly changed
                if (False
                        # or (abs(current_acc / current_acc_n - prev_current_mean) > DESIGN_CAP * 0.05) # this will let throug noise (daly)
                        # or (current_acc_n > 1 and rel_err(current_acc / current_acc_n, prev_current_mean) > 0.5)
                        or (current_acc_n > 16 and rel_err(current_acc / current_acc_n, prev_current_mean) > 0.3)
                        or int(round(soc)) != int(round(prev_soc))
                        or rel_err(voltage, prev_voltage) > 0.004):  # 0.002
                    print('significant load or soc change current=', prev_current_mean, current_acc / current_acc_n,
                          'voltage=', prev_voltage, voltage, )
                    store_interval = 1  # store now
                elif abs(current) > DESIGN_CAP * 0.05:
                    store_interval = 16
                elif abs(current) > 280 * 0.005:
                    store_interval = 64
                else:
                    store_interval = 256

                store_interval //= 16

                if current_acc_n >= store_interval:
                    current_mean = current_acc / current_acc_n
                    prev_current_mean = current_mean
                    prev_soc = soc
                    prev_voltage = voltage
                    current_acc_n = 0
                    current_acc = 0
                    try:
                        print('store point I=', current_mean)
                        store.add_sample(dict(
                            time=int(now),
                            voltage=data['voltage'],
                            current=current_mean,
                            temp2=((max(-40, temp_mean) + 40) * 2),
                            soc2=(data['battery_level'] * 2),
                            cell_min=cell_min,
                            cell_max=cell_max,
                            minmax_idx=cell_max_idx * cell_num + cell_min_idx,
                        ))
                    except OSError as e:
                        print('could not write sample store, full disk?', e)

                # influxdb.write_point('batmon', dict(device=dev_name), dict(
                #    charge=data['cycle_charge'],
                #    soc=data.get("cycle_charge", 0) / data.get("design_capacity", 0) * 100,
                #    current=current,
                #    voltage=data['voltage']
                # ))

                # for ci in range(cell_num):
                #    influxdb.write_point('cells',
                #                         dict(device=dev_name, cell_index=ci),
                #                         dict(voltage=int(round(cells[ci] * 1000))))

                lcd.clear()
                lcd.print(line0)
                lcd.set_cursor(col=0, row=1)
                lcd.print(line1)
                lcd.home()

                await asyncio.sleep(1)
                si += random.random() * 2
            await bms.disconnect()
        except KeyboardInterrupt as ex:
            logger.error("Exception occurred: %s", ex)

            lcd.clear()
            lcd.home()
            lcd.print("err: %s" % ex)
            await asyncio.sleep(30)
            # break
        finally:
            store.flush()


if __name__ == "__main__":
    asyncio.run(main())
