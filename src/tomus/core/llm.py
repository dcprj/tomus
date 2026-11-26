"""Classificador LLM com protocolo extensível e provedores múltiplos (Item 18).

Declara o Protocol LLMProvider, aplica short-circuit antes da chamada de rede
quando o texto alfanumérico útil for < 50 caracteres e não houver
ExternalMetadata (confidence_score = 0.0), implementa múltiplos provedores
(Gemini, NVIDIA, DeepSeek, Claude, Groq) com saída estruturada, classificação
estruturada de falhas HTTP e estado volátil thread-safe de cooldown, sem
retries exteriores nos provedores (o orçamento de tentativas é gerenciado pelo
scheduler/dispatcher), normalização taxonômica/autores, filtro de
identificadores contaminantes e teto min(score, 0.50) quando o título for
vazio/genérico sem autor.
"""

from __future__ import annotations

import inspect
import json
import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from zoneinfo import ZoneInfo

import httpx

from tomus.core.config import GEMINI_ENV_KEYS, AppConfig, mask_key
from tomus.core.models import ExternalMetadata, LLMClassificationOutput
from tomus.core.prompts import (
    build_context_payload,
    build_system_prompt,
    extract_first_author_key,
    is_generic_title,
    normalize_authors,
)
from tomus.core.taxonomy import (
    normalize_and_resolve_taxonomy,
    repair_taxonomy_levels,
    validate_or_repair_pair,
)
from tomus.extractors.identifiers import normalize_doi, normalize_isbn

# Limite de texto alfanumérico útil abaixo do qual ocorre short-circuit.
MIN_USEFUL_CHARS = 50

# Teto de confiança quando o título é vazio/genérico sem autor identificável.
GENERIC_TITLE_CONFIDENCE_CAP = 0.50

# Limiar de confiança para organização automática.
CONFIDENCE_MIN = 0.70

# Orçamento máximo de tentativas físicas por entrada/documento, compartilhado
# pelos modelos (política proposta para provedor único).
MAX_TENTATIVAS_FISICAS = 4

# Backoff base (segundos) apenas sem alternativa e com espera curta.
BACKOFF_BASE_S = 2.0
BACKOFF_MAX_CURTO_S = 4.0

# Fallback conservador quando a base IANA não está disponível (Windows
# empacotado sem tzdata): 24 h de bloqueio para cota diária.
FALLBACK_DIARIO_S = 24 * 60 * 60

# Cooldown moderado por par para falhas de servidor (503/504/529) quando não
# há Retry-After explícito, evitando repetição lenta a cada PDF seguinte.
COOLDOWN_TRANSIENT_SERVER_S = 60.0

_llm_logger = logging.getLogger("tomus.llm")


# --------------------------------------------------------------------------- #
# Decisão privada e imutável sobre falha (substitui _is_retryable_http,
# _is_generic_openai_retryable e GeminiProvider._is_404).
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class _FailureDecision:
    """Resultado imutável da classificação estruturada de uma falha.

    atributos:
        categoria: "permanente" | "transitorio" | "cooldown_diario" |
            "cooldown_curto" | "modelo_indisponivel" | "nao_retryavel".
        escopo: "entrada" (bloqueia a entrada na cadeia) ou "par"
            (bloqueia apenas o par entrada/modelo).
        status: código HTTP quando disponível.
        retry_after: espera sugerida em segundos (None se não houver).
        motivo: descrição legível da decisão (não guarda exceção/headers/token).
    """
    categoria: str
    escopo: str
    status: int | None = None
    retry_after: float | None = None
    motivo: str = ""


def _pacific_midnight_deadline() -> float | None:
    """Calcular o deadline monotônico para a próxima meia-noite
    America/Los_Angeles.

    Protegido por try/except Exception: se a base IANA estiver indisponível
    (ex.: Windows empacotado sem tzdata -> ZoneInfoNotFoundError), retorna
    None e o chamador aplica o fallback conservador de 24 h.
    """
    try:
        agora = datetime.now(UTC)
        tz_la = ZoneInfo("America/Los_Angeles")
        agora_la = agora.astimezone(tz_la)
        # Meia-noite local de hoje; se já passou, amanhã.
        meia_noite_la = agora_la.replace(hour=0, minute=0, second=0, microsecond=0)
        if meia_noite_la <= agora_la:
            meia_noite_la += timedelta(days=1)
        meia_noite_utc = meia_noite_la.astimezone(UTC)
        return (meia_noite_utc - agora).total_seconds()
    except Exception:  # ZoneInfoNotFoundError em Windows sem tzdata, etc.
        return None


def _retry_after_segundos(header_valor: str | None) -> float | None:
    """Converter o cabeçalho Retry-After (segundos ou data HTTP RFC) em segundos."""
    if not header_valor:
        return None
    try:
        return float(header_valor)
    except (TypeError, ValueError):
        pass
    # Data HTTP RFC 1123 / RFC 850 / asctime.
    try:
        from email.utils import parsedate_to_datetime
        data = parsedate_to_datetime(header_valor)
        if data is not None:
            if data.tzinfo is None:
                data = data.replace(tzinfo=UTC)
            return max(0.0, (data - datetime.now(UTC)).total_seconds())
    except Exception:
        return None
    return None


def _extrair_details_api_error(exc: BaseException) -> tuple[list[Any], Any | None]:
    """Extrair (details, status) de um google.genai.errors.APIError sem guardar
    a exceção nem seus campos no estado volátil."""
    details: list[Any] = []
    status: Any = None
    try:
        status = getattr(exc, "status", None)
        if status is not None and isinstance(status, dict):
            detalhes_status = status.get("details") or status.get("error", {}).get("details", [])
            if isinstance(detalhes_status, list):
                details.extend(detalhes_status)
        # details direto quando exposto. O ClientError armazena como
        # {"error": {"message": ..., "details": [...]}} (aninhado).
        exc_details = getattr(exc, "details", None)
        if isinstance(exc_details, list):
            details.extend(exc_details)
        elif isinstance(exc_details, dict):
            # exc_details pode ser {"details": [...]} ou {"error": {"details": [...]}}.
            detalhes_dict = exc_details.get("details", [])
            if not isinstance(detalhes_dict, list) or not detalhes_dict:
                error_dict = exc_details.get("error", {})
                if isinstance(error_dict, dict):
                    detalhes_dict = error_dict.get("details", [])
            if isinstance(detalhes_dict, list):
                details.extend(detalhes_dict)
    except Exception:  # noqa: S110 - extração defensiva de details, falha silenciosa intencional
        pass
    return details, status


def _extrair_json_httpx(exc: BaseException) -> Any:
    """Extrair corpo JSON de uma exceção httpx, aceitando corpo ausente ou inválido."""
    try:
        resposta = getattr(exc, "response", None)
        if resposta is not None:
            return resposta.json()
    except Exception:
        return None
    return None


