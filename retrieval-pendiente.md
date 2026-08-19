# Pendientes y ruta de evolución del repositorio

## Estado al 2026-08-19

El repositorio tiene una base funcional de ingesta, limpieza, chunking,
embeddings, FAISS y recuperación determinista. Hay una suite amplia de tests
unitarios y de integración con fixtures sintéticos. El árbol de Git está limpio
y `main` está alineada con `origin/main`.

Lo que todavía no está demostrado es el comportamiento del pipeline completo
con un corpus y modelos reales. El corpus local está en `docs/` y permanece
fuera de Git; los índices generados también son artefactos locales. El archivo
`errores_parseo.jsonl` ya se persiste desde `main.py` y tiene cobertura en
`tests/test_main.py`, por lo que no es un pendiente.

## Prioridad 0 — cerrar la validación funcional

- [ ] Confirmar el contrato de entrada y salida con el reto o consumidor real:
  `fuente`, `doc_id`, `documents`, `fragments`, identificadores y cardinalidad.
  Resolver expresamente si `doc_id` debe ser el identificador interno
  `DOC-<fenomeno>-<contador>` o el nombre exacto del archivo fuente.
- [ ] Ejecutar `main.py` contra un corpus real representativo y revisar el
  inventario de documentos válidos, documentos descartados y
  `errores_parseo.jsonl`.
- [ ] Descargar y probar los modelos reales configurados (`BAAI/bge-m3` y
  `intfloat/multilingual-e5-large`), confirmando dimensión, prefijos, memoria,
  dispositivo CPU/GPU y tiempos razonables.
- [ ] Construir y abrir un índice real para cada encoder. En el estado actual
  solo hay evidencia local de `encoder_bge-m3`; falta validar `e5-large` y la
  fusión multi-encoder con índices producidos por el pipeline.
- [ ] Preparar consultas reales con respuesta conocida y medir al menos
  `Recall@k`, `Precision@k` o `MRR`, además de revisar manualmente casos límite.
  Dejar el conjunto de evaluación separado del corpus de ingesta.
- [ ] Ejecutar dos veces el generador con los mismos insumos y comparar los
  archivos byte a byte en Windows y Linux; registrar versiones de Python,
  PyTorch, FAISS, NumPy y sentence-transformers.
- [ ] Probar fallos operativos: corpus vacío, archivo corrupto, modelo ausente,
  índice incompleto, dimensión incompatible, consulta duplicada y falta de
  documentos suficientes para completar la salida.

## Prioridad 1 — documentación que falta

- [ ] Crear un `README.md` raíz con propósito, alcance, arquitectura, requisitos,
  instalación, configuración, comandos de ingesta/indexación/recuperación,
  ejemplos de entrada y salida y limitaciones conocidas.
- [ ] Documentar la arquitectura y el flujo de datos en `docs/architecture.md`,
  incluyendo parser → limpieza → chunker → encoder → FAISS → generador.
- [ ] Documentar el contrato de datos en `docs/data-contract.md`: formatos de
  corpus, JSONL de consultas, `metadata.jsonl`, resultados, versionado de
  índices y política de identificadores.
- [ ] Documentar configuración y operación en `docs/operations.md`: variables
  de entorno, modelos, CPU/GPU, tamaños de batch, rutas de salida, logs,
  errores, reproducibilidad y limpieza de artefactos.
- [ ] Documentar la guía de desarrollo en `CONTRIBUTING.md`: entorno local,
  lint/type-check si se incorporan, tests, convenciones, commits y pull
  requests.
- [ ] Añadir `CHANGELOG.md` o notas de versiones, y declarar licencia mediante
  `LICENSE` antes de publicar el código.
- [ ] Revisar la documentación existente del parser para sustituir rutas
  relativas y referencias al pliego/entorno local por configuración genérica.

## Prioridad 1 — convertirlo en proyecto generalizable

- [ ] Separar el núcleo reutilizable de la lógica específica del reto: nombres
  de fenómenos, cardinalidad fija de 50 consultas, esquema de evaluación,
  prefijos/modelos y reglas de `fuente` deben vivir en configuración o plugins.
- [ ] Definir una configuración versionada (por ejemplo YAML/TOML) para corpus,
  parsers, limpieza, chunking, encoders, índice, consultas y salida; evitar
  defaults ligados a `./docs`, `./base_vectorial` o nombres del reto.
- [ ] Normalizar una API pública y una CLI estable para: parsear, indexar,
  consultar, validar y auditar. Mantener funciones internas fuera de la API
  pública y documentar compatibilidad.
- [ ] Convertir el proyecto en paquete instalable con `build-system`, metadatos,
  dependencias opcionales por feature (PDF/OCR, mapas, encoders) y entry points
  de CLI. Añadir lockfile o política clara de actualización de dependencias.
- [ ] Sustituir fixtures sintéticos acoplados a nombres internos por fixtures
  mínimos y corpus de ejemplo redistribuible; no incluir documentos sensibles,
  modelos descargados, índices FAISS ni resultados generados en el repositorio.
- [ ] Añadir validación de configuración, versionado del esquema y metadatos del
  índice (encoder, dimensión, normalización, chunking, commit y fecha de
  construcción) para evitar mezclar índices incompatibles.
- [ ] Auditar dependencias, licencias de documentos/modelos y datos de ejemplo;
  eliminar secretos, `.env` local, artefactos temporales y residuos de IDE.

## Prioridad 2 — llevarlo a nuestros GitHub

1. Acordar nombre, descripción, organización propietaria, visibilidad, licencia
   y responsables del repositorio.
2. Preparar una rama de publicación que contenga README, licencia, contribución,
   changelog, configuración de ejemplo, CI y únicamente datos redistribuibles.
3. Crear el repositorio remoto y publicar la rama inicial; conservar este repo
   como origen histórico solo si su corpus/artefactos no deben hacerse públicos.
4. Configurar protección de `main`, revisión obligatoria, `CODEOWNERS`, plantillas
   de issues/PR y etiquetas para parser, retrieval, documentación y seguridad.
5. Configurar GitHub Actions para instalación limpia, tests, lint/type-check y
   validaciones de contrato. Separar jobs pesados de modelos reales mediante un
   workflow manual o fixtures pequeños cacheables.
6. Publicar una primera versión etiquetada solo después de validar el pipeline
   real y revisar licencias. A partir de ahí, usar releases y changelog para
   cambios incompatibles.

## Criterio de terminado

El proyecto está listo para compartirse cuando una persona externa puede
clonar el repositorio, instalarlo en una máquina limpia, ejecutar un ejemplo
completo con datos redistribuibles, entender sus contratos y limitaciones,
reproducir los resultados esperados y distinguir claramente entre código,
configuración, datos, modelos e índices generados.

## Decisiones abiertas

- [ ] ¿El repositorio público será el núcleo genérico, una implementación del
  reto o ambos mediante un paquete núcleo y un adaptador separado?
- [ ] ¿Qué corpus y consultas pueden redistribuirse legalmente como ejemplo?
- [ ] ¿Se soportarán solo encoders locales o también backends configurables?
- [ ] ¿Qué organización, nombre, licencia y política de releases usaremos en
  nuestros GitHub?
