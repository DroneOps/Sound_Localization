"""Análisis de una sesión del banco volante.

    python -m soundloc.analyze_flight sessions/<carpeta>

Mide el nivel de cada tramo, lo compara con la ley inversa del cuadrado, mide la
repetibilidad entre hovers a la misma distancia y genera tres gráficas. Nunca
modifica los datos crudos: se puede volver a correr cuantas veces haga falta.
"""

import argparse
import json
import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from scipy.signal import spectrogram  # noqa: E402

from .dsp import VOICE_BAND_HZ, bandpass  # noqa: E402
from .levels import (clip_fraction, dbfs, dominant_peak_hz, power_mean_db,  # noqa: E402
                     short_time_levels, subtract_level, to_float)
from .session import load_session  # noqa: E402
from .timing import clock_drift_s, estimate_t0, time_to_sample  # noqa: E402

AMBIENT_TRIM_S = 0.5
HOVER_TRIM_END_S = 0.5
MIN_WINDOW_S = 1.0
INVERSE_SQUARE_DB_PER_DOUBLING = -20 * math.log10(2)  # −6.02 dB


def _window(seg):
    """Parte del tramo que se mide: sin el asentamiento tras moverse ni los bordes."""
    if seg["tipo"] == "hover":
        return seg["t_inicio"] + (seg["asentamiento_s"] or 0.0), seg["t_fin"] - HOVER_TRIM_END_S
    if seg["tipo"] == "ambiente":
        return seg["t_inicio"] + AMBIENT_TRIM_S, seg["t_fin"] - AMBIENT_TRIM_S
    return seg["t_inicio"], seg["t_fin"]


def _telemetry_stats(tel, ta, tb):
    if "t" not in tel:
        return {}
    mask = (tel["t"] >= ta) & (tel["t"] <= tb)
    out = {"lecturas_telemetria": int(mask.sum())}
    for key in ("tof", "h", "bat", "temph", "pitch", "roll"):
        if key in tel and mask.any():
            values = tel[key][mask]
            values = values[np.isfinite(values)]
            if values.size:
                out[f"{key}_media"] = float(values.mean())
                out[f"{key}_std"] = float(values.std())
    return out


def _segment_row(s, seg, t0, mic_height, x_all, x_band):
    ta, tb = _window(seg)
    row = {"etiqueta": seg["etiqueta"], "tipo": seg["tipo"],
           "distancia_nominal_m": seg["distancia_m"], "inicio_s": ta - t0, "fin_s": tb - t0}
    i0 = max(0, time_to_sample(ta, t0, s.fs))
    i1 = min(len(s.audio), time_to_sample(tb, t0, s.fs))
    if i1 - i0 < MIN_WINDOW_S * s.fs:
        row["nota"] = "ventana de medición demasiado corta"
        return row
    raw = s.audio[i0:i1]
    x = x_all[i0:i1]
    row["nivel_dbfs"] = dbfs(x)
    if x_band is not None:
        row["nivel_banda_dbfs"] = dbfs(x_band[i0:i1])
    row["saturacion_pct"] = 100.0 * clip_fraction(raw)
    row.update(_telemetry_stats(s.telemetry, ta, tb))
    if seg["tipo"] == "hover":
        row["pico_hz"] = dominant_peak_hz(x, s.fs)
        if mic_height is not None and "tof_media" in row and seg["distancia_m"] is not None:
            row["altura_m"] = row["tof_media"] / 100.0
            row["distancia_real_m"] = math.hypot(seg["distancia_m"], row["altura_m"] - mic_height)
    return row


def _distance(row):
    return row.get("distancia_real_m", row["distancia_nominal_m"])