def _classificar_falha(exc: BaseException) -> _FailureDecision | None:
    """Classificar estruturalmente uma falha ANTES de _sanitize_error_message.

    Cobre google.genai.errors.APIError (code, message, details/error.details,
    QuotaFailure, RetryInfo fracionario) e httpx (status_code, JSON,
    Retry-After em segundos ou data RFC), além de transport/timeout,
    401/403 permanente, 429 PerDay/RPD vs RPM/FreeTier/RESOURCE_EXHAUSTED,
    retryDelay >60s vs ==60s, 503/504/529, 404 por modelo/par, e demais 4xx
    sem cooldown coletivo.

    Retorna None quando a exceção não se enquadra em nenhuma categoria
    reconhecida (não gera cooldown coletivo).
    """
    # ---------- google.genai.errors.APIError ----------
    # Aceita APIError, ClientError (4xx) e ServerError (5xx) do SDK real,
    # com try/except defensivo quando o SDK não está instalado.
    exc_tipo = type(exc)
    modulo_exc = getattr(exc_tipo, "__module__", "") or ""
    nome_exc = getattr(exc_tipo, "__name__", "") or ""
    # Fallback para mocks que definem __module__/__name__ na instância.
    if not modulo_exc:
        modulo_exc = getattr(exc, "__module__", modulo_exc) or modulo_exc
    exc_class = getattr(exc, "__class__", exc_tipo)
    if not nome_exc:
        nome_exc = getattr(exc_class, "__name__", nome_exc) or nome_exc
    is_api_error = False
    try:
        from google.genai import errors as _genai_errors
        for _cls in (_genai_errors.APIError, _genai_errors.ClientError, _genai_errors.ServerError):
            if isinstance(exc, _cls):
                is_api_error = True
                break
        # Fallback para mocks quando o SDK está instalado mas exc é um Mock.
        if not is_api_error:
            is_api_error = "google.genai.errors" in modulo_exc and nome_exc in (
                "APIError", "ClientError", "ServerError"
            )
    except Exception:
        # Fallback por string de módulo/nome quando o SDK não está instalado.
        is_api_error = "google.genai.errors" in modulo_exc and nome_exc in (
            "APIError", "ClientError", "ServerError"
        )
        # Fallback para mocks de teste que definem code/message/details.
        if not is_api_error:
            is_api_error = hasattr(exc, "code") and hasattr(exc, "message") and hasattr(exc, "details")

    if is_api_error:
        codigo = getattr(exc, "code", None)
        mensagem = str(getattr(exc, "message", "") or "")
        details, _status = _extrair_details_api_error(exc)

        # Coletar quotaIds / quotaMetrics / violações de details (QuotaFailure).
        texto_detalhes = ""
        try:
            texto_detalhes = json.dumps(details, ensure_ascii=False).lower()
        except Exception:
            texto_detalhes = ""
        combinado = f"{mensagem.lower()} {texto_detalhes}".lower()

        eh_diario = any(
            token in combinado
            for token in ("perday", "rpd", "requests/day", "requests per day", "daily", "diário", "por dia")
        )
        eh_por_minuto = any(
            token in combinado
            for token in ("perminute", "rpm", "requests per minute", "tpm", "tokens per minute")
        )
        eh_resource_exhausted = "resource_exhausted" in combinado

        # RetryInfo fracional (pode vir como número ou string "8.5s").
        retry_delay_s: float | None = None
        try:
            for detalhe in details:
                d = getattr(detalhe, "__dict__", {}) if not isinstance(detalhe, dict) else detalhe
                rd = d.get("retryDelay") or d.get("retry_delay")
                if rd is not None:
                    if isinstance(rd, str):
                        rd = rd.replace("s", "").replace("S", "")
                    retry_delay_s = float(rd)
                    break
        except Exception:
            retry_delay_s = None

        # 401/403: permanente para a entrada durante a vida da cadeia.
        if codigo in (401, 403):
            return _FailureDecision(
                categoria="permanente",
                escopo="entrada",
                status=int(codigo) if codigo is not None else None,
                motivo=f"{nome_exc} {codigo} credencial inválida ou expirada",
            )

        # 404/410 Gone: marcar só o par indisponível nesta cadeia, tentar outro modelo.
        if codigo in (404, 410):
            return _FailureDecision(
                categoria="modelo_indisponivel",
                escopo="par",
                status=int(codigo),
                motivo=f"{nome_exc} {codigo} modelo/par indisponível",
            )

        # 429: diferenciar PerDay/RPD vs RPM/FreeTier/RESOURCE_EXHAUSTED.
        if codigo == 429:
            # Detectar se alguma violação identifica modelo específico
            # (quotaDimensions.model) -> escopo par mesmo em cota diária.
            eh_modelo_especifico = False
            try:
                for detalhe in details:
                    d = getattr(detalhe, "__dict__", {}) if not isinstance(detalhe, dict) else detalhe
                    dims = d.get("quotaDimensions") or {}
                    if isinstance(dims, dict) and dims.get("model"):
                        eh_modelo_especifico = True
                        break
                    # Nos payloads reais do Google, quotaDimensions vem dentro
                    # de QuotaFailure.violations[i].
                    violations = d.get("violations") or []
                    for v in violations:
                        vd = getattr(v, "__dict__", {}) if not isinstance(v, dict) else v
                        vdims = vd.get("quotaDimensions") or {}
                        if isinstance(vdims, dict) and vdims.get("model"):
                            eh_modelo_especifico = True
                            break
                    if eh_modelo_especifico:
                        break
            except Exception:
                eh_modelo_especifico = False

            if eh_diario:
                # Bloquear até o próximo reset (meia-noite Pacífico), mesmo se
                # o RetryInfo sugerir apenas 8 s.
                segundos_ate_meia_noite = _pacific_midnight_deadline()
                espera = segundos_ate_meia_noite
                # Respeitar a espera mínima maior informada pelo servidor.
                if retry_delay_s is not None and retry_delay_s > (espera or 0):
                    espera = retry_delay_s
                if espera is None:
                    espera = FALLBACK_DIARIO_S
                # Se a violação identifica modelo específico, escopo é par;
                # senão, escopo é entrada (cota global/diária indeterminada).
                escopo_diario = "par" if eh_modelo_especifico else "entrada"
                return _FailureDecision(
                    categoria="cooldown_diario",
                    escopo=escopo_diario,
                    status=429,
                    retry_after=espera,
                    motivo="cota diária esgotada até o reset do Pacífico",
                )
            # PerMinute/FreeTier/desconhecido -> transitório, respeitar
            # RetryInfo/retryDelay. retryDelay >60s sem marcador diário: troca
            # imediata mas bloqueia pelo intervalo anunciado. Exatamente 60s
            # continua transitório.
            if retry_delay_s is not None:
                if retry_delay_s > 60.0:
                    return _FailureDecision(
                        categoria="cooldown_curto",
                        escopo="entrada",
                        status=429,
                        retry_after=retry_delay_s,
                        motivo=f"retryDelay {retry_delay_s}s > 60s sem marcador diário",
                    )
                if retry_delay_s == 60.0:
                    return _FailureDecision(
                        categoria="transitorio",
                        escopo="par",
                        status=429,
                        retry_after=retry_delay_s,
                        motivo="retryDelay 60s transitório",
                    )
                return _FailureDecision(
                    categoria="transitorio",
                    escopo="par",
                    status=429,
                    retry_after=retry_delay_s,
                    motivo=f"retryDelay {retry_delay_s}s (RPM/TPM)",
                )
            if eh_resource_exhausted and not eh_diario and not eh_por_minuto:
                # FreeTier isolado ou RESOURCE_EXHAUSTED isolado não identifica
                # RPD -> transitorio (tentativa alternativa), nunca nao_retryavel.
                return _FailureDecision(
                    categoria="transitorio",
                    escopo="par",
                    status=429,
                    retry_after=BACKOFF_BASE_S,
                    motivo="RESOURCE_EXHAUSTED/FreeTier isolado -> transitorio por par",
                )
            return _FailureDecision(
                categoria="transitorio",
                escopo="par",
                status=429,
                motivo="429 sem detalhes de cota",
            )

        # 503/504/529: indisponibilidade transitória.
        if codigo in (503, 504, 529):
            return _FailureDecision(
                categoria="transitorio",
                escopo="par",
                status=int(codigo),
                motivo=f"{nome_exc} {codigo} indisponibilidade transitória",
            )

        # Demais 4xx: sem cooldown coletivo.
        if codigo is not None and 400 <= int(codigo) < 500 and codigo not in (401, 403, 404, 429):
            return _FailureDecision(
                categoria="nao_retryavel",
                escopo="par",
                status=int(codigo),
                motivo=f"{nome_exc} {codigo} erro de cliente sem cooldown coletivo",
            )

        # Não reconhecido: sem cooldown coletivo.
        return None

    # ---------- httpx ----------
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return _FailureDecision(
            categoria="transitorio",
            escopo="par",
            status=None,
            motivo="erro de transporte/timeout httpx",
        )

    if isinstance(exc, httpx.HTTPStatusError):
        resposta = exc.response
        codigo = getattr(resposta, "status_code", None)
        headers = getattr(resposta, "headers", {}) or {}
        corpo_json = _extrair_json_httpx(exc)

        texto_corpo = ""
        try:
            texto_corpo = json.dumps(corpo_json, ensure_ascii=False).lower() if corpo_json is not None else ""
        except Exception:
            texto_corpo = ""
        combinado = f"{texto_corpo} {str(exc).lower()}".lower()

        eh_diario = any(
            token in combinado
            for token in ("perday", "rpd", "requests/day", "requests per day", "daily", "diário", "por dia")
        )

        # Retry-After (segundos ou data RFC).
        retry_after_header = headers.get("retry-after") or headers.get("Retry-After")
        retry_after_s = _retry_after_segundos(retry_after_header)

        # 401/403: permanente para a entrada.
        if codigo in (401, 403):
            return _FailureDecision(
                categoria="permanente",
                escopo="entrada",
                status=int(codigo),
                motivo=f"httpx {codigo} credencial inválida ou expirada",
            )

        # 404/410 Gone: par indisponível.
        if codigo in (404, 410):
            return _FailureDecision(
                categoria="modelo_indisponivel",
                escopo="par",
                status=int(codigo),
                motivo=f"httpx {codigo} modelo/par indisponível",
            )

        # 429: diferenciar diário vs transitório.
        if codigo == 429:
            if eh_diario:
                segundos_ate_meia_noite = _pacific_midnight_deadline()
                espera_base = (
                    segundos_ate_meia_noite
                    if segundos_ate_meia_noite is not None
                    else FALLBACK_DIARIO_S
                )
                # Mesmo que o servidor mande Retry-After curto (ex.: 8 s),
                # NÃO reduzir abaixo da próxima meia-noite do Pacífico.
                espera = max(espera_base, retry_after_s or 0.0)
                return _FailureDecision(
                    categoria="cooldown_diario",
                    escopo="entrada",
                    status=429,
                    retry_after=espera,
                    motivo="cota diária esgotada até o reset do Pacífico",
                )
            if retry_after_s is not None:
                if retry_after_s > 60.0:
                    return _FailureDecision(
                        categoria="cooldown_curto",
                        escopo="entrada",
                        status=429,
                        retry_after=retry_after_s,
                        motivo=f"Retry-After {retry_after_s}s > 60s",
                    )
                return _FailureDecision(
                    categoria="transitorio",
                    escopo="par",
                    status=429,
                    retry_after=retry_after_s,
                    motivo=f"Retry-After {retry_after_s}s",
                )
            return _FailureDecision(
                categoria="transitorio",
                escopo="par",
                status=429,
                motivo="429 sem Retry-After",
            )

        # 503/504/529: transitório.
        if codigo in (503, 504, 529):
            return _FailureDecision(
                categoria="transitorio",
                escopo="par",
                status=int(codigo),
                retry_after=retry_after_s,
                motivo=f"httpx {codigo} indisponibilidade transitória",
            )

        # Demais 4xx: sem cooldown coletivo.
        if codigo is not None and 400 <= int(codigo) < 500 and codigo not in (401, 403, 404, 429):
            return _FailureDecision(
                categoria="nao_retryavel",
                escopo="par",
                status=int(codigo),
                motivo=f"httpx {codigo} erro de cliente sem cooldown coletivo",
            )

        return None

    # TimeoutError / socket.timeout puro.
    if isinstance(exc, (TimeoutError,)):
        return _FailureDecision(
            categoria="transitorio",
            escopo="par",
            status=None,
            motivo="TimeoutError",
        )

    return None


def _resolve_api_keys(api_key: str | list[str] | None) -> list[str]:
    """Resolver múltiplas chaves de API (pool): retorna lista de tokens individuais."""
    if not api_key:
        return []
    if isinstance(api_key, list):
        keys: list[str] = []
        for item in api_key:
            keys.extend([k.strip() for k in str(item).split(",") if k.strip()])
        return keys
    if isinstance(api_key, str) and api_key.strip():
        return [k.strip() for k in api_key.split(",") if k.strip()]
    return []


def _resolve_api_key(api_key: str | list[str]) -> str:
    """Resolver a chave de API: se for lista, usar o primeiro elemento."""
    if isinstance(api_key, list):
        return api_key[0] if api_key else ""
    return api_key or ""


# --------------------------------------------------------------------------- #
# Estado volátil thread-safe de cooldown do pool de provedores.
# --------------------------------------------------------------------------- #

