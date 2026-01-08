#!/usr/bin/env bash

set -e

mpremote cp util.py scan.py :

mpremote mip install  aioble
mpremote mip install  logging abc
mpremote mip install  github:josverl/micropython-stubs/mip/typing.json


mpremote cp service.py clone.py batmon.py :
mpremote cp -r mints/ lib/enum/ :
# mpremote cp -r bleak/ aiobmsble/

mpremote cp boot.py :boot.py
mpremote run boot.py