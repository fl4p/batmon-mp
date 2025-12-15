import json


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


def main():
    import sys
    sys.path.append("/remote/lib")

    connect_wifi()

    from web.micropyserver import MicroPyServer

    ''' there should be a wi-fi connection code here '''

    def hello_world(request):
        ''' request handler '''
        server.send("HELLO WORLD!")
        server.send(str(request))

    def serve_file(fn, request):
        # server#.os.stat(fn)[6]
        with open(fn, 'rb') as f:
            while len(d := f.read(1024)):
                server.send_raw(d)

    server = MicroPyServer()
    ''' add route '''
    server.add_route("/", lambda r: serve_file('web/www/index.html', r))
    server.add_route("/st/.+", hello_world)
    ''' start server '''
    server.start()


if __name__ == '__main__':
    main()
