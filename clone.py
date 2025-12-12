import asyncio
import collections
import sys

from bluetooth import UUID
from micropython import const

import aioble
from aioble.client import ClientService, ClientCharacteristic
from aioble.device import DeviceConnection, DeviceDisconnectedError
from util import display_char, find_device

_ADV_INTERVAL_US = const(250_000)  # How frequently to send advertising beacons.

_FLAG_READ = (0x0002)
_FLAG_WRITE_NO_RESPONSE = (0x0004)
_FLAG_WRITE = (0x0008)
_FLAG_NOTIFY = (0x0010)
_FLAG_INDICATE = (0x0020)

# see https://github.com/micropython/micropython/blob/master/docs/library/bluetooth.rst
_IRQ_GATTS_WRITE = const(3)
_IRQ_GATTS_READ_REQUEST = const(4)
_IRQ_SCAN_RESULT = const(5)
_IRQ_GATTC_NOTIFY = const(18)
_IRQ_CONNECTION_UPDATE = const(27)

rw_queue = collections.deque((), 10)

_per_conn: DeviceConnection = None
_central_conn: DeviceConnection = None

services: list = None
write_chars: list[tuple[aioble.Characteristic, ClientCharacteristic]] = None
chars_by_handle: dict[int, aioble.Characteristic] = {}
scan_result = None


async def data_forward_task(chars: list[tuple[aioble.Characteristic, ClientCharacteristic]],
                            central_conn: DeviceConnection, per_conn: DeviceConnection,
                            subscribe_all=True,
                            ):
    if subscribe_all:
        for c, p in chars:
            if (p.properties & _FLAG_NOTIFY):
                await p.subscribe(notify=True, indicate=False)

    while not closed:
        if not per_conn.is_connected():
            print('connection to peripheral lost')
            break
        if not central_conn.is_connected():
            print('connection to client/central lost')
            break

        try:
            # TODO?
            while False and len(rw_queue):
                conn_handle, attr_handle = rw_queue.popleft()
                print('rw event', conn_handle, attr_handle)

                if per_conn._conn_handle == conn_handle:
                    for c, p in chars:
                        if p._value_handle == attr_handle:
                            v = await p.read(timeout_ms=200)
                            print('per wrote', p, v)
                            send = (c.flags & _FLAG_NOTIFY) or (c.flags & _FLAG_INDICATE)
                            await c.write(v, send_update=send)
                            break
                    else:
                        print('per char handle not found', attr_handle)
                elif central_conn._conn_handle == conn_handle:
                    for c, p in chars:
                        print('central attr handle', c._value_handle, p._value_handle)
                        if c._value_handle == attr_handle:
                            print('central wrote', display_char(c))
                            assert (c.flags & _FLAG_WRITE) or (c.flags & _FLAG_WRITE_NO_RESPONSE)
                            v = await c.read()
                            if v:
                                print('read', v, 'from', display_char(c), 'writing', p)
                                await p.write(v)
                            else:
                                print('read empty')
                            # print('value', v)
                            # await p.write(v)
                            # print('written')
                            break
                    else:
                        print('central char handle not found', attr_handle)
                else:
                    print('rw event with unknown connection handle', conn_handle)

            for s, c in chars:
                assert c._connection() == per_conn

                if len(rw_queue) and ((s.flags & _FLAG_WRITE) or (s.flags & _FLAG_WRITE_NO_RESPONSE)):
                    # client -> proxy -> device
                    v = s.read()
                    if v:
                        print('read', v, 'from', display_char(s))
                        print('  writing', v, 'to', c)
                        await c.write(v)
                        rw_queue.popleft()

        except DeviceDisconnectedError:  # client connection
            print('device disconnected')
            break
        await asyncio.sleep(.2)

    print('data loop ended.')
    await central_conn.disconnect()
    await per_conn.disconnect()


async def clone_services(conn: DeviceConnection):
    services = []
    service: ClientService
    # cannot use nested loops here (ValueError: Discovery in progress)
    async for service in conn.services():
        services.append(service)

    print(' ')
    write_chars = []
    clone_services = []
    for service in services:
        print('cloning service', service.uuid)
        chars: list[ClientCharacteristic] = []
        async for char in service.characteristics():
            chars.append(char)

        svc = aioble.Service(service.uuid)
        for char in chars:
            clone_char = aioble.Characteristic(
                svc, char.uuid,
                read=char.properties & _FLAG_READ,
                write=char.properties & _FLAG_WRITE,
                write_no_response=char.properties & _FLAG_WRITE_NO_RESPONSE,
                notify=char.properties & _FLAG_NOTIFY,
                indicate=char.properties & _FLAG_INDICATE,
                initial=None,
            )
            write_chars.append((clone_char, char))

        clone_services.append(svc)

    return clone_services, write_chars


