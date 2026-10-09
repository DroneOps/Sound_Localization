# Pendientes

## El Tello, antes de volver a volar

1. Revisión física: hélices A/B en su lugar y sin daños, que giren libres (sin pelos en los ejes),
   protectores sin rozar, batería bien asentada.
2. Calibrar la IMU con la app oficial, sobre una superficie plana.
3. Piso con textura y buena luz bajo la ruta.
4. Volar con la app oficial: si obedece, probar el modo manual; si no, es el dron.

## Mediciones

- Repetir la prueba del micrófono interno en un salón silencioso.
- Medir si el ISD1820 llega a 70 dB a 1 m.
- Con el dron del TMR volando: espectro del ruido (¿cuánto cae en la banda?, ¿cuánto es tonal?), SNR en
  banda con la bocina y variabilidad entre cajas vacías. Eso decide si el notch del audio vale la pena.

## Organización del TMR

- ¿El TMR 2027 conserva las misiones del IMAV 2025 o pasa al IMAV 2026? ¿Cuándo sale el reglamento?
- Si se queda el sonido: idioma, grabación, continuo o en intervalos, dB(A) o sin ponderar, pico o
  promedio, si comparten el archivo.
- Material del piso y luz de la arena; ¿se permite aterrizar a mitad de misión o poner micrófonos en el piso?

## Teoría que falta

- 2.3 STFT (ventanas, compromiso tiempo-frecuencia).
- 2.4 Welch (cuánto baja la varianza al promediar; cuánto tiempo sobre cada caja).
- 2.5 El estadístico de decisión y la prueba de hipótesis.
- 2.6 La variabilidad nula (el experimento que decide si el método sirve).
- 3. Features: contraste espectral, notch dirigido, espectro de modulación, coherencia entre canales.
- 4. Arquitectura y 5. validación con señales sintéticas.

## Git

Hecho el 9 de octubre: todo el trabajo (banco volante, filtro de banda, notch y esta documentación)
está en `main`, y la rama `banco-volante` se borró.
