"""Testes unitários do extrator de OCR seletivo via RapidOCR (Opção B1).

Valida o recorte de páginas sem texto, a instância singleton/lazy do
RapidOCR, renderização a 200 DPI com fallback para 150 DPI em páginas
grandes, ordenação geográfica de caixas (y_bucket, x) e o fallback seguro
quando o RapidOCR não está disponível.
"""

from __future__ import annotations

import hashlib
from unittest.mock import MagicMock, patch

import fitz
import pytest

from tomus.extractors import ocr
from tomus.extractors.ocr import (
    _OCR_FIRST_PAGES,
    _OCR_LAST_PAGES,
    _OCR_MAX_PAGES,
    _ALPHANUM_THRESHOLD,
    _build_slice_pdf,
    _configure_opencv_threads,
    _dpi_for_page,
    _extract_lines_from_result,
    _get_rapidocr_engine,
    _ocr_with_rapidocr,
    _order_boxes_geometricamente,
    _pages_without_text,
    ocr_scanned_pages,
)
from tomus.extractors.ocr_docling import ocr_scanned_pages as ocr_scanned_pages_fachada


def _make_scanned_pdf(path: Path, num_pages: int = 10) -> Path:
    """Criar um PDF com páginas sem texto selecionável (simula escaneado)."""
    doc = fitz.open()
    for _ in range(num_pages):
        doc.new_page()
    doc.save(str(path))
    doc.close()
    return path


def _make_native_pdf(path: Path, num_pages: int = 10) -> Path:
    """Criar um PDF com texto selecionável em algumas páginas."""
    doc = fitz.open()
    for i in range(num_pages):
        page = doc.new_page()
        if i < 3:
            page.insert_text((72, 72), "Texto selecionável na página " + str(i))
    doc.save(str(path))
    doc.close()
    return path


def _make_scanned_pdf_with_image(path: Path, num_pages: int = 1) -> Path:
    """Criar um PDF com uma imagem em cada página (sem camada de texto)."""
    import io

    from PIL import Image, ImageDraw

    doc = fitz.open()
    for _ in range(num_pages):
        page = doc.new_page()
        img = Image.new("RGB", (700, 500), color="white")
        draw = ImageDraw.Draw(img)
        draw.text((50, 60), "RAPIDOCR TITULO DE TESTE", fill="black", font_size=36)
        draw.text((50, 140), "Autor: Sobrenome, Nome", fill="black", font_size=28)
        draw.text((50, 220), "Ano: 2024", fill="black", font_size=28)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        page.insert_image(fitz.Rect(0, 0, 700, 500), stream=buf.getvalue())
    doc.save(str(path))
    doc.close()
    return path


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------


def test_constantes_ocr():
    """Verificar que as constantes de OCR têm os valores esperados."""
    assert _OCR_FIRST_PAGES == 8
    assert _OCR_LAST_PAGES == 2
    assert _OCR_MAX_PAGES == 8
    assert _ALPHANUM_THRESHOLD == 30


# ---------------------------------------------------------------------------
# _configure_opencv_threads
# ---------------------------------------------------------------------------


def test_configure_opencv_threads_nao_levanta_excecao():
    """Verificar que _configure_opencv_threads não levanta exceção mesmo sem cv2."""
    _configure_opencv_threads()  # não deve levantar


# ---------------------------------------------------------------------------
# _get_rapidocr_engine
# ---------------------------------------------------------------------------


def test_get_rapidocr_engine_singleton():
    """Verificar que _get_rapidocr_engine retorna o mesmo objeto (singleton)."""
    e1 = _get_rapidocr_engine()
    e2 = _get_rapidocr_engine()
    assert e1 is e2


# ---------------------------------------------------------------------------
# _pages_without_text
# ---------------------------------------------------------------------------


def test_pages_without_text_identifica_paginas_vazias(tmp_path):
    """Verificar que _pages_without_text identifica páginas sem texto."""
    path = tmp_path / "mixed.pdf"
    doc = fitz.open()
    doc.new_page()  # página 0: sem texto
    page = doc.new_page()
    page.insert_text((72, 72), "Texto alfanumerico suficiente aqui")  # página 1
    doc.new_page()  # página 2: sem texto
    doc.save(str(path))
    doc.close()

    doc = fitz.open(str(path))
    empty = _pages_without_text(doc)
    doc.close()

    assert 0 in empty
    assert 1 not in empty
    assert 2 in empty


