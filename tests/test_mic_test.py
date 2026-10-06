import numpy as np

from soundloc.levels import clip_fraction, dbfs, to_float
from soundloc.mic_test import analyze_step_test, evaluate, generate_stimulus

FS = 16000


def record(y, floor_db=-75.0, lead_s=1.0, seed=0):
    """Simula la grabación: silencio previo, ruido de la habitación y conversión a int16."""
    rng = np.random.default_rng(seed)
    y = np.concatenate([np.zeros(int(lead_s * FS)), y])
    y = y + rng.normal(0.0, 10 ** (floor_db / 20) / np.sqrt(2), y.size)
    return np.clip(np.round(y * 32768), -32768, 32767).astype(np.int16)


def simulate_agc(x, target_db=-25.0, tau_s=0.3, block_s=0.01):
    """AGC de primer orden: la ganancia sigue al error con constante de tiempo tau.

    Es un filtro de un polo discretizado por Euler: G += (dt/tau)·(objetivo − nivel).
    """
    n = int(block_s * FS)
    gain_db = 0.0
    y = np.empty_like(x)
    for i in range(0, len(x), n):
        block = x[i:i + n] * 10 ** (gain_db / 20)
        y[i:i + n] = block
        level = dbfs(block)
        if level > -60.0:  # sólo reacciona cuando hay señal
            gain_db += block_s / tau_s * (target_db - level)
    return y


def run(raw):
    return evaluate(analyze_step_test(to_float(raw), FS), clip_fraction(raw))


def test_linear_chain_with_fixed_gain_passes():
    verdict, checks = run(record(0.5 * generate_stimulus(FS)))  # ganancia fija: sesgo común
    assert verdict == "APTO", checks


def test_agc_is_detected():
    verdict, checks = run(record(simulate_agc(generate_stimulus(FS))))
    failed = {c["prueba"] for c in checks if not c["ok"]}
    assert verdict == "NO APTO"
    assert "escalon_subida" in failed


def test_clipping_is_detected():
    verdict, checks = run(record(40 * generate_stimulus(FS)))
    assert verdict == "NO APTO"
    assert "sin_saturacion" in {c["prueba"] for c in checks if not c["ok"]}


def test_silence_is_inconclusive():
    verdict, _ = run(record(np.zeros(24 * FS)))
    assert verdict == "NO CONCLUYENTE"
