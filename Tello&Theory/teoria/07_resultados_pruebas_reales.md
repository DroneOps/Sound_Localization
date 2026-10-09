# Resultados de las pruebas con hardware real (6 de octubre de 2026)

Las grabaciones están en `datos/` (carpetas del 20261006); ver la tabla del `LEEME.md`.

## Pruebas del micrófono (tono de 1 kHz con escalones de ±10 dB)

| Sesión | Micrófono | Resultado |
|---|---|---|
| 215929 | Steren, lejos y con volumen bajo | No concluyente |
| 220139 | Interno, volumen al 50 % | No concluyente (tono casi al nivel de la sala) |
| 220548 | Interno, volumen al 100 % | Escalones de +9.0 / −9.0 dB, A2 − A = +0.04 dB. Casi lineal; el dB que falta probablemente es ruido de la sala. Figura: `figuras/prueba_mic_interno_laptop.png` |
| 220713 | Steren a 30 cm, volumen al 100 % | **No apto**: silencio digital, borra los tonos constantes. Figura: `figuras/prueba_mic_steren.png` |

Comparación en los mismos instantes (el micrófono interno como referencia):

| Tramo | Interno | Steren |
|---|---|---|
| Tono A (4–10 s) | estable, −40 dBFS | pasa 1 s y luego ceros exactos |
| Tono B (10–16 s) | estable, −31 dBFS | pasa, pero baja 13 dB en 6 s |
| Tono A2 (16–22 s) | estable, −40 dBFS | ceros exactos |

## Vuelos del Tello (micrófono interno de la laptop, laptop sobre una mesa)

| Sesión | Qué pasó |
|---|---|
| 221821 | Abortó al conectar: el Tello contestó un paquete binario |
| 221910 | Abortó: no contestó `command` (amarrado al puerto del intento anterior, o caliente) |
| 222601 | Despegó a 86 °C y aterrizó solo 7.5 s después. Se rescataron 3.7 s de hover a 1 m |
| 223749 | Hover de 7 s a 1 m completo; el `forward 80` fue rechazado con `No valid imu` |
| 224451 | El ajuste de altura falló; un Ctrl+C durante el aterrizaje perdió los datos (corregido) |
| 232248 | Vuelo manual: Ctrl+C durante el despegue, el programa no mandó `land` (corregido) |
| 232338 | Vuelo manual de 76.7 s hasta 96 °C sin aterrizar solo; sin hovers marcados; casi sin respuesta a las palancas |

## Las mediciones reales

| | Vuelo 3 | Vuelo 4 |
|---|---|---|
| Nivel a 1 m (banda ancha) | −22.5 dBFS | −22.4 dBFS |
| En la banda de voz | −37.2 dBFS | −37.5 dBFS |
| Fracción en banda | −14.7 dB | −15.1 dB |

- **Repetibilidad entre vuelos en el mismo punto: 0.1 dB** (dos muestras).
- El Tello está 35.7 dB sobre la sala. Reparto de su potencia: 0.6 % < 100 Hz, 3.7 % en 300–3000 Hz,
  11.5 % en 3–8 kHz, **84 % arriba de 8 kHz**.
- Tonos de pala: ~642–680 Hz, con armónicos cerca de 1320 y 1920–2010 Hz. Los dos picos cercanos son
  motores girando a velocidades distintas (correcciones de actitud). Con 2 palas, ~19 000–20 000 RPM.
- El notch agrega de +2.5 a +3.7 dB de SNR con Q de 60 a 30 (ver 04_notch.md).
- Reservas: pocos segundos, una sola distancia, respuesta en frecuencia del micrófono desconocida.

Figuras: `tello_espectro_hover_1m.png`, `tello_espectrograma_vuelo3.png`,
`tello_linea_de_tiempo_vuelo4.png`, `notch_tello_real.png`.

## Defectos que encontró el hardware real (todos corregidos y con prueba)

1. El piso de ruido se estimaba con un promedio y el chasquido de arranque lo inflaba → mediana.
2. El códec interno tarda ~1 s en asentarse → arranque de 1 s.
3. Un micrófono con compuerta salía "no concluyente" → "no apto" de inmediato.
4. Paquetes binarios del Tello tomados como respuesta → se ignoran.
5. Puerto local aleatorio → puerto fijo 8889 y reintento sólo del idempotente `command`.
6. Mantenimiento con `battery?` (sospechoso del aterrizaje del vuelo 3) → `command`.
7. El ajuste de altura fallido abortaba el vuelo → ya no es fatal.
8. Un Ctrl+C durante el aterrizaje perdía los datos → se guardan siempre.
9. Un aborto durante el despegue no mandaba `land` → espera la respuesta pendiente del despegue y
   entonces aterriza (la simulación encontró que mandarlo antes confundía los dos `ok`).

Lección: la simulación sólo prueba lo que uno ya pensó; el hardware encuentra lo demás. Y como se
guardan los datos crudos, todo se pudo volver a analizar sin repetir las grabaciones.
