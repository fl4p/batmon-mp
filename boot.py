import asyncio
import json
import time

import machine

import conn


def connect_wifi():
    import network
    sta_if = network.WLAN(network.WLAN.IF_STA)
    if not sta_if.isconnected():
        print('connecting to network...')
        sta_if.active(True)
        with open('wifi-secret.json', 'r') as f:
            sta_if.connect(**json.load(f))
        while not sta_if.isconnected():
            pass
    print('network config:', sta_if.ipconfig('addr4'))


try:
    asyncio.run(conn.main())
except KeyboardInterrupt:  # TODO catch micropython reset exceptions, interrupts?
    print('boot:KeyboardInterrupt')
    asyncio.run(conn.close())

except Exception as e:

    # put this raise for debugging stack traces
    # raise

    print(e)
    try:
        # this does not work in micropython: (yet)
        import traceback

        traceback.print_exc()
    except:
        pass

    print('reset in 10 seconds')
    time.sleep(10)
    machine.reset()
