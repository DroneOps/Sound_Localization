# 2.2 El filtro pasa-banda de voz (300–3000 Hz)

Implementado en `codigo/soundloc/dsp.py` (`bandpass_sos`, `bandpass`). Figura:
`figuras/respuesta_pasabanda.png`.

## Qué es un filtro, visto en frecuencia

Multiplica cada senoidal de la señal por una ganancia `|H(f)|`. La curva de esa ganancia en dB es la
**respuesta en frecuencia**. La **frecuencia de corte** es donde la ganancia vale −3 dB (mitad de la
potencia). Entre lo que pasa y lo que se bloquea queda la **banda de transición**.

## Orden y pendiente

- **Octava** = duplicar la frecuencia; **década** = multiplicarla por 10.
- Cada **polo** agrega 6 dB por octava (20 dB por década).
- Nuestro filtro: 4 polos por flanco → ~24 dB por octava. Medido: −26.8 dB a 150 Hz.
- Un filtro muy empinado "suena" más tiempo después de un golpe y retrasa más en tiempo real. El
  orden 4 es el equilibrio habitual.

## Butterworth

Es el más plano posible en la banda de paso (sin ondulaciones). Medido: ±0.1 dB entre 600 y 1500 Hz.
Para medir niveles queremos que la ganancia no dependa de la frecuencia exacta de la voz.

## De analógico a digital

Transformación **bilineal** con corrección previa de las frecuencias (*prewarping*): el −3 dB cae
exactamente en 300 y 3000 Hz (verificado: −3.01 dB). Es lo que no lograría Euler a estas frecuencias.

## Secciones de segundo orden (SOS)

Un filtro de 8 polos escrito como un solo polinomio es numéricamente frágil. Se parte en 4 secciones
de segundo orden (*biquads*) en cascada, cada una bien condicionada. En scipy:
`butter(..., output="sos")`, nunca `output="ba"` para órdenes altos.

## Ida y vuelta (fase cero)

Todo filtro causal retrasa la señal. `sosfiltfilt` filtra hacia adelante y hacia atrás: no desplaza
nada en el tiempo, pero aplica la atenuación dos veces (−6 dB en los cortes, pendiente doble). Como es
igual en todas las mediciones, es sesgo común. Sólo sirve con grabaciones completas; en tiempo real se
usa `sosfilt`, causal.

**Filtrar la grabación completa y recortar después**: el filtro tiene memoria y cortar antes mete
transitorios en los bordes.

## Qué gana

El ruido blanco conserva sólo la fracción de su potencia que cae en la banda: a 48 kHz,
`2700/24000 = 11 %`, o sea −9.5 dB (medido: −10.0 dB; la ida y vuelta angosta un poco el ancho
efectivo). Una voz casi completa dentro de la banda pasa casi entera.

## Su límite, y el dato real

Los tonos de pala que caen dentro de la banda pasan intactos. En el Tello real, con el micrófono
interno de la laptop, sólo el **3.7 %** de la potencia cae en 300–3000 Hz: el pasa-banda le quita
**~15 dB** al ruido del Tello (el 84 % está por encima de 8 kHz). El simulador suponía 60 % tonal
dentro de la banda; la realidad fue otra. Por eso se mide.
