# Sound_Localization

Subsistema de localización acústica para el dron autónomo del grupo estudiantil de drones,
categoría **Drones Autónomos del Torneo Mexicano de Robótica 2026** (misiones basadas en la
categoría de interiores del IMAV 2025).

## Objetivo

Misión 3 del reto: localizar una caja que contiene una bocina emitiendo un sonido de auxilio,
entre hasta 5 cajas idénticas (57 x 78 x 36 cm), y entregarle un med-kit (20 x 10 x 5 cm, 30 g).

El audio no es el detector primario: las cajas se detectan por visión y el audio sirve para
**desempatar** entre candidatas.

## Enfoque: búsqueda diferencial

Estimar la dirección del sonido en pleno vuelo es muy difícil con el ruido de los rotores. En
lugar de eso:

1. Detectar las cajas por visión (objetos grandes, de color uniforme).
2. Sobrevolar cada caja a la **misma altura** y con el **mismo régimen de motores**, midiendo
   durante unos segundos la energía acústica en la banda de voz (300–3000 Hz).
3. La caja correcta es la de mayor energía. Al mantener condiciones de vuelo idénticas, el ruido
   propio se vuelve casi constante y se cancela en la comparación: no se necesita SNR positivo,
   solo diferencia medible entre posiciones.

Refuerzos previstos sobre la métrica de energía cruda:

- **Coherencia entre canales** de un arreglo de micrófonos: el ruido de rotor llega descorrelacionado
  a cada cápsula, una fuente lejana llega coherente.
- **Supresión dirigida de tonos de hélice** usando la telemetría de RPM por DShot bidireccional de
  los ESC AM32.
- Clasificación con **YAMNet** (TFLite): el valor está en los embeddings, para entrenar un
  clasificador propio con grabaciones reales del equipo, con ruido de rotor incluido.

## Restricciones que condicionan el diseño

| Restricción | Implicación |
|---|---|
| Arena interior 10 x 10 x 4 m con red | No hay GPS: se requiere otra fuente de posición |
| Máx. 60 cm punta de hélice a punta opuesta | Dron clase 5–7", presupuesto de peso ajustado |
| Prohibido el pilotaje manual | Todo autónomo, solo se permite accionar un botón o comando |
| Paro / aterrizaje de emergencia obligatorio | Sin él no se permite participar |
| Bocina a mínimo 70 dB a 1 m, apuntando hacia arriba | Condición reproducible en laboratorio |
| Precisión de entrega del orden de ±20 cm | Lazo cerrado con cámara, no posición del EKF |

## Hardware

- **Controladora de vuelo:** Holybro Pixhawk 6C Mini (FMUv6C), ESC Tekko32 con firmware AM32, DShot600.
- **Computadora a bordo:** Raspberry Pi 5 con BEC dedicado de 5 V / 5–6 A.
- **Audio:** arreglo USB tipo ReSpeaker para desarrollo; MEMS I2S (INMP441 / ICS-43434) como
  candidato para el dron final. Cápsula electret analógica descartada (la Pi no tiene ADC).

## Entorno de desarrollo

```
Ubuntu 24.04 | ROS 2 Jazzy | Gazebo
~/ardupilot              # código fuente de ArduPilot
~/venv-ardupilot         # entorno Python (MAVProxy, pymavlink, OpenCV)
~/QGroundControl-x86_64.AppImage
```

Simulación:

```bash
sim_vehicle.py -v ArduCopter --console --map --out=udp:127.0.0.1:14551
```

Grabación de audio:

```bash
arecord -D plughw:1,0 -f S16_LE -r 16000 -c 1 prueba.wav
```

## Banco de pruebas de audio

- Bocina de 70 dB a 1 m, apuntando hacia arriba, dentro de una caja de plástico de dimensiones
  similares a la del reglamento (la caja actúa como caja acústica y altera el espectro).
- Sonómetro para repetibilidad entre pruebas.
- Espuma antiviento **y aislamiento mecánico** del micrófono: la espuma no bloquea la vibración
  estructural transmitida por el frame.
- Audio de referencia grabado por el equipo, no descargado.
- Protocolo: grabar 10 s a 1, 2 y 3 m de altura, con y sin dron encendido; analizar espectrogramas.

## Banco volante (Tello + micrófono USB)

