"""Prueba del micrófono: ¿la cadena es lineal y fija, o hay AGC o supresión de ruido?

    python -m soundloc.mic_test --device hw:CARD=Device,DEV=0 --rate 48000

La laptop reproduce un tono de 1 kHz con escalones conocidos (−30, −20 y otra
vez −30 dBFS en el archivo) mientras se graba. Una cadena lineal registra los
mismos escalones de ±10 dB y un nivel plano dentro de cada tono. Un AGC es un
lazo de control: tras un escalón, la ganancia se corrige sola y el nivel se va
regresando a su setpoint, así que el escalón medido sale menor que 10 dB y el
nivel deriva dentro del tono. Una supresión de ruido estacionaria trataría el
tono constante como fondo y lo iría bajando.

Para volver a analizar una grabación sin repetirla:
    python -m soundloc.mic_test --analyze sessions/<carpeta>
"""

import argparse
import json
import subprocess
import sys
import time
import wave
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from .devices import mixer_report  # noqa: E402
from .dsp import bandpass  # noqa: E402
from .levels import clip_fraction, dbfs, short_time_levels, subtract_level, to_float  # noqa: E402
from .recorder import Recorder, RecorderError  # noqa: E402
from .session import PROJECT_ROOT, Session, load_session  # noqa: E402

PLAY_FS = 48000
TONE_HZ = 1000.0
SCHEDULE = (
    ("silencio", 3.0, None),
    ("A", 6.0, -30.0),
    ("B", 6.0, -20.0),
    ("A2", 6.0, -30.0),
    ("silencio_final", 3.0, None),
)
EARLY = (0.5, 1.5)  # segundos desde el inicio de cada tono
LATE = (3.5, 5.5)
TOLERANCE_DB = 0.5
# Como al tono se le resta la potencia del piso, 10 dB sobre el ruido alcanzan para medirlo bien.
MIN_TONE_SNR_DB = 10.0
DIGITAL_SILENCE_DBFS = -90.0  # ningún ADC real da esto en una sala: hay una compuerta o un supresor
# Al abrirse, el códec interno de la laptop da un chasquido que tarda casi 1 s en apagarse.
STARTUP_S = 1.0
ONSET_RISE_DB = 6.0
ONSET_HOLD_S = 0.5  # el tono se sostiene; un ruido breve (alguien que habla) no


def generate_stimulus(fs, schedule=SCHEDULE, tone_hz=TONE_HZ, ramp_s=0.01):
    """Para una senoidal, el nivel en dBFS es 20·log10(pico): amplitud = 10^(L/20)."""
    parts = []
    ramp = int(ramp_s * fs)
    window = 0.5 - 0.5 * np.cos(np.pi * np.arange(ramp) / ramp)  # rampa suave: sin chasquidos
    for _, duration, level in schedule:
        n = int(round(duration * fs))
        if level is None:
            parts.append(np.zeros(n))
            continue
        seg = 10 ** (level / 20) * np.sin(2 * np.pi * tone_hz * np.arange(n) / fs)
        seg[:ramp] *= window
        seg[-ramp:] *= window[::-1]
        parts.append(seg)
    return np.concatenate(parts)


def _window_db(x, fs, ta, tb):
    i0, i1 = max(0, int(ta * fs)), min(len(x), int(tb * fs))
    return dbfs(x[i0:i1]) if i1 - i0 >= 0.2 * fs else float("nan")


def _sustained_onset(levels, threshold, hold, first=0):
    above = levels > threshold
    for i in np.nonzero(above)[0]:
        if i < first:
            continue
        if above[i:i + hold].all() and i + hold <= above.size:
            return i
    return None


def analyze_step_test(x, fs, schedule=SCHEDULE, window_s=0.05, band=(TONE_HZ / 2, TONE_HZ * 2)):
    # Se mide sólo la octava alrededor del tono. Hay micrófonos (el interno de una laptop, por
    # ejemplo) con un desplazamiento de DC y un zumbido de la red en 60/120 Hz mucho más fuertes
    # que el tono; en banda ancha lo tapan, aunque el tono se grabe perfectamente. Un AGC o una
    # compuerta cambian la ganancia de toda la señal, así que se siguen viendo en esta banda.
    if band is not None:
        x = bandpass(x, fs, band)
    t, levels = short_time_levels(x, fs, window_s)
    quiet = (t >= STARTUP_S) & (t < 2.0)
    if not quiet.any():
        raise ValueError("La grabación es demasiado corta")
    # Mediana, no promedio: un chasquido de arranque es un valor atípico y no debe mover el piso.
    floor = float(np.median(levels[quiet]))
    result = {"piso_dbfs": floor, "tiempos": t, "niveles": levels, "inicio_tono_s": None}
    i = _sustained_onset(levels, floor + ONSET_RISE_DB, int(round(ONSET_HOLD_S / window_s)),
                         first=int(np.searchsorted(t, STARTUP_S)))
    if i is None:
        return result

    onset = float(t[i] - window_s / 2)
    lead = 0.0
    for _, duration, level in schedule:
        if level is not None:
            break
        lead += duration
    start = onset - lead
    segments = {}
    for name, duration, level in schedule:
        if level is not None:
            early_raw = _window_db(x, fs, start + EARLY[0], start + EARLY[1])
            late_raw = _window_db(x, fs, start + LATE[0], start + LATE[1])
            # Lo medido es tono + ruido de la sala (incoherentes): se resta el piso en potencia.
            early, late = subtract_level(early_raw, floor), subtract_level(late_raw, floor)
            segments[name] = {"nivel_archivo_dbfs": level, "inicio_s": start,
                              "temprano_bruto_dbfs": early_raw, "tardio_bruto_dbfs": late_raw,
                              "temprano_dbfs": early, "tardio_dbfs": late,
                              "deriva_db": late - early}
        start += duration
    a, b, a2 = (segments[k]["tardio_dbfs"] for k in ("A", "B", "A2"))
    result.update({
        "inicio_tono_s": onset,
        "segmentos": segments,
        "escalon_subida_db": b - a,
        "escalon_bajada_db": a2 - b,
        "repetibilidad_db": a2 - a,
        "snr_tono_db": min(segments[k]["tardio_bruto_dbfs"] for k in ("A", "A2")) - floor,
    })
    return result


