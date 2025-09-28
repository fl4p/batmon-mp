from boot import connect_wifi

connect_wifi()

import mip

deps = [
    'aioble',
    'github:brainelectronics/micropython-i2c-lcd',
    'github:josverl/micropython-stubs/mip/typing.json',
    'logging',
    'abc',
    'types',]

for dep in deps:
    mip.install(dep)
