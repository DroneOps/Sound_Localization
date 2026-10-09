import numpy as np
import pytest

from soundloc.dsp import (bandpass, bandpass_sos, find_tonal_peaks, harmonics_in_band, notch,
                          notch_sos, response_db)
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


# --- notch -------------------------------------------------------------------------------

def test_a_notch_kills_its_tone():
    x = tone(1000.0)
    assert dbfs(middle(notch(x, FS, [1000.0], q=30))) - dbfs(middle(x)) < -40


def test_a_notch_leaves_other_frequencies_alone():
    # A tres anchos de distancia (BW = 1000/30 ≈ 33 Hz), casi no toca nada.
    for f in (1000.0 - 100.0, 1000.0 + 100.0, 2000.0):
        x = tone(f)
        assert dbfs(middle(notch(x, FS, [1000.0], q=30))) - dbfs(middle(x)) > -0.5


def test_the_width_at_minus_3_db_is_f0_over_q():
    bw = 1000.0 / 20
    assert response_db(notch_sos(FS, 1000.0, 20), FS, [1000.0 - bw / 2, 1000.0 + bw / 2]) == \
        pytest.approx([-3.0, -3.0], abs=0.3)


def test_the_notch_is_deep_only_at_the_center():
    """|H| ≈ |δ| / √(δ² + (BW/2)²): en el borde sólo quita la mitad de la potencia."""
    bw = 1000.0 / 20
    for delta in (bw / 20, bw / 10, bw / 4, bw / 2, bw):
        expected = 20 * np.log10(delta / np.sqrt(delta ** 2 + (bw / 2) ** 2))
        assert response_db(notch_sos(FS, 1000.0, 20), FS, [1000.0 + delta])[0] == pytest.approx(expected, abs=0.3)


def test_white_noise_loses_three_quarters_pi_times_the_width():
    """Ida y vuelta, un notch le quita al ruido blanco un ancho equivalente de (3π/4)·BW."""
    x = np.random.default_rng(1).normal(0.0, 0.1, 60 * FS)
    bw = 1000.0 / 10
    expected = 10 * np.log10(1 - (3 * np.pi / 4) * bw / (FS / 2))
    assert dbfs(notch(x, FS, [1000.0], q=10)) - dbfs(x) == pytest.approx(expected, abs=0.02)


def test_harmonics_in_the_voice_band():
    assert harmonics_in_band(300.0) == pytest.approx([300.0 * k for k in range(1, 11)])
    assert harmonics_in_band(660.0) == pytest.approx([660.0, 1320.0, 1980.0, 2640.0])


def test_a_harmonic_notch_removes_blade_tones_but_not_a_tone_between_them():
    bpf = 330.0
    blades = sum(0.2 / k * np.sin(2 * np.pi * k * bpf * np.arange(4 * FS) / FS) for k in range(1, 10))
    voice_like = tone(500.0, amplitude=0.05)  # 500 Hz cae entre 330 y 660
    y = notch(blades + voice_like, FS, harmonics_in_band(bpf), q=30)
    assert dbfs(middle(y)) == pytest.approx(dbfs(middle(voice_like)), abs=0.3)


def test_tonal_peaks_are_found_in_noise():
    rng = np.random.default_rng(2)
    x = sum(0.05 * np.sin(2 * np.pi * f * np.arange(8 * FS) / FS) for f in (642.0, 677.0, 1324.0))
    x = x + rng.normal(0.0, 0.05, 8 * FS)
    assert find_tonal_peaks(x, FS) == pytest.approx([642.0, 677.0, 1324.0], abs=2.0)


def test_a_notch_must_fit_below_nyquist():
    with pytest.raises(ValueError):
        notch_sos(FS, 9000.0, 30)
