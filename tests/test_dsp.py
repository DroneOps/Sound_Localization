import numpy as np
import pytest

from soundloc.dsp import bandpass, bandpass_sos, response_db
from soundloc.levels import dbfs

FS = 16000


def tone(f, seconds=4.0, amplitude=0.5):
    return amplitude * np.sin(2 * np.pi * f * np.arange(int(seconds * FS)) / FS)


def middle(x):
    """Lejos de los bordes, donde el filtro todavía tiene transitorios."""
    return x[FS:-FS]


def test_cutoffs_are_at_minus_3_db():
    assert response_db(bandpass_sos(FS), FS, [300.0, 3000.0]) == pytest.approx([-3.01, -3.01], abs=0.02)


def test_passband_is_flat():
    assert np.max(np.abs(response_db(bandpass_sos(FS), FS, np.geomspace(600, 1500, 30)))) < 0.1


def test_one_octave_outside_is_strongly_attenuated():
    low, high = response_db(bandpass_sos(FS), FS, [150.0, 6000.0])
    assert low < -20 and high < -20


def test_a_voice_band_tone_passes_unchanged():
    x = tone(1000.0)
    assert dbfs(middle(bandpass(x, FS))) == pytest.approx(dbfs(middle(x)), abs=0.05)


def test_zero_phase_doubles_the_attenuation_at_the_cutoff():
    x = tone(300.0)
    assert dbfs(middle(bandpass(x, FS))) - dbfs(middle(x)) == pytest.approx(-6.02, abs=0.1)
    assert dbfs(middle(bandpass(x, FS, zero_phase=False))) - dbfs(middle(x)) == pytest.approx(-3.01, abs=0.1)


def test_white_noise_keeps_power_in_proportion_to_the_bandwidth():
    x = np.random.default_rng(0).normal(0.0, 0.1, 20 * FS)
    expected = 10 * np.log10((3000 - 300) / (FS / 2))
    assert dbfs(bandpass(x, FS)) - dbfs(x) == pytest.approx(expected, abs=0.5)


def test_the_band_must_fit_below_nyquist():
    with pytest.raises(ValueError):
        bandpass_sos(5000)  # Nyquist en 2500 Hz, por debajo de los 3000 Hz
