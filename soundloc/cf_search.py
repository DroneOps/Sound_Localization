"""Búsqueda acústica con el Crazyflie: aterriza en el punto donde el micrófono lo oye más fuerte.

Simulación, sin ROS ni hardware:
    python -m soundloc.cf_search --simulate

Con el dron. En la terminal donde se corre, primero `source ~/crazyflie-optitrack/source_all.sh`;
el crazybridge y el optitrack_client tienen que estar corriendo en otras terminales:
    python -m soundloc.cf_search --device hw:CARD=PCH,DEV=0 --near 1.5,0 --far=-1.0,0 --mic 2.6,0,0.75

Las coordenadas negativas van con '=' (--far=-1.0,0); si no, argparse las confunde con opciones.

Rutina: ambiente con el dron en el piso → despegue → visitas A B C C B A con un hover en
cada una, midiendo la energía en banda → decisión → vuelo al ganador → aterrizaje →
ambiente final. El dron aterriza siempre en un punto candidato, nunca junto al micrófono.
"""

import argparse
import math
import sys
import threading
import time

import numpy as np

from .acoustic_search import (analyze, candidate_points, decide_from_audio, hover_label,
                              print_report, visit_order)
from .crazyflie import BridgeError, FakeBridge
from .devices import mixer_report
from .dsp import VOICE_BAND_HZ
from .recorder import Recorder, RecorderError
from .session import PROJECT_ROOT, Session
from .timing import estimate_t0

STALE_ODOMETRY_S = 1.0
LANDED_Z_M = 0.08


class MissionAbort(RuntimeError):
    pass


