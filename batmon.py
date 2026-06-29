"""

TODO:
better capture peaks (in-rush motor)

"""
import sys

from daq.downsample import Downsampler
from service import BaseService

sys.path.append("/remote/lib")

import asyncio
import logging
import math
import random
import time

#- noinspection PyUnresolvedReferences

from lcd_i2c import LCD
from machine import I2C, Pin

#  # adjust this import for your BMS

from bleak import BleakScanner
from mints import Store, Col

from aiobmsble.bms.jikong_bms import BMS

dev_name = "JKPferdestall"  # # BMS name

# from aiobmsble.bms.ant_bms import BMS
# dev_name = "ANT-BLE20PHUB"

DESIGN_CAP = 280  # # battery design capacity

# Logger data-rate vs flash-retention knob (see Downsampler.BOOST_PROFILES). The
# boost window oversamples the voltage relaxation tail after each load step for
# the offline impedance/OCV fits; trimming it trades that fidelity for retention:
#   'full'    -> impedance-grade,  shortest retention (~1 month on 1.4 MB)
#   'trimmed' -> coarse tau fit,   ~mid retention
#   'none'    -> no relaxation tail, longest retention (~1 year; pre-impedance)
DOWNSAMPLE_BOOST = 'trimmed'

# PCF8574 on 0x50
I2C_ADDR = 0x27  # DEC 39, HEX 0x27
NUM_ROWS = 2
NUM_COLS = 16
i2c = I2C(0, scl=Pin(2), sda=Pin(1), freq=800000)
lcd: LCD = None
store: Store | None = None

# reset if no fresh BMS data for this long (stuck-BLE watchdog)
WD_STALE_MS = 30000
_last_update_ms = None

# periodically re-init the LCD: the HD44780 over a PCF8574 backpack can silently
# lose its config from I2C glitches on long unattended runs and show garbage
# while the chip keeps running. begin() blocks ~1s, so don't do it every loop.
LCD_REINIT_S = 120

# logging.basicConfig(level=logging.DEBUG)
logger: logging.Logger = logging.getLogger(__name__)


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

    if lcd:
        lcd.clear()
        lcd.home()
        lcd.print('Interrupt')

    if bms:
        print('disconnecting bms..')
        await bms.disconnect()


bms: BMS | None = None


async def connect_bms(tries=3):
    while True:
        if lcd:
            lcd.backlight()
            lcd.set_cursor(col=0, row=1)
            lcd.print("Connecting " + dev_name)
            lcd.blink()

        print('Finding BLE device', dev_name)
        await asyncio.sleep(.2)
        device = await BleakScanner.find_device_by_name(dev_name)
        print('found', device)
        await asyncio.sleep(.2)
        if device is None:
            logger.error("Device '%s' not found.", dev_name)
            if lcd:
                lcd.set_cursor(col=0, row=1)
                lcd.print('Device not found')
            if tries == 0:
                raise Exception("Connection timed out")
            await asyncio.sleep(10)
            tries -= 1

        else:
            if lcd:
                lcd.set_cursor(col=0, row=1)
                lcd.print("Found " + dev_name + "    ")
            logger.info("Found device: %s (%s)", device.name, device.address)

            return device

def reset_lcd():
    if lcd:
        lcd.begin()


async def _data_watchdog():
    import machine
    try:
        wdt = machine.WDT(timeout=30000)
    except Exception as e:
        print('WDT init failed:', e)
        wdt = None
    while True:
        if wdt:
            wdt.feed()
        await asyncio.sleep(2)
        if _last_update_ms is None:
            continue
        if time.ticks_diff(time.ticks_ms(), _last_update_ms) > WD_STALE_MS:
            print('watchdog: no BMS data -> reset')
            try:
                store and store.flush()
            except Exception:
                pass
            time.sleep_ms(200)
            machine.reset()


