import re
import pysbd
from transformers import AutoTokenizer
from parser.models import Block, ParsedDocument
from chunker.models import Chunk

TOKENIZER = AutoTokenizer.from_pretrained("BAAI/bge-m3")

SEGMENTADORES = {
    "es": pysbd.Segmenter(language="es", clean=False),
    "en": pysbd.Segmenter(language="en", clean=False),
}

TIPOS_ESTRUCTURADOS = frozenset({"table_row", "cell", "feature"})


def oracionador(block: Block) -> list[str]:
    """Parte el texto de un bloque en oraciones completas.

    Los bloques estructurados se devuelven enteros, sin segmentar: si una fila
    trae una columna de texto libre con puntos, pysbd la parte en pedazos sin
    sentido (un fragmento que empieza por "| anio: 2024" no significa nada).

    Los saltos de linea sueltos se aplanan antes de segmentar. La limpieza los
    conserva a proposito, pero pysbd los lee como final de oracion y partiria
    "El crecimiento\\nha sido acelerado" en dos frases incompletas.
    """
    if block.tipo in TIPOS_ESTRUCTURADOS:
        return [block.texto]
    else:
        text = re.sub(r'\s*\n\s*', " ", block.texto)
        seg = SEGMENTADORES.get(block.idioma, SEGMENTADORES["es"])

        return seg.segment(text)

def agrupador(ora: list[str], lim: int, over: int ) -> list[list[str]]:
    """Agrupa oraciones en bloques de como maximo `lim` palabras.

    `over` es cuantas oraciones del grupo anterior se repiten al inicio del
    siguiente, para que una idea no quede partida entre dos chunks sin puente.

    Como la oracion es la unidad minima y nunca se abre, el requisito de
    completitud linguistica del pliego (3.3) se cumple por construccion.

    TODO: una sola oracion mas larga que `lim` produce un grupo que se pasa del
    limite, porque partirla violaria el 3.3. El pliego lo contempla: el 9.2.1
    manda dividir en subfragmentos al RESPONDER, no al indexar. El caso sin
    salida es una unica oracion de 250+ palabras (OCR sin puntuacion); si
    aparece en el corpus, lo resuelve generador.py, no este modulo.
    """
    grup = []
    act = []
    pal = 0

    for sen in ora:
        cant = len(sen.split())
        if act and cant + pal > lim:
            grup.append(act)
            if over <= 0:
                act = []
            else:
                act = act[-over:]
            pal = sum(len(o.split()) for o in act)
        act.append(sen)
        pal += cant


    if act:
        grup.append(act)

    return grup

def agrupar_por_seccion(bloques: list[Block]) -> list[list[Block]]:
    """Agrupa bloques consecutivos que comparten seccion_path.

    Evita que un chunk mezcle dos temas: un vector a medio camino entre dos
    secciones recupera peor en las dos. Medido sobre texto real, el tema que
    queda en segundo lugar dentro de un chunk mezclado pierde hasta un 30% de
    similitud frente al mismo texto aislado.

    Los heading se saltan: seccion_path guarda solo los ANCESTROS, nunca el
    texto del propio bloque, asi que un encabezado siempre tiene una ruta mas
    corta que su contenido y cerraria el grupo entre el titulo y lo que titula.
    Su texto no se pierde: viaja en el seccion_path de sus hijos.
    """
    grupos = []
    act = []

    for block in bloques:
        if block.tipo == "heading":
            continue
        if act and block.seccion_path != act[-1].seccion_path:
            grupos.append(act)
            act = []

        act.append(block)

    if act:
        grupos.append(act)

    return grupos

def fragmentar_documento(doc: ParsedDocument, lim: int, over: int, id_inicial: int = 0) -> list[Chunk]:
    """Convierte un documento parseado y limpio en su lista de Chunk.

    Encadena las tres funciones anteriores: agrupa por seccion, aplana cada
    grupo en oraciones y corta por tamano. Cada pedazo resultante es un Chunk.

    `id_inicial` permite que los id_ sigan corriendo entre documentos; ver
    fragmentar_corpus.
    """
    indice = 0
    chunks = []
    id_actual = id_inicial

    for grup in agrupar_por_seccion(doc.bloques_activos()):
        ora = []
        for blo in grup:
            ora.extend(oracionador(blo))
        for part in agrupador(ora, lim, over):
            unasola = " ".join(o.strip() for o in part)

            chunks.append(
                Chunk(
                    id_ = id_actual,
                    doc_id =  doc.doc_id,
                    indice = indice,
                    texto = unasola,
                    fuente = doc.fuente,
                    fenomeno = doc.fenomeno,
                    seccion_path = grup[0].seccion_path,
                    pagina = grup[0].ancla.get("pagina"),
                    tipo_bloque_origen = grup[0].tipo,
                    formato = doc.formato,
                    chunk_id = f"{doc.doc_id}-chunk-{indice:04d}",
                    num_tokens = len(TOKENIZER.tokenize(unasola))
                )
            )

            id_actual += 1
            indice += 1

    return chunks

def fragmentar_corpus(docs: list[ParsedDocument], lim: int, over: int) -> list[Chunk]:
    """Fragmenta todos los documentos del corpus con id_ unicos entre ellos.

    El contador avanza tantas posiciones como chunks produjo cada documento.
    Sin eso, cada documento numeraria desde cero y encoder.enc.validar_ids
    rechazaria el lote: FAISS necesita un id entero unico por vector.

    El orden de `docs` determina que id le toca a cada chunk, asi que tiene que
    ser estable entre ejecuciones para que el pipeline sea reproducible.
    """

    chunks_total = []
    ids = 0

    for doc in docs:
        chunks_parciales = fragmentar_documento(doc, lim, over, ids)
        chunks_total.extend(chunks_parciales)
        ids += len(chunks_parciales)

    return chunks_total
