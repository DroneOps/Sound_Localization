"""Dispositivos de captura: qué hay conectado, qué formatos acepta y si trae AGC.

    python -m soundloc.devices
"""

import re
import subprocess
import sys
from pathlib import Path

_CARD_LINE = re.compile(r"^card (\d+): (\S+) \[(.*?)\], device (\d+): (.*?) \[(.*?)\]")


def list_capture_devices():
    out = subprocess.run(["arecord", "-l"], capture_output=True, text=True).stdout
    devices = []
    for line in out.splitlines():
        m = _CARD_LINE.match(line)
        if m:
            devices.append({"indice": int(m[1]), "id": m[2], "nombre": m[3],
                            "dispositivo": int(m[4]), "hw": f"hw:CARD={m[2]},DEV={m[4]}"})
    return devices


def usb_stream_info(card_index):
    """Para tarjetas USB, el kernel publica los formatos exactos que acepta el hardware."""
    p = Path(f"/proc/asound/card{card_index}/stream0")
    return p.read_text() if p.exists() else None


def parse_capture_caps(text):
    capture = text.split("Capture:", 1)[1] if "Capture:" in text else ""
    return {"formatos": sorted(set(re.findall(r"Format:\s*(\S+)", capture))),
            "canales": sorted(set(re.findall(r"Channels:\s*(\d+)", capture))),
            "frecuencias": [r.strip() for r in re.findall(r"Rates:\s*(.+)", capture)]}


def _covers(rate_text, target):
    numbers = [int(v) for v in re.findall(r"\d+", rate_text)]
    if " - " in rate_text and len(numbers) >= 2:
        return numbers[0] <= target <= numbers[1]
    return target in numbers


def suggest_rate(caps):
    for target in (16000, 48000):
        if any(_covers(r, target) for r in caps["frecuencias"]):
            return target
    numbers = [int(v) for r in caps["frecuencias"] for v in re.findall(r"\d+", r)]
    return max(numbers) if numbers else None


def card_from_device(device):
    """'hw:CARD=Device,DEV=0' → 'Device';  'hw:1,0' → '1'."""
    m = re.match(r"^(?:plug)?hw:(?:CARD=)?([^,]+)", device or "")
    return m[1] if m else None


def mixer_text(card):
    r = subprocess.run(["amixer", "-c", str(card), "scontents"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def agc_controls(text):
    """Controles del mezclador ALSA que parezcan un AGC, y si están encendidos."""
    controls = []
    for block in text.split("Simple mixer control ")[1:]:
        first = block.split("\n", 1)[0]
        name = first.split("'")[1] if first.count("'") >= 2 else first
        if "auto gain" in name.lower() or name.lower().strip() == "agc":
            states = re.findall(r"\[(on|off)\]", block)
            controls.append({"control": name, "encendido": ("on" in states) if states else None})
    return controls


def mixer_report(device):
    card = card_from_device(device)
    text = mixer_text(card) if card else ""
    return {"tarjeta": card, "mezclador": text, "agc": agc_controls(text)}


def main():
    devices = list_capture_devices()
    if not devices:
        print("No se encontró ningún dispositivo de captura (arecord -l).")
        return 1
    print("Dispositivos de captura:\n")
    for d in devices:
        print(f"  Tarjeta {d['indice']}: {d['nombre']}")
        print(f"    --device {d['hw']}")
        info = usb_stream_info(d["indice"])
        if info:
            caps = parse_capture_caps(info)
            print(f"    USB. Formatos: {', '.join(caps['formatos']) or '?'}"
                  f" | canales: {', '.join(caps['canales']) or '?'}"
                  f" | frecuencias: {'; '.join(caps['frecuencias']) or '?'}")
            rate = suggest_rate(caps)
            if rate == 16000:
                print("    Sugerencia: --rate 16000 (graba a 16 kHz nativo)")
            elif rate:
                print(f"    Sugerencia: --rate {rate}. No graba a 16 kHz nativo: se graba a"
                      f" {rate} y se remuestrea después con filtro anti-aliasing.")
        else:
            print(f"    No es USB. Capacidades: arecord -D {d['hw']} --dump-hw-params -d 1 /dev/null")
        for c in agc_controls(mixer_text(d["id"])):
            state = {True: "ENCENDIDO", False: "apagado", None: "estado desconocido"}[c["encendido"]]
            print(f"    ¡Ojo! El mezclador tiene un control '{c['control']}' ({state}).")
            if c["encendido"]:
                print(f"    Para apagarlo: amixer -c {d['id']} sset '{c['control']}' off")
        print()
    print("Usa el nombre (CARD=...) y no el número de tarjeta: el número puede cambiar al reconectar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
