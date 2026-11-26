"""OCR seletivo de páginas escaneadas via RapidOCR + PyMuPDF (Opção B1).

Recebe o caminho de um PDF escaneado, recorta via PyMuPDF as páginas sem texto
dentro da janela das 10 primeiras e 5 últimas páginas (alinhada com o
extrator nativo em native_pdf.py, máximo de 15 páginas por teto de desempenho)
e executa OCR direto com RapidOCR renderizando cada página via
fitz.get_pixmap() a 150 DPI padrão (com guarda de memória que reduz para 120
DPI quando a página ultrapassa 4000 px na maior dimensão).

O teto de páginas OCR (_OCR_MAX_PAGES) permanece por desempenho, mas a janela
de inspeção agora cobre as mesmas páginas que o extrator nativo sinaliza em
needs_ocr, de modo que nenhuma página sinalizada fique de fora sem motivo
registrado. O early stop em 15.000 caracteres alfanuméricos úteis limita o
tempo de processamento na prática.

Processa as páginas em ordem de prioridade (primeiras 3, última, depois o
restante) e faz early stop quando há cobertura mínima com pelo menos
15.000 caracteres alfanuméricos úteis, juntando o texto final em ordem
crescente de índice de página (ordem natural do PDF, capa..contracapa).

Trata exceções ou ausência do modelo com fallback seguro (retorna texto vazio)
sem quebrar o processo, sem Threads custom nem CoreML (CPU default do ONNX).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import fitz  # PyMuPDF

_logger = logging.getLogger("tomus.extractors.ocr")

# Janela de inspeção para OCR seletivo (Item 15).
# Alinhada com o extrator nativo (native_pdf.py: _FIRST_PAGES=10, _LAST_PAGES=5)
# para que nenhuma página sinalizada por needs_ocr fique de fora do OCR.
_OCR_FIRST_PAGES = 10
_OCR_LAST_PAGES = 5
# Teto de páginas OCR por desempenho. A janela máxima possível é 15 (10+5),
# portanto 15 não exclui nenhuma página inspecionada pelo nativo. O early stop
# em _OCR_TARGET_ALPHANUM limita o tempo de processamento na prática.
_OCR_MAX_PAGES = 15
_ALPHANUM_THRESHOLD = 30

# DPI padrão de renderização (reduzido de 200 para 150 a fim de cortar ~16-21%
# do tempo do engine sem perder ano/mês/título da capa/folha de rosto).
_DEFAULT_OCR_DPI = 150

# Limite de maior dimensão em pixels (a _DEFAULT_OCR_DPI) acima do qual
# reduzimos um degrau (150 -> 120 DPI) a fim de evitar alocação excessiva de
# memória em páginas grandes.
_MAX_DIM_PX_AT_DEFAULT_DPI = 4000

# Alvo de caracteres alfanuméricos úteis para early stop do OCR seletivo. Ao
# atingir esse valor com cobertura mínima de páginas, para o processamento
# antecipadamente sem perder precisão da capa/folha de rosto.
_OCR_TARGET_ALPHANUM = 15_000


_RAPIDOCR_ENGINE: object | None = None


def _configure_opencv_threads():
    """Definir defensivamente cv2.setNumThreads(0) e OPENCV_FOR_THREADS_NUM=1.

    Evita contenção de threads do Apple GCD com onnxruntime durante o OCR,
    especialmente em bundles congelados (.app) do PyInstaller no macOS.
    """
    try:
        os.environ.setdefault("OPENCV_FOR_THREADS_NUM", "1")
        import cv2  # type: ignore

        cv2.setNumThreads(0)
    except Exception as exc:  # pragma: no cover - cv2 pode não estar instalado
        _logger.debug("cv2 não disponível para ajuste de threads: %s", exc)


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


def _build_slice_pdf(path: Path, pages: list[int]) -> bytes | None:
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


def _dpi_for_page(doc: fitz.Document, idx: int, base_dpi: int = _DEFAULT_OCR_DPI) -> int:
    """Escolher a DPI de renderização para a página ``idx``.

    Se a maior dimensão da página renderizada a ``base_dpi`` ultrapassar
    ``_MAX_DIM_PX_AT_DEFAULT_DPI`` pixels, reduzimos um degrau (150 -> 120 DPI)
    a fim de evitar alocação excessiva de memória em páginas grandes.
    """
    page = doc[idx]
    rect = page.rect
    # PyMuPDF usa pontos (72 dpi). Fator de escala para converter pontos em px.
    scale = base_dpi / 72.0
    max_dim = max(rect.width, rect.height) * scale
    if max_dim > _MAX_DIM_PX_AT_DEFAULT_DPI:
        return base_dpi - 30
    return base_dpi


def _order_priority_pages(pages: list[int]) -> tuple[list[int], int]:
    """Ordenar páginas por prioridade de processamento.

    Para ``len(pages) > 4`` retorna ``(pages[:3] + [pages[-1]] + pages[3:-1], 4)``:
    processa primeiro as 3 primeiras (capa/folha de rosto/índice), depois a
    última (contracapa) e, por fim, o miolo restante, com ``min_pages=4`` para
    o early stop. Para ``len(pages) <= 4`` retorna ``(list(pages), len(pages))``
    (processa todas, sem early stop antecipado).

    O segundo elemento da tupla é o ``min_pages``: número mínimo de páginas a
    processar antes de considerar early stop pelo alvo alfanumérico.
    """
    if len(pages) > 4:
        return pages[:3] + [pages[-1]] + pages[3:-1], 4
    return list(pages), len(pages)


def _ocr_with_rapidocr(doc: fitz.Document, pages: list[int]) -> str:
    """Extrair texto via RapidOCR renderizando páginas selecionadas.

    Processa as páginas em ordem de prioridade retornada por
    ``_order_priority_pages`` (primeiras 3, última, depois o restante),
    mantendo um mapa ``page_texts`` índice->texto. Faz early stop quando já
    foram processadas pelo menos ``min_pages`` páginas e o total de caracteres
    alfanuméricos atingir ``_OCR_TARGET_ALPHANUM``. O texto final é juntado
    ordenado por índice crescente de página (ordem natural do PDF,
    capa..contracapa).

    Renderiza cada página como PNG via PyMuPDF (DPI 150 por padrão, 120 DPI
    quando a página é muito grande) e passa os bytes para a instância
    RapidOCR, juntando as linhas de texto com quebra de linha.

    A ordenação do texto segue uma heurística geométrica leve (y_bucket, x):
    agrupa caixas por linha vertical usando tolerância proporcional à altura
    mediana das caixas e ordena por x_min dentro de cada linha, com fallback
    para iterável ou txts quando as caixas não estiverem disponíveis.

    Sem Threads custom nem CoreML (fallback seguro, CPU default do ONNX).
    """
    engine = _get_rapidocr_engine()
    if engine is None:
        return ""

    ordered_pages, min_pages = _order_priority_pages(pages)
    page_texts: dict[int, str] = {}
    total_alnum = 0
    processed = 0

    for idx in ordered_pages:
        try:
            dpi = _dpi_for_page(doc, idx, base_dpi=_DEFAULT_OCR_DPI)
            pix = doc[idx].get_pixmap(dpi=dpi)
            png_bytes = pix.tobytes("png")
            result = engine(png_bytes)
            if result is None:
                continue
            texto = "\n".join(_extract_lines_from_result(result))
            page_texts[idx] = texto
            processed += 1
            total_alnum += sum(1 for ch in texto if ch.isalnum())
        except Exception as exc:  # pragma: no cover - defesa por página
            _logger.warning("RapidOCR falhou na página %d: %s", idx, exc)
            continue

        # Early stop: cobertura mínima atingida com alvo alfanumérico suficiente.
        if processed >= min_pages and total_alnum >= _OCR_TARGET_ALPHANUM:
            break

    # Juntar em ordem crescente de índice de página (ordem natural do PDF).
    linhas: list[str] = []
    for idx in sorted(page_texts):
        texto = page_texts[idx]
        if texto:
            linhas.append(texto)

    return "\n".join(linhas).strip()


def _extrair_caixa(box: object) -> tuple[float, float, float, float, str] | None:
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


def _extrair_poligono_4x2(box: object) -> tuple[float, float, float, float] | None:
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
    except Exception as exc:  # falha benigna de parsing de resultado do RapidOCR
        _logger.warning("Falha ao iterar resultado do RapidOCR: %s", exc)
    return linhas


def _order_boxes_geometricamente(
    boxes: object, txts: list[str] | None = None
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
    except Exception as exc:  # falha benigna de parsing de caixas do RapidOCR
        _logger.warning("Falha ao extrair caixas do RapidOCR: %s", exc)

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
    for x0, y0, _x1, y1, texto in caixas:
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

    Renderiza cada página selecionada via PyMuPDF a 150 DPI (ou 120 DPI quando
    a página é muito grande) e executa OCR direto com RapidOCR.

    Processa em ordem de prioridade com early stop ao atingir cobertura mínima
    e 15.000 caracteres alfanuméricos úteis, juntando o texto final em ordem
    crescente de índice de página (ordem natural do PDF, capa..contracapa).

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
        first = list(range(min(_OCR_FIRST_PAGES, total_pages)))
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
        except Exception as exc:  # falha benigna ao fechar documento PDF
            _logger.debug("Falha ao fechar documento PDF %s: %s", path.name, exc)
