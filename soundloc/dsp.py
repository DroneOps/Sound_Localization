"""Procesamiento de señal del subsistema acústico.

Sección 2.2: filtro pasa-banda de la banda de voz (300–3000 Hz) y notch para los
tonos de las hélices que caen dentro de ella.
"""

import math

import numpy as np
from scipy.signal import butter, find_peaks, iirnotch, sosfilt, sosfiltfilt, sosfreqz, tf2sos, welch

VOICE_BAND_HZ = (300.0, 3000.0)
DEFAULT_ORDER = 4


def bandpass_sos(fs, band=VOICE_BAND_HZ, order=DEFAULT_ORDER):
    """Butterworth pasa-banda como cascada de secciones de segundo orden (SOS).

    `butter` diseña el filtro analógico y lo pasa a digital con la
    transformación bilineal, corrigiendo antes las frecuencias de corte
    (prewarping) para que el −3 dB quede exactamente donde se pidió. En un
    pasa-banda, `order` es el orden de cada flanco: el filtro completo tiene
    2·order polos, repartidos en `order` secciones de segundo orden.
    """
    low, high = band
    if not 0 < low < high < fs / 2:
        raise ValueError(f"La banda {band} Hz no cabe debajo de Nyquist ({fs / 2:g} Hz)")
    return butter(order, [low, high], btype="bandpass", fs=fs, output="sos")


def bandpass(x, fs, band=VOICE_BAND_HZ, order=DEFAULT_ORDER, zero_phase=True):
    """Filtra una señal a la banda indicada.

    Con zero_phase=True filtra hacia adelante y luego hacia atrás: los retrasos
    se cancelan y nada se desplaza en el tiempo, pero sólo funciona con una
    grabación completa, y la atenuación se aplica dos veces (en los cortes
    queda en −6 dB en lugar de −3 dB). Como es igual en todas las mediciones,
    es un sesgo común. Con zero_phase=False el filtro es causal, para tiempo real.

    Hay que filtrar la grabación completa y recortar después: el filtro tiene
    memoria, y cortar antes metería transitorios en los bordes de cada tramo.
    """
    sos = bandpass_sos(fs, band, order)
    x = np.asarray(x, dtype=np.float64)
    return sosfiltfilt(sos, x) if zero_phase else sosfilt(sos, x)


def response_db(sos, fs, freqs, zero_phase=False):
    """Ganancia del filtro, en dB, en las frecuencias indicadas (Hz)."""
    _, h = sosfreqz(sos, worN=np.asarray(freqs, dtype=np.float64), fs=fs)
    gain_db = 20 * np.log10(np.maximum(np.abs(h), 1e-15))
    return 2 * gain_db if zero_phase else gain_db


def notch_sos(fs, f0, q):
    """Un notch de segundo orden en f0, con factor de calidad q (ancho a −3 dB = f0 / q).

    Es la ecuación en diferencias
        y[n] = x[n] − 2·cos(ω0)·x[n−1] + x[n−2] + 2r·cos(ω0)·y[n−1] − r²·y[n−2]
    La parte con x cancela exactamente una senoidal de frecuencia f0; la parte con y
    (realimentación, r un poco menor que 1) devuelve las demás frecuencias.
    """
    if not 0 < f0 < fs / 2:
        raise ValueError(f"El notch en {f0:g} Hz no cabe debajo de Nyquist ({fs / 2:g} Hz)")
    if q <= 0:
        raise ValueError("Q tiene que ser positivo")
    return tf2sos(*iirnotch(f0, q, fs=fs))


def notch_bank_sos(fs, freqs, q):
    """Un notch de Q constante en cada frecuencia: el ancho crece con la frecuencia, igual que
    la separación entre los armónicos de motores que giran a velocidades un poco distintas."""
    return np.vstack([notch_sos(fs, f, q) for f in freqs])


def harmonics_in_band(fundamental_hz, band=VOICE_BAND_HZ):
    """Los múltiplos de la fundamental (por ejemplo, la BPF) que caen dentro de la banda."""
    if fundamental_hz <= 0:
        raise ValueError("La fundamental tiene que ser positiva")
    low, high = band
    first = max(1, math.ceil(low / fundamental_hz - 1e-9))
    return [k * fundamental_hz for k in range(first, int(high / fundamental_hz + 1e-9) + 1)]


def notch(x, fs, freqs, q, zero_phase=True):
    """Aplica un notch en cada frecuencia de `freqs`. Sin frecuencias, devuelve la señal igual."""
    x = np.asarray(x, dtype=np.float64)
    if len(freqs) == 0:
        return x.copy()
    sos = notch_bank_sos(fs, freqs, q)
    return sosfiltfilt(sos, x) if zero_phase else sosfilt(sos, x)


def find_tonal_peaks(x, fs, band=VOICE_BAND_HZ, prominence_db=12.0, min_separation_hz=15.0,
                     resolution_hz=1.5):
    """Picos tonales del espectro promedio (Welch) dentro de la banda.

    Sirve cuando no hay RPM del ESC para saber dónde están los tonos, como con el Tello.
    `prominence_db` es cuánto tiene que sobresalir un pico de lo que lo rodea.
    """
    x = np.asarray(x, dtype=np.float64)
    nperseg = min(x.size, 2 ** math.ceil(math.log2(fs / resolution_hz)))
    f, p = welch(x, fs=fs, nperseg=nperseg)
    level = 10 * np.log10(p + 1e-30)
    inside = (f >= band[0]) & (f <= band[1])
    distance = max(1, int(round(min_separation_hz / (f[1] - f[0]))))
    peaks, _ = find_peaks(np.where(inside, level, -300.0), prominence=prominence_db, distance=distance)
    return f[peaks]
