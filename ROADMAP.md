# Roadmap de CorridorKey para Nuke

Estado al 2026-11-13. Versión en el repo: **0.8.0**, probada en GUI con shots reales (la 0.6 nunca se repartió). Última versión repartida (ZIP): 0.5.1; la 0.8.0 está en Releases.

## Hecho

| Versión | Qué trajo |
|---|---|
| 0.1 | Instalador de doble clic (uv, Python 3.12 propio, torch con CUDA, modelos) y menú en Nuke con un panel. |
| 0.2 | El panel pasa a ser un nodo Group con entradas `clip` y `hint`. Reutiliza la conversión si nada cambió aguas arriba. |
| 0.3 | Carpeta de salida, nombre y versión definidos por el usuario (`2_prerenders` automático). Temporales siempre en la PC. Opción 720p. |
| 0.4 | El modelo entrega solo alpha y fg; el cutout y el despill se calculan en vivo. Vista straight. Nombre prellenado. |
| 0.5 | Chequeo de disco, pantalla verde o azul, ventana temporal. Rango que sigue al clip. |
| 0.6 | Panel en secciones, casilla "Usar hint", hint solo en el primer frame, calidad interna del hint, hint sin arrastre, memoria baja manual, "Original en zonas sólidas". |
| 0.7 | Panel con el diseño de SHARP Splat y flujo en 3 pasos; la carpeta de salida muestra la ruta automática (también con el script sin guardar). "Plate original en el interior" marcada por defecto. El aviso de GPU ocupada lista los procesos. Poca VRAM: ventana según la tabla de CorridorKey para cada tarjeta, ventanas 2 y 4, reintento automático si falta memoria, memoria Auto / Baja / Mínima. |
| 0.7.1 | Suavidad del borde en "plate original en el interior". Layers `ck_fg` y `ck_fg_raw` para sacar con un Shuffle. Arregla "Missing input channel" en los nodos que aún no tienen resultado. |
| 0.8.0 | Cola de procesado: Procesar seleccionados sin bloquear Nuke, un shot tras otro en segundo plano; sigue aunque se cierre Nuke y publica al reabrir. Cancelar cola. Hint en un frame de referencia. Panel de la cola. El estado da el tiempo en minutos; sección "ajustes de color" y "color croma". |

## Para cerrar la 0.7.0

- [x] `tests\nuke_node_test.py` en Nuke 17.0v4 headless con `CK_TEST_FAKE=1` (2026-11-11: pasa, incluido el bloque de la 0.6).
- [x] Mejoras de la revisión del 2026-11-11: los temporales ya no dependen del número de versión del script y se purgan a los 14 días sin uso; se verifica que salieron todos los frames antes de publicar; se detecta el proceso muerto; la huella de los Read mira el primer y el último frame.
- [x] Probar el nodo en la GUI de Nuke (2026-11-11: el panel en 3 pasos y el hint funcionan bien).
- [x] Ajustes tras la prueba en GUI: controles del hint juntos en "1 · entrada"; con el script sin guardar, la salida va a la `2_prerenders` de Comp del shot del clip; el aviso de GPU ocupada dice qué procesos la ocupan; "plate original en el interior" con ayuda nueva y marcada por defecto.
- [x] Probado en GUI (2026-11-11, "todo funciona"): plate original en el interior, carpeta de salida con el script sin guardar, "Solo el primer frame", memoria y ventanas 2 y 4.
- [x] Créditos y licencia en el README; `LICENSE` de CorridorKey 2.0 en el repo.
- [x] Commit, push y ZIP 0.7.0.

## 0.8: cola de procesado

Pedida el 2026-11-12. Varios shots en un script, cada uno con su nodo CorridorKey, procesados en una sola tanda y sin bloquear Nuke.

