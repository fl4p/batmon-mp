import asyncio
import binascii
import time

import aioble

if 0:
    from aioble.central import ScanResult


async def main():
    devices = {}
    t_out = 0
    while True:
        async with aioble.scan(5000, interval_us=30000, window_us=30000, active=True) as scanner:
            result: 'ScanResult'
            async for result in scanner:
                name = result.name()
                if result.device.addr not in devices:
                    print('found new ble device', result.device.addr, name, result.rssi)
                    devices[result.device.addr] = dict(name=name, last_rssi=result.rssi, sum_rssi=result.rssi, n_rssi=1, max_rssi=result.rssi)
                else:
                    d = devices[result.device.addr]
                    if name:
                        d['name'] = name
                    d['last_rssi'] = result.rssi
                    d['sum_rssi'] += result.rssi
                    d['n_rssi'] += 1
                    if result.rssi > d['max_rssi']:
                        d['max_rssi'] = result.rssi

                if time.time() - t_out > .5:
                    for a, d in devices.items():
                        mean_rssi = d['sum_rssi'] / d['n_rssi'] if d['n_rssi'] else -999
                        d['n_rssi'] = 0
                        d['sum_rssi'] = 0
                        print('%20s %20s %6d %6d' % (binascii.hexlify(a), d['name'], d['max_rssi'], mean_rssi))
                    print('')
                    t_out = time.time()


asyncio.run(main())
