"""Simulador del Tello por UDP: el "SITL" del banco volante.

Contesta los mismos comandos de texto que el dron real y manda telemetría con
el mismo formato, así que el cliente se prueba sin cambiar una línea. También
escribe su posición en un JSON para que el audio simulado (fake_audio) sepa a
qué distancia está del micrófono.

Coordenadas: x es la distancia horizontal al micrófono ("forward" aleja al
dron, porque despega de espaldas al micrófono) y z es la altura sobre el piso.
"""

import json
import math
import os
import queue
import random
import socket
import threading
import time
from pathlib import Path

_MOVES = {"up": (0.0, 1.0), "down": (0.0, -1.0), "forward": (1.0, 0.0), "back": (-1.0, 0.0)}
TAKEOFF_HEIGHT_M = 0.8


class FakeTello:
    def __init__(self, cmd_port=8889, state_port=8890, host="127.0.0.1", start_x_m=1.0,
                 speed_mps=1.0, sim_state_path=None, battery=90.0, seed=0, auto_land_after_s=None,
                 reject_moves=False):
        self.host = host
        self.state_port = state_port
        self.x = float(start_x_m)
        self.z = 0.0
        self.motors = False
        self.battery = float(battery)
        self.speed = speed_mps
        self.auto_land_after_s = auto_land_after_s  # imita un aterrizaje automático del dron
        self.reject_moves = reject_moves  # imita "error No valid imu" (posicionamiento no confiable)
        self.sim_state_path = Path(sim_state_path) if sim_state_path else None
        self._sdk = False
        self._stick_vel = (0.0, 0.0)  # (adelante, arriba) en m/s, por las palancas virtuales
        self._flight_start = None
        self._rng = random.Random(seed)
        self._lock = threading.RLock()
        self._file_lock = threading.Lock()  # dos hilos escriben la posición simulada
        self._interrupt = threading.Event()
        self._queue = queue.Queue()
        self._running = False
        self._threads = []
        self._cmd_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._cmd_sock.bind((host, cmd_port))
        self._cmd_sock.settimeout(0.2)
        self._state_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def start(self):
        self._running = True
        self._write_sim_state()
        for target in (self._recv_loop, self._worker_loop, self._state_loop):
            thread = threading.Thread(target=target, daemon=True)
            thread.start()
            self._threads.append(thread)

    def stop(self):
        self._running = False
        self._interrupt.set()
        for thread in self._threads:
            thread.join(timeout=2)
        self._cmd_sock.close()
        self._state_sock.close()

    def _recv_loop(self):
        while self._running:
            try:
                data, addr = self._cmd_sock.recvfrom(1024)
            except socket.timeout:
                continue
            except OSError:
                break
            cmd = data.decode("utf-8", "replace").strip()
            if cmd.startswith("rc "):
                try:
                    _, fb, ud, _ = (int(v) for v in cmd.split()[1:])
                except ValueError:
                    continue
                with self._lock:
                    self._stick_vel = (fb / 100.0, ud / 100.0)  # 100 = 1 m/s
                continue  # el Tello real no contesta "rc"
            if cmd == "emergency":
                # Como en el dron real, la emergencia no espera a que termine otro comando.
                with self._lock:
                    self.motors = False
                    self.z = 0.0
                self._interrupt.set()
                self._write_sim_state()
                self._reply("ok", addr)
            else:
                self._queue.put((cmd, addr))

    def _worker_loop(self):
        while self._running:
            try:
                cmd, addr = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            self._interrupt.clear()
            reply = self._handle(cmd)
            if reply is not None:
                self._reply(reply, addr)

    def _reply(self, text, addr):
        try:
            self._cmd_sock.sendto(text.encode("utf-8"), addr)
        except OSError:
            pass

    def _handle(self, cmd):
        parts = cmd.split()
        if not parts:
            return "error"
        name = parts[0]
        if name == "command":
            self._sdk = True
            return "ok"
        if not self._sdk:
            return "error"
        if name == "battery?":
            return str(int(self.battery))
        if name == "keepalive":
            return "ok"
        if name == "takeoff":
            if self.motors:
                return "error"
            with self._lock:
                self.motors = True
                self._flight_start = time.monotonic()
            return "ok" if self._move(dz=TAKEOFF_HEIGHT_M) else "error"
        if name == "land":
            if not self.motors:
                return "error"
            ok = self._move(dz=-self.z)
            with self._lock:
                self.motors = False
                self.z = 0.0
            self._write_sim_state()
            return "ok" if ok else "error"
        if name in _MOVES and len(parts) == 2:
            try:
                cm = int(parts[1])
            except ValueError:
                return "error"
            if not 20 <= cm <= 500 or not self.motors:
                return "error"
            if self.reject_moves:
                return "error No valid imu"
            ux, uz = _MOVES[name]
            return "ok" if self._move(dx=ux * cm / 100, dz=uz * cm / 100) else "error"
        return "error"

    def _move(self, dx=0.0, dz=0.0):
        """Línea recta a velocidad constante. Devuelve False si la interrumpe una emergencia."""
        distance = math.hypot(dx, dz)
        steps = max(1, int(distance / self.speed / 0.02))
        step_s = distance / self.speed / steps
        x0, z0 = self.x, self.z
        for i in range(1, steps + 1):
            if self._interrupt.wait(step_s):
                return False
            with self._lock:
                if not self.motors:
                    return False
                self.x = x0 + dx * i / steps
                self.z = z0 + dz * i / steps
            self._write_sim_state()
        return True

    def _state_loop(self):
        period = 0.1
        while self._running:
            with self._lock:
                z, motors = self.z, self.motors
                if motors:
                    vx, vz = self._stick_vel
                    if vx or vz:  # sólo mientras alguien mueve las palancas
                        self.x += vx * period
                        self.z = max(0.2, self.z + vz * period)
                        z = self.z
                    self.battery = max(0.0, self.battery - 0.1 * period)
                    if (self.auto_land_after_s is not None and self._flight_start is not None
                            and time.monotonic() - self._flight_start > self.auto_land_after_s):
                        self.motors = False
                        self.z = 0.0
                        motors, z = False, 0.0
                        self._interrupt.set()
                battery = int(self.battery)
                flight_s = int(time.monotonic() - self._flight_start) if motors else 0
            z_obs = z + self._rng.gauss(0.0, 0.01) if motors else z
            tof = int(round(z_obs * 100)) if z_obs > 0.1 else 10
            height = int(round(z_obs * 100)) if motors else 0
            text = (f"pitch:0;roll:0;yaw:0;vgx:0;vgy:0;vgz:0;templ:60;temph:62;tof:{tof};"
                    f"h:{height};bat:{battery};baro:{100 + z_obs:.2f};time:{flight_s};"
                    "agx:0.00;agy:0.00;agz:-1000.00;\r\n")
            try:
                self._state_sock.sendto(text.encode("utf-8"), (self.host, self.state_port))
            except OSError:
                break
            self._write_sim_state()
            time.sleep(period)

    def _write_sim_state(self):
        if self.sim_state_path is None:
            return
        with self._lock:
            data = {"x": self.x, "z": self.z, "motors": self.motors}
        with self._file_lock:
            tmp = self.sim_state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data))
            os.replace(tmp, self.sim_state_path)
