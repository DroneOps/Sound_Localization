"""Prueba de punta a punta en simulación: Tello simulado, audio simulado y análisis.

El audio simulado decae exactamente como 1/r, así que el análisis tiene que
recuperar −6.02 dB por duplicación de distancia. Si no lo hace, el error está en
la cadena de sincronización o de análisis, no en la física.
"""

import json
import subprocess
import sys

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
    assert len([t for t in analysis["tramos"] if t["tipo"] == "hover"]) == 3
    for name in ("audio.wav", "telemetria.csv", "segmentos.csv", "espectrograma.png",
                 "nivel_vs_distancia.png", "linea_de_tiempo.png"):
        assert (session / name).exists()
