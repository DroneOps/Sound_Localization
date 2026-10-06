"""Cliente mínimo del SDK del Tello por UDP.

El Tello crea su propia red Wi-Fi. Los comandos son texto ("takeoff",
"forward 100") que se mandan a 192.168.10.1:8889, y el dron contesta "ok" o
"error" cuando termina. Aparte, el dron manda su telemetría unas 10 veces por
segundo al puerto 8890 de la computadora.

Este cliente no reintenta comandos a propósito: si un "forward 100" llegó pero
se perdió la respuesta, repetirlo movería el dron otros 100 cm. Un comando que
da lo mismo ejecutar una o varias veces se llama idempotente; "emergency" lo
es, "forward 100" no.
"""

import socket
import threading
import time

TELLO_IP = "192.168.10.1"
CMD_PORT = 8889
STATE_PORT = 8890

_INT_FIELDS = {"mid", "x", "y", "z", "pitch", "roll", "yaw", "vgx", "vgy", "vgz",
               "templ", "temph", "tof", "h", "bat", "time"}
_FLOAT_FIELDS = {"baro", "agx", "agy", "agz"}


def parse_state(text):
    """Convierte 'pitch:0;roll:0;...;tof:98;...' en un diccionario."""
    state = {}
    for field in text.strip().split(";"):
        if ":" not in field:
            continue
        key, value = field.split(":", 1)
        try:
            if key in _INT_FIELDS:
                state[key] = int(value)
            elif key in _FLOAT_FIELDS:
                state[key] = float(value)
            else:
                state[key] = value
        except ValueError:
            state[key] = value
    return state


class TelloError(RuntimeError):
    pass


class TelloClient:
    MIN_INTERVAL_S = 0.1

    def __init__(self, ip=TELLO_IP, cmd_port=CMD_PORT, state_port=STATE_PORT):
        self.addr = (ip, cmd_port)
        self.state_port = state_port
        # Si se activa, cualquier espera de respuesta se interrumpe (lo usa la misión al abortar).
        self.cancel = None
        self.state_log = []  # (hora de llegada, estado)
        self._cmd = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._cmd.bind(("", 0))
        self._state_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._state_sock.bind(("", state_port))
        self._state_sock.settimeout(0.5)
        self._lock = threading.Lock()
        self._last_send = 0.0
        self._state = {}
        self._state_t = None
        self._running = False
        self._thread = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._state_loop, daemon=True)
        self._thread.start()

    def _state_loop(self):
        while self._running:
            try:
                data, _ = self._state_sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            arrival = time.monotonic()
            state = parse_state(data.decode("utf-8", "replace"))
            if state:
                self._state, self._state_t = state, arrival
                self.state_log.append((arrival, state))

    def state(self):
        """Último estado recibido y cuántos segundos tiene de antigüedad."""
        if self._state_t is None:
            return {}, float("inf")
        return dict(self._state), time.monotonic() - self._state_t

    def _drain(self):
        """Descarta respuestas atrasadas para no confundirlas con la del siguiente comando."""
        self._cmd.setblocking(False)
        try:
            while True:
                self._cmd.recvfrom(1024)
        except OSError:
            pass

    def _exchange(self, cmd, timeout):
        with self._lock:
            wait = self.MIN_INTERVAL_S - (time.monotonic() - self._last_send)
            if wait > 0:
                time.sleep(wait)
            self._drain()
            self._cmd.sendto(cmd.encode("utf-8"), self.addr)
            self._last_send = time.monotonic()
            deadline = self._last_send + timeout
            while True:
                if self.cancel is not None and self.cancel.is_set():
                    raise TelloError(f"'{cmd}' cancelado")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TelloError(f"sin respuesta a '{cmd}' en {timeout:g} s")
                self._cmd.settimeout(min(remaining, 0.2))
                try:
                    data, _ = self._cmd.recvfrom(1024)
                except socket.timeout:
                    continue
                return data.decode("utf-8", "replace").strip()

    def command(self, cmd, timeout=15.0):
        """Comando de acción: exige 'ok'. Sin reintentos."""
        response = self._exchange(cmd, timeout)
        if response.lower() != "ok":
            raise TelloError(f"'{cmd}' respondió '{response}'")
        return response

    def query(self, cmd, timeout=5.0):
        """Consulta como 'battery?': devuelve el texto de la respuesta."""
        return self._exchange(cmd, timeout)

    def emergency(self, repeats=3):
        """Apaga los motores al instante.

        No toma el candado: si otro comando está esperando respuesta, el paro de
        emergencia no puede hacer fila detrás de él. Como es idempotente, se manda
        varias veces por si se pierde un paquete.
        """
        for _ in range(repeats):
            self._cmd.sendto(b"emergency", self.addr)
            time.sleep(0.02)

    def close(self):
        self._running = False
        self._cmd.close()
        self._state_sock.close()
        if self._thread is not None:
            self._thread.join(timeout=2)
