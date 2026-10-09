# Tello & Theory: subsistema acústico (TMR, Misión 3)

Trabajo realizado entre el 25 de septiembre y el 9 de octubre de 2026: la teoría del
subsistema acústico, el banco volante con el Tello y las primeras pruebas con hardware real.

## Contenido

```
teoria/      notas, en el orden en que se vieron
figuras/     gráficas de la teoría y de las pruebas reales
datos/       las sesiones grabadas con el Tello y los micrófonos (sin el audio, ver abajo)
documentos/  el documento de contexto del proyecto y el reglamento del TMR 2026
```

El código está en la raíz del repositorio (`soundloc/` y `tests/`).

### Teoría (leer en orden)

| Archivo | Tema |
|---|---|
| `00_revision_del_proyecto.md` | Opinión del proyecto, riesgos, el filtro de Euler, cómo presentar avances |
| `01_planteamiento.md` | Sección 1: decibeles, SNR, detección contra comparación, sesgo y varianza |
| `02_adquisicion.md` | Sección 2.1: Nyquist, dBFS, headroom, suma de niveles, hardware, montaje, protocolo |
| `03_filtro_de_banda.md` | Sección 2.2: el pasa-banda de voz |
| `04_notch.md` | El notch, con los datos reales del Tello |
| `05_reglamento.md` | Qué sonido se detecta, TMR 2027, IMAV 2026 y el punto caliente |
| `06_hardware.md` | Micrófonos, ISD1820 y lo aprendido del Tello |
| `07_resultados_pruebas_reales.md` | Las pruebas del 6 de octubre y los defectos que encontraron |
| `glosario.md` | Todas las definiciones para la libreta |
| `pendientes.md` | Lo que sigue |

### Código

Desde la raíz del repositorio, con el entorno de Python de `Sound_Localization/.venv`:

```bash
cd ~/Sound_Localization
.venv/bin/python -m pytest
.venv/bin/python -m soundloc.devices            # micrófonos conectados
.venv/bin/python -m soundloc.mic_test --device hw:CARD=PCH,DEV=0 --rate 48000 --channels 2
.venv/bin/python -m soundloc.bench_flight --simulate
.venv/bin/python -m soundloc.manual_flight --simulate --cmd-port 18889 --state-port 18890
```

Las sesiones nuevas se guardan en `sessions/`, que no se sube al repositorio. El `README.md` de la
raíz explica todos los módulos.

### Datos

Las grabaciones reales con el Tello y los micrófonos están en `datos/`. El repositorio sólo guarda su
metadata, tramos, telemetría y gráficas: los `.wav` (unos 88 MB) quedan fuera por el `.gitignore` y
sólo existen en la copia local.

| Carpeta | Qué es |
|---|---|
| `20261006-215929_prueba_microfono` | Steren, lejos y con volumen bajo (no concluyente) |
| `20261006-220139_prueba_microfono` | Micrófono interno al 50 % de volumen (no concluyente) |
| `20261006-220548_prueba_microfono` | Micrófono interno al 100 %: casi lineal |
| `20261006-220713_prueba_microfono` | Steren a 30 cm: no apto (borra los tonos constantes) |
| `20261006-222601_banco_volante` | Vuelo 3: 3.7 s de hover a 1 m (rescatados antes de que aterrizara solo) |
| `20261006-223749_banco_volante` | Vuelo 4: 7 s de hover a 1 m, la mejor medición |
| `20261006-232338_vuelo_manual` | Vuelo manual de 76.7 s, sin hovers marcados |
| `20261006-232812_vuelo_manual` | Vuelo manual completo |

Para volver a analizar una desde la raíz (necesita el `.wav`, así que sólo funciona en la copia local):

```bash
.venv/bin/python -m soundloc.analyze_flight "Tello&Theory/datos/20261006-223749_banco_volante"
.venv/bin/python -m soundloc.mic_test --analyze "Tello&Theory/datos/20261006-220713_prueba_microfono"
```

### Documentos

- `documentos/Proyecto_Dron_TMR2026_Contexto.pdf`: el documento de contexto con el que empezó el trabajo.
- `documentos/reglamentos/Reglas_DronesAutonomos_TMR2026_enero2026.pdf`: el reglamento oficial.
- Los otros reglamentos consultados (TMR 2026 de noviembre de 2025, IMAV 2025 e IMAV 2026) tienen sus
  enlaces en `teoria/05_reglamento.md`.
