"""Búsqueda diferencial: visitar puntos candidatos y elegir el de mayor energía en banda.

Es la misma lógica que la de la competencia (sobrevolar cada caja en las mismas
condiciones y quedarse con la más fuerte), con los papeles invertidos para poder
probarla sin el deck de audio: la fuente de sonido es el propio dron y el micrófono
está fijo. Gana el punto donde el micrófono oye más fuerte al dron.

    python -m soundloc.acoustic_search sessions/<carpeta>

Este módulo no sabe nada de ROS ni de radios: recibe audio y tramos, y decide. Así
la decisión en pleno vuelo y el análisis posterior usan exactamente el mismo código.
"""

import argparse
import json
import math
import re
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from .dsp import VOICE_BAND_HZ, bandpass  # noqa: E402
from .levels import dbfs, power_mean_db, to_float  # noqa: E402
from .session import load_session  # noqa: E402
from .timing import estimate_t0, time_to_sample  # noqa: E402

HOVER_TRIM_END_S = 0.3
AMBIENT_TRIM_S = 0.5
MIN_WINDOW_S = 1.0
MIN_SNR_DB = 3.0  # por debajo de esto, lo que se mide es el cuarto, no el dron
_HOVER_LABEL = re.compile(r"^P(\d+)_v(\d+)$")


def candidate_points(near, far, n):
    """n puntos equiespaciados sobre el segmento que va de `near` a `far` (x, y en metros)."""
    if n < 2:
        raise ValueError("Hacen falta al menos 2 puntos para comparar")
    return [(near[0] + (far[0] - near[0]) * k / (n - 1),
             near[1] + (far[1] - near[1]) * k / (n - 1)) for k in range(n)]


def visit_order(n_points, rounds):
    """Orden de visita que cancela una deriva lineal en el tiempo.

    El nivel del dron cambia durante el vuelo (la batería baja y los motores aceleran
    para sostener el mismo empuje). Visitando A B C C B A, el instante promedio de las
    visitas es el mismo para todos los puntos, así que una deriva lineal les suma lo
    mismo a todos y no cambia cuál gana.
    """
    forward = list(range(n_points))
    order = []
    for r in range(rounds):
        order += forward if r % 2 == 0 else forward[::-1]
    return order


def hover_label(point_index, visit):
    return f"P{point_index + 1}_v{visit}"


def parse_hover_label(label):
    m = _HOVER_LABEL.match(label)
    return (int(m[1]) - 1, int(m[2])) if m else None


def _window(seg):
    if seg["tipo"] == "hover":
        return seg["t_inicio"] + (seg["asentamiento_s"] or 0.0), seg["t_fin"] - HOVER_TRIM_END_S
    return seg["t_inicio"] + AMBIENT_TRIM_S, seg["t_fin"] - AMBIENT_TRIM_S


def _mean_position(telemetry, ta, tb):
    if not telemetry or "t" not in telemetry or "x" not in telemetry:
        return None
    t = np.asarray(telemetry["t"], dtype=float)
    mask = (t >= ta) & (t <= tb)
    if not mask.any():
        return None
    return tuple(float(np.nanmean(np.asarray(telemetry[k], dtype=float)[mask])) for k in "xyz")


def segment_levels(audio, fs, t0, segments, band=VOICE_BAND_HZ, telemetry=None):
    """Nivel en banda de cada tramo de ambiente y de hover.

    Se filtra la grabación completa y se recorta después: el filtro tiene memoria, y
    cortar antes metería transitorios en los bordes de cada tramo.
    """
    x = bandpass(to_float(audio), fs, band)
    rows = []
    for seg in segments:
        if seg["tipo"] not in ("hover", "ambiente"):
            continue
        ta, tb = _window(seg)
        i0 = max(0, time_to_sample(ta, t0, fs))
        i1 = min(len(x), time_to_sample(tb, t0, fs))
        row = {"etiqueta": seg["etiqueta"], "tipo": seg["tipo"], "t_inicio": ta, "t_fin": tb}
        parsed = parse_hover_label(seg["etiqueta"]) if seg["tipo"] == "hover" else None
        if parsed:
            row["punto"], row["visita"] = parsed
        if i1 - i0 < MIN_WINDOW_S * fs:
            row["nota"] = "ventana de medición demasiado corta"
        else:
            row["nivel_banda_dbfs"] = dbfs(x[i0:i1])
        pos = _mean_position(telemetry, ta, tb)
        if pos is not None:
            row["posicion_m"] = pos
        rows.append(row)
    return rows


