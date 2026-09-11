# DocuEngine

DocuEngine transforma un corpus de documentos heterogéneos en una base vectorial local y recupera los documentos y fragmentos más relevantes para un conjunto de consultas. La ingesta, la indexación y la generación de resultados son pasos separados y reproducibles.

```text
corpus → parseo → limpieza → fragmentación → embeddings → índice FAISS → recuperación
```

El proyecto recupera evidencia textual del corpus; no genera respuestas con un modelo de lenguaje. La salida incluye los identificadores de los documentos y los fragmentos que sustentan cada resultado.

## Estado y alcance

La base de código incluye parsers, limpieza, fragmentación, embeddings con Sentence Transformers, índices FAISS y recuperación con fusión de encoders. Se procesan estos formatos:

| Tipo | Extensiones |
| --- | --- |
| Texto y Markdown | `.md`, `.markdown`, `.txt` |
| HTML | `.html`, `.htm` |
| JSON | `.json`, `.jsonl` |
| PDF | `.pdf` |
| Tabulares | `.csv`, `.tsv`, `.xlsx`, `.xls` |
| Imagen con OCR | `.png`, `.jpg`, `.jpeg`, `.tiff`, `.webp`, `.avif` |
| Datos geoespaciales | `.pbf` |

Los formatos no soportados se omiten. Un archivo que no pueda parsearse o limpiarse no detiene todo el lote: el fallo se registra en JSONL.

Cada archivo procesable recibe un identificador global consecutivo: `DOC-00001`, `DOC-00002`, etc. Directorios y archivos se recorren en orden alfabético, por lo que el mismo árbol de archivos produce los mismos IDs. Si se agrega, elimina o renombra un archivo situado antes que otros, sus IDs posteriores pueden cambiar. Reconstruye el índice después de modificar el corpus o el esquema.

La validación con un corpus real representativo, modelos descargados y métricas de recuperación sigue pendiente. No asumas que los parámetros por defecto sean óptimos para todos los corpus.

## Requisitos

