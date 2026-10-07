"""Banco volante: el Tello vuela una rutina fija mientras se graba el audio.

Dron real (con la laptop conectada al Wi-Fi del Tello):
    python -m soundloc.bench_flight --device hw:CARD=Device,DEV=0 --rate 48000 --mic-height 1.0

Simulación sin dron, el "SITL" del banco:
    python -m soundloc.bench_flight --simulate

Rutina: ambiente con motores apagados → despegue → ajuste de altura → hover en
cada distancia del plan → aterrizaje → ambiente final. El plan por omisión,
1-2-3-2-1 m, va y regresa: si el nivel a 1 m al principio y al final coincide,
la deriva durante el vuelo (batería, temperatura) es pequeña, y la diferencia
entre ambos es una medida directa de la variabilidad entre hovers repetidos.
"""

import argparse
import sys
import threading
import time

from .analyze_flight import analyze_and_report
from .devices import mixer_report
from .fake_tello import FakeTello
from .recorder import Recorder, RecorderError
from .session import PROJECT_ROOT, Session
from .tello import CMD_PORT, STATE_PORT, TELLO_IP, TelloClient, TelloError

# El Tello aterriza solo si pasa 15 s sin recibir comandos. Mientras vuela, se le
# manda "command" cada 4 s: es un comando del SDK de verdad (no una consulta) y es
# idempotente. Aun así, ningún hover dura tanto como para depender de eso.
MAX_HOVER_S = 13.0
KEEPALIVE_S = 4.0
LANDED_TOF_CM = 15  # con h = 0 y el ToF a menos de esto, el dron está en el piso
MIN_MOVE_CM, MAX_MOVE_CM = 20, 500
STALE_TELEMETRY_S = 2.0
MIN_MEASURE_S = 1.5


class MissionAbort(RuntimeError):
    pass


