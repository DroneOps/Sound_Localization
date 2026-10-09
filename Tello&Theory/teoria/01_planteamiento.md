# 1. Planteamiento formal

## 1.1 Qué mide el micrófono

El sonido es una variación de la presión del aire alrededor de la presión atmosférica
(~101 325 Pa). El micrófono la convierte en voltaje y el **ADC** (*Analog-to-Digital Converter*)
la **muestrea** (mide cada `dt = 1/fs`) y la **cuantiza** (la redondea a un entero; `S16_LE` =
16 bits con signo, de −32768 a 32767).

Notación: `x(t)` es la señal continua (tiempo en segundos); `x[n]` es la discreta (índice de
muestra); `t = n·dt`.

## 1.2 Superposición

```
x(t) = s(t) + n(t)
```

`s` = señal (la bocina, atenuada y coloreada por la caja); `n` = ruido (rotores, flujo de aire,
vibración del frame). En acústica a niveles normales, las presiones de varias fuentes se suman
algebraicamente. Por eso el problema es difícil (no se separan los términos en una muestra) y a la
vez tiene solución: si `n` es igual en dos mediciones, la diferencia sólo contiene a `s`.

## 1.3 Amplitud, potencia y RMS

El promedio de una señal de audio es ~0. Lo que sirve es elevar al cuadrado: la potencia va con el
cuadrado de la amplitud.

```
RMS = sqrt( (1/N) · Σ x[n]² )        (senoidal de pico A → A/√2)
potencia = RMS²   (no depende de la duración)
energía  = Σ x[n]² (crece con la duración)
```

## 1.4 El decibel

Un decibel expresa un **cociente** en escala logarítmica:

```
potencias (potencia, intensidad, energía):  dB = 10·log10(P / P_ref)
amplitudes (presión, voltaje, muestras):    dB = 20·log10(A / A_ref)
```

Es la misma definición: el 20 sale de que `P ∝ A²` y `log(u²) = 2·log(u)`.

| Cambio | Potencia | Amplitud |
|---|---|---|
| +3 dB | ×2 | ×1.41 |
| +6 dB | ×4 | ×2 |
| +10 dB | ×10 | ×3.16 |
| +20 dB | ×100 | ×10 |

**dB SPL**: `20·log10(p_RMS / 20 µPa)`. 0 dB SPL ≈ umbral de audición; 120 ≈ dolor (20 Pa).

Para comparar cajas no hace falta calibrar: la sensibilidad desconocida `k` (m = k·p) se cancela
en la resta, `L_B − L_A = 20·log10(p_B/p_A)`, siempre que `k` sea la misma en las dos mediciones.

## 1.5 Ley inversa del cuadrado

```
I ∝ 1/r²      p ∝ 1/r      ΔL = 20·log10(r1/r2)      (−6 dB por duplicar la distancia)
```

Supone fuente puntual y campo libre. Con 70 dB SPL a 1 m y el micrófono a ~1.6 m de la bocina:
`70 − 4.1 ≈ 66 dB SPL`.

## 1.6 SNR

```
SNR_dB = 10·log10(P_señal / P_ruido) = L_señal − L_ruido
```

Estimado: 66 dB de bocina contra ~90 dB de rotores → **SNR ≈ −24 dB**. La señal tiene el 0.4 % de
la potencia del ruido; en amplitud, el ruido es ~16 veces mayor.

## 1.7 Detección contra comparación (el punto central)

- **Detección** (una grabación, umbral absoluto: `H0` = no hay bocina, `H1` = sí hay) no funciona
  con −24 dB de SNR.
- El problema real es **elegir 1 de M ≤ 5 cajas**: basta con ordenar.

```
n(t) = n_común(t) + n_variable(t)
```

Al restar mediciones, `n_común` se cancela y la señal compite sólo contra `n_variable`. Por eso
"misma altura, mismo régimen de motores" es parte del algoritmo. Es **rechazo de modo común**,
como el bus CAN (CAN_H − CAN_L). La pregunta de viabilidad es: ¿cuál es el CMRR del protocolo?
¿Cuánto se mueve la medición entre dos cajas vacías?

## 1.8 Estimador, sesgo y varianza

- **Varianza**: dispersión aleatoria. Se reduce promediando (error ∝ 1/√K).
- **Sesgo**: error sistemático. No se reduce promediando.

> No vamos a mejorar la SNR. Vamos a reducir la **varianza del estimador** hasta que la pequeña
> diferencia entre una caja con bocina y una vacía sea estadísticamente resoluble.

## 1.9 El problema formal

Dadas `M ≤ 5` posiciones (una por caja) y en cada una una grabación `x_i[n]` tomada en condiciones
deliberadamente iguales: construir un estadístico `T_i = f(x_i)` que dependa lo más posible de `s`
y lo menos posible de `n`; decidir `i* = argmax T_i`; y reportar una confianza comparable con la
variabilidad del estadístico entre cajas igualmente vacías.

---

## Lo que salió de las preguntas de comprobación

**Promediar no elimina el ruido.** Con `N = 1.000` y `S = 0.004` (−24 dB), la caja vacía converge a
1.000 y la llena a 1.004: el ruido sigue ahí completo. Lo que desaparece es el bamboleo de la
estimación. La diferencia real es:

```
Δ = 10·log10(1 + S/N)
```

| SNR en la banda | Diferencia entre cajas |
|---|---|
| −24 dB (sin procesar) | **0.017 dB** |
| −10 dB | 0.41 dB |
| −5 dB | 1.19 dB |
| 0 dB | 3.01 dB |

Por eso el filtro de banda, el notch y los features no son refinamientos: son lo que hace que el
problema sea resoluble. (Los ejemplos de "2 dB de diferencia" sólo valen si la SNR en banda ya
quedó cerca de −2 dB.)

**No todos los sesgos son iguales.**

| | Odometría | Audio | Remedio |
|---|---|---|---|
| Varianza | temblor del encoder | turbulencia de trama a trama | promediar |
| Sesgo común | las dos ruedas con el mismo error | ganancia fija al doble en las 5 cajas | se cancela al comparar |
| Sesgo diferencial | una rueda distinta de la otra | más RPM sobre una caja | prevenir con el protocolo, o medirlo y compensarlo |

Criterio: ¿la alteración sube tantas veces como baja dentro de la medición? → varianza. Si no, ¿afecta
igual a todas? → sesgo común. Si no → sesgo diferencial. Que sea externa o interna no importa.

- El ruido de rotor crece aproximadamente con RPM⁵–RPM⁶: **1 % más de RPM ≈ +0.2 a 0.26 dB**, más de
  10 veces la diferencia que produce la bocina en banda ancha.
- El AGC es un lazo de control cuyo setpoint es "que todo suene igual": sesgo diferencial.
- Una ráfaga breve no se cancela al promediar: sólo se diluye. Hay que detectar y descartar las
  tramas afectadas (la telemetría de RPM sirve para eso).
- **Precisión** (poca varianza) no es **exactitud** (poco sesgo): promediar compra precisión, nunca
  exactitud. Medir más tiempo con un sesgo diferencial da la respuesta equivocada con más confianza.
- Un grito del público se parece a la señal que buscamos. Lo que distingue a la bocina es la
  **persistencia**: suena toda la medición y sólo sobre una caja. El estadístico debe premiar la
  persistencia, no sólo el nivel.
