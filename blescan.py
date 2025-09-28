import asyncio
import aioble

# https://docs.micropython.org/en/latest/library/bluetooth.html

async def main():
    async with aioble.scan(5000, interval_us=30000, window_us=30000, active=True) as scanner:
        async for result in scanner:
            if result.name():
                print(result.name(), list(result.services()))

asyncio.run(main())