class Mission:
    def __init__(self, tello, session, args):
        self.tello = tello
        self.session = session
        self.args = args
        self.abort = threading.Event()
        self.abort_reason = None
        self.emergency_fired = threading.Event()
        self.flying = False
        self.taking_off = False  # despegue mandado, todavía sin el 'ok'
        self.finished = False
        self._t_ref = time.monotonic()

    def log(self, message):
        print(f"[{time.monotonic() - self._t_ref:6.1f} s] {message}", flush=True)

    def request_abort(self, reason):
        if not self.abort.is_set():
            self.abort_reason = reason
            self.abort.set()

    def emergency(self):
        self.tello.emergency()
        self.emergency_fired.set()
        self.flying = False
        self.request_abort("paro de emergencia")
        print("\n*** PARO DE EMERGENCIA: motores apagados ***", flush=True)

    def wait(self, seconds):
        """Espera vigilando: aborto, telemetría viva, batería y que el dron siga en el aire."""
        end = time.monotonic() + seconds
        while (remaining := end - time.monotonic()) > 0:
            if self.abort.wait(min(remaining, 0.2)):
                raise MissionAbort(self.abort_reason)
            if not self.flying:
                continue
            state, age = self.tello.state()
            if age > STALE_TELEMETRY_S:
                raise MissionAbort("se dejó de recibir la telemetría del Tello")
            if state.get("bat", 100) < self.args.land_battery:
                raise MissionAbort(f"batería en {state['bat']} %")
            if state.get("h", 1) <= 0 and state.get("tof", 100) <= LANDED_TOF_CM:
                self.flying = False
                raise MissionAbort(f"el Tello aterrizó por su cuenta (temperatura {state.get('temph')} °C, "
                                   f"batería {state.get('bat')} %)")
            if self.tello.seconds_since_last_command() >= KEEPALIVE_S:
                self.tello.command("command", timeout=3)

    def segment(self, label, kind, action, **extra):
        t_start = time.monotonic()
        action()
        self.session.add_segment(label, kind, t_start, time.monotonic(), **extra)

    def current_height_m(self, seconds=1.0):
        readings = []
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            state, age = self.tello.state()
            if age < 0.5 and "tof" in state:
                readings.append(state["tof"])
            self.wait(0.1)
        if not readings:
            raise MissionAbort("no hay lecturas del sensor de distancia (tof)")
        return sum(readings) / len(readings) / 100.0

    def _takeoff(self):
        self.taking_off = True
        self.tello.command("takeoff", timeout=20)
        self.taking_off = False  # sólo si terminó bien: un aborto a medias necesita aterrizar
        self.flying = True

    def _land(self):
        self.tello.command("land", timeout=20)
        self.flying = False

    def run(self):
        a = self.args
        self.log(f"Ambiente con motores apagados ({a.ambient_start:g} s)")
        self.segment("ambiente_inicio", "ambiente", lambda: self.wait(a.ambient_start))
        temp = self.tello.state()[0].get("temph")
        if temp is not None and temp > a.max_takeoff_temp:
            raise MissionAbort(f"el Tello está a {temp} °C, arriba del límite para despegar "
                               f"({a.max_takeoff_temp} °C). Apágalo y déjalo enfriar")
        self.log(f"Despegando (Tello a {temp} °C)")
        self.segment("despegue", "transicion", self._takeoff)
        self.wait(2.0)
        z = self.current_height_m()
        dz = a.mic_height - z
        if abs(dz) >= 0.25:
            cm = min(max(round(abs(dz) * 100), MIN_MOVE_CM), MAX_MOVE_CM)
            cmd = f"{'up' if dz > 0 else 'down'} {cm}"
            self.log(f"Altura {z:.2f} m; ajustando a {a.mic_height:.2f} m ({cmd})")
            try:
                self.segment("ajuste_altura", "transicion", lambda: self.tello.command(cmd))
            except TelloError as exc:
                if self.abort.is_set():
                    raise
                # No es esencial: el análisis calcula la distancia con la altura medida.
                self.log(f"No se pudo ajustar la altura ({exc}); se mide a {z:.2f} m")
        else:
            self.log(f"Altura {z:.2f} m (micrófono a {a.mic_height:.2f} m)")

        current = a.start_distance
        for i, d in enumerate(a.plan, 1):
            delta = round((d - current) * 100)
            if delta:
                cmd = f"{'forward' if delta > 0 else 'back'} {abs(delta)}"
                self.log(f"Moviendo a {d:g} m ({cmd})")
                self.segment(f"mover_a_{d:g}m", "transicion", lambda c=cmd: self.tello.command(c))
                current = d
            self.log(f"Hover {i}/{len(a.plan)} a {d:g} m ({a.hover:g} s)")
            self.segment(f"hover{i}_{d:g}m", "hover", lambda: self.wait(a.hover),
                         distance_m=d, settle_s=a.settle)

        self.log("Aterrizando")
        self.segment("aterrizaje", "transicion", self._land)
        self.wait(1.0)
        self.log(f"Ambiente final ({a.ambient:g} s)")
        self.segment("ambiente_final", "ambiente", lambda: self.wait(a.ambient))


def parse_plan(text):
    return [float(v) for v in text.split(",") if v.strip()]


def validate(args):
    errors = []
    if args.yes and not args.simulate:
        errors.append("--yes sólo se permite con --simulate: un vuelo real siempre pide confirmación")
    if not args.simulate and not args.device:
        errors.append("falta --device (usa `python -m soundloc.devices` para encontrarlo)")
    if args.hover > MAX_HOVER_S:
        errors.append(f"--hover no puede pasar de {MAX_HOVER_S:g} s (aterrizaje automático a los 15 s)")
    if args.settle > args.hover - MIN_MEASURE_S:
        errors.append(f"--settle tiene que dejar al menos {MIN_MEASURE_S:g} s de medición en cada hover")
    current = args.start_distance
    for d in args.plan:
        if not 0 < d <= args.max_distance:
            errors.append(f"la distancia {d:g} m está fuera de (0, {args.max_distance:g}] m")
        delta = round(abs(d - current) * 100)
        if delta and not MIN_MOVE_CM <= delta <= MAX_MOVE_CM:
            errors.append(f"de {current:g} m a {d:g} m son {delta} cm; el Tello sólo acepta "
                          f"movimientos de {MIN_MOVE_CM} a {MAX_MOVE_CM} cm")
        current = d
    return errors



