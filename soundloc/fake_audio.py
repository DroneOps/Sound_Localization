"""Audio simulado del banco volante: el ruido de un dron que decae con la distancia.

Corre como proceso aparte y escribe muestras int16 por la salida estándar, igual
que `arecord -t raw`, a ritmo de tiempo real. La posición del dron la lee del
JSON que escribe el Tello simulado.

Modelo del ruido a 1 m: la frecuencia de paso de pala y dos armónicos (60 % de
la potencia) más ruido de banda ancha (40 %). La presión cae como 1/r.
"""

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

from .levels import FULL_SCALE_SINE_RMS


def drone_gain(state, mic_height, mic_x=0.0, mic_y=0.0):
    if not state or not state.get("motors"):
        return 0.0
    distance = max(0.2, math.hypot(state["x"] - mic_x, state.get("y", 0.0) - mic_y,
                                   state["z"] - mic_height))
    return 1.0 / distance


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rate", type=int, default=48000)
    p.add_argument("--state-file", required=True)
    p.add_argument("--mic-height", type=float, default=1.0)
    p.add_argument("--mic-x", type=float, default=0.0)
    p.add_argument("--mic-y", type=float, default=0.0)
    p.add_argument("--level-1m", type=float, default=-30.0, help="nivel del dron a 1 m, en dBFS")
    p.add_argument("--bpf", type=float, default=610.0, help="frecuencia de paso de pala, en Hz")
    p.add_argument("--ambient", type=float, default=-70.0, help="ruido de la habitación, en dBFS")
    p.add_argument("--chunk", type=int, default=1024)
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args(argv)

    fs, n_chunk = args.rate, args.chunk
    rng = np.random.default_rng(args.seed)
    p_total = (10 ** (args.level_1m / 20) * FULL_SCALE_SINE_RMS) ** 2
    weights = np.array([1.0, 10 ** -0.6, 10 ** -1.0])
    weights /= weights.sum()
    tone_amp = np.sqrt(2 * 0.6 * p_total * weights)
    harmonics = args.bpf * np.arange(1, 4)
    noise_sigma = math.sqrt(0.4 * p_total)
    ambient_sigma = 10 ** (args.ambient / 20) * FULL_SCALE_SINE_RMS
    state_file = Path(args.state_file)
    state = {}
    gain_prev = 0.0
    out = sys.stdout.buffer
    t_start = time.monotonic()
    n = 0
    try:
        while True:
            # Un ADC real entrega cada bloque cuando termina de capturarlo, no antes.
            delay = t_start + (n + n_chunk) / fs - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            try:
                state = json.loads(state_file.read_text())
            except (OSError, ValueError):
                pass
            gain = drone_gain(state, args.mic_height, args.mic_x, args.mic_y)
            ramp = np.linspace(gain_prev, gain, n_chunk, endpoint=False)
            gain_prev = gain
            idx = n + np.arange(n_chunk)
            tones = sum(a * np.sin(2 * np.pi * f * idx / fs) for a, f in zip(tone_amp, harmonics))
            drone = (tones + rng.normal(0.0, noise_sigma, n_chunk)) * ramp
            x = drone + rng.normal(0.0, ambient_sigma, n_chunk)
            out.write(np.clip(np.round(x * 32768), -32768, 32767).astype("<i2").tobytes())
            out.flush()
            n += n_chunk
    except (BrokenPipeError, KeyboardInterrupt):
        pass


if __name__ == "__main__":
    main()
