# Roadmap de CorridorKey para Nuke

Estado al 2026-11-12. Versión en el repo: **0.7.1** (la 0.6 nunca se repartió). Última versión repartida (ZIP): 0.5.1.

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

- [ ] Medir cuánto tarda `load_model` (no está en los logs): decide cuánto pesa cargar el modelo una sola vez frente a no bloquear Nuke.
- [ ] Menú **CorridorKey > Procesar seleccionados**: Nuke convierte el plate y el hint de cada nodo (reutiliza la conversión si nada cambió) y lanza un solo proceso en segundo plano.
- [ ] Script de cola nuestro, sin tocar CorridorKey: importa su `infer.py`, carga el modelo una vez y llama a `run_inference` por shot con los mismos argumentos que hoy (`core.build_argv`). Un log y un estado por shot, y reintento por memoria por shot.
- [ ] En Nuke, un temporizador revisa el estado: cada nodo muestra en cola, procesando o listo, y al terminar un shot se publican sus EXR y se conecta el resultado como hoy.
- [ ] Si se cierra Nuke a mitad, el proceso sigue; al reabrir el script, el nodo recoge lo que terminó.
- [ ] Probar en Nuke 15.1 (el temporizador usa Qt).
- [ ] Pantalla azul: sin buenos resultados (2026-11-12, 4K nativo con hint); el repo de CorridorKey solo habla de verde. Probar el truco de intercambiar verde y azul antes del nodo y deshacerlo después (despill en Verde). Si funciona, que el nodo lo haga por dentro con pantalla Azul; si no, avisar en el README que azul no se recomienda.

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

- Hint con un frame de referencia arbitrario (el CLI solo documenta el primer frame).
- Color de despill automático.
- EXR en 32 bit float (`--exr_dtype`) y `--stage2_batch` para GPUs grandes.
- Umbral ajustable en "plate original en el interior" (la suavidad ya está desde la 0.7.1).

## Última prioridad

- [ ] Probar en Nuke 15.1.
