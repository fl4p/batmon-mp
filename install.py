import os

from util import connect_wifi

if 'bdev' in globals() and not isinstance(os.mount()[0][0], os.VfsLfs2):
    print('formatting rootfs as littlefs')
    os.umount('/')
    os.VfsFat.mkfs(bdev)
    os.mount(bdev, '/')
else:
    print('root partition filesystem is already littlefs', os.mount()[0][0])

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
