"""Junta varias sesiones del banco volante, por ejemplo un vuelo corto por distancia.

    python -m soundloc.compare_sessions sessions/<vuelo_1m> sessions/<vuelo_1.8m> ...

Cuando el Tello no puede moverse con precisión, se pone a mano sobre cada marca
del piso, despega, hace un solo hover y aterriza. Cada vuelo resta su propio
ambiente; aquí se comparan los hovers de todos los vuelos.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from .analyze_flight import (INVERSE_SQUARE_DB_PER_DOUBLING, _clean, _fit_inverse_square, _fmt,
                             _plot_level_vs_distance, _repeatability, analyze)
from .session import PROJECT_ROOT


def compare(session_dirs, out_dir):
    hovers = []
    for d in session_dirs:
        name = Path(d).name
        for r in analyze(d)["tramos"]:
            if r["tipo"] == "hover" and "nivel_dbfs" in r and r.get("nivel_dron_dbfs") is not None:
                hovers.append(dict(r, sesion=name, etiqueta=f"{r['etiqueta']}@{name[9:15]}"))
    hovers.sort(key=lambda r: r["sesion"])
    fit = _fit_inverse_square(hovers)
    summary = {"sesiones": [str(d) for d in session_dirs], "ajuste": fit,
               "repetibilidad_db": _repeatability(hovers), "hovers": hovers}
    out_dir.mkdir(parents=True, exist_ok=True)
    _plot_level_vs_distance(hovers, fit, out_dir / "nivel_vs_distancia.png")
    (out_dir / "comparacion.json").write_text(json.dumps(_clean(summary), ensure_ascii=False, indent=2),
                                              encoding="utf-8")
    return summary


def print_report(summary, out_dir):
    print(f"\n=== Comparación de {len(summary['sesiones'])} sesiones ===")
    print("  Hover                       D.real  Dron    Banda   En banda  Predic.  Dif.   Pico")
    for r in summary["hovers"]:
        print(f"  {r['etiqueta']:<27} {_fmt(r.get('distancia_real_m'), '.2f'):>6}  "
              f"{_fmt(r.get('nivel_dron_dbfs'), '.1f'):>6}  {_fmt(r.get('nivel_banda_dron_dbfs'), '.1f'):>6}  "
              f"{_fmt(r.get('fraccion_en_banda_db'), '+.1f'):>8}  {_fmt(r.get('prediccion_dbfs'), '.1f'):>7}  "
              f"{_fmt(r.get('diferencia_db'), '+.1f'):>5}  {_fmt(r.get('pico_hz'), '.0f')} Hz")
    fit = summary["ajuste"]
    if fit:
        print(f"\nPendiente: {fit['pendiente_db_por_duplicacion']:+.2f} dB por duplicación de distancia "
              f"(ley inversa del cuadrado: {INVERSE_SQUARE_DB_PER_DOUBLING:+.2f})")
    else:
        print("\nHace falta al menos dos distancias distintas para la pendiente.")
    if summary["repetibilidad_db"]:
        print("Repetibilidad entre vuelos: "
              + "; ".join(f"{k}: {v:.2f} dB" for k, v in summary["repetibilidad_db"].items()))
    print(f"Resultados en: {out_dir}")


def main(argv=None):
    p = argparse.ArgumentParser(description="Compara varias sesiones del banco volante")
    p.add_argument("session_dirs", nargs="+")
    p.add_argument("--out", default=None, help="carpeta de resultados (por omisión, una nueva en sessions/)")
    args = p.parse_args(argv)
    out = Path(args.out) if args.out else PROJECT_ROOT / "sessions" / f"comparacion_{datetime.now():%Y%m%d-%H%M%S}"
    print_report(compare(args.session_dirs, out), out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
