"""Banco volante con piloto: el Tello se vuela con el teclado y se graba igual.

    python -m soundloc.manual_flight --device hw:CARD=PCH,DEV=0 --rate 48000 --channels 2 --plan 1,1.8

Sirve cuando el Tello no puede sostener su posición solo (por ejemplo, con "No valid imu"):
un piloto corrige la deriva a mano. Las teclas son las de Mover.py (Learning-Projects/Tello),
con dos cambios: cada tecla es un empujón corto, para corregir con precisión en un espacio
chico, y ENTER es paro de emergencia, como en el banco automático.

Cuando el Tello esté quieto sobre una marca, se presiona el número de esa distancia del plan
para empezar a medir, y otra vez para terminar. Las correcciones durante un hover se cuentan,
porque cada corrección cambia las RPM y mete variabilidad en la medición.
"""

import argparse
import os
import queue
import select
import sys
import termios
import threading
import time
import tty

from .analyze_flight import analyze_and_report
from .bench_flight import (LANDED_TOF_CM, STALE_TELEMETRY_S, MissionAbort, land_after_abort,
                           parse_plan, wait_for_telemetry)
from .devices import mixer_report
from .fake_tello import FakeTello
from .recorder import Recorder, RecorderError
from .session import PROJECT_ROOT, Session
from .tello import CMD_PORT, STATE_PORT, TELLO_IP, TelloClient, TelloError

PULSE_S = 0.25  # duración de cada empujón; mantener la tecla lo repite
TICK_S = 0.1
STARTUP_S = 1.5  # el códec interno de la laptop da un chasquido al abrirse
MIN_AMBIENT_S = 3.0
MIN_HOVER_S = 5.0
KEYS = {"w": (0, 1, 0, 0), "s": (0, -1, 0, 0), "a": (-1, 0, 0, 0), "d": (1, 0, 0, 0),
        "y": (0, 0, 1, 0), "u": (0, 0, -1, 0), "r": (0, 0, 0, -1), "t": (0, 0, 0, 1)}


def split_keys(data):
    """Convierte lo leído de la terminal en teclas.

    Las flechas, las teclas de función y el teclado numérico con Bloq Num apagado mandan
    secuencias que empiezan con ESC: se reportan como "ESPECIAL" para que no se confundan
    con ESC ("aterrizar y salir").
    """
    keys, i = [], 0
    while i < len(data):
        c = data[i]
        if c == "\x1b":
            if i + 1 < len(data) and data[i + 1] in "[O":
                j = i + 2
                while j < len(data) and not (data[j].isalpha() or data[j] == "~"):
                    j += 1
                keys.append("ESPECIAL")
                i = j + 1
                continue
            keys.append("ESC")
        elif c in "\r\n":
            keys.append("ENTER")
        else:
            keys.append(c)
        i += 1
    return keys


class KeyReader:
    """Lee teclas sueltas de la terminal en un hilo aparte.

    ENTER dispara el paro de emergencia desde este mismo hilo: no espera a que el ciclo
    principal termine lo que esté haciendo, por ejemplo un despegue.
    """

    def __init__(self, on_emergency):
        self.on_emergency = on_emergency
        self._queue = queue.Queue()
        self._stop = threading.Event()
        self._fd = None
        self._old = None
        self._thread = None

    def start(self):
        self._fd = sys.stdin.fileno()
        self._old = termios.tcgetattr(self._fd)
        tty.setcbreak(self._fd)
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        while not self._stop.is_set():
            ready, _, _ = select.select([self._fd], [], [], 0.1)
            if not ready:
                continue
            for key in split_keys(os.read(self._fd, 64).decode("utf-8", "ignore")):
                if key == "ENTER":
                    self.on_emergency()
                else:
                    self._queue.put(key)

    def drain(self):
        keys = []
        while True:
            try:
                keys.append(self._queue.get_nowait())
            except queue.Empty:
                return keys

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
        if self._old is not None:
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old)
            self._old = None


