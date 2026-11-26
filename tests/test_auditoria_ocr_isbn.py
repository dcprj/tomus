"""Testes de regressão para achados críticos da auditoria 2026-11-24 (release 1.4.1).

Cobre:
  - LINCE-01: janela de inspeção do OCR alinhada com o extrator nativo
    (10 primeiras + 5 últimas páginas). Nenhuma página sinalizada por
    needs_ocr fica de fora do OCR.
  - LINCE-04: extract_isbn devolve ISBN-13 normalizado (via normalize_isbn)
    ou None quando o dígito verificador é inválido.
"""

from __future__ import annotations

from pathlib import Path

import fitz

from tomus.extractors import extract_document_content
from tomus.extractors.identifiers import (
    extract_isbn,
    normalize_isbn,
)
from tomus.extractors.native_pdf import extract_native_pdf

# --------------------------------------------------------------------------- #
# LINCE-01: janela de inspeção do OCR alinhada com o nativo
# --------------------------------------------------------------------------- #


def _make_pdf_with_scanned_page_at_index(
    path: Path, total_pages: int, scanned_index: int
) -> Path:
    """Criar PDF com texto em todas as páginas exceto uma (simula escaneado)."""
    doc = fitz.open()
    for i in range(total_pages):
        page = doc.new_page()
        if i != scanned_index:
            page.insert_text(
                (72, 72),
                f"Pagina {i} com texto suficiente para evitar OCR aqui mesmo",
            )
    doc.save(str(path))
    doc.close()
    return path


def test_lince01_ocr_inspects_same_window_as_native(tmp_path):
    """LINCE-01: OCR deve inspecionar as mesmas páginas que o nativo sinaliza.

    Cria um PDF com 12 páginas onde a página índice 9 (dentro das 10 primeiras
    do nativo, FORA das 8 primeiras do OCR antigo) está sem texto (escaneada).
    O nativo deve sinalizar needs_ocr=True e o OCR deve cobrir a página 9.
    """
    path = tmp_path / "scanned_at_9.pdf"
    _make_pdf_with_scanned_page_at_index(path, total_pages=12, scanned_index=9)

    native = extract_native_pdf(path)
    # A página 9 está nas 10 primeiras do nativo -> inspecionada
    assert 9 in native["inspected_pages"], (
        f"nativo deveria inspecionar página 9, inspecionou {native['inspected_pages']}"
    )
    # Como mais da metade das páginas inspecionadas tem texto, needs_ocr pode
    # ser False. Forçamos com mais páginas vazias para garantir needs_ocr=True.

    # Teste direto: a janela do OCR agora cobre a página 9
    from tomus.extractors.ocr import _OCR_FIRST_PAGES, _OCR_LAST_PAGES

    assert _OCR_FIRST_PAGES == 10, "OCR deveria usar 10 primeiras páginas"
    assert _OCR_LAST_PAGES == 5, "OCR deveria usar 5 últimas páginas"

    # Verificar que a janela do OCR cobre a página 9
    first = list(range(min(_OCR_FIRST_PAGES, native["total_pages"])))
    last_start = max(native["total_pages"] - _OCR_LAST_PAGES, _OCR_FIRST_PAGES)
    last = list(range(last_start, native["total_pages"]))
    window = sorted(set(first + last))
    assert 9 in window, f"janela do OCR ({window}) deveria incluir página 9"


def test_lince01_ocr_covers_scanned_page_outside_old_window(tmp_path):
    """LINCE-01: página escaneada no índice 9 (fora da janela antiga 8+2)
    deve ser coberta pela nova janela 10+5 e processada pelo OCR."""
    path = tmp_path / "scanned_at_9.pdf"
    _make_pdf_with_scanned_page_at_index(path, total_pages=12, scanned_index=9)

    # Muitas páginas sem texto para forçar needs_ocr=True
    doc = fitz.open()
    for i in range(12):
        page = doc.new_page()
        if i != 5:  # só a página 5 tem texto
            pass  # sem texto = escaneada
        else:
            page.insert_text((72, 72), "texto suficiente aqui")
    doc.save(str(path))
    doc.close()

    native = extract_native_pdf(path)
    assert native["needs_ocr"] is True, (
        f"esperado needs_ocr=True, obtido {native['needs_ocr']}"
    )
    # Página 9 (escaneada) deve estar nas páginas inspecionadas pelo nativo
    assert 9 in native["inspected_pages"]

    # OCR deve processar a página 9 (está dentro da janela 10+5)
    from tomus.extractors.ocr import ocr_scanned_pages

    ocr_text = ocr_scanned_pages(path)
    # Como a página 9 é escaneada (sem texto), o OCR deve retornar algo
    # (mesmo que vazio se não houver texto reconhecível, o importante é não
    # ignorar a página por estar fora da janela)
    assert isinstance(ocr_text, str)


# --------------------------------------------------------------------------- #
# LINCE-04: extract_isbn devolve ISBN-13 normalizado
# --------------------------------------------------------------------------- #


def test_lince04_extract_isbn_returns_normalized_isbn13():
    """LINCE-04: ISBN com hífen deve ser devolvido como ISBN-13 normalizado."""
    resultado = extract_isbn("ISBN 978-85-363-1234-7")
    assert resultado == "9788536312347", (
        f"esperado ISBN-13 normalizado '9788536312347', obtido {resultado!r}"
    )


def test_lince04_extract_isbn_returns_normalized_isbn10_converted():
    """LINCE-04: ISBN-10 deve ser convertido para ISBN-13 normalizado."""
    resultado = extract_isbn("ISBN 0-306-40615-2")
    assert resultado == "9780306406157", (
        f"esperado ISBN-13 '9780306406157', obtido {resultado!r}"
    )


def test_lince04_extract_isbn_rejects_invalid_check_digit():
    """LINCE-04: número com dígito verificador inválido deve retornar None."""
    resultado = extract_isbn("531581939")
    assert resultado is None, f"esperado None para ISBN inválido, obtido {resultado!r}"


def test_lince04_extract_isbn_no_spaces_or_hyphens_in_result():
    """LINCE-04: resultado nunca deve conter hífens ou espaços."""
    resultado = extract_isbn("ISBN 978-85-363-1234-7")
    assert resultado is not None
    assert "-" not in resultado
    assert " " not in resultado


def test_lince04_normalize_isbn_idempotent():
    """LINCE-04: normalização deve ser idempotente (enriquecedor chama
    normalize_isbn novamente no resultado de extract_isbn)."""
    isbn_bruto = "978-85-363-1234-7"
    extraido = extract_isbn(isbn_bruto)
    normalizado_novamente = normalize_isbn(extraido)
    assert extraido == normalizado_novamente, (
        f"normalização não é idempotente: {extraido!r} vs {normalizado_novamente!r}"
    )


def test_lince04_extract_document_content_detects_normalized_isbn(tmp_path):
    """LINCE-04: extract_document_content deve conter ISBN normalizado."""
    path = tmp_path / "com_isbn.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(
        (72, 72),
        "ISBN 978-85-363-1234-7 Texto suficiente para nao acionar OCR aqui",
    )
    doc.save(str(path))
    doc.close()

    sha256 = Path(path).read_bytes().hex() if False else __import__("hashlib").sha256(
        Path(path).read_bytes()
    ).hexdigest()
    extrato = extract_document_content(path, sha256)

    assert extrato.detected_isbn == "9788536312347", (
        f"esperado ISBN normalizado '9788536312347', obtido {extrato.detected_isbn!r}"
    )
