_FLAG_READ = (0x0002)
_FLAG_WRITE_NO_RESPONSE = (0x0004)
_FLAG_WRITE = (0x0008)
_FLAG_NOTIFY = (0x0010)
_FLAG_INDICATE = (0x0020)

async def find_device(dev_name) -> 'ScanResult':
    import binascii
    import aioble

    try:
        addr = binascii.unhexlify(dev_name.replace(":", ""))
    except:
        addr = None

    async with aioble.scan(5000, interval_us=30000, window_us=30000, active=True) as scanner:
        async for result in scanner:
            if result.name():
                print('found ble device', result.device.addr, result.name())
            if result.name() == dev_name or (addr and result.device.addr == addr):
                return result
    print('ble device not found', dev_name)
    return None


def display_char(c): # 'aioble.Characteristic | aioble.client.ClientCharacteristic'
    flags = ('_FLAG_READ', '_FLAG_WRITE_NO_RESPONSE', '_FLAG_WRITE', '_FLAG_NOTIFY', '_FLAG_INDICATE')
    fs = ''
    cf = c.flags if hasattr(c, 'flags') else c.properties
    for f in flags:
        if cf & globals()[f]:
            fs += f[6:] + ','
    return f'<Characteristic({c.uuid},{c._value_handle},flags={fs})>'


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

def connect_wifi():
    import json
    import network
    sta_if = network.WLAN(network.WLAN.IF_STA)
    if not sta_if.isconnected():
        with open('wifi-secret.json', 'r') as f:
            print('connecting to network...', json.load(f)[0])
            sta_if.active(True)
            sta_if.connect(*json.load(f))
        while not sta_if.isconnected():
            pass
    print('network config:', sta_if.ipconfig('addr4'))
