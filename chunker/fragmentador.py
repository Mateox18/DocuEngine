import re
import pysbd
from lxml.doctestcompare import strip

from parser.models import ParsedDocument
from chunker.models import Chunk
from parser.models import Block

SEGMENTADORES = {
    "es": pysbd.Segmenter(language="es", clean=False),
    "en": pysbd.Segmenter(language="en", clean=False),
}

def oracionador(block: Block) -> list[str]:
    if block.tipo == "table_row" or block.tipo == "cell" or block.tipo == "feature":
        return [block.texto]
    else:
        text = re.sub(r'\s*\n\s*', " ", block.texto)
        seg = SEGMENTADORES.get(block.idioma, SEGMENTADORES["es"])

        return seg.segment(text)

def agrupador(ora: list[str], lim: int, over: int ) -> list[list[str]]:
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
                    tipo_bloque_origen = grup[0].tipo
                )
            )


            id_actual += 1
            indice += 1

    return chunks



