def estimated_duration_s(args):
    moves = sum(1 for prev, d in zip([args.start_distance] + args.plan, args.plan) if prev != d)
    return args.ambient_start + args.ambient + 15 + len(args.plan) * args.hover + 4 * moves


def print_checklist(args, tello_temp_c=None):
    route = " → ".join(f"{d:g}" for d in args.plan)
    print("\n" + "=" * 70)
    print("BANCO VOLANTE" + ("  (SIMULACIÓN)" if args.simulate else ""))
    print(f"  [MIC] altura {args.mic_height:.2f} m  <--- {args.start_distance:g} m --->  [TELLO]"
          " de espaldas al micrófono")
    print(f"  Distancias de hover: {route} m. Duración estimada: {estimated_duration_s(args):.0f} s")
    print("\nLISTA DE VERIFICACIÓN")
    print("  [ ] Protectores de hélice puestos")
    print(f"  [ ] Área libre hasta {max(args.plan) + 0.5:g} m del micrófono en la dirección de vuelo,"
          " y 1 m a los lados")
    print(f"  [ ] Micrófono fijo a {args.mic_height:.2f} m de altura; nadie lo toca durante la prueba")
    print(f"  [ ] Tello en el piso a {args.start_distance:g} m del micrófono, de espaldas a él")
    print("  [ ] Piso con textura y buena luz (el Tello se sostiene viendo el piso)")
    print("  [ ] Nadie en la ruta; silencio en la habitación")
    if tello_temp_c is not None:
        print(f"  Temperatura del Tello: {tello_temp_c} °C. Encendido en el piso se calienta porque no le"
              " pasa aire; si sube demasiado puede apagarse.")
    print("\n  ENTER en cualquier momento = PARO DE EMERGENCIA (motores apagados, el dron cae)")
    print("  Ctrl+C                     = aterrizaje controlado")
    print("=" * 70)


def wait_for_telemetry(tello, timeout=3.0):
    deadline = time.monotonic() + timeout
    while tello.state()[1] > 1.0:
        if time.monotonic() > deadline:
            raise MissionAbort(f"no llega la telemetría del Tello al puerto UDP {tello.state_port}. "
                               "Si tienes firewall activo (sudo ufw status), permite ese puerto")
        time.sleep(0.1)


def start_emergency_listener(mission):
    def listen():
        try:
            sys.stdin.readline()
        except (OSError, ValueError):
            return
        if not mission.finished:
            mission.emergency()

    threading.Thread(target=listen, daemon=True).start()


def _on_ground(tello):
    state, age = tello.state()
    return age < 1.0 and state.get("h", 1) <= 0 and state.get("tof", 100) <= LANDED_TOF_CM


def land_after_abort(tello, mission, during_takeoff=False):
    tello.cancel = None  # el aterrizaje de seguridad no se cancela
    if during_takeoff:
        # El 'ok' del despegue llega cuando de verdad termina. Si se manda 'land' antes, ese 'ok'
        # atrasado parecería la confirmación del aterrizaje con el dron todavía en el aire.
        # Además, mientras arranca la telemetría dice altura 0: no sirve para saber si despegó.
        print("El despegue estaba en curso: espero a que termine para mandar el aterrizaje...", flush=True)
        reply = tello.wait_reply(timeout=15)
        if (reply is None or reply.lower() != "ok") and _on_ground(tello):
            print("El Tello no llegó a despegar" + (f" ({reply})." if reply else "."), flush=True)
            mission.flying = False
            return
    elif _on_ground(tello):
        print("El Tello ya está en el piso (altura 0 según la telemetría).", flush=True)
        mission.flying = False
        return
    print("Aterrizando (esperando la confirmación del Tello, hasta 20 s)...", flush=True)
    try:
        tello.command("land", timeout=20)
        mission.flying = False
    except TelloError as exc:
        print(f"¡No se confirmó el aterrizaje ({exc})! Si sigue en el aire, presiona ENTER para el "
              "paro de emergencia.", flush=True)