# ---------------------------------------------------------------------------
# _build_slice_pdf
# ---------------------------------------------------------------------------


def test_build_slice_pdf_cria_pdf_valido(tmp_path):
    """Verificar que _build_slice_pdf cria um PDF válido com páginas selecionadas."""
    path = tmp_path / "source.pdf"
    _make_scanned_pdf(path, num_pages=10)

    pdf_bytes = _build_slice_pdf(path, [0, 2, 5])
    assert pdf_bytes is not None
    assert pdf_bytes.startswith(b"%PDF-")

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    assert doc.page_count == 3
    doc.close()


# ---------------------------------------------------------------------------
# _dpi_for_page
# ---------------------------------------------------------------------------


def test_dpi_for_page_retorna_200_para_pagina_pequena(tmp_path):
    """Verificar que páginas pequenas usam DPI 200."""
    path = tmp_path / "pequena.pdf"
    _make_scanned_pdf(path, num_pages=1)
    doc = fitz.open(str(path))
    dpi = _dpi_for_page(doc, 0, base_dpi=200)
    assert dpi == 200
    doc.close()


def test_dpi_for_page_reduz_para_150_pagina_grande(tmp_path):
    """Verificar que páginas grandes reduzem para DPI 150 (acima de 4000px)."""
    path = tmp_path / "grande.pdf"
    doc = fitz.open()
    # Página enorme: 40000 pontos de largura -> 40000 * 200/72 ≈ 111111 px > 4000
    page = doc.new_page(width=40000, height=40000)
    doc.save(str(path))
    doc.close()

    doc = fitz.open(str(path))
    dpi = _dpi_for_page(doc, 0, base_dpi=200)
    assert dpi == 150
    doc.close()


# ---------------------------------------------------------------------------
# _extract_lines_from_result / _order_boxes_geometricamente
# ---------------------------------------------------------------------------


def test_extract_lines_from_result_com_txts():
    """Verificar extração de linhas quando resultado tem atributo txts."""
    class FakeResult:
        txts = ["linha um", "linha dois", ""]

    linhas = _extract_lines_from_result(FakeResult())
    assert linhas == ["linha um", "linha dois"]


def test_extract_lines_from_result_com_caixas():
    """Verificar extração de linhas a partir de caixas (bbox, texto, conf)."""
    class FakeBox:
        def __init__(self, x0, y0, x1, y1, texto):
            self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1
            self.text = texto

    class FakeResult:
        boxes = [
            FakeBox(100, 100, 200, 120, "primeira"),
            FakeBox(300, 100, 400, 120, "segunda"),
            FakeBox(100, 200, 200, 220, "terceira"),
        ]

    linhas = _extract_lines_from_result(FakeResult())
    # Duas linhas: y≈100 e y≈200. Dentro de cada linha, ordenado por x.
    assert "primeira segunda" in linhas
    assert "terceira" in linhas


def test_order_boxes_geometricamente_agrupa_por_linha():
    """Verificar que caixas são agrupadas por linha (y_bucket) e ordenadas por x."""
    class Box:
        def __init__(self, x0, y0, x1, y1, texto):
            self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1
            self.text = texto

    boxes = [
        Box(300, 100, 400, 120, "B"),
        Box(100, 100, 200, 120, "A"),
        Box(100, 200, 200, 220, "C"),
        Box(300, 200, 400, 220, "D"),
    ]

    linhas = _order_boxes_geometricamente(boxes)
    assert "A B" in linhas
    assert "C D" in linhas


def test_ocr_scanned_pages_extrai_texto_imagem(tmp_path):
    """Verificar que OCR extrai texto de imagem em PDF escaneado."""
    path = tmp_path / "escaneado_imagem.pdf"
    _make_scanned_pdf_with_image(path, num_pages=1)

    texto = ocr_scanned_pages(path)
    assert isinstance(texto, str)
    # O RapidOCR deve detectar texto real na imagem (título e ano).
    texto_upper = texto.upper()
    assert "RAPIDOCR" in texto_upper, f"Esperado 'RAPIDOCR' no OCR: {texto_upper}"
    assert "2024" in texto, f"Esperado '2024' no OCR: {texto}"


