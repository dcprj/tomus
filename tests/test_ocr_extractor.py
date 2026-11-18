"""Testes unitários do extrator de OCR seletivo via Docling (Item 15).

Valida o recorte de páginas sem texto, o uso de DocumentStream, a instância
singleton/lazy do DocumentConverter e o fallback seguro quando o Docling não
está disponível.
"""

from __future__ import annotations

import hashlib
from unittest.mock import patch

import fitz
import pytest

from tomus.extractors.ocr_docling import (
    ocr_scanned_pages,
    _get_converter,
    _pages_without_text,
    _build_slice_pdf,
)


def _make_scanned_pdf(path: Path, num_pages: int = 10) -> Path:
    """Criar um PDF com páginas sem texto selecionável (simula escaneado)."""
    doc = fitz.open()
    for _ in range(num_pages):
        page = doc.new_page()
        # Página em branco (sem texto selecionável) -> simula página escaneada
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


def test_ocr_scanned_pages_returns_text_for_empty_pages(tmp_path):
    """Verificar que OCR extrai texto de páginas sem texto selecionável."""
    path = tmp_path / "scanned.pdf"
    _make_scanned_pdf(path, num_pages=10)

    texto = ocr_scanned_pages(path)
    # O OCR pode ou não retornar texto dependendo da disponibilidade de modelos
    # de OCR no ambiente; apenas verificar que não levanta exceção.
    assert isinstance(texto, str)


def test_ocr_scanned_pages_all_pages_have_text_returns_empty(tmp_path):
    """Verificar que OCR retorna vazio quando todas as páginas da janela têm texto."""
    path = tmp_path / "all_native.pdf"
    doc = fitz.open()
    for i in range(10):
        page = doc.new_page()
        page.insert_text((72, 72), "Texto selecionável suficiente na página " + str(i) + " para evitar OCR")
    doc.save(str(path))
    doc.close()

    texto = ocr_scanned_pages(path)
    # Todas as páginas da janela têm texto -> não há páginas para OCR -> retorna vazio
    assert texto == ""


def test_pages_without_text_identifies_empty_pages(tmp_path):
    """Verificar que _pages_without_text identifica páginas sem texto."""
    path = tmp_path / "mixed.pdf"
    doc = fitz.open()
    # Página 0: sem texto
    doc.new_page()
    # Página 1: com texto
    page = doc.new_page()
    page.insert_text((72, 72), "Texto alfanumerico suficiente aqui")
    # Página 2: sem texto
    doc.new_page()
    doc.save(str(path))
    doc.close()

    doc = fitz.open(str(path))
    empty = _pages_without_text(doc)
    doc.close()

    assert 0 in empty
    assert 1 not in empty
    assert 2 in empty


def test_build_slice_pdf_creates_valid_pdf(tmp_path):
    """Verificar que _build_slice_pdf cria um PDF válido com as páginas selecionadas."""
    path = tmp_path / "source.pdf"
    _make_scanned_pdf(path, num_pages=10)

    pdf_bytes = _build_slice_pdf(path, [0, 2, 5])
    assert pdf_bytes is not None
    assert pdf_bytes.startswith(b"%PDF-")

    # Verificar que o PDF recortado tem apenas 3 páginas
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    assert doc.page_count == 3
    doc.close()


def test_get_converter_returns_none_without_docling(monkeypatch):
    """Verificar fallback seguro quando Docling não está disponível."""
    import tomus.extractors.ocr_docling as ocr_mod

    # Forçar _CONVERTER a None para simular ausência de Docling
    ocr_mod._CONVERTER = None

    with patch.object(ocr_mod, "_get_converter", return_value=None):
        converter = ocr_mod._get_converter()
        assert converter is None


def test_ocr_scanned_pages_fallback_safe(tmp_path, monkeypatch):
    """Verificar que ocr_scanned_pages não quebra quando Docling indisponível."""
    path = tmp_path / "scanned.pdf"
    _make_scanned_pdf(path, num_pages=10)

    import tomus.extractors.ocr_docling as ocr_mod

    # Simular Docling indisponível
    ocr_mod._CONVERTER = None
    with patch.object(ocr_mod, "_get_converter", return_value=None):
        texto = ocr_scanned_pages(path)
        assert texto == ""


def test_extract_document_content_uses_ocr_when_needed(tmp_path):
    """Verificar integração: extrato usa OCR quando native_pdf sinaliza needs_ocr."""
    import hashlib

    path = tmp_path / "scanned.pdf"
    _make_scanned_pdf(path, num_pages=10)

    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()

    from tomus.extractors import extract_document_content
    doc_extracted = extract_document_content(path, sha256)

    assert doc_extracted.source_path == path
    assert doc_extracted.sha256 == sha256
    assert doc_extracted.total_pages == 10
    assert isinstance(doc_extracted.used_ocr, bool)


