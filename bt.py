import asyncio
import os
import sys
from collections import deque

import bluetooth
from bluetooth import UUID
from micropython import const

import aioble
from aioble.client import ClientService
from mints import Store
from util import WriteBuffer

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

services: list = None

# org.bluetooth.service.environmental_sensing
_ENV_SENSE_UUID = bluetooth.UUID(0x5798)

# org.bluetooth.characteristic.temperature
_ENV_SENSE_IO_UUID = bluetooth.UUID(0xe8d7)

#  <Enumeration key="1156" value="Cycling: Power Sensor"
# https://github.com/oesmith/gatt-xml/blob/master/org.bluetooth.characteristic.gap.appearance.xml
_ADV_APPEARANCE_CYCLING_POWER_SENSOR = const(1156)

# Register GATT server.
sense_service = aioble.Service(_ENV_SENSE_UUID)
io_characteristic = aioble.BufferedCharacteristic(
    sense_service, _ENV_SENSE_IO_UUID, write=True, indicate=True, read=True,
)
aioble.register_services(sense_service)

_notification_handlers = {}


def register_notification_handler(char: aioble.Characteristic, func):
    if io_characteristic._value_handle is None:
        raise ValueError('please register char service first')
    assert char._value_handle not in _notification_handlers
    _notification_handlers[char._value_handle] = func


closed = False
_client_conn: aioble.client.DeviceConnection = None
_mtu = 20

store: Store = None

cmd_queue: deque[str] = deque((), 10)
cmd_event = asyncio.ThreadSafeFlag()  # dont use asyncio.Event() here!


def notification_handler(conn_handle: int, notify_data: memoryview):
    cmd = bytes(notify_data[:30])
    print('got notification', conn_handle, notify_data, cmd)
    cmd_queue.append(str(notify_data, 'utf-8'))
    cmd_event.set()


register_notification_handler(io_characteristic, notification_handler)


async def _write(data: memoryview):
    print('write', bytes(data))
    return await io_characteristic.indicate(_client_conn, data, 1000)


w_buf = WriteBuffer(_write, 500)


async def process_command(cmd: str):
    print('process_command', cmd)
    if cmd == 'list':
        list_path = ''
        print("List:", list_path)
        for name, size, typ in os.ilistdir(list_path):
            is_dir = typ == 0x4000
            l = "{}:{}\n".format('D' if is_dir else size, name).encode('ascii')
            print(name, typ, size, l)
            await w_buf.write(l)
            # io_characteristic.write(l, send_update=True)
        await w_buf.flush()
        await w_buf.write(b"\n", flush=True)
        print("")

    elif cmd.startswith('read '):
        fn = cmd[5:]
        print('sending', fn)
        with open(fn, "rb") as f:  # noqa: ASYNC230
            buf = bytearray(_mtu)
            mv = memoryview(buf)
            while n := f.readinto(buf):
                await w_buf.write(mv[:n])
            await w_buf.flush()
            await w_buf.write(b"\n", flush=True)
            # await io_characteristic.write(mv[:n], send_update=True)
    else:
        print('unknown command', cmd)
        # await channel.flush()
        # send_done_notification(connection)


async def command_task():
    while True:
        print('waiting for command..')
        await cmd_event.wait()
        cmd_event.clear()
        print('get event received_write=', received_write)

        if received_write:
            cmd = None
            try:
                cmd = str(io_characteristic.read(), 'utf-8')
                await process_command(cmd)
            except Exception as e:
                print('error processing command', cmd)
                sys.print_exception(e)
                await asyncio.sleep(.2)


# Serially wait for connections. Don't advertise while a central is
# connected.
async def peripheral_task():
    global _client_conn, _mtu
    MTU = 500

    # await process_command("list")

    while True:
        print('advertising')
        async with await aioble.advertise(
                _ADV_INTERVAL_US,
                name="shanty-shunt",
                services=[_ENV_SENSE_UUID],
                appearance=_ADV_APPEARANCE_CYCLING_POWER_SENSOR,
        ) as connection:
            print("Connection from", connection.device)
            _mtu = await connection.exchange_mtu(MTU)
            print('connection MTU', _mtu)
            _client_conn = connection
            cmd_event.set()
            await connection.disconnected(timeout_ms=None)
            print('connection closed.')
            _client_conn = None


received_write = False


def ble_irq(event, data):
    global received_write

    if closed:
        return

    if event == _IRQ_GATTS_WRITE:
        # a write from a central (we are the device)
        conn_handle, attr_handle = data
        received_write = True
        cmd_event.set()
        print('wrote to char', attr_handle)
    elif event == _IRQ_GATTS_READ_REQUEST:
        # Note: This event is not supported on ESP32.
        conn_handle, attr_handle = data
        print('read request', attr_handle)
    elif event == _IRQ_GATTC_NOTIFY:
        conn_handle, value_handle, notify_data = data
        print('notify event', conn_handle, value_handle, bytes(notify_data))
        _notification_handlers[value_handle](conn_handle, notify_data)
        # chars_by_handle[value_handle].notify(_central_conn, notify_data)
    else:
        if event != _IRQ_SCAN_RESULT:
            pass
            # print('irq event', event, data)


def ble_shutdown():
    # global closed
    # closed = True
    pass


async def close():
    global closed
    closed = True
    if _client_conn:
        await _client_conn.disconnect()


def main():
    asyncio.create_task(command_task())
    asyncio.run(peripheral_task())


aioble.core.register_irq_handler(ble_irq, ble_shutdown)

main()
