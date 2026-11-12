# CorridorKey para Nuke

Un nodo para usar CorridorKey 2.0, el keyer con IA de Corridor Digital, dentro de Nuke y en tu propia GPU.

El paquete no trae CorridorKey ni sus modelos. El instalador los descarga en cada PC.

## Qué necesitas

- Windows 10 u 11.
- Una NVIDIA RTX serie 30 o más nueva, con driver 570 o superior. Funciona desde 4 GB de VRAM, pero con 12 GB se trabaja cómodo.
- Nuke 15.1 o 17.
- Unos 15 GB libres en C: e internet durante la instalación.

Para ver tu versión de driver, abre una terminal y escribe `nvidia-smi`. Aparece arriba a la derecha.

## Instalar

1. Extrae el ZIP en cualquier carpeta, por ejemplo `C:\Users\<tu usuario>\.nuke\CorridorKey-Nuke`. No lo ejecutes desde dentro del ZIP, porque no encuentra sus archivos. El ZIP de la última versión está en [Releases](https://github.com/juano-tools/CorridorKey-Nuke/releases/latest), en Assets.
2. Cierra Nuke.
3. Doble clic en `instalar.bat`. Si Windows avisa que protegió tu PC, elige Más información > Ejecutar de todos modos. Sale porque el archivo no está firmado.
4. Espera. La primera vez tarda entre 10 y 30 minutos, casi todo en descargar PyTorch y los modelos. A ratos parece que no avanza; no cierres la ventana.
5. Cuando termina dice "Listo. Reinicia Nuke" en verde.

Al abrir Nuke aparece el menú CorridorKey. En CorridorKey > Diagnóstico puedes ver la instalación y tu GPU. Si el menú no aparece, busca en la consola de Nuke la línea `CorridorKey: no se pudo cargar`, que dice por qué.

Si el instalador muestra un ERROR en rojo, el mensaje suele decir qué pasó: conexión, antivirus, driver viejo o falta de espacio. Arréglalo y vuelve a correr `instalar.bat`, que sigue desde donde quedó. Si no se soluciona, mándale `%LOCALAPPDATA%\CorridorKey\install.log` a quien te pasó el paquete.

Todo queda en `%LOCALAPPDATA%\CorridorKey`, con un Python propio que no toca el tuyo ni el de Nuke. En `.nuke\menu.py` se agregan unas líneas para cargar el menú, y antes se guarda una copia en `menu.py.bak_corridorkey`. Después de instalar puedes borrar la carpeta del ZIP.

## Actualizar

Extrae el ZIP nuevo, cierra Nuke y vuelve a correr `instalar.bat`. Reutiliza lo que ya está descargado, así que tarda poco.

Los nodos que ya tengas en tus scripts se quedan con el panel viejo. Bórralos y crea uno nuevo. Los EXR que ya sacaste no se pierden; si el nodo nuevo usa el mismo nombre y versión, los reemplaza al procesar.

Desde la 0.7.0, la casilla "plate original en el interior" viene marcada.

Desde la 0.7.1, el nodo trae "suavidad" en "plate original en el interior" y las layers `ck_fg` y `ck_fg_raw`. Un nodo hecho con la 0.7.0 sigue funcionando, pero sin eso: créalo de nuevo para tenerlas.

## Cómo se usa

1. Tab > CorridorKey, o en el menú CorridorKey > Crear nodo CorridorKey. Si tenías un nodo seleccionado, se conecta solo.
2. Conecta el plate a la entrada `clip`. Si tienes un matte del sujeto, conéctalo a `hint`; usa su alpha. El hint es opcional.
3. Elige la resolución y dale a ▶ Procesar. Puedes cancelar desde la barra de progreso.

> **Ojo con las pantallas azules y las pantallas detrás de un set.** Sin hint, CorridorKey elige solo el sujeto, casi siempre las personas, y puede recortar también el set: paredes, marcos de ventana, muebles. En esos shots conecta siempre un hint con 0 en la pantalla y 1 en todo lo que se queda. Basta un keyer rápido (Keylight, IBK) con un poco de blur, pero tiene que estar limpio en la pantalla: si el hint queda gris o con ruido ahí, el alpha sale igual. Más detalles en Hint.

El nodo saca el cutout premultiplicado al tamaño del plate. Con "ver" cambias entre cutout, alpha, fg, fg + alpha y el plate, sin volver a procesar.

Si necesitas otra pasada sin duplicar el nodo, sácala con un Shuffle. La salida lleva dos layers, las dos sin premultiplicar y con el alpha:

- `ck_fg`: el fg con plate original y despill.
- `ck_fg_raw`: el fg crudo del modelo, sin plate original ni despill.

El panel sigue el orden en que se trabaja:

- 1 · entrada: resolución, rango y hint.
- 2 · salida: carpeta, nombre y versión de los EXR.
- 3 · ajustar: vista, despill y plate original. Todo en vivo.
- avanzado y mantenimiento vienen cerrados. Normalmente no hay que tocarlos.

Cada control tiene su ayuda si dejas el mouse encima.

### Resolución

En HD el nodo trabaja a 1920 de ancho por dentro y devuelve el resultado al tamaño del plate. No le pongas un Reformat antes: conecta el plate 4K directo. Si lo reduces tú, el resultado sale reducido.

Las otras resoluciones:

- Nativa: para pelo muy fino o motion blur exigente. Con 12 GB de VRAM conviene conectar un hint.
- 720p: para máquinas con poca VRAM o una prueba rápida. Da menos detalle en el borde.

Un plate más chico que la resolución elegida no se agranda.

### Hint

- "usar hint" sirve para probar sin hint sin desconectar el nodo.
- "hint en": todos los frames o solo el primero. Con el primer frame el modelo sigue al sujeto por su cuenta, y en tomas largas o con oclusiones se puede perder.
- "calidad del hint": 0,95 para un roto de artista, 0,75 para un matte automático o un key rápido, 0,5 o menos si es aproximado.
- "calidad interna" y "hint sin arrastre" controlan cuánto se apoya el modelo en lo que arrastra de un tramo de frames al siguiente. Déjalos como están salvo que el key derive.

Sin hint, el modelo decide solo cuál es el sujeto, y casi siempre elige a las personas. Si la pantalla está detrás de un set (ventanas, por ejemplo), sin hint también recorta el set: paredes, marcos y muebles. La solución es un hint con 0 en la pantalla y 1 en todo lo que se queda. Basta un keyer rápido con un poco de blur: el borde lo rehace el modelo, no lo copia del hint. El hint tiene que ser claro en la pantalla, porque donde el hint duda (gris), el alpha también sale gris.

### Despill

El despill no lo hace el modelo: es una regla que se aplica al fg después. Por eso aquí es en vivo.

- "pantalla": verde o azul. El modelo separa bien la pantalla azul. Si en un shot azul el set desaparece, falta el hint (ver Hint), no es por el color.
- Average es la regla de CorridorKey. Máximo es más suave y respeta mejor los amarillos y la piel. Ninguno deja el fg crudo.
- "fuerza" va de 0 a 1. CorridorKey usa 0,5.
- Si el fg ya viene limpio, el despill casi no cambia nada.

Si prefieres tu propio despill (DespillMadness u otro), pon "ver" en fg + alpha y el despill en Ninguno, y haz el Premult después de tu nodo. Esa vista sale sin premultiplicar.

### Plate original en el interior

Con esta casilla marcada, el nodo usa el plate original en las zonas sólidas del sujeto y el fg de CorridorKey solo en los bordes.

El fg del modelo es el que limpia los bordes: saca el verde o el azul del croma que se mezcla en el pelo, el motion blur y las transparencias. En el interior no hay nada que limpiar, y si procesaste en HD el fg viene reescalado, más blando y con menos grano. Aun en resolución nativa, el fg no es idéntico al plate: la red calcula con poca precisión (bfloat16) y deja de 1 a 2 % de diferencia. Con la casilla marcada, el interior conserva el detalle y el grano del plate.

Si se nota una línea entre el interior y el borde, sube la "suavidad" (en píxeles; viene en 4) o desmarca la casilla.

Es en vivo y no cambia los EXR guardados.

### Memoria de GPU

Cierra ComfyUI y lo que esté usando la GPU antes de procesar. Si queda poca memoria libre, el nodo avisa y dice qué la está ocupando.

- "ventana temporal" (en avanzado) es cuántos frames mira el modelo a la vez. Más frames dan un key más estable, pero usan más memoria. Auto la elige según tu tarjeta. Si fijas una más grande de lo recomendado, el nodo pide confirmación: en una tarjeta de 12 GB, una ventana de 24 en 4K colgó el PC.
- Si se queda sin memoria a mitad de camino, reintenta solo con una ventana más chica y lo dice en el estado.
- "memoria": Auto se ajusta solo. Baja gasta menos y va más lento. Mínima es para tarjetas de 4 a 6 GB, o si Baja no alcanza.

Antes de empezar, el nodo también revisa que haya espacio en disco.

### Dónde quedan los archivos

Los EXR van a la carpeta de salida del nodo:

```
<carpeta>\<nombre>_alpha_v01\<nombre>_alpha_v01.1001.exr
<carpeta>\<nombre>_fg_v01\<nombre>_fg_v01.1001.exr
```

Se guardan el alpha y el fg sin despill, con el frame real del shot y a la resolución con que procesaste. El cutout no se guarda: lo arma el nodo en vivo.

- Carpeta: el nodo propone una automática y la muestra escrita en el campo; puedes cambiarla por cualquier otra. Si no encuentra una carpeta de prerenders del shot, usa `%LOCALAPPDATA%\CorridorKey\salida`.
- Nombre: el del plate más `_ck`.
- Carpeta y nombre se pueden cambiar a mano. Si borras el campo, vuelve el automático.
- Versión: procesar de nuevo reemplaza esa versión. Si quieres conservarla, sube el número antes.
- Si otro Read del script tiene abierta esa versión, Windows no deja reemplazarla. El nodo avisa y no toca nada. Sube la versión o borra ese Read.

Los temporales quedan en tu PC, en `%LOCALAPPDATA%\CorridorKey\runs`, nunca en el shot. Si no cambiaste nada aguas arriba, el nodo reutiliza el plate ya convertido; si cambias un Grade, el Read o el rango, lo vuelve a convertir. Los que llevan 14 días sin usarse se borran solos. Para limpiar antes: mantenimiento > borrar temporales en el nodo, o CorridorKey > Limpiar carpetas de nodos borrados.

## Otras cosas

- El plate se manda en el espacio de trabajo del script (ACEScg, por ejemplo), sin convertir. CorridorKey no maneja espacios de color y su README recomienda convertir ACEScg, Rec.2020 o log a lineal antes. En nuestras pruebas, ACEScg dio lo mismo que Rec.709 lineal, también con pantalla azul.
- Mientras procesa, Nuke queda bloqueado con la barra de progreso.
- Si abres el script en una PC sin el plugin, el nodo se ve pero los botones no hacen nada.

## Si algo falla

- Mira CorridorKey > Diagnóstico.
- Los logs están en `%LOCALAPPDATA%\CorridorKey\install.log` (instalación) y en el `run.log` de cada proceso, dentro de `%LOCALAPPDATA%\CorridorKey\runs\<script>\<nodo>`. Mándalos a quien te pasó el paquete.
- "No se pudo descargar": revisa la conexión, el proxy o el antivirus. El instalador baja de github.com, download.pytorch.org y huggingface.co.
- "El driver NVIDIA es antiguo": actualízalo en nvidia.com/drivers.

## Desinstalar

Doble clic en `desinstalar.bat`. Quita el menú y, si confirmas, borra Python y los modelos (unos 10 GB).

## Créditos y licencia

Este paquete usa [CorridorKey 2.0](https://github.com/nikopueringer/CorridorKey2.0) de Corridor Digital. El modelo lo diseñó y entrenó Zachary Harris junto a Niko y Corridor Digital. Se distribuye bajo la misma licencia: CC BY-NC-SA 4.0 con los términos adicionales de Corridor Digital (ver [LICENSE](LICENSE)).

- No es el plugin oficial de Corridor Digital, que se vende en [corridorkey.com](https://corridorkey.com).
- El código y los pesos de CorridorKey se descargan del repositorio original en cada PC. Este paquete no los incluye.
- Las imágenes que sacas son tuyas y puedes usarlas en trabajos comerciales.
- CorridorKey se apoya en tres modelos base: [C-RADIO](https://github.com/NVlabs/RADIO) de NVIDIA, [MoGe](https://github.com/microsoft/MoGe) de Microsoft y [RVM](https://github.com/google-deepmind/representations4d) de Google DeepMind.

## Para quien mantiene el paquete

- `installer\install.ps1` fija el commit de CorridorKey y el de `utils3d`. Para actualizar, cambia `$AppCommit` y prueba en un sandbox: `instalar.bat -Root C:\prueba_ck\home -NukeDir C:\prueba_ck\.nuke`.
- Pruebas: `tests\test_core.py` (la lógica, sin Nuke) y `tests\nuke_node_test.py` (el nodo completo en Nuke headless).
- No redistribuyas los modelos ni la carpeta `app` instalada. Cada PC los descarga con `instalar.bat`.
