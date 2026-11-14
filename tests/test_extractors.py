"""Testes unitários dos extratores de conteúdo PDF (Itens 12 a 14).

Valida a extração nativa via PyMuPDF, a decisão de necessidade de OCR, a
detecção de Ficha Catalográfica CIP e a extração de identificadores DOI/ISBN.
"""

from __future__ import annotations

from pathlib import Path

from tomus.extractors import extract_document_content
from tomus.extractors.native_pdf import extract_native_pdf
from tomus.extractors.identifiers import (
    extract_doi,
    extract_isbn,
    detect_cip_page,
    extract_identifiers,
)


def test_extract_native_pdf_returns_metadata_and_text(tmp_path):
    """Verificar que a extração nativa retorna metadados, total de páginas e texto."""
    import fitz

    path = tmp_path / "sample_native.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Título do Documento de Teste\nAutor: Fulano, Teste")
    doc.save(str(path))
    doc.close()

    result = extract_native_pdf(path)
    assert "metadata" in result
    assert "total_pages" in result and result["total_pages"] >= 1
    assert "sampled_text" in result
    assert "needs_ocr" in result
    assert isinstance(result["needs_ocr"], bool)
    assert "file_size_bytes" in result


def test_needs_ocr_false_when_text_dense(tmp_path):
    """Verificar que needs_ocr é False quando há texto suficiente nas páginas."""
    import fitz

    path = tmp_path / "dense_text.pdf"
    doc = fitz.open()
    for _ in range(3):
        page = doc.new_page()
        page.insert_text((72, 72), "A" * 200 + "\n" + "B" * 200)
    doc.save(str(path))
    doc.close()

    result = extract_native_pdf(path)
    assert result["needs_ocr"] is False


def test_needs_ocr_true_when_text_sparse(tmp_path):
    """Verificar que needs_ocr é True quando a maioria das páginas tem pouco texto."""
    import fitz

    path = tmp_path / "sparse_text.pdf"
    doc = fitz.open()
    for i in range(10):
        page = doc.new_page()
        if i < 6:
            page.insert_text((72, 72), "x")  # menos de 30 chars alfanuméricos
        else:
            page.insert_text((72, 72), "A" * 200)
    doc.save(str(path))
    doc.close()

    result = extract_native_pdf(path)
    assert result["needs_ocr"] is True


def test_extract_document_content_coordination(tmp_path):
    """Verificar que extract_document_content coordena nativo + OCR + identificadores."""
    import fitz
    import hashlib

    path = tmp_path / "coordination_test.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "DOI: 10.1037/arc0000014\nISBN 978-85-363-1234-7\nFicha catalográfica\nCDD 150.19\nTexto suficiente para teste")
    doc.save(str(path))
    doc.close()

    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    doc_extracted = extract_document_content(path, sha256)

    assert doc_extracted.source_path == path
    assert doc_extracted.sha256 == sha256
    assert doc_extracted.total_pages >= 1
    assert doc_extracted.detected_doi == "10.1037/arc0000014"
    assert doc_extracted.detected_isbn == "9788536312347"
    assert "Ficha catalográfica" in doc_extracted.cip_text


def test_extract_doi_strict_regex_and_terminal_punct():
    """Verificar extração de DOI com regex estrita e limpeza de pontuação terminal."""
    assert extract_doi("Veja 10.1037/arc0000014. para mais") == "10.1037/arc0000014"
    assert extract_doi("https://doi.org/10.1000/xyz123,") == "10.1000/xyz123"
    assert extract_doi("não há doi aqui") is None


def test_extract_isbn_validates_with_stdnum():
    """Verificar validação de ISBN via stdnum.isbn.is_valid."""
    assert extract_isbn("ISBN 978-85-363-1234-7") == "9788536312347"
    assert extract_isbn("853660106X") == "853660106X"
    assert extract_isbn("531581939") is None  # número arbitrário, não ISBN válido
    assert extract_isbn("não há isbn aqui") is None


def test_detect_cip_page_markers():
    """Verificar detecção de Ficha Catalográfica por marcadores ABNT."""
    texto = """
    Sumário
    ...
    Ficha catalográfica
    Silva, João.
    Título da obra / João Silva. -- São Paulo : Editora, 2021.
    CDD 150.19
    """
    cip = detect_cip_page(texto)
    assert "Ficha catalográfica" in cip
    assert "CDD" in cip


def test_detect_cip_page_no_marker():
    """Verificar que detect_cip_page retorna vazio quando não há marcador CIP."""
    texto = "apenas texto comum sem nenhum marcador de catalografia"
    assert detect_cip_page(texto) == ""


def test_extract_identifiers_tuple():
    """Verificar que extract_identifiers retorna tupla (doi, isbn)."""
    texto = "DOI: 10.1109/5.771073, ISBN 0-306-40615-2"
    doi, isbn = extract_identifiers(texto)
    assert doi == "10.1109/5.771073"
    assert isbn == "0306406152"
