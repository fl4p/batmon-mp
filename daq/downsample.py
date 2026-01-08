import math


def rel_err(a, b, reg=1e-3):
    return abs(a - b) / (abs(b) + reg)


class Downsampler:

    def __init__(self, design_cap):
        self.current_acc = 0
        self._n = 0
        self.current_mean = math.nan
        self.prev_mean = -9e9
        self.prev_voltage = -1
        self.prev_soc = -1
        self.DESIGN_CAP = design_cap

    def add_sample(self, sample):
        pass

    # noinspection PyMethodParameters
    def update(s, soc, current, voltage):
        # TODO average current ewma
        # - power jumps

        s.current_acc += current
        s._n += 1

        soc_d = 2 if max(soc, s.prev_soc) >= 99 else 1
        # if current significantly changed
        if (False
                # or (abs(current_acc / current_acc_n - prev_current_mean) > DESIGN_CAP * 0.05) # this will let throug noise (daly)
                # or (current_acc_n > 1 and rel_err(current_acc / current_acc_n, prev_current_mean) > 0.5)
                or (abs(current - s.prev_mean) > s.DESIGN_CAP * 0.25)  # TODO capture peak, big jumps, in-rush
                or (s._n > 16 and abs(
                    s.current_acc / s._n - s.prev_mean) > s.DESIGN_CAP * 0.05)  # rel_err(current_acc / current_acc_n, prev_current_mean, reg=DESIGN_CAP * 0.05) > 0.3)
                or abs(soc - s.prev_soc) >= soc_d
                or rel_err(voltage, s.prev_voltage) > 0.005):  # 0.002
            print('load or soc change I=', current, s.prev_mean, s.current_acc / s._n, 'U=', s.prev_voltage, voltage)
            store_interval = 1  # store now
        # elif abs(current) > s.DESIGN_CAP * 0.05:
        #    store_interval = 64
        elif abs(current) > s.DESIGN_CAP * 0.005:
            store_interval = 256
        else:
            store_interval = 1024

        # store_interval //= 16

        s.store_interval = store_interval

        if s._n >= store_interval:
            s.current_mean = s.current_acc / s._n
            s.prev_mean = s.current_mean
            s.prev_soc = soc
            s.prev_voltage = voltage
            s._n = 0
            s.current_acc = 0
            return True

        return False