def build_parser():
    p = argparse.ArgumentParser(description="Banco volante: rutina del Tello con grabación sincronizada")
    p.add_argument("--device", help="dispositivo ALSA de captura, p. ej. hw:CARD=Device,DEV=0")
    p.add_argument("--rate", type=int, default=48000)
    p.add_argument("--channels", type=int, default=1)
    p.add_argument("--mic-height", type=float, default=1.0, help="altura del micrófono sobre el piso (m)")
    p.add_argument("--mic-model", default="Steren MOV-033")
    p.add_argument("--mic-notes", default="", help="orientación, espuma, soporte...")
    p.add_argument("--start-distance", type=float, default=1.0,
                   help="distancia horizontal inicial entre el Tello y el micrófono (m)")
    p.add_argument("--plan", default="1,2,3,2,1", help="distancias de hover (m), separadas por comas")
    p.add_argument("--max-distance", type=float, default=4.0)
    p.add_argument("--hover", type=float, default=12.0, help="duración de cada hover (s)")
    p.add_argument("--settle", type=float, default=2.0, help="segundos que se descartan al llegar a cada punto")
    p.add_argument("--ambient-start", type=float, default=3.0,
                   help="ambiente antes de despegar (s); corto, porque en el piso el Tello se calienta")
    p.add_argument("--ambient", type=float, default=10.0, help="ambiente después de aterrizar (s)")
    p.add_argument("--max-takeoff-temp", type=int, default=90,
                   help="no despegar si el Tello está más caliente que esto (°C)")
    p.add_argument("--min-battery", type=int, default=50, help="batería mínima para despegar (%%)")
    p.add_argument("--land-battery", type=int, default=20, help="batería a la que se aborta (%%)")
    p.add_argument("--tello-ip", default=TELLO_IP)
    p.add_argument("--cmd-port", type=int, default=CMD_PORT)
    p.add_argument("--state-port", type=int, default=STATE_PORT)
    p.add_argument("--location", default="")
    p.add_argument("--notes", default="")
    p.add_argument("--out", default=str(PROJECT_ROOT / "sessions"))
    p.add_argument("--simulate", action="store_true", help="Tello y audio simulados, sin hardware")
    p.add_argument("--sim-speed", type=float, default=1.0, help="velocidad del Tello simulado (m/s)")
    p.add_argument("--yes", action="store_true", help="no pedir confirmación (sólo en simulación)")
    p.add_argument("--sim-auto-land", type=float, default=None, help=argparse.SUPPRESS)
    p.add_argument("--sim-reject-moves", action="store_true", help=argparse.SUPPRESS)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.plan = parse_plan(args.plan)
    errors = validate(args)
    if errors:
        for e in errors:
            print(f"Error: {e}")
        return 2

    session = Session(args.out, "simulacion" if args.simulate else "banco_volante")
    sim_state = session.dir / "sim_estado.json"
    tello_ip = "127.0.0.1" if args.simulate else args.tello_ip
    session.meta.update({
        "simulado": args.simulate,
        "lugar": args.location,
        "notas": args.notes,
        "microfono": {"modelo": "simulado" if args.simulate else args.mic_model,
                      "dispositivo": args.device or "simulado", "altura_m": args.mic_height,
                      "notas": args.mic_notes},
        "audio": {"fs": args.rate, "canales": args.channels, "formato": "S16_LE"},
        "tello": {"ip": tello_ip},
        "plan": {"distancia_inicial_m": args.start_distance, "distancias_m": args.plan,
                 "hover_s": args.hover, "asentamiento_s": args.settle,
                 "ambiente_inicio_s": args.ambient_start, "ambiente_final_s": args.ambient},
    })

    fake = None
    source_cmd = None
    if args.simulate:
        fake = FakeTello(cmd_port=args.cmd_port, state_port=args.state_port,
                         start_x_m=args.start_distance, speed_mps=args.sim_speed,
                         sim_state_path=sim_state, auto_land_after_s=args.sim_auto_land,
                         reject_moves=args.sim_reject_moves)
        fake.start()
        source_cmd = [sys.executable, "-m", "soundloc.fake_audio", "--rate", str(args.rate),
                      "--state-file", str(sim_state), "--mic-height", str(args.mic_height)]
    else:
        session.meta["microfono"]["alsa"] = mixer_report(args.device)
        for c in session.meta["microfono"]["alsa"]["agc"]:
            print(f"¡Ojo! El micrófono tiene un control '{c['control']}' (encendido: {c['encendido']}).")

    tello = TelloClient(tello_ip, args.cmd_port, args.state_port,
                        local_port=0 if args.simulate else CMD_PORT)
    recorder = Recorder(session.audio_path, session.timestamps_path, rate=args.rate,
                        channels=args.channels, device=args.device, source_cmd=source_cmd,
                        cwd=PROJECT_ROOT)
    mission = Mission(tello, session, args)
    tello.cancel = mission.abort
    outcome = "completo"
    try:
        tello.start()
        tello.connect()
        reply = tello.query("battery?")
        try:
            battery = int(reply)
        except ValueError:
            raise MissionAbort(f"respuesta inesperada a 'battery?': {reply!r}") from None
        session.meta["tello"]["bateria_inicio_pct"] = battery
        if battery < args.min_battery:
            raise MissionAbort(f"batería en {battery} %, se necesita al menos {args.min_battery} %")
        wait_for_telemetry(tello)
        temp = tello.state()[0].get("temph")
        session.meta["tello"]["temperatura_inicio_c"] = temp
        recorder.start()
        recorder.wait_started()  # no se despega si no se está grabando
        print_checklist(args, temp)
        if not args.yes and input("Escribe 'despegar' para iniciar: ").strip().lower() != "despegar":
            raise MissionAbort("cancelado por el operador")
        if sys.stdin.isatty():
            start_emergency_listener(mission)
        mission.run()
    except KeyboardInterrupt:
        outcome = "abortado: Ctrl+C, aterrizaje controlado"
    except (MissionAbort, TelloError, RecorderError) as exc:
        outcome = f"abortado: {exc}"
    finally:
        try:
            if outcome != "completo":
                print(f"\n*** {outcome} ***", flush=True)  # el operador tiene que saber por qué
            if mission.emergency_fired.is_set():
                outcome = "abortado: paro de emergencia"
            elif mission.flying or mission.taking_off:
                land_after_abort(tello, mission, during_takeoff=mission.taking_off)
        except KeyboardInterrupt:
            outcome += "; espera del aterrizaje interrumpida con Ctrl+C"
            print("\nEl Tello ya recibió la orden de aterrizar. Si no la hubiera recibido, aterriza solo "
                  "al pasar 15 s sin comandos. Espera a que esté en el piso antes de acercarte.", flush=True)
        finally:
            # Pase lo que pase, los datos se guardan.
            mission.finished = True
            recorder.stop()
            state, _ = tello.state()
            session.meta["audio"]["muestras"] = recorder.frames
            session.meta["tello"]["bateria_fin_pct"] = state.get("bat")
            session.meta["tello"]["temperatura_fin_c"] = state.get("temph")
            session.meta["resultado"] = outcome
            session.write_segments()
            session.write_telemetry(tello.state_log)
            session.write_meta()
            tello.close()
            if fake is not None:
                fake.stop()

    print(f"\nResultado: {outcome}\nDatos en: {session.dir}")
    if outcome != "completo":
        return 1
    analyze_and_report(session.dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
