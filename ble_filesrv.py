import asyncio
import os
import sys

import bluetooth
from micropython import const

import aioble
from aioble.client import ClientService
# from mints import Store
from service import BaseService
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
_IRQ_GATTS_INDICATE_DONE = const(20)

services: list | None = None

_ENV_SENSE_UUID = bluetooth.UUID(0x5798)  # org.bluetooth.service.environmental_sensing
_ENV_SENSE_IO_UUID = bluetooth.UUID(0xe8d7)  # org.bluetooth.characteristic.temperature

# https://github.com/oesmith/gatt-xml/blob/master/org.bluetooth.characteristic.gap.appearance.xml
_ADV_APPEARANCE_CYCLING_POWER_SENSOR = const(1156)



class BleFileServer(BaseService):
    def __init__(self):
        BaseService.__init__(self)

        self._client_conn: aioble.client.DeviceConnection | None = None
        self._closed = True
        self._mtu = 20

        async def _write(data: memoryview):
            # print('write', len(data), bytes(data))
            # print('write', len(data), ' '.join(map(lambda i:f"{hex(i)[2:]:0>{5-len(hex(i))}}", data )))
            return await self.io_char.indicate(_client_conn, data, 1000)

        self.w_buf = WriteBuffer(_write, 500 - 3)

        # Register GATT server.
        sense_service = aioble.Service(_ENV_SENSE_UUID)
        self.io_char = aioble.BufferedCharacteristic(
            sense_service, _ENV_SENSE_IO_UUID, write=True, indicate=True, read=True,
            max_len=500 - 3
        )

        self._cmd_event = asyncio.ThreadSafeFlag()  # dont use asyncio.Event() here!
        self._received_write = False

        aioble.core.register_irq_handler(self.ble_irq, self.ble_shutdown)
        aioble.register_services(sense_service)

    async def start(self, background, args):
        self._closed = False
        asyncio.create_task(self._command_task())

        pt = self._peripheral_task(args['advertising_name'])
        if background:
            asyncio.create_task(pt)
        else:
            asyncio.run(pt)

    async def stop(self):
        self._closed = True
        if self._client_conn:
            await _client_conn.disconnect()

    async def _command_task(self):
        while True:
            print('waiting for command..')
            await self._cmd_event.wait()
            self._cmd_event.clear()

            if received_write:
                cmd = None
                try:
                    cmd = str(self.io_char.read(), 'utf-8')
                    await self._process_command(cmd)
                except Exception as e:
                    print('error processing command', cmd)
                    sys.print_exception(e)
                    await asyncio.sleep(.2)

    async def _process_command(self, cmd: str):
        w_buf = self.w_buf
        print('process_command', cmd)
        if cmd == 'list':
            list_path = '.'
            print("List:", list_path)
            for name in os.listdir(list_path):
                fp = list_path + '/' + name
                st = os.stat(fp)
                print(fp, st)
                is_dir = not (st[0] >> 15)
                size = st[6]
                if is_dir or size <= 0:
                    continue
                l = "{}:{}\n".format('D' if is_dir else size, name).encode('ascii')
                await w_buf.write(l)
            await w_buf.flush()
            await w_buf.write(b"\n", flush=True)
            print("")

        elif cmd.startswith('read '):
            fn = cmd[5:]
            print('sending', fn, os.stat(fn))
            with open(fn, "rb") as f:  # noqa: ASYNC230
                buf = bytearray(_mtu - 3)
                mv = memoryview(buf)
                while n := f.readinto(buf):
                    await w_buf.write(mv[:n])
                await w_buf.flush()
                await w_buf.write(b"\n", flush=True)
        else:
            print('unknown command', cmd)

    async def _peripheral_task(self, name):
        global _client_conn, _mtu, received_write
        MTU = 500

        while True:
            print('advertising')
            async with await aioble.advertise(
                    _ADV_INTERVAL_US,
                    name=name,
                    services=[_ENV_SENSE_UUID],
                    appearance=_ADV_APPEARANCE_CYCLING_POWER_SENSOR,
            ) as connection:
                print("Connection from", connection.device)
                _mtu = await connection.exchange_mtu(MTU)
                print('connection MTU', _mtu)
                _client_conn = connection
                received_write = False
                # cmd_event.set()
                await connection.disconnected(timeout_ms=None)
                print('connection closed.')
                _client_conn = None
                received_write = False

    def ble_irq(self, event, data):
        global received_write

        cmd_event = self._cmd_event

        if self._closed:
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
            # _notification_handlers[value_handle](conn_handle, notify_data)
            # chars_by_handle[value_handle].notify(_central_conn, notify_data)
        else:
            if event != _IRQ_SCAN_RESULT:
                pass  # print('irq event', event, data)

    def ble_shutdown(self):
        # closed = True
        pass


Service = BleFileServer

# TODO removed, notification handlers are only valid for centrals (not when acting as peripheral device)
"""
_notification_handlers = {}
def register_notification_handler(char: aioble.Characteristic, func):
    if io_characteristic._value_handle is None:
        raise ValueError('please register char service first')
    assert char._value_handle not in _notification_handlers
    _notification_handlers[char._value_handle] = func

cmd_queue: deque[str] = deque((), 10) # TODO remove
def notification_handler(conn_handle: int, notify_data: memoryview):
    cmd = bytes(notify_data[:30])
    print('got notification', conn_handle, notify_data, cmd)
    cmd_queue.append(str(notify_data, 'utf-8'))
    cmd_event.set()
register_notification_handler(io_characteristic, notification_handler)
"""