def evaluate(result, clip):
    checks = []

    def add(name, ok, detail):
        checks.append({"prueba": name, "ok": bool(ok), "detalle": detail})

    if result.get("inicio_tono_s") is None:
        add("tono_detectado", False, f"no se detectó un tono sostenido {ONSET_RISE_DB:g} dB sobre el "
            f"ruido ({result['piso_dbfs']:.1f} dBFS): sube el volumen o acerca el micrófono")
        return "NO CONCLUYENTE", checks
    add("sin_saturacion", clip == 0.0, f"{100 * clip:.3f} % de muestras en los extremos del ADC")
    if result["piso_dbfs"] <= DIGITAL_SILENCE_DBFS:
        add("sin_compuerta", False, f"el piso es silencio digital ({result['piso_dbfs']:.0f} dBFS): el "
            "micrófono apaga la señal cuando es débil, así que la cadena no es lineal")
        return "NO APTO", checks
    snr = result["snr_tono_db"]
    if snr < MIN_TONE_SNR_DB:
        add("tono_sobre_ruido", False, f"el tono está sólo {snr:.1f} dB sobre el ruido; "
            f"hacen falta {MIN_TONE_SNR_DB:g}")
        return "NO CONCLUYENTE", checks
    add("tono_sobre_ruido", True, f"{snr:.1f} dB sobre el ruido de la habitación")

    seg = result["segmentos"]
    up_expected = seg["B"]["nivel_archivo_dbfs"] - seg["A"]["nivel_archivo_dbfs"]
    up, down = result["escalon_subida_db"], result["escalon_bajada_db"]
    add("escalon_subida", abs(up - up_expected) <= TOLERANCE_DB,
        f"medido {up:+.2f} dB, esperado {up_expected:+.2f} dB")
    add("escalon_bajada", abs(down + up_expected) <= TOLERANCE_DB,
        f"medido {down:+.2f} dB, esperado {-up_expected:+.2f} dB")
    worst = max(seg, key=lambda k: abs(seg[k]["deriva_db"]) if np.isfinite(seg[k]["deriva_db"]) else np.inf)
    add("nivel_estable", abs(seg[worst]["deriva_db"]) <= TOLERANCE_DB,
        f"deriva máxima dentro de un tono: {seg[worst]['deriva_db']:+.2f} dB (tono {worst})")
    add("repetibilidad", abs(result["repetibilidad_db"]) <= TOLERANCE_DB,
        f"A2 − A = {result['repetibilidad_db']:+.2f} dB")
    add("sin_compuerta", result["piso_dbfs"] > DIGITAL_SILENCE_DBFS,
        f"piso de ruido {result['piso_dbfs']:.1f} dBFS (un piso de silencio digital indicaría "
        "una compuerta o supresión de ruido)")
    return ("APTO" if all(c["ok"] for c in checks) else "NO APTO"), checks


HINTS = {
    "sin_saturacion": "Hay saturación: baja el volumen de la laptop o aleja el micrófono.",
    "escalon_subida": "El escalón no mide 10 dB: señal típica de un AGC (o de que la bocina de la laptop distorsiona; prueba con menos volumen).",
    "escalon_bajada": "El escalón no mide 10 dB: señal típica de un AGC.",
    "nivel_estable": "El nivel cambia dentro de un tono constante: un AGC corrigiendo, o una supresión de ruido que va aprendiendo el tono como fondo.",
    "repetibilidad": "El mismo tono no marca lo mismo dos veces: algo en la cadena cambió entre ambos.",
    "sin_compuerta": "El piso es silencio digital: hay una compuerta de ruido o un supresor de ruido. Este micrófono no sirve para medir niveles.",
}


