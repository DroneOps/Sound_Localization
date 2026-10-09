# 2.1 Adquisición

## Parte A: de la onda a los números

### La cadena

```
presión (Pa) → micrófono → voltaje (mV) → preamplificador → filtro anti-aliasing → ADC → números → WAV
```

En un micrófono **MEMS** digital (INMP441, ICS-43434) toda la cadena está dentro del chip. La regla:
la cadena tiene que ser **lineal y fija**.

### Frecuencia

Todo sonido es una suma de senoidales (Fourier). Una **banda** es un rango de frecuencias.

### Nyquist y aliasing

```
fs > 2·f          frecuencia de Nyquist = fs/2
```

Lo que está arriba de `fs/2` no desaparece, se disfraza: `f_alias = fs − f` (para `fs/2 < f < fs`).
Con `fs = 16 kHz`, un tono de 10 kHz da las mismas muestras que uno de 6 kHz. **Es irreversible**, así
que el filtro anti-aliasing va antes del ADC (los convertidores de audio lo traen integrado).

La trampa real es **remuestrear en software sin filtrar** (diezmar): con fs = 16 kHz, el ruido de
rotor en 13–14 kHz caería en 2–3 kHz, dentro de la banda. Usar `scipy.signal.resample_poly`.

Un alias además rompe el notch: no cae en múltiplos de la BPF y se mueve al revés cuando suben las RPM.

**Por qué 16 kHz:** cubre 300–3000 Hz con margen para la banda de transición del filtro, es lo que
exige YAMNet y son pocos datos (32 KB/s por canal). (El micrófono interno y el Steren sólo graban a
48 kHz: se graba a 48 kHz y se remuestrea después.)

### Cuantización

Cada bit agrega ~6 dB: 16 bits ≈ 96 dB de **rango dinámico**. El **LSB** es el paso más pequeño; el
redondeo produce **ruido de cuantización**.

### dBFS

0 dBFS = escala completa (convención de las hojas de datos: una senoidal cuyo pico toca el máximo).
Todo lo demás es negativo. Las dos convenciones posibles difieren 3 dB: es un sesgo común.

### Las cifras de un micrófono digital

| | INMP441 | ICS-43434 |
|---|---|---|
| Sensibilidad (1 kHz, 94 dB SPL = 1 Pa) | −26 dBFS | −26 dBFS ±1 dB |
| AOP (saturación acústica, 10 % de THD) | 120 dB SPL | 120 dB SPL |
| SNR del micrófono (respecto a su ruido propio) | 61 dB(A) | 65 dB(A) |

Con −26 dBFS: `dB SPL = dBFS + 120`. Es la `k` de la sección 1, con número. La "SNR" de la hoja de
datos **no** es nuestra SNR: es 94 dB menos el ruido propio (33 dB(A) en el INMP441).

### Headroom y mapa de niveles

**Factor de cresta** = pico/RMS (senoidal 3 dB, ruido aleatorio ~12 dB). **Headroom** = distancia del
pico más fuerte a 0 dBFS. La saturación ocurre con los picos.

```
 dBFS   dB SPL
    0 ── 120    escala completa y AOP
  −18 ── 102    picos de los rotores (RMS + 12 dB)       ← headroom 18 dB
  −30 ──  90    rotores, RMS (estimado)                  ← 24 dB = SNR de la sección 1
  −54 ──  66    bocina en el micrófono
  −87 ──  33    ruido propio del micrófono
  −96 ──   —    piso de cuantización de 16 bits
```

Conclusiones: el lugar de montaje decide el headroom; ni el micrófono ni los bits son el cuello de
botella (lo son los rotores); 16 bits alcanzan; un MEMS no tiene perilla de ganancia que se pueda
configurar mal. Con ganancia ajustable: picos esperados cerca de −12 dBFS, y no volver a tocarla.

### Suma de niveles (fuentes incoherentes)

Los dB no se suman directo; se suman potencias:

```
L_total = 10·log10(10^(L1/10) + 10^(L2/10))
N fuentes iguales: L + 10·log10(N)      (+3 dB cada vez que se duplica el número)
```

| Diferencia entre fuentes | El total queda arriba de la más fuerte |
|---|---|
| 0 dB | +3 dB |
| 6 dB | +1 dB |
| 10 dB | +0.4 dB |
| 20 dB | +0.04 dB |

Fuentes **coherentes** (misma señal, sincronizada): se suman amplitudes (hasta +6 dB, o se cancelan).
El Δ de la sección 1 es esta misma suma.

Ejercicio resuelto: 4 motores de 84 dB → 90 dB (no 93). Uno a 94 dB y tres a 84 → 95.1 dB, con el 77 %
de la potencia de un solo motor. Montar el micrófono en el **centro** baja el ruido y además lo
estabiliza: ante una corrección de pitch (±5 % de RPM en motores opuestos), en el centro el ruido
cambia +0.16 dB; junto a un motor, ±0.9 dB. Menos sesgo diferencial entre cajas.