@dataclass
class _PoolCooldownState:
    """Estado volátil (apenas na memória do processo) de cooldown do pool.

    Protege com threading.Lock + Condition:
      * deadlines de entrada (entry_id -> deadline monotônico),
      * deadlines por par (par_id -> deadline monotônico),
      * cursor por família (família -> índice),
      * geração (incrementada a cada mudança relevante),
      * reserva única de sondagem (escopo -> bool), liberada em finally.

    entry_id é opaco (ex: "entry:idx") e identifica o escopo de entrada.
    par_id identifica o par entrada/modelo (ex: "entry:idx:model:M").

    Não guarda exceções, headers, corpos nem tokens. clock/sleep são injetáveis
    para testes determinísticos.
    """

    lock: threading.Lock = field(default_factory=threading.Lock)
    condition: threading.Condition = field(init=False)
    clock: Callable[[], float] = field(default=time.monotonic)
    sleep: Callable[[float], None] = field(default=time.sleep)

    # deadline monotônico por entrada (cota global / diária de escopo indeterminado).
    entrada_deadlines: dict[str, float] = field(default_factory=dict)
    # deadline monotônico por par (entrada_id + modelo).
    par_deadlines: dict[str, float] = field(default_factory=dict)
    # cursor de round-robin por família de provedores.
    cursor_por_familia: dict[str, int] = field(default_factory=dict)
    # geração do estado (incrementada a cada publicação de falha/expiração).
    geracao: int = 0
    # bloqueio de geração para proteger contra sucesso atrasado de voo antigo.
    bloqueio_gen: int = 0
    # geração do envio da sonda atual (protege voo antigo contra bloqueio novo).
    geracao_envio: int = 0
    # reserva única de sondagem por escopo (só um worker sonda por vez).
    reserva_sondagem: dict[str, bool] = field(default_factory=dict)
    # bloqueios permanentes de entrada (401/403) durante a vida da cadeia.
    entradas_permanentes: set[str] = field(default_factory=set)
    # pares indisponíveis (404) por cadeia.
    pares_indisponiveis: set[str] = field(default_factory=set)
    # Geração do bloqueio por entrada e par (protege sucesso atrasado de voo
    # antigo contra bloqueio mais recente).
    bloqueio_gen_entrada: dict[str, int] = field(default_factory=dict)
    bloqueio_gen_par: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.condition = threading.Condition(lock=self.lock)

    # ------------------------------------------------------------------ #
    # Helpers internos (chamados sempre dentro do lock).
    # ------------------------------------------------------------------ #
    def _agora(self) -> float:
        return self.clock()

    def _limpar_expirados(self, agora: float) -> None:
        """Remover deadlines vencidos e marcar geração."""
        expirados = False
        for entrada_id in list(self.entrada_deadlines):
            if self.entrada_deadlines[entrada_id] <= agora:
                del self.entrada_deadlines[entrada_id]
                expirados = True
        for par_id in list(self.par_deadlines):
            if self.par_deadlines[par_id] <= agora:
                del self.par_deadlines[par_id]
                expirados = True
        if expirados:
            self.geracao += 1

    def esta_bloqueado(self, entrada_id: str, par_id: str, agora: float | None = None) -> bool:
        """Verificar se entrada ou par está bloqueado agora (dentro do lock)."""
        if agora is None:
            agora = self._agora()
        self._limpar_expirados(agora)
        if entrada_id in self.entradas_permanentes:
            return True
        if entrada_id in self.entrada_deadlines and self.entrada_deadlines[entrada_id] > agora:
            return True
        if par_id in self.par_deadlines and self.par_deadlines[par_id] > agora:
            return True
        if par_id in self.pares_indisponiveis:  # noqa: SIM103
            return True
        return False

    def proximo_prazo(self, agora: float | None = None) -> float | None:
        """Calcular o próximo prazo (deadline mínimo) no bloqueio total.

        Retorna segundos até o próximo vencimento, ou None se não houver
        bloqueios ativos. Chamado dentro do lock.
        """
        if agora is None:
            agora = self._agora()
        self._limpar_expirados(agora)
        candidatos: list[float] = []
        for d in self.entrada_deadlines.values():
            if d > agora:
                candidatos.append(d)
        for d in self.par_deadlines.values():
            if d > agora:
                candidatos.append(d)
        if not candidatos:
            return None
        return min(candidatos) - agora

    def publicar_falha(
        self,
        entrada_id: str,
        par_id: str,
        decisao: _FailureDecision,
        agora: float | None = None,
    ) -> None:
        """Publicar uma falha tipada antes de selecionar o próximo candidato.

        Combina deadlines por máximo e torna o bloqueio permanente dominante.
        Chamado sempre dentro do lock.
        """
        if agora is None:
            agora = self._agora()
        self._limpar_expirados(agora)

        if decisao.categoria == "permanente":
            self.entradas_permanentes.add(entrada_id)
            self.bloqueio_gen_entrada[entrada_id] = self.geracao + 1
            self.geracao += 1
            self.condition.notify_all()
            return

        if decisao.categoria == "modelo_indisponivel":
            self.pares_indisponiveis.add(par_id)
            self.bloqueio_gen_par[par_id] = self.geracao + 1
            self.geracao += 1
            self.condition.notify_all()
            return

        retry_after = decisao.retry_after
        if retry_after is None:
            retry_after = BACKOFF_BASE_S

        deadline = agora + retry_after

        if decisao.categoria == "cooldown_diario":
            if decisao.escopo == "par":
                atual = self.par_deadlines.get(par_id, 0.0)
                self.par_deadlines[par_id] = max(atual, deadline)
                self.bloqueio_gen_par[par_id] = self.geracao + 1
            else:
                atual = self.entrada_deadlines.get(entrada_id, 0.0)
                self.entrada_deadlines[entrada_id] = max(atual, deadline)
                self.bloqueio_gen_entrada[entrada_id] = self.geracao + 1
            self.geracao += 1
            self.condition.notify_all()
            return

        if decisao.categoria == "cooldown_curto":
            atual = self.entrada_deadlines.get(entrada_id, 0.0)
            self.entrada_deadlines[entrada_id] = max(atual, deadline)
            self.bloqueio_gen_entrada[entrada_id] = self.geracao + 1
            self.geracao += 1
            self.condition.notify_all()
            return

        if decisao.categoria == "transitorio":
            # Falhas de servidor (503/504/529) sem Retry-After explícito
            # recebem cooldown moderado por par para evitar repetição lenta.
            if (
                decisao.status in (503, 504, 529)
                and decisao.retry_after is None
            ):
                deadline = agora + COOLDOWN_TRANSIENT_SERVER_S
            if decisao.escopo == "entrada":
                atual = self.entrada_deadlines.get(entrada_id, 0.0)
                self.entrada_deadlines[entrada_id] = max(atual, deadline)
                self.bloqueio_gen_entrada[entrada_id] = self.geracao + 1
            else:
                atual = self.par_deadlines.get(par_id, 0.0)
                self.par_deadlines[par_id] = max(atual, deadline)
                self.bloqueio_gen_par[par_id] = self.geracao + 1
            self.geracao += 1
            self.condition.notify_all()
            return

        # nao_retryavel: não altera estado.
        return

    def reservar_sonda(self, escopo: str) -> bool:
        """Reservar única sondagem de um escopo. Retorna True se conseguiu."""
        with self.lock:
            if self.reserva_sondagem.get(escopo):
                return False
            self.reserva_sondagem[escopo] = True
            return True

    def aguardar_sonda(self, escopo: str, timeout: float) -> bool:
        """Aguardar a sonda de um escopo ser liberada, com timeout.

        Retorna True se a sonda foi liberada dentro do timeout, False caso
        contrário. Chamado dentro do lock (usa a Condition).
        """
        fim = self._agora() + timeout
        while self.reserva_sondagem.get(escopo):
            restante = fim - self._agora()
            if restante <= 0:
                return False
            self.condition.wait(timeout=min(restante, 0.5))
        return True

    def liberar_sonda(self, escopo: str) -> None:
        """Liberar a reserva de sondagem (chamado em finally)."""
        with self.lock:
            self.reserva_sondagem.pop(escopo, None)
            self.geracao += 1
            self.condition.notify_all()

    def adquirir_candidato(
        self, entrada_id: str, par_id: str, agora: float
    ) -> tuple[bool, str | None, int, bool]:
        """Selecionar candidato sob lock (dentro de ``self.lock``).

        Retorna ``(elegivel, escopo_sonda, geracao_envio, bloqueado_por_sonda)``:

        * ``elegivel=False`` quando o par/entrada está permanentemente bloqueado
          ou tem deadline futuro (sem sonda, sem reserva).
        * ``elegivel=True`` com ``escopo_sonda`` quando o deadline venceu e este
          worker é o único a sondar esse escopo (reserva adquirida).
        * ``bloqueado_por_sonda=True`` quando outra worker já está sondando o
          escopo expirado (usar alternativa em vez de esperar).
        """
        self._limpar_expirados(agora)

        if entrada_id in self.entradas_permanentes or par_id in self.pares_indisponiveis:
            return (False, None, self.geracao, False)

        dl_e = self.entrada_deadlines.get(entrada_id)
        dl_p = self.par_deadlines.get(par_id)

        if (dl_e is not None and dl_e > agora) or (dl_p is not None and dl_p > agora):
            return (False, None, self.geracao, False)

        # Deadline vencido (ou ausente): este escopo precisa de sonda.
        if dl_e is not None and dl_e <= agora:
            escopo = f"entry:{entrada_id}"
        elif dl_p is not None and dl_p <= agora:
            escopo = f"pair:{par_id}"
        else:
            # Saudável (sem deadlines).
            return (True, None, self.geracao, False)

        if self.reserva_sondagem.get(escopo):
            return (False, None, self.geracao, True)

        self.reserva_sondagem[escopo] = True
        # Remover o deadline expirado correspondente (<= agora).
        if dl_e is not None and dl_e <= agora:
            self.entrada_deadlines.pop(entrada_id, None)
        if dl_p is not None and dl_p <= agora:
            self.par_deadlines.pop(par_id, None)
        self.geracao += 1
        return (True, escopo, self.geracao, False)

    def confirmar_sucesso_candidato(
        self, entrada_id: str, par_id: str, geracao_envio: int, agora: float
    ) -> bool:
        """Confirmar sucesso de um candidato sob lock.

        Retorna True se o resultado deste voo deve ser promovido (limpar
        vencidos). Retorna False se o alvo recebeu um bloqueio mais novo
        depois do envio (voo antigo não limpa bloqueio novo).
        """
        self._limpar_expirados(agora)
        bloqueio_atual = max(
            self.bloqueio_gen_entrada.get(entrada_id, 0),
            self.bloqueio_gen_par.get(par_id, 0),
        )
        if bloqueio_atual > geracao_envio:
            # Bloqueio mais recente chegou depois deste envio: não promove.
            return False
        return True

    def avancar_cursor(self, familia: str) -> int:
        """Avançar o cursor round-robin de uma família. Retorna o novo índice."""
        with self.lock:
            atual = self.cursor_por_familia.get(familia, 0)
            self.cursor_por_familia[familia] = atual + 1
            self.geracao += 1
            return self.cursor_por_familia[familia]

    def ler_cursor(self, familia: str) -> int:
        with self.lock:
            return self.cursor_por_familia.get(familia, 0)


def _deduplicar_chaves(chaves: list[str]) -> list[str]:
    """Deduplicar chaves idênticas por provedor após _resolve_api_keys,
    preservando a ordem."""
    vistos: set[str] = set()
    resultado: list[str] = []
    for chave in chaves:
        if chave not in vistos:
            vistos.add(chave)
            resultado.append(chave)
    return resultado


