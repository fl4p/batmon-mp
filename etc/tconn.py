import asyncio
from collections import deque

from bluetooth import UUID

import aioble
from aioble.client import ClientCharacteristic
from aioble.device import DeviceConnection, DeviceDisconnectedError
from util import find_device


async def notify_loop(conn: DeviceConnection, char):
    print('notify loop started.', char)
    await char.subscribe(notify=True, indicate=False)
    buf = deque((), 20)
    while conn.is_connected:
        try:
            data = await char.notified(500)
            buf.append(data)
        except asyncio.TimeoutError:
            while buf:
                data =  buf.popleft()
                print('got notified data', char, len(data), data)
            pass
        except DeviceDisconnectedError:
            break
    print('notify loop ended.')

from micropython import const

_IRQ_GATTS_WRITE = const(3)
_IRQ_GATTS_READ_REQUEST = const(4)
_IRQ_SCAN_RESULT = const(5)
_IRQ_GATTC_NOTIFY = const(18)
_IRQ_CONNECTION_UPDATE = const(27)

def ble_irq(event, data):
    # irq event 3 (2, 16) (read from central)
    if event == _IRQ_GATTS_WRITE:
        conn_handle, attr_handle = data
        print('write event', conn_handle, attr_handle)

    elif event == _IRQ_GATTS_READ_REQUEST:
        # Note: This event is not supported on ESP32.
        conn_handle, attr_handle = data
        print('read request', data)

    elif event == _IRQ_GATTC_NOTIFY:
        conn_handle, value_handle, notify_data = data
        print('notify event', conn_handle, value_handle, bytes(notify_data))
    # elif event == _IRQ_CONNECTION_UPDATE:
    #    conn_handle, conn_interval, conn_latency, supervision_timeout, status =  data
    else:
        if event != _IRQ_SCAN_RESULT:
            print('irq event', event, data)


def ble_shutdown():
    pass


async def main():

    aioble.core.register_irq_handler(ble_irq, ble_shutdown)

    while True:
        scan_result = await find_device("20:A1:11:02:23:45")
        print('found device', scan_result)
        if scan_result:
            break

    conn:DeviceConnection = await scan_result.device.connect()

    await conn.exchange_mtu(200)

    svc = await conn.service(UUID(0xffe0))
    ch: ClientCharacteristic = await svc.characteristic(UUID(0xffe1))

    t = asyncio.create_task(notify_loop(conn, ch))
    await asyncio.sleep(.1)

    while conn.is_connected:
        try:
            s = b'~\xa1\x01\x00\x00\xbe\x18U\xaaU' # bat info
            #print('sending', s)
            #await ch.write(s)
            #await asyncio.sleep(1)

            #s = b'~\xa1\x02l\x02 X\xc4\xaaU'  # dev info
            print('sending', s)
            await ch.write(s)
            await asyncio.sleep(2)
        except KeyboardInterrupt:
            t.cancel()
            await conn.disconnect()
            break


asyncio.run(main())