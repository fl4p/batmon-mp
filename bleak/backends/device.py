from aioble.central import ScanResult
from aioble.device import DeviceConnection


class BLEDevice:
    def __init__(self, scan_result: ScanResult):
        self.scan_result = scan_result
        self.address = scan_result.device.addr

    @property
    def name(self):
        return self.scan_result.name()

    #    @property
    #    def services(self):
    #        return self.aioble_connection.services()
    # return self.scan_result.services()

    @property
    def aioble_connection(self) -> DeviceConnection:
        return self.scan_result.device._connection