def _sanitize_error_message(message: str) -> str:
    import re as _re

    text = message
    # Chaves Google / Anthropic / GitHub e sk- genérico (8+ chars).
    text = _re.sub(r"(AIzaSy[A-Za-z0-9_-]{8,})", "AIza-***REDACTED***", text)
    text = _re.sub(r"(sk-ant-[A-Za-z0-9-]{8,})", "sk-ant-***REDACTED***", text)
    text = _re.sub(r"(ghp_[A-Za-z0-9]{8,})", "ghp-***REDACTED***", text)
    text = _re.sub(r"(gho_[A-Za-z0-9]{8,})", "gho-***REDACTED***", text)
    text = _re.sub(r"(sk-[A-Za-z0-9]{8,})", "sk-***REDACTED***", text)
    text = _re.sub(r"(nvapi-[A-Za-z0-9._-]{20,})", "nvapi-***REDACTED***", text)
    text = _re.sub(r"(gsk-[A-Za-z0-9._-]{20,})", "gsk-***REDACTED***", text)
    text = _re.sub(r"(gsh_[A-Za-z0-9._-]{20,})", "gsh-***REDACTED***", text)
    for m in _re.finditer(r"[A-Za-z0-9._-]{20,}", message):
        masked = mask_key(m.group(0))
        if masked != m.group(0):
            text = text.replace(m.group(0), masked)
    return text


def humanize_error_message(message: str) -> str:
    """Traduz mensagens técnicas de erro HTTP/LLM para linguagem clara e amigável (FEAT-UX-02)."""
    clean = _sanitize_error_message(message)
    lower = clean.lower()

    prov = ""
    if "deepseek" in lower:
        prov = "DeepSeek"
    elif "groq" in lower:
        prov = "Groq"
    elif "nvidia" in lower or "nvapi" in lower:
        prov = "NVIDIA"
    elif "claude" in lower or "anthropic" in lower:
        prov = "Claude"
    elif "gemini" in lower or "google" in lower:
        prov = "Gemini"

    prov_str = f" no provedor {prov}" if prov else ""

    if "401" in lower or "unauthorized" in lower or "não autorizada" in lower:
        return f"Chave de API não autorizada ou expirada{prov_str}. Por favor, verifique suas credenciais na tela de Preferências."
    if "429" in lower or "resource_exhausted" in lower or "quota" in lower or "rate limit" in lower:
        return f"Cota de requisições por minuto ou limite diário excedido{prov_str}."
    if any(code in lower for code in ("503", "502", "504", "529", "service unavailable")):
        return f"Instabilidade temporária nos servidores{prov_str}. Tente novamente mais tarde."
    if "timeout" in lower or "timed out" in lower or "tempo limite" in lower:
        return f"Tempo limite de resposta esgotado ao consultar o provedor{f' {prov}' if prov else ''}."

    return clean


def _alphanumeric_count(text: str) -> int:
    """Contar caracteres alfanuméricos úteis em um texto."""
    return sum(1 for ch in text if ch.isalnum())


def _strip_markdown_json(text: str) -> str:
    """Remover eventuais blocos markdown (```json ... ```) da resposta."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
    if text.endswith("```"):
        text = text.rsplit("\n", 1)[0] if "\n" in text else text
    text = text.strip()
    if text.startswith("json"):
        text = text[4:].strip()
    return text


def _parse_classification_json(content: str) -> LLMClassificationOutput:
    json_text = _strip_markdown_json(content)
    try:
        return LLMClassificationOutput.model_validate_json(json_text)
    except Exception:
        return LLMClassificationOutput.model_validate(json.loads(json_text))


@dataclass
class ClassificationResult:
    """Resultado da classificação de um documento."""

    grande_area: str
    area_basica: str
    tipo: str
    authors: list[str]
    title: str
    subtitle: str
    year: int | None
    confidence_score: float
    reasoning: str
    subarea: str = ""
    especialidade: str = ""
    used_ocr: bool = False
    provider_name: str = ""
    model_name: str = ""
    publisher: str | None = None
    city: str | None = None
    edition: str | None = None
    journal_name: str | None = None
    volume: str | None = None
    number: str | None = None
    pages: str | None = None
    doi: str | None = None
    isbn: str | None = None
    # Campos opcionais para fascículos de revista (PR #14).
    publication_month: int | None = None
    publication_month_end: int | None = None
    publication_year_end: int | None = None
    issn: str | None = None
    journal_genre: str | None = None
    volume_label: str | None = None
    issue_designation: str | None = None
    serial_evidence: str | None = None


def _check_short_circuit(
    sampled_text: str,
    cip_text: str,
    external_metadata: ExternalMetadata | None,
    used_ocr: bool,
) -> ClassificationResult | None:
    """Retornar ClassificationResult de short-circuit se texto útil < 50 chars e sem metadados.

    Somente classificações bem-sucedidas têm vencedor: short-circuit e erro
    não preenchem provider_name/model_name.
    """
    useful_chars = _alphanumeric_count(sampled_text) + _alphanumeric_count(cip_text)
    has_external = external_metadata is not None and bool(
        external_metadata.title or external_metadata.authors
    )
    if useful_chars < MIN_USEFUL_CHARS and not has_external:
        return ClassificationResult(
            grande_area="",
            area_basica="",
            tipo="Outros",
            authors=[],
            title="",
            subtitle="",
            year=None,
            confidence_score=0.0,
            reasoning=(
                "Texto alfanumérico útil inferior a 50 caracteres e sem "
                "metadados externos; classificação não realizada."
            ),
            used_ocr=used_ocr,
        )
    return None


def _error_result(reasoning: str, used_ocr: bool) -> ClassificationResult:
    return ClassificationResult(
        grande_area="",
        area_basica="",
        tipo="Outros",
        authors=[],
        title="",
        subtitle="",
        year=None,
        confidence_score=0.0,
        reasoning=reasoning,
        used_ocr=used_ocr,
    )


def _finalize_classification(
    output: LLMClassificationOutput,
    used_ocr: bool,
    provider_name: str = "",
    model_name: str = "",
) -> ClassificationResult:
    """Aplicar normalização de autores, consolidação taxonômica, blacklist e travas de confiança."""
    reparado = validate_or_repair_pair(output.grande_area, output.area_basica)
    tipo_str = output.tipo.value if hasattr(output.tipo, "value") else str(output.tipo)
    authors_norm = normalize_authors(list(output.authors))
    clean_doi = normalize_doi(output.doi)
    clean_isbn = normalize_isbn(output.isbn)

    # [BUG-ENRICH-01] Livro nunca herda journal_name/number do LLM.
    journal_name = output.journal_name
    number = output.number
    if tipo_str == "Livro":
        journal_name = None
        number = None

    subarea = (output.subarea or "").strip()
    especialidade = (output.especialidade or "").strip()
    if not subarea or subarea.lower() in ("não especificada", "nao especificada", "none", "null", ""):
        subarea = "Geral"
    if not especialidade or especialidade.lower() in ("não especificada", "nao especificada", "none", "null", ""):
        especialidade = "Geral"

    if reparado is None:
        # Antes de zerar a confiança, tentar reparo dos quatro níveis
        # (deslocamento Grande Área <-> Área Básica, ex.: Letras/Literatura).
        reparado_niveis = repair_taxonomy_levels(
            output.grande_area, output.area_basica, subarea, especialidade
        )
        if reparado_niveis is None:
            return ClassificationResult(
                grande_area=output.grande_area,
                area_basica=output.area_basica,
                subarea=subarea,
                especialidade=especialidade,
                tipo=tipo_str,
                authors=authors_norm,
                title=output.title,
                subtitle=output.subtitle,
                year=output.year,
                publisher=output.publisher,
                city=output.city,
                edition=output.edition,
                journal_name=journal_name,
                volume=output.volume,
                number=number,
                pages=output.pages,
                doi=clean_doi,
                isbn=clean_isbn,
                publication_month=output.publication_month,
                publication_month_end=output.publication_month_end,
                publication_year_end=output.publication_year_end,
                issn=output.issn,
                journal_genre=output.journal_genre,
                volume_label=output.volume_label,
                issue_designation=output.issue_designation,
                serial_evidence=output.serial_evidence,
                confidence_score=0.0,
                reasoning=(
                    f"{output.reasoning} Par (grande_area, area_basica) irreparável "
                    f"contra o catálogo CAPES/CNPq."
                ),
                used_ocr=used_ocr,
                provider_name=provider_name,
                model_name=model_name,
            )
        grande_area, area_basica, subarea, especialidade = reparado_niveis
        reparado = (grande_area, area_basica)

    grande_area, area_basica = reparado
    resolved = normalize_and_resolve_taxonomy(
        {
            "grande_area": grande_area,
            "area_basica": area_basica,
            "subarea": subarea,
            "especialidade": especialidade,
            "titulo": output.title or "",
            "subtitulo": output.subtitle or "",
            "authors": authors_norm,
        },
        first_author_key=extract_first_author_key(authors_norm),
    )

    confidence = float(output.confidence_score)
    title = output.title or ""
    has_authors = bool(authors_norm) and authors_norm != ["Autor Desconhecido"]
    if is_generic_title(title) and not has_authors:
        confidence = min(confidence, GENERIC_TITLE_CONFIDENCE_CAP)

    return ClassificationResult(
        grande_area=resolved["grande_area"],
        area_basica=resolved["area_basica"],
        subarea=resolved["subarea"],
        especialidade=resolved["especialidade"],
        tipo=tipo_str,
        authors=authors_norm,
        title=title,
        subtitle=output.subtitle,
        year=output.year,
        publisher=output.publisher,
        city=output.city,
        edition=output.edition,
        journal_name=journal_name,
        volume=output.volume,
        number=number,
        pages=output.pages,
        doi=clean_doi,
        isbn=clean_isbn,
        publication_month=output.publication_month,
        publication_month_end=output.publication_month_end,
        publication_year_end=output.publication_year_end,
        issn=output.issn,
        journal_genre=output.journal_genre,
        volume_label=output.volume_label,
        issue_designation=output.issue_designation,
        serial_evidence=output.serial_evidence,
        confidence_score=confidence,
        reasoning=output.reasoning,
        used_ocr=used_ocr,
        provider_name=provider_name,
        model_name=model_name,
    )


@runtime_checkable
class LLMProvider(Protocol):
    """Protocolo de classificação de documentos por modelo de linguagem."""

    def classify(
        self,
        sampled_text: str,
        cip_text: str,
        external_metadata: ExternalMetadata | None,
        used_ocr: bool = False,
        source_path: Path | None = None,
    ) -> ClassificationResult:
        """Classificar um documento e retornar o resultado estruturado."""
        ...


class GeminiProvider:
    """Provedor Gemini usando google-genai com saída estruturada.

    O cliente google-genai é configurado com ``HttpRetryOptions(attempts=1)``
    para que o contador de tentativas reflita a rede real; o orçamento de
    tentativas e o cooldown são gerenciados pelo estado volátil
    (``_PoolCooldownState``) e pelo scheduler/dispatcher, não por retries
    exteriores do tenacity.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3.5-flash",
        max_sampled_chars: int = 15_000,
        cooldown_state: _PoolCooldownState | None = None,
    ) -> None:
        from google.genai import Client
        from google.genai import types as genai_types

        http_options = genai_types.HttpOptions(
            timeout=45_000,
            client_args={"timeout": 45.0},
            retry_options=genai_types.HttpRetryOptions(attempts=1),
        )
        self._client = Client(api_key=api_key, http_options=http_options)
        self._model = model
        self._max_sampled_chars = max_sampled_chars
        self._types = genai_types
        self._fallback_models = ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-3.1-flash-lite"]
        # Estado privado equivalente quando construído diretamente (fora da
        # cadeia compartilhada do dispatcher).
        self._cooldown_state = cooldown_state or _PoolCooldownState()

    def _classificar(self, exc: BaseException) -> _FailureDecision | None:
        return _classificar_falha(exc)

    def _call_gemini(
        self,
        system_prompt: str,
        context_payload: str,
        model: str | None = None,
    ) -> tuple[LLMClassificationOutput, str]:
        """Uma única tentativa de chamada ao Gemini (sem retry exterior, sem loop interno).

        A decisão de repetir/trocar de modelo cabe ao chamador (dispatcher),
        com base na decisão tipada de _classificar_falha e no orçamento de
        tentativas físicas.

        Retorna (parsed, effective_model) onde effective_model é
        response.model_version quando preenchido, senão o modelo que obteve
        sucesso.
        """
        modelo_usado = model or self._model
        config = self._types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            response_schema=LLMClassificationOutput,
            temperature=0.1,
        )
        response = self._client.models.generate_content(
            model=modelo_usado,
            contents=context_payload,
            config=config,
        )
        parsed = response.parsed
        if parsed is None:
            raise ValueError("Resposta do Gemini não pôde ser interpretada como JSON")
        if not isinstance(parsed, LLMClassificationOutput):
            parsed = LLMClassificationOutput.model_validate(parsed)
        effective_model = getattr(response, "model_version", None) or modelo_usado
        return parsed, effective_model

    def _classify_once(
        self,
        sampled_text: str,
        cip_text: str,
        external_metadata: ExternalMetadata | None,
        used_ocr: bool = False,
        source_path: Path | None = None,
        *,
        model: str | None = None,
    ) -> ClassificationResult:
        """Uma única tentativa física de classificação.

        Exceções brutas vazam para o dispatcher (não capturam Exception).
        """
        system_prompt = build_system_prompt()
        context_payload = build_context_payload(
            sampled_text, cip_text, external_metadata, source_path=source_path
        )
        output, effective_model = self._call_gemini(
            system_prompt, context_payload, model=model
        )
        return _finalize_classification(output, used_ocr, "gemini", effective_model)

    def classify(
        self,
        sampled_text: str,
        cip_text: str,
        external_metadata: ExternalMetadata | None,
        used_ocr: bool = False,
        source_path: Path | None = None,
    ) -> ClassificationResult:
        """Classificação de uso direto de provedor único.

        Orçamento máximo de MAX_TENTATIVAS_FISICAS=4 entre os modelos do
        provedor (Gemini: [self._model] + _fallback_models), dormindo
        backoff 2/2/4 s via cooldown_state.sleep somente se espera <= 4 s
        e sem alternativa elegível.
        """
        short = _check_short_circuit(sampled_text, cip_text, external_metadata, used_ocr)
        if short is not None:
            return short

        modelos = [self._model] + [m for m in self._fallback_models if m != self._model]
        tentativas = 0
        indice_modelo = 0
        ultimo_erro: str | None = None
        state = self._cooldown_state
        while tentativas < MAX_TENTATIVAS_FISICAS and indice_modelo < len(modelos):
            modelo = modelos[indice_modelo]
            entrada_id = "entry:gemini"
            par_id = f"entry:gemini:model:{modelo}"

            agora = state.clock()
            elegivel, escopo_sonda, geracao_envio, bloqueado_por_sonda = (
                state.adquirir_candidato(entrada_id, par_id, agora)
            )
            if not elegivel:
                # Sem alternativa elegível neste modelo; pular para o próximo.
                indice_modelo += 1
                continue

            tentativas += 1
            try:
                return self._classify_once(
                    sampled_text,
                    cip_text,
                    external_metadata,
                    used_ocr,
                    source_path,
                    model=modelo,
                )
            except Exception as exc:
                decisao = self._classificar(exc)
                motivo_sanitizado = _sanitize_error_message(str(exc))
                ultimo_erro = motivo_sanitizado
                with state.lock:
                    state.publicar_falha(entrada_id, par_id, decisao, agora)
                # Parar imediato (0 sleeps) em permanente / nao_retryavel /
                # cooldown_diario de escopo entrada.
                if decisao is not None and decisao.categoria in (
                    "permanente",
                    "nao_retryavel",
                ):
                    break
                if (
                    decisao is not None
                    and decisao.categoria == "cooldown_diario"
                    and decisao.escopo == "entrada"
                ):
                    break
                # 404/par, cooldown_diario de par, ou transitorio: próximo
                # modelo imediatamente, sem dormir antes de tentar alternativas.
                indice_modelo += 1
            finally:
                if escopo_sonda is not None:
                    state.liberar_sonda(escopo_sonda)
        return _error_result(
            f"Falha na chamada ao LLM: {ultimo_erro or 'erro desconhecido'}",
            used_ocr,
        )


