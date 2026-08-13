# Retrieval — lo que falta

La capa está implementada y con 48 tests en verde, pero todos corren contra un
índice sintético. Esto es lo que queda antes de poder confiar en ella.

---

## 1. El formato de salida

`generador.py` emite en `documents[].doc_id` y en `fragments[].doc_id` lo que trae
la metadata, que se genera así:

```python
doc_id = f"DOC-{fenomeno}-{docs_por_fenomeno[fenomeno]:05d}"   # parser/main.py:47
```

Es decir, `DOC-2-00013`: un contador interno. Pero `lib/parser/models.py:127-129` dice
del otro campo:

> `fuente` — nombre EXACTO del archivo original (path.name). **Clave de
> emparejamiento del reto.**

## 2. El formato de entrada está supuesto, no confirmado

`generador.py` espera un JSONL con `{"query_id": "q001", "text": "..."}`.

## 3. No hay con qué probarlo de verdad

| Falta | Consecuencia |
|---|---|
| `base_vectorial/` | La capa nunca ha corrido contra datos reales |
| Modelos descargados (bge-m3, e5-large) | `codificar_consulta()` solo se ha ejecutado con un stub |
| Confirmar `dim=1024` de bge-m3 | Está declarado en `CONFIG_ENCODERS` y solo se comprueba en runtime |
| Un segundo índice (e5-large) | RRF con dos encoders solo está probado con listas a mano |
| Consultas con respuesta conocida | Solo podemos medir determinismo, no calidad |

## 4. Persistir los errores de ingesta

Los archivos sin contenido util —por ejemplo, HTML compuesto casi solo por
menu, cookies o navegacion— deben quedar fuera del indice y registrarse como
`ErrorParseo`. `procesar_todo()` ya acumula esos errores, pero falta persistirlos
en un archivo como `errores_parseo.jsonl` para poder auditarlos despues.
