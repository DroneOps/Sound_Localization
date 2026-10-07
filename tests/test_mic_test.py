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


def test_a_startup_click_does_not_hide_the_tone():
    """Imita al códec interno de la laptop: un chasquido saturado y una cola de casi 1 s."""
    raw = record(0.5 * generate_stimulus(FS))
    n = int(0.9 * FS)
    tail = 0.3 * np.exp(-np.arange(n) / (0.1 * FS)) * np.sin(2 * np.pi * 50 * np.arange(n) / FS)
    raw[:n] = np.clip(np.round(tail * 32768), -32768, 32767).astype(np.int16)
    raw[:20] = 32767  # unas cuantas muestras saturadas al abrir el dispositivo
    verdict, checks = run_like_report(raw)
    assert verdict == "APTO", checks


def run_like_report(raw):
    """Como report(): la saturación no se cuenta durante el arranque."""
    from soundloc.mic_test import STARTUP_S
    return evaluate(analyze_step_test(to_float(raw), FS), clip_fraction(raw[int(STARTUP_S * FS):]))


def test_a_brief_noise_is_not_taken_as_the_tone_onset():
    y = 0.5 * generate_stimulus(FS)
    y[int(1.5 * FS):int(1.8 * FS)] += 0.05 * np.random.default_rng(1).normal(size=int(0.3 * FS))
    verdict, checks = run(record(y))
    assert verdict == "APTO", checks


def test_a_tone_only_11_db_above_the_room_is_measured_accurately():
    # Tono A a −41 dBFS y sala a −52 dBFS: la resta del piso corrige el sesgo del ruido.
    verdict, checks = run(record(10 ** (-11 / 20) * generate_stimulus(FS), floor_db=-52.0))
    assert verdict == "APTO", checks


def test_a_tone_buried_in_the_room_is_inconclusive():
    verdict, _ = run(record(10 ** (-27 / 20) * generate_stimulus(FS), floor_db=-55.0))
    assert verdict == "NO CONCLUYENTE"


def test_a_gated_microphone_is_rejected():
    """Imita al Steren: deja pasar el inicio de cada tono y luego lo corta a cero exacto."""
    raw = record(0.5 * generate_stimulus(FS))
    gated = np.zeros_like(raw)
    for start_s in (4.0, 10.0):  # los inicios de A y B, con el silencio previo de 1 s
        i = int(start_s * FS)
        gated[i:i + FS] = raw[i:i + FS]
    verdict, checks = run(gated)
    assert verdict == "NO APTO"
    assert "sin_compuerta" in {c["prueba"] for c in checks if not c["ok"]}