- [x] Medir cuánto tarda `load_model` (2026-11-12, RTX 4070 Ti, caché de disco caliente): imports 1,4 s + `load_model` 8,5–9,4 s ≈ 10 s por proceso, 2,3 GB de VRAM. Un shot de 128 frames en HD tarda ~200 s: cargar el modelo es ~5 %. Decisión: no cargarlo una sola vez; un proceso de `infer.py` por shot, como hoy.
- [x] Menú **CorridorKey > Procesar seleccionados**: Nuke convierte el plate y el hint de cada nodo (reutiliza la conversión si nada cambió) y lanza un solo proceso en segundo plano. Y **Cancelar cola**.
- [x] `cola.py`, sin tocar CorridorKey: corre `infer.py` shot por shot con los mismos argumentos que hoy (`core.build_argv`). Un log y un estado por shot (`trabajo.json` y `estado.json` en la carpeta de trabajo del nodo) y reintento por memoria por shot. Una cola a la vez en la GPU (`cola.lock`); si hay otra corriendo, espera su turno.
- [x] El botón ▶ Procesar pasa por la misma cola, pero espera con la barra de progreso. Así el reintento por memoria vive en un solo lugar.
- [x] En Nuke, un temporizador (QTimer, cada 2 s) muestra en el panel y bajo el nombre del nodo si está en cola o procesando, y al terminar publica los EXR y conecta el resultado como antes. Se apaga solo cuando no queda nada pendiente.
- [x] Si se cierra Nuke a mitad, el proceso sigue; al reabrir el script (`onScriptLoad`), el nodo recoge lo que terminó o sigue mostrando el avance.
- [x] Un nodo en cola no se puede reprocesar ni borrar sus temporales. Si su proceso murió (PC reiniciado), se marca como cortado y se puede volver a procesar.
- [x] Pruebas (2026-11-12): `test_core` 36 OK (4 de la cola); `nuke_node_test` con `CK_TEST_FAKE=1` en 15.1v6, 17.0v4 y 17.1v2 (26 verificaciones, incluida la cola); prueba real con GPU en headless (dos shots en serie, 24 s y 23 s); y en la GUI de 17.1v2 y 15.1v6: el temporizador publica solo, cerrar Nuke con la cola corriendo y reabrir publica lo pendiente, y el botón Procesar con barra.
- [x] Prueba en GUI con shots reales (2026-11-13).
- [x] Pantalla azul (probado el 2026-11-12 en un shot con ventanas azules detrás de un set, 128 frames en HD, sin hint): el modelo separa bien el azul (alpha 0,001 en la pantalla, pelo limpio) en ACEScg, con una matriz azul→verde, con el swap G/B y sin `--frame_dir_linear`. El problema es otro: sin hint elige a las personas como sujeto y recorta también el set (alpha 0,70–0,77 en el set; con la matriz 0,94, pero ensucia la pantalla). Con el hint de un keyer azul simple el set queda entero (0,998), la pantalla sigue en 0 y el borde lo rehace el modelo. No se integra la matriz; el README explica el hint para pantallas detrás de un set. Una prueba anterior en otro plate (ventanas azules tenues) dio alpha gris porque el hint era gris en la pantalla.
- [x] Hint en un frame de referencia (pedido el 2026-11-12). El plugin de pago lo tiene ("Reference Frame", propaga hacia adelante y hacia atrás). El CLI no: solo `--hint_first_frame`. Se imita con dos tramos desde ese frame (`core.split_at`: carpetas de enlaces a los EXR ya convertidos, una hacia adelante y otra invertida), que `cola.py` corre en serie y junta en el orden del clip (`core.merge_tramos`). Con el frame de referencia en el primer frame es lo mismo que "Solo el primer frame"; en el último, un solo tramo hacia atrás. Pruebas: `test_core` 37 OK; `nuke_node_test` con FAKE en 17.1v2 pasa entero con un plate plano (cada frame sale del tramo correcto). Ojo: las verificaciones de "plate original en el interior" comparan el mismo píxel del resultado y del clip, y fallan con un plate con textura (un plate 4K real o ruido); falta ver si es solo la prueba o un desplazamiento real. Corrida real (2026-11-13, 84 frames 4K nativo, referencia 1051, 7 min 53 s): el cambio de alpha en los bordes entre 1050→1051 es el 2º mayor del clip (0,0181 contra una mediana de 0,0068) y 1051→1052 el 6º; en el mismo shot con hint en todos los frames ese par es normal. El salto rodea al frame con hint por los dos lados, así que parece que ese frame resalta frente a sus vecinos más que la unión en sí. Visto en Nuke (2026-11-13): poco notorio, pero está. Medido sobre esa corrida: el "exceso" de 1051 (d(1050,1051) + d(1051,1052) − d(1050,1052), en bordes) es 0,0206, el mayor del clip y 3,4 veces el p95; en cambio d(1050,1052) = 0,0138 es normal. O sea, los dos tramos calzan entre sí y el que se sale es el frame con hint: en el motor (`runtime.hann_stage1_stream`) solo ese frame recibe el hint y el resto de la ventana se propaga. Arreglo ("relevo"): el tramo hacia atrás parte en ref+1 y su hint es el alpha que el tramo hacia adelante dio ahí (`core.hint_relevo`, calidad 0,95 como el arrastre entre ventanas); `merge_tramos` descarta de cada tramo su frame con hint, así ningún frame del resultado es un frame con hint. Cuesta un frame más. `test_core` 39 OK; `nuke_node_test` actualizado pero sin correr. Corrida real con el relevo (2026-11-13, mismo shot, 8 min 44 s): el frame con hint ya no resalta (exceso de 1051 = 0,0046, dentro del p95 de 0,0048), pero queda un escalón en la unión 1051→1052 (0,0166 contra una mediana de 0,0063) y la primera ventana del tramo hacia adelante sigue inquieta (1052–1058: 0,0082–0,0180; con hint en todos los frames esa zona da 0,0054–0,0097). Visto en Nuke: funciona, pero la imagen cambia mucho alrededor de la unión; la propagación entre frames deja fantasmas, y el hint en todos los frames da mejor resultado. Conclusión de la prueba: la opción funciona y queda en el nodo, sin más trabajo por ahora; en este shot no rinde más que el hint en todos los frames. Falta probarla en otro tipo de plano antes de recomendarla.
- [x] Panel "Cola de CorridorKey" (pedido el 2026-11-13): `panel.py`, menú CorridorKey > Ver cola y Windows > Custom. Lee las carpetas de trabajo de todos los scripts (`core.queue_rows`: procesando, en cola por orden de llegada y terminados de las últimas 24 h); por fila, ir al nodo (solo si está en el script abierto), log y cancelar ese shot (`core.cancel_job`: cola.py anota el PID de infer.py en `infer.pid`; la cola no pisa el estado cancelado y sigue con el siguiente). Pruebas: `test_core` 39 OK; el widget en Nuke 17.1v2 con `--tg` y Qt offscreen; `nuke_node_test` FAKE pasa. Falta verlo en la GUI.
- [ ] Idea: con pantalla Azul o Verde y sin hint conectado, que el nodo genere solo un hint de keyer (0 en la pantalla, 1 en el resto, con blur). Arreglaría los shots de set con ventanas sin pedirle nada al artista.

