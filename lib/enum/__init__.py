
class IntEnum(object):
    def __init__(self, i: int):
        self.i = i
        print(self.__dict__)

    def __int__(self):
        return self.i

    def __eq__(self, other):
        return self.i == other

    def __ne__(self, other):
        return self.i != other

    def __lt__(self, other):
        return self.i < int(other)

    def __gt__(self, other):
        return self.i > int(other)

    def __le__(self, other):
        return self.i <= int(other)

    def __ge__(self, other):
        return self.i >= int(other)

    def __str__(self):
        return str(self.i)


def _test():
    class TestEnum(IntEnum):
        A = 1
        B = 2

    TestEnum(1)

if __name__ == "__main__":
    _test()