def _fit_inverse_square(hovers):
    usable = [r for r in hovers if _distance(r) and np.isfinite(r["nivel_dron_dbfs"])]
    if len({round(_distance(r), 2) for r in usable}) < 2:
        return None
    d = np.array([_distance(r) for r in usable])
    level = np.array([r["nivel_dron_dbfs"] for r in usable])
    slope, intercept = np.polyfit(np.log2(d), level, 1)
    d_ref, level_ref = d[0], level[0]
    for r in usable:
        r["prediccion_dbfs"] = level_ref + INVERSE_SQUARE_DB_PER_DOUBLING * math.log2(_distance(r) / d_ref)
        r["diferencia_db"] = r["nivel_dron_dbfs"] - r["prediccion_dbfs"]
    return {"pendiente_db_por_duplicacion": float(slope),
            "pendiente_esperada": INVERSE_SQUARE_DB_PER_DOUBLING,
            "nivel_a_1m_dbfs": float(intercept)}


def _repeatability(hovers):
    groups = {}
    for r in hovers:
        if r["distancia_nominal_m"] is not None and np.isfinite(r["nivel_dron_dbfs"]):
            groups.setdefault(r["distancia_nominal_m"], []).append(r["nivel_dron_dbfs"])
    return {f"{d:g} m": max(v) - min(v) for d, v in sorted(groups.items()) if len(v) >= 2}


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
    session_dir = Path(session_dir)
    s = load_session(session_dir)
    t0 = estimate_t0(s.chunk_frames, s.chunk_times, s.fs)
    mic_height = s.meta.get("microfono", {}).get("altura_m")
    x_all = to_float(s.audio)
    # Se filtra la grabación completa y se recorta después (el filtro tiene memoria).
    x_band = bandpass(x_all, s.fs) if s.fs / 2 > VOICE_BAND_HZ[1] else None
    rows = [_segment_row(s, seg, t0, mic_height, x_all, x_band) for seg in s.segments]

    ambient_rows = [r for r in rows if r["tipo"] == "ambiente" and "nivel_dbfs" in r]
    ambient = [r["nivel_dbfs"] for r in ambient_rows]
    ambient_ref = power_mean_db(ambient) if ambient else float("nan")
    ambient_band = [r["nivel_banda_dbfs"] for r in ambient_rows if "nivel_banda_dbfs" in r]
    ambient_band_ref = power_mean_db(ambient_band) if ambient_band else float("nan")
    hovers = [r for r in rows if r["tipo"] == "hover" and "nivel_dbfs" in r]
    for r in hovers:
        # Lo que mide el micrófono es dron + habitación; restamos la habitación en potencia.
        r["nivel_dron_dbfs"] = subtract_level(r["nivel_dbfs"], ambient_ref) if ambient else r["nivel_dbfs"]
        if "nivel_banda_dbfs" in r:
            r["nivel_banda_dron_dbfs"] = (subtract_level(r["nivel_banda_dbfs"], ambient_band_ref)
                                          if ambient_band else r["nivel_banda_dbfs"])
            # Cuánta de la potencia del dron cae en la banda de voz, en dB (0 = toda).
            r["fraccion_en_banda_db"] = r["nivel_banda_dron_dbfs"] - r["nivel_dron_dbfs"]

    summary = {
        "sesion": str(session_dir),
        "simulado": s.meta.get("simulado", False),
        "duracion_s": len(s.audio) / s.fs,
        "deriva_reloj_ms": 1000 * clock_drift_s(s.chunk_frames, s.chunk_times, s.fs),
        "ambiente": {"niveles_dbfs": ambient, "referencia_dbfs": ambient_ref,
                     "referencia_banda_dbfs": ambient_band_ref,
                     "cambio_db": ambient[-1] - ambient[0] if len(ambient) >= 2 else None},
        "banda_hz": list(VOICE_BAND_HZ),
        "ajuste": _fit_inverse_square(hovers),
        "repetibilidad_db": _repeatability(hovers),
        "tramos": rows,
    }
    _plot_spectrogram(s, rows, session_dir / "espectrograma.png")
    _plot_level_vs_distance(hovers, summary["ajuste"], session_dir / "nivel_vs_distancia.png")
    _plot_timeline(s, t0, rows, session_dir / "linea_de_tiempo.png")
    (session_dir / "analisis.json").write_text(
        json.dumps(_clean(summary), ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def _fmt(value, spec, missing="—"):
    return format(value, spec) if value is not None and np.isfinite(value) else missing


def print_report(summary):
    print(f"\n=== Análisis: {summary['sesion']} ===")
    print(f"Duración: {summary['duracion_s']:.1f} s. Deriva del reloj de audio: "
          f"{summary['deriva_reloj_ms']:.1f} ms (cada tramo se recorta al menos 0.5 s por borde).")
    amb = summary["ambiente"]
    if amb["niveles_dbfs"]:
        levels = ", ".join(f"{v:.1f}" for v in amb["niveles_dbfs"])
        print(f"Ambiente con motores apagados: {levels} dBFS"
              + (f" (cambio {amb['cambio_db']:+.1f} dB)" if amb["cambio_db"] is not None else ""))
    print("\n  Tramo            Dist.  Altura  D.real  Nivel   Dron    Predic.  Dif.  Banda  En banda  Sat.%  Pico")
    for r in summary["tramos"]:
        if r["tipo"] != "hover":
            continue
        print(f"  {r['etiqueta']:<16} {_fmt(r['distancia_nominal_m'], '.2f'):>5}  "
              f"{_fmt(r.get('altura_m'), '.2f'):>6}  {_fmt(r.get('distancia_real_m'), '.2f'):>6}  "
              f"{_fmt(r.get('nivel_dbfs'), '.1f'):>6}  {_fmt(r.get('nivel_dron_dbfs'), '.1f'):>6}  "
              f"{_fmt(r.get('prediccion_dbfs'), '.1f'):>7}  {_fmt(r.get('diferencia_db'), '+.1f'):>5}  "
              f"{_fmt(r.get('nivel_banda_dron_dbfs'), '.1f'):>5}  {_fmt(r.get('fraccion_en_banda_db'), '+.1f'):>8}  "
              f"{_fmt(r.get('saturacion_pct'), '.2f'):>5}  {_fmt(r.get('pico_hz'), '.0f')} Hz")
    print(f"  Nivel: banda ancha. Dron: sin la habitación. Banda: dron en {VOICE_BAND_HZ[0]:g}–"
          f"{VOICE_BAND_HZ[1]:g} Hz. En banda: cuánto de su potencia cae ahí (0 dB = toda).")
    fit = summary["ajuste"]
    if fit:
        print(f"\nPendiente medida: {fit['pendiente_db_por_duplicacion']:+.2f} dB cada vez que se "
              f"duplica la distancia (ley inversa del cuadrado: {fit['pendiente_esperada']:+.2f}).")
    if summary["repetibilidad_db"]:
        reps = "; ".join(f"{k}: {v:.2f} dB" for k, v in summary["repetibilidad_db"].items())
        print(f"Repetibilidad (mismo punto, distinto momento): {reps}")
    print("Gráficas: espectrograma.png, nivel_vs_distancia.png, linea_de_tiempo.png")


def analyze_and_report(session_dir):
    summary = analyze(session_dir)
    print_report(summary)
    return summary


def _mark_segments(ax, rows, color):
    for r in rows:
        if r["tipo"] in ("hover", "ambiente") and "nivel_dbfs" in r:
            ax.axvline(r["inicio_s"], color=color, ls="--", lw=0.7)
            ax.axvline(r["fin_s"], color=color, ls="--", lw=0.7)
            ax.text((r["inicio_s"] + r["fin_s"]) / 2, 1.01, r["etiqueta"].replace("_", " "),
                    transform=ax.get_xaxis_transform(), ha="center", va="bottom", fontsize=7,
                    rotation=20)


def _plot_spectrogram(s, rows, path):
    x = to_float(s.audio)
    nperseg = 2048 if s.fs >= 32000 else 1024
    f, t, sxx = spectrogram(x, fs=s.fs, nperseg=nperseg, noverlap=nperseg // 2)
    keep = f <= min(8000.0, s.fs / 2)
    sxx_db = 10 * np.log10(sxx[keep] + 1e-20)
    vmax = np.percentile(sxx_db, 99.5)
    fig, ax = plt.subplots(figsize=(13, 5))
    image = ax.imshow(sxx_db, origin="lower", aspect="auto", cmap="magma", vmin=vmax - 70, vmax=vmax,
                      extent=[t[0], t[-1], f[keep][0], f[keep][-1]])
    _mark_segments(ax, rows, "white")
    ax.set_xlabel("Tiempo (s)")
    ax.set_ylabel("Frecuencia (Hz)")
    fig.colorbar(image, ax=ax, label="Densidad espectral (dB, relativa)")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def _plot_level_vs_distance(hovers, fit, path):
    pts = [(_distance(r), r["nivel_dron_dbfs"], r["etiqueta"]) for r in hovers
           if _distance(r) and np.isfinite(r["nivel_dron_dbfs"])]
    fig, ax = plt.subplots(figsize=(7, 5))
    if pts:
        d = np.array([p[0] for p in pts])
        level = np.array([p[1] for p in pts])
        ax.scatter(d, level, zorder=3, label="Hover medido")
        for di, li, name in pts:
            ax.annotate(name.split("_")[1], (di, li), textcoords="offset points", xytext=(5, 5), fontsize=8)
        grid = np.geomspace(d.min() * 0.9, d.max() * 1.1, 50)
        ax.plot(grid, level[0] + INVERSE_SQUARE_DB_PER_DOUBLING * np.log2(grid / d[0]),
                color="tab:green", ls="--", label="Ley inversa del cuadrado (−6.02 dB por duplicación)")
        if fit:
            ax.plot(grid, fit["nivel_a_1m_dbfs"] + fit["pendiente_db_por_duplicacion"] * np.log2(grid),
                    color="tab:red", lw=1, label=f"Ajuste: {fit['pendiente_db_por_duplicacion']:+.2f} dB por duplicación")
        ax.set_xscale("log", base=2)
        ax.set_xticks(sorted(set(np.round(d, 2))))
        ax.get_xaxis().set_major_formatter(matplotlib.ticker.FormatStrFormatter("%.2f"))
    ax.set_xlabel("Distancia al micrófono (m, escala logarítmica)")
    ax.set_ylabel("Nivel del dron (dBFS)")
    ax.set_title("Nivel contra distancia")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def _plot_timeline(s, t0, rows, path):
    t, levels = short_time_levels(to_float(s.audio), s.fs, 0.25)
    fig, ax = plt.subplots(figsize=(13, 4.5))
    ax.plot(t, levels, color="0.2", lw=0.9, label="Nivel (ventanas de 0.25 s)")
    for r in rows:
        if r["tipo"] == "hover" and "nivel_dbfs" in r:
            ax.axvspan(r["inicio_s"], r["fin_s"], color="tab:blue", alpha=0.12)
    ax.set_xlabel("Tiempo (s)")
    ax.set_ylabel("Nivel (dBFS)")
    if "tof" in s.telemetry:
        ax2 = ax.twinx()
        ax2.plot(s.telemetry["t"] - t0, s.telemetry["tof"], color="tab:orange", lw=0.9, label="Altura ToF (cm)")
        ax2.set_ylabel("Altura medida por el ToF (cm)", color="tab:orange")
    ax.set_title("Línea de tiempo (azul: ventanas de medición de cada hover)")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def main(argv=None):
    p = argparse.ArgumentParser(description="Análisis de una sesión del banco volante")
    p.add_argument("session_dir")
    args = p.parse_args(argv)
    analyze_and_report(args.session_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
