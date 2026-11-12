# CorridorKey para Nuke

Nodo de Nuke para keyear croma verde o azul con **CorridorKey 2.0** (el keyer neuronal de Corridor Digital), local en tu GPU.
Este paquete no incluye CorridorKey ni sus modelos: el instalador los descarga desde sus fuentes oficiales en cada PC.

## Requisitos

- Windows 10/11 y una GPU **NVIDIA RTX serie 30 o más nueva** con el driver 570 o superior (mínimo 4 GB de VRAM; 12 GB o más es lo cómodo).
- Nuke 15.1 o 17 (Python estándar, sin compilar nada).
- Unos 15 GB libres y conexión a internet durante la instalación.

## Descargar e instalar (paso a paso)

Antes de empezar, comprueba tres cosas:

- Tienes una GPU NVIDIA RTX serie 30 o más nueva y el driver al día (si dudas: abre una terminal y escribe `nvidia-smi`; arriba a la derecha dice la versión del driver, tiene que ser 570 o más).
- Tienes unos **15 GB libres** en el disco `C:` (o en el disco donde esté tu carpeta `%LOCALAPPDATA%`).
- **Nuke está cerrado** (si estaba abierto, ciérralo: el menú nuevo solo aparece al abrirlo de nuevo).

### 1. Descargar el paquete

Si te enviaron el ZIP por correo, Drive o la red del estudio, salta al punto 3 (extraerlo). Si lo bajas de GitHub:

1. Entra a la página del repositorio en GitHub con tu cuenta (es privado: tienes que haber aceptado la invitación que llegó a tu correo).
2. Pulsa el botón verde **Code** y elige **Download ZIP**. Se baja un archivo `CorridorKey-Nuke-main.zip` (pesa poco: el paquete no trae los modelos, el instalador los baja después).
3. Haz clic derecho sobre el ZIP y elige **Extraer todo...**. Déjalo en una carpeta normal, por ejemplo `C:\Herramientas\CorridorKey-Nuke`. **No lo ejecutes desde dentro del ZIP**: el instalador necesita ver la carpeta `nuke` que viene junto a él.

Si usas git, es equivalente: `git clone <dirección del repositorio>`.

### 2. Instalar

1. Abre la carpeta que extrajiste y haz **doble clic en `instalar.bat`**.
2. Si Windows muestra una ventana azul ("Windows protegió su PC"), pulsa **Más información** y luego **Ejecutar de todos modos**. Sale porque el archivo viene de internet y no está firmado; es el `.bat` de esta carpeta y su contenido se puede leer con el Bloc de notas.
3. Se abre una ventana negra que va mostrando pasos con `==>`. **No la cierres.** Hace esto, en orden:
   - revisa la GPU, el driver y el espacio libre (si algo no cumple, se detiene y lo dice);
   - baja `uv` y crea un Python 3.12 propio (no toca tu Python ni el de Nuke);
   - baja CorridorKey 2.0 desde su GitHub oficial;
   - instala PyTorch con CUDA (unos 3 GB, es lo que más tarda);
   - instala las dependencias y baja los modelos (unos 3,5 GB);
   - comprueba que PyTorch ve tu GPU y copia el menú a tu carpeta `.nuke`.
4. Al final dice **"Listo. Reinicia Nuke"** en verde y la ventana queda esperando una tecla. La primera vez tarda entre 10 y 30 minutos según tu conexión; es normal que pasen varios minutos sin que se mueva el texto mientras baja PyTorch.
5. Si dice **ERROR** en rojo, no hace falta repetir nada a mano: lee el mensaje (suele ser conexión, antivirus, driver antiguo o poco espacio), arréglalo y vuelve a ejecutar `instalar.bat`, que continúa con lo ya descargado. Si no logras resolverlo, envía el archivo `%LOCALAPPDATA%\CorridorKey\install.log` a quien mantiene el paquete.

### 3. Comprobar que funciona

1. Abre Nuke (15.1 o 17). En la barra de menús superior aparece **CorridorKey**.
2. Elige **CorridorKey > Diagnóstico**: tiene que mostrar la instalación y el nombre de tu GPU.
3. Crea el nodo con **CorridorKey > Crear nodo CorridorKey** y sigue con "Usar", más abajo.

Si el menú no aparece, mira la consola de Nuke (o la terminal desde donde lo abriste): el bloque que agregamos a `menu.py` imprime ahí `CorridorKey: no se pudo cargar: ...` con la causa.