def decide(rows, n_points, ambient_db=None):
    """Elige el punto con más energía en banda, promediando sus visitas en potencia.

    Además del ganador, dice qué tan confiable es la decisión:
    - margen: cuántos dB le saca el ganador al segundo lugar;
    - dispersión: cuánto varían entre sí las visitas a un mismo punto. Si el margen no
      supera la dispersión, el ganador pudo salir por azar;
    - si ganó en todas las rondas;
    - si el dron se oye por encima del ambiente en todos los puntos.
    """
    per_point = []
    for p in range(n_points):
        levels = [r["nivel_banda_dbfs"] for r in rows
                  if r.get("punto") == p and "nivel_banda_dbfs" in r]
        entry = {"punto": p, "visitas_dbfs": levels,
                 "nivel_dbfs": power_mean_db(levels) if levels else float("nan"),
                 "dispersion_db": (max(levels) - min(levels)) if len(levels) >= 2 else 0.0}
        if ambient_db is not None and math.isfinite(ambient_db) and levels:
            entry["snr_db"] = entry["nivel_dbfs"] - ambient_db
        per_point.append(entry)

    measured = [e for e in per_point if math.isfinite(e["nivel_dbfs"])]
    if len(measured) < 2:
        return {"puntos": per_point, "ganador": None,
                "nota": "no hay mediciones suficientes para comparar"}
    ranked = sorted(measured, key=lambda e: e["nivel_dbfs"], reverse=True)
    winner, second = ranked[0], ranked[1]
    margin = winner["nivel_dbfs"] - second["nivel_dbfs"]
    spread = max(e["dispersion_db"] for e in measured)

    visits = max((len(e["visitas_dbfs"]) for e in measured), default=0)
    wins = 0
    for v in range(visits):
        round_levels = {e["punto"]: e["visitas_dbfs"][v] for e in measured if v < len(e["visitas_dbfs"])}
        if round_levels and max(round_levels, key=round_levels.get) == winner["punto"]:
            wins += 1

    snrs = [e["snr_db"] for e in measured if "snr_db" in e]
    audible = (min(snrs) >= MIN_SNR_DB) if snrs else None
    return {"puntos": per_point,
            "ranking": [e["punto"] for e in ranked],
            "ganador": winner["punto"],
            "margen_db": margin,
            "dispersion_max_db": spread,
            "rondas_ganadas": wins,
            "rondas": visits,
            "dron_audible": audible,
            "confiable": bool(margin > spread and wins == visits and audible is not False)}


def decide_from_audio(audio, fs, t0, segments, n_points, band=VOICE_BAND_HZ, telemetry=None):
    rows = segment_levels(audio, fs, t0, segments, band, telemetry)
    ambient = [r["nivel_banda_dbfs"] for r in rows if r["tipo"] == "ambiente" and "nivel_banda_dbfs" in r]
    ambient_db = power_mean_db(ambient) if ambient else None
    result = decide(rows, n_points, ambient_db)
    result["ambiente_dbfs"] = ambient_db
    result["tramos"] = rows
    return result


def _clean(obj):
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, (float, np.floating)):
        return float(obj) if math.isfinite(obj) else None
    if isinstance(obj, np.integer):
        return int(obj)
    return obj


