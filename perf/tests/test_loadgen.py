import pytest

from perf.loadgen import Pacer, summarize


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.slept = 0.0

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.slept += seconds
        self.now += seconds


def test_pacer_without_rate_never_sleeps():
    fake = FakeClock()
    pacer = Pacer(None, fake.clock, fake.sleep)
    for _ in range(1000):
        pacer.wait()

    assert fake.slept == 0.0


def test_pacer_holds_the_rate_over_time():
    fake = FakeClock()
    pacer = Pacer(100.0, fake.clock, fake.sleep)
    for _ in range(1100):
        pacer.wait()

    # The first second's burst is free; the other 1,000 calls take ~10 s.
    assert fake.now == pytest.approx(10.0, rel=0.02)


def test_pacer_rejects_non_positive_rate():
    with pytest.raises(ValueError):
        Pacer(0.0)


def test_summarize():
    summary = summarize([100, 300, 200], 600, 0, 3.0, 250.0)

    assert summary.mean_rps == 200.0
    assert summary.peak_rps == 300
    assert summary.target_rps == 250.0
    assert summary.failed == 0
