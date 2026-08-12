# Flujo de ingesta

La carpeta `parser` transforma los archivos de `docs/` en objetos
`ParsedDocument`. El flujo actual es:

```text
DOCS_PATH (.env)
    ↓
recorrer_archivos()
    ↓
inferir_fenomeno()
    ↓
detectar_parser()
    ↓
parser.parse_seguro()
    ↓
cleaning.pipeline.limpiar_documento()
    ↓
(documento, error)
```

## Configuración

`.env` debe definir la raíz del corpus:

```env
DOCS_PATH=C:\ruta\al\repositorio\docs
```

`main.py` carga esta variable con `python-dotenv`. El módulo no procesa el
corpus al importarse; hay que llamar a `procesar_todo(raiz)`.

## Recorrido

`recorrer_archivos()` usa `os.walk()` y entrega cada `Path` mediante `yield`.
Ordena los subdirectorios y archivos en cada nivel, por lo que el recorrido es
reproducible sin cargar todas las rutas en memoria.

## Fenómeno e identificador

El fenómeno se infiere desde la primera carpeta relativa a `docs/`:

| Carpeta | Fenómeno |
|---|---:|
| `F1_IA_y_Capacidades_Estrategicas` | 1 |
| `F2_Seguridad_Entorno_Espacial` | 2 |
| `F3_Dinamicas_Territoriales` | 3 |

Los IDs se asignan por fenómeno en el orden del recorrido:

```text
DOC-1-00001
DOC-1-00002
DOC-2-00001
```

El contador aumenta cuando el archivo tiene un parser, incluso si su parseo
termina en error. Esto mantiene un identificador único para cada intento de
ingesta y evita reutilizar IDs dentro de una ejecución.

## Selección y errores

Cada parser declara sus extensiones en `EXTENSIONES`. `detectar_parser()` las
consulta y devuelve una instancia del primer parser compatible. Una extensión
desconocida devuelve `None` y se omite.

`parse_seguro()` convierte fallos del parser en `ErrorParseo`; un archivo con
error no detiene el lote. La limpieza tiene el mismo aislamiento en `main.py`:
si `limpiar_documento()` falla, se genera otro `ErrorParseo` y se continúa.

## Limpieza

Cada documento válido pasa por `limpiar_documento()`, que normaliza texto,
elimina boilerplate, evalúa calidad, detecta idioma y calcula el hash.
`limpiar_corpus()` existe para la deduplicación entre documentos, pero todavía
no forma parte de `procesar_todo()`.

## Salida actual

`procesar_todo()` devuelve:

```python
(documentos_procesados, errores)
```

Los `ParsedDocument` no necesitan serializarse a JSON para continuar: se pasan
directamente en memoria a la siguiente etapa, el `chunker`:

```text
documentos parseados y limpiados
    ↓
chunker
    ↓
chunks
```

Los errores sí deben persistirse, por ejemplo en `errores_parseo.jsonl`, para
conservar los archivos omitidos o fallidos y poder revisarlos después.
