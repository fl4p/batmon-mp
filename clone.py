import asyncio
import collections
import sys

from micropython import const

import aioble
from aioble.client import ClientService, ClientCharacteristic
from aioble.device import DeviceConnection, DeviceDisconnectedError
from service import BaseService
from util import display_char, find_device

_ADV_INTERVAL_US = const(250_000)  # How frequently to send advertising beacons.

_FLAG_READ = 0x0002
_FLAG_WRITE_NO_RESPONSE = 0x0004
_FLAG_WRITE = 0x0008
_FLAG_NOTIFY = 0x0010
_FLAG_INDICATE = 0x0020

# see https://github.com/micropython/micropython/blob/master/docs/library/bluetooth.rst
_IRQ_GATTS_WRITE = const(3)
_IRQ_GATTS_READ_REQUEST = const(4)
_IRQ_SCAN_RESULT = const(5)
_IRQ_GATTC_NOTIFY = const(18)
_IRQ_CONNECTION_UPDATE = const(27)


async def clone_services(conn: DeviceConnection):
    services = []
    service: ClientService
    # cannot use nested loops here (ValueError: Discovery in progress)
    async for service in conn.services():
        services.append(service)

    print(' ')
    write_chars = []
    cloned_services = []
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

        cloned_services.append(svc)

    return cloned_services, write_chars


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


class CloneService(BaseService):
    def __init__(self):
        super().__init__()
        self.closed = False

        self.rw_queue = collections.deque((), 10)

        self._per_conn: DeviceConnection | None = None
        self._central_conn: DeviceConnection | None = None

        self.services: list | None = None
        self.write_chars: list[tuple[aioble.Characteristic, ClientCharacteristic]] | None = None
        self.chars_by_handle: dict[int, aioble.Characteristic] = {}
        self.scan_result = None

        aioble.core.register_irq_handler(self.ble_irq, self.ble_shutdown)

    async def start(self, background: bool, args: dict):
        coro = self.peripheral_task(args['dev_name'])
        return asyncio.create_task(coro) if background else await coro

    async def stop(self):
        await self.close()

    async def close(self):
        self.closed = True
        if self._per_conn:
            await self._per_conn.disconnect()
        if self._central_conn:
            await self._central_conn.disconnect()

    async def data_forward_task(self, chars: list[tuple[aioble.Characteristic, ClientCharacteristic]],
                                central_conn: DeviceConnection, per_conn: DeviceConnection,
                                subscribe_all=True,
                                ):
        if subscribe_all:
            for c, p in chars:
                if (p.properties & _FLAG_NOTIFY):
                    await p.subscribe(notify=True, indicate=False)

        while not self.closed:
            if not per_conn.is_connected():
                print('connection to peripheral lost')
                break
            if not central_conn.is_connected():
                print('connection to client/central lost')
                break

            try:
                """
                # TODO?
                while False and len(self.rw_queue):
                    conn_handle, attr_handle = self.rw_queue.popleft()
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
                """

                for s, c in chars:
                    assert c._connection() == per_conn

                    # TODO here we just iterate over all chars, try to read them and pop from the rw queue if success
                    # the queue acts nothing more than a counter
                    if len(self.rw_queue) and ((s.flags & _FLAG_WRITE) or (s.flags & _FLAG_WRITE_NO_RESPONSE)):
                        # central -> proxy -> device
                        v = s.read()
                        if v:
                            print('read', v, 'from', display_char(s))
                            print('  writing', v, 'to', c)
                            await c.write(v)
                            self.rw_queue.popleft()

            except DeviceDisconnectedError:  # client connection
                print('device disconnected')
                break
            await asyncio.sleep(.2)

        print('data loop ended.')
        await central_conn.disconnect()
        await per_conn.disconnect()

    def ble_irq(self, event, data):
        if self.closed:
            return

        if event == _IRQ_GATTS_WRITE:
            conn_handle, attr_handle = data
            if self._per_conn and self._per_conn._conn_handle == conn_handle:
                print('per wrote', attr_handle)
            elif self._central_conn and self._central_conn._conn_handle == conn_handle:
                print('central wrote to char', attr_handle)
            self.rw_queue.append((conn_handle, attr_handle))

        elif event == _IRQ_GATTS_READ_REQUEST:
            # Note: This event is not supported on ESP32.
            # conn_handle, attr_handle = data
            print('read request', data)
        elif event == _IRQ_GATTC_NOTIFY:
            # forward notifications
            conn_handle, value_handle, notify_data = data
            self.chars_by_handle[value_handle].notify(self._central_conn, notify_data)
        # elif event == _IRQ_CONNECTION_UPDATE:
        #    conn_handle, conn_interval, conn_latency, supervision_timeout, status =  data
        else:
            if event != _IRQ_SCAN_RESULT:
                pass
            # print('irq event', event, data)

    def ble_shutdown(self):
        print('ble shutdown')
        asyncio.run(self.close())

    # Serially wait for connections. Don't advertise while a central is connected.
    async def peripheral_task(self, dev_name):
        # keep this globally so we can re-use them, since there is no aioble.unregister_services(...)
        # global services, write_chars, scan_result

        MTU = 500  # must be lower than (BLE_ATT_MTU_MAX=527)-3 = 524

        while True:
            # aioble.register_services() # clear?

            if self.closed:
                return

            if self.services:  # re-use services
                break

            self.scan_result = await find_device(dev_name)
            if not self.scan_result:
                print('peripheral not found')
                await asyncio.sleep(10)
                continue

            per_conn: DeviceConnection | None = None

            try:
                per_conn = await self.scan_result.device.connect()
                print('connected peripheral', self.scan_result.device.addr)
                self.services, self.write_chars = await clone_services(per_conn)
                await per_conn.disconnect()
                aioble.register_services(*self.services)
                per_conn = None
                print('peripheral successfully cloned', self.services)
                break
            except Exception as e:
                print('error cloning device')
                sys.print_exception(e)
                if per_conn:
                    await per_conn.disconnect()

        assert self.write_chars, "no write chars"

        while not self.closed:
            adv_name = (self.scan_result.name() or 'unknown') + '_cloned'
            print("Waiting for connection from central, adv_name=", adv_name)
            central_conn: DeviceConnection = await aioble.advertise(
                _ADV_INTERVAL_US,
                name=adv_name,
                services=list(self.scan_result.services()),
            )
            print("Connection from", central_conn.device)
            print('central MTU', await central_conn.exchange_mtu(MTU))

            try:
                print('connecting peripheral')
                per_conn = await self.scan_result.device.connect()
                await match_chars(per_conn, self.write_chars)
                for c, p in self.write_chars:
                    self.chars_by_handle[p._value_handle] = c
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

            self._per_conn = per_conn
            self._central_conn = central_conn

            print('per MTU', await per_conn.exchange_mtu(MTU))
            print('peripheral successfully connected, starting data pump')

            await self.data_forward_task(self.write_chars, central_conn=central_conn, per_conn=per_conn)


def main():
    svc = CloneService()
    asyncio.run(svc.peripheral_task("20:A1:11:02:23:45"))

# main()