class ManualFlight:
    def __init__(self, tello, session, plan, speed=30, max_takeoff_temp=90, land_battery=20,
                 t_start=None, log=None):
        self.tello = tello
        self.session = session
        self.plan = plan
        self.speed = speed
        self.max_takeoff_temp = max_takeoff_temp
        self.land_battery = land_battery
        self.t_start = time.monotonic() if t_start is None else t_start
        self.log = log or (lambda message: print(message, flush=True))
        self.flying = False
        self.taking_off = False  # despegue mandado, todavía sin el 'ok'
        self.done = False
        self.emergency_fired = False
        self.hovers = []
        self._stick = (0, 0, 0, 0)
        self._stick_until = 0.0
        self._hover = None  # [tecla, inicio, correcciones]
        self._landed_at = None

    def handle_key(self, key):
        if key == "ENTER":
            self.emergency()
            return
        if key == "ESC":
            self.finish()
            return
        if key == "ESPECIAL":
            self.log("Tecla especial ignorada (flechas o teclado numérico con Bloq Num apagado). "
                     "Usa las letras y los números de la fila de arriba.")
            return
        k = key.lower()
        if k == "q":
            self.takeoff()
        elif k == "e":
            self.land()
        elif k in KEYS:
            self.nudge(KEYS[k])
        elif k.isdigit() and k != "0":
            self.toggle_hover(int(k))

    def takeoff(self):
        if self.flying:
            return
        waited = time.monotonic() - self.t_start
        if waited < STARTUP_S + MIN_AMBIENT_S:
            self.log(f"Espera {STARTUP_S + MIN_AMBIENT_S - waited:.1f} s: se está midiendo el ambiente.")
            return
        temp = self.tello.state()[0].get("temph")
        if temp is not None and temp > self.max_takeoff_temp:
            self.log(f"El Tello está a {temp} °C (límite {self.max_takeoff_temp} °C). Apágalo y déjalo enfriar.")
            return
        self.session.add_segment("ambiente_inicio", "ambiente", self.t_start + STARTUP_S, time.monotonic())
        self.log(f"Despegando (Tello a {temp} °C)...")
        t = time.monotonic()
        self.taking_off = True
        self.tello.command("takeoff", timeout=20)
        self.taking_off = False  # sólo si terminó bien: un aborto a medias necesita aterrizar
        self.flying = True
        self.session.add_segment("despegue", "transicion", t, time.monotonic())
        self.log("En el aire. Llévalo a una marca y, cuando esté quieto, presiona su número.")

    def land(self):
        if not self.flying:
            return
        self._close_hover("aterrizaje")
        self.log("Aterrizando...")
        t = time.monotonic()
        self.tello.command("land", timeout=20)
        self.flying = False
        self._landed_at = time.monotonic()
        self.session.add_segment("aterrizaje", "transicion", t, self._landed_at)
        self.log("En el piso. Se mide el ambiente; espera unos 5 s y presiona ESC para terminar.")

    def finish(self):
        if self.flying:
            self.land()
        if self._landed_at is not None and time.monotonic() - self._landed_at > 3.0:
            self.session.add_segment("ambiente_final", "ambiente", self._landed_at + 1.0, time.monotonic())
        self.done = True

    def emergency(self):
        self.tello.emergency()
        self.emergency_fired = True
        self.flying = False
        self.done = True
        print("\n*** PARO DE EMERGENCIA: motores apagados ***", flush=True)

    def nudge(self, direction):
        if not self.flying:
            return
        self._stick = tuple(int(v * self.speed) for v in direction)
        self._stick_until = time.monotonic() + PULSE_S
        self.tello.rc(*self._stick)
        if self._hover is not None:
            self._hover[2] += 1

    def toggle_hover(self, n):
        if not self.flying:
            self.log("Primero despega (Q).")
        elif n > len(self.plan):
            self.log(f"El plan sólo tiene {len(self.plan)} distancias (teclas 1 a {len(self.plan)}).")
        elif self._hover is None:
            self._hover = [n, time.monotonic(), 0]
            self.log(f"Hover a {self.plan[n - 1]:g} m: midiendo. Presiona {n} otra vez para terminar.")
        elif self._hover[0] == n:
            self._close_hover("tecla")
        else:
            self.log(f"Hay un hover abierto en la tecla {self._hover[0]}: ciérralo primero.")

    def _close_hover(self, reason):
        if self._hover is None:
            return
        n, t0, corrections = self._hover
        self._hover = None
        d, t1 = self.plan[n - 1], time.monotonic()
        label = f"hover{len(self.hovers) + 1}_{d:g}m"
        self.session.add_segment(label, "hover", t0, t1, distance_m=d, settle_s=0.5)
        self.hovers.append({"etiqueta": label, "distancia_m": d, "duracion_s": round(t1 - t0, 2),
                            "correcciones": corrections, "cierre": reason})
        note = "" if t1 - t0 >= MIN_HOVER_S else f" (corto: conviene al menos {MIN_HOVER_S:g} s)"
        self.log(f"Hover a {d:g} m: {t1 - t0:.1f} s, {corrections} correcciones{note}.")

    def tick(self):
        if not self.flying:
            return
        if time.monotonic() >= self._stick_until:
            self._stick = (0, 0, 0, 0)
        self.tello.rc(*self._stick)
        state, age = self.tello.state()
        if age > STALE_TELEMETRY_S:
            raise MissionAbort("se dejó de recibir la telemetría del Tello")
        if state.get("h", 1) <= 0 and state.get("tof", 100) <= LANDED_TOF_CM:
            self.flying = False
            self._close_hover("aterrizó solo")
            raise MissionAbort(f"el Tello aterrizó por su cuenta (temperatura {state.get('temph')} °C, "
                               f"batería {state.get('bat')} %)")
        if state.get("bat", 100) < self.land_battery:
            raise MissionAbort(f"batería en {state['bat']} %")


