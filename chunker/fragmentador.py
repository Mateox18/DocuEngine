import re
import pysbd

from parser.models import Block

SEGMENTADORES = {
    "es": pysbd.Segmenter(language="es", clean=False),
    "en": pysbd.Segmenter(language="en", clean=False),
}

def oracionador(block: Block) -> list[str]:
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
            act = act[-over:]
            pal = sum(len(o.split()) for o in act)

    act.append(sen)
    pal += cant


    if act:
        grup.append(act)

    return grup






