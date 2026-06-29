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

    # Post-transition oversampling schedule, in polls since the last significant
    # event: store_interval is 1 / 4 / 16 within the fine / med / coarse bands,
    # then heartbeat. Tuned for LiFePO4 (fast polarisation tau ~30-100 s). The
    # window captures the voltage relaxation tail after each load step for the
    # offline impedance/OCV fits; samples-per-event roughly sets the data rate,
    # so this is the knob that trades impedance fidelity for flash retention:
    #   'full'    -> ~67 samples/event, full V(t) tail  (impedance-grade; shortest retention)
    #   'trimmed' -> ~24 samples/event, fast tail only  (coarse tau fit; ~mid retention)
    #   'none'    -> 1 sample/event, no tail            (pre-impedance behaviour; longest retention)
    # 'trimmed' is sized to what the bat-impedance R0/R1/tau fits actually read:
    # they cap the relaxation window at ~150-180 s and need >=12 tail points over
    # >=2*tau (~60-120 s), so ~8 pts @2s (0-16s, R0) + ~6 @8s (16-64s, tau) + ~3
    # @32s (64-150s, R_dc); everything past ~180 s in 'full' is unread overhead.
    BOOST_PROFILES = {
        #            (fine_end, med_end, coarse_end)  -- polls since the event
        'full':      (32, 128, 300),   # ~67 samples / ~600 s
        'trimmed':   ( 8,  32,  75),   # ~17 samples / ~150 s  (impedance-grade, ~4x retention)
        'none':      ( 0,   0,   0),   # 1 sample/event (no relaxation tail -> no R estimate)
    }

    # Step-gate: only a genuine current STEP this large opens the relaxation boost
    # window (the bat-impedance R0/tau fits need dI >= ~6 A; bigger = better SNR).
    # Smaller "events" -- SoC ticks and pack-voltage drift -- still store ONE
    # sample but no longer spawn a boost; that spurious boosting on voltage noise
    # was the main retention sink (it fired ~every 75 s, each costing a full tail).
    BOOST_STEP_FRAC = 0.05      # * design_cap (~14 A): a current step >= this --
                                # instantaneous OR drifted over ~16 polls -- opens
                                # the boost, fired the same poll so R0 isn't missed.

    # Rest heartbeat (|I| ~ 0): keeps the settled-OCV anchor alive for Qmax/SoH.
    # ~6 min (@2 s poll) puts ~5 samples in a 30 min rest (plus the post-step
    # boost); the old 1024-poll (~34 min) tier dropped ~1 sample/rest and starved
    # the bat-impedance rest_events / OCV-asymptote fits.
    REST_HEARTBEAT = 180        # polls

    def __init__(self, design_cap, boost='full'):
        if boost not in self.BOOST_PROFILES:
            raise ValueError('boost must be one of %s' % list(self.BOOST_PROFILES.keys()))
        self.boost = boost
        self.BOOST_FINE_END, self.BOOST_MED_END, self.BOOST_COARSE_END = self.BOOST_PROFILES[boost]
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
        cap = s.DESIGN_CAP
        # A genuine load step (current jump or sustained level change) opens the
        # relaxation boost window -- this is the only thing the impedance R0/tau
        # fits can use.
        boost_event = (abs(current - s.prev_mean) > cap * s.BOOST_STEP_FRAC
                       or (s._n > 16
                           and abs(s.current_acc / s._n - s.prev_mean) > cap * s.BOOST_STEP_FRAC))
        # Other significant changes (SoC tick, pack-voltage drift) store one
        # sample so the series stays faithful, but do NOT spawn a boost.
        store_event = (boost_event
                       or abs(soc - s.prev_soc) >= soc_d
                       or rel_err(voltage, s.prev_voltage) > 0.005)

        if boost_event:
            print('load step -> boost I=', current, s.prev_mean, 'U=', s.prev_voltage, voltage)
            s._polls_since_change = 0
            store_interval = 1
        elif store_event:
            store_interval = 1  # store now, no relaxation boost
        elif s._polls_since_change < s.BOOST_FINE_END:
            # fine: instant jump + fast polarisation (first ~tau)
            store_interval = 1
        elif s._polls_since_change < s.BOOST_MED_END:
            # medium: middle of the relaxation curve
            store_interval = 4
        elif s._polls_since_change < s.BOOST_COARSE_END:
            # coarse: settling toward the asymptote
            store_interval = 16
        elif abs(current) > cap * 0.05:
            # restored mid-current heartbeat -- without this, the 5-25%
            # design_cap regime falls through to the 256-tier and slow
            # charging events are coulomb-undercounted
            store_interval = 64
        elif abs(current) > cap * 0.005:
            store_interval = 256
        else:
            # rest: kept fast enough to preserve the OCV/Qmax anchor (see above)
            store_interval = s.REST_HEARTBEAT

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
