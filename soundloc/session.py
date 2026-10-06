"""Sesiones de grabación: carpeta, metadata, tramos y telemetría (sección 2.1, parte C).

Cada sesión vive en su propia carpeta con los datos crudos y un sesion.json que
dice cómo se grabaron. Sin esa metadata, en tres meses el audio no sirve.
"""

import csv
import json
import math
import subprocess
import sys
import wave
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent

AUDIO = "audio.wav"
TIMESTAMPS = "audio_tiempos.csv"
SEGMENTS = "segmentos.csv"
TELEMETRY = "telemetria.csv"
META = "sesion.json"

_SEGMENT_FIELDS = ["etiqueta", "tipo", "t_inicio", "t_fin", "distancia_m", "asentamiento_s"]
_TELEMETRY_ORDER = ["tof", "h", "bat", "templ", "temph", "pitch", "roll", "yaw",
                    "vgx", "vgy", "vgz", "baro", "time", "agx", "agy", "agz"]


def git_version():
    """Con qué versión del código se grabó, para poder reproducir el análisis."""
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=PROJECT_ROOT,
                                capture_output=True, text=True, check=True).stdout.strip()
        status = subprocess.run(["git", "status", "--porcelain"], cwd=PROJECT_ROOT,
                                capture_output=True, text=True).stdout.strip()
        return {"commit": commit, "con_cambios_sin_commit": bool(status)}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "con_cambios_sin_commit": None}


class Session:
    def __init__(self, root, kind):
        now = datetime.now()
        self.dir = Path(root) / f"{now:%Y%m%d-%H%M%S}_{kind}"
        self.dir.mkdir(parents=True, exist_ok=False)
        self.segments = []
        self.meta = {"tipo": kind, "inicio": now.isoformat(timespec="seconds"),
                     "codigo": git_version(), "python": sys.version.split()[0]}

    @property
    def audio_path(self):
        return self.dir / AUDIO

    @property
    def timestamps_path(self):
        return self.dir / TIMESTAMPS

    def add_segment(self, label, kind, t_start, t_end, distance_m=None, settle_s=None):
        self.segments.append({"etiqueta": label, "tipo": kind, "t_inicio": t_start,
                              "t_fin": t_end, "distancia_m": distance_m,
                              "asentamiento_s": settle_s})

    def write_segments(self):
        with open(self.dir / SEGMENTS, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=_SEGMENT_FIELDS)
            writer.writeheader()
            for seg in self.segments:
                writer.writerow({k: ("" if v is None else v) for k, v in seg.items()})

    def write_telemetry(self, state_log):
        keys = {k for _, state in state_log for k in state}
        columns = [k for k in _TELEMETRY_ORDER if k in keys] + sorted(keys - set(_TELEMETRY_ORDER))
        with open(self.dir / TELEMETRY, "w", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["t"] + columns)
            for t, state in state_log:
                writer.writerow([f"{t:.6f}"] + [state.get(k, "") for k in columns])

    def write_meta(self):
        self.meta["fin"] = datetime.now().isoformat(timespec="seconds")
        (self.dir / META).write_text(json.dumps(self.meta, ensure_ascii=False, indent=2),
                                     encoding="utf-8")


@dataclass
class SessionData:
    path: Path
    meta: dict
    fs: int
    audio: np.ndarray  # int16, primer canal
    chunk_frames: np.ndarray
    chunk_times: np.ndarray
    segments: list
    telemetry: dict


def _float_or_none(value):
    return float(value) if value not in ("", None) else None


def _to_float(value):
    try:
        return float(value)
    except ValueError:
        return math.nan


def load_session(path):
    path = Path(path)
    meta = json.loads((path / META).read_text(encoding="utf-8"))
    with wave.open(str(path / AUDIO), "rb") as w:
        fs, channels = w.getframerate(), w.getnchannels()
        raw = w.readframes(w.getnframes())
    audio = np.frombuffer(raw, dtype="<i2").reshape(-1, channels)[:, 0].copy()

    with open(path / TIMESTAMPS, newline="") as fh:
        rows = list(csv.DictReader(fh))
    chunk_frames = np.array([int(r["muestras_fin"]) for r in rows])
    chunk_times = np.array([float(r["t"]) for r in rows])

    segments = []
    if (path / SEGMENTS).exists():
        with open(path / SEGMENTS, newline="") as fh:
            for r in csv.DictReader(fh):
                segments.append({"etiqueta": r["etiqueta"], "tipo": r["tipo"],
                                 "t_inicio": float(r["t_inicio"]), "t_fin": float(r["t_fin"]),
                                 "distancia_m": _float_or_none(r["distancia_m"]),
                                 "asentamiento_s": _float_or_none(r["asentamiento_s"])})

    telemetry = {}
    if (path / TELEMETRY).exists():
        with open(path / TELEMETRY, newline="") as fh:
            reader = csv.reader(fh)
            header = next(reader, None)
            rows = list(reader)
        if header:
            columns = list(zip(*rows)) if rows else [()] * len(header)
            telemetry = {name: np.array([_to_float(v) for v in col])
                         for name, col in zip(header, columns)}

    return SessionData(path, meta, fs, audio, chunk_frames, chunk_times, segments, telemetry)