### Actualizar

Cuando haya una versión nueva: descarga el ZIP otra vez, extráelo (puedes reemplazar la carpeta anterior) y vuelve a ejecutar `instalar.bat`. Reutiliza lo ya descargado (Python, PyTorch, modelos) y solo cambia lo necesario.
Cierra Nuke antes de instalar, o reinícialo después.

Ten en cuenta al actualizar:

- Los nodos CorridorKey que ya tengas en tus scripts conservan el panel viejo y no tendrán los controles nuevos. Bórralos y crea uno nuevo (Tab > CorridorKey). Los EXR que ya procesaste no se pierden: si usas el mismo nombre y versión de salida, el nodo nuevo los sobrescribe al procesar.
- Desde la 0.7.0, el panel viene con **plate original en el interior** marcada.

### Dónde queda todo

El instalador deja todo en `%LOCALAPPDATA%\CorridorKey` (Python propio, no toca el tuyo) y agrega un bloque a `~\.nuke\menu.py`
(con copia de seguridad `menu.py.bak_corridorkey`). La carpeta que descargaste ya no hace falta después de instalar: puedes borrarla.
Si tu estudio usa otra carpeta de Nuke, abre una terminal en la carpeta del paquete y ejecuta:
`instalar.bat -NukeDir D:\ruta\.nuke`.

## Usar

1. Crea el nodo: **CorridorKey > Crear nodo CorridorKey**, o con Tab escribiendo `CorridorKey`. Si tenías un nodo seleccionado, queda conectado a la entrada **clip**.
2. Conecta el **clip** (el plate de croma) a la entrada `clip` y, si tienes un matte del sujeto, conéctalo a la entrada `hint` (opcional; se usa su alpha).
3. En las propiedades del nodo elige la resolución y pulsa **Procesar**. Hay barra de progreso y botón Cancelar. El **rango** toma el del clip conectado; si lo cambias a mano se respeta, y el botón **rango del clip** lo vuelve a tomar del clip. El panel se lee de arriba abajo en el orden en que se trabaja: **1 · entrada** (resolución, rango y hint), **2 · salida** (carpeta, nombre y versión), el botón **Procesar** con el **estado** debajo, y **3 · ajustar** (ver, pantalla, despill, fuerza, plate original en el interior: es en vivo y no vuelve a procesar). Al final, cerradas, **avanzado** (ventana temporal y memoria) y **mantenimiento** (reconvertir, borrar temporales). Cada título y cada control tiene su ayuda al dejar el mouse encima. Los controles que no aplican (por ejemplo la calidad del hint sin hint conectado) quedan en gris.
4. El nodo entrega el **cutout** (RGBA premultiplicado) a la resolución del clip. El desplegable **Ver** cambia entre cutout, alpha, fg, fg + alpha y el clip original sin volver a procesar.
5. Los EXR del resultado (alpha y fg) quedan en la **carpeta de salida** (ver abajo), listos para subir con el resto de tus prerenders.

### Despill en vivo y salida straight

El modelo entrega el **alpha** y el **fg** (el color del sujeto sin la mezcla con la pantalla en los bordes). El **despill** no lo hace el modelo: es una regla fija que se aplica después. Por eso aquí es un paso **en vivo** dentro del nodo, sobre el fg: lo cambias y se ve al instante, sin Procesar.

- **Pantalla**: verde o azul (el canal que baja el despill).
- **Despill**: *Average* es exactamente la regla de CorridorKey (baja el verde que supera el promedio de rojo y azul y reparte la mitad a cada uno); *Máximo* solo baja el verde que supera al mayor de los dos, así respeta amarillos y tonos cálidos (corrige menos que Average); *Ninguno* deja el fg crudo. **Fuerza** va de 0 a 1 (CorridorKey usa 0,5 por defecto, que corrige solo la mitad del exceso).
- Si el fg del modelo ya viene limpio, mover el despill casi no cambia nada: es normal (en una toma de prueba, a fuerza 1 Average cambiaba ~1 % de los píxeles).
- **Ver > cutout** = el fg con ese despill, premultiplicado por el alpha.
- **Ver > fg + alpha** = el fg crudo con el alpha en el canal alpha, **sin premultiplicar**. Sirve para despillar con tu propio nodo (DespillMadness u otro): conéctalo a esta vista, pon **Despill = Ninguno** si no quieres doble despill, y haz el **Premult** después.

