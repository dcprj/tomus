"""Classificador LLM com protocolo extensível e provedores múltiplos (Item 18).

Declara o Protocol LLMProvider, aplica short-circuit antes da chamada de rede
quando o texto alfanumérico útil for < 50 caracteres e não houver
ExternalMetadata (confidence_score = 0.0), implementa múltiplos provedores
(Gemini, NVIDIA, DeepSeek, Claude, Groq) com saída estruturada, retry em HTTP
429/503, normalização taxonômica/autores, filtro de identificadores contaminantes
e teto min(score, 0.50) quando o título for vazio/genérico sem autor.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from tomus.core.config import mask_key
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
    validate_or_repair_pair,
    repair_taxonomy_levels,
)
from tomus.extractors.identifiers import normalize_doi, normalize_isbn

# Limite de texto alfanumérico útil abaixo do qual ocorre short-circuit.
MIN_USEFUL_CHARS = 50

# Teto de confiança quando o título é vazio/genérico sem autor identificável.
GENERIC_TITLE_CONFIDENCE_CAP = 0.50

# Limiar de confiança para organização automática.
CONFIDENCE_MIN = 0.70

_llm_logger = logging.getLogger("tomus.llm")


def _resolve_api_key(api_key: str | list[str]) -> str:
    """Resolver a chave de API: se for lista, usar o primeiro elemento."""
    if isinstance(api_key, list):
        return api_key[0] if api_key else ""
    return api_key or ""


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


def _sanitize_error_message(message: str) -> str:
    import re as _re

    text = _re.sub(r"(sk-[A-Za-z0-9]{20,})", "sk-***REDACTED***", message)
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


def _is_retryable_http(exc: BaseException) -> bool:
    """Verificar se uma exceção do google-genai é um erro HTTP retryable (429/503 ou timeout)."""
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return True
    import socket

    if isinstance(exc, (TimeoutError, socket.timeout)):
        return True
    code = getattr(exc, "code", None)
    if code is None:
        response = getattr(exc, "response", None)
        if response is not None:
            code = getattr(response, "status_code", None)
    try:
        return int(code) in (429, 503, 504)
    except (TypeError, ValueError):
        return False


def _is_generic_openai_retryable(exc: BaseException) -> bool:
    """Verificar se uma exceção httpx é transitória (429/503/529 ou transporte/timeout)."""
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 503, 529)
    return False


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


def _check_short_circuit(
    sampled_text: str,
    cip_text: str,
    external_metadata: ExternalMetadata | None,
    used_ocr: bool,
    provider_name: str = "",
    model_name: str = "",
) -> ClassificationResult | None:
    """Retornar ClassificationResult de short-circuit se texto útil < 50 chars e sem metadados."""
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
            provider_name=provider_name,
            model_name=model_name,
        )
    return None


def _error_result(
    reasoning: str,
    used_ocr: bool,
    provider_name: str = "",
    model_name: str = "",
) -> ClassificationResult:
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
        provider_name=provider_name,
        model_name=model_name,
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
    """Provedor Gemini usando google-genai com saída estruturada."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3.5-flash",
        max_sampled_chars: int = 15_000,
    ) -> None:
        from google.genai import Client
        from google.genai import types as genai_types

        http_options = genai_types.HttpOptions(
            timeout=45_000,
            client_args={"timeout": 45.0},
        )
        self._client = Client(api_key=api_key, http_options=http_options)
        self._model = model
        self._max_sampled_chars = max_sampled_chars
        self._types = genai_types
        self._fallback_models = ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-3.1-flash-lite"]

    def _is_404(self, exc: BaseException) -> bool:
        code = getattr(exc, "code", None)
        try:
            return int(code) == 404
        except (TypeError, ValueError):
            return False

    @retry(
        retry=retry_if_exception(_is_retryable_http),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _call_gemini(
        self,
        system_prompt: str,
        context_payload: str,
    ) -> LLMClassificationOutput:
        config = self._types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            response_schema=LLMClassificationOutput,
            temperature=0.1,
        )
        ultimo_erro: Exception | None = None
        modelos_a_tentar = [self._model] + [
            m for m in self._fallback_models if m != self._model
        ]
        for modelo in modelos_a_tentar:
            try:
                response = self._client.models.generate_content(
                    model=modelo,
                    contents=context_payload,
                    config=config,
                )
                parsed = response.parsed
                if parsed is None:
                    raise ValueError("Resposta do Gemini não pôde ser interpretada como JSON")
                if not isinstance(parsed, LLMClassificationOutput):
                    parsed = LLMClassificationOutput.model_validate(parsed)
                return parsed
            except Exception as exc:
                ultimo_erro = exc
                if self._is_404(exc) or _is_retryable_http(exc):
                    continue
                raise
        raise ultimo_erro or RuntimeError("Falha ao chamar a API Gemini")

    def classify(
        self,
        sampled_text: str,
        cip_text: str,
        external_metadata: ExternalMetadata | None,
        used_ocr: bool = False,
        source_path: Path | None = None,
    ) -> ClassificationResult:
        short = _check_short_circuit(
            sampled_text, cip_text, external_metadata, used_ocr, "gemini", self._model
        )
        if short is not None:
            return short

        system_prompt = build_system_prompt()
        context_payload = build_context_payload(
            sampled_text, cip_text, external_metadata, source_path=source_path
        )

        try:
            output = self._call_gemini(system_prompt, context_payload)
        except Exception as exc:
            return _error_result(
                f"Falha na chamada ao LLM: {_sanitize_error_message(str(exc))}",
                used_ocr,
                "gemini",
                self._model,
            )

        return _finalize_classification(output, used_ocr, "gemini", self._model)


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

    @retry(
        retry=retry_if_exception(_is_generic_openai_retryable),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _call_chat_completions(self, system_prompt: str, context_payload: str) -> str:
        payload: dict[str, Any] = {
            "model": self._model,
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

    def classify(
        self,
        sampled_text: str,
        cip_text: str,
        external_metadata: ExternalMetadata | None,
        used_ocr: bool = False,
        source_path: Path | None = None,
    ) -> ClassificationResult:
        short = _check_short_circuit(
            sampled_text, cip_text, external_metadata, used_ocr
        )
        if short is not None:
            return short

        system_prompt = build_system_prompt()
        context_payload = build_context_payload(
            sampled_text, cip_text, external_metadata, source_path=source_path
        )

        try:
            content = self._call_chat_completions(system_prompt, context_payload)
        except Exception as exc:
            return _error_result(
                f"Falha na chamada ao LLM {self._provider_label}: {_sanitize_error_message(str(exc))}",
                used_ocr,
            )

        output = _parse_classification_json(content)
        return _finalize_classification(output, used_ocr, self._provider_id, self._model)


class NvidiaProvider(_OpenAICompatibleProvider):
    """Provedor NVIDIA NIM usando httpx diretamente."""

    _provider_label = "NVIDIA"
    _provider_id = "nvidia"
    _max_tokens = 4096
    _allow_reasoning_fallback = True

    def __init__(
        self,
        api_key: str,
        model: str = "meta/llama-3.2-90b-vision-instruct",
        base_url: str = "https://integrate.api.nvidia.com/v1",
        max_sampled_chars: int = 15_000,
    ) -> None:
        super().__init__(api_key, model, base_url, max_sampled_chars)


class DeepSeekProvider(_OpenAICompatibleProvider):
    """Provedor DeepSeek usando httpx diretamente."""

    _provider_label = "DeepSeek"
    _provider_id = "deepseek"

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-flash",
        base_url: str = "https://api.deepseek.com/v1",
        max_sampled_chars: int = 15_000,
    ) -> None:
        super().__init__(api_key, model, base_url, max_sampled_chars)


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
    ) -> None:
        super().__init__(api_key, model, base_url, max_sampled_chars)


