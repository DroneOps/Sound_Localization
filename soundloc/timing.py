"""Sincronización entre el audio y el resto del sistema (sección 2.1, parte C).

Todo se marca con el mismo reloj, time.monotonic(), que no cambia si alguien
ajusta la hora de la computadora. El audio llega en bloques: de cada bloque
sabemos cuántas muestras van acumuladas y a qué hora llegó. Un bloque siempre
llega después de capturarse, nunca antes, así que el retraso sólo suma. Por eso
el mejor estimador del instante de la muestra 0 es el mínimo, no el promedio.
"""

import numpy as np


def _offsets(frames_end, t_arrival, fs):
    frames_end = np.asarray(frames_end, dtype=np.float64)
    t_arrival = np.asarray(t_arrival, dtype=np.float64)
    if frames_end.size == 0:
        raise ValueError("No hay marcas de tiempo del audio")
    return t_arrival - frames_end / fs


def estimate_t0(frames_end, t_arrival, fs):
    """Instante, en el reloj monotónico, en que se capturó la muestra 0."""
    return float(_offsets(frames_end, t_arrival, fs).min())


def clock_drift_s(frames_end, t_arrival, fs):
    """Cuánto se separan el reloj del ADC y el de la computadora durante la grabación."""
    offsets = _offsets(frames_end, t_arrival, fs)
    q = max(1, offsets.size // 4)
    return float(offsets[-q:].min() - offsets[:q].min())


def time_to_sample(t, t0, fs):
    return int(round((t - t0) * fs))