def write_wav(path, x, fs):
    data = np.clip(np.round(x * 32767), -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(fs)
        w.writeframes(data.tobytes())


def plot_step_test(result, path):
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.plot(result["tiempos"], result["niveles"], lw=0.9, color="0.25", label="Nivel (ventanas de 50 ms)")
    ax.axhline(result["piso_dbfs"], color="0.6", ls=":", label="Piso de la habitación")
    for name, seg in result.get("segmentos", {}).items():
        for (a, b), color in ((EARLY, "tab:orange"), (LATE, "tab:blue")):
            ax.axvspan(seg["inicio_s"] + a, seg["inicio_s"] + b, color=color, alpha=0.15)
        ax.hlines(seg["tardio_dbfs"], seg["inicio_s"] + LATE[0], seg["inicio_s"] + LATE[1],
                  color="tab:blue", lw=2)
        ax.text(seg["inicio_s"] + 3.0, seg["tardio_dbfs"] + 2, f"{name}: {seg['tardio_dbfs']:.1f}",
                ha="center", fontsize=9)
    ax.set_xlabel("Tiempo (s)")
    ax.set_ylabel("Nivel (dBFS)")
    ax.set_title("Prueba de linealidad del micrófono (naranja: ventana temprana, azul: tardía)")
    ax.legend(loc="lower right", fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def report(session_dir):
    session_dir = Path(session_dir)
    s = load_session(session_dir)
    result = analyze_step_test(to_float(s.audio), s.fs)
    verdict, checks = evaluate(result, clip_fraction(s.audio[int(STARTUP_S * s.fs):]))
    plot_step_test(result, session_dir / "nivel_microfono.png")
    saved = {k: v for k, v in result.items() if k not in ("tiempos", "niveles")}
    saved.update(veredicto=verdict, pruebas=checks)
    (session_dir / "resultado_microfono.json").write_text(
        json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n=== Prueba del micrófono: {verdict} ===")
    for c in checks:
        print(f"  [{'OK' if c['ok'] else 'FALLA'}] {c['prueba']}: {c['detalle']}")
    for c in checks:
        if not c["ok"] and c["prueba"] in HINTS:
            print(f"  → {HINTS[c['prueba']]}")
    print(f"\nGráfica: {session_dir / 'nivel_microfono.png'}")
    return 0 if verdict == "APTO" else 1


def main(argv=None):
    p = argparse.ArgumentParser(description="Prueba de linealidad y AGC del micrófono")
    p.add_argument("--device", help="dispositivo de captura, p. ej. hw:CARD=Device,DEV=0")
    p.add_argument("--rate", type=int, default=48000)
    p.add_argument("--channels", type=int, default=1)
    p.add_argument("--play-device", help="dispositivo de reproducción para aplay (por omisión, el del sistema)")
    p.add_argument("--out", default=str(PROJECT_ROOT / "sessions"))
    p.add_argument("--analyze", metavar="CARPETA", help="sólo volver a analizar una prueba ya grabada")
    args = p.parse_args(argv)
    if args.analyze:
        return report(args.analyze)
    if not args.device:
        p.error("falta --device (usa `python -m soundloc.devices` para encontrarlo)")

    session = Session(args.out, "prueba_microfono")
    stimulus = session.dir / "estimulo.wav"
    write_wav(stimulus, generate_stimulus(PLAY_FS), PLAY_FS)
    alsa = mixer_report(args.device)
    session.meta.update({
        "microfono": {"dispositivo": args.device, "alsa": alsa},
        "audio": {"fs": args.rate, "canales": args.channels, "formato": "S16_LE"},
        "estimulo": {"tono_hz": TONE_HZ, "fs": PLAY_FS,
                     "tramos": [{"nombre": n, "duracion_s": d, "nivel_dbfs": lv} for n, d, lv in SCHEDULE]},
    })
    for c in alsa["agc"]:
        print(f"¡Ojo! El mezclador del micrófono tiene un control '{c['control']}' "
              f"(encendido: {c['encendido']}).")

    print("\nPreparación:")
    print("  1. Micrófono a unos 30 cm de la bocina de la laptop, quieto y apuntando hacia ella.")
    print("  2. Volumen de la laptop a la mitad. No lo cambies durante la prueba.")
    print("  3. Silencio en la habitación. La prueba dura unos 27 s.")
    input("Presiona ENTER para empezar...")

    recorder = Recorder(session.audio_path, session.timestamps_path, rate=args.rate,
                        channels=args.channels, device=args.device)
    try:
        recorder.start()
        recorder.wait_started()
        time.sleep(1.0)
        play = ["aplay", "-q"] + (["-D", args.play_device] if args.play_device else []) + [str(stimulus)]
        subprocess.run(play, check=True)
        time.sleep(1.5)
    except (RecorderError, subprocess.CalledProcessError) as exc:
        print(f"Error: {exc}")
        return 2
    finally:
        recorder.stop()
        session.meta["audio"]["muestras"] = recorder.frames
        session.write_meta()
    return report(session.dir)


if __name__ == "__main__":
    sys.exit(main())
