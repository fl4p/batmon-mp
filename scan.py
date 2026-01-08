import asyncio
import binascii
import time

import aioble

if 0:
    from aioble.central import ScanResult

# TODO last seen
# last Rssi, current rssi, max rssi, avg rssi, num adv packets received


def mean(a):
    a = list(a)
    n = len(a)
    if n == 0: return float('nan')
    return sum(a) / n

async def main():
    devices = {}
    t_out = 0
    t_start = time.time()
    n_out = 0
    while True:
        async with aioble.scan(5000, interval_us=30000, window_us=30000, active=True) as scanner:
            result: 'ScanResult'
            async for result in scanner:
                name = result.name()
                if result.device.addr not in devices:
                    print('found new ble device', result.device.addr, name, result.rssi, list(result.manufacturer()))
                    devices[result.device.addr] = dict(name=name,
                                                       last_rssi=result.rssi,
                                                       tot_rssi=result.rssi,
                                                       frm_rssi=result.rssi,
                                                       n_tot_rssi=1, n_frm_rssi=1,
                                                       max_rssi=result.rssi
                                                       )
                else:
                    d = devices[result.device.addr]
                    if name:
                        d['name'] = name
                    d['last_rssi'] = result.rssi
                    d['tot_rssi'] += result.rssi
                    d['n_tot_rssi'] += 1
                    d['frm_rssi'] += result.rssi
                    d['n_frm_rssi'] += 1
                    if result.rssi > d['max_rssi']:
                        d['max_rssi'] = result.rssi

                if time.time() - t_out >= 2:
                    n_out += 1
                    print('%20s %20s %6s %6s %6s %6s' % ('addr', 'name', 'MXrssi', 'MNrssi', 'TOrssi', '/s'))
                    for a, d in devices.items():
                        mean_rssi = d['frm_rssi'] / d['n_frm_rssi'] if d['n_frm_rssi'] else -999
                        d['n_frm_rssi'] = 0
                        d['frm_rssi'] = 0
                        tot_rssi = d['tot_rssi'] / d['n_tot_rssi'] if d['n_tot_rssi'] else -999
                        print('%20s %20s %6d %6d %6.1f %6.1f' % (
                            binascii.hexlify(a), d['name'], d['max_rssi'], mean_rssi, tot_rssi, d['n_tot_rssi'] / (time.time() - t_start + 1e-9) ))
                    print('%20s %20s %6d %6d %6.1f %6.1f' % (
                        'total %d devs'%len(devices), 'num out=%d' % n_out, max(d['max_rssi'] for d in devices.values()), 0,
                        mean( (d['tot_rssi'] / d['n_tot_rssi'] if d['n_tot_rssi'] else -999) for d in devices.values()),
                        sum(d['n_tot_rssi']  for d in devices.values()) / (time.time() - t_start + 1e-9)))

                    print('')
                    t_out = time.time()


asyncio.run(main())
