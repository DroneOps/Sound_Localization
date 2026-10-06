import numpy as np
import pytest

from soundloc.levels import (clip_fraction, dbfs, dominant_peak_hz, power_mean_db,
                             short_time_levels, subtract_level)

FS = 16000


def sine(amplitude, f=1000.0, seconds=1.0):
    t = np.arange(int(seconds * FS)) / FS
    return amplitude * np.sin(2 * np.pi * f * t)


def test_full_scale_sine_is_0_dbfs():
    assert dbfs(sine(1.0)) == pytest.approx(0.0, abs=0.01)


def test_half_amplitude_is_minus_6_dbfs():
    assert dbfs(sine(0.5)) == pytest.approx(-6.02, abs=0.01)


def test_clip_fraction_detects_saturation():
    clipped = np.clip(np.round(sine(2.0) * 32768), -32768, 32767).astype(np.int16)
    clean = np.round(sine(0.5) * 32768).astype(np.int16)
    assert clip_fraction(clipped) > 0.3
    assert clip_fraction(clean) == 0.0


def test_power_mean_averages_powers_not_decibels():
    assert power_mean_db([-30.0, -30.0]) == pytest.approx(-30.0)
    assert power_mean_db([-30.0, -40.0]) == pytest.approx(10 * np.log10((1e-3 + 1e-4) / 2))


def test_subtract_level_undoes_a_level_sum():
    total = 10 * np.log10(10 ** (-30 / 10) + 10 ** (-40 / 10))
    assert subtract_level(total, -40.0) == pytest.approx(-30.0)
    assert np.isnan(subtract_level(-30.0, -31.0))


def test_short_time_levels_follow_a_step():
    x = np.concatenate([sine(0.1), sine(10 ** (-10 / 20))])
    _, levels = short_time_levels(x, FS, 0.1)
    assert levels[:10] == pytest.approx(-20.0, abs=0.05)
    assert levels[10:] == pytest.approx(-10.0, abs=0.05)


def test_dominant_peak_finds_a_tone():
    noise = 0.01 * np.random.default_rng(0).normal(size=4 * FS)
    assert dominant_peak_hz(sine(0.5, f=610.0, seconds=4.0) + noise, FS) == pytest.approx(610.0, abs=1.0)