### Hint

- **Usar hint**: desmárcalo para procesar sin hint sin desconectar el nodo.
- **Hint en**: *Todos los frames* (un matte por frame, lo más controlado) o *Solo el primer frame* (el modelo parte del hint del primer frame del rango y sigue al sujeto solo; puede derivar en tomas largas u oclusiones).
- **Calidad interna** es la confianza en lo que el modelo arrastra entre ventanas temporales (0,95 por defecto); **Hint sin arrastre** hace que el hint mande tal cual en todos los frames.
- **Avanzado > Memoria**: *Auto* (recomendado) activa el modo de memoria baja solo cuando hace falta; *Baja* lo fuerza (más lento, menos VRAM); *Mínima* baja además todos los ajustes finos, para tarjetas de 4 a 6 GB o cuando *Baja* no alcanza.

### Plate original en el interior

La casilla **plate original en el interior** (en **3 · ajustar**, marcada por defecto) usa el plate original dentro del sujeto y el resultado de CorridorKey solo en los bordes.

- **Por qué**: el fg de CorridorKey es el color del sujeto recalculado por el modelo. En los bordes eso es lo valioso: quita la pantalla mezclada en el pelo, el motion blur y las transparencias. Dentro del sujeto no hay nada que separar, y ahí el fg es una copia del plate de menor calidad: si procesas en HD o 720p viene reescalado (más blando que tu plate) y puede perder grano y detalle fino.
- **Qué hace**: donde el alpha es sólido (de 0,95 a 1) pone los píxeles del plate; en los bordes y las zonas translúcidas deja el fg del modelo. El despill se aplica después, sobre todo el sujeto.
- **Cuándo usarla**: al procesar en HD o 720p un plate de más resolución, casi siempre.
- **Qué revisar**: el límite entre el interior y el borde. El umbral es fijo y no tiene erosión; si ves una línea ahí, desmárcala.
- Es en vivo: no vuelve a procesar. Cambia las vistas cutout, fg y fg + alpha; los EXR guardados no cambian (son siempre el alpha y el fg crudos del modelo).

### HD interno: no pongas un Reformat

Con **Resolución = HD** el nodo reduce el clip a 1920 px de ancho **por dentro** y devuelve el resultado al tamaño original del clip.
**No hace falta poner un Reformat antes**: conecta el clip tal cual (4K, por ejemplo). Si lo reduces tú antes, el resultado saldrá a ese tamaño reducido.
En pruebas con un plano 4K, el key calculado en HD y subido a 4K difirió del 4K nativo en el 0,13 % de los píxeles, casi todos en los bordes de los dedos, y fue unas 4 veces más rápido.
Usa **Nativa** solo si necesitas el máximo detalle de borde (pelo fino, motion blur); en una GPU de 12 GB conviene entonces conectar un hint.

**Ventana temporal**: cuántos frames mira el modelo a la vez. Más frames = key más estable en el tiempo y mejor borde, pero más memoria de GPU (en las pruebas pesó más que la resolución). *Auto* (recomendado) deja que CorridorKey elija según la memoria libre; *Frame a frame* es lo más liviano pero puede parpadear; 2 a 80 fija la ventana. En GPUs de 16 GB o menos una ventana fija usa siempre el modo de memoria baja, y si supera lo recomendado para tu tarjeta y la resolución (la tabla de CorridorKey, de 4 a 48 GB) el nodo pide confirmación: en un PC de 12 GB, una ventana de 24 en 4K lo colgó.

**Si falta memoria de GPU**, el nodo no falla a la primera: reintenta solo con la ventana siguiente más chica, hasta frame a frame, y el estado dice con cuál terminó (por ejemplo, *Ventana: 4 frames (bajó de 16 por memoria)*).

Antes de convertir, el nodo **revisa el espacio en disco** (temporales y carpeta de salida) y, si no alcanza, avisa sin empezar.

**720p** reduce a 1280 px de ancho, también por dentro del nodo. Es para equipos con poca memoria de GPU o para una prueba rápida: va más rápido y gasta menos memoria, con menos detalle en los bordes. Un clip que ya es más chico que el ancho elegido no se agranda.

### Dónde quedan los archivos

**El resultado (lo que subes)** va a la **Carpeta de salida** del nodo, con la convención de `2_prerenders`:

