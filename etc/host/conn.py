import asyncio
import logging

from etc.host.aiobmsble.bms.jikong_bms import BMS
from bleak import BleakScanner
from bleak.exc import BleakError

logging.basicConfig(level=logging.INFO)
logger: logging.Logger = logging.getLogger(__name__)


#import asyncio
#dev = asyncio.run(BleakScanner.find_device_by_name("jk-pak01"))
#bms = BMS(ble_device=dev)
#asyncio.run(bms._connect())
#data = asyncio.run(bms.async_update())
# Configure logging



NAME = "jk-pak01"

async def main(dev_name) -> None:
    """Find a BLE device by name and update its sensor data."""

    device = await BleakScanner.find_device_by_name(dev_name)
    if device is None:
        logger.error("Device '%s' not found.", dev_name)
        return

    logger.info("Found device: %s (%s)", device.name, device.address)
    try:
        bms = BMS(ble_device=device)
        await bms._connect()

        for i in range(0, 10):
            logger.info("Updating BMS data...")
            data = await bms.async_update()
            #print("BMS data: %s", repr(data).replace(", ", ",\n\t"))
            #print('get data from BMS')
            await asyncio.sleep(1)


        #            logger.info("BMS data: %.1f %%  %.1f A  %.0f°", data['battery_level'], data['current'], data['temperature'])

        # v = data['battery_level']
        # print(v)
        # logger.info("BMS data: %s", )

    except BleakError as ex:
        logger.error("Failed to update BMS: %s", ex)


if __name__ == "__main__":
    asyncio.run(main(NAME))
else:
    asyncio.run(main(NAME))
