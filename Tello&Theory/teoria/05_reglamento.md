# Reglamento: qué sonido se detecta y qué competencia sigue

Investigación del 6 de octubre de 2026, con los documentos oficiales.

## El sonido de la Misión 3 (TMR 2026 = IMAV 2025, interiores)

El TMR 2026 copió en inglés las misiones del IMAV 2025: dentro de una caja negra de 57 × 78 × 36 cm,
en un lugar aleatorio del piso, una bocina que apunta hacia arriba reproduce *"the sound of somebody
crying out for help"*, de al menos 70 dB medidos a 1 m arriba de la bocina. Hay que encontrar la caja
y soltar dentro un med-kit de 20 × 10 × 5 cm y 30 g.

- *Cry out* significa **gritar o clamar**, no llorar. El mismo rulebook habla de detectar personas
  *gritando* para pedir ayuda. Casi seguro es **un grito pidiendo ayuda**.
- **No se especifica**: el idioma ("¡ayuda!" o "help!"), si es una grabación fija, la voz, si suena
  continuo o en intervalos, si los 70 dB son con ponderación A, pico o promedio, ni si dan el archivo.
- Opciones del reglamento: renunciar a buscar y pedir la ubicación aproximada (sólo puntúa la
  entrega); hasta 5 cajas iguales, con la bocina del mismo color (puntos extra).
- Puntaje: caja encontrada 3, med-kit entregado 2. Multiplicadores: un dron con procesamiento a
  bordo ×1.5; enjambre con procesamiento en tierra ×2.0; enjambre a bordo ×3.0.
- Se permiten hasta 3 drones si cada uno pesa 300 g o menos (el Tello pesa ~80 g).

Consecuencias de diseño:

- Usar features que no dependan del idioma (energía en banda, modulación, persistencia) y entrenar
  YAMNet con varios candidatos grabados por el equipo: "¡ayuda!", "help!" y, por si acaso, llanto.
- Si el grito se repite con pausas, el hover sobre cada caja tiene que durar **al menos un ciclo
  completo**, y el criterio de persistencia debe buscar **repetición**, no energía constante. Eso
  también separa la bocina de un grito suelto del público.

El IMAV 2025 tenía además un **reto de vuelo silencioso**: el dron flota sobre un micrófono en el piso
y se califica su nivel, corregido por la distancia con `20·log10(D)` (la ley inversa del cuadrado).

## Calendario y reglamento siguiente

- El **TMR 2026 ya se realizó** (Puebla; la UDLAP publicó su segundo lugar en Drones Autónomos el
  4 de mayo de 2026).
- El **TMR 2027 será del 3 al 6 de marzo de 2027, en Zacatecas** (Palacio de Convenciones).
- El reglamento del TMR 2027 aún no se publica, y la base puede cambiar: la primera versión del TMR
  2026 (noviembre de 2025) se basaba en el IMAV 2026 (arena de 8 × 8 m, sin sonido); la de enero de
  2026 pasó al IMAV 2025 (con sonido).
- El **IMAV 2026** (Estrasburgo, septiembre de 2026) no tiene misión acústica en interiores: pista de
  obstáculos, contar muñecas en un cuarto oscuro, soltar un cono en la caja con un **punto caliente**
  (50–80 °C, entre 3 cajas, con un LED rojo que parpadea sobre la caja detectada) e inspección de un
  aerogenerador. En exteriores hay un dispositivo de alarma de 2.6–3.0 kHz, 95 dB a 3 m.

## Si cambian la misión del sonido por la del punto caliente

Se conserva casi todo: plataforma, posicionamiento, autonomía, visión de las cajas, mecanismo de
entrega (cono de 7 g en lugar de med-kit), infraestructura de sesiones, sincronización y simulador, y
el método de comparar candidatos. Se pierde la cadena acústica (micrófono, montaje, filtros, YAMNet);
se agrega un sensor térmico (por ejemplo, un arreglo de 32 × 24 píxeles), la detección de la mancha
caliente y el LED.

El térmico es mucho más fácil: contraste de 25 a 55 °C contra décimas de grado de resolución (SNR
muy positiva) y una imagen que dice dónde está el punto caliente. Lo nuevo sería la **dilución por
píxel** (a 2 m, ~6 cm por píxel con 55° de campo) y sesgos como el aire de las hélices enfriando la
superficie.

Recomendación: seguir el orden del documento (audio al final), no comprar hardware acústico caro hasta
que salga el reglamento y tratar la cadena acústica como una apuesta hasta entonces.

## Fuentes

- Reglamento TMR 2026, Drones Autónomos (enero de 2026):
  https://femexrobotica.org/tmr2026/wp-content/uploads/2026/01/Reglas_DronesAutonomos_2026-1.pdf
- Primera versión (noviembre de 2025):
  https://femexrobotica.org/tmr2026/wp-content/uploads/2025/11/Drones-Autonomos-2026-2.pdf
- Rulebook IMAV 2025: https://femexrobotica.org/imav2025/wp-content/uploads/2025/11/RuleBook_IMAV2025.pdf
- Rulebook IMAV 2026 v5: https://2026.imavs.org/wp-content/uploads/2026/09/Rulebook_IMAV2026_v5.pdf
- UDLAP en el TMR 2026: https://oronoticiaspuebla.com/udlap-destaca-en-torneo-mexicano-de-robotica-2026/
- TMR 2027 en Zacatecas: https://turismo.zacatecas.gob.mx/sera-zacatecas-sede-del-torneo-mexicano-de-robotica-2027/
- Contacto del reglamento TMR 2026: Dra. Leticia Oyuki Rojas Pérez (el correo del PDF termina en
  "@gmaill.com" y parece un error de dedo: confirmarlo en la página oficial).
