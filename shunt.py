"""
Battery Charge Gauge
- use ina228 to for charge, energy counting
- lifepo4: set battery percentages 0 ... 100%
    - 100: 3.4
    - 0: 3.088 (24.7)
"""
import asyncio
import json
import math
import os
import random
import sys
import time

from machine import Pin, I2C

from daq import ina228
from daq.downsample import Downsampler
from mints import file_exists, Store, Col
from service import BaseService
from util import BoolHysteresisVar

# setup falling edge interrupt ALERT

VOLT_EOC = 27.2
VOLT_EMPTY = 24.7
BAT_CAP = 280  # Ah
BAT_ENERGY = 3.3 * 8 * 280  # Wh


async def main():
    # alert = Pin(40) #  esp32:19, esp32s3:40 TODO
    sda = Pin(42, Pin.IN, Pin.PULL_DOWN)  # 21(esp32) => 42(esp32s3)
    scl = Pin(38, Pin.IN, Pin.PULL_DOWN)  # 15(esp32), esp32s3: 48

    # sda.init(Pin.OUT,value=0)
    # scl.init(Pin.OUT,value=0)

    assert sda.value(), "sda low"
    assert scl.value(), "scl low"
    # assert alert.value(), "alert low"

    i2c = I2C(0,
              sda=sda,
              scl=scl,  # cant use 22, see https://github.com/orgs/micropython/discussions/15507
              freq=400_000)
    print('i2c scan result:', i2c.scan())

    # (1.052*512)/20
    ina228.INA228_ADC_MODE = 0xF  # U,I,T
    ina228.INA228_VTCT_CONV_TIME = 0x01  # 84 µS
    ina228.INA228_ADCRANGE = 1  # 0x1 - ±40.96 mV
    ina228.INA228_ADC_AVG = 0x6  # => 512

    ina = ina228.INA228(i2c, shunt_ohms=0.001)
    ina.configure()
    ina.get_manufacturer_id()
    ina.get_deviceid()
    ina.reset_energy()

    store = Store('shanty-shunt', [
        Col('time', 'u16', monotonic=True),
        Col('voltage', 'u16'),
        Col('current', 'i16'),
        Col('temp2', 'u8'),
        Col('charge', 'i16'),  # [C] (note: 280Ah = 1e6C)
        Col('energy', 'i16'),  # ina228 ENERGY is positive only, for compat use signed type
        Col('gaugeQ', 'i16'),
        Col('gaugeE', 'i16'),
        Col('soc2', 'u8'),
    ])

    ds = Downsampler(BAT_CAP)

    gauge = {}
    if file_exists('gauge.json'):
        with open('gauge.json', 'r') as f:
            try:
                gauge = json.load(f)
            except json.decoder.JSONDecodeError as e:
                sys.print_exception(e)
                with open('gauge.json.%dbak' % random.randint(1, 10000), 'w') as f2:
                    f.seek(0, os.SEEK_SET)  # TODO
                    f2.write(f.read())
    else:
        print('gauge.json not found')

    if not gauge:
        gauge = dict(charge=BAT_CAP / 2, energy=BAT_ENERGY / 2)
        print('init gauge', gauge)

    q_gauge = float(gauge['charge'])
    e_gauge = float(gauge['energy'])

    def soc():
        return q_gauge / 3600 / BAT_CAP * 100
        # return e_gauge / BAT_ENERGY * 100

    soc_last_store = soc()

    prev_e = math.nan
    prev_q = math.nan

    bat_conn = BoolHysteresisVar(False, VOLT_EMPTY * 0.5, VOLT_EMPTY * 0.7)
    print('BatConn Hysteresis Thresholds', bat_conn.thres0, bat_conn.thres1)
    n_empty = 0

    while True:
        time.sleep(0.4)
        alrt = ina.read_diag_alrt()
        # print('alrt diag', bin(alrt))

        # TODO recover from overflow (40bit registers)
        if ina228.DIAG_ALERT_FLAGS.CHARGEOF(alrt):
            print('CHARGEOF')
            prev_q = math.nan
        if ina228.DIAG_ALERT_FLAGS.ENERGYOF(alrt):
            print('ENERGYOF')
            prev_e = math.nan

        if ina228.DIAG_ALERT_FLAGS.CNVRF(alrt):
            # print('CNVRF')
            t = time.time()
            i = ina.get_current()
            u = ina.get_vbus_voltage()
            e = ina.get_energy()
            q = ina.get_charge()
            tmp = ina.get_temp_voltage()

            dE = e - prev_e
            prev_e = e

            dQ = q - prev_q
            prev_q = q

            if math.isfinite(dE):
                e_gauge += dE

            if math.isfinite(dQ):
                q_gauge += dQ

            bat_chg = bat_conn.update(u)
            if bat_chg:
                print('  battery', 'connected' if bat_conn else 'disconnected', ' U=', round(u,2))

            if u > VOLT_EOC:
                q_gauge = BAT_CAP
                e_gauge = BAT_ENERGY
            elif u < VOLT_EMPTY:
                if bat_conn:
                    n_empty += 1
                    if n_empty >= 20:
                        print('  battery empty, counters reset')
                        q_gauge = 0
                        e_gauge = 0
                        n_empty = 0
                else:
                    n_empty = 0  # reset counter
            else:
                n_empty = 0

            print(t, 'BatConn', bat_conn, 'n_empty=', n_empty,
                  'I=%.3fA U=%.2fV Ecnt=%.3fWh Qcnt=%.3fAh Egau=%.3fWh Qgau=%.3fAh SoC=%.2f%%' % (
                      i, u, e/3600, q/3600, e_gauge/3600, q_gauge/3600, soc()))

            if ds.update(soc(), current=i, voltage=u):
                print('store point I=', ds.current_mean)
                store.add_sample(dict(
                    time=int(math.ceil(t / 10)),  # ceil: prevents look-ahead
                    voltage=int(round(u * 100)),
                    current=int(round(i * 100)),
                    temp2=int(round((max(-40, tmp) + 40) * 2)),
                    charge=q,
                    energy=e,
                    gaugeQ=q_gauge,
                    gaugeE=e_gauge,
                    soc2=int(round(soc() * 2)),
                ))

        if abs(soc() - soc_last_store) > 0.1:
            print('writing', 'soc', soc(), dict(charge=q_gauge, energy=e_gauge))
            with open('gauge.json', 'w') as f:
                json.dump(dict(charge=q_gauge, energy=e_gauge), f)
            soc_last_store = soc()


class ShuntService(BaseService):
    async def stop(self):
        raise NotImplementedError()

    async def start(self, background: bool, args: dict):
        t = main()
        if background:
            asyncio.create_task(t)
        else:
            await t


service = ShuntService

if __name__ == '__main__':
    asyncio.run(main())
