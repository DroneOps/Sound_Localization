"""Cliente del crazybridge (ROS 2) para las misiones del Crazyflie, y su simulador.

El bridge del laboratorio (~/crazyflie-optitrack) es el único nodo que habla por radio
con el dron. Este cliente es otro nodo de ROS que le pide despegar, ir a un punto y
aterrizar por medio de sus servicios, y escucha su odometría: lo mismo que hace el TUI
del laboratorio con el teclado.

rclpy sólo se importa al crear el cliente real, para que la simulación y las pruebas
corran sin ROS.
"""

import json
import math
import threading
import time
from pathlib import Path

TAKEOFF_SRV = "/crazybridge/takeoff"
LAND_SRV = "/crazybridge/land"
GOTO_SRV = "/crazybridge/go_to"
KILL_SRV = "/crazybridge/kill"
ODOM_TOPIC = "/crazybridge/odometry"
BATTERY_TOPIC = "/crazybridge/battery"
SERVICE_TIMEOUT_S = 3.0


class BridgeError(RuntimeError):
    pass


class _Telemetry:
    """Posición y batería más recientes, y el historial con marcas de time.monotonic()."""

    def __init__(self):
        self._lock = threading.Lock()
        self._pos = None
        self._t_pos = None
        self._battery = None
        self._log = []

    def _update_position(self, x, y, z):
        t = time.monotonic()
        with self._lock:
            self._pos = (x, y, z)
            self._t_pos = t
            entry = {"x": x, "y": y, "z": z}
            if self._battery is not None:
                entry["bat"] = self._battery
            self._log.append((t, entry))

    def _update_battery(self, pct):
        with self._lock:
            self._battery = pct

    def position(self):
        """Última posición estimada y cuántos segundos tiene."""
        with self._lock:
            age = math.inf if self._t_pos is None else time.monotonic() - self._t_pos
            return self._pos, age

    def battery(self):
        with self._lock:
            return self._battery

    def state_log(self):
        with self._lock:
            return list(self._log)


def _duration_msg(seconds):
    from builtin_interfaces.msg import Duration
    d = Duration()
    d.sec = int(seconds)
    d.nanosec = int((seconds - int(seconds)) * 1e9)
    return d


class BridgeClient(_Telemetry):
    def __init__(self, node_name="busqueda_acustica"):
        super().__init__()
        try:
            import rclpy
            from crazybridge_interfaces.srv import GoTo, Land, Takeoff
            from nav_msgs.msg import Odometry
            from rclpy.executors import MultiThreadedExecutor
            from std_msgs.msg import Float32
            from std_srvs.srv import SetBool
        except ImportError as exc:
            raise BridgeError(f"no se encontró ROS 2 o el workspace del bridge ({exc}). En esta terminal "
                              "corre antes: source ~/crazyflie-optitrack/source_all.sh") from exc
        self._rclpy = rclpy
        self._types = {"takeoff": Takeoff, "land": Land, "go_to": GoTo, "kill": SetBool}
        rclpy.init()
        self._node = rclpy.create_node(node_name)
        self._clients = {name: self._node.create_client(self._types[name], srv)
                         for name, srv in (("takeoff", TAKEOFF_SRV), ("land", LAND_SRV),
                                           ("go_to", GOTO_SRV), ("kill", KILL_SRV))}
        self._node.create_subscription(Odometry, ODOM_TOPIC, self._on_odom, 10)
        self._node.create_subscription(Float32, BATTERY_TOPIC, self._on_battery, 10)
        # Los callbacks de ROS corren en este hilo; la misión sigue en el principal.
        self._executor = MultiThreadedExecutor()
        self._executor.add_node(self._node)
        self._spin = threading.Thread(target=self._executor.spin, daemon=True)
        self._spin.start()

    def _on_odom(self, msg):
        p = msg.pose.pose.position
        self._update_position(p.x, p.y, p.z)

    def _on_battery(self, msg):
        self._update_battery(float(msg.data))

    def wait_ready(self, timeout=10.0):
        """El bridge publica odometría y ya ofrece el despegue (o sea, ve al OptiTrack)."""
        deadline = time.monotonic() + timeout
        while self.position()[1] > 1.0:
            if time.monotonic() > deadline:
                raise BridgeError(f"no llega odometría en {ODOM_TOPIC}: ¿está corriendo el crazybridge?")
            time.sleep(0.1)
        remaining = max(0.5, deadline - time.monotonic())
        if not self._clients["takeoff"].wait_for_service(timeout_sec=remaining):
            raise BridgeError(f"el bridge no ofrece {TAKEOFF_SRV}: todavía no recibe una posición válida "
                              "del OptiTrack (revisa optitrack_client y Motive)")
        for name, client in self._clients.items():
            if not client.wait_for_service(timeout_sec=1.0):
                raise BridgeError(f"el bridge no ofrece el servicio {name}")

    def _call(self, name, request, timeout=SERVICE_TIMEOUT_S):
        future = self._clients[name].call_async(request)
        deadline = time.monotonic() + timeout
        while not future.done():
            if time.monotonic() > deadline:
                raise BridgeError(f"el bridge no respondió a '{name}' en {timeout:g} s")
            time.sleep(0.01)
        response = future.result()
        if not response.success:
            raise BridgeError(f"el bridge rechazó '{name}': {response.message}")

    def takeoff(self, height, duration):
        req = self._types["takeoff"].Request()
        req.group_mask = 0
        req.height = float(height)
        req.duration = _duration_msg(duration)
        self._call("takeoff", req)

    def go_to(self, x, y, z, duration, yaw_deg=0.0):
        req = self._types["go_to"].Request()
        req.group_mask = 0
        req.relative = False
        req.goal.x, req.goal.y, req.goal.z = float(x), float(y), float(z)
        req.yaw = float(yaw_deg)
        req.duration = _duration_msg(duration)
        self._call("go_to", req)

    def land(self, duration):
        req = self._types["land"].Request()
        req.group_mask = 0
        req.height = 0.0
        req.duration = _duration_msg(duration)
        self._call("land", req)

    def kill(self):
        req = self._types["kill"].Request()
        req.data = True
        self._call("kill", req)

    def close(self):
        # Primero se detiene el hilo de ROS y se espera a que salga: si el proceso termina
        # con ese hilo todavía dentro de spin(), la biblioteca de C++ aborta el programa.
        try:
            self._executor.shutdown(timeout_sec=2.0)
            self._spin.join(timeout=2.0)
            self._node.destroy_node()
        finally:
            self._rclpy.try_shutdown()


