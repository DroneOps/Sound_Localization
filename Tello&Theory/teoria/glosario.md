# Glosario para la libreta

## El sonido como fenómeno físico

- **Presión sonora**: variación de la presión respecto a la atmosférica, en Pa. 70 dB SPL ≈ 0.063 Pa.
  Instantánea `p(t)` o eficaz `p_RMS`.
- **Amplitud**: tamaño de la oscilación de cualquier señal (pico o RMS). No es lo mismo que presión
  sonora: puede ser de presión (Pa), voltaje (V) o muestras (cuentas).
- **Potencia acústica**: energía por segundo que emite la fuente (W). No depende de la distancia.
- **Intensidad acústica**: potencia por unidad de área (W/m²). `I = W/(4πr²)`, `I = p²/(ρc)`.
- **Superposición**: las presiones de varias fuentes se suman algebraicamente.
- **Ley inversa del cuadrado**: `I ∝ 1/r²`, `p ∝ 1/r`, −6 dB por duplicar la distancia.
- **Longitud de onda**: `λ = c/f`. **Difracción**: las ondas rodean obstáculos más chicos que λ.

## Decibeles

- **Decibel**: logaritmo de un cociente. 10·log10 para potencias, 20·log10 para amplitudes.
- **Nivel** (con referencia fija, absoluto) contra **diferencia** (relativa).
- **dB SPL**: referencia 20 µPa. **dB(A)**: con ponderación A (imita al oído; 0 dB en 1 kHz).
- **dBFS**: respecto a la escala completa del ADC; todo es negativo.
- **Suma de niveles**: se suman potencias. N fuentes iguales: `L + 10·log10(N)`.
- **Fuentes incoherentes / coherentes**: se suman potencias / amplitudes.

## De la presión a los números

- **Transductor**: convierte una magnitud física en otra (el micrófono: presión → voltaje).
- **MEMS**: estructuras mecánicas microscópicas en silicio (micrófonos, IMU).
- **ADC**, **muestreo**, **frecuencia de muestreo fs**, **cuantización**, **LSB**, **ruido de cuantización**.
- **Nyquist**: `fs > 2f`; frecuencia de Nyquist `fs/2`. **Aliasing**: `f_alias = fs − f`.
- **Filtro anti-aliasing**, **remuestreo**, **diezmado**.
- **Rango dinámico**: de la señal más fuerte al piso de ruido (~6 dB por bit).
- **Sensibilidad** (dBFS a 94 dB SPL = 1 Pa), **AOP** (saturación acústica), **THD**, **ruido propio**,
  **SNR del micrófono** (no es nuestra SNR).
- **Factor de cresta** (pico/RMS), **headroom** (del pico más fuerte a 0 dBFS).
- **Linealidad**, **saturación (clipping)**, **AGC** (lazo de control que iguala niveles).
- **ALSA**, **PipeWire**, `hw:` (falla) contra `plughw:` (convierte en silencio).
- **PCM/WAV** (sin compresión), **FLAC** (sin pérdida), **compresión con pérdida** y **enmascaramiento**.
- **UAC** (audio por USB sin driver), **I2S** (BCLK, WS/LRCLK, SD), **EMI**, **DSP**.
- **Supresión de ruido**, **beamforming**, **AEC**, **des-reverberación**, **VAD**, **DOA**.

## Medidas de una señal

- **Señal y ruido** (relativos al objetivo), **RMS**, **potencia** y **energía** de una señal, **SNR**.
- Diferencia entre cajas: `Δ = 10·log10(1 + S/N)`.

## Estadística de la medición

- **Estimador**, **varianza** (y desviación estándar), **error estándar** (`σ/√K`), **sesgo**.
- **Sesgo común** (se cancela) y **sesgo diferencial** (no se cancela ni se promedia).
- **Precisión** (poca varianza) y **exactitud** (poco sesgo). En ISO 5725, *veracidad* es la parte del sesgo.
- **Valor atípico (outlier)**: se detecta contra la dispersión normal y se descarta.
- **Confusión**: cuando otra variable cambia junto con la que se estudia (se evita alternando).

## Planteamiento

- **Detección (H0/H1)** contra **decisión entre M alternativas**.
- **Modo común**, **rechazo de modo común**, **CMRR**.

## Montaje

- **Ruido de flujo**, **vibración estructural**, **frecuencia natural** `fn = (1/2π)√(k/m)`,
  **transmisibilidad** `T = 1/|1 − (f/fn)²|`, **resonancia**.

## Filtros

- **Respuesta en frecuencia**, **frecuencia de corte** (−3 dB), **banda de paso / transición / rechazo**.
- **Octava** (×2), **década** (×10), **polo** (6 dB por octava).
- **Butterworth** (plano en la banda de paso), **transformación bilineal**, **prewarping**.
- **SOS / biquad** (secciones de segundo orden), **fase cero** (`sosfiltfilt`) contra **causal** (`sosfilt`).
- **IIR**: usa sus salidas anteriores (realimentación); **estabilidad**.
- **Notch**: quita una banda angosta en `f0`. **Q = f0/BW**. **Ancho de banda BW** (a −3 dB).
- **BPF** = `(RPM/60) × palas`. **Fundamental** y **armónicos** (múltiplos exactos).
- **Mejora de SNR** = lo que baja el ruido − lo que baja la señal.

## Software y drones

- **Idempotente**: da lo mismo ejecutarlo una o varias veces (`emergency`, `command`; no `forward 100`).
- **SITL / simulador**: probar el código sin el dron. **Flujo óptico**, **ToF**, **VPS** del Tello.