- Python 3.11 o superior.
- `pip` y un entorno virtual recomendado.
- Espacio en disco y memoria suficientes para modelos e índices; el consumo depende del corpus y encoder elegidos.
- Para OCR, el ejecutable de [Tesseract OCR](https://tesseract-ocr.github.io/) accesible desde `PATH`.
- GPU NVIDIA opcional. El indexador usa CUDA si PyTorch la detecta; en caso contrario funciona en CPU. Para GPU, instala antes la variante de PyTorch compatible con tus drivers y CUDA.

Los encoders configurados son `BAAI/bge-m3` e `intfloat/multilingual-e5-large`. En la primera ejecución sus archivos pueden descargarse desde Hugging Face y guardarse en la caché local.

## Instalación

Desde la raíz del repositorio:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

En Windows, activa el entorno con:

```powershell
.venv\Scripts\Activate.ps1
```

Para instalar las dependencias de desarrollo:

```bash
python -m pip install -r requirements-dev.txt
```

## Uso rápido

### 1. Preparar el corpus

El corpus puede tener subcarpetas libres. DocuEngine las recorre en orden alfabético:

```text
mi_corpus/
├── informes/
│   ├── informe_orbital.pdf
│   └── capacidades.md
└── datos/
    └── indicadores.csv
```

El nombre exacto del archivo se conserva como `fuente` en la metadata. No incluyas índices ni resultados generados dentro del corpus.

### 2. Construir un índice

Este comando parsea, limpia, fragmenta e indexa el corpus con `bge-m3`:

```bash
python main.py \
  --corpus ./mi_corpus \
  --salida ./base_vectorial \
  --encoder bge-m3
```

Para añadir el índice de `e5-large` a la misma base, ejecuta nuevamente:

```bash
python main.py \
  --corpus ./mi_corpus \
  --salida ./base_vectorial \
  --encoder e5-large
```

Los artefactos resultantes son:

```text
base_vectorial/
├── encoder_bge-m3/
│   ├── index.faiss
│   └── metadata.jsonl
└── encoder_e5-large/
    ├── index.faiss
    └── metadata.jsonl

errores_parseo.jsonl
errores_indexacion.jsonl
```

`errores_parseo.jsonl` registra archivos que no pudieron parsearse o limpiarse. `errores_indexacion.jsonl` registra chunks sin embedding. Ambos se escriben aunque no haya fallos, en cuyo caso quedan vacíos.

| Opción | Valor por defecto | Descripción |
| --- | ---: | --- |
| `--corpus` | `./docs` | Directorio de documentos. |
| `--salida` | `./base_vectorial` | Directorio para los índices. |
| `--encoder` | `bge-m3` | `bge-m3` o `e5-large`. |
| `--palabras` | `200` | Máximo aproximado de palabras por fragmento. |
| `--solapamiento` | `2` | Oraciones compartidas entre chunks consecutivos. |
| `--batch-size` | `32` | Textos vectorizados por lote; redúcelo si falta memoria. |
| `--errores-parseo` | `./errores_parseo.jsonl` | Ruta de errores de parseo. |
| `--errores-indexacion` | `./errores_indexacion.jsonl` | Ruta de errores de embeddings. |

Cada ejecución crea un índice para un único encoder. No mezcles índices producidos con corpus, IDs, configuración de chunks o encoders distintos.

### 3. Preparar las consultas

El generador recibe JSONL: un objeto JSON por línea. El contrato actual exige exactamente 50 consultas, IDs con formato `q` seguido de tres dígitos y texto no vacío.

`consultas.jsonl`:

```json
{"query_id":"q001","text":"¿Qué capacidades estratégicas se mencionan?"}
{"query_id":"q002","text":"¿Qué riesgos se describen para la infraestructura?"}
```

Completa el archivo hasta `q050`. Los IDs no se repiten y se ordenan antes de procesarse, sin depender del orden de las líneas de entrada.

### 4. Generar resultados

Con una base vectorial y consultas válidas:

```bash
python generador.py \
  --consultas ./consultas.jsonl \
  --base ./base_vectorial \
  --salida ./resultados.jsonl \
  --fusion rrf
```

Por defecto se recuperan 100 vecinos por encoder. Si el pool no alcanza para completar la salida, se amplía de manera determinista.

| Opción | Valor por defecto | Descripción |
| --- | ---: | --- |
| `--consultas` | requerida | JSONL con 50 consultas. |
| `--base` | `./base_vectorial` | Directorio con `encoder_<nombre>/`. |
| `--salida` | `./resultados.jsonl` | Archivo JSONL de resultados. |
| `--k_busqueda` | `100` | Vecinos iniciales por encoder. |
| `--fusion` | `rrf` | `rrf` o `combsum`. |
| `--estricto` / `--no-estricto` | `--estricto` | Detenerse o descartar resultados inválidos. |

El modo estricto es recomendado: si una consulta no cumple el esquema, el proceso termina sin escribir una salida parcial.

## Contrato de salida

`resultados.jsonl` contiene una línea por consulta. Cada objeto tiene:

- `query_id`: identificador de la consulta.
- `documents`: exactamente tres documentos distintos, ordenados por `rank`.
- `fragments`: exactamente diez fragmentos, ordenados por `rank`.

Ejemplo abreviado:

```json
{
  "query_id": "q001",
  "documents": [
    {"rank": 1, "doc_id": "DOC-00007"},
    {"rank": 2, "doc_id": "DOC-00012"},
    {"rank": 3, "doc_id": "DOC-00003"}
  ],
  "fragments": [
    {
      "rank": 1,
      "chunk_id": "DOC-00007-chunk-0000",
      "doc_id": "DOC-00007",
      "text": "Fragmento recuperado del documento."
    }
  ]
}
```

Los fragmentos se filtran para evitar repeticiones debidas al solapamiento de chunks. Cada uno debe tener texto no vacío y hasta 250 palabras. Para producir una salida válida, el índice debe contener tres documentos distintos y suficientes fragmentos no redundantes.

## Diseño de recuperación

Los documentos y consultas deben representarse en el mismo espacio vectorial. La configuración actual es:

| Encoder | Modelo | Dimensión | Prefijos |
| --- | --- | ---: | --- |
| `bge-m3` | `BAAI/bge-m3` | 1024 | Sin prefijos. |
| `e5-large` | `intfloat/multilingual-e5-large` | 1024 | `passage: ` para documentos y `query: ` para consultas. |

Los vectores se normalizan y se consultan mediante producto interno en FAISS. Cuando hay varios encoders, los resultados se fusionan con Reciprocal Rank Fusion (`rrf`) o `combsum`. Los documentos se ordenan por el score de su mejor fragmento para no favorecer documentos extensos solo por tener más chunks.

## Reproducibilidad y mantenimiento

- Conserva corpus, configuración y versiones de dependencias para reproducir un índice.
- La salida usa ordenamientos y desempates estables, pero debe validarse con datos y modelos reales antes de una entrega.
- Reconstruye los índices si cambian documentos, IDs, chunks, encoder o esquema serializado.
- No subas documentos sensibles, modelos descargados, índices FAISS, resultados ni archivos de errores locales al repositorio.

## Desarrollo

Las pruebas están en `tests/` y usan fixtures sintéticos. Cuando el entorno esté disponible:

```bash
pytest
```

La documentación de arquitectura, contrato de datos, operación y contribución se añadirá progresivamente. Por ahora, `main.py`, `generador.py`, `lib/` y `retrieval/` son la referencia operativa del proyecto.