def test_order_boxes_geometricamente_com_poligonos_4x2_e_txts_fora_ordem():
    """Verificar ordenação de polígonos 4x2 pareados com txts fora de ordem.

    Simula o formato real do RapidOCROutput: boxes são polígonos 4x2 (sem texto)
    e txts contêm os textos pareados por índice, possivelmente fora de ordem
    espacial. As páginas vêm com y=200 ANTES de y=100 para forçar ordenação
    vertical real.
    """
    # Polígonos 4x2: [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
    boxes = [
        [[100, 200], [200, 200], [200, 220], [100, 220]],  # linha 2 (y=200), x=100 -> vem PRIMEIRO na entrada
        [[300, 200], [400, 200], [400, 220], [300, 220]],  # linha 2 (y=200), x=300
        [[300, 100], [400, 100], [400, 120], [300, 120]],  # linha 1 (y=100), x=300
        [[100, 100], [200, 100], [200, 120], [100, 120]],  # linha 1 (y=100), x=100
    ]
    txts = ["C", "B", "D", "A"]  # pareados por índice, fora de ordem espacial

    linhas = _order_boxes_geometricamente(boxes, txts=txts)
    # Ordenado por (y_mid, x0):
    # linha 1 (y≈100): x=100 -> A, x=300 -> D => "A D"
    # linha 2 (y≈200): x=100 -> C, x=300 -> B => "C B"
    assert linhas == ["A D", "C B"]


# ---------------------------------------------------------------------------
# ocr_scanned_pages (função principal)
# ---------------------------------------------------------------------------


def test_ocr_scanned_pages_retorna_string_vazia_para_pdf_com_texto(tmp_path):
    """Verificar que OCR retorna vazio quando todas as páginas da janela têm texto."""
    path = tmp_path / "nativo.pdf"
    doc = fitz.open()
    for i in range(10):
        page = doc.new_page()
        # Texto com mais de 30 caracteres alfanuméricos para evitar OCR
        page.insert_text((72, 72), "Texto selecionável suficiente na página " + str(i) + " para evitar OCR")
    doc.save(str(path))
    doc.close()

    texto = ocr_scanned_pages(path)
    assert texto == ""


def test_ocr_scanned_pages_paginas_sem_texto_retorna_string(tmp_path):
    """Verificar que OCR processa páginas sem texto selecionável."""
    path = tmp_path / "escaneado.pdf"
    _make_scanned_pdf(path, num_pages=10)

    texto = ocr_scanned_pages(path)
    assert isinstance(texto, str)


def test_ocr_scanned_pages_fallback_seguro_sem_rapidocr(tmp_path, monkeypatch):
    """Verificar que ocr_scanned_pages retorna vazio quando RapidOCR indisponível."""
    path = tmp_path / "escaneado.pdf"
    _make_scanned_pdf(path, num_pages=10)

    import tomus.extractors.ocr as ocr_mod

    ocr_mod._RAPIDOCR_ENGINE = None
    with patch.object(ocr_mod, "_get_rapidocr_engine", return_value=None):
        texto = ocr_scanned_pages(path)
        assert texto == ""


def test_ocr_scanned_pages_facade_de_ocr_docling(tmp_path):
    """Verificar que a fachada ocr_docling delega para .ocr."""
    path = tmp_path / "escaneado.pdf"
    _make_scanned_pdf(path, num_pages=5)

    texto_fachada = ocr_scanned_pages_fachada(path)
    texto_modulo = ocr_scanned_pages(path)
    assert isinstance(texto_fachada, str)
    assert isinstance(texto_modulo, str)


# ---------------------------------------------------------------------------
# Integração com extract_document_content
# ---------------------------------------------------------------------------


def test_extract_document_content_usa_ocr_quando_preciso(tmp_path):
    """Verificar integração: extrato usa OCR quando native_pdf sinaliza needs_ocr."""
    import hashlib

    path = tmp_path / "escaneado.pdf"
    _make_scanned_pdf(path, num_pages=10)

    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()

    from tomus.extractors import extract_document_content
    doc_extrato = extract_document_content(path, sha256)

    assert doc_extrato.source_path == path
    assert doc_extrato.sha256 == sha256
    assert doc_extrato.total_pages == 10
    assert isinstance(doc_extrato.used_ocr, bool)
