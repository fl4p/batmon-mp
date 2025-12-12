import asyncio
import binascii
import collections
import sys

from bluetooth import UUID
from micropython import const

import aioble
from aioble.central import ScanResult
from aioble.client import ClientService, ClientCharacteristic
from aioble.device import DeviceConnection, DeviceDisconnectedError

# from typing import List, Tuple

_ADV_INTERVAL_US = const(250_000)  # How frequently to send advertising beacons.

_FLAG_READ = (0x0002)
_FLAG_WRITE_NO_RESPONSE = (0x0004)
_FLAG_WRITE = (0x0008)
_FLAG_NOTIFY = (0x0010)
_FLAG_INDICATE = (0x0020)

_per_conn: DeviceConnection = None
_central_conn: DeviceConnection = None
services: list = None
write_chars: list[tuple[aioble.Characteristic, ClientCharacteristic]] = None
scan_result = None


def display_char(c: aioble.Characteristic | aioble.client.ClientCharacteristic):
    flags = ('_FLAG_READ', '_FLAG_WRITE_NO_RESPONSE', '_FLAG_WRITE', '_FLAG_NOTIFY', '_FLAG_INDICATE')
    fs = ''
    cf = c.flags if hasattr(c, 'flags') else c.properties
    for f in flags:
        if cf & globals()[f]:
            fs += f[6:] + ','
    return f'<Characteristic({c.uuid},{c._value_handle},flags={fs})>'


async def notify_loop(char: ClientCharacteristic, central_conn, central_char: aioble.Characteristic):
    print('notify loop started', char)
    await char.subscribe(notify=True, indicate=False)
    buf = collections.deque((), 20)
    while True:
        try:
            data = await char.notified(500)
            buf.append(data)
        except asyncio.TimeoutError:
            if buf:
                print('notification timeout, flush', len(buf))
            while buf:
                data = buf.popleft()
                print('fwd notify data', central_char, len(data), data)
                central_char.notify(central_conn, data)
                await asyncio.sleep(.05)
        except DeviceDisconnectedError:
            break
    print('notify loop ended.', char, 'central_conn=', central_conn.is_connected())


async def data_forward_task(chars: list[tuple[aioble.Characteristic, ClientCharacteristic]],
                            central_conn: DeviceConnection, per_conn: DeviceConnection,
                            poll_read=False,
                            subscribe_all=True,
                            ):
    if subscribe_all:
        for c, p in chars:
            if (p.properties & _FLAG_NOTIFY):
                # print('subscribing', display_char(p))
                asyncio.create_task(notify_loop(p, central_conn, c))

    # await asyncio.sleep(1)

    # await p.write(b'~\xa1\x01\x00\x00\xbe\x18U\xaaU')

    # svc = await per_conn.service(UUID(0xffe0))
    # ch: aioble.client.ClientCharacteristic = await svc.characteristic(UUID(0xffe1))
    # print('subscribe', display_char(ch))
    # await ch.subscribe(notify=True, indicate=False)
    # await ch.write(b'~\xa1\x01\x00\x00\xbe\x18U\xaaU')
    # n = await ch.notified(4000)
    # print('notified1', n)

    # if subscribe_all:
    #    for c, p in chars:
    #        if (c.flags & _FLAG_NOTIFY):  # or (c.flags & _FLAG_INDICATE):
    #            print('subscribe', display_char(p))
    # await p.write(b'~\xa1\x01\x00\x00\xbe\x18U\xaaU')
    #            await p.subscribe((c.flags & _FLAG_NOTIFY), indicate=(c.flags & _FLAG_INDICATE))
    # print('chars', p, ch, id(p), id(ch))
    #            await asyncio.sleep(.2)
    #            await p.write(b'~\xa1\x01\x00\x00\xbe\x18U\xaaU')
    # n = await p.notified(4000)
    # print('notified2', n, 'from', display_char(c))
    while True:
        if not per_conn.is_connected():
            print('connection to peripheral lost')
            break
        if not central_conn.is_connected():
            print('connection to client/central lost')
            break

        try:
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

                if poll_read and (s.flags & _FLAG_READ):
                    print('reading per char', c.uuid, c._connection()._conn_handle, c._value_handle)
                    # client <- proxy <- device
                    try:
                        v = await c.read(timeout_ms=20)
                        if v:
                            send = (s.flags & _FLAG_NOTIFY) or (s.flags & _FLAG_INDICATE)
                            print('writing', v, 'char', c.uuid, 'send=', send)
                            s.write(v, send_update=send)
                    except asyncio.TimeoutError:
                        pass

                if len(rw_queue) and ((s.flags & _FLAG_WRITE) or (s.flags & _FLAG_WRITE_NO_RESPONSE)):
                    # client -> proxy -> device
                    v = s.read()
                    if v:
                        print('read', v, 'from', display_char(s))
                        print('  writing', v, 'to', c)
                        await c.write(v)
                        rw_queue.popleft()

                if False and (s.flags & _FLAG_NOTIFY):
                    # client <- proxy <- device (push)
                    try:
                        data = await c.notified(timeout_ms=20)
                        print('per notified', c, data)
                        if data:
                            s.notify(central_conn, data)
                    except asyncio.TimeoutError:
                        pass

                if False and (s.flags & _FLAG_INDICATE):
                    # client <- proxy <- device (ACKed push)
                    try:
                        data = await c.indicated(timeout_ms=20)
                        if data:
                            await s.indicate(central_conn, data, timeout_ms=1000)
                    except asyncio.TimeoutError:
                        pass

        except DeviceDisconnectedError:  # client connection
            print('device disconnected')
            break
        await asyncio.sleep(.2)

    print('data loop ended.')
    await central_conn.disconnect()
    await per_conn.disconnect()


