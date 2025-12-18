fh =open('stufff', 'ab')

try:
    while 1:
        assert fh.write(b'\0' * 512) == 512
        print('wrote')
except Exception as e:
    print('err', e)

print('open4')
fh2 = open('stufff4', 'ab')
while 1:
    assert fh2.write(b'\0' * 256) == 256
    print('wrote')

    #fh.flush()