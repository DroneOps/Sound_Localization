# 0. Revisión del proyecto y decisiones iniciales

Primera revisión del documento *Proyecto_Dron_TMR2026_Contexto.pdf* (25 de septiembre de 2026).

## Veredicto

El orden de trabajo del documento es el correcto: dron estable → posicionamiento en interiores →
enlace Raspberry Pi–controladora → Guided desde código → visión → audio. El audio es la última
capa y depende de todo lo anterior.

Lo mejor pensado del documento:

- **La búsqueda diferencial acústica**: en lugar de estimar la dirección del sonido bajo el ruido
  de los rotores, comparar posiciones en las mismas condiciones.
- **La regla de probar todo primero en SITL**, con piloto listo en el radio.
- **Usar los embeddings de YAMNet** para entrenar un clasificador propio con grabaciones del
  equipo, en lugar de entrenar desde cero.

## Riesgos, en orden

1. **El rumbo (yaw) en interiores.** El flujo óptico da velocidad, no orientación, y la brújula en
   interiores no es confiable (varillas del concreto, estructura metálica, corrientes de los
   motores). La deriva de yaw es una causa clásica de choques en arenas cerradas.
2. **El flujo óptico depende del piso.** Sobre un piso liso, brillante o de un solo color, el sensor
   no ve nada. Hay que preguntar a la organización el material del piso y la iluminación. La VIO
   propia en la Pi no es una alternativa rápida: es un proyecto completo. (El 6 de octubre el Tello
   lo mostró en vivo: deriva y `No valid imu`.)
3. **Presupuesto de peso y autonomía.** Pi 5 + BEC + cámara + micrófonos + med-kit, bajo 60 cm.
   Falta el cálculo de empuje/peso ≥ 2:1 y de minutos de vuelo útiles.
4. **El supuesto de "ruido propio constante" es frágil.** Al pasar sobre una caja cambian la
   distancia al suelo, el efecto suelo y las reflexiones. Refuerzos: coherencia entre canales,
   estructura temporal (modulación) del sonido, y la pregunta de si se puede aterrizar a mitad
   de misión para escuchar con los motores apagados.
5. **Definir la corrida mínima que da puntos**: despegue autónomo, ir a la ubicación que da la
   organización, soltar el med-kit, aterrizar, paro de emergencia demostrado.
6. **El micrófono necesita aislamiento mecánico**, no solo espuma antiviento.
7. **La entrega con ±20 cm** necesita cerrar el lazo con la cámara (servo visual), no la posición
   del EKF.
8. **El paro de emergencia va en la etapa 1**: sin él no se compite.

Faltaba en el documento: fechas y personas por etapa.

## El "filtro discreto de Euler" (propuesta de un compañero)

Se refería a un **filtro paso-bajas de un polo discretizado por Euler**:

```
y[n] = y[n−1] + α · (x[n] − y[n−1])
```

- Usar la forma estable `α = dt / (dt + 1/(2π·fc))` (la de `LowPassFilterFloat` de ArduPilot):
  α nunca pasa de 1. La forma ingenua `α = 2π·fc·dt` se vuelve **inestable** si `fc·dt > 1/(2π)`.
- **Sí sirve** para señales lentas: envolvente de energía, telémetro, centroide de una detección.
  Ahí `fc` es de 0.1–1 Hz contra decenas de Hz de muestreo, el régimen donde Euler es preciso.
- **No sirve** para la banda de audio (300–3000 Hz a 16 kHz): Euler desplaza las frecuencias de
  corte (regla práctica: sólo si `fc < fs/20`) y un polo no da la selectividad necesaria. Para eso
  va un Butterworth en secciones de segundo orden (ver 03_filtro_de_banda.md).
- Todo filtro causal introduce retardo (≈ la constante de tiempo): en un lazo de control, filtrar
  de más causa oscilación.
- Otras interpretaciones descartadas: complementario sobre ángulos de Euler (EKF3 ya lo hace mejor)
  e integrar la aceleración para posición (la deriva crece con el cuadrado del tiempo).

## Cómo presentar los avances al grupo

No contar lo aprendido, sino lo decidido gracias a ello:

1. Qué se hizo, en una línea.
2. El hallazgo principal (un número que cambia el plan; por ejemplo, los 0.017 dB de la sección 1).
3. Decisiones tomadas (formato de grabación, micrófono, montaje, filtros).
4. Riesgos para el resto del equipo, planteados como preguntas.
5. Preguntas para la organización.
6. Siguiente paso, fecha y lo que se necesita del grupo.

Decir siempre qué números son estimados y no prometer que el método funcionará antes de medirlo.
