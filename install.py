from boot import connect_wifi

connect_wifi()

import mip

deps = [
    'aioble',
    'github:brainelectronics/micropython-i2c-lcd',
    'github:josverl/micropython-stubs/mip/typing.json',
    'logging',
    'abc',
    'types',
    'github:brianpugh/tamp/package-compressor.json',
]

for dep in deps:
    mip.install(dep)