```
<carpeta de salida>\<nombre>_alpha_v01\<nombre>_alpha_v01.1001.exr
<carpeta de salida>\<nombre>_fg_v01\<nombre>_fg_v01.1001.exr
```

Son el alpha y el fg **crudos, sin despill**; el cutout se calcula en vivo dentro del nodo y no se guarda en disco. El nodo guardado en el script lee estos archivos.

- **Carpeta**: aparece escrita la automática, la carpeta `2_prerenders` que está junto a `1_projects`, subiendo desde donde guardaste el script (`...\SHOW_101_0500\Comp\1_projects\x.nk` guarda en `...\Comp\2_prerenders`). Con el script sin guardar (o fuera de esa estructura), usa la `2_prerenders` de Comp del shot al que pertenece el clip (`...\SHOW_101_0500\_input\plate\x.exr` guarda en `...\SHOW_101_0500\Comp\2_prerenders`), solo si esa carpeta ya existe. Si nada de eso aplica, usa `%LOCALAPPDATA%\CorridorKey\salida`. Si escribes otra se respeta; si la borras, vuelve la automática.
- **Nombre**: aparece escrito el nombre automático, el del clip (sin número de frame) + `_ck`, por ejemplo `SHOW_101_1200_aPlate_v001_ck`, para que lo retoques. Si lo cambias a mano se respeta; si lo borras, vuelve a ser automático y sigue al clip.
- Los archivos llevan el **número de frame real** del shot (1001…) y son **HD** si elegiste HD (el nodo los reescala al tamaño del clip solo dentro de Nuke).
- **Versión**: Procesar **reemplaza** los archivos de esa versión, así no se acumula espacio. Para conservar lo anterior, sube el número de **Versión** antes de procesar: se crea `..._v02` y la `v01` queda intacta.
- Si otro Read de tu script tiene abierta la secuencia que se va a reemplazar, Windows no deja pisarla: el nodo te avisa, deja la versión como estaba y no mezcla frames. Sube la versión o desactiva ese Read.

**Los temporales (no se suben)** viven en tu PC, en `%LOCALAPPDATA%\CorridorKey\runs\`, nunca junto al shot:

- El clip (y el hint) se convierten una vez. Si no cambió nada de lo que alimenta al nodo, **reutiliza la conversión**: cambiar la calidad del hint o lo que ves no reconvierte (el despill ni siquiera corre el modelo: es en vivo). Si cambias algo aguas arriba (un Grade, el Read, el rango), lo detecta y reconvierte.
- **Mantenimiento > borrar temporales** (en el nodo) quita el clip y el hint convertidos y no toca la carpeta de salida. **CorridorKey > Limpiar carpetas de nodos borrados** quita los temporales de nodos que ya no están en el script.

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

## Créditos y licencia

Este paquete instala y usa [CorridorKey 2.0](https://github.com/nikopueringer/CorridorKey2.0), de Corridor Digital (modelo diseñado y entrenado por Zachary Harris junto a Niko y Corridor Digital). Se distribuye bajo la misma licencia: CC BY-NC-SA 4.0 con los términos adicionales de Corridor Digital (ver [LICENSE](LICENSE)).

- No es el plugin oficial de Corridor Digital, que se vende en [corridorkey.com](https://corridorkey.com).
- El código y los pesos de CorridorKey se descargan del repositorio original en cada PC; este paquete no los incluye.
- Las imágenes que produces son tuyas y puedes usarlas en trabajos comerciales.
- Una empresa con más de USD 20 millones de facturación anual (o quien trabaje a nombre de ella) necesita comprar un asiento por persona en corridorkey.com.

## Para quien mantiene el paquete

- `installer\install.ps1` fija el commit de CorridorKey y el de `utils3d`; para actualizar, cambia `$AppCommit` y prueba en un sandbox:
  `instalar.bat -Root C:\prueba_ck\home -NukeDir C:\prueba_ck\.nuke`.
- Pruebas: `tests\test_core.py` (lógica sin Nuke) y `tests\nuke_node_test.py` (el nodo completo en Nuke headless: dos entradas, reutilización de la conversión, reconversión al cambiar algo aguas arriba, guardar y reabrir).
- No redistribuyas los modelos ni la carpeta `app` ya instalada: cada PC los descarga con `instalar.bat`.
- Limitación conocida: mientras corre, Nuke muestra la barra de progreso y no se puede editar el script (el proceso de CorridorKey sí es independiente de Nuke).