class MockLLMProvider:
    """Provedor de teste determinístico (não requer rede)."""

    def __init__(self, result: ClassificationResult | None = None) -> None:
        self._result = result or ClassificationResult(
            grande_area="Ciências Humanas",
            area_basica="Psicologia",
            subarea="Psicologia Clínica",
            especialidade="Psicoterapia Cognitivo-Comportamental",
            tipo="Livro",
            authors=["Silva, João"],
            title="Título de teste",
            subtitle="",
            year=2020,
            confidence_score=0.90,
            reasoning="mock",
        )

    def classify(
        self,
        sampled_text: str,
        cip_text: str,
        external_metadata: ExternalMetadata | None,
        used_ocr: bool = False,
        source_path: Path | None = None,
    ) -> ClassificationResult:
        return self._result


class _OpenAICompatibleProvider:
    """Base compartilhada para provedores HTTP OpenAI-compatíveis (NVIDIA, DeepSeek, Groq)."""

    _provider_label: str = ""
    _provider_id: str = ""
    _max_tokens: int = 2048
    _use_json_response_format: bool = False
    _allow_reasoning_fallback: bool = False

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        max_sampled_chars: int = 15_000,
        cooldown_state: _PoolCooldownState | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=60.0,
        )
        self._model = model
        self._max_sampled_chars = max_sampled_chars
        self._cooldown_state = cooldown_state or _PoolCooldownState()

    def _classificar(self, exc: BaseException) -> _FailureDecision | None:
        return _classificar_falha(exc)

    def _call_chat_completions(
        self, system_prompt: str, context_payload: str, model: str | None = None
    ) -> str:
        """Uma única tentativa de chamada OpenAI-compatível (sem retry exterior).

        Envia ``model`` (ou self._model) no payload.
        """
        modelo_usado = model or self._model
        payload: dict[str, Any] = {
            "model": modelo_usado,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt
                    + "\n\nResponda APENAS com um objeto JSON válido estritamente no schema solicitado, sem marcação markdown adicional.",
                },
                {"role": "user", "content": context_payload},
            ],
            "temperature": 0.1,
            "max_tokens": self._max_tokens,
        }
        if self._use_json_response_format:
            payload["response_format"] = {"type": "json_object"}

        resp = self._client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()
        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {})
        content = msg.get("content")
        if (not content or not str(content).strip()) and self._allow_reasoning_fallback:
            reasoning = msg.get("reasoning_content")
            if reasoning and "{" in reasoning and "}" in reasoning:
                content = reasoning
        if not content or not str(content).strip():
            raise ValueError(f"Resposta do LLM {self._provider_label} veio vazia")
        return str(content)

    def _classify_once(
        self,
        sampled_text: str,
        cip_text: str,
        external_metadata: ExternalMetadata | None,
        used_ocr: bool = False,
        source_path: Path | None = None,
        *,
        model: str | None = None,
    ) -> ClassificationResult:
        """Uma única tentativa física de classificação.

        Exceções brutas vazam para o dispatcher (não capturam Exception).
        """
        modelo_usado = model or self._model
        system_prompt = build_system_prompt()
        context_payload = build_context_payload(
            sampled_text, cip_text, external_metadata, source_path=source_path
        )
        content = self._call_chat_completions(
            system_prompt, context_payload, model=modelo_usado
        )
        output = _parse_classification_json(content)
        return _finalize_classification(output, used_ocr, self._provider_id, modelo_usado)

    def classify(
        self,
        sampled_text: str,
        cip_text: str,
        external_metadata: ExternalMetadata | None,
        used_ocr: bool = False,
        source_path: Path | None = None,
    ) -> ClassificationResult:
        """Classificação de uso direto de provedor único.

        Orçamento máximo de MAX_TENTATIVAS_FISICAS=4 entre os modelos do
        provedor, dormindo backoff 2/2/4 s via cooldown_state.sleep somente
        se espera <= 4 s e sem alternativa elegível.
        """
        short = _check_short_circuit(sampled_text, cip_text, external_metadata, used_ocr)
        if short is not None:
            return short

        modelos = [self._model]
        tentativas = 0
        indice_modelo = 0
        ultimo_erro: str | None = None
        while tentativas < MAX_TENTATIVAS_FISICAS and indice_modelo < len(modelos):
            modelo = modelos[indice_modelo]
            tentativas += 1
            try:
                return self._classify_once(
                    sampled_text,
                    cip_text,
                    external_metadata,
                    used_ocr,
                    source_path,
                    model=modelo,
                )
            except Exception as exc:
                decisao = self._classificar(exc)
                motivo_sanitizado = _sanitize_error_message(str(exc))
                ultimo_erro = motivo_sanitizado
                if decisao is not None and decisao.categoria == "permanente":
                    with self._cooldown_state.lock:
                        entrada_id = f"{self._provider_id}:{self._model}"
                        self._cooldown_state.entradas_permanentes.add(entrada_id)
                        self._cooldown_state.geracao += 1
                    break
                retry_after = decisao.retry_after if decisao is not None else None
                espera_para_dormir = None
                if retry_after is not None and retry_after <= BACKOFF_MAX_CURTO_S:
                    espera_para_dormir = retry_after
                elif (
                    decisao is not None
                    and decisao.categoria == "transitorio"
                    and retry_after is None
                ):
                    espera_para_dormir = BACKOFF_BASE_S
                if espera_para_dormir is not None:
                    self._cooldown_state.sleep(espera_para_dormir)
                # Só há um modelo -> retry com o mesmo modelo; senão avança.
                if len(modelos) > 1:
                    indice_modelo += 1
        return _error_result(
            f"Falha na chamada ao LLM {self._provider_label}: {ultimo_erro or 'erro desconhecido'}",
            used_ocr,
        )


