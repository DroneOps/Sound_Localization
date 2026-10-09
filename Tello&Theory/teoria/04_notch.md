# El notch (filtro de muesca)

Implementado en `codigo/soundloc/dsp.py` (`notch_sos`, `notch_bank_sos`, `harmonics_in_band`,
`notch`, `find_tonal_peaks`). Figuras: `figuras/notch_q.png`, `notch_tello_real.png`,
`notch_tiempo.png`.

## El problema

El pasa-banda no toca lo que está dentro de la banda. En el Tello real hay **20 picos tonales** entre
300 y 3000 Hz.

```
BPF = (RPM / 60) × número de palas
```

El pulso de cada pala no es una senoidal pura; toda señal periódica no senoidal se descompone en la
**fundamental** más sus **armónicos** (múltiplos exactos). Con 4 motores a velocidades un poco
distintas, cada uno tiene su familia de armónicos (ej. 642 y 677 Hz).

## Qué es

Lo contrario de un pasa-banda: quita una banda muy angosta alrededor de `f0` y deja pasar lo demás.

```
Q = f0 / BW          (BW = ancho entre los puntos de −3 dB)
```

Q = 30 en 660 Hz → 22 Hz de ancho.

## Cómo funciona

Es una sección de segundo orden:

```
y[n] = x[n] − 2·cos(ω0)·x[n−1] + x[n−2]  +  2r·cos(ω0)·y[n−1] − r²·y[n−2]       ω0 = 2π·f0/fs
```

- **Los términos con x matan el tono.** Con `x[n] = cos(ω0·n)` y la identidad
  `cos(a+b) + cos(a−b) = 2·cos(a)·cos(b)`: `x[n] − 2·cos(ω0)·x[n−1] + x[n−2] = 0` exactamente, para
  cualquier amplitud y fase.
- **Los términos con y salvan a las demás frecuencias** (realimentación). `r` un poco menor que 1
  controla el ancho: `BW ≈ (1 − r)·fs/π`. Para 22 Hz a 48 kHz, `r ≈ 0.99856`.
- Un filtro que usa sus salidas anteriores es **IIR** (*Infinite Impulse Response*). El filtro de un
  polo del compañero también lo es. Si `r ≥ 1`, es inestable.
- En código: `scipy.signal.iirnotch(f0, Q, fs)`.

## Cerca del centro

```
|H| ≈ |δ| / √(δ² + (BW/2)²)          δ = distancia al centro (Hz)
```

Con BW = 44 Hz: 2 Hz → −21 dB; 5 Hz → −13 dB; 10 Hz → −8 dB; 22 Hz → −3 dB. **El notch sólo es
profundo en un par de hertz**: el seguimiento de la frecuencia tiene que ser muy preciso. De ida y
vuelta, a un ruido blanco le quita un ancho equivalente de `(3π/4)·BW`.

## Los tres compromisos

1. **Ancho contra voz perdida.** Lo que cuenta es la **mejora de SNR** = lo que baja el ruido − lo que
   baja la señal. Datos reales del Tello (20 notches, uno por pico, "voz" de prueba plana):

   | Q | Banda tapada | Ruido del Tello | "Voz" | Mejora de SNR |
   |---|---|---|---|---|
   | 10 | 107 % | −16.7 dB | −9.5 dB | +7.2 dB |
   | 30 | 36 % | −7.6 dB | −3.9 dB | +3.7 dB |
   | 60 | 18 % | −4.5 dB | −2.0 dB | +2.5 dB |
   | 100 | 11 % | −3.1 dB | −1.2 dB | +1.9 dB |
   | 200 | 5 % | −1.9 dB | −0.6 dB | +1.3 dB |

   Es el mejor caso: los picos se sacaron de la misma grabación. Y cambian entre vuelos.

2. **Ancho contra rapidez.** Tiempo de respuesta ≈ `1/(π·BW) = Q/(π·f0)`: en 660 Hz, 2 ms (Q = 5),
   14 ms (Q = 30), 48 ms (Q = 100). No se puede ser muy angosto en frecuencia y muy rápido en tiempo.

3. **Los armónicos se separan.** Si dos motores difieren 35 Hz en la fundamental, en el 4.º armónico
   difieren 140 Hz. Un banco de **Q constante** se ensancha solo con la frecuencia.

## Dónde poner los notches

- En el dron del TMR: con la RPM del ESC (DShot bidireccional), en `k × BPF`. Es lo que hace
  `INS_HNTCH` en ArduPilot para los giroscopios (`INS_HNTCH_MODE = 3`, `INS_HNTCH_BW` es el ancho):
  **esto se va a usar seguro**, aunque desaparezca la misión del sonido.
- En el Tello: estimar los picos del propio audio (`find_tonal_peaks`).

## Conclusión con los datos

Para el Tello, el pasa-banda fue la ganancia grande (~15 dB) y el notch un refinamiento (+2.5 a
+3.7 dB con Q de 60 a 30). En el dron del TMR (hélices más grandes y lentas, BPF ~300 Hz) puede pesar
más: hay que medirlo. No conviene profundizar en el notch del audio sin datos del dron real.

## Preguntas de comprobación (resueltas)

1. BPF 600 Hz, 3 palas → 12 000 RPM. BPF 300 Hz → 10 armónicos en 300–3000 Hz.
2. Q = 40 en 1200 Hz → 30 Hz de ancho.
3. +3 % de RPM mueve el 4.º armónico de 660 Hz unos 79 Hz; un notch de Q = 60 ahí mide 44 Hz: no
   alcanza (y sólo es profundo en un par de hertz).
4. Los 16.7 dB con Q = 10 no son útiles: también se llevan la voz (mejora real de SNR: 7.2 dB, tapando
   el 107 % de la banda).
