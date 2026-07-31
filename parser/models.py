#Todo aqui van a estar las clases que se pasan como molde en el parser
#Deberian haber 2 modelos, ParsedDocument que es el que se entrega a chunking
#Block que contiene metadata relevante para el chunking (que tipo de bloque es, ej header) y ademas es como se dividiran los documentos para parseo
# Se divide por bloques para tratar de conservar la estructura y asi despues en chunking poder trabajarla
from dataclasses import dataclass