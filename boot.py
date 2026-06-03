import asyncio
import sys
import time

import machine

from service import BaseService


def main():
    services = []

    try:
        # Grace window: a single Ctrl-C here (or while a service runs) drops to
        # the REPL instead of reset-looping, so you don't have to spam Ctrl-C.
        print('starting services in 3s - Ctrl-C for REPL')
        time.sleep(3)

        # Imports inside the try so an import-time failure (corrupt .mpy, flash
        # read error) resets instead of stranding the device at the REPL.
        import ble_filesrv
        import batmon
        services = [
            (ble_filesrv.service, dict(advertising_name='shanty-shunt')),
            (batmon.service, {}),
        ]

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
        # Manual intervention: stay at the REPL, do NOT reset.
        print('Ctrl-C -> dropping to REPL (no reset)')
        return

    except Exception as e:
        # Unattended self-recovery from real faults. Keep the reset reachable
        # even if logging itself raises (e.g. MemoryError formatting the trace).
        try:
            sys.print_exception(e)
            print('reset in 5 seconds')
            time.sleep(5)
        except Exception:
            pass
        machine.reset()

    # Foreground service returned on its own (not expected during normal,
    # unattended operation) -> self-recover.
    print('main service', services[-1] if services else None, 'stopped, reset in 10 seconds')
    time.sleep(10)
    machine.reset()


if __name__ == '__main__':
    main()
