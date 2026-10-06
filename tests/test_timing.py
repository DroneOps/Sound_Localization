import numpy as np
import pytest

from soundloc.timing import clock_drift_s, estimate_t0

FS = 16000
CHUNK = 1024


def arrivals(n_chunks, t0, latency, jitter_s, drift_ppm=0.0, seed=0):
    rng = np.random.default_rng(seed)
    frames = CHUNK * np.arange(1, n_chunks + 1)
    capture_end = t0 + frames / FS * (1 + drift_ppm * 1e-6)
    # El retraso de entrega sólo suma: latencia fija más un temblor siempre positivo.
    return frames, capture_end + latency + rng.exponential(jitter_s, n_chunks)


def test_minimum_beats_median_with_one_sided_jitter():
    frames, t = arrivals(500, t0=100.0, latency=0.020, jitter_s=0.010)
    offsets = t - frames / FS
    assert estimate_t0(frames, t, FS) == pytest.approx(100.020, abs=0.001)
    assert np.median(offsets) - 100.020 > 0.005  # la mediana arrastra el retraso típico


def test_clock_drift_is_detected():
    frames, t = arrivals(3000, t0=0.0, latency=0.02, jitter_s=0.001, drift_ppm=100)
    duration = frames[-1] / FS
    assert clock_drift_s(frames, t, FS) == pytest.approx(100e-6 * duration * 0.75, rel=0.3)
