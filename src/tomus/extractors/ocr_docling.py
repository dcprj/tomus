"""Fachada para o extrator de OCR seletivo (Item 15).

Mantida por compatibilidade com código existente e testes que importam de
``tomus.extractors.ocr_docling``. Toda a implementação real agora vive em
:mod:`tomus.extractors.ocr` (Opção B1: PyMuPDF 200 DPI + RapidOCR direto,
sem dependência do Docling).

Apenas re-exporta símbolos públicos para não quebrar importações existentes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .ocr import (  # noqa: F401
    _OCR_FIRST_PAGES,
    _OCR_LAST_PAGES,
    _OCR_MAX_PAGES,
    _ALPHANUM_THRESHOLD,
    _build_slice_pdf,
    _configure_opencv_threads,
    _get_rapidocr_engine,
    _ocr_with_rapidocr,
    _pages_without_text,
    ocr_scanned_pages,
)

__all__ = [
    "ocr_scanned_pages",
    "_OCR_FIRST_PAGES",
    "_OCR_LAST_PAGES",
    "_OCR_MAX_PAGES",
    "_ALPHANUM_THRESHOLD",
    "_configure_opencv_threads",
    "_get_rapidocr_engine",
    "_ocr_with_rapidocr",
    "_pages_without_text",
    "_build_slice_pdf",
]