Primer sistema aplicado: el micrófono queda fijo y un DJI Tello vuela solo una rutina
(ambiente con motores apagados, hover a 1-2-3-2-1 m, ambiente final) mientras se graba el
audio sincronizado con la telemetría. Mide la ley inversa del cuadrado, el espectro del ruido
del dron y la repetibilidad entre hovers a la misma distancia.

Instalación:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Uso, en este orden:

```bash
# 1. Encontrar el micrófono y ver qué formatos acepta
.venv/bin/python -m soundloc.devices

# 2. Verificar que la cadena es lineal y sin AGC (sin dron, ~30 s)
.venv/bin/python -m soundloc.mic_test --device hw:CARD=<id>,DEV=0 --rate 48000

# 3. Ensayar la rutina completa en simulación (sin dron ni micrófono)
.venv/bin/python -m soundloc.bench_flight --simulate

# 4. Vuelo real, con la laptop conectada al Wi-Fi del Tello
.venv/bin/python -m soundloc.bench_flight --device hw:CARD=<id>,DEV=0 --rate 48000 --mic-height 1.0

# Volver a analizar una sesión ya grabada
.venv/bin/python -m soundloc.analyze_flight sessions/<carpeta>

# Si el Tello no acepta movimientos ("No valid imu"): un vuelo corto por distancia...
.venv/bin/python -m soundloc.bench_flight --device hw:CARD=<id>,DEV=0 --start-distance 1.8 --plan 1.8 --max-distance 1.8
# ...o vuelo con piloto: Q despega, E aterriza, números = marcar hover, ENTER = emergencia
.venv/bin/python -m soundloc.manual_flight --device hw:CARD=<id>,DEV=0 --plan 1,1.8

# Juntar varios vuelos
.venv/bin/python -m soundloc.compare_sessions sessions/<vuelo_a> sessions/<vuelo_b>
```

Durante el vuelo: **ENTER = paro de emergencia** (motores apagados), **Ctrl+C = aterrizaje
controlado**. Cada sesión se guarda en `sessions/` con el audio crudo, la telemetría, los
tramos y un `sesion.json` con la metadata.

| Módulo | Qué hace |
|---|---|
| `soundloc/levels.py` | RMS, dBFS, saturación, suma y resta de niveles |
| `soundloc/dsp.py` | Filtro pasa-banda de voz (Butterworth en secciones de segundo orden) |
| `soundloc/recorder.py` | Grabación con `arecord` sobre `hw:`, con marcas de tiempo por bloque |
| `soundloc/timing.py` | Sincronización del audio con el reloj de la computadora |
| `soundloc/tello.py` | Cliente del SDK del Tello por UDP, sin reintentos |
| `soundloc/fake_tello.py`, `fake_audio.py` | Simulador del Tello y de su ruido (el "SITL" del banco) |
| `soundloc/mic_test.py` | Prueba de linealidad y AGC del micrófono |
| `soundloc/bench_flight.py` | Rutina de vuelo con verificaciones de seguridad |
| `soundloc/analyze_flight.py` | Niveles por tramo, ley inversa del cuadrado, gráficas |
| `soundloc/manual_flight.py` | Vuelo con piloto (teclas de `Mover.py`), con grabación y marcas de hover |
| `soundloc/compare_sessions.py` | Junta varios vuelos (por ejemplo, uno por distancia) |

Pruebas: `.venv/bin/python -m pytest`

## Estado

Primeras pruebas con hardware real (6 de octubre de 2026):

- El micrófono Steren MOV-033 queda descartado: tiene supresión de ruido adaptativa con
  compuerta (borra los sonidos constantes). Se usa el micrófono interno de la laptop.
- Dos hovers del Tello a 1 m, en vuelos distintos, coinciden con 0.1 dB de diferencia. Con el
  micrófono interno, sólo ~3.7 % de la potencia del Tello cae en la banda de voz (−15 dB).
- Pendiente: el Tello deriva siempre hacia el mismo lado y rechaza movimientos ("No valid
  imu"). Antes de volver a volar: revisar hélices y motores, calibrar la IMU en la app oficial
  y probar con la app si obedece.
- Siguiente en código: supresión de tonos de hélice (notch) y STFT/Welch.

## Regla de trabajo

Cada línea de código que controle el dron se prueba primero en SITL. Siempre hay un piloto con el
radio listo para retomar el control, incluso en vuelo autónomo.
