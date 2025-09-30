import asyncio
import json
import sys
import time

import machine

#import conn




def connect_wifi():
    import network
    sta_if = network.WLAN(network.WLAN.IF_STA)
    if not sta_if.isconnected():
        print('connecting to network...')
        sta_if.active(True)
        with open('wifi-secret.json', 'r') as f:
            sta_if.connect(*json.load(f))
        while not sta_if.isconnected():
            pass
    print('network config:', sta_if.ipconfig('addr4'))

    # This file is executed on every boot (including wake-boot from deepsleep)
    #import esp
    #esp.osdebug(None)
    #import webrepl
    #webrepl.start()

connect_wifi()
