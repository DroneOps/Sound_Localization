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

## Estado

Repositorio recién iniciado. Primer entregable previsto: herramienta de análisis acústico
(grabación, filtrado en banda, energía por ventana, comparación entre posiciones).

## Regla de trabajo

Cada línea de código que controle el dron se prueba primero en SITL. Siempre hay un piloto con el
radio listo para retomar el control, incluso en vuelo autónomo.
