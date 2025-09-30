# https://docs.influxdata.com/influxdb/v1/write_protocols/line_protocol_tutorial/
# https://docs.influxdata.com/influxdb/v2/reference/syntax/line-protocol/

import io

import socket

soc = None
buf: io.BytesIO | None = None  # io.BytesIO()

addr = ('rpi.local', 8086)

MIN_BUF = 1436

#import ntptime
#ntptime.settime()	# this queries the time from an NTP server
#time.localtime()


def write_point(measurement, tags, fields):
    global buf, soc
    if buf is None:
        buf = io.BytesIO()
    buf.write(measurement.encode('utf-8'))
    for k, v in tags.items():
        buf.write(f',{k}={v}'.encode('utf-8'))
    for k, v in fields.items():
        buf.write(f' {k}={v}'.encode('utf-8'))

    if buf.tell() > MIN_BUF:
        flush()


def flush():
    global soc
    if soc is None:
        bsize = buf.tell()
        buf.seek(0)
        if soc is None:
            soc = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            soc.setblocking(False)

        bytes = buf.read(bsize)
        soc.sendto(bytes, addr)


# buf.write(f' {int(timestamp_seconds * 1e9)}')
# def pointToLine(point):
# def writePoints(points: list[dict]):


if __name__ == '__main__':
    write_point('test', dict(a='b'), dict(v=1, w=2))
    flush()