## Parte B: hardware y montaje

### El principio

> Entre la membrana y el archivo no debe haber nada que se adapte a lo que escucha.
> Guardar los datos crudos y procesar después, sobre una copia.

### Procesamiento a evitar

- **AGC**: lazo de control que iguala niveles.
- **Supresión de ruido** (sobre todo la estacionaria): borra lo que suena constante, incluida la
  bocina. (Confirmado con el Steren, ver 07_resultados_pruebas_reales.md.)
- **Beamforming adaptativo** (uno fijo, programado por nosotros, sí sirve: +10·log10(M) dB ideal).
- **AEC** (cancelación de eco) y **des-reverberación**. VAD y DOA no tocan el audio.
- **Compresión con pérdida** (MP3, AAC, Opus): descarta lo "enmascarado", y la bocina 24 dB debajo
  de los rotores es justo eso. Grabar en **WAV** (PCM) o **FLAC** (sin pérdida).
- **Celulares**: aplican todo lo anterior por omisión.

### ALSA, PipeWire y `arecord`

- **ALSA** habla con el hardware; **PipeWire** está en medio y tiene un volumen de captura que
  cualquiera puede mover.
- `hw:` entrega los datos tal cual y **falla** si pides algo que no soporta; `plughw:` **convierte en
  silencio**. Preferimos que falle.
- Con el ReSpeaker, `-c 1` por `plughw` grabaría el canal procesado: hay que grabar los 6 canales con
  `hw:` y usar los crudos (1 a 4).
- Usar el nombre de la tarjeta (`hw:CARD=...`) y no su número.

### Opciones de micrófono

- **USB / adaptador con solapa**: electret + preamplificador + ADC. Cable analógico: capta **EMI** de
  los ESC. Puede traer AGC.
- **ReSpeaker USB Mic Array v2.0** (XMOS XVF-3000): 4 MEMS de −26 dBFS, máx. 16 kHz y 16 bits;
  firmware de 6 canales: 0 procesado, 1–4 crudos, 5 reproducción. Los canales crudos hay que
  verificarlos midiendo. El XVF3800 tiene otro mapeo.
- **MEMS I2S** (INMP441 / ICS-43434): sensibilidad fija, digital desde el chip, pocos gramos. **I2S**
  usa BCLK, WS/LRCLK y SD; dos micrófonos por línea (pin L/R). En la Pi requiere un device tree overlay.

Regla: todo lo que se compare, y todo lo que se use para entrenar YAMNet, con el mismo modelo de
micrófono montado en el mismo lugar.

### Montaje mecánico

Tres caminos del ruido: sonido aéreo de los rotores; **ruido de flujo** (aire turbulento sobre la
membrana: la espuma sirve contra esto); **vibración estructural** (la espuma no sirve).

Aislamiento masa-resorte:

```
fn = (1/2π)·√(k/m)          T = 1 / |1 − (f/fn)²|   (sin amortiguamiento)
```

Aísla por arriba de `√2·fn`; en `fn` amplifica. Con `fn = 30 Hz`: −20 dB a 100 Hz (giro de los
motores) y −40 dB a 300 Hz (BPF). Un soporte con resonancia cerca de una frecuencia del motor es peor
que atornillarlo. El cable rígido salta el aislamiento: delgado, flexible y con holgura.

Posición: en el plano, el centro. En altura: arriba hay menos flujo (el aire entra lento; abajo sale
al doble de velocidad y turbulento), pero el frame tapa a la bocina. Las ondas rodean obstáculos más
chicos que su longitud de onda (`λ = c/f`: 1.14 m a 300 Hz, 11 cm a 3 kHz), así que arriba se pierden
agudos. Se decide midiendo.

## Parte C: registro y protocolo (implementado en el código)

No se dio como teoría aparte; quedó en las decisiones del banco volante:

- **Una grabación continua con tramos marcados** (graba todo, decide después).
- **Un solo reloj** (`time.monotonic()`) para audio, telemetría y tramos. El audio llega en bloques y
  siempre después de capturarse: el mejor estimador del instante de la muestra 0 es el **mínimo** de
  los retrasos, no el promedio. La latencia fija que queda es un sesgo común.
- **Metadata obligatoria** (`sesion.json`): micrófono, mezclador ALSA, altura, plan, versión del código.
- **Plan de ida y vuelta** (1-2-3-2-1 m): separa la distancia del tiempo (deriva de batería o
  temperatura) y mide la repetibilidad. No empezar en 0.5 m: 20 cm de error de posición son 2.9 dB.
- **Asentamiento**: se descartan los primeros segundos de cada hover.
- **Protocolo de banco**: ambiente con motores apagados al inicio y al final; alternar condiciones
  para no confundir el efecto con la deriva.