async def get_char(conn: DeviceConnection, char_id):
    services = []
    service: ClientService
    # cannot use nested loops here (ValueError: Discovery in progress)
    async for service in conn.services():
        services.append(service)
    for service in services:
        print('cloning service', service.uuid)
        chars: list[ClientCharacteristic] = []
        async for char in service.characteristics():
            chars.append(char)


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


async def find_device(dev_name) -> ScanResult:
    try:
        addr = binascii.unhexlify(dev_name.replace(":", ""))
    except:
        addr = None

    async with aioble.scan(5000, interval_us=30000, window_us=30000, active=True) as scanner:
        async for result in scanner:
            if result.name():
                print('found ble device', result.device.addr, result.name(), result.rssi)
            if result.name() == dev_name or (addr and result.device.addr == addr):
                return result
    print('ble device not found', dev_name)
    return None


# see https://github.com/micropython/micropython/blob/master/docs/library/bluetooth.rst
_IRQ_GATTS_WRITE = const(3)
_IRQ_GATTS_READ_REQUEST = const(4)
_IRQ_SCAN_RESULT = const(5)
_IRQ_CONNECTION_UPDATE = const(27)

rw_queue = collections.deque((), 10)


def ble_irq(event, data):
    # irq event 3 (2, 16) (read from central)
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
    # elif event == _IRQ_CONNECTION_UPDATE:
    #    conn_handle, conn_interval, conn_latency, supervision_timeout, status =  data
    else:
        if event != _IRQ_SCAN_RESULT:
            pass
            # print('irq event', event, data)


def ble_shutdown():
    pass


# Serially wait for connections. Don't advertise while a central is
# connected.
async def peripheral_task():
    # keep this globally so we can re-use them
    # since there is no aioble.unregister_services(...)
    global services, write_chars, scan_result

    MTU = 500  # must be lower than (BLE_ATT_MTU_MAX=527)-3 = 524

    while True:
        # aioble.register_services() # clear?

        if services:
            # re-use services
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

            # svc = await per_conn.service(UUID(0xffe0))
            # ch: aioble.client.ClientCharacteristic = await svc.characteristic(UUID(0xffe1))
            # print('subscribe', display_char(ch))
            # await ch.subscribe(notify=True, indicate=False)
            ## r =            (b'~\xa1\x01\x00\x00\xbe\x18U\xaaU', b'~\xa1\x02l\x02 X\xc4\xaaU')
            # await ch.write(b'~\xa1\x01\x00\x00\xbe\x18U\xaaU')
            # n = await ch.notified(4000)
            # print('notified', n)

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

        # write_task = asyncio.create_task(data_forward_task(write_chars, connection, svr_conn))
        await data_forward_task(write_chars, central_conn=central_conn, per_conn=per_conn)
        # write_task.cancel()
        # await connection.disconnected()

    # write_task.cancel()


# Run both tasks.
def main():
    asyncio.run(peripheral_task())


aioble.core.register_irq_handler(ble_irq, ble_shutdown)

main()
