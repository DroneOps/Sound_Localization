"""Búsqueda acústica con el Crazyflie: lógica de decisión y misión completa en simulación."""

import json
import signal
import subprocess
import sys

import numpy as np
import pytest

from soundloc.acoustic_search import candidate_points, decide, decide_from_audio, visit_order
from soundloc.session import PROJECT_ROOT


def test_candidate_points_are_evenly_spaced_from_near_to_far():
    assert candidate_points((1.0, 0.0), (-1.0, 2.0), 3) == [(1.0, 0.0), (0.0, 1.0), (-1.0, 2.0)]


def test_visit_order_gives_every_point_the_same_mean_time():
    order = visit_order(3, 2)
    assert order == [0, 1, 2, 2, 1, 0]
    mean_slot = [np.mean([k for k, p in enumerate(order) if p == i]) for i in range(3)]
    assert mean_slot == [2.5, 2.5, 2.5]  # una deriva lineal les suma lo mismo a todos


def _rows(levels_by_point):
    return [{"punto": p, "visita": v + 1, "tipo": "hover", "nivel_banda_dbfs": level}
            for p, levels in enumerate(levels_by_point) for v, level in enumerate(levels)]


def test_a_clear_winner_is_confident():
    result = decide(_rows([[-30, -30.5], [-36, -35.5], [-40, -40]]), 3, ambient_db=-70)
    assert result["ganador"] == 0
    assert result["margen_db"] == pytest.approx(5.5, abs=0.1)
    assert result["rondas_ganadas"] == 2
    assert result["confiable"]


def test_a_margin_smaller_than_the_spread_between_visits_is_not_confident():
    result = decide(_rows([[-30, -36], [-31, -31]]), 2, ambient_db=-70)
    assert result["ganador"] == 1
    assert not result["confiable"]


def test_a_drone_buried_in_the_room_noise_is_not_confident():
    result = decide(_rows([[-60, -60], [-66, -66]]), 2, ambient_db=-61)
    assert result["ganador"] == 0
    assert result["dron_audible"] is False
    assert not result["confiable"]


def test_levels_are_measured_inside_each_hover_window():
    fs = 16000
    t = np.arange(6 * fs) / fs
    rng = np.random.default_rng(0)
    tone = np.sin(2 * np.pi * 1000 * t)
    audio = 0.001 * rng.standard_normal(t.size)
    audio[fs:3 * fs] += 0.1 * tone[fs:3 * fs]      # P1: fuerte
    audio[4 * fs:] += 0.01 * tone[4 * fs:]          # P2: 20 dB más bajo
    audio = np.round(audio * 32768).astype(np.int16)
    segments = [{"etiqueta": "P1_v1", "tipo": "hover", "t_inicio": 1.0, "t_fin": 3.0, "asentamiento_s": 0.0},
                {"etiqueta": "P2_v1", "tipo": "hover", "t_inicio": 4.0, "t_fin": 6.0, "asentamiento_s": 0.0}]
    result = decide_from_audio(audio, fs, 0.0, segments, 2)
    assert result["ganador"] == 0
    assert result["margen_db"] == pytest.approx(20.0, abs=0.5)


def _run(tmp_path, *extra):
    cmd = [sys.executable, "-m", "soundloc.cf_search", "--simulate", "--yes", "--rate", "16000",
           "--hover", "2.5", "--settle", "1", "--ambient-start", "1.5", "--ambient", "1.5",
           "--speed", "1.5", "--out", str(tmp_path), *extra]
    return subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=120)


def test_the_simulated_drone_lands_at_the_point_closest_to_the_microphone(tmp_path):
    # Micrófono del lado de "far": el ganador tiene que ser P3, no simplemente el primero.
    proc = _run(tmp_path, "--near", "1,0", "--far=-1,0.5", "--mic=-2.2,0.5,0.75")
    assert proc.returncode == 0, proc.stdout + proc.stderr

    (session,) = tmp_path.iterdir()
    meta = json.loads((session / "sesion.json").read_text())
    analysis = json.loads((session / "busqueda.json").read_text())
    assert meta["resultado"] == "completo"
    assert meta["decision"]["ganador"] == 2
    assert analysis["ganador"] == 2 and analysis["acerto"] and analysis["confiable"]
    assert analysis["decision_en_vuelo"] == analysis["ganador"]  # vuelo y análisis coinciden
    # Audio simulado a 1/r: de P3 a P2 la distancia pasa de 1.21 m a 1.68 m.
    p = {e["punto"]: e for e in analysis["puntos"]}
    expected = 20 * np.log10(p[1]["distancia_microfono_m"] / p[2]["distancia_microfono_m"])
    assert p[2]["nivel_dbfs"] - p[1]["nivel_dbfs"] == pytest.approx(expected, abs=0.3)

    with open(session / "telemetria.csv") as fh:
        last = fh.read().strip().splitlines()[-1].split(",")
    header = (session / "telemetria.csv").read_text().splitlines()[0].split(",")
    final = {k: float(v) for k, v in zip(header, last) if v}
    assert final["z"] < 0.05                                           # en el piso...
    assert np.hypot(final["x"] + 1.0, final["y"] - 0.5) < 0.05          # ...en P3
    for name in ("audio.wav", "segmentos.csv", "busqueda.png"):
        assert (session / name).exists()


def test_points_too_close_to_the_microphone_are_rejected(tmp_path):
    proc = _run(tmp_path, "--near", "2,0", "--far", "0,0", "--mic", "2.3,0,0.75")
    assert proc.returncode == 2
    assert "del micrófono" in proc.stdout


def test_ctrl_c_in_a_hover_lands_and_saves_everything(tmp_path):
    cmd = [sys.executable, "-u", "-m", "soundloc.cf_search", "--simulate", "--yes", "--rate", "16000",
           "--hover", "6", "--settle", "1", "--ambient-start", "1", "--ambient", "1", "--speed", "1.5",
           "--out", str(tmp_path)]
    proc = subprocess.Popen(cmd, cwd=PROJECT_ROOT, stdout=subprocess.PIPE, text=True)
    lines = []
    for line in proc.stdout:
        lines.append(line)
        if "Hover 2/6" in line:
            proc.send_signal(signal.SIGINT)
    proc.wait(timeout=60)
    out = "".join(lines)
    assert proc.returncode == 1, out
    assert "Aterrizando" in out and "En el piso" in out, out
    (session,) = tmp_path.iterdir()
    meta = json.loads((session / "sesion.json").read_text())
    assert meta["resultado"].startswith("abortado: Ctrl+C")
    for name in ("audio.wav", "audio_tiempos.csv", "segmentos.csv", "telemetria.csv"):
        assert (session / name).exists()
