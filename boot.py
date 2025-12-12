import asyncio
import sys
import time

import machine


def main():

    #import batmon
    import clone
    try:
        clone.main()
        #pass
        # asyncio.run(batmon.main())
    except KeyboardInterrupt:
        print('boot:KeyboardInterrupt')
        asyncio.run(clone.close())

    except Exception as e:

        sys.print_exception(e)

        print('reset in 2 seconds')
        time.sleep(2)
        machine.reset()


if __name__ == '__main__':
    main()