def print_instructions(args):
    keys = ", ".join(f"{i} = {d:g} m" for i, d in enumerate(args.plan, 1))
    print("\n" + "=" * 70)
    print("VUELO MANUAL (teclas de Mover.py)")
    print("  Q despegar | E aterrizar | ESC aterrizar y terminar")
    print("  W/S adelante/atrás | A/D izquierda/derecha | Y/U subir/bajar | R/T girar")
    print(f"  Cada tecla es un empujón de {PULSE_S:g} s a velocidad {args.speed}; mantenla para repetir.")
    print(f"  Hovers: {keys}. Presiona el número cuando el Tello ya esté quieto sobre la marca,")
    print(f"  y otra vez para terminar (al menos {MIN_HOVER_S:g} s). Mientras más quieto, mejor la medición.")
    print("\n  ENTER = PARO DE EMERGENCIA (motores apagados)   Ctrl+C = aterrizaje controlado")
    print("=" * 70, flush=True)


def build_parser():
    p = argparse.ArgumentParser(description="Banco volante con piloto, con las teclas de Mover.py")
    p.add_argument("--device", help="dispositivo ALSA de captura, p. ej. hw:CARD=PCH,DEV=0")
    p.add_argument("--rate", type=int, default=48000)
    p.add_argument("--channels", type=int, default=1)
    p.add_argument("--mic-height", type=float, default=1.0)
    p.add_argument("--mic-model", default="microfono interno de la laptop")
    p.add_argument("--mic-notes", default="")
    p.add_argument("--plan", default="1,1.8", help="distancias de las marcas (m); teclas 1, 2, ...")
    p.add_argument("--speed", type=int, default=30, help="velocidad de cada empujón (0 a 100)")
    p.add_argument("--min-battery", type=int, default=50)
    p.add_argument("--land-battery", type=int, default=20)
    p.add_argument("--max-takeoff-temp", type=int, default=90)
    p.add_argument("--tello-ip", default=TELLO_IP)
    p.add_argument("--cmd-port", type=int, default=CMD_PORT)
    p.add_argument("--state-port", type=int, default=STATE_PORT)
    p.add_argument("--location", default="")
    p.add_argument("--notes", default="")
    p.add_argument("--out", default=str(PROJECT_ROOT / "sessions"))
    p.add_argument("--simulate", action="store_true", help="Tello y audio simulados")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.plan = parse_plan(args.plan)
    if not sys.stdin.isatty():
        print("Error: el modo manual necesita una terminal para leer el teclado.")
        return 2
    if not args.simulate and not args.device:
        print("Error: falta --device (usa `python -m soundloc.devices`)")
        return 2
    if not 1 <= len(args.plan) <= 9:
        print("Error: el plan necesita de 1 a 9 distancias (teclas 1 a 9)")
        return 2

    session = Session(args.out, "simulacion_manual" if args.simulate else "vuelo_manual")
    sim_state = session.dir / "sim_estado.json"
    tello_ip = "127.0.0.1" if args.simulate else args.tello_ip
    session.meta.update({
        "simulado": args.simulate, "modo": "manual", "lugar": args.location, "notas": args.notes,
        "microfono": {"modelo": "simulado" if args.simulate else args.mic_model,
                      "dispositivo": args.device or "simulado", "altura_m": args.mic_height,
                      "notas": args.mic_notes},
        "audio": {"fs": args.rate, "canales": args.channels, "formato": "S16_LE"},
        "tello": {"ip": tello_ip},
        "plan": {"distancias_m": args.plan, "velocidad_empujon": args.speed, "empujon_s": PULSE_S},
    })
    fake = None
    source_cmd = None
    if args.simulate:
        fake = FakeTello(cmd_port=args.cmd_port, state_port=args.state_port, start_x_m=args.plan[0],
                         sim_state_path=sim_state)
        fake.start()
        source_cmd = [sys.executable, "-m", "soundloc.fake_audio", "--rate", str(args.rate),
                      "--state-file", str(sim_state), "--mic-height", str(args.mic_height)]
    else:
        session.meta["microfono"]["alsa"] = mixer_report(args.device)

    tello = TelloClient(tello_ip, args.cmd_port, args.state_port,
                        local_port=0 if args.simulate else CMD_PORT)
    recorder = Recorder(session.audio_path, session.timestamps_path, rate=args.rate,
                        channels=args.channels, device=args.device, source_cmd=source_cmd,
                        cwd=PROJECT_ROOT)
    flight = None
    reader = None
    outcome = "completo"
    try:
        tello.start()
        tello.connect()
        battery = int(tello.query("battery?"))
        session.meta["tello"]["bateria_inicio_pct"] = battery
        if battery < args.min_battery:
            raise MissionAbort(f"batería en {battery} %, se necesita al menos {args.min_battery} %")
        wait_for_telemetry(tello)
        session.meta["tello"]["temperatura_inicio_c"] = tello.state()[0].get("temph")
        recorder.start()
        recorder.wait_started()
        flight = ManualFlight(tello, session, args.plan, speed=args.speed,
                              max_takeoff_temp=args.max_takeoff_temp, land_battery=args.land_battery)
        print_instructions(args)
        print(f"Tello a {session.meta['tello']['temperatura_inicio_c']} °C, batería {battery} %. "
              "Midiendo el ambiente; presiona Q para despegar.", flush=True)
        reader = KeyReader(on_emergency=flight.emergency)
        reader.start()
        while not flight.done:
            t_loop = time.monotonic()
            for key in reader.drain():
                flight.handle_key(key)
                if flight.done:
                    break
            flight.tick()
            time.sleep(max(0.0, TICK_S - (time.monotonic() - t_loop)))
    except KeyboardInterrupt:
        outcome = "abortado: Ctrl+C, aterrizaje controlado"
    except (MissionAbort, TelloError, RecorderError, ValueError) as exc:
        outcome = f"abortado: {exc}"
    finally:
        if reader is not None:
            reader.stop()  # la terminal vuelve a la normalidad antes de seguir imprimiendo
        try:
            if outcome != "completo":
                print(f"\n*** {outcome} ***", flush=True)
            if flight is not None and flight.emergency_fired:
                outcome = "abortado: paro de emergencia"
            elif flight is not None and (flight.flying or flight.taking_off):
                flight._close_hover("aborto")
                land_after_abort(tello, flight, during_takeoff=flight.taking_off)
        except KeyboardInterrupt:
            outcome += "; espera del aterrizaje interrumpida con Ctrl+C"
            print("\nEl Tello ya recibió la orden de aterrizar. Si no la hubiera recibido, aterriza solo "
                  "al pasar 15 s sin comandos.", flush=True)
        finally:
            recorder.stop()
            state, _ = tello.state()
            session.meta["audio"]["muestras"] = recorder.frames
            session.meta["tello"]["bateria_fin_pct"] = state.get("bat")
            session.meta["tello"]["temperatura_fin_c"] = state.get("temph")
            session.meta["hovers"] = flight.hovers if flight is not None else []
            session.meta["resultado"] = outcome
            session.write_segments()
            session.write_telemetry(tello.state_log)
            session.write_meta()
            tello.close()
            if fake is not None:
                fake.stop()

    print(f"\nResultado: {outcome}\nDatos en: {session.dir}")
    if any(seg["tipo"] == "hover" for seg in session.segments):
        analyze_and_report(session.dir)
    return 0 if outcome == "completo" else 1


if __name__ == "__main__":
    sys.exit(main())