class FakeBridge(_Telemetry):
    """Crazyflie simulado con la misma interfaz que BridgeClient.

    Se mueve en línea recta hacia cada destino en el tiempo pedido, como el
    high-level commander, y escribe su estado en un JSON que lee el audio simulado.
    """

    def __init__(self, sim_state_path, start=(0.0, 0.0), rate_hz=50.0, battery_drain_pct_s=0.05):
        super().__init__()
        self._state_path = Path(sim_state_path)
        self._pos = (float(start[0]), float(start[1]), 0.0)
        self._motors = False
        self._move = None  # (desde, hacia, t_inicio, duración, apagar_al_llegar)
        self._bat = 100.0
        self._drain = battery_drain_pct_s
        self._dt = 1.0 / rate_hz
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._update_battery(self._bat)
        self._thread.start()

    def _loop(self):
        while not self._stop.wait(self._dt):
            with self._lock:
                pos, move = self._pos, self._move
                if move is not None:
                    start, end, t_start, duration, stop_motors = move
                    f = min(1.0, (time.monotonic() - t_start) / duration)
                    pos = tuple(a + (b - a) * f for a, b in zip(start, end))
                    if f >= 1.0:
                        self._move = None
                        if stop_motors:
                            self._motors = False
            if self._motors:
                self._bat = max(0.0, self._bat - self._drain * self._dt)
                self._update_battery(round(self._bat))
            self._update_position(*pos)
            tmp = self._state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"x": pos[0], "y": pos[1], "z": pos[2], "motors": self._motors}))
            tmp.replace(self._state_path)

    def wait_ready(self, timeout=10.0):
        deadline = time.monotonic() + timeout
        while self.position()[1] > 1.0:
            if time.monotonic() > deadline:
                raise BridgeError("el simulador no publica posición")
            time.sleep(0.05)

    def _start_move(self, target, duration, stop_motors=False):
        pos, _ = self.position()
        with self._lock:
            self._move = (pos, tuple(target), time.monotonic(), max(duration, 1e-3), stop_motors)

    def takeoff(self, height, duration):
        pos, _ = self.position()
        self._motors = True
        self._start_move((pos[0], pos[1], height), duration)

    def go_to(self, x, y, z, duration, yaw_deg=0.0):
        if not self._motors:
            raise BridgeError("el bridge rechazó 'go_to': el dron está en el piso")
        self._start_move((x, y, z), duration)

    def land(self, duration):
        pos, _ = self.position()
        self._start_move((pos[0], pos[1], 0.0), duration, stop_motors=True)

    def kill(self):
        pos, _ = self.position()
        with self._lock:
            self._move = None
            self._motors = False
            self._pos = (pos[0], pos[1], 0.0)

    def close(self):
        self._stop.set()
        self._thread.join(timeout=1.0)
