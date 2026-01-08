#!/usr/bin/env bash

set -e

mpremote cp install.py :
mpremote cp util.py :
mpremote cp wifi-secret.json :
mpremote run install.py

mpremote cp service.py clone.py batmon.py :
mpremote cp -r mints/ aiobmsble/ bleak/ lib/enum/ :

mpremote cp boot.py :b00t.py
mpremote run b00t.py