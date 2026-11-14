"""Módulo de validação sintática e ativa (Health Check) de chaves de API.

Fornece regras rigorosas de formato para provedores de LLM e Enriquecimento,
além de testes de conexão ativa contra os endpoints oficiais.
"""

from __future__ import annotations

import json
import re
from typing import Any

# Regras estritas de validação sintática por campo
KEY_VALIDATION_RULES = {
    "gemini_api_key": {
        "min_len": 8,
        "prefix": ("AIzaSy", "AQ."),
        "prefix_optional": False,
        "email": False,
        "label": "Google Gemini (começa com 'AIzaSy' ou 'AQ.')",
    },
    "groq_api_key": {
        "min_len": 8,
        "prefix": "gsk_",
        "prefix_optional": False,
        "email": False,
        "label": "Groq Cloud (deve começar com 'gsk_')",
    },
    "nvidia_api_key": {
        "min_len": 8,
        "prefix": "nvapi-",
        "prefix_optional": False,
        "email": False,
        "label": "NVIDIA NIM (deve começar com 'nvapi-')",
    },
    "deepseek_api_key": {
        "min_len": 8,
        "prefix": "sk-",
        "prefix_optional": False,
        "email": False,
        "label": "DeepSeek (deve começar com 'sk-')",
    },
    "claude_api_key": {
        "min_len": 8,
        "prefix": "sk-ant-",
        "prefix_optional": False,
        "email": False,
        "label": "Anthropic Claude (deve começar com 'sk-ant-')",
    },
    "google_books_api_key": {
        "min_len": 8,
        "prefix": ("AIzaSy", "AQ."),
        "prefix_optional": False,
        "email": False,
        "label": "Google Books (começa com 'AIzaSy' ou 'AQ.')",
    },
    "openalex_polite_email": {
        "min_len": 5,
        "prefix": "",
        "prefix_optional": True,
        "email": True,
        "label": "OpenAlex (e-mail institucional)",
    },
}

_EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _normalize_field_name(field_or_provider: Any) -> str:
    """Normaliza o nome do provedor, campo ou rótulo para a chave correspondente no dicionário de regras."""
    if not field_or_provider or not isinstance(field_or_provider, str):
        return ""
    f = field_or_provider.strip().lower()

    if "gemini" in f or "google_genai" in f:
        return "gemini_api_key"
    if "groq" in f:
        return "groq_api_key"
    if "claude" in f or "anthropic" in f:
        return "claude_api_key"
    if "deepseek" in f:
        return "deepseek_api_key"
    if "nvidia" in f or "nim" in f:
        return "nvidia_api_key"
    if "books" in f:
        return "google_books_api_key"
    if "openalex" in f:
        return "openalex_polite_email"

    if not f.endswith("_key") and not f.endswith("_email"):
        return f"{f}_api_key"
    return f


def validate_key_syntax(field_or_provider: str, key_token: str) -> tuple[bool, str]:
    """Validar sintaticamente uma única chave de API de acordo com o padrão do provedor.

    Retorna (valido: bool, mensagem_erro: str).
    """
    key_token = key_token.strip()
    if not key_token:
        return True, ""

    field_name = _normalize_field_name(field_or_provider)
    rule = KEY_VALIDATION_RULES.get(field_name)
    if rule is None:
        return True, ""

    prefix = rule["prefix"]
    prefix_optional = rule.get("prefix_optional", False)
    min_len = rule["min_len"]
    require_email = rule.get("email", False)

    if require_email:
        if not _EMAIL_REGEX.match(key_token):
            return False, "E-mail inválido"
        return True, ""

    if prefix and not prefix_optional:
        if isinstance(prefix, (tuple, list)):
            if not any(key_token.startswith(p) for p in prefix):
                expected = " ou ".join(f"'{p}'" for p in prefix)
                return False, f"Formato inválido: deve começar com {expected}"
        elif isinstance(prefix, str) and not key_token.startswith(prefix):
            return False, f"Formato inválido: deve começar com '{prefix}'"

    if min_len and len(key_token) < min_len:
        return False, f"Mínimo de {min_len} caracteres"

    return True, ""


def validate_key_format(field_or_provider: str, value: str) -> tuple[bool, str]:
    """Validar sintaticamente uma chave ou conjunto de chaves separadas por vírgula.

    Retorna (valido: bool, mensagem_erro: str).
    """
    value = value.strip()
    if not value:
        return True, ""

    tokens = [t.strip() for t in value.split(",") if t.strip()]
    if not tokens:
        return True, ""

    for idx, token in enumerate(tokens):
        ok, err = validate_key_syntax(field_or_provider, token)
        if not ok:
            prefix_info = f"Chave {idx + 1}: " if len(tokens) > 1 else ""
            return False, f"{prefix_info}{err}"

    return True, ""


def _extract_error_detail(resp: Any) -> str:
    """Extrai mensagem descritiva de erro retornada pela API do provedor."""
    try:
        data = resp.json()
        if isinstance(data, dict):
            err = data.get("error")
            if isinstance(err, dict):
                return str(err.get("message") or err.get("type") or err)
            if isinstance(err, str):
                return err
            if "detail" in data:
                return str(data["detail"])
            if "message" in data:
                return str(data["message"])
    except Exception:
        pass
    text = getattr(resp, "text", "") or ""
    return str(text)[:120].strip()