class NvidiaProvider(_OpenAICompatibleProvider):
    """Provedor NVIDIA NIM usando httpx diretamente."""

    _provider_label = "NVIDIA"
    _provider_id = "nvidia"
    _max_tokens = 4096
    _allow_reasoning_fallback = True

    def __init__(
        self,
        api_key: str,
        model: str = "nvidia/nemotron-3.5-super-vl-120b-a12b",
        base_url: str = "https://integrate.api.nvidia.com/v1",
        max_sampled_chars: int = 15_000,
        cooldown_state: _PoolCooldownState | None = None,
    ) -> None:
        super().__init__(api_key, model, base_url, max_sampled_chars, cooldown_state=cooldown_state)


class DeepSeekProvider(_OpenAICompatibleProvider):
    """Provedor DeepSeek usando httpx diretamente."""

    _provider_label = "DeepSeek"
    _provider_id = "deepseek"
    _max_tokens = 4096
    _allow_reasoning_fallback = True

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-flash",
        base_url: str = "https://api.deepseek.com/v1",
        max_sampled_chars: int = 15_000,
        cooldown_state: _PoolCooldownState | None = None,
    ) -> None:
        super().__init__(api_key, model, base_url, max_sampled_chars, cooldown_state=cooldown_state)


class GroqProvider(_OpenAICompatibleProvider):
    """Provedor Groq (OpenAI-compatível) usando httpx diretamente."""

    _provider_label = "Groq"
    _provider_id = "groq"
    _use_json_response_format = True

    def __init__(
        self,
        api_key: str,
        model: str = "openai/gpt-oss-120b",
        base_url: str = "https://api.groq.com/openai/v1",
        max_sampled_chars: int = 15_000,
        cooldown_state: _PoolCooldownState | None = None,
    ) -> None:
        super().__init__(api_key, model, base_url, max_sampled_chars, cooldown_state=cooldown_state)


class ClaudeProvider:
    """Provedor Anthropic Claude usando httpx diretamente."""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-haiku-5-5",
        base_url: str = "https://api.anthropic.com/v1",
        max_sampled_chars: int = 15_000,
        cooldown_state: _PoolCooldownState | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            timeout=60.0,
        )
        self._model = model
        self._max_sampled_chars = max_sampled_chars
        self._cooldown_state = cooldown_state or _PoolCooldownState()

    def _classificar(self, exc: BaseException) -> _FailureDecision | None:
        return _classificar_falha(exc)

    def _call_claude(self, system_prompt: str, context_payload: str, model: str | None = None) -> str:
        """Uma única tentativa de chamada Claude (sem retry exterior).

        Envia ``model`` (ou self._model) no payload.
        """
        modelo_usado = model or self._model
        payload = {
            "model": modelo_usado,
            "max_tokens": 2048,
            "system": system_prompt
            + "\nResponda APENAS com um objeto JSON válido estritamente no schema solicitado, sem marcação markdown adicional.",
            "messages": [{"role": "user", "content": context_payload}],
        }
        resp = self._client.post("/messages", json=payload)
        resp.raise_for_status()
        data = resp.json()
        content_blocks = data.get("content", [])
        texts = [b.get("text", "") for b in content_blocks if b.get("type") == "text"]
        content = "".join(texts)
        if not content:
            raise ValueError("Resposta do LLM Claude veio vazia")
        return content

    def _classify_once(
        self,
        sampled_text: str,
        cip_text: str,
        external_metadata: ExternalMetadata | None,
        used_ocr: bool = False,
        source_path: Path | None = None,
        *,
        model: str | None = None,
    ) -> ClassificationResult:
        """Uma única tentativa física de classificação.

        Exceções brutas vazam para o dispatcher (não capturam Exception).
        """
        modelo_usado = model or self._model
        system_prompt = build_system_prompt()
        context_payload = build_context_payload(
            sampled_text, cip_text, external_metadata, source_path=source_path
        )
        content = self._call_claude(system_prompt, context_payload, model=modelo_usado)
        output = _parse_classification_json(content)
        return _finalize_classification(output, used_ocr, "claude", modelo_usado)

    def classify(
        self,
        sampled_text: str,
        cip_text: str,
        external_metadata: ExternalMetadata | None,
        used_ocr: bool = False,
        source_path: Path | None = None,
    ) -> ClassificationResult:
        """Classificação de uso direto de provedor único.

        Orçamento máximo de MAX_TENTATIVAS_FISICAS=4 entre os modelos do
        provedor, dormindo backoff 2/2/4 s via cooldown_state.sleep somente
        se espera <= 4 s e sem alternativa elegível.
        """
        short = _check_short_circuit(sampled_text, cip_text, external_metadata, used_ocr)
        if short is not None:
            return short

        modelos = [self._model]
        tentativas = 0
        indice_modelo = 0
        ultimo_erro: str | None = None
        while tentativas < MAX_TENTATIVAS_FISICAS and indice_modelo < len(modelos):
            modelo = modelos[indice_modelo]
            tentativas += 1
            try:
                return self._classify_once(
                    sampled_text,
                    cip_text,
                    external_metadata,
                    used_ocr,
                    source_path,
                    model=modelo,
                )
            except Exception as exc:
                decisao = self._classificar(exc)
                motivo_sanitizado = _sanitize_error_message(str(exc))
                ultimo_erro = motivo_sanitizado
                if decisao is not None and decisao.categoria == "permanente":
                    with self._cooldown_state.lock:
                        entrada_id = f"claude:{self._model}"
                        self._cooldown_state.entradas_permanentes.add(entrada_id)
                        self._cooldown_state.geracao += 1
                    break
                retry_after = decisao.retry_after if decisao is not None else None
                espera_para_dormir = None
                if retry_after is not None and retry_after <= BACKOFF_MAX_CURTO_S:
                    espera_para_dormir = retry_after
                elif (
                    decisao is not None
                    and decisao.categoria == "transitorio"
                    and retry_after is None
                ):
                    espera_para_dormir = BACKOFF_BASE_S
                if espera_para_dormir is not None:
                    self._cooldown_state.sleep(espera_para_dormir)
                # Só há um modelo -> retry com o mesmo modelo; senão avança.
                if len(modelos) > 1:
                    indice_modelo += 1
        return _error_result(
            f"Falha na chamada ao LLM Claude: {ultimo_erro or 'erro desconhecido'}",
            used_ocr,
        )


