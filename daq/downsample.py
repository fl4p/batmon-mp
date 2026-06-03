import math


def rel_err(a, b, reg=1e-3):
    return abs(a - b) / (abs(b) + reg)


class Downsampler:
    """Event-driven sample emitter for the mints time-series log.

    `update(soc, current, voltage)` is called once per polling tick (typically
    ~1 Hz). It returns True when a sample should be stored. The decision
    interleaves four regimes:

      1. Significant event (load step, soc/voltage change) -> store now AND
         enter a post-transition oversampling window so the RC relaxation tail
         is captured -- without this, the cell voltage trajectory in the
         seconds-to-minutes after a load drop is lost, which is exactly what
         the offline OCV/Qmax algorithms need to extrapolate true OCV at rest
         endpoints (see tools/impedance/REPORT.md in batmon-ha).

      2. Post-transition window: 3-stage decay sized to LFP fast-polarisation
         time constants (tau ~30-100 s). At ~1 Hz polling that's ~5 min total:
         32 fine samples + ~24 medium + ~10 coarse, covering 2-3 tau and
         giving curve_fit enough leverage for V(t) = A + B*exp(-t/tau).

      3. Steady regimes binned by current magnitude (heartbeat). The 64-tier
         was previously removed; it is reinstated here because without it,
         moderate currents (5-25% of DESIGN_CAP) drop to a 256-tier and the
         coulomb integral over slow charging events is severely under-sampled,
         producing an asymmetric Qmax estimate (discharge counted, charge not).

      4. Very-low / no current -> the slowest tier.
    """

    # Post-transition oversampling schedule, in polls since the last
    # significant event. Tuned for LiFePO4: fast polarisation tau ~30-100 s,
    # so 32 fine + 96 medium + 172 coarse polls (~5 min @ 1 Hz) span 2-3 tau.
    BOOST_FINE_END = 32       # polls 0..32  -> store_interval = 1   (~32 samples)
    BOOST_MED_END = 128       # polls 33..128 -> store_interval = 4  (~24 samples)
    BOOST_COARSE_END = 300    # polls 129..300 -> store_interval = 16 (~11 samples)

    def __init__(self, design_cap):
        self.current_acc = 0
        self._n = 0
        self.current_mean = math.nan
        self.prev_mean = -9e9
        self.prev_voltage = -1
        self.prev_soc = -1
        self.DESIGN_CAP = design_cap
        # polls since the last significant event; start outside the boost
        # window so we don't oversample on first call before any history exists
        self._polls_since_change = self.BOOST_COARSE_END

    def add_sample(self, sample):
        pass

    # noinspection PyMethodParameters
    def update(s, soc, current, voltage):
        s.current_acc += current
        s._n += 1
        s._polls_since_change += 1

        soc_d = 2 if max(soc, s.prev_soc) >= 99 else 1
        # Significant event -> store now, AND enter post-transition window
        if (False
                # or (abs(current_acc / current_acc_n - prev_current_mean) > DESIGN_CAP * 0.05) # this will let throug noise (daly)
                # or (current_acc_n > 1 and rel_err(current_acc / current_acc_n, prev_current_mean) > 0.5)
                or (abs(current - s.prev_mean) > s.DESIGN_CAP * 0.25)  # TODO capture peak, big jumps, in-rush
                or (s._n > 16 and abs(
                    s.current_acc / s._n - s.prev_mean) > s.DESIGN_CAP * 0.05)
                or abs(soc - s.prev_soc) >= soc_d
                or rel_err(voltage, s.prev_voltage) > 0.005):  # 0.002
            print('load or soc change I=', current, s.prev_mean, s.current_acc / s._n, 'U=', s.prev_voltage, voltage)
            s._polls_since_change = 0
            store_interval = 1
        elif s._polls_since_change < s.BOOST_FINE_END:
            # fine: instant jump + fast polarisation (first ~tau)
            store_interval = 1
        elif s._polls_since_change < s.BOOST_MED_END:
            # medium: middle of the relaxation curve
            store_interval = 4
        elif s._polls_since_change < s.BOOST_COARSE_END:
            # coarse: settling toward the asymptote
            store_interval = 16
        elif abs(current) > s.DESIGN_CAP * 0.05:
            # restored mid-current heartbeat -- without this, the 5-25%
            # design_cap regime falls through to the 256-tier and slow
            # charging events are coulomb-undercounted
            store_interval = 64
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
