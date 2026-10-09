# Hardware: micrófonos, fuentes de sonido y el Tello

## Micrófonos

| Micrófono | Veredicto | Por qué |
|---|---|---|
| Steren MOV-033 (USB-C, chip JieLi) | **Descartado** | Supresión de ruido adaptativa con compuerta: deja pasar el inicio de un tono, lo va borrando y lo corta a cero exacto. Probado contra una referencia. |
| Interno de la laptop (`hw:CARD=PCH,DEV=0`) | **Sirve para el banco** | Sin compuerta, ganancia fija, repite con 0.04 dB. Escalones de 9 dB en lugar de 10 en una sala ruidosa: repetir en silencio. Da un chasquido de ~1 s al abrirse. 48 kHz, 2 canales. |
| ReSpeaker USB Mic Array v2.0 | Para desarrollo | Sólo los canales crudos 1–4 (ver 02_adquisicion.md). No comprar hasta conocer el reglamento. |
| INMP441 (o ICS-43434) | **Recomendado para el dron final** | MEMS I2S, sensibilidad fija, digital, gramos. El ICS-43434 tiene 4 dB más de SNR propia, que no ayuda (el límite son los rotores), pero garantiza ±1 dB entre unidades. |
| CZN-15E en plaquita con LM393 | La plaquita **no sirve** | El LM393 es un **comparador**: la salida dice "hay sonido arriba del umbral" o "no hay". La cápsula sí se puede rescatar: a la entrada de micrófono de una tarjeta de sonido USB (carcasa a tierra/manga; la otra terminal a punta y anillo), y verificar con la prueba del micrófono. |

Regla: cualquier micrófono "para celular" con reducción de ruido es sospechoso. Siempre correr
`soundloc.devices` y `soundloc.mic_test` antes de usar un micrófono nuevo.

## Fuente de sonido para pruebas: ISD1820

Graba y reproduce un mensaje de ~8–20 s (unos 10 s con la resistencia de fábrica), con sonido tipo
teléfono (hasta ~3 kHz). Con el jumper **P-E** reproduce en bucle: sirve como bocina de auxilio para
el banco, con un "¡ayuda!" grabado por el equipo. Hay que medir si llega a 70 dB a 1 m; si no,
agregarle un amplificador pequeño y una bocina más grande.

## El Tello

- SDK por UDP: comandos de texto a `192.168.10.1:8889`, telemetría al puerto 8890 de la computadora
  (~10 paquetes por segundo). Comandos de movimiento de 20 a 500 cm.
- **Sin reintentos de movimientos** (no son idempotentes); `command` y `emergency` sí lo son.
- Recién encendido manda **paquetes binarios** de su protocolo interno: hay que ignorarlos.
- Conviene usar siempre el mismo **puerto local (8889)**: recién encendido parece contestarle sólo al
  primer puerto que le habló.
- Aterriza solo si pasa **15 s sin comandos**. Las palancas virtuales (`rc`) y `command` sirven para
  mantenerlo vivo.
- Se mantiene quieto con una **cámara y un ToF en la panza** (flujo óptico). Si fallan: deriva hacia
  un lado y rechaza `forward`/`up` con `No valid imu`. Las palancas `rc` sí funcionan, porque no le
  piden medir cuánto se movió.
- **Temperatura**: se calienta unos 12 °C por minuto encendido; voló hasta 96 °C sin aterrizar solo.
  El límite de despegue quedó en 90 °C.
- El **yaw** se mide respecto a hacia dónde apuntaba al encenderlo.
- **Pendiente** (6 de octubre): deriva siempre al mismo lado, reporta 0° de inclinación mientras se le
  ve ladeado y casi no responde a las palancas. Sospecha principal: IMU descalibrada. Revisar hélices
  (A/B, sin daños, girando libres), protectores, batería asentada; calibrar la IMU con la app oficial;
  piso con textura; y probar con la app si obedece antes de volver al código.