class ClaudeProvider:
    """Provedor Anthropic Claude usando httpx diretamente."""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-haiku-5-5",
        base_url: str = "https://api.anthropic.com/v1",
        max_sampled_chars: int = 15_000,
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

    @retry(
        retry=retry_if_exception(_is_generic_openai_retryable),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _call_claude(self, system_prompt: str, context_payload: str) -> str:
        payload = {
            "model": self._model,
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

    def classify(
        self,
        sampled_text: str,
        cip_text: str,
        external_metadata: ExternalMetadata | None,
        used_ocr: bool = False,
        source_path: Path | None = None,
    ) -> ClassificationResult:
        short = _check_short_circuit(
            sampled_text, cip_text, external_metadata, used_ocr
        )
        if short is not None:
            return short

        system_prompt = build_system_prompt()
        context_payload = build_context_payload(
            sampled_text, cip_text, external_metadata, source_path=source_path
        )

        try:
            content = self._call_claude(system_prompt, context_payload)
        except Exception as exc:
            return _error_result(
                f"Falha na chamada ao LLM Claude: {_sanitize_error_message(str(exc))}",
                used_ocr,
            )

        output = _parse_classification_json(content)
        return _finalize_classification(output, used_ocr, "claude", self._model)


class FallbackLLMDispatcher:
    """Despachante de provedores LLM com fallback automático."""

    def __init__(self, providers: list[tuple[str, object]]) -> None:
        if not providers:
            raise ValueError("FallbackLLMDispatcher requer pelo menos um provedor.")
        self._providers: list[tuple[str, object]] = providers

    @property
    def primary_name(self) -> str:
        return self._providers[0][0]

    @property
    def provider_names(self) -> list[str]:
        return [nome for nome, _ in self._providers]

    def classify(
        self,
        sampled_text: str,
        cip_text: str,
        external_metadata: ExternalMetadata | None,
        used_ocr: bool = False,
        source_path: Path | None = None,
    ) -> ClassificationResult:
        ultimo_resultado: ClassificationResult | None = None
        ultimo_erro: str | None = None

        for indice, (nome, provedor) in enumerate(self._providers):
            try:
                try:
                    resultado = provedor.classify(
                        sampled_text=sampled_text,
                        cip_text=cip_text,
                        external_metadata=external_metadata,
                        used_ocr=used_ocr,
                        source_path=source_path,
                    )
                except TypeError:
                    resultado = provedor.classify(
                        sampled_text=sampled_text,
                        cip_text=cip_text,
                        external_metadata=external_metadata,
                        used_ocr=used_ocr,
                    )
            except Exception as exc:
                ultimo_erro = str(exc)
                proximo = (
                    self._providers[indice + 1][0]
                    if indice + 1 < len(self._providers)
                    else "nenhum (último)"
                )
                _llm_logger.warning(
                    "Provedor %s falhou: %s. Tentando fallback para %s...",
                    nome,
                    exc,
                    proximo,
                )
                ultimo_resultado = _error_result(
                    f"Falha na chamada ao LLM {nome}: {_sanitize_error_message(str(exc))}",
                    used_ocr,
                )
                continue

            if resultado.reasoning.startswith("Falha na chamada ao LLM"):
                ultimo_erro = resultado.reasoning
                proximo = (
                    self._providers[indice + 1][0]
                    if indice + 1 < len(self._providers)
                    else "nenhum (último)"
                )
                _llm_logger.warning(
                    "Provedor %s falhou: %s. Tentando fallback para %s...",
                    nome,
                    resultado.reasoning,
                    proximo,
                )
                ultimo_resultado = resultado
                continue

            if not resultado.provider_name:
                resultado.provider_name = nome.split(" (")[0]
            if not resultado.model_name:
                resultado.model_name = str(getattr(provedor, "_model", ""))
            return resultado

        if ultimo_resultado is not None:
            return ultimo_resultado
        return _error_result(
            f"Falha na chamada ao LLM: {_sanitize_error_message(str(ultimo_erro or 'provedor desconhecido'))}",
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
            "chave_env": ("BIBLIOTEC_GEMINI_API_KEY", "GEMINI_API_KEY"),
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
            "modelo_padrao": "meta/llama-3.2-90b-vision-instruct",
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

    cadeia: list[tuple[str, object]] = []
    nomes_vistos: set[str] = set()

    def _adicionar_provedor(
        nome: str, usar_cli_key: bool, usar_cli_model: bool
    ) -> None:
        if nome in nomes_vistos:
            return
        info = provedores_disponiveis[nome]
        chaves = _resolver_chaves(nome, cli_api_key if usar_cli_key else None)
        if not chaves:
            return
        modelo = _resolver_modelo(nome, cli_model if usar_cli_model else None)
        for idx, chave in enumerate(chaves):
            instancia = info["classe"](api_key=chave, model=modelo)
            rotulo = nome if idx == 0 else f"{nome} (pool chave {idx + 1})"
            cadeia.append((rotulo, instancia))
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

    return FallbackLLMDispatcher(cadeia)
