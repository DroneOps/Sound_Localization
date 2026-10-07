"""Prueba de punta a punta en simulación: Tello simulado, audio simulado y análisis.

El audio simulado decae exactamente como 1/r, así que el análisis tiene que
recuperar −6.02 dB por duplicación de distancia. Si no lo hace, el error está en
la cadena de sincronización o de análisis, no en la física.
"""

import csv
import json
import signal
import subprocess
import sys
import time
import wave

import pytest

from soundloc.session import PROJECT_ROOT


def test_simulated_session_recovers_the_inverse_square_law(tmp_path):
    cmd = [sys.executable, "-m", "soundloc.bench_flight", "--simulate", "--yes",
           "--plan", "1,2,1", "--hover", "3", "--settle", "1", "--ambient", "2",
           "--rate", "16000", "--sim-speed", "2.0",
           "--cmd-port", "38889", "--state-port", "38890", "--out", str(tmp_path)]
    proc = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    (session,) = tmp_path.iterdir()
    meta = json.loads((session / "sesion.json").read_text())
    analysis = json.loads((session / "analisis.json").read_text())
    assert meta["resultado"] == "completo"
    assert analysis["ajuste"]["pendiente_db_por_duplicacion"] == pytest.approx(-6.02, abs=0.3)
    assert analysis["repetibilidad_db"]["1 m"] < 0.3
    hovers = [t for t in analysis["tramos"] if t["tipo"] == "hover"]
    assert len(hovers) == 3
    # El ruido simulado es 60 % tonal (610, 1220 y 1830 Hz, todos dentro de la banda) y 40 %
    # ancho de banda hasta 8 kHz: en la banda queda 0.6 + 0.4·(2700/8000) ≈ −1.3 dB.
    assert all(-2.0 < t["fraccion_en_banda_db"] < -0.8 for t in hovers)
    for name in ("audio.wav", "telemetria.csv", "segmentos.csv", "espectrograma.png",
                 "nivel_vs_distancia.png", "linea_de_tiempo.png"):
        assert (session / name).exists()


def test_an_unexpected_landing_is_detected_and_explained(tmp_path):
    cmd = [sys.executable, "-m", "soundloc.bench_flight", "--simulate", "--yes",
           "--plan", "1,2", "--hover", "4", "--settle", "1", "--ambient", "1", "--ambient-start", "1",
           "--rate", "16000", "--sim-speed", "2.0", "--sim-auto-land", "3",
           "--cmd-port", "38891", "--state-port", "38892", "--out", str(tmp_path)]
    proc = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 1
    assert "aterrizó por su cuenta" in proc.stdout
    assert "No se confirmó el aterrizaje" not in proc.stdout  # sin alarma falsa


def test_one_short_flight_per_distance_can_be_combined(tmp_path):
    """Un vuelo por distancia, con el Tello puesto a mano en cada marca, y la comparación."""
    from soundloc.compare_sessions import compare

    flights = tmp_path / "vuelos"
    for i, d in enumerate(("1", "2")):
        cmd = [sys.executable, "-m", "soundloc.bench_flight", "--simulate", "--yes",
               "--start-distance", d, "--plan", d, "--max-distance", "2", "--hover", "3", "--settle", "1",
               "--ambient", "1", "--ambient-start", "1", "--rate", "16000", "--sim-speed", "2.0",
               "--cmd-port", str(38893 + 2 * i), "--state-port", str(38894 + 2 * i), "--out", str(flights)]
        proc = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        time.sleep(1.1)  # cada sesión lleva la hora en el nombre de su carpeta
    summary = compare(sorted(flights.iterdir()), tmp_path / "comparacion")
    assert len(summary["hovers"]) == 2
    assert summary["ajuste"]["pendiente_db_por_duplicacion"] == pytest.approx(-6.02, abs=0.3)
    assert (tmp_path / "comparacion" / "nivel_vs_distancia.png").exists()