def validate_provider_key_live(
    provider_or_field: str, api_key: str, timeout: float = 12.0
) -> tuple[bool, str]:
    """Testa ativamente uma chave de API contra o endpoint oficial do provedor via HTTP mínimo.

    Retorna (sucesso: bool, mensagem_detalhada: str).
    """
    import httpx

    prov = _normalize_field_name(provider_or_field)
    key = (api_key or "").strip()
    if not key:
        return False, "Chave não informada"

    # Checar sintaxe primeiro para evitar requisições com formato sabidamente errado
    ok, err = validate_key_syntax(prov, key)
    if not ok:
        return False, f"Falha de formato: {err}"

    try:
        if prov == "gemini_api_key":
            with httpx.Client(timeout=timeout) as client:
                resp = client.get(
                    "https://generativelanguage.googleapis.com/v1beta/models",
                    params={"key": key},
                )
                if resp.status_code == 200:
                    return True, "Chave autenticada com sucesso (Google Gemini)"
                elif resp.status_code in (400, 403):
                    detail = _extract_error_detail(resp)
                    return False, f"Chave recusada pelo Google ({detail or f'HTTP {resp.status_code}: Chave inválida'})"
                elif resp.status_code == 429:
                    return True, "Chave válida na API (Atenção: Limite de cota atingido HTTP 429)"
                else:
                    detail = _extract_error_detail(resp)
                    return False, f"Erro HTTP {resp.status_code} na API do Gemini: {detail}"

        elif prov == "groq_api_key":
            with httpx.Client(timeout=timeout) as client:
                resp = client.get(
                    "https://api.groq.com/openai/v1/models",
                    headers={"Authorization": f"Bearer {key}"},
                )
                if resp.status_code == 200:
                    return True, "Chave autenticada com sucesso (Groq Cloud)"
                elif resp.status_code in (401, 403):
                    detail = _extract_error_detail(resp)
                    return False, f"Chave recusada pela Groq ({detail or 'HTTP 401: Não autorizada'})"
                elif resp.status_code == 429:
                    return True, "Chave válida na API (Atenção: Limite de cota atingido HTTP 429)"
                else:
                    detail = _extract_error_detail(resp)
                    return False, f"Erro HTTP {resp.status_code} na API da Groq: {detail}"

        elif prov == "claude_api_key":
            with httpx.Client(timeout=timeout) as client:
                resp = client.get(
                    "https://api.anthropic.com/v1/models",
                    headers={
                        "x-api-key": key,
                        "anthropic-version": "2023-06-01",
                    },
                )
                if resp.status_code == 200:
                    return True, "Chave autenticada com sucesso (Anthropic Claude)"
                elif resp.status_code in (401, 403):
                    detail = _extract_error_detail(resp)
                    return False, f"Chave recusada pela Anthropic ({detail or 'HTTP 401: Não autorizada'})"
                elif resp.status_code == 429:
                    return True, "Chave válida na API (Atenção: Limite de cota atingido HTTP 429)"
                else:
                    detail = _extract_error_detail(resp)
                    return False, f"Erro HTTP {resp.status_code} na API da Anthropic: {detail}"

        elif prov == "deepseek_api_key":
            with httpx.Client(timeout=timeout) as client:
                resp = client.get(
                    "https://api.deepseek.com/models",
                    headers={"Authorization": f"Bearer {key}"},
                )
                if resp.status_code == 200:
                    return True, "Chave autenticada com sucesso (DeepSeek)"
                elif resp.status_code in (401, 403):
                    detail = _extract_error_detail(resp)
                    return False, f"Chave recusada pela DeepSeek ({detail or 'HTTP 401: Não autorizada'})"
                elif resp.status_code == 429:
                    return True, "Chave válida na API (Atenção: Limite de cota atingido HTTP 429)"
                else:
                    detail = _extract_error_detail(resp)
                    return False, f"Erro HTTP {resp.status_code} na API da DeepSeek: {detail}"

        elif prov == "nvidia_api_key":
            with httpx.Client(timeout=timeout) as client:
                resp = client.get(
                    "https://integrate.api.nvidia.com/v1/models",
                    headers={"Authorization": f"Bearer {key}"},
                )
                if resp.status_code == 200:
                    return True, "Chave autenticada com sucesso (NVIDIA NIM)"
                elif resp.status_code in (401, 403):
                    detail = _extract_error_detail(resp)
                    return False, f"Chave recusada pela NVIDIA ({detail or 'HTTP 401: Não autorizada'})"
                elif resp.status_code == 429:
                    return True, "Chave válida na API (Atenção: Limite de cota atingido HTTP 429)"
                else:
                    detail = _extract_error_detail(resp)
                    return False, f"Erro HTTP {resp.status_code} na API da NVIDIA: {detail}"

        elif prov == "google_books_api_key":
            with httpx.Client(timeout=timeout) as client:
                resp = client.get(
                    "https://www.googleapis.com/books/v1/volumes",
                    params={"q": "isbn:9780132350884", "key": key, "maxResults": 1},
                )
                if resp.status_code == 200:
                    return True, "Chave autenticada com sucesso (Google Books)"
                elif resp.status_code in (400, 403):
                    detail = _extract_error_detail(resp)
                    return False, f"Chave recusada pelo Google Books ({detail or 'HTTP 400/403: Chave inválida'})"
                else:
                    detail = _extract_error_detail(resp)
                    return False, f"Erro HTTP {resp.status_code} na API do Google Books: {detail}"

        return False, f"Provedor não suportado para validação ativa: {provider_or_field}"

    except httpx.ConnectError:
        return False, "Falha de conexão com o endpoint do provedor (sem acesso à rede)"
    except httpx.TimeoutException:
        return False, "Tempo limite esgotado ao contatar o servidor do provedor"
    except Exception as exc:
        return False, f"Erro inesperado de validação: {exc}"