def analyze(session_dir):
    """Rehace la decisión con los datos guardados y la compara con la geometría real."""
    session_dir = Path(session_dir)
    s = load_session(session_dir)
    plan = s.meta.get("plan", {})
    points = [tuple(p) for p in plan.get("puntos_m", [])]
    band = tuple(plan.get("banda_hz", VOICE_BAND_HZ))
    t0 = estimate_t0(s.chunk_frames, s.chunk_times, s.fs)
    result = decide_from_audio(s.audio, s.fs, t0, s.segments, len(points), band, s.telemetry)

    mic = plan.get("microfono_m")
    if mic is not None:
        for e in result["puntos"]:
            positions = [r["posicion_m"] for r in result["tramos"]
                         if r.get("punto") == e["punto"] and "posicion_m" in r]
            where = np.mean(positions, axis=0) if positions else (*points[e["punto"]], plan.get("altura_m", 0))
            e["distancia_microfono_m"] = float(math.dist(where, mic))
        expected = min(result["puntos"], key=lambda e: e["distancia_microfono_m"])["punto"]
        result["esperado"] = expected
        result["acerto"] = result["ganador"] == expected

    result["sesion"] = str(session_dir)
    result["simulado"] = s.meta.get("simulado", False)
    result["decision_en_vuelo"] = s.meta.get("decision", {}).get("ganador")
    result["banda_hz"] = list(band)
    _plot(s, points, mic, result, session_dir / "busqueda.png")
    (session_dir / "busqueda.json").write_text(
        json.dumps(_clean(result), ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def _fmt(value, spec, missing="—"):
    return format(value, spec) if value is not None and math.isfinite(value) else missing


def print_report(result):
    print("\nBÚSQUEDA DIFERENCIAL" + ("  (SIMULACIÓN)" if result.get("simulado") else ""))
    print(f"  Banda {result['banda_hz'][0]:g}–{result['banda_hz'][1]:g} Hz; "
          f"ambiente {_fmt(result.get('ambiente_dbfs'), '.1f')} dBFS")
    print(f"  {'punto':>5}  {'nivel dBFS':>10}  {'SNR dB':>7}  {'dispersión':>10}  {'dist. mic':>9}  visitas")
    for e in result["puntos"]:
        visits = ", ".join(f"{v:.1f}" for v in e["visitas_dbfs"])
        mark = "  <- ganador" if e["punto"] == result.get("ganador") else ""
        print(f"  {'P' + str(e['punto'] + 1):>5}  {_fmt(e['nivel_dbfs'], '10.1f')}  "
              f"{_fmt(e.get('snr_db'), '7.1f')}  {_fmt(e['dispersion_db'], '10.1f')}  "
              f"{_fmt(e.get('distancia_microfono_m'), '7.2f') + ' m':>9}  [{visits}]{mark}")
    if result.get("ganador") is None:
        print(f"  Sin decisión: {result.get('nota', '')}")
        return
    print(f"  Margen sobre el segundo: {result['margen_db']:.1f} dB; dispersión máxima entre visitas: "
          f"{result['dispersion_max_db']:.1f} dB; ganó {result['rondas_ganadas']} de {result['rondas']} rondas")
    if result.get("dron_audible") is False:
        print(f"  ¡Ojo! En algún punto el dron no supera al ambiente por {MIN_SNR_DB:g} dB: "
              "la decisión puede ser ruido del cuarto")
    print(f"  Decisión {'confiable' if result['confiable'] else 'NO confiable'}")
    if "acerto" in result:
        print(f"  Punto más cercano al micrófono: P{result['esperado'] + 1} → "
              f"{'ACERTÓ' if result['acerto'] else 'FALLÓ'}")
    if result.get("decision_en_vuelo") not in (None, result["ganador"]):
        print(f"  ¡La decisión en vuelo (P{result['decision_en_vuelo'] + 1}) no coincide con el análisis!")


def _plot(s, points, mic, result, path):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    for e in result["puntos"]:
        visits = e["visitas_dbfs"]
        ax1.plot([e["punto"] + 1] * len(visits), visits, "o", color="0.6")
        if math.isfinite(e["nivel_dbfs"]):
            ax1.plot(e["punto"] + 1, e["nivel_dbfs"], "s", ms=10,
                     color="C3" if e["punto"] == result.get("ganador") else "C0")
    if result.get("ambiente_dbfs") is not None:
        ax1.axhline(result["ambiente_dbfs"], color="0.4", ls="--", label="ambiente")
        ax1.legend()
    ax1.set_xticks(range(1, len(points) + 1), [f"P{i + 1}" for i in range(len(points))])
    ax1.set_ylabel("nivel en banda (dBFS)")
    ax1.set_title("Nivel por punto (gris: cada visita; cuadro: promedio)")
    ax1.grid(alpha=0.3)

    tel = s.telemetry
    if tel and "x" in tel:
        ax2.plot(tel["x"], tel["y"], color="0.7", lw=1, label="trayectoria")
    for i, (x, y) in enumerate(points):
        winner = i == result.get("ganador")
        ax2.plot(x, y, "s", ms=12, color="C3" if winner else "C0")
        ax2.annotate(f"P{i + 1}", (x, y), textcoords="offset points", xytext=(8, 8))
    if mic is not None:
        ax2.plot(mic[0], mic[1], "k^", ms=12, label="micrófono")
    # Ventana cuadrada alrededor de puntos y micrófono, para que una línea recta no se aplaste.
    xy = np.array(points + ([tuple(mic[:2])] if mic is not None else []))
    center = (xy.min(axis=0) + xy.max(axis=0)) / 2
    half = max(np.ptp(xy, axis=0).max() / 2 + 0.5, 1.0)
    ax2.set_xlim(center[0] - half, center[0] + half)
    ax2.set_ylim(center[1] - half, center[1] + half)
    ax2.set_aspect("equal")
    ax2.set_xlabel("x (m)")
    ax2.set_ylabel("y (m)")
    ax2.set_title("Vista superior (marco del OptiTrack)")
    ax2.grid(alpha=0.3)
    ax2.legend(loc="best")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("session", help="carpeta de la sesión")
    args = p.parse_args(argv)
    print_report(analyze(args.session))
    return 0


if __name__ == "__main__":
    sys.exit(main())