async def match_chars(per_conn, write_chars):
    per_services = []
    service: ClientService
    # cannot use nested loops here (ValueError: Discovery in progress)
    async for service in per_conn.services():
        per_services.append(service)

    all_chars = {}
    for service in per_services:
        async for char in service.characteristics():
            all_chars[char.uuid] = char

    for i in range(len(write_chars)):
        clone_char: aioble.Characteristic = write_chars[i][0]
        write_chars[i] = clone_char, all_chars[clone_char.uuid]


def ble_irq(event, data):
    if closed:
        return

    if event == _IRQ_GATTS_WRITE:
        conn_handle, attr_handle = data
        if _per_conn and _per_conn._conn_handle == conn_handle:
            print('per wrote', attr_handle)
        elif _central_conn and _central_conn._conn_handle == conn_handle:
            print('central wrote to char', attr_handle)
        rw_queue.append((conn_handle, attr_handle))

    elif event == _IRQ_GATTS_READ_REQUEST:
        # Note: This event is not supported on ESP32.
        conn_handle, attr_handle = data
        print('read request', data)
    elif event == _IRQ_GATTC_NOTIFY:
        conn_handle, value_handle, notify_data = data
        # print('notify event', conn_handle, value_handle, bytes(notify_data))
        chars_by_handle[value_handle].notify(_central_conn, notify_data)
    # elif event == _IRQ_CONNECTION_UPDATE:
    #    conn_handle, conn_interval, conn_latency, supervision_timeout, status =  data
    else:
        if event != _IRQ_SCAN_RESULT:
            pass
            # print('irq event', event, data)


def ble_shutdown():
    pass


closed = False

# Serially wait for connections. Don't advertise while a central is connected.
async def peripheral_task():
    # keep this globally so we can re-use them, since there is no aioble.unregister_services(...)
    global services, write_chars, scan_result

    MTU = 500  # must be lower than (BLE_ATT_MTU_MAX=527)-3 = 524

    while True:
        # aioble.register_services() # clear?

        if closed:
            return

        if services:  # re-use services
            break

        scan_result = await find_device("20:A1:11:02:23:45")
        if not scan_result:
            print('peripheral not found')
            await asyncio.sleep(10)
            continue

        per_conn: DeviceConnection = None

        try:
            per_conn = await scan_result.device.connect()
            print('connected peripheral', scan_result.device.addr)
            services, write_chars = await clone_services(per_conn)
            await per_conn.disconnect()
            aioble.register_services(*services)
            per_conn = None
            print('peripheral successfully cloned', services)
            break
        except Exception as e:
            print('error cloning device')
            sys.print_exception(e)
            if per_conn:
                await per_conn.disconnect()

    assert write_chars

    while True:
        adv_name = (scan_result.name() or 'unknown') + '_cloned'
        print("Waiting for connection from central, adv_name=", adv_name)
        central_conn: DeviceConnection = await aioble.advertise(
            _ADV_INTERVAL_US,
            name=adv_name,
            services=list(scan_result.services()),
        )
        print("Connection from", central_conn.device)
        print('central MTU', await central_conn.exchange_mtu(MTU))

        try:
            print('connecting peripheral')
            per_conn = await scan_result.device.connect()
            await match_chars(per_conn, write_chars)
            for c, p in write_chars:
                chars_by_handle[p._value_handle] = c
        except KeyboardInterrupt:
            raise
        except ValueError as e:
            sys.print_exception(e)
            return
        except Exception as e:
            print('peripheral connection failed', e)
            sys.print_exception(e)
            await central_conn.disconnect()
            await asyncio.sleep(5)
            continue

        global _per_conn, _central_conn
        _per_conn = per_conn
        _central_conn = central_conn

        print('per MTU', await per_conn.exchange_mtu(MTU))
        # await asyncio.sleep(.1)

        print('peripheral successfully connected, starting data pump')

        await data_forward_task(write_chars, central_conn=central_conn, per_conn=per_conn)


def main():
    asyncio.run(peripheral_task())

async def close():
    global closed
    closed = True
    if _per_conn:
        await _per_conn.disconnect()
    if _central_conn:
        await _central_conn.disconnect()


aioble.core.register_irq_handler(ble_irq, ble_shutdown)

#main()