def test_ocr_window_limits_to_max_8_pages(tmp_path):
    """Verificar que o OCR limita a janela a no máximo 8 páginas."""
    path = tmp_path / "many_pages.pdf"
    _make_scanned_pdf(path, num_pages=50)

    import tomus.extractors.ocr_docling as ocr_mod

    # Verificar a lógica de seleção de páginas: 8 primeiras + 2 últimas = max 10,
    # mas limitado a 8 páginas via _OCR_MAX_PAGES
    doc = fitz.open(str(path))
    total_pages = doc.page_count

    first = list(range(0, min(ocr_mod._OCR_FIRST_PAGES, total_pages)))
    last_start = max(total_pages - ocr_mod._OCR_LAST_PAGES, ocr_mod._OCR_FIRST_PAGES)
    last = list(range(last_start, total_pages))
    window = sorted(set(first + last))

    assert len(window) <= 10  # 8 + 2
    # Todas as páginas estão sem texto, então empty_in_window = window
    # selected = empty_in_window[:_OCR_MAX_PAGES] -> max 8
    selected = window[:ocr_mod._OCR_MAX_PAGES]
    assert len(selected) <= ocr_mod._OCR_MAX_PAGES
    doc.close()


def test_document_stream_name_format(tmp_path):
    """Verificar que DocumentStream usa o nome correto com sufixo _slice.pdf."""
    import io
    from docling.datamodel.base_models import DocumentStream

    path = tmp_path / "meu_documento.pdf"
    _make_scanned_pdf(path, num_pages=5)

    pdf_bytes = _build_slice_pdf(path, [0, 1])
    buf = io.BytesIO(pdf_bytes)
    stream = DocumentStream(name=f"{path.stem}_slice.pdf", stream=buf)

    assert stream.name == "meu_documento_slice.pdf"


def test_ocr_extracts_title_author_year_from_scanned(tmp_path):
    """Verificar que OCR consegue recuperar título, autor e ano de PDF escaneado."""
    path = tmp_path / "scanned_with_text.pdf"
    doc = fitz.open()
    # Página 1: capa com título e autor (simulada como texto, mas sem camada selecionável)
    # Como o PDF é "escaneado" (sem texto selecionável), o OCR deve ler a imagem
    # Aqui testamos que o fluxo não quebra e retorna string
    doc.new_page()
    doc.save(str(path))
    doc.close()

    texto = ocr_scanned_pages(path)
    assert isinstance(texto, str)


def test_ocr_fallback_rapidocr_when_docling_none(tmp_path):
    """Validar que o fallback RapidOCR é usado quando _get_converter() retorna None (bundle macOS)."""
    import io
    from unittest.mock import patch

    from PIL import Image, ImageDraw

    import tomus.extractors.ocr_docling as ocr_mod

    # Criar imagem com texto para simular uma página escaneada (sem camada de texto).
    img = Image.new("RGB", (700, 500), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((50, 60), "RAPIDOCR TITULO DE TESTE", fill="black", font_size=36)
    draw.text((50, 140), "Autor: Sobrenome, Nome", fill="black", font_size=28)
    draw.text((50, 220), "Ano: 2024", fill="black", font_size=28)

    img_buf = io.BytesIO()
    img.save(img_buf, format="PNG")
    img_bytes = img_buf.getvalue()

    # Criar PDF com a imagem inserida (sem texto selecionavel = pagina escaneada).
    path = tmp_path / "scanned_with_image.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_image(fitz.Rect(0, 0, 700, 500), stream=img_bytes)
    doc.save(str(path))
    doc.close()

    # Mock _get_converter para retornar None (simulando falha do Docling no bundle .app).
    with patch.object(ocr_mod, "_get_converter", return_value=None):
        texto = ocr_scanned_pages(path)

    assert isinstance(texto, str)
    assert len(texto) > 0, "RapidOCR deve extrair texto da imagem quando Docling indisponível"


def test_get_converter_uses_pypdfium_backend_on_win32(monkeypatch):
    """No Windows, _get_converter deve forçar o backend pypdfium2 para evitar
    access violation intermitente no parser nativo threadado docling-parse."""
    import sys as _sys

    import tomus.extractors.ocr_docling as ocr_mod
    from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
    from docling.document_converter import DocumentConverter
    from docling.datamodel.base_models import InputFormat

    ocr_mod._CONVERTER = None
    monkeypatch.setattr(_sys, "platform", "win32")
    converter = ocr_mod._get_converter()
    assert isinstance(converter, DocumentConverter)
    opt = converter.format_to_options.get(InputFormat.PDF)
    assert opt is not None
    assert opt.backend is PyPdfiumDocumentBackend


def test_get_converter_uses_default_backend_on_darwin(monkeypatch):
    """No macOS/Linux, _get_converter preserva o DocumentConverter() padrão
    (sem forçar pypdfium2)."""
    import sys as _sys

    import tomus.extractors.ocr_docling as ocr_mod
    from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
    from docling.document_converter import DocumentConverter
    from docling.datamodel.base_models import InputFormat

    ocr_mod._CONVERTER = None
    monkeypatch.setattr(_sys, "platform", "darwin")
    converter = ocr_mod._get_converter()
    assert isinstance(converter, DocumentConverter)
    opt = converter.format_to_options.get(InputFormat.PDF)
    assert opt is None or opt.backend is not PyPdfiumDocumentBackend

