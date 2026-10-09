"""Grabación con arecord, con marcas de tiempo por bloque (sección 2.1, partes B y C).

Se usa `arecord` sobre un dispositivo `hw:` para que ALSA entregue los datos
exactamente como los produce el hardware, sin conversiones silenciosas.
"""

import csv
import subprocess
import threading
import time
import wave


class RecorderError(RuntimeError):
    pass


def arecord_command(device, rate, channels, fmt="S16_LE"):
    return ["arecord", "-D", device, "-f", fmt, "-r", str(rate), "-c", str(channels),
            "-t", "raw", "-q", "-"]


class Recorder:
    """Lee audio crudo de un proceso (arecord o un simulador) y lo guarda en WAV."""

    def __init__(self, wav_path, timestamps_path, rate, channels=1, device=None,
                 source_cmd=None, cwd=None, chunk_frames=1024, on_chunk=None):
        if source_cmd is None:
            if not device:
                raise ValueError("Hace falta un dispositivo o un comando de fuente")
            source_cmd = arecord_command(device, rate, channels)
        self.cmd = list(source_cmd)
        self.wav_path = wav_path
        self.timestamps_path = timestamps_path
        self.rate = rate
        self.channels = channels
        self.cwd = cwd
        self.chunk_frames = chunk_frames
        self.frame_bytes = 2 * channels
        self.frames = 0
        self.chunks = []  # (muestras acumuladas al final del bloque, hora de llegada)
        self.on_chunk = on_chunk  # recibe los bytes de cada bloque, para quien analiza en vivo
        self._proc = None
        self._thread = None
        self._wav = None
        self._stopped = False

    def start(self):
        self._wav = wave.open(str(self.wav_path), "wb")
        self._wav.setnchannels(self.channels)
        self._wav.setsampwidth(2)
        self._wav.setframerate(self.rate)
        try:
            self._proc = subprocess.Popen(self.cmd, stdout=subprocess.PIPE,
                                          stderr=subprocess.PIPE, cwd=self.cwd)
        except OSError as exc:
            self._wav.close()
            raise RecorderError(f"No se pudo iniciar la grabación: {exc}") from exc
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        chunk_bytes = self.chunk_frames * self.frame_bytes
        leftover = b""
        while True:
            data = self._proc.stdout.read(chunk_bytes)
            if not data:
                break
            arrival = time.monotonic()
            data = leftover + data
            usable = len(data) - len(data) % self.frame_bytes
            leftover = data[usable:]
            if usable:
                self._wav.writeframesraw(data[:usable])
                if self.on_chunk is not None:
                    self.on_chunk(data[:usable])
                self.frames += usable // self.frame_bytes
                self.chunks.append((self.frames, arrival))

    def wait_started(self, timeout=3.0):
        """No sigue hasta comprobar que de verdad está llegando audio."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.frames > 0:
                return
            if self._proc.poll() is not None:
                break
            time.sleep(0.05)
        detail = self.stop()
        raise RecorderError("No llega audio del dispositivo" + (f": {detail}" if detail else ""))

    def stop(self):
        """Detiene la grabación y guarda todo. Devuelve lo que la fuente escribió en stderr."""
        if self._stopped or self._proc is None:
            return ""
        self._stopped = True
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
        self._thread.join(timeout=5)
        self._wav.close()
        with open(self.timestamps_path, "w", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["muestras_fin", "t"])
            writer.writerows((n, f"{t:.6f}") for n, t in self.chunks)
        return self._proc.stderr.read().decode("utf-8", "replace").strip()
