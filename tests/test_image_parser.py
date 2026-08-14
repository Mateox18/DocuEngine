"""Pruebas del parser OCR de imagenes."""

from pathlib import Path

from PIL import Image

from lib.parser.parsers.image_parser import ImageParser


def _datos_ocr(textos: list[str]) -> dict:
    cantidad = len(textos)
    return {
        "text": textos,
        "conf": ["95"] * cantidad,
        "block_num": [1] * cantidad,
        "par_num": [1] * cantidad,
        "line_num": list(range(1, cantidad + 1)),
        "word_num": [1] * cantidad,
        "left": [10] * cantidad,
        "top": [10 * n for n in range(cantidad)],
        "width": [80] * cantidad,
        "height": [20] * cantidad,
    }


def test_image_parser_extrae_bloques_y_metadata(tmp_path: Path, monkeypatch) -> None:
    ruta = tmp_path / "escaneo.avif"
    Image.new("RGB", (100, 100), "white").save(ruta, format="PNG")

    monkeypatch.setattr(
        "lib.parser.parsers.image_parser.pytesseract.image_to_data",
        lambda *args, **kwargs: _datos_ocr(
            ["Informe", "de", "seguridad", "espacial", "regional"]
        ),
    )

    doc = ImageParser().parse(ruta, "DOC-1-00001", 1)

    assert doc.formato == "imagen"
    assert doc.meta_extra["ocr"] is True
    assert doc.meta_extra["confianza_media"] == 95.0
    assert doc.meta_extra["psm_usado"] == 3
    assert doc.blocks[0].tipo == "ocr_text"
    assert "seguridad" in doc.blocks[0].texto
    assert doc.blocks[0].ancla["bbox"] == [10, 0, 90, 60]


def test_image_parser_rechaza_ocr_insuficiente(tmp_path: Path, monkeypatch) -> None:
    ruta = tmp_path / "logo.jpg"
    Image.new("RGB", (100, 100), "white").save(ruta)
    monkeypatch.setattr(
        "lib.parser.parsers.image_parser.pytesseract.image_to_data",
        lambda *args, **kwargs: _datos_ocr(["logo"]),
    )

    _, error = ImageParser().parse_seguro(ruta, "DOC-1-00001", 1)

    assert error is not None
    assert "OCR insuficiente" in error.excepcion
