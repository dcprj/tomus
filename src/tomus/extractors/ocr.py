"""OCR seletivo de páginas escaneadas via RapidOCR + PyMuPDF (Opção B1).

Recebe o caminho de um PDF escaneado, recorta via PyMuPDF as páginas sem texto
dentro da janela das 8 primeiras e 2 últimas páginas (máximo de 8 páginas) e
executa OCR direto com RapidOCR renderizando cada página via fitz.get_pixmap()
a 200 DPI (com guarda de memória que reduz para 150 DPI quando a página
ultrapassa 4000 px na maior dimensão).

Trata exceções ou ausência do modelo com fallback seguro (retorna texto vazio)
sem quebrar o processo.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF

_logger = logging.getLogger("tomus.extractors.ocr")

# Janela de inspeção para OCR seletivo (Item 15).
_OCR_FIRST_PAGES = 8
_OCR_LAST_PAGES = 2
_OCR_MAX_PAGES = 8
_ALPHANUM_THRESHOLD = 30

# Limite de maior dimensão em pixels (a 200 DPI) acima do qual reduzimos para
# 150 DPI a fim de evitar alocação excessiva de memória em páginas grandes.
_MAX_DIM_PX_AT_200_DPI = 4000


_RAPIDOCR_ENGINE: Optional[object] = None


def _configure_opencv_threads():
    """Definir defensivamente cv2.setNumThreads(0) e OPENCV_FOR_THREADS_NUM=1.

    Evita contenção de threads do Apple GCD com onnxruntime durante o OCR,
    especialmente em bundles congelados (.app) do PyInstaller no macOS.
    """
    try:
        os.environ.setdefault("OPENCV_FOR_THREADS_NUM", "1")
        import cv2  # type: ignore

        cv2.setNumThreads(0)
    except Exception:  # pragma: no cover - cv2 pode não estar instalado
        pass


def _get_rapidocr_engine():
    """Retornar uma instância singleton/lazy do mecanismo RapidOCR.

    Retorna ``None`` quando o RapidOCR não estiver disponível ou não puder ser
    instanciado (fallback seguro).
    """
    _configure_opencv_threads()
    global _RAPIDOCR_ENGINE
    if _RAPIDOCR_ENGINE is not None:
        return _RAPIDOCR_ENGINE
    try:
        from rapidocr import RapidOCR  # type: ignore

        _RAPIDOCR_ENGINE = RapidOCR()
        return _RAPIDOCR_ENGINE
    except Exception as exc:  # pragma: no cover - ambiente sem RapidOCR
        _logger.warning("RapidOCR indisponível no ambiente: %s", exc)
        _RAPIDOCR_ENGINE = None
        return None


def _pages_without_text(doc: fitz.Document) -> list[int]:
    """Listar índices de páginas com menos de 30 caracteres alfanuméricos úteis
    (escaneadas ou vazias)."""
    empty_pages: list[int] = []
    for idx in range(doc.page_count):
        text = doc[idx].get_text() or ""
        if sum(1 for ch in text if ch.isalnum()) < _ALPHANUM_THRESHOLD:
            empty_pages.append(idx)
    return empty_pages


def _build_slice_pdf(path: Path, pages: list[int]) -> Optional[bytes]:
    """Recortar as ``pages`` indicadas para um novo PDF em memória (bytes).

    Usa ``doc.insert_pdf`` para copiar apenas as páginas selecionadas.
    Retorna ``None`` em caso de falha.
    """
    try:
        src = fitz.open(str(path))
        try:
            out = fitz.open()  # documento vazio
            for idx in pages:
                out.insert_pdf(src, from_page=idx, to_page=idx)
            buf = __import__("io").BytesIO()
            out.save(buf, deflate=True)
            return buf.getvalue()
        finally:
            src.close()
            out.close()
    except Exception:
        return None


def _dpi_for_page(doc: fitz.Document, idx: int, base_dpi: int = 200) -> int:
    """Escolher a DPI de renderização para a página ``idx``.

    Se a maior dimensão da página renderizada a ``base_dpi`` ultrapassar
    ``_MAX_DIM_PX_AT_200_DPI`` pixels, reduzimos para 150 DPI a fim de evitar
    alocação excessiva de memória.
    """
    page = doc[idx]
    rect = page.rect
    # PyMuPDF usa pontos (72 dpi). Fator de escala para converter pontos em px.
    scale = base_dpi / 72.0
    max_dim = max(rect.width, rect.height) * scale
    if max_dim > _MAX_DIM_PX_AT_200_DPI:
        return 150
    return base_dpi


def _ocr_with_rapidocr(doc: fitz.Document, pages: list[int]) -> str:
    """Extrair texto via RapidOCR renderizando páginas selecionadas.

    Renderiza cada página em ``pages`` como PNG via PyMuPDF (DPI 200 por
    padrão, 150 DPI quando a página é muito grande) e passa os bytes para a
    instância RapidOCR, juntando as linhas de texto com quebra de linha.

    A ordenação do texto segue uma heurística geométrica leve (y_bucket, x):
    agrupa caixas por linha vertical usando tolerância proporcional à altura
    mediana das caixas e ordena por x_min dentro de cada linha, com fallback
    para iterável ou txts quando as caixas não estiverem disponíveis.
    """
    engine = _get_rapidocr_engine()
    if engine is None:
        return ""

    linhas: list[str] = []
    for idx in pages:
        try:
            dpi = _dpi_for_page(doc, idx, base_dpi=200)
            pix = doc[idx].get_pixmap(dpi=dpi)
            png_bytes = pix.tobytes("png")
            result = engine(png_bytes)
            if result is None:
                continue

            linhas.extend(_extract_lines_from_result(result))
        except Exception as exc:  # pragma: no cover - defesa por página
            _logger.warning("RapidOCR falhou na página %d: %s", idx, exc)
            continue

    return "\n".join(linhas).strip()


def _extrair_caixa(box: object) -> Optional[tuple[float, float, float, float, str]]:
    """Extrair (x0, y0, x1, y1, texto) de uma caixa de resultado do RapidOCR.

    Suporta:
      - objeto com atributos x0/y0/x1/y1 e text;
      - tupla/lista de 5 elementos: (x0, y0, x1, y1, texto);
      - polígono 4x2 pareado com txts[i]: lista de 4 pontos [[x1,y1],[x2,y2],...].
    """
    try:
        if hasattr(box, "x0"):
            return (
                float(box.x0),
                float(box.y0),
                float(box.x1),
                float(box.y1),
                str(getattr(box, "text", "")),
            )
        if isinstance(box, (list, tuple)) and len(box) >= 5:
            return (
                float(box[0]),
                float(box[1]),
                float(box[2]),
                float(box[3]),
                str(box[4]),
            )
    except Exception:
        return None
    return None


def _extrair_poligono_4x2(box: object) -> Optional[tuple[float, float, float, float]]:
    """Extrair (x0, y0, x1, y1) de um polígono 4x2 (lista de 4 pontos)."""
    try:
        pts = list(box)
        if len(pts) != 4:
            return None
        xs = [float(p[0]) for p in pts]
        ys = [float(p[1]) for p in pts]
        return (min(xs), min(ys), max(xs), max(ys))
    except Exception:
        return None


def _extract_lines_from_result(result: object) -> list[str]:
    """Extrair linhas de texto do resultado do RapidOCR.

    Lê ``res.boxes`` (polígonos 4x2 sem texto) e ``res.txts`` (textos pareados
    por índice), passando ambos para ordenação geométrica. Fallback para
    ``res.txts`` sozinho ou iteração direta quando as caixas não estão
    disponíveis.
    """
    boxes = getattr(result, "boxes", None)
    txts = getattr(result, "txts", None)

    if boxes is not None:
        return _order_boxes_geometricamente(boxes, txts=txts)

    if txts:
        return [str(t) for t in txts if t]

    # Último recurso: iterar sobre o resultado como sequência de caixas.
    linhas: list[str] = []
    try:
        for box in result:
            if len(box) >= 5:
                linhas.append(str(box[4]))
    except Exception:
        pass
    return linhas


def _order_boxes_geometricamente(
    boxes: object, txts: Optional[list[str]] = None
) -> list[str]:
    """Ordenar caixas de texto geometricamente por (y_mid, x0).

    Aceita:
      - objetos com atributos x0/y0/x1/y1 e text;
      - tuplas/listas de 5 elementos: (x0, y0, x1, y1, texto);
      - polígonos 4x2 (lista de 4 pontos [x,y]) pareados via txts[i].

    As caixas válidas são ordenadas previamente por (y_mid, x0) crescente e
    depois agrupadas em linhas usando anchor_y_mid com tolerância
    max(8.0, mediana_altura*0.55). Dentro de cada linha, ordena por x0.
    """
    caixas: list[tuple[float, float, float, float, str]] = []
    try:
        for i, box in enumerate(boxes):
            poligono = _extrair_poligono_4x2(box)
            if poligono is not None:
                texto = str(txts[i]) if txts is not None and i < len(txts) else ""
                caixas.append((poligono[0], poligono[1], poligono[2], poligono[3], texto))
                continue

            extraida = _extrair_caixa(box)
            if extraida is not None:
                caixas.append(extraida)
    except Exception:
        pass

    if not caixas:
        # Fallback seguro: tentar apenas txts.
        if txts:
            return [str(t) for t in txts if t]
        return []

    # Ordenar previamente por (y_mid, x0) crescente.
    caixas.sort(key=lambda c: ((c[1] + c[3]) / 2.0, c[0]))

    # Altura mediana para tolerância de linha.
    alturas = sorted(c[3] - c[1] for c in caixas if c[3] > c[1])
    if not alturas:
        return [c[4] for c in caixas]
    mediana_altura = alturas[len(alturas) // 2]
    tolerancia = max(8.0, mediana_altura * 0.55)

    # Agrupar por linha usando anchor_y_mid.
    # Cada elemento da linha é (x0, texto); a referência y_mid é armazenada
    # separadamente como primeiro elemento da tupla externa.
    linhas: list[tuple[float, list[tuple[float, str]]]] = []  # (y_mid_ref, [(x0, texto), ...])
    for x0, y0, x1, y1, texto in caixas:
        y_mid = (y0 + y1) / 2.0
        colocada = False
        for linha in linhas:
            ref_y_mid = linha[0]
            if abs(y_mid - ref_y_mid) <= tolerancia:
                linha[1].append((x0, texto))
                colocada = True
                break
        if not colocada:
            linhas.append((y_mid, [(x0, texto)]))

    resultado: list[str] = []
    for _, linha in linhas:
        # Ordenar dentro da linha por x0.
        linha_ordenada = sorted(linha, key=lambda m: m[0])
        textos = [t for _, t in linha_ordenada if t]
        if textos:
            resultado.append(" ".join(textos))

    return resultado


def ocr_scanned_pages(path: Path) -> str:
    """Executar OCR seletivo nas páginas sem texto do ``path``.

    Renderiza cada página selecionada via PyMuPDF a 200 DPI (ou 150 DPI quando
    a página é muito grande) e executa OCR direto com RapidOCR.

    Retorna o texto extraído, ou uma string vazia quando não há páginas para
    OCR, o RapidOCR não está disponível ou ocorre qualquer exceção
    (fallback seguro, nunca lança exceção para o chamador).
    """
    try:
        doc = fitz.open(str(path))
    except Exception as exc:  # pragma: no cover - defesa contra arquivo corrompido
        _logger.warning("Erro ao abrir PDF para OCR %s: %s", path.name, exc)
        return ""

    try:
        total_pages = doc.page_count

        # Janela: 8 primeiras e 2 últimas páginas, sem duplicar.
        first = list(range(0, min(_OCR_FIRST_PAGES, total_pages)))
        last_start = max(total_pages - _OCR_LAST_PAGES, _OCR_FIRST_PAGES)
        last = list(range(last_start, total_pages))
        window = sorted(set(first + last))

        # Apenas páginas sem texto dentro da janela.
        empty_in_window = [idx for idx in window if idx in _pages_without_text(doc)]

        if not empty_in_window:
            return ""

        # Limitar a no máximo 8 páginas.
        selected = empty_in_window[:_OCR_MAX_PAGES]

        return _ocr_with_rapidocr(doc, selected)
    except Exception as exc:  # pragma: no cover - defesa geral
        _logger.warning("Erro durante OCR seletivo para %s: %s", path.name, exc)
        return ""
    finally:
        try:
            doc.close()
        except Exception:
            pass
