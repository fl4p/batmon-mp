import asyncio
import sys
import time

import machine

from service import BaseService


def main():
    import ble_filesrv
    import shunt
    services = [
        (ble_filesrv.service, dict(advertising_name='shanty-shunt')),
        (shunt.service, {}),
        # (batmon.service, {}),
    ]

    try:
        for svc_class, args in services:
            svc_class: type[BaseService]
            svc: BaseService = svc_class()
            if svc_class == services[-1][0]:
                print('starting service', svc_class.__module__, svc_class.__name__, args)
                asyncio.run(svc.start(background=False, args=args))  # last service blocks
            else:
                print('starting service in BG', svc_class.__module__, svc_class.__name__, args)
                asyncio.run(svc.start(background=True, args=args))
    except KeyboardInterrupt:
        print('boot:KeyboardInterrupt')
        for service in services:
            service: BaseService
            asyncio.run(service.stop())

    except Exception as e:

        sys.print_exception(e)

        print('reset in 5 seconds')
        time.sleep(5)
        machine.reset()

    print('main service', services[-1], 'stopped, reset in 10 seconds')
    time.sleep(10)
    machine.reset()


if __name__ == '__main__':
    main()