async def main() -> None:
    # import batmon; import asyncio; asyncio.run(batmon.main())
    global bms, store, lcd, _last_update_ms

    try:
        lcd = LCD(addr=I2C_ADDR, cols=NUM_COLS, rows=NUM_ROWS, i2c=i2c)
        lcd.begin()
        lcd.clear()
        lcd.print("Hello World!")
    except:
        lcd = None

    store = Store(dev_name, [
        Col('time', 'u16', monotonic=True),
        Col('voltage', 'u16'),
        Col('current', 'i16'),
        Col('temp2', 'u8'),  # y = (x+40)*2, so temperates [-40, 88] can stored
        Col('soc2', 'u8'),
        Col('cell_min', 'u16'),
        Col('cell_max', 'u16'),
        Col('minmax_idx', 'u8'),
    ])

    asyncio.create_task(_data_watchdog())

    while True:
        try:
            print('connect_bms')
            device = await connect_bms(tries=3)

            bms = BMS(ble_device=device, keep_alive=True)
            await bms._connect()
            print('connected bms!')

            lcd_bl_state = True
            if lcd:
                reset_lcd()
                lcd.set_cursor(col=0, row=1)
                lcd.print("Connected!")
                lcd.no_blink()
                lcd.no_cursor()
                lcd.home()
                lcd.backlight()

            t0 = time.time()
            t_last_lcd_reset = t0

            def set_backlight(on):
                nonlocal lcd_bl_state
                if not lcd or on == lcd_bl_state: return
                lcd.backlight() if on else lcd.no_backlight()
                lcd_bl_state = on

            status_chars = 175, 188, 194  # https://www.seetron.com/bpk000/bpk000prog.html
            status_chars_empty = 222, 206

            si = 0.0

            ds = Downsampler(design_cap=DESIGN_CAP, boost=DOWNSAMPLE_BOOST)

            data = await bms.async_update()
            _last_update_ms = time.ticks_ms()
            cell_num = int(data['cell_count'])
            assert cell_num == len(data['cell_voltages'])
            assert cell_num > 0 and cell_num <= 16  # we use a single byte to store index of min&max cell, and 16*16=256
            print('cell_num:', cell_num)

            prev_data = {}
            t_last_change = time.time()

            while bms._client.is_connected:
                logger.info("Updating BMS data...")
                data = await bms.async_update()
                _last_update_ms = time.ticks_ms()
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
                    set_backlight(True or current > 1 or current < -1 or now - t0 < 120)  # pos => charging

                cell_min = min(cells) * 1000
                cell_max = max(cells) * 1000
                cell_min_idx = argmin(cells)
                cell_max_idx = argmax(cells)

                temp_mean = sum(data['temp_values']) / (
                        len(data['temp_values']) + 1e-9)  # regularization to prevent `ZeroDivisionError:

                volt = data['voltage']

                show_idx = int(si) % 6 == 0 or int(si - 1) % 6 == 0
                line0 = "%.0f%%" "%s%.0fW %s%s%.0fA %.0fV" % (
                    soc,
                    '+' if current >= +0 else '-', abs(current * volt),
                    '+' if current >= +0 else '-', '.' if abs(current) < 0.95 else '',
                    abs(current if abs(current) >= 0.95 else (current * 10)), volt)
                line1 = "%4d %4d %.0f\xDF %s" % (
                    cell_min if not show_idx else cell_min_idx,
                    cell_max if not show_idx else cell_max_idx,
                    temp_mean, chr(sc[int(si / 5) % len(sc)]))

                print(round(now), line0, line1,
                      'soc=', soc,  # data.get("cycle_charge", 0) / data.get("design_capacity", 1) * 100
                      'I=', current)

                if ds.update(soc=soc, current=current, voltage=voltage):
                    try:
                        print('store point I=', ds.current_mean)
                        store.add_sample(dict(
                            time=int(math.ceil(now / 10)),  # ceil: prevents look-ahead
                            voltage=int(round(data['voltage'] * 100)),
                            current=int(round(ds.current_mean * 100)),
                            temp2=int(round((max(-40, temp_mean) + 40) * 2)),
                            soc2=int(round(data['battery_level'] * 2)),
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

                # periodically re-init the LCD to recover from a glitched
                # controller (begin() preserves backlight state via _backlightval)
                if lcd and now - t_last_lcd_reset > LCD_REINIT_S:
                    reset_lcd()
                    t_last_lcd_reset = now

                if lcd:
                    lcd.clear()
                    lcd.print(line0)
                    lcd.set_cursor(col=0, row=1)
                    lcd.print(line1)
                    lcd.home()

                await asyncio.sleep(2)
                si += random.random() * 2
            await bms.disconnect()
        except Exception as ex:
            # KeyboardInterrupt is a BaseException, so it is NOT caught here and
            # propagates up to boot.py for a graceful service stop. Every other
            # error (BLE/GATT failures, timeouts, missing data keys, asserts) is
            # logged and we fall through to `while True` to reconnect, instead of
            # escaping main() and triggering machine.reset().
            logger.error("Exception occurred: %s", ex)
            sys.print_exception(ex)

            if lcd:
                lcd.clear()
                lcd.home()
                lcd.print("err: %s" % ex)

            if bms:
                try:
                    await bms.disconnect()
                except Exception as de:
                    print('error disconnecting bms during recovery', de)

            await asyncio.sleep(10)
            # loop back and reconnect
        finally:
            store.flush()


class Batmon(BaseService):
    def __init__(self):
        super().__init__()

    async def start(self, background: bool, args: dict):
        assert not background, "background must be False"
        await main()

    async def stop(self):
        await close()


service = Batmon

if __name__ == "__main__":
    asyncio.run(main())

# import batmon; import asyncio; asyncio.run(batmon.main())