class AudioTap:
    """Copia en memoria de lo que se graba, para decidir sin esperar a que se cierre el WAV."""

    def __init__(self):
        self._buf = bytearray()
        self._lock = threading.Lock()

    def __call__(self, data):
        with self._lock:
            self._buf.extend(data)

    def samples(self, channels):
        with self._lock:
            raw = bytes(self._buf)
        frame = 2 * channels
        x = np.frombuffer(raw[: len(raw) // frame * frame], dtype="<i2")
        return x.reshape(-1, channels)[:, 0]


def telemetry_arrays(state_log):
    if not state_log:
        return {}
    return {"t": np.array([t for t, _ in state_log]),
            **{k: np.array([s.get(k, math.nan) for _, s in state_log]) for k in ("x", "y", "z")}}


class Mission:
    def __init__(self, cf, session, args, recorder, tap):
        self.cf = cf
        self.session = session
        self.args = args
        self.recorder = recorder
        self.tap = tap
        self.order = visit_order(len(args.points), args.rounds)
        self.abort = threading.Event()
        self.abort_reason = None
        self.emergency_fired = threading.Event()
        self.flying = False
        self.finished = False
        self.target = None  # punto (x, y, z) que el dron debe sostener; None mientras se mueve
        self.result = None
        self._t_ref = time.monotonic()

    def log(self, message):
        print(f"[{time.monotonic() - self._t_ref:6.1f} s] {message}", flush=True)

    def request_abort(self, reason):
        if not self.abort.is_set():
            self.abort_reason = reason
            self.abort.set()

    def emergency(self):
        try:
            self.cf.kill()
        except BridgeError as exc:
            print(f"\n¡El kill falló ({exc})! Usa la tecla k del TUI del laboratorio.", flush=True)
        self.emergency_fired.set()
        self.flying = False
        self.request_abort("paro de emergencia")
        print("\n*** PARO DE EMERGENCIA: motores apagados ***", flush=True)

    def wait(self, seconds):
        """Espera vigilando: aborto, odometría viva, batería y que el dron sostenga su punto."""
        a = self.args
        end = time.monotonic() + seconds
        while (remaining := end - time.monotonic()) > 0:
            if self.abort.wait(min(remaining, 0.1)):
                raise MissionAbort(self.abort_reason)
            if not self.flying:
                continue
            pos, age = self.cf.position()
            if age > STALE_ODOMETRY_S:
                raise MissionAbort(f"no llega odometría del bridge desde hace {age:.1f} s")
            battery = self.cf.battery()
            if a.land_battery > 0 and battery is not None and battery < a.land_battery:
                raise MissionAbort(f"batería en {battery:.0f} %")
            if self.target is not None and math.dist(pos, self.target) > a.max_deviation:
                raise MissionAbort(f"el dron se alejó {math.dist(pos, self.target):.2f} m del punto "
                                   f"(límite {a.max_deviation:g} m)")

    def wait_until_near(self, target, tolerance, timeout, what):
        deadline = time.monotonic() + timeout
        while math.dist(self.cf.position()[0], target) > tolerance:
            if time.monotonic() > deadline:
                pos = self.cf.position()[0]
                raise MissionAbort(f"no llegó a {what}: está a {math.dist(pos, target):.2f} m "
                                   f"({pos[0]:.2f}, {pos[1]:.2f}, {pos[2]:.2f})")
            self.wait(0.1)

    def segment(self, label, kind, action, **extra):
        t_start = time.monotonic()
        action()
        self.session.add_segment(label, kind, t_start, time.monotonic(), **extra)

    def fly_to(self, x, y, z, what):
        a = self.args
        pos, _ = self.cf.position()
        if math.dist(pos, (x, y, z)) <= a.arrive_tolerance:
            self.target = (x, y, z)  # ya está ahí (la segunda ronda empieza donde acabó la primera)
            return
        duration = max(a.min_move_s, math.dist(pos, (x, y, z)) / a.speed)
        self.target = None
        self.cf.go_to(x, y, z, duration)
        self.wait(duration)
        self.wait_until_near((x, y, z), a.arrive_tolerance, a.arrive_timeout, what)
        self.target = (x, y, z)

    def _takeoff(self):
        a = self.args
        x, y, _ = self.cf.position()[0]
        self.cf.takeoff(a.height, a.takeoff_s)
        self.flying = True
        self.wait(a.takeoff_s)
        self.wait_until_near((x, y, a.height), a.arrive_tolerance, a.arrive_timeout, "la altura de vuelo")

    def _land(self):
        self.target = None
        self.cf.land(self.args.land_s)
        self.wait(self.args.land_s)
        deadline = time.monotonic() + 4.0
        while self.cf.position()[0][2] > LANDED_Z_M and time.monotonic() < deadline:
            self.wait(0.1)
        self.flying = False

    def mic_distance(self, i):
        if self.args.mic is None:
            return None
        x, y = self.args.points[i]
        return math.dist((x, y, self.args.height), self.args.mic)

    def decide(self):
        chunks = list(self.recorder.chunks)
        if not chunks:
            raise MissionAbort("no hay audio grabado para decidir")
        frames, times = zip(*chunks)
        t0 = estimate_t0(frames, times, self.args.rate)
        return decide_from_audio(self.tap.samples(self.args.channels), self.args.rate, t0,
                                 self.session.segments, len(self.args.points), self.args.band,
                                 telemetry_arrays(self.cf.state_log()))

    def run(self):
        a = self.args
        n = len(a.points)
        self.log(f"Ambiente con el dron en el piso ({a.ambient_start:g} s)")
        self.segment("ambiente_inicio", "ambiente", lambda: self.wait(a.ambient_start))

        self.log(f"Despegando a {a.height:g} m")
        self.segment("despegue", "transicion", self._takeoff)

        for k, i in enumerate(self.order):
            visit = k // n + 1
            x, y = a.points[i]
            self.log(f"Moviendo a P{i + 1} ({x:.2f}, {y:.2f})")
            self.segment(f"mover_a_P{i + 1}", "transicion", lambda: self.fly_to(x, y, a.height, f"P{i + 1}"))
            self.log(f"Hover {k + 1}/{len(self.order)} en P{i + 1}, visita {visit} ({a.hover:g} s)")
            self.segment(hover_label(i, visit), "hover", lambda: self.wait(a.hover),
                         distance_m=self.mic_distance(i), settle_s=a.settle)

        self.result = self.decide()
        winner = self.result["ganador"]
        if winner is None:
            raise MissionAbort(f"no se pudo decidir: {self.result.get('nota')}")
        levels = ", ".join(f"P{e['punto'] + 1} {e['nivel_dbfs']:.1f}" for e in self.result["puntos"])
        self.log(f"Decisión: P{winner + 1} (dBFS en banda: {levels}; margen {self.result['margen_db']:.1f} dB, "
                 f"{'confiable' if self.result['confiable'] else 'NO confiable'})")
        self.session.meta["decision"] = {k: self.result[k] for k in
                                         ("ganador", "ranking", "margen_db", "dispersion_max_db",
                                          "rondas_ganadas", "rondas", "dron_audible", "confiable")}

        x, y = a.points[winner]
        self.log(f"Volando al ganador, P{winner + 1}")
        self.segment("mover_a_ganador", "transicion", lambda: self.fly_to(x, y, a.height, "el ganador"))
        self.log("Aterrizando")
        self.segment("aterrizaje", "transicion", self._land)
        self.wait(1.0)
        self.log(f"Ambiente final ({a.ambient:g} s)")
        self.segment("ambiente_final", "ambiente", lambda: self.wait(a.ambient))


def land_after_abort(cf, mission):
    pos, age = cf.position()
    if pos is not None and age < STALE_ODOMETRY_S and pos[2] <= LANDED_Z_M:
        print("El dron ya está en el piso.", flush=True)
        mission.flying = False
        return
    print("Aterrizando...", flush=True)
    try:
        cf.land(mission.args.land_s)
    except BridgeError as exc:
        print(f"¡No se pudo mandar el aterrizaje ({exc})! Si sigue en el aire, presiona ENTER para el "
              "paro de emergencia, o la tecla l (aterrizar) o k (kill) en el TUI.", flush=True)
        return
    deadline = time.monotonic() + mission.args.land_s + 5.0
    while time.monotonic() < deadline:
        pos, age = cf.position()
        if pos is not None and age < STALE_ODOMETRY_S and pos[2] <= LANDED_Z_M:
            mission.flying = False
            print("En el piso.", flush=True)
            return
        time.sleep(0.1)
    print("No se confirmó el aterrizaje con la odometría: revisa el dron antes de acercarte.", flush=True)


def start_emergency_listener(mission):
    def listen():
        try:
            sys.stdin.readline()
        except (OSError, ValueError):
            return
        if not mission.finished:
            mission.emergency()

    threading.Thread(target=listen, daemon=True).start()


def parse_xy(text):
    values = [float(v) for v in text.split(",")]
    if len(values) != 2:
        raise argparse.ArgumentTypeError(f"se esperaba x,y y llegó {text!r}")
    return tuple(values)


def parse_xyz(text):
    values = [float(v) for v in text.split(",")]
    if len(values) != 3:
        raise argparse.ArgumentTypeError(f"se esperaba x,y,z y llegó {text!r}")
    return tuple(values)


def parse_band(text):
    values = [float(v) for v in text.split(",")]
    if len(values) != 2:
        raise argparse.ArgumentTypeError(f"se esperaba fmin,fmax y llegó {text!r}")
    return tuple(values)


def validate(args):
    errors = []
    if args.yes and not args.simulate:
        errors.append("--yes sólo se permite con --simulate: un vuelo real siempre pide confirmación")
    if not args.simulate:
        if not args.device:
            errors.append("falta --device (usa `python -m soundloc.devices` para encontrarlo)")
        if args.near is None or args.far is None:
            errors.append("faltan --near y --far: los extremos de la línea de puntos, en el marco del OptiTrack")
    if not 0.3 <= args.height <= 1.5:
        errors.append(f"--height {args.height:g} m fuera de [0.3, 1.5] m")
    if args.n_points < 2:
        errors.append("--n-points tiene que ser al menos 2")
    if args.rounds < 1:
        errors.append("--rounds tiene que ser al menos 1")
    if args.settle > args.hover - 1.0:
        errors.append("--settle tiene que dejar al menos 1 s de medición en cada hover")
    if args.near is not None and args.far is not None and args.n_points >= 2:
        points = candidate_points(args.near, args.far, args.n_points)
        for i, (x, y) in enumerate(points):
            if max(abs(x), abs(y)) > args.max_coord:
                errors.append(f"P{i + 1} ({x:.2f}, {y:.2f}) sale de ±{args.max_coord:g} m; el bridge "
                              "aterriza solo si el dron pasa de 3 m del origen")
        spacing = math.dist(points[0], points[1])
        if spacing < 0.3:
            errors.append(f"los puntos quedan a {spacing:.2f} m entre sí; se necesitan al menos 0.3 m")
    if args.mic is not None and args.near is not None and args.far is not None and args.n_points >= 2:
        for i, (x, y) in enumerate(candidate_points(args.near, args.far, args.n_points)):
            if math.dist((x, y), args.mic[:2]) < args.min_mic_distance:
                errors.append(f"P{i + 1} queda a {math.dist((x, y), args.mic[:2]):.2f} m del micrófono; "
                              f"el mínimo es {args.min_mic_distance:g} m")
    return errors


def estimated_duration_s(args):
    path = [args.points[i] for i in visit_order(len(args.points), args.rounds)]
    moves = sum(max(args.min_move_s, math.dist(p, q) / args.speed) + 1.0 for p, q in zip(path, path[1:]))
    hovers = len(path) * args.hover
    return args.ambient_start + args.ambient + args.takeoff_s + args.land_s + moves + hovers + 8


def print_checklist(args):
    print("\n" + "=" * 70)
    print("BÚSQUEDA ACÚSTICA CON EL CRAZYFLIE" + ("  (SIMULACIÓN)" if args.simulate else ""))
    for i, (x, y) in enumerate(args.points):
        extra = f", a {math.dist((x, y, args.height), args.mic):.2f} m del micrófono" if args.mic else ""
        print(f"  P{i + 1}: ({x:.2f}, {y:.2f}) m{extra}")
    order = " ".join(f"P{i + 1}" for i in visit_order(len(args.points), args.rounds))
    print(f"  Altura {args.height:g} m; visitas: {order}; hover de {args.hover:g} s")
    print(f"  Banda {args.band[0]:g}–{args.band[1]:g} Hz. Duración estimada: {estimated_duration_s(args):.0f} s")
    print("\nLISTA DE VERIFICACIÓN")
    print("  [ ] Laptop fuera de la red, quieta; nadie la toca ni habla cerca durante la prueba")
    print("  [ ] Nadie dentro de la red")
    print("  [ ] En Motive sólo está el Crazyflie; el bridge no muestra 'Bad mocap'")
    print("  [ ] Batería cargada; ventiladores del cuarto apagados")
    print("  [ ] La terminal del TUI a la mano: su tecla k es el kill de respaldo")
    print("\n  ENTER en cualquier momento = PARO DE EMERGENCIA (motores apagados, el dron cae)")
    print("  Ctrl+C                     = aterrizaje controlado donde esté")
    print("=" * 70)


def build_parser():
    p = argparse.ArgumentParser(description="Búsqueda acústica: aterrizar donde el micrófono oye más fuerte al Crazyflie")
    p.add_argument("--device", help="dispositivo ALSA de captura, p. ej. hw:CARD=PCH,DEV=0")
    p.add_argument("--rate", type=int, default=48000)
    p.add_argument("--channels", type=int, default=1)
    p.add_argument("--mic-model", default="micrófono interno de la laptop")
    p.add_argument("--mic-notes", default="")
    p.add_argument("--mic", type=parse_xyz, default=None,
                   help="posición del micrófono x,y,z en el marco del OptiTrack (m); sólo para el reporte")
    p.add_argument("--near", type=parse_xy, default=None, help="punto x,y más cercano al micrófono")
    p.add_argument("--far", type=parse_xy, default=None, help="punto x,y más lejano al micrófono (negativos con =: --far=-1,0)")
    p.add_argument("--n-points", type=int, default=3)
    p.add_argument("--rounds", type=int, default=2, help="vueltas por los puntos (2 = A B C C B A)")
    p.add_argument("--height", type=float, default=0.8, help="altura de vuelo (m)")
    p.add_argument("--hover", type=float, default=5.0, help="duración de cada hover (s)")
    p.add_argument("--settle", type=float, default=1.5, help="segundos que se descartan al llegar a cada punto")
    p.add_argument("--band", type=parse_band, default=VOICE_BAND_HZ, help="banda fmin,fmax en Hz")
    p.add_argument("--speed", type=float, default=0.4, help="velocidad de traslado (m/s)")
    p.add_argument("--min-move-s", type=float, default=2.0)
    p.add_argument("--takeoff-s", type=float, default=2.5)
    p.add_argument("--land-s", type=float, default=3.0)
    p.add_argument("--arrive-tolerance", type=float, default=0.15, help="qué tan cerca cuenta como llegar (m)")
    p.add_argument("--arrive-timeout", type=float, default=4.0)
    p.add_argument("--max-deviation", type=float, default=0.4, help="se aborta si en hover se aleja más (m)")
    p.add_argument("--max-coord", type=float, default=2.5, help="límite de |x| y |y| de los puntos (m)")
    p.add_argument("--min-mic-distance", type=float, default=0.8)
    p.add_argument("--ambient-start", type=float, default=4.0)
    p.add_argument("--ambient", type=float, default=4.0)
    p.add_argument("--min-battery", type=float, default=50.0,
                   help="batería mínima para despegar (%%), leída con los motores apagados")
    # El porcentaje del firmware sale del voltaje instantáneo. Con los motores encendidos la
    # LiPo cae de golpe y el Crazyflie reporta 0-10 %% en pleno vuelo con la batería sana, así
    # que en vuelo ese número no sirve para decidir. Por omisión no se usa.
    p.add_argument("--land-battery", type=float, default=0.0,
                   help="abortar si la batería en vuelo baja de esto (%%); 0 = no revisar")
    p.add_argument("--location", default="")
    p.add_argument("--notes", default="")
    p.add_argument("--out", default=str(PROJECT_ROOT / "sessions"))
    p.add_argument("--simulate", action="store_true", help="dron y audio simulados, sin ROS ni hardware")
    p.add_argument("--sim-start", type=parse_xy, default=(0.0, 0.0), help="dónde despega el dron simulado")
    p.add_argument("--yes", action="store_true", help="no pedir confirmación (sólo en simulación)")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.simulate:
        args.near = args.near or (1.0, 0.0)
        args.far = args.far or (-1.0, 0.0)
        args.mic = args.mic or (2.2, 0.0, 0.75)
    errors = validate(args)
    if errors:
        for e in errors:
            print(f"Error: {e}")
        return 2
    args.points = candidate_points(args.near, args.far, args.n_points)

    session = Session(args.out, "simulacion_busqueda_cf" if args.simulate else "busqueda_cf")
    session.meta.update({
        "simulado": args.simulate,
        "lugar": args.location,
        "notas": args.notes,
        "microfono": {"modelo": "simulado" if args.simulate else args.mic_model,
                      "dispositivo": args.device or "simulado", "notas": args.mic_notes},
        "audio": {"fs": args.rate, "canales": args.channels, "formato": "S16_LE"},
        "plan": {"puntos_m": args.points, "orden": visit_order(len(args.points), args.rounds),
                 "rondas": args.rounds, "altura_m": args.height, "hover_s": args.hover,
                 "asentamiento_s": args.settle, "banda_hz": list(args.band), "microfono_m": args.mic,
                 "velocidad_mps": args.speed, "ambiente_inicio_s": args.ambient_start,
                 "ambiente_final_s": args.ambient},
    })

    source_cmd = None
    if args.simulate:
        cf = FakeBridge(session.dir / "sim_estado.json", start=args.sim_start)
        mx, my, mz = args.mic
        source_cmd = [sys.executable, "-m", "soundloc.fake_audio", "--rate", str(args.rate),
                      "--state-file", str(session.dir / "sim_estado.json"), "--mic-height", str(mz),
                      "--mic-x", str(mx), "--mic-y", str(my)]
    else:
        session.meta["microfono"]["alsa"] = mixer_report(args.device)
        for c in session.meta["microfono"]["alsa"]["agc"]:
            print(f"¡Ojo! El micrófono tiene un control '{c['control']}' (encendido: {c['encendido']}). "
                  "Un control automático de ganancia aplana justo las diferencias que se quieren medir.")
        try:
            from .crazyflie import BridgeClient
            cf = BridgeClient()
        except BridgeError as exc:
            print(f"Error: {exc}")
            return 2

    tap = AudioTap()
    recorder = Recorder(session.audio_path, session.timestamps_path, rate=args.rate,
                        channels=args.channels, device=args.device, source_cmd=source_cmd,
                        cwd=PROJECT_ROOT, on_chunk=tap)
    mission = Mission(cf, session, args, recorder, tap)
    outcome = "completo"
    try:
        cf.wait_ready()
        pos, _ = cf.position()
        session.meta["posicion_inicial_m"] = list(pos)
        battery = cf.battery()
        session.meta["bateria_inicio_pct"] = battery
        if battery is None:
            print("¡Ojo! El bridge todavía no reporta batería.")
        elif battery < args.min_battery:
            raise MissionAbort(f"batería en {battery:.0f} %, se necesita al menos {args.min_battery:g} %")
        if pos[2] > 0.15:
            raise MissionAbort(f"el dron no está en el piso (z = {pos[2]:.2f} m)")
        recorder.start()
        recorder.wait_started()  # no se despega si no se está grabando
        print_checklist(args)
        if not args.yes and input("Escribe 'despegar' para iniciar: ").strip().lower() != "despegar":
            raise MissionAbort("cancelado por el operador")
        if sys.stdin.isatty():
            start_emergency_listener(mission)
        mission.run()
    except KeyboardInterrupt:
        outcome = "abortado: Ctrl+C, aterrizaje controlado"
    except (MissionAbort, BridgeError, RecorderError) as exc:
        outcome = f"abortado: {exc}"
    finally:
        try:
            if outcome != "completo":
                print(f"\n*** {outcome} ***", flush=True)
            if mission.emergency_fired.is_set():
                outcome = "abortado: paro de emergencia"
            elif mission.flying:
                land_after_abort(cf, mission)
        except KeyboardInterrupt:
            outcome += "; espera del aterrizaje interrumpida con Ctrl+C"
            print("\nEl bridge ya recibió la orden de aterrizar. Espera a que el dron esté en el piso "
                  "antes de entrar a la red.", flush=True)
        finally:
            # Pase lo que pase, los datos se guardan.
            mission.finished = True
            recorder.stop()
            session.meta["audio"]["muestras"] = recorder.frames
            session.meta["bateria_fin_pct"] = cf.battery()
            session.meta["resultado"] = outcome
            session.write_segments()
            session.write_telemetry(cf.state_log())
            session.write_meta()
            cf.close()

    print(f"\nResultado: {outcome}\nDatos en: {session.dir}")
    if outcome != "completo":
        print(f"Para analizar lo que alcanzó a medir: python -m soundloc.acoustic_search {session.dir}")
        return 1
    print_report(analyze(session.dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