## Poca VRAM, fase 2 (medir en GPU antes de decidir)

- [ ] Medir los valores de memoria "Mínima" (hoy provisorios: la mitad de "Baja").
- [ ] PR #9 del repo original (pesos en bf16, sin fusionar): el autor mide de 6,19 a 3,20 GiB de pico a 720p con ventana 8 y salida idéntica. Aplicarlo como parche del instalador solo si la salida sale idéntica aquí.
- [ ] Probar en una tarjeta de 6 u 8 GB real: nada de la 0.7 se ha corrido en una.
- [ ] Cuando el repo original fusione el PR #18 (`--optimized`, hasta 3x más rápido), subir el commit fijo del instalador.

## Sin probar

- [ ] Prueba con colegas, en curso: dos reportaron la 0.5.1 instalada y funcionando sin problemas. Falta el resto.
- [ ] Un script con un config OCIO distinto de aces_1.2.
- [ ] Velocidad y calidad a 720p.
- [ ] El detalle de procesos del aviso de GPU en un Windows que no esté en inglés (si falla, el aviso sale sin la lista).
- [ ] Usuarios de Windows con acentos o espacios en el nombre (rutas del log y de los temporales).

## Decisiones abiertas

- [ ] ¿Un EXR de cutout bajo demanda? Desde la 0.4 solo se guardan alpha y fg crudos.
- [ ] Híbrido 4K: fg del proceso HD solo en una banda de borde (~20 px) sobre el plate 4K. Prototipo medido, sin integrar.

## Ideas aparcadas

- Color de despill automático.
- EXR en 32 bit float (`--exr_dtype`) y `--stage2_batch` para GPUs grandes.
- Umbral ajustable en "plate original en el interior" (la suavidad ya está desde la 0.7.1).

## Última prioridad

- [ ] Probar en Nuke 15.1.
