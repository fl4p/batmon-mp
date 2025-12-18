import asyncio


def test_writebuffer():
    from util import WriteBuffer

    a = []
    async def fn(data):
        a.append(bytes(data))

    wb = WriteBuffer(fn, 20)

    async def _prog():
        await wb.write(b'hello world')  # len=11
        assert len(a) == 0
        await wb.write(b'hello world2')  # len=11
        assert len(a) == 1
        assert a[0] == b'hello world'
        await wb.flush()
        assert len(a) == 2
        assert a[1] == b'hello world2'

    asyncio.run(_prog())



def test_hysteresis():
    from util import BoolHysteresisVar
    h = BoolHysteresisVar(False, 12, 17)
    assert not h
    h.update(10)
    assert not h
    h.update(13)
    assert not h
    h.update(18)
    assert h
    h.update(19)
    assert h
    h.update(13)
    assert h
    h.update(11)
    assert not h