class FallbackLLMDispatcher:
    """Despachante de provedores LLM com fallback automático.

    Mantém o construtor público com pares ``(rótulo, provedor)``,
    ``_providers``, ``primary_name`` e ``provider_names``. Quando um
    ``cooldown_state`` compartilhado é fornecido, as falhas tipadas são
    publicadas nele antes de selecionar o próximo candidato.

    Regras de roteamento:
      * short-circuit antes do roteamento;
      * rotacionar sob lock SOMENTE dentro de cada família por cursor;
      * família secundária apenas após esgotar a primária;
      * para Gemini, tentar M1 entre entradas elegíveis antes de M2/M3;
      * provedores internos usam _classify_once (falha tipada vaza antes de
        _sanitize_error_message);
      * provedores externos detectam source_path via inspect.signature por
        provedor, sem try/except TypeError ao redor da chamada HTTP;
      * reserva única de sondagem com liberar_sonda em finally, proteção de
        geração contra sucesso atrasado, retorno imediato 0-rede com próximo
        prazo quando todos em cooldown longo;
      * confiança baixa legítima e erro terminal sem fallback.
    """

    def __init__(
        self,
        providers: list[tuple[str, object]],
        cooldown_state: _PoolCooldownState | None = None,
        families: list[str] | None = None,
    ) -> None:
        if not providers:
            raise ValueError("FallbackLLMDispatcher requer pelo menos um provedor.")
        self._providers: list[tuple[str, object]] = providers
        self._cooldown_state = cooldown_state or _PoolCooldownState()
        self._families: list[str] = list(families or [])
        # Cursor de round-robin por família.
        self._cursors: dict[str, int] = {}

    @property
    def primary_name(self) -> str:
        return self._providers[0][0]

    @property
    def provider_names(self) -> list[str]:
        return [nome for nome, _ in self._providers]

    def _entrada_id(self, indice_slot: int, provedor: object) -> str:
        """ID opaco de entrada por índice de slot (ex: entry:0)."""
        return f"entry:{indice_slot}"

    def _par_id(self, indice_slot: int, cand_model: str) -> str:
        """ID de par entrada/modelo (ex: entry:0:model:gemini-3.5-flash)."""
        return f"entry:{indice_slot}:model:{cand_model}"

    def _provedor_aceita_source(self, provedor: object) -> bool:
        """Detectar suporte a source_path pela assinatura, por provedor."""
        try:
            sig = inspect.signature(provedor.classify)
        except (TypeError, ValueError):
            return False
        return (
            "source_path" in sig.parameters
            or any(
                p.kind == inspect.Parameter.VAR_KEYWORD
                for p in sig.parameters.values()
            )
        )

    def _classify_provedor_interno(
        self,
        provedor: object,
        sampled_text: str,
        cip_text: str,
        external_metadata: ExternalMetadata | None,
        used_ocr: bool,
        source_path: Path | None,
        model: str | None = None,
    ) -> ClassificationResult:
        """Chamar _classify_once de provedores internos (falha tipada vaza)."""
        if hasattr(provedor, "_classify_once"):
            return provedor._classify_once(
                sampled_text,
                cip_text,
                external_metadata,
                used_ocr,
                source_path,
                model=model,
            )
        # Provedor externo: detectar source_path via inspect.signature por provedor.
        if self._provedor_aceita_source(provedor):
            return provedor.classify(
                sampled_text=sampled_text,
                cip_text=cip_text,
                external_metadata=external_metadata,
                used_ocr=used_ocr,
                source_path=source_path,
            )
        return provedor.classify(
            sampled_text=sampled_text,
            cip_text=cip_text,
            external_metadata=external_metadata,
            used_ocr=used_ocr,
        )

    def _classify_provedor_externo(
        self,
        provedor: object,
        sampled_text: str,
        cip_text: str,
        external_metadata: ExternalMetadata | None,
        used_ocr: bool,
        source_path: Path | None,
    ) -> ClassificationResult:
        """Chamar provedores externos detectando source_path por provedor."""
        if self._provedor_aceita_source(provedor):
            return provedor.classify(
                sampled_text=sampled_text,
                cip_text=cip_text,
                external_metadata=external_metadata,
                used_ocr=used_ocr,
                source_path=source_path,
            )
        return provedor.classify(
            sampled_text=sampled_text,
            cip_text=cip_text,
            external_metadata=external_metadata,
            used_ocr=used_ocr,
        )

    def _varrer_familia(
        self,
        familia: str,
        slots: list[int],
        state: _PoolCooldownState,
        sampled_text: str,
        cip_text: str,
        external_metadata: ExternalMetadata | None,
        used_ocr: bool,
        source_path: Path | None,
        agora: float,
        tentativas_fisicas: int,
        max_tentativas: int,
        transitorios_curto: list[tuple[int, object, str, float]],
    ) -> tuple[ClassificationResult | None, int, bool]:
        """Varredura de candidatos de uma família (primeira ou segunda passada).

        Monta candidatos em camadas de modelo (M1 de todos os slots, depois
        M2/M3 de slots que os possuam), rotaciona o cursor por família sob lock
        e varre os candidatos elegíveis. Retorna
        (resultado_ou_None, tentativas_fisicas_atualizadas, houve_bloqueio_sonda).
        Sempre libera a reserva de sonda em finally.
        """
        # Ler cursor de round-robin sob lock (Lock não é reentrante).
        with state.lock:
            cursor = state.cursor_por_familia.get(familia, 0) % len(slots)
        slots_rot = [slots[(cursor + off) % len(slots)] for off in range(len(slots))]
        houve_bloqueio_sonda = False

        # Montar candidatos em camadas de modelo sobre slots_rot.
        candidatos: list[tuple[int, object, str, str]] = []
        vistos_candidatos: set[tuple[int, str]] = set()
        # Camada 0: modelo primário (M1) de cada slot.
        for idx in slots_rot:
            nome, provedor = self._providers[idx]
            cand_model = getattr(provedor, "_model", "")
            chave = (idx, cand_model)
            if chave not in vistos_candidatos:
                vistos_candidatos.add(chave)
                candidatos.append((idx, provedor, cand_model, nome))
        # Camadas k>=1: _fallback_models (M2, M3...) de slots que os possuam.
        max_fallback = 0
        for idx in slots_rot:
            _, provedor = self._providers[idx]
            fbs = getattr(provedor, "_fallback_models", []) or []
            max_fallback = max(max_fallback, len(fbs))
        for k in range(max_fallback):
            for idx in slots_rot:
                nome, provedor = self._providers[idx]
                fbs = getattr(provedor, "_fallback_models", []) or []
                if k < len(fbs):
                    cand_model = fbs[k]
                    chave = (idx, cand_model)
                    if chave not in vistos_candidatos:
                        vistos_candidatos.add(chave)
                        candidatos.append((idx, provedor, cand_model, nome))

        # Varrer candidatos da família.
        for idx, provedor, cand_model, nome in candidatos:
            if tentativas_fisicas >= max_tentativas:
                break
            entrada_id = self._entrada_id(idx, provedor)
            par_id = self._par_id(idx, cand_model)

            agora_atual = state.clock()
            # Sob lock: verificar deadlines, reservar sonda única e avançar
            # o cursor da família ao adquirir candidato elegível.
            with state.lock:
                elegivel, escopo_sonda, geracao_envio, bloqueado_por_sonda = (
                    state.adquirir_candidato(entrada_id, par_id, agora_atual)
                )
                if elegivel:
                    try:
                        pos = slots.index(idx)
                    except ValueError:
                        pos = 0
                    state.cursor_por_familia[familia] = (pos + 1) % len(slots)
                    state.geracao += 1
            if not elegivel:
                if bloqueado_por_sonda:
                    houve_bloqueio_sonda = True
                continue

            # Chamada e processamento dentro de try/finally (libera sonda).
            try:
                if hasattr(provedor, "_classify_once"):
                    resultado = provedor._classify_once(
                        sampled_text,
                        cip_text,
                        external_metadata,
                        used_ocr,
                        source_path,
                        model=cand_model,
                    )
                else:
                    if self._provedor_aceita_source(provedor):
                        resultado = provedor.classify(
                            sampled_text=sampled_text,
                            cip_text=cip_text,
                            external_metadata=external_metadata,
                            used_ocr=used_ocr,
                            source_path=source_path,
                        )
                    else:
                        resultado = provedor.classify(
                            sampled_text=sampled_text,
                            cip_text=cip_text,
                            external_metadata=external_metadata,
                            used_ocr=used_ocr,
                        )

                # Resultado obtido (sucesso ou erro legado por prefixo).
                if resultado.reasoning.startswith("Falha na chamada ao LLM"):
                    # Fallback legado: NÃO derivar cooldown desse texto.
                    tentativas_fisicas += 1
                    continue

                # Sucesso: confirmar candidato sob lock (proteção de geração).
                agora_sucesso = state.clock()
                with state.lock:
                    promovido = state.confirmar_sucesso_candidato(
                        entrada_id, par_id, geracao_envio, agora_sucesso
                    )
                if not promovido:
                    # Voo antigo: não limpar bloqueio novo nem mexer no cursor,
                    # mas o resultado deste voo ainda é válido.
                    return resultado, tentativas_fisicas, houve_bloqueio_sonda

                # Proveniência canônica e modelo efetivo.
                resultado.provider_name = nome.split(" (")[0]
                if not resultado.model_name:
                    resultado.model_name = cand_model
                return resultado, tentativas_fisicas, houve_bloqueio_sonda

            except Exception as exc:
                # Classificar ANTES de _sanitize_error_message.
                decisao = _classificar_falha(exc)
                motivo_sanitizado = _sanitize_error_message(str(exc))
                _llm_logger.warning(
                    "Provedor %s (modelo=%s) falhou [cat=%s status=%s]: %s",
                    nome,
                    cand_model,
                    decisao.categoria if decisao else "desconhecida",
                    decisao.status if decisao else None,
                    motivo_sanitizado,
                )
                with state.lock:
                    if decisao is not None:
                        state.publicar_falha(
                            entrada_id, par_id, decisao, state.clock()
                        )
                        state.condition.notify_all()
                # nao_retryavel (400/JSON): pular para o próximo candidato/família,
                # não abortar toda a cadeia (só retorna imediato se não restar
                # nenhuma outra família, tratado no chamador classify()).
                if (
                    decisao is not None
                    and decisao.categoria == "nao_retryavel"
                ):
                    tentativas_fisicas += 1
                    continue
                # transitorio: anotar e continuar SEM DORMIR.
                if (
                    decisao is not None
                    and decisao.categoria == "transitorio"
                ):
                    ra = (
                        decisao.retry_after
                        if decisao.retry_after is not None
                        else BACKOFF_BASE_S
                    )
                    if ra <= BACKOFF_MAX_CURTO_S:
                        transitorios_curto.append(
                            (idx, provedor, cand_model, ra)
                        )
                tentativas_fisicas += 1
                continue

            finally:
                if escopo_sonda is not None:
                    state.liberar_sonda(escopo_sonda)

        return None, tentativas_fisicas, houve_bloqueio_sonda

    def classify(
        self,
        sampled_text: str,
        cip_text: str,
        external_metadata: ExternalMetadata | None,
        used_ocr: bool = False,
        source_path: Path | None = None,
    ) -> ClassificationResult:
        """Classificar com fallback automático e roteamento por família.

        Regras (PERF-LLM-01):
          * short-circuit antes do roteamento (sem rede);
          * famílias ordenadas por _families (quando None, inferido via
            nome.split(' (')[0]); nunca rotacionar entre famílias distintas;
          * dentro de cada família, camadas de modelo: M1 (_model) de todos os
            slots elegíveis, depois M2/M3 (_fallback_models) de slots que os
            possuam; família secundária só após esgotar a primária;
          * rotacionar cursor por família sob lock na aquisição;
          * _classify_once nos provedores internos (falha tipada vaza antes de
            _sanitize_error_message); provedores externos via classify;
          * adquirir_candidato / confirmar_sucesso_candidato / liberar_sonda
            (em finally) com proteção de geração e condition.wait para sonda;
          * nao_retryavel (400/JSON) retorna erro imediato, sem fallback;
          * prefixo legado "Falha na chamada ao LLM" nunca deriva cooldown;
          * não dormir antes de tentar alternativas; teto
            MAX_TENTATIVAS_FISICAS=4 apenas em transitorio curto sem
            alternativa; 0 sleep se todos em cooldown longo/permanente.
        """
        state = self._cooldown_state

        # Short-circuit ANTES do roteamento (sem rede).
        short = _check_short_circuit(sampled_text, cip_text, external_metadata, used_ocr)
        if short is not None:
            return short

        def _familia_provedor(nome: str, provedor: object) -> str:
            """Extrai família do rótulo ou do _provider_id do provedor."""
            rotulo_base = nome.split(" (")[0]
            if rotulo_base in familias_ordenadas:
                return rotulo_base
            pid = getattr(provedor, "_provider_id", "")
            if pid and pid in familias_ordenadas:
                return pid
            return rotulo_base

        # Famílias ordenadas: _families informado, senão inferido do rótulo.
        if self._families:
            familias_ordenadas = list(self._families)
        else:
            familias_ordenadas = []
            for nome, _ in self._providers:
                familia = nome.split(" (")[0]
                if familia not in familias_ordenadas:
                    familias_ordenadas.append(familia)

        # Família de cada slot.
        slot_family = [
            _familia_provedor(nome, provedor) for nome, provedor in self._providers
        ]

        # Ordenar famílias únicas preservando ordem de primeira aparição.
        familias_unicas: list[str] = []
        for fam in slot_family:
            if fam not in familias_unicas:
                familias_unicas.append(fam)

        tentativas_fisicas = 0
        houve_bloqueio_sonda = False
        transitorios_curto: list[tuple[int, str, float | None]] = []
        aguardou_sonda = False
        agora = state.clock()

        for familia in familias_unicas:
            slots = [i for i in range(len(self._providers)) if slot_family[i] == familia]
            if not slots:
                continue
            resultado, tentativas_fisicas, hbs = self._varrer_familia(
                familia,
                slots,
                state,
                sampled_text,
                cip_text,
                external_metadata,
                used_ocr,
                source_path,
                agora,
                tentativas_fisicas,
                float("inf"),  # Sem teto na varredura de famílias; teto só no retry loop.
                transitorios_curto,
            )
            if hbs:
                houve_bloqueio_sonda = True
            if resultado is not None:
                return resultado

        # Após varrer todas as famílias.
        with state.lock:
            proximo = state.proximo_prazo(state.clock())

        # Se houve bloqueio de sonda e nada resolveu ainda, aguardar uma rodada
        # da sonda em curso e fazer uma segunda passada nas famílias para
        # reavaliar candidatos recuperados.
        if houve_bloqueio_sonda and not aguardou_sonda and proximo is not None:
            aguardou_sonda = True
            with state.lock:
                fim = state.clock() + min(proximo, 5.0)
                while state.reserva_sondagem:
                    restante = fim - state.clock()
                    if restante <= 0:
                        break
                    state.condition.wait(timeout=min(restante, 0.5))
            # Segunda passada: reavaliar candidatos nas famílias (sondas
            # liberadas podem ter liberado deadlines).
            for familia in familias_unicas:
                slots = [i for i in range(len(self._providers)) if slot_family[i] == familia]
                if not slots:
                    continue
                resultado, tentativas_fisicas, hbs = self._varrer_familia(
                    familia,
                    slots,
                    state,
                    sampled_text,
                    cip_text,
                    external_metadata,
                    used_ocr,
                    source_path,
                    state.clock(),
                    tentativas_fisicas,
                    float("inf"),  # Sem teto na varredura de famílias.
                    transitorios_curto,
                )
                if hbs:
                    houve_bloqueio_sonda = True
                if resultado is not None:
                    return resultado

        # Transitorio curto sem alternativa: respeitar _ra (dormir _ra ate 4.0s
        # quando informado) e iterar ate atingir MAX_TENTATIVAS_FISICAS=4
        # (com backoff [2.0, 2.0, 4.0] quando _ra for None), com
        # finally: liberar_sonda.
        tentativas_retry = 0
        if transitorios_curto and tentativas_retry < MAX_TENTATIVAS_FISICAS:
            esperas = [BACKOFF_BASE_S, BACKOFF_BASE_S, BACKOFF_MAX_CURTO_S]
            for idx, provedor, cand_model, _ra in transitorios_curto:
                if tentativas_retry >= MAX_TENTATIVAS_FISICAS:
                    break
                espera = (
                    min(_ra, BACKOFF_MAX_CURTO_S)
                    if _ra is not None
                    else esperas[tentativas_retry % len(esperas)]
                )
                state.sleep(espera)
                tentativas_retry += 1
                entrada_id = self._entrada_id(idx, provedor)
                par_id = self._par_id(idx, cand_model)
                agora = state.clock()
                with state.lock:
                    elegivel, escopo_sonda, geracao_envio, bloqueado_por_sonda = (
                        state.adquirir_candidato(entrada_id, par_id, agora)
                    )
                if not elegivel:
                    continue
                try:
                    if hasattr(provedor, "_classify_once"):
                        resultado = provedor._classify_once(
                            sampled_text, cip_text, external_metadata,
                            used_ocr, source_path, model=cand_model,
                        )
                    else:
                        if self._provedor_aceita_source(provedor):
                            resultado = provedor.classify(
                                sampled_text=sampled_text, cip_text=cip_text,
                                external_metadata=external_metadata, used_ocr=used_ocr,
                                source_path=source_path,
                            )
                        else:
                            resultado = provedor.classify(
                                sampled_text=sampled_text, cip_text=cip_text,
                                external_metadata=external_metadata, used_ocr=used_ocr,
                            )
                    # Resultado obtido (sucesso ou erro legado por prefixo).
                    if resultado.reasoning.startswith("Falha na chamada ao LLM"):
                        # Fallback legado: NÃO derivar cooldown desse texto.
                        tentativas_retry += 1
                        continue
                    with state.lock:
                        promovido = state.confirmar_sucesso_candidato(
                            entrada_id, par_id, geracao_envio, state.clock()
                        )
                        state.geracao += 1
                    if promovido:
                        nome_t = self._providers[idx][0]
                        resultado.provider_name = nome_t.split(" (")[0]
                        if not resultado.model_name:
                            resultado.model_name = cand_model
                        return resultado
                    tentativas_retry += 1
                    continue
                except Exception as exc:
                    # Classificar ANTES de _sanitize_error_message e logar.
                    decisao = _classificar_falha(exc)
                    motivo_sanitizado = _sanitize_error_message(str(exc))
                    _llm_logger.warning(
                        "Provedor %s (modelo=%s) falhou [cat=%s status=%s]: %s",
                        self._providers[idx][0],
                        cand_model,
                        decisao.categoria if decisao else "desconhecida",
                        decisao.status if decisao else None,
                        motivo_sanitizado,
                    )
                    # Já foi incrementado acima (tentativas_retry); apenas libera sonda.
                    continue
                finally:
                    if escopo_sonda is not None:
                        state.liberar_sonda(escopo_sonda)
                continue

        # Retorno imediato (0 rede extra) com próximo prazo se ativo.
        if proximo is not None and proximo > 0:
            return _error_result(
                f"Falha na chamada ao LLM: todos os provedores em cooldown "
                f"(próximo prazo em {proximo:.1f}s)",
                used_ocr,
            )
        return _error_result(
            "Falha na chamada ao LLM: todos os provedores indisponíveis",
            used_ocr,
        )


