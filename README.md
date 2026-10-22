# CorridorKey para Nuke

Nodo de Nuke para keyear croma verde o azul con **CorridorKey 2.0** (el keyer neuronal de Corridor Digital), local en tu GPU.
Este paquete no incluye CorridorKey ni sus modelos: el instalador los descarga desde sus fuentes oficiales en cada PC.

## Requisitos

- Windows 10/11 y una GPU **NVIDIA RTX serie 30 o más nueva** con el driver 570 o superior (mínimo 4 GB de VRAM; 12 GB o más es lo cómodo).
- Nuke 15.1 o 17 (Python estándar, sin compilar nada).
- Unos 15 GB libres y conexión a internet durante la instalación.

## Instalar (o actualizar)

1. Copia esta carpeta a tu PC (o ábrela desde la carpeta compartida).
2. Doble clic en **instalar.bat**. La primera vez tarda entre 5 y 30 minutos según tu conexión. Si Windows pregunta, elige "Más información" y "Ejecutar de todos modos".
3. Reinicia Nuke. Aparece el menú **CorridorKey** en la barra superior.

Para **actualizar** a una versión nueva del paquete, vuelve a ejecutar `instalar.bat`: reutiliza lo ya descargado y solo cambia lo necesario.

El instalador deja todo en `%LOCALAPPDATA%\CorridorKey` (Python propio, no toca el tuyo) y agrega un bloque a `~\.nuke\menu.py`
(con copia de seguridad `menu.py.bak_corridorkey`). Si tu estudio usa otra carpeta de Nuke:
`instalar.bat -NukeDir D:\ruta\.nuke`.

## Usar

1. Crea el nodo: **CorridorKey > Crear nodo CorridorKey**, o con Tab escribiendo `CorridorKey`. Si tenías un nodo seleccionado, queda conectado a la entrada **clip**.
2. Conecta el **clip** (el plate de croma) a la entrada `clip` y, si tienes un matte del sujeto, conéctalo a la entrada `hint` (opcional; se usa su alpha).
3. En las propiedades del nodo elige la resolución y pulsa **Procesar**. Hay barra de progreso y botón Cancelar. **Primer y Último frame** toman el rango del clip conectado; si los cambias a mano se respetan, y el botón **Rango del clip** los vuelve a tomar del clip. Lo que está bajo **Post proceso** (pantalla, despill, fuerza, ver) es en vivo y no vuelve a procesar.
4. El nodo entrega el **cutout** (RGBA premultiplicado) a la resolución del clip. El desplegable **Ver** cambia entre cutout, alpha, fg, fg + alpha (straight) y el clip original sin volver a procesar.
5. Los EXR del resultado (alpha y fg) quedan en la **carpeta de salida** (ver abajo), listos para subir con el resto de tus prerenders.

### Despill en vivo y salida straight

El modelo entrega el **alpha** y el **fg** (el color del sujeto sin la mezcla con la pantalla en los bordes). El **despill** no lo hace el modelo: es una regla fija que se aplica después. Por eso aquí es un paso **en vivo** dentro del nodo, sobre el fg: lo cambias y se ve al instante, sin Procesar.

- **Pantalla**: verde o azul (el canal que baja el despill).
- **Despill**: *Average (CorridorKey)* es exactamente la regla de CorridorKey (baja el verde que supera el promedio de rojo y azul y reparte la mitad a cada uno); *Máximo (suave)* solo baja el verde que supera al mayor de los dos, así respeta amarillos y tonos cálidos (corrige menos que Average); *Ninguno* deja el fg crudo. **Fuerza** va de 0 a 1 (CorridorKey usa 0,5 por defecto, que corrige solo la mitad del exceso).
- Si el fg del modelo ya viene limpio, mover el despill casi no cambia nada: es normal (en una toma de prueba, a fuerza 1 Average cambiaba ~1 % de los píxeles).
- **Ver > cutout** = el fg con ese despill, premultiplicado por el alpha.
- **Ver > fg + alpha (straight)** = el fg crudo con el alpha en el canal alpha, **sin premultiplicar**. Sirve para despillar con tu propio nodo (DespillMadness u otro): conéctalo a esta vista, pon **Despill = Ninguno** si no quieres doble despill, y haz el **Premult** después.

### HD interno: no pongas un Reformat

Con **Resolución = HD (recomendado)** el nodo reduce el clip a 1920 px de ancho **por dentro** y devuelve el resultado al tamaño original del clip.
**No hace falta poner un Reformat antes**: conecta el clip tal cual (4K, por ejemplo). Si lo reduces tú antes, el resultado saldrá a ese tamaño reducido.
En pruebas con un plano 4K, el key calculado en HD y subido a 4K difirió del 4K nativo en el 0,13 % de los píxeles, casi todos en los bordes de los dedos, y fue unas 4 veces más rápido.
Usa **Nativa** solo si necesitas el máximo detalle de borde (pelo fino, motion blur); en una GPU de 12 GB conviene entonces conectar un hint.

**Ventana temporal**: cuántos frames mira el modelo a la vez. Más frames = key más estable en el tiempo y mejor borde, pero más memoria de GPU (en las pruebas pesó más que la resolución). *Auto* (recomendado) deja que CorridorKey elija según la memoria libre; *Frame a frame* es lo más liviano pero puede parpadear; 8 a 80 fija la ventana. En GPUs de 16 GB o menos una ventana fija usa siempre el modo de memoria baja, y si supera lo recomendado (12 GB: 720p 80, HD 24, 4K 8) el nodo pide confirmación: en un PC de 12 GB, una ventana de 24 en 4K lo colgó.

