"""Procesamiento de señal del subsistema acústico.

Sección 2.2: filtro pasa-banda de la banda de voz (300–3000 Hz).
"""

import numpy as np
from scipy.signal import butter, sosfilt, sosfiltfilt, sosfreqz

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