def create_provider_chain(
    config: AppConfig,
    *,
    cli_provider: str | None = None,
    cli_model: str | None = None,
    cli_api_key: str | None = None,
) -> LLMProvider:
    """Criar uma cadeia de provedores LLM com fallback automático."""
    provedores_disponiveis: dict[str, dict[str, Any]] = {
        "gemini": {
            "classe": GeminiProvider,
            "chave": config.api_keys.gemini_api_key,
            "modelo_padrao": "gemini-3.5-flash",
            "chave_env": GEMINI_ENV_KEYS,
        },
        "groq": {
            "classe": GroqProvider,
            "chave": config.api_keys.groq_api_key,
            "modelo_padrao": "openai/gpt-oss-120b",
            "chave_env": ("TOMUS_GROQ_API_KEY", "GROQ_API_KEY"),
        },
        "nvidia": {
            "classe": NvidiaProvider,
            "chave": config.api_keys.nvidia_api_key,
            "modelo_padrao": "nvidia/nemotron-3.5-super-vl-120b-a12b",
            "chave_env": ("TOMUS_NVIDIA_API_KEY", "NVIDIA_API_KEY"),
        },
        "deepseek": {
            "classe": DeepSeekProvider,
            "chave": config.api_keys.deepseek_api_key,
            "modelo_padrao": "deepseek-flash",
            "chave_env": ("TOMUS_DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY"),
        },
        "claude": {
            "classe": ClaudeProvider,
            "chave": config.api_keys.claude_api_key,
            "modelo_padrao": "claude-haiku-5-5",
            "chave_env": (
                "TOMUS_CLAUDE_API_KEY",
                "CLAUDE_API_KEY",
                "ANTHROPIC_API_KEY",
            ),
        },
    }

    def _resolver_chaves(nome_provedor: str, cli_key: str | None) -> list[str]:
        if cli_key:
            return _resolve_api_keys(cli_key)
        info = provedores_disponiveis[nome_provedor]
        for env_var in info["chave_env"]:
            valor = os.environ.get(env_var, "")
            if valor:
                return _resolve_api_keys(valor)
        return _resolve_api_keys(info["chave"])

    def _resolver_modelo(nome_provedor: str, cli_model_val: str | None) -> str:
        if cli_model_val:
            return cli_model_val
        prov_cfg = (config.llm.providers or {}).get(nome_provedor, {})
        if isinstance(prov_cfg, dict) and prov_cfg.get("model"):
            return str(prov_cfg["model"])
        if config.llm.provider == nome_provedor and config.llm.model:
            return config.llm.model
        return provedores_disponiveis[nome_provedor]["modelo_padrao"]

    provedor_solicitado = cli_provider or config.llm.provider or "gemini"
    if provedor_solicitado not in provedores_disponiveis:
        provedor_solicitado = "gemini"

    # Estado volátil compartilhado por toda a cadeia (um estado por cadeia).
    cooldown_state_compartilhado = _PoolCooldownState()

    cadeia: list[tuple[str, object]] = []
    nomes_vistos: set[str] = set()

    # Lista paralela de famílias (um nome por instância na cadeia).
    familias_cadeia: list[str] = []

    def _adicionar_provedor(
        nome: str, usar_cli_key: bool, usar_cli_model: bool
    ) -> None:
        if nome in nomes_vistos:
            return
        info = provedores_disponiveis[nome]
        chaves = _resolver_chaves(nome, cli_api_key if usar_cli_key else None)
        # Deduplicar chaves idênticas por provedor após _resolve_api_keys,
        # preservando ordem e precedência CLI/ambiente/config.
        chaves = _deduplicar_chaves(chaves)
        if not chaves:
            return
        modelo = _resolver_modelo(nome, cli_model if usar_cli_model else None)
        for idx, chave in enumerate(chaves):
            instancia = info["classe"](
                api_key=chave,
                model=modelo,
                cooldown_state=cooldown_state_compartilhado,
            )
            rotulo = nome if idx == 0 else f"{nome} (pool chave {idx + 1})"
            cadeia.append((rotulo, instancia))
            familias_cadeia.append(nome.split(" (")[0])
        nomes_vistos.add(nome)

    _adicionar_provedor(
        provedor_solicitado,
        usar_cli_key=(cli_provider is not None),
        usar_cli_model=(cli_model is not None),
    )

    for nome in config.llm.fallback_chain:
        if nome != provedor_solicitado:
            _adicionar_provedor(nome, usar_cli_key=False, usar_cli_model=False)

    if not cadeia:
        for nome in ("gemini", "nvidia", "deepseek", "claude", "groq"):
            _adicionar_provedor(nome, usar_cli_key=False, usar_cli_model=False)
            if cadeia:
                break

    if not cadeia:
        raise ValueError(
            "Nenhum provedor de LLM tem chave de API configurada. "
            "Defina gemini_api_key, nvidia_api_key, deepseek_api_key, "
            "claude_api_key, groq_api_key no config.toml "
            "ou variáveis de ambiente."
        )

    return FallbackLLMDispatcher(
        cadeia,
        cooldown_state=cooldown_state_compartilhado,
        families=familias_cadeia,
    )