def test_a_rejected_height_adjustment_does_not_abort_the_flight(tmp_path):
    cmd = [sys.executable, "-m", "soundloc.bench_flight", "--simulate", "--yes", "--sim-reject-moves",
           "--mic-height", "1.3", "--plan", "1", "--hover", "3", "--settle", "1", "--ambient", "1",
           "--ambient-start", "1", "--rate", "16000", "--sim-speed", "2.0",
           "--cmd-port", "38897", "--state-port", "38898", "--out", str(tmp_path)]
    proc = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "No se pudo ajustar la altura" in proc.stdout


def test_ctrl_c_during_the_safety_landing_still_saves_everything(tmp_path):
    """El caso real del vuelo a 1.8 m: abortar, y un segundo Ctrl+C mientras aterriza."""
    cmd = [sys.executable, "-u", "-m", "soundloc.bench_flight", "--simulate", "--yes",
           "--plan", "1", "--hover", "10", "--settle", "1", "--ambient", "1", "--ambient-start", "1",
           "--rate", "16000", "--sim-speed", "0.15",  # aterrizar desde 0.8 m tarda ~5 s
           "--cmd-port", "38899", "--state-port", "38900", "--out", str(tmp_path)]
    proc = subprocess.Popen(cmd, cwd=PROJECT_ROOT, stdout=subprocess.PIPE, text=True)
    lines = []
    for line in proc.stdout:
        lines.append(line)
        if "Hover 1/1" in line:
            proc.send_signal(signal.SIGINT)  # primer Ctrl+C: aterrizaje controlado
        if "Aterrizando" in line:
            time.sleep(1.0)
            proc.send_signal(signal.SIGINT)  # segundo Ctrl+C, a medio aterrizaje
    proc.wait(timeout=60)
    (session,) = tmp_path.iterdir()
    meta = json.loads((session / "sesion.json").read_text())
    assert "interrumpida" in meta["resultado"], "".join(lines)
    for name in ("segmentos.csv", "telemetria.csv", "audio_tiempos.csv"):
        assert (session / name).exists()
    with wave.open(str(session / "audio.wav")) as w:
        assert w.getnframes() > 0


def test_a_wav_with_an_unfinished_header_can_still_be_read(tmp_path):
    from soundloc.session import read_wav_bytes
    path = tmp_path / "audio.wav"
    w = wave.open(str(path), "wb")
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(16000)
    w.writeframesraw(b"\x01\x00" * 2 * 1000)
    w._file.flush()  # el programa se interrumpe antes de cerrar: el encabezado dice 0 muestras
    fs, channels, raw = read_wav_bytes(path)
    assert (fs, channels, len(raw)) == (16000, 2, 4000)


def test_ctrl_c_during_takeoff_still_lands(tmp_path):
    """El caso real del vuelo manual: Ctrl+C mientras el Tello todavía está despegando."""
    cmd = [sys.executable, "-u", "-m", "soundloc.bench_flight", "--simulate", "--yes",
           "--plan", "1", "--hover", "5", "--settle", "1", "--ambient", "1", "--ambient-start", "1",
           "--rate", "16000", "--sim-speed", "0.2",  # despegar hasta 0.8 m tarda ~4 s
           "--cmd-port", "38901", "--state-port", "38902", "--out", str(tmp_path)]
    proc = subprocess.Popen(cmd, cwd=PROJECT_ROOT, stdout=subprocess.PIPE, text=True)
    lines = []
    for line in proc.stdout:
        lines.append(line)
        if "Despegando" in line:
            time.sleep(1.0)
            proc.send_signal(signal.SIGINT)
    proc.wait(timeout=60)
    out = "".join(lines)
    assert "espero a que termine" in out and "Aterrizando" in out, out
    (session,) = tmp_path.iterdir()
    with open(session / "telemetria.csv") as fh:
        rows = list(csv.DictReader(fh))
    heights = [float(r["h"]) for r in rows]
    top = heights.index(max(heights))
    assert heights[top] > 50                    # llegó a despegar...
    assert min(heights[top:]) <= 10             # ...y el programa esperó a que bajara