Antes de convertir, el nodo **revisa el espacio en disco** (temporales y carpeta de salida) y, si no alcanza, avisa sin empezar.

**720p (liviano)** reduce a 1280 px de ancho, también por dentro del nodo. Es para equipos con poca memoria de GPU o para una prueba rápida: va más rápido y gasta menos memoria, con menos detalle en los bordes. Un clip que ya es más chico que el ancho elegido no se agranda.

### Dónde quedan los archivos

**El resultado (lo que subes)** va a la **Carpeta de salida** del nodo, con la convención de `2_prerenders`:

```
<carpeta de salida>\<nombre>_alpha_v01\<nombre>_alpha_v01.1001.exr
<carpeta de salida>\<nombre>_fg_v01\<nombre>_fg_v01.1001.exr
```

Son el alpha y el fg **crudos, sin despill**; el cutout se calcula en vivo dentro del nodo y no se guarda en disco. El nodo guardado en el script lee estos archivos.

- **Carpeta de salida vacía = automática**: la carpeta `2_prerenders` que está junto a `1_projects`, subiendo desde donde guardaste el script (`...\SHOW_101_0500\Comp\1_projects\x.nk` guarda en `...\Comp\2_prerenders`). Si el script no está en esa estructura (o no está guardado), usa `%LOCALAPPDATA%\CorridorKey\salida`. Puedes escribir otra carpeta.
- **Nombre**: aparece escrito el nombre automático, el del clip (sin número de frame) + `_ck`, por ejemplo `SHOW_101_1200_aPlate_v001_ck`, para que lo retoques. Si lo cambias a mano se respeta; si lo borras, vuelve a ser automático y sigue al clip.
- Los archivos llevan el **número de frame real** del shot (1001…) y son **HD** si elegiste HD (el nodo los reescala al tamaño del clip solo dentro de Nuke).
- **Versión**: Procesar **reemplaza** los archivos de esa versión, así no se acumula espacio. Para conservar lo anterior, sube el número de **Versión** antes de procesar: se crea `..._v02` y la `v01` queda intacta.
- Si otro Read de tu script tiene abierta la secuencia que se va a reemplazar, Windows no deja pisarla: el nodo te avisa, deja la versión como estaba y no mezcla frames. Sube la versión o desactiva ese Read.

**Los temporales (no se suben)** viven en tu PC, en `%LOCALAPPDATA%\CorridorKey\runs\`, nunca junto al shot:

- El clip (y el hint) se convierten una vez. Si no cambió nada de lo que alimenta al nodo, **reutiliza la conversión**: cambiar la calidad del hint o lo que ves no reconvierte (el despill ni siquiera corre el modelo: es en vivo). Si cambias algo aguas arriba (un Grade, el Read, el rango), lo detecta y reconvierte.
- **Borrar temp.** (en el nodo) quita el clip y el hint convertidos y no toca la carpeta de salida. **CorridorKey > Limpiar carpetas de nodos borrados** quita los temporales de nodos que ya no están en el script.

## Consejos

- **Cierra ComfyUI y otras apps que usen la GPU** antes de correr: CorridorKey elige el tamaño de sus ventanas temporales según la VRAM libre.
- Calidad del hint: `0.95` para un matte de artista, `0.75` para uno automático o rough (por ejemplo un keyer rápido).
- El clip se escribe en el espacio de trabajo del script (por ejemplo ACEScg) sin convertir; en pruebas el modelo respondió igual que con lineal Rec.709.
- Las semitransparencias de un vidrio o reflejo (luz aditiva) no las entrega ningún keyer; CorridorKey resuelve cobertura (pelo, motion blur, bokeh).
- Si abres el script en una PC sin el plugin, el nodo se ve pero los botones no funcionan hasta instalarlo.

## Si algo falla

- **CorridorKey > Diagnóstico** muestra la instalación y la GPU.
- El instalador guarda su log en `%LOCALAPPDATA%\CorridorKey\install.log` y cada corrida en `...\run.log` dentro de la carpeta de temporales del nodo (`%LOCALAPPDATA%\CorridorKey\runs\<script>\<nodo>`). Envíalos a quien mantiene este paquete.
- "No se pudo descargar": revisa la conexión, el proxy o el antivirus (el instalador baja de github.com, download.pytorch.org y huggingface.co).
- "El driver NVIDIA es antiguo": actualiza desde nvidia.com/drivers.

## Desinstalar

Doble clic en **desinstalar.bat** (quita el menú y, si lo confirmas, borra los ~10 GB de modelos y Python).

## Para quien mantiene el paquete

- `installer\install.ps1` fija el commit de CorridorKey y el de `utils3d`; para actualizar, cambia `$AppCommit` y prueba en un sandbox:
  `instalar.bat -Root C:\prueba_ck\home -NukeDir C:\prueba_ck\.nuke`.
- Pruebas: `tests\test_core.py` (lógica sin Nuke) y `tests\nuke_node_test.py` (el nodo completo en Nuke headless: dos entradas, reutilización de la conversión, reconversión al cambiar algo aguas arriba, guardar y reabrir).
- No redistribuyas los modelos ni la carpeta `app` ya instalada: cada PC los descarga con `instalar.bat`.
- Limitación conocida: mientras corre, Nuke muestra la barra de progreso y no se puede editar el script (el proceso de CorridorKey sí es independiente de Nuke).
