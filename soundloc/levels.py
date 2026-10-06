"""Medidas de nivel de una señal de audio digital.

Convenciones (sección 2.1, parte A):
- Las muestras int16 se normalizan a [-1, 1) dividiendo entre 32768.
- 0 dBFS es el nivel RMS de una senoidal cuyo pico toca la escala completa,
  la convención de las hojas de datos de los micrófonos MEMS.
"""

import numpy as np
from scipy.signal import welch

FULL_SCALE_SINE_RMS = 1.0 / np.sqrt(2.0)
_EPS = 1e-12


def to_float(samples):
    """Convierte muestras int16 a flotante en [-1, 1)."""
    return np.asarray(samples, dtype=np.float64) / 32768.0


def rms(x):
    x = np.asarray(x, dtype=np.float64)
    if x.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(x * x)))


def rms_to_dbfs(value):
    return float(20.0 * np.log10(max(value, _EPS) / FULL_SCALE_SINE_RMS))


def dbfs(x):
    """Nivel RMS de una señal normalizada, en dBFS."""
    return rms_to_dbfs(rms(x))


def clip_fraction(samples_int16, margin=1):
    """Fracción de muestras pegadas a los extremos del ADC (saturación)."""
    s = np.asarray(samples_int16)
    if s.size == 0:
        return 0.0
    hits = (s >= 32767 - margin) | (s <= -32768 + margin)
    return float(np.mean(hits))


def short_time_levels(x, fs, window_s):
    """Nivel en dBFS por ventanas consecutivas, sin traslape.

    Devuelve (t, niveles), con t en el centro de cada ventana, en segundos.
    """
    n = max(1, int(round(window_s * fs)))
    k = len(x) // n
    if k == 0:
        return np.array([]), np.array([])
    frames = np.asarray(x[: k * n], dtype=np.float64).reshape(k, n)
    r = np.sqrt(np.mean(frames * frames, axis=1))
    levels = 20.0 * np.log10(np.maximum(r, _EPS) / FULL_SCALE_SINE_RMS)
    t = (np.arange(k) + 0.5) * n / fs
    return t, levels


def power_mean_db(levels_db):
    """Promedio de niveles en potencia, no en dB: así se combinan fuentes incoherentes."""
    levels_db = np.asarray(levels_db, dtype=np.float64)
    return float(10.0 * np.log10(np.mean(10.0 ** (levels_db / 10.0))))


def subtract_level(total_db, background_db, min_diff_db=3.0):
    """Quita a un nivel el aporte de un fondo incoherente (resta de potencias).

    Es la suma de niveles al revés. Si el total no supera al fondo por al menos
    `min_diff_db`, la resta amplifica los errores de medición y devuelve nan.
    """
    if not (np.isfinite(total_db) and np.isfinite(background_db)):
        return float("nan")
    if total_db - background_db < min_diff_db:
        return float("nan")
    return float(10.0 * np.log10(10.0 ** (total_db / 10.0) - 10.0 ** (background_db / 10.0)))


def dominant_peak_hz(x, fs, fmin=100.0, fmax=4000.0):
    """Frecuencia del pico más fuerte del espectro promedio (Welch) entre fmin y fmax."""
    x = np.asarray(x, dtype=np.float64)
    if x.size < 256:
        return float("nan")
    nperseg = int(min(x.size, 2 ** int(np.log2(fs))))
    f, p = welch(x, fs=fs, nperseg=nperseg)
    band = (f >= fmin) & (f <= min(fmax, fs / 2))
    if not band.any():
        return float("nan")
    return float(f[band][np.argmax(p[band])])
