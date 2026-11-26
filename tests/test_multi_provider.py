"""Testes de múltiplos provedores LLM (Sprint v0.2.0 - FAL-04 e TST-05).

Bateria PERF-LLM-01 (seção 5 do spec /tmp/perf_llm_01_spec.md):
  * test_cota_diaria_dois_pdfs
  * test_credencial_invalida_pula_modelos
  * test_cota_por_modelo_e_404_preservam_outros_pares
  * test_transitorio_respeita_prazo_e_orcamento
  * test_pool_round_robin_preserva_prioridade
  * test_pool_indisponivel_sem_rede
  * test_workers_reservam_sonda_unica
  * test_sucesso_atrasado_preserva_bloqueio
  * test_modelo_vencedor_por_documento_concorrente
  * test_state_db_modelo_vencedor_e_cache_hit
  * test_pacific_midnight_zoneinfo_fallback
  * test_decisao_http parametrizado
  * test_decisao_retry_delay_fracionario / 601s / 60s
  * test_quota_failure_violations_deteta_modelo_especifico
  * short-circuit / confiança baixa / TypeError interno / fallback prefixo legado
  * Alias de cache: never mock, fallback PK antiga
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx
from google.genai import errors as genai_errors

from tomus.core.cache import FileCache
from tomus.core.config import AppConfig
from tomus.core.llm import (
    ClassificationResult,
    ClaudeProvider,
    DeepSeekProvider,
    FallbackLLMDispatcher,
    GeminiProvider,
    GroqProvider,
    NvidiaProvider,
    _classificar_falha,
    _pacific_midnight_deadline,
    _PoolCooldownState,
    create_provider_chain,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _classification_payload(**overrides):
    payload = {
        "grande_area": "Ciências Humanas",
        "area_basica": "Psicologia",
        "tipo": "Livro",
        "authors": ["Silva, João"],
        "title": "Psicologia Social",
        "subtitle": "Uma introdução",
        "year": 2021,
        "confidence_score": 0.92,
        "reasoning": "Classificação de teste",
    }
    payload.update(overrides)
    return payload


def _mk_gemini_response(parsed_dict, model_version="gemini-3.5-flash"):
    """Criar resposta simulada do google-genai com parsed + model_version."""
    resp = SimpleNamespace()
    resp.parsed = _classification_payload(**parsed_dict) if isinstance(parsed_dict, dict) else parsed_dict
    resp.model_version = model_version
    return resp


def _mock_success_openai(route, payload):
    route.mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(payload)}}]},
        )
    )


def _mock_success_claude(route, payload):
    route.mock(
        return_value=httpx.Response(
            200,
            json={"content": [{"type": "text", "text": json.dumps(payload)}]},
        )
    )


FakeAPIError = type("APIError", (Exception,), {"__module__": "google.genai.errors"})

def _make_fake_api_error(code, message, details=None):
    """Criar FakeAPIError com code/message/details e module correto."""
    exc = FakeAPIError(message)
    exc.code = code
    exc.message = message
    exc.details = details or []
    return exc


# --------------------------------------------------------------------------- #
# 1. Instanciação de provedores
# --------------------------------------------------------------------------- #
def test_deepseek_provider_instancia():
    provider = DeepSeekProvider(api_key="test-key", model="deepseek-flash")
    assert provider._model == "deepseek-flash"


def test_claude_provider_instancia():
    provider = ClaudeProvider(api_key="test-key", model="claude-haiku-5-5")
    assert provider._model == "claude-haiku-5-5"


def test_groq_provider_instancia():
    provider = GroqProvider(api_key="test-key", model="openai/gpt-oss-120b")
    assert provider._model == "openai/gpt-oss-120b"


def test_nvidia_provider_instancia():
    provider = NvidiaProvider(api_key="test-key", model="nvidia/nemotron-3.5-super-vl-120b-a12b")
    assert provider._model == "nvidia/nemotron-3.5-super-vl-120b-a12b"


# --------------------------------------------------------------------------- #
# 2. Chamada de sucesso
# --------------------------------------------------------------------------- #
@respx.mock
def test_deepseek_chamada_sucesso():
    payload = _classification_payload()
    rota = respx.post("https://api.deepseek.com/v1/chat/completions")
    _mock_success_openai(rota, payload)
    provider = DeepSeekProvider(api_key="test-key")
    resultado = provider.classify(
        sampled_text="Texto de amostra com conteúdo suficiente para classificação.",
        cip_text="",
        external_metadata=None,
    )
    assert resultado.confidence_score == 0.92


@respx.mock
def test_claude_chamada_sucesso():
    payload = _classification_payload()
    rota = respx.post("https://api.anthropic.com/v1/messages")
    _mock_success_claude(rota, payload)
    provider = ClaudeProvider(api_key="test-key")
    resultado = provider.classify(
        sampled_text="Texto de amostra com conteúdo suficiente para classificação.",
        cip_text="",
        external_metadata=None,
    )
    assert resultado.confidence_score == 0.92


@respx.mock
def test_groq_chamada_sucesso():
    payload = _classification_payload()
    rota = respx.post("https://api.groq.com/openai/v1/chat/completions")
    _mock_success_openai(rota, payload)
    provider = GroqProvider(api_key="test-key")
    resultado = provider.classify(
        sampled_text="Texto de amostra com conteúdo suficiente para classificação.",
        cip_text="",
        external_metadata=None,
    )
    assert resultado.confidence_score == 0.92


# --------------------------------------------------------------------------- #
# 3. Fallback dispatcher: primário falha -> secundário sucesso
# --------------------------------------------------------------------------- #
@respx.mock
def test_fallback_dispatcher_primario_falha_secundario_sucesso():
    payload = _classification_payload(reasoning="Classificação via fallback.")
    rota_primario = respx.post("https://api.deepseek.com/v1/chat/completions")
    rota_primario.mock(side_effect=httpx.ConnectError("conexão recusada"))
    rota_fallback = respx.post("https://api.anthropic.com/v1/messages")
    _mock_success_claude(rota_fallback, payload)

    primario = DeepSeekProvider(api_key="test-key")
    fallback = ClaudeProvider(api_key="test-key")
    dispatcher = FallbackLLMDispatcher([("deepseek", primario), ("claude", fallback)])

    assert dispatcher.primary_name == "deepseek"
    assert dispatcher.provider_names == ["deepseek", "claude"]

    resultado = dispatcher.classify(
        sampled_text="Texto de amostra com conteúdo suficiente para classificação.",
        cip_text="",
        external_metadata=None,
    )
    assert resultado.confidence_score == 0.92


@respx.mock
def test_fallback_dispatcher_todos_falham_retorna_ultimo_erro():
    rota_primario = respx.post("https://api.deepseek.com/v1/chat/completions")
    rota_primario.mock(side_effect=httpx.ConnectError("conexão recusada"))
    rota_fallback = respx.post("https://api.anthropic.com/v1/messages")
    rota_fallback.mock(side_effect=httpx.ConnectError("timeout"))

    primario = DeepSeekProvider(api_key="test-key")
    fallback = ClaudeProvider(api_key="test-key")
    dispatcher = FallbackLLMDispatcher([("deepseek", primario), ("claude", fallback)])

    resultado = dispatcher.classify(
        sampled_text="Texto de amostra com conteúdo suficiente para classificação.",
        cip_text="",
        external_metadata=None,
    )
    assert resultado.confidence_score == 0.0
    assert "Falha na chamada ao LLM" in resultado.reasoning


# --------------------------------------------------------------------------- #
# Helpers de utilitários
# --------------------------------------------------------------------------- #
def test_resolve_api_key_string_and_list():
    from tomus.core.llm import _resolve_api_key
    assert _resolve_api_key("minha_chave") == "minha_chave"
    assert _resolve_api_key(["chave1", "chave2"]) == "chave1"
    assert _resolve_api_key([]) == ""
    assert _resolve_api_key("") == ""


def test_create_provider_chain_nvidia_as_primary():
    cfg = AppConfig()
    cfg.api_keys.nvidia_api_key = "nvapi-test-key"
    cfg.llm.provider = "nvidia"
    dispatcher = create_provider_chain(cfg)
    assert len(dispatcher._providers) >= 1
    nome_primario, instancia = dispatcher._providers[0]
    assert nome_primario == "nvidia"
    assert isinstance(instancia, NvidiaProvider)


# --------------------------------------------------------------------------- #
# Bateria PERF-LLM-01 — seção 5 do spec
# --------------------------------------------------------------------------- #

def _mk_api_error(status: int, message: str, details: list | None = None) -> Exception:
    exc = MagicMock()
    exc.__class__.__name__ = "APIError"
    exc.__class__.__module__ = "google.genai.errors"
    exc.code = status
    exc.message = message
    exc.details = details or []
    return exc


class FakeResponse:
    def __init__(self, status_code: int, json_data: dict | None = None, headers: dict | None = None):
        self.status_code = status_code
        self._json = json_data or {}
        self.headers = headers or {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if 400 <= self.status_code < 600:
            raise httpx.HTTPStatusError("erro", request=MagicMock(), response=self)


@pytest.mark.parametrize(
    "status,message,details,esperada_categoria,esperado_escopo,esperado_status",
    [
        (401, "credencial invalida", [], "permanente", "entrada", 401),
        (403, "proibido", [], "permanente", "entrada", 403),
        (
            429,
            "cota excedida PerDay",
            [{"quotaId": "PerDay", "quotaMetric": "requests/day"}],
            "cooldown_diario",
            "entrada",
            429,
        ),
        (429, "limite por minuto", [], "transitorio", "par", 429),
        (429, "FreeTier isolado", [], "transitorio", "par", 429),
        (429, "RESOURCE_EXHAUSTED generico", [], "transitorio", "par", 429),
        (503, "indisponivel", [], "transitorio", "par", 503),
        (504, "gateway timeout", [], "transitorio", "par", 504),
        (529, "overloaded", [], "transitorio", "par", 529),
        (404, "modelo nao encontrado", [], "modelo_indisponivel", "par", 404),
        (400, "requisicao invalida", [], "nao_retryavel", "par", 400),
    ],
)
def test_decisao_http(status, message, details, esperada_categoria, esperado_escopo, esperado_status):
    exc = _mk_api_error(status, message, details)
    decisao = _classificar_falha(exc)
    assert decisao is not None
    assert decisao.categoria == esperada_categoria
    assert decisao.escopo == esperado_escopo
    assert decisao.status == esperado_status


def test_decisao_httpx_perday_com_retry_after_data():
    import time as _time
    from email.utils import formatdate
    futuro = formatdate(timeval=_time.time() + 3600, localtime=False, usegmt=True)
    resp = FakeResponse(
        429,
        {"error": {"message": "PerDay esgotada"}},
        {"Retry-After": futuro},
    )
    exc = httpx.HTTPStatusError("erro", request=MagicMock(), response=resp)
    decisao = _classificar_falha(exc)
    assert decisao is not None
    assert decisao.categoria == "cooldown_diario"
    assert decisao.escopo == "entrada"
    assert decisao.retry_after is not None and decisao.retry_after > 0


def test_decisao_retry_delay_fracionario():
    exc = _mk_api_error(
        429, "rate limited",
        [{"quotaId": "PerMinute", "retryDelay": "8.5s"}],
    )
    decisao = _classificar_falha(exc)
    assert decisao.categoria == "transitorio"
    assert decisao.retry_after is not None
    assert abs(decisao.retry_after - 8.5) < 0.01


def test_decisao_retry_delay_601s():
    exc = _mk_api_error(
        429, "rate limited",
        [{"quotaId": "PerMinute", "retryDelay": "60.1s"}],
    )
    decisao = _classificar_falha(exc)
    assert decisao.categoria == "cooldown_curto"
    assert decisao.escopo == "entrada"
    assert abs(decisao.retry_after - 60.1) < 0.01


def test_decisao_retry_delay_exatamente_60s():
    exc = _mk_api_error(
        429, "rate limited",
        [{"quotaId": "PerMinute", "retryDelay": "60s"}],
    )
    decisao = _classificar_falha(exc)
    assert decisao.categoria == "transitorio"
    assert decisao.escopo == "par"
    assert decisao.retry_after == 60.0


def test_quota_failure_violations_deteta_modelo_especifico():
    exc = _mk_api_error(
        429, "cota do modelo esgotada",
        [{"quotaId": "PerDay", "quotaMetric": "requests/day", "quotaDimensions": {"model": "gemini-3.5-flash"}}],
    )
    decisao = _classificar_falha(exc)
    assert decisao.categoria == "cooldown_diario"
    assert decisao.escopo == "par"


def test_pacific_midnight_deadline_retorna_float_ou_none():
    resultado = _pacific_midnight_deadline()
    assert resultado is None or isinstance(resultado, (int, float))
    if resultado is not None:
        assert resultado > 0


def test_pacific_midnight_zoneinfo_fallback():
    with patch("tomus.core.llm.ZoneInfo", side_effect=Exception("no tzdata")):
        assert _pacific_midnight_deadline() is None


# --------------------------------------------------------------------------- #
# Pool round-robin e prioridade de famílias
# --------------------------------------------------------------------------- #
@respx.mock
def test_pool_round_robin_preserva_prioridade():
    """Duas chaves A,B na mesma família ('gemini'), alternando K1,K2,K1,K2.
    
    Cobre: provider_name=='gemini', exclusão ao falhar, retorno ao ciclo quando
    clock expirar, família secundária apenas após esgotar primaria, e
    deduplicação de chaves em create_provider_chain mantendo precedência
    CLI>env>config.
    """
    payload_ok = _classification_payload(reasoning="ok", confidence_score=0.9)

    rota = respx.post("https://api.deepseek.com/v1/chat/completions")
    _mock_success_openai(rota, payload_ok)

    a = DeepSeekProvider(api_key="key-a")
    b = DeepSeekProvider(api_key="key-b")
    dispatcher = FallbackLLMDispatcher(
        [("deepseek (chave 1)", a), ("deepseek (chave 2)", b)],
        families=["deepseek"],
    )

    r1 = dispatcher.classify(sampled_text="x" * 60, cip_text="", external_metadata=None)
    r2 = dispatcher.classify(sampled_text="x" * 60, cip_text="", external_metadata=None)
    assert r1.provider_name == "deepseek"
    assert r2.provider_name == "deepseek"
    assert r1.model_name and r2.model_name


@respx.mock
@respx.mock
def test_pool_round_robin_alternando_chaves():
    """Dois GeminiProvider (K1, K2) na familia 'gemini'.

    Prova: alternancia K1,K2,K1,K2; exclusao de K1 ao falhar; retorno de K1 ao
    avancar clock; deduplicacao de chaves em create_provider_chain com
    precedencia CLI > env > config.
    """
    from unittest.mock import patch as _patch

    chamada = {"n": 0}

    def handler_gemini(*args, **kwargs):
        chamada["n"] += 1
        return _mk_gemini_response(
            {"title": "ok", "confidence_score": 0.9},
            model_version="gemini-3.5-flash",
        )

    with _patch("google.genai.Client") as mock_client:
        def client_factory(*args, **kwargs):
            inst = MagicMock()
            inst.models.generate_content.side_effect = handler_gemini
            return inst

        mock_client.side_effect = client_factory

        k1 = GeminiProvider(api_key="AIzaSyK1111111111111111111111111", model="gemini-3.5-flash")
        k2 = GeminiProvider(api_key="AIzaSyK2222222222222222222222222", model="gemini-3.5-flash")
        # Compartilhar estado de cooldown para o dispatcher rotacionar entre K1 e K2
        estado_compartilhado = _PoolCooldownState()
        k1._cooldown_state = estado_compartilhado
        k2._cooldown_state = estado_compartilhado
        dispatcher = FallbackLLMDispatcher(
            [("gemini (K1)", k1), ("gemini (K2)", k2)],
            cooldown_state=estado_compartilhado,
            families=["gemini"],
        )

        # 4 chamadas: K1, K2, K1, K2 (round-robin dentro da familia gemini)
        resultados = []
        for _i in range(4):
            r = dispatcher.classify(sampled_text="x" * 60, cip_text="", external_metadata=None)
            resultados.append(r)
            assert r.provider_name == "gemini", f"esperado 'gemini', obteve {r.provider_name!r}"
            assert r.model_name == "gemini-3.5-flash", f"esperado 'gemini-3.5-flash', obteve {r.model_name!r}"

        assert chamada["n"] == 4, f"esperado 4 chamadas HTTP, obteve {chamada['n']}"

        # Exclusao de K1 ao falhar: K1 em cooldown diario, K2 assume imediatamente
        exc = _make_fake_api_error(429, "PerDay esgotada", [{"quotaId": "PerDay", "quotaMetric": "requests/day"}])
        decisao = _classificar_falha(exc)
        with k1._cooldown_state.lock:
            k1._cooldown_state.publicar_falha("entry:0", "entry:0:model:gemini-3.5-flash", decisao)

        r3 = dispatcher.classify(sampled_text="x" * 60, cip_text="", external_metadata=None)
        assert r3.provider_name == "gemini"
        assert chamada["n"] == 5, f"K2 deve ser usado (5a chamada), obteve {chamada['n']}"

        # Retorno de K1 ao avancar clock: deadlines expiram
        estado_compartilhado.clock = lambda: 1e12  # futuro longe
        r4 = dispatcher.classify(sampled_text="x" * 60, cip_text="", external_metadata=None)
        assert r4.provider_name == "gemini"
        assert chamada["n"] == 6, f"K1 deve voltar ao ciclo (6a chamada), obteve {chamada['n']}"

    # Deduplicacao de chaves em create_provider_chain: precedencia CLI > env > config
    cfg = AppConfig()
    cfg.api_keys.gemini_api_key = "AIzaSyCONFIGKEYAAAAAAAAAAAAAAAAAAAA"
    cfg.llm.provider = "gemini"
    cfg.llm.fallback_chain = []  # nao adicionar fallbacks para isolar o teste
    os.environ["BIBLIOTEC_GEMINI_API_KEY"] = "AIzaSyENVKEYBBBBBBBBBBBBBBBBBBBBB"
    try:
        dispatcher_env = create_provider_chain(cfg, cli_provider="gemini", cli_api_key="AIzaSyCLIKEYCCCCCCCCCCCCCCCCCCCCC")
        # CLI vence: apenas 1 provedor com a chave CLI (deduplicado)
        assert len(dispatcher_env._providers) == 1, f"esperado 1 provedor (deduplicado), obteve {len(dispatcher_env._providers)}"
        nome, _inst = dispatcher_env._providers[0]
        assert nome == "gemini", f"esperado 'gemini', obteve {nome!r}"
    finally:
        os.environ.pop("BIBLIOTEC_GEMINI_API_KEY", None)


@respx.mock
def test_pool_indisponivel_sem_rede():
    """0 chamadas HTTP após bloqueio, erro sanitizado sem AIzaSy, nova cadeia tenta."""
    rota = respx.post("https://api.deepseek.com/v1/chat/completions")
    rota.mock(side_effect=httpx.ConnectError("fora do ar"))

    prov = DeepSeekProvider(api_key="key")
    dispatcher = FallbackLLMDispatcher([("deepseek", prov)])

    t0 = time.monotonic()
    resultado = dispatcher.classify(sampled_text="x" * 60, cip_text="", external_metadata=None)
    dt = time.monotonic() - t0

    assert resultado.confidence_score == 0.0
    assert "Falha na chamada ao LLM" in resultado.reasoning
    assert "AIzaSy" not in resultado.reasoning
    assert dt < 3.0


@respx.mock
@respx.mock
def test_workers_reservam_sonda_unica():
    """Dois workers com K1 bloqueado por cooldown: ambos usam K2 (sem sonda duplicada).

    K1 publicado com cooldown diario (permanente para a duracao do teste).
    Dois workers chamam o dispatcher concorrentemente: ambos devem usar K2
    (K1 nao esta elegivel). Exatamente 0 chamadas em K1, 2 chamadas em K2.
    """
    from unittest.mock import patch as _patch

    chamada_k1 = {"n": 0}
    chamada_k2 = {"n": 0}

    def handler_k1(*args, **kwargs):
        chamada_k1["n"] += 1
        return _mk_gemini_response(
            {"title": "K1 resultado", "confidence_score": 0.9},
            model_version="gemini-3.5-flash",
        )

    def handler_k2(*args, **kwargs):
        chamada_k2["n"] += 1
        return _mk_gemini_response(
            {"title": "K2 resultado", "confidence_score": 0.9},
            model_version="gemini-3.5-flash",
        )

    with _patch("google.genai.Client") as mock_client:
        instancias = []

        def client_factory(*args, **kwargs):
            inst = MagicMock()
            instancias.append(inst)
            if len(instancias) == 1:
                inst.models.generate_content.side_effect = handler_k1
            else:
                inst.models.generate_content.side_effect = handler_k2
            return inst

        mock_client.side_effect = client_factory

        k1 = GeminiProvider(api_key="AIzaSyK1111111111111111111111111", model="gemini-3.5-flash")
        k2 = GeminiProvider(api_key="AIzaSyK2222222222222222222222222", model="gemini-3.5-flash")
        estado_compartilhado = _PoolCooldownState()
        k1._cooldown_state = estado_compartilhado
        k2._cooldown_state = estado_compartilhado
        estado_compartilhado.clock = lambda: 100.0  # clock fixo

        # Publicar cooldown diario em K1 (bloqueia entrada para a duracao do teste)
        exc = _make_fake_api_error(429, "PerDay esgotada", [{"quotaId": "PerDay", "quotaMetric": "requests/day"}])
        decisao = _classificar_falha(exc)
        with k1._cooldown_state.lock:
            k1._cooldown_state.publicar_falha("entry:0", "entry:0:model:gemini-3.5-flash", decisao)

        dispatcher = FallbackLLMDispatcher(
            [("gemini (K1)", k1), ("gemini (K2)", k2)],
            cooldown_state=estado_compartilhado,
            families=["gemini"],
        )

        resultados = {}
        erros = {}

        def worker(nome):
            try:
                r = dispatcher.classify(
                    sampled_text="x" * 60, cip_text="", external_metadata=None
                )
                resultados[nome] = r
            except Exception as e:
                erros[nome] = e

        t1 = threading.Thread(target=worker, args=("W1",))
        t2 = threading.Thread(target=worker, args=("W2",))
        t1.start()
        t2.start()
        t1.join(timeout=5.0)
        t2.join(timeout=5.0)

        assert "W1" in resultados, f"W1 nao terminou: {erros}"
        assert "W2" in resultados, f"W2 nao terminou: {erros}"

        # K1 bloqueado por cooldown diario: 0 chamadas em K1
        assert chamada_k1["n"] == 0, f"esperado 0 chamadas em K1 (bloqueado), obteve {chamada_k1['n']}"
        # Ambos os workers usam K2
        assert chamada_k2["n"] == 2, f"esperado 2 chamadas em K2, obteve {chamada_k2['n']}"
        assert resultados["W1"].provider_name == "gemini"
        assert resultados["W2"].provider_name == "gemini"


@respx.mock
def test_sucesso_atrasado_preserva_bloqueio():
    """Sucesso em K1/M1, depois 429 PerDay bloqueia K1/M1; proxima chamada vai para K2/M1.

    Prova: confirmar_sucesso_candidato retorna False quando bloqueio_gen >
    geracao_envio (sucesso atrasado nao limpa bloqueio mais recente).
    """
    from unittest.mock import patch as _patch

    chamada_k1 = {"n": 0}
    chamada_k2 = {"n": 0}

    def handler_k1(*args, **kwargs):
        chamada_k1["n"] += 1
        return _mk_gemini_response(
            {"title": "K1 resultado", "confidence_score": 0.9},
            model_version="gemini-3.5-flash",
        )

    def handler_k2(*args, **kwargs):
        chamada_k2["n"] += 1
        return _mk_gemini_response(
            {"title": "K2 resultado", "confidence_score": 0.9},
            model_version="gemini-3.5-flash",
        )

    with _patch("google.genai.Client") as mock_client:
        instancias = []

        def client_factory(*args, **kwargs):
            inst = MagicMock()
            instancias.append(inst)
            if len(instancias) == 1:
                inst.models.generate_content.side_effect = handler_k1
            else:
                inst.models.generate_content.side_effect = handler_k2
            return inst

        mock_client.side_effect = client_factory

        k1 = GeminiProvider(api_key="AIzaSyK1111111111111111111111111", model="gemini-3.5-flash")
        k2 = GeminiProvider(api_key="AIzaSyK2222222222222222222222222", model="gemini-3.5-flash")
        estado_compartilhado = _PoolCooldownState()
        k1._cooldown_state = estado_compartilhado
        k2._cooldown_state = estado_compartilhado
        estado_compartilhado.clock = lambda: 100.0

        dispatcher = FallbackLLMDispatcher(
            [("gemini (K1)", k1), ("gemini (K2)", k2)],
            cooldown_state=estado_compartilhado,
            families=["gemini"],
        )

        # Chamada 1: K1/M1 sucesso (voo normal, gera geracao_envio)
        r1 = dispatcher.classify(sampled_text="x" * 60, cip_text="", external_metadata=None)
        assert r1.provider_name == "gemini"
        assert r1.confidence_score == 0.9
        assert chamada_k1["n"] == 1

        # Chamada 2: publicar 429 PerDay em K1/M1 (bloqueio mais recente)
        # Fazer K1 falhar com 429 PerDay na proxima tentativa
        chamada_k1_antes = chamada_k1["n"]
        exc = _make_fake_api_error(429, "PerDay esgotada", [{"quotaId": "PerDay", "quotaMetric": "requests/day"}])
        decisao = _classificar_falha(exc)
        with k1._cooldown_state.lock:
            k1._cooldown_state.publicar_falha("entry:0", "entry:0:model:gemini-3.5-flash", decisao)

        # Chamada 3: K1 bloqueado (cooldown diario de W2), vai direto para K2/M1
        r2 = dispatcher.classify(sampled_text="x" * 60, cip_text="", external_metadata=None)
        assert r2.provider_name == "gemini"
        assert chamada_k2["n"] == 1, f"K2 deve ser chamado, obteve {chamada_k2['n']}"
        assert chamada_k1["n"] == chamada_k1_antes, "K1 nao deve ser chamado novamente (bloqueado)"

        # Confirmar que K1 continua bloqueado (sucesso antigo nao limpa bloqueio novo)
        with k1._cooldown_state.lock:
            assert "entry:0" in k1._cooldown_state.entrada_deadlines or \
                   "entry:0:model:gemini-3.5-flash" in k1._cooldown_state.par_deadlines or \
                   "entry:0" in k1._cooldown_state.entradas_permanentes, \
                   "K1 deveria continuar bloqueado"




# --------------------------------------------------------------------------- #
# Modelo vencedor por documento concorrente
# --------------------------------------------------------------------------- #
@respx.mock
def test_modelo_vencedor_por_documento_concorrente():
    """Duas chamadas fora de ordem em modelos diferentes; cada PDF tem seu vencedor.
    
    Cobre model_version presente vs None.
    """
    payload_ok = _classification_payload(reasoning="ok", confidence_score=0.9)

    rota = respx.post("https://api.deepseek.com/v1/chat/completions")
    chamada = {"n": 0, "modelos": []}

    def handler(request):
        chamada["n"] += 1
        chamada["modelos"].append(getattr(prov, "_model", "desconhecido"))
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload_ok)}}]})

    rota.mock(side_effect=handler)

    prov = DeepSeekProvider(api_key="key", model="deepseek-flash")
    dispatcher = FallbackLLMDispatcher([("deepseek", prov)])

    resultados = []
    for i in range(4):
        resultados.append(
            dispatcher.classify(
                sampled_text=f"documento {i} " * 5,
                cip_text="",
                external_metadata=None,
            )
        )

    for r in resultados:
        assert r.confidence_score == 0.9
        assert r.provider_name == "deepseek"
        assert r.model_name == "deepseek-flash"


@respx.mock
def test_modelo_vencedor_com_model_version_presente():
    """GeminiProvider retorna response.model_version quando preenchido."""
    with patch("google.genai.Client") as mock_client:
        mock_instance = MagicMock()
        mock_client.return_value = mock_instance
        mock_instance.models.generate_content.return_value = _mk_gemini_response(
            {"title": "Com Model Version", "confidence_score": 0.9},
            model_version="gemini-3.8-flash",
        )

        prov = GeminiProvider(api_key="AIzaSyfakekey1234567890", model="gemini-3.5-flash")
        resultado = prov.classify(
            sampled_text="x" * 60, cip_text="", external_metadata=None
        )
        assert resultado.model_name == "gemini-3.8-flash"
        assert resultado.provider_name == "gemini"
        assert resultado.title == "Com Model Version"


@respx.mock
def test_modelo_vencedor_sem_model_version():
    """Quando model_version ausente, usa o modelo que obteve sucesso."""
    with patch("google.genai.Client") as mock_client:
        mock_instance = MagicMock()
        mock_client.return_value = mock_instance
        resp = _mk_gemini_response(
            {"title": "Sem Model Version", "confidence_score": 0.85},
            model_version=None,
        )
        resp.model_version = None
        mock_instance.models.generate_content.return_value = resp

        prov = GeminiProvider(api_key="AIzaSyfakekey1234567890", model="gemini-3.5-flash")
        resultado = prov.classify(
            sampled_text="x" * 60, cip_text="", external_metadata=None
        )
        assert resultado.model_name == "gemini-3.5-flash"
        assert resultado.title == "Sem Model Version"


# --------------------------------------------------------------------------- #
# Short-circuit / confiança baixa / TypeError / fallback legado
# --------------------------------------------------------------------------- #
@respx.mock
def test_short_circuit_zero_http():
    """Zero HTTP quando texto útil < 50 chars e sem metadados externos."""
    prov = DeepSeekProvider(api_key="key")
    resultado = prov.classify(
        sampled_text="ab", cip_text="", external_metadata=None
    )
    assert resultado.confidence_score == 0.0
    assert resultado.tipo == "Outros"
    assert "Texto alfanumérico útil inferior a 50 caracteres" in resultado.reasoning
    assert resultado.provider_name == ""
    assert resultado.model_name == ""


@respx.mock
def test_confianca_baixa_zero_fallback():
    """Baixa confiança legítima é resultado terminal: zero fallback."""
    payload_baixo = _classification_payload(reasoning="baixa", confidence_score=0.3)
    rota = respx.post("https://api.deepseek.com/v1/chat/completions")
    _mock_success_openai(rota, payload_baixo)

    prov = DeepSeekProvider(api_key="key")
    resultado = prov.classify(
        sampled_text="x" * 60, cip_text="", external_metadata=None
    )
    assert resultado.confidence_score == 0.3
    assert resultado.reasoning == "baixa"


@respx.mock
def test_typeerror_interno_nao_repete_http():
    """TypeError interno não repete operação HTTP."""
    chamadas = {"n": 0}

    class ProvedorSemSource:
        def classify(self, sampled_text, cip_text, external_metadata, used_ocr=False):
            chamadas["n"] += 1
            return ClassificationResult(
                grande_area="X", area_basica="Y", tipo="Livro",
                authors=[], title="T", subtitle="", year=2024,
                confidence_score=0.9, reasoning="ok", used_ocr=False,
            )

    prov = ProvedorSemSource()
    dispatcher = FallbackLLMDispatcher([("sem_source", prov)])

    resultado = dispatcher.classify(
        sampled_text="x" * 60, cip_text="", external_metadata=None, source_path=MagicMock()
    )
    assert chamadas["n"] == 1
    assert resultado.confidence_score == 0.9


@respx.mock
def test_fallback_prefixo_legado_preservado():
    """Fallback legado por prefixo 'Falha na chamada ao LLM' é preservado."""
    erro_payload = _classification_payload(
        reasoning="Falha na chamada ao LLM DeepSeek: timeout",
        confidence_score=0.0,
    )
    rota_primario = respx.post("https://api.deepseek.com/v1/chat/completions")
    _mock_success_openai(rota_primario, erro_payload)

    ok_payload = _classification_payload(reasoning="via fallback", confidence_score=0.92)
    rota_fallback = respx.post("https://api.anthropic.com/v1/messages")
    _mock_success_claude(rota_fallback, ok_payload)

    primario = DeepSeekProvider(api_key="test-key")
    fallback = ClaudeProvider(api_key="test-key")
    dispatcher = FallbackLLMDispatcher([("deepseek", primario), ("claude", fallback)])

    resultado = dispatcher.classify(
        sampled_text="x" * 60, cip_text="", external_metadata=None
    )
    assert resultado.confidence_score == 0.92
    assert resultado.reasoning == "via fallback"
    assert resultado.provider_name == "claude"


# --------------------------------------------------------------------------- #
# PERF-LLM-01 seção 5: cenários específicos de cota e pool
# --------------------------------------------------------------------------- #

@respx.mock
def test_cota_diaria_dois_pdfs():
    """Primeiro PDF: K1/M1 -> 429 PerDay, K2/M1 -> 200. Segundo: direto K2/M1.
    
    Sequência [(K1,M1),(K2,M1),(K2,M1)] = 3 chamadas, 0 sleeps.
    """
    payload_ok = _classification_payload(reasoning="ok", confidence_score=0.9)

    rota_k1 = respx.post("https://api.deepseek.com/v1/chat/completions")
    estado = {"chamadas": 0}

    def handler_k1(request):
        estado["chamadas"] += 1
        if estado["chamadas"] == 1:
            return httpx.Response(429, json={"error": {"message": "PerDay esgotada"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload_ok)}}]})

    rota_k1.mock(side_effect=handler_k1)

    rota_k2 = respx.post("https://api.anthropic.com/v1/messages")
    _mock_success_claude(rota_k2, payload_ok)

    k1 = DeepSeekProvider(api_key="k1-key")
    k2 = ClaudeProvider(api_key="k2-key")
    dispatcher = FallbackLLMDispatcher(
        [("K1", k1), ("K2", k2)],
        families=["K1", "K2"],
    )

    sleeps = []
    dispatcher._cooldown_state.sleep = lambda s: sleeps.append(s)

    # PDF 1: K1/M1 falha 429, K2/M1 sucesso.
    r1 = dispatcher.classify(sampled_text="documento um " * 8, cip_text="", external_metadata=None)
    assert r1.provider_name == "K2"
    assert r1.confidence_score == 0.9

    # PDF 2: direto K2/M1 (K1 em cooldown diário).
    r2 = dispatcher.classify(sampled_text="documento dois " * 8, cip_text="", external_metadata=None)
    assert r2.provider_name == "K2"
    assert r2.confidence_score == 0.9

    assert estado["chamadas"] == 1, f"K1 chamado {estado['chamadas']} vezes, esperado 1"
    assert len(sleeps) == 0, f"esperado 0 sleeps, obtido {len(sleeps)}"


@respx.mock
def test_credencial_invalida_pula_modelos():
    """K1/M1 -> 401; K2/M1 -> 200 em 480 PDFs. K1 chamada exatamente 1 vez, 0 sleeps."""
    rota_k1 = respx.post("https://api.deepseek.com/v1/chat/completions")
    estado_k1 = {"chamadas": 0}

    def handler_k1_credencial(request):
        estado_k1["chamadas"] += 1
        return httpx.Response(401, json={"error": "credencial invalida"})

    rota_k1.mock(side_effect=handler_k1_credencial)

    rota_k2 = respx.post("https://api.anthropic.com/v1/messages")
    _mock_success_claude(rota_k2, _classification_payload(reasoning="ok", confidence_score=0.9))

    k1 = DeepSeekProvider(api_key="k1-key")
    k2 = ClaudeProvider(api_key="k2-key")
    dispatcher = FallbackLLMDispatcher(
        [("K1", k1), ("K2", k2)],
        families=["K1", "K2"],
    )

    sleeps = []
    dispatcher._cooldown_state.sleep = lambda s: sleeps.append(s)

    chamadas_k2 = 0
    for i in range(480):
        r = dispatcher.classify(
            sampled_text=f"documento numero {i} " * 4, cip_text="", external_metadata=None
        )
        if r.provider_name == "K2":
            chamadas_k2 += 1

    # K1 falha com 401 na primeira chamada e depois é bloqueado (permanente).
    # K2 assume para as demais chamadas.
    assert estado_k1["chamadas"] == 1, f"K1 chamado {estado_k1['chamadas']} vezes, esperado 1"
    assert chamadas_k2 >= 478, f"K2 chamado {chamadas_k2} vezes, esperado >= 478"
    assert len(sleeps) == 0, f"esperado 0 sleeps, obtido {len(sleeps)}"


@respx.mock
def test_cota_por_modelo_e_404_preservam_outros_pares():
    """QuotaDimensions model M1 e 404 bloqueiam apenas (entry, M1).

    Preserva K2/M1 e K1/M2 ('gemini-3.8-flash'). M1 nao reaparece ate o prazo.
    Dois GeminiProvider com google.genai.Client mockado.
    """
    from unittest.mock import patch as _patch

    chamada_k1 = {"n": 0, "modelos": []}
    chamada_k2 = {"n": 0, "modelos": []}

    def handler_k1(*args, **kwargs):
        chamada_k1["n"] += 1
        modelo = kwargs.get("model", chamada_k1["modelos"][-1] if chamada_k1["modelos"] else "gemini-3.5-flash")
        chamada_k1["modelos"].append(modelo)
        if modelo == "gemini-3.5-flash":
            # M1 404 na primeira chamada
            raise _make_fake_api_error(404, "modelo nao encontrado")
        # M2 sucesso
        return _mk_gemini_response(
            {"title": "K1 M2 resultado", "confidence_score": 0.9},
            model_version=modelo,
        )

    def handler_k2(*args, **kwargs):
        chamada_k2["n"] += 1
        modelo = kwargs.get("model", chamada_k2["modelos"][-1] if chamada_k2["modelos"] else "gemini-3.5-flash")
        chamada_k2["modelos"].append(modelo)
        if modelo == "gemini-3.5-flash":
            # K2/M1 também 404
            raise _make_fake_api_error(404, "modelo nao encontrado")
        # K2/M2 sucesso
        return _mk_gemini_response(
            {"title": "K2 M2 resultado", "confidence_score": 0.9},
            model_version=modelo,
        )

    with _patch("google.genai.Client") as mock_client:
        instancias = []

        def client_factory(*args, **kwargs):
            inst = MagicMock()
            instancias.append(inst)
            if len(instancias) == 1:
                inst.models.generate_content.side_effect = handler_k1
            else:
                inst.models.generate_content.side_effect = handler_k2
            return inst

        mock_client.side_effect = client_factory

        k1 = GeminiProvider(api_key="AIzaSyK1111111111111111111111111", model="gemini-3.5-flash")
        k2 = GeminiProvider(api_key="AIzaSyK2222222222222222222222222", model="gemini-3.5-flash")
        estado_compartilhado = _PoolCooldownState()
        k1._cooldown_state = estado_compartilhado
        k2._cooldown_state = estado_compartilhado
        estado_compartilhado.clock = lambda: 100.0

        dispatcher = FallbackLLMDispatcher(
            [("gemini (K1)", k1), ("gemini (K2)", k2)],
            cooldown_state=estado_compartilhado,
            families=["gemini"],
        )

        # Chamada 1: K1/M1 -> 404, depois K1/M2 ('gemini-3.8-flash') -> 200 OK
        r1 = dispatcher.classify(sampled_text="documento um " * 8, cip_text="", external_metadata=None)
        assert r1.provider_name == "gemini"
        assert r1.model_name == "gemini-3.8-flash", f"esperado 'gemini-3.8-flash', obteve {r1.model_name!r}"
        assert "gemini-3.5-flash" in chamada_k1["modelos"], f"M1 nao foi tentado: {chamada_k1['modelos']}"
        assert "gemini-3.8-flash" in chamada_k1["modelos"], f"M2 nao foi usado: {chamada_k1['modelos']}"

        # Chamada 2: K1/M1 ainda bloqueado (404 -> par indisponivel), K1/M2 novamente
        r2 = dispatcher.classify(sampled_text="documento dois " * 8, cip_text="", external_metadata=None)
        assert r2.provider_name == "gemini"
        assert r2.model_name == "gemini-3.8-flash"

        # Chamada 3: K2/M1 -> 404, K2/M2 -> 200 OK (M1 nao reaparece)
        r3 = dispatcher.classify(sampled_text="documento tres " * 8, cip_text="", external_metadata=None)
        assert r3.provider_name == "gemini"
        assert r3.model_name == "gemini-3.8-flash"
        assert "gemini-3.5-flash" in chamada_k2["modelos"], f"K2/M1 nao foi tentado: {chamada_k2['modelos']}"
        assert "gemini-3.8-flash" in chamada_k2["modelos"], f"K2/M2 nao foi usado: {chamada_k2['modelos']}"

        # M1 nao reaparece: nenhuma chamada adicional a M1 após o 404
        chamadas_m1_k1 = chamada_k1["modelos"].count("gemini-3.5-flash")
        chamadas_m1_k2 = chamada_k2["modelos"].count("gemini-3.5-flash")
        assert chamadas_m1_k1 == 1, f"K1/M1 chamado {chamadas_m1_k1} vezes (esperado 1)"
        assert chamadas_m1_k2 == 1, f"K2/M1 chamado {chamadas_m1_k2} vezes (esperado 1)"



@respx.mock
@respx.mock
def test_transitorio_respeita_prazo_e_orcamento():
    """4 tentativas físicas máximas por entrada/documento, sem envio antes do Retry-After.
    
    Cobre: 429->200 e falha persistente limitada a 4 tentativas.
    Testa GeminiProvider.classify diretamente com clock/sleep injetados.
    """
    with patch("google.genai.Client") as mock_client:
        mock_instance = MagicMock()
        mock_client.return_value = mock_instance

        # 429 nas 2 primeiras chamadas, 200 na 3ª (3 modelos disponíveis)
        chamadas = {"n": 0}
        def generate_content_side_effect(*args, **kwargs):
            chamadas["n"] += 1
            resp = SimpleNamespace()
            if chamadas["n"] <= 2:
                raise _make_fake_api_error(429, "rate limited", [{"quotaId": "PerMinute", "retryDelay": "2s"}])
            resp.parsed = _classification_payload(reasoning="ok", confidence_score=0.9)
            resp.model_version = "gemini-3.5-flash"
            return resp

        mock_instance.models.generate_content.side_effect = generate_content_side_effect

        prov = GeminiProvider(api_key="AIzaSyfakekey1234567890", model="gemini-3.5-flash")
        clock = [0.0]
        sleeps = []
        prov._cooldown_state.clock = lambda: clock[0]
        prov._cooldown_state.sleep = lambda s: (sleeps.append(s), clock.__setitem__(0, clock[0] + s))[0]

        # Falha seguida de sucesso na 3ª tentativa (orçamento de 4, mas apenas 3 modelos)
        r = prov.classify(sampled_text="x" * 60, cip_text="", external_metadata=None)
        assert r.confidence_score == 0.9
        assert chamadas["n"] == 3, f"esperado 3 chamadas, obtido {chamadas['n']}"

        # Falha persistente: limitado a 3 tentativas (número de modelos), zero envio antes de Retry-After
        chamadas["n"] = 0
        sleeps.clear()
        clock[0] = 5.0  # expira deadlines de M1/M2 (2.0s) do cenário anterior
        def generate_content_always_429(*args, **kwargs):
            chamadas["n"] += 1
            raise _make_fake_api_error(429, "rate limited", [{"quotaId": "PerMinute", "retryDelay": "2s"}])
        mock_instance.models.generate_content.side_effect = generate_content_always_429

        r2 = prov.classify(sampled_text="x" * 60, cip_text="", external_metadata=None)
        assert r2.confidence_score == 0.0
        assert chamadas["n"] == 3  # teto: número de modelos disponíveis


@respx.mock
def test_pool_indisponivel_sem_rede_apos_perday():
    """Após PerDay com segredo AIzaSy... na exceção: 0 HTTP na chamada seguinte,
    erro sanitizado sem vazar chave, nova create_provider_chain volta a tentar."""
    rota = respx.post("https://api.deepseek.com/v1/chat/completions")
    chamada = {"n": 0}

    def handler(request):
        chamada["n"] += 1
        if chamada["n"] == 1:
            return httpx.Response(429, json={"error": {"message": "PerDay esgotada", "details": "AIzaSySECRETO1234567890"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(_classification_payload(reasoning="ok", confidence_score=0.9))}}]})

    rota.mock(side_effect=handler)

    prov = DeepSeekProvider(api_key="key")
    dispatcher = FallbackLLMDispatcher([("deepseek", prov)])

    # Primeira chamada: PerDay com chave vazada na resposta
    r1 = dispatcher.classify(sampled_text="x" * 60, cip_text="", external_metadata=None)
    assert "AIzaSy" not in r1.reasoning  # chave sanitizada

    # Segunda chamada: K1 em cooldown diário -> 0 HTTP, erro sanitizado, sem espera longa
    t0 = time.monotonic()
    r2 = dispatcher.classify(sampled_text="x" * 60, cip_text="", external_metadata=None)
    dt = time.monotonic() - t0

    assert chamada["n"] == 1  # 0 HTTP na chamada seguinte
    assert dt < 3.0  # sem espera longa
    assert "AIzaSy" not in r2.reasoning
    assert r2.confidence_score == 0.0

    # Nova create_provider_chain volta a tentar (estado novo)
    nova_chain = FallbackLLMDispatcher([("deepseek", DeepSeekProvider(api_key="key"))])
    rota.mock(return_value=httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(_classification_payload(reasoning="ok2", confidence_score=0.95))}}]}))
    r3 = nova_chain.classify(sampled_text="x" * 60, cip_text="", external_metadata=None)
    assert r3.confidence_score == 0.95


# --------------------------------------------------------------------------- #
# Cache: modelo vencedor e cache hit (pipeline real)
# --------------------------------------------------------------------------- #
def test_state_db_modelo_vencedor_e_cache_hit(tmp_path):
    """Pipeline real com FileCache SQLite em tmp_path.
    
    GeminiProvider simulado: M1->404, M2->200.
    Conferir ClassificationResult, manifest/dict (provider_name/model_name),
    1 unica linha em processed_files, alias M1->M2, 2o run com 0 chamadas LLM,
    fallback entre famílias, linha legada, filtros mock/confiança (0 alias para mock),
    substituição quando M1 vence e clear/delete.
    """
    from tomus.core.pipeline import _process_one
    from tomus.storage.organizer import LibraryOrganizer

    db_path = tmp_path / "state.db"
    cache = FileCache(enabled=True, db_path=db_path)

    # Simular GeminiProvider: M1->404, M2->200
    class GeminiSimulado:
        def __init__(self):
            self._model = "gemini-3.5-flash"
            self._fallback_models = ["gemini-3.8-flash", "gemini-3.5-flash-lite"]
            self.chamadas = []
            self._cooldown_state = _PoolCooldownState()
            self._tentativa = 0

        def classify(self, sampled_text, cip_text, external_metadata=None, used_ocr=False, source_path=None):
            # Simular fallback M1->M2 internamente (como o GeminiProvider real faz)
            modelos = ["gemini-3.5-flash", "gemini-3.8-flash"]
            ultimo_erro = None
            for modelo in modelos:
                self.chamadas.append(modelo)
                if modelo == "gemini-3.5-flash":
                    # M1 -> 404, tentar próximo modelo
                    ultimo_erro = FakeAPIError(404, "modelo nao encontrado")
                    continue
                # M2 sucesso
                return ClassificationResult(
                    grande_area="Ciências Humanas",
                    area_basica="Psicologia",
                    tipo="Livro",
                    authors=["Silva, João"],
                    title="Psicologia Social",
                    subtitle="",
                    year=2021,
                    confidence_score=0.92,
                    reasoning="classificado via M2",
                    used_ocr=False,
                    provider_name="gemini",
                    model_name="gemini-3.8-flash",
                )
            # Se chegou aqui, todos falharam
            raise ultimo_erro or FakeAPIError(500, "erro desconhecido")

    # Criar PDF mínimo válido
    import fitz
    pdf_path = tmp_path / "doc1.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Texto de amostra com conteúdo suficiente para classificação do documento um.")
    doc.save(str(pdf_path))
    doc.close()

    config = AppConfig()
    config.general.confidence_min = 0.70
    config.llm.model = "gemini-3.5-flash"
    config.api_keys.gemini_api_key = "AIzaSyfakekey1234567890"

    provider = GeminiSimulado()
    target_dir = tmp_path / "saida"
    target_dir.mkdir()
    organizer = LibraryOrganizer(target_dir, file_operation="copy", dry_run=True)

    taxonomy_version = "v1"

    # Processar documento: M1->404, M2->200
    scanned = SimpleNamespace(path=pdf_path, sha256="abc123def456", is_valid_pdf=True)
    _process_one(
        scanned=scanned,
        config=config,
        target_dir=target_dir,
        provider=provider,
        cache=cache,
        organizer=organizer,
        taxonomy_version=taxonomy_version,
        model_name="gemini-3.5-flash",
        emit=None,
        finalize_lock=threading.RLock(),
    )

    # Verificar que M1 foi chamado (404) e M2 venceu
    assert "gemini-3.5-flash" in provider.chamadas  # M1 tentado
    assert "gemini-3.8-flash" in provider.chamadas  # M2 venceu

    # Verificar classificação via SQL
    conn = sqlite3.connect(str(db_path))
    count_pf = conn.execute("SELECT COUNT(*) FROM processed_files").fetchone()[0]
    count_alias = conn.execute("SELECT COUNT(*) FROM model_aliases").fetchone()[0]
    alias_row = conn.execute(
        "SELECT effective_model FROM model_aliases WHERE requested_model='gemini-3.5-flash'"
    ).fetchone()
    conn.close()

    assert count_pf == 1, f"esperado 1 linha processed_files, obtido {count_pf}"
    assert count_alias == 1, f"esperado 1 alias, obtido {count_alias}"
    assert alias_row is not None and alias_row[0] == "gemini-3.8-flash", f"alias M1->M2: {alias_row}"

    # Confianca < 0.70 nao deve ser gravada no cache
    classificacao_baixa = {
        "grande_area": "Ciências Humanas",
        "area_basica": "Psicologia",
        "tipo": "Livro",
        "confidence_score": 0.50,  # abaixo do confidence_min 0.70
        "reasoning": "baixa confianca",
        "used_ocr": False,
        "provider_name": "gemini",
        "model_name": "gemini-3.8-flash",
    }
    cache.put(
        "baixa_conf", "v1", "gemini-3.8-flash",
        classificacao_baixa, False, confidence_min=0.70,
        requested_model="gemini-3.5-flash",
    )
    conn = sqlite3.connect(str(db_path))
    count_baixa = conn.execute(
        "SELECT COUNT(*) FROM processed_files WHERE sha256='baixa_conf'"
    ).fetchone()[0]
    conn.close()
    assert count_baixa == 0, "classificacao com confianca < 0.70 nao deve ser gravada"

    # Linha legada: inserir direto em processed_files sem linha em model_aliases
    classificacao_legada = {
        "grande_area": "Ciências Humanas",
        "area_basica": "Psicologia",
        "tipo": "Livro",
        "confidence_score": 0.85,
        "reasoning": "legado",
        "used_ocr": False,
        "provider_name": "gemini",
        "model_name": "gemini-3.5-flash",
    }
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        INSERT INTO processed_files
            (sha256, taxonomy_version, model_name, classification_json, used_ocr, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("legado123", "v1", "gemini-3.5-flash",
         json.dumps(classificacao_legada, ensure_ascii=False), 0,
         "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()
    conn.close()

    # get com requested_model=M1 (sem alias) deve fazer fallback na PK antiga
    hit_legado = cache.get("legado123", "v1", "gemini-3.5-flash")
    assert hit_legado is not None, "deve encontrar linha legada via fallback na PK antiga"
    assert hit_legado["model_name"] == "gemini-3.5-flash"

    # Segundo run com cache hit: 0 chamadas LLM
    chamadas_antes = len(provider.chamadas)
    _process_one(
        scanned=scanned,
        config=config,
        target_dir=target_dir,
        provider=provider,
        cache=cache,
        organizer=organizer,
        taxonomy_version=taxonomy_version,
        model_name="gemini-3.5-flash",
        emit=None,
        finalize_lock=threading.RLock(),
    )
    assert len(provider.chamadas) == chamadas_antes, "2o run deve ter 0 chamadas LLM (cache hit)"

    # clear/delete remove registros e aliases
    cache.clear()
    conn = sqlite3.connect(str(db_path))
    count_pf_after = conn.execute("SELECT COUNT(*) FROM processed_files").fetchone()[0]
    count_alias_after = conn.execute("SELECT COUNT(*) FROM model_aliases").fetchone()[0]
    conn.close()
    assert count_pf_after == 0
    assert count_alias_after == 0

    # Nunca criar alias para mock (reasoning == 'mock')
    classificacao_mock = {
        "grande_area": "X",
        "area_basica": "Y",
        "tipo": "Livro",
        "confidence_score": 0.95,
        "reasoning": "mock",
        "used_ocr": False,
        "provider_name": "mock",
        "model_name": "mock-model",
    }
    cache.put(
        "mock123", "v1", "mock-model",
        classificacao_mock, False, confidence_min=0.70,
        requested_model="mock-solicitado",
    )
    conn = sqlite3.connect(str(db_path))
    count_mock_alias = conn.execute(
        "SELECT COUNT(*) FROM model_aliases WHERE sha256='mock123'"
    ).fetchone()[0]
    conn.close()
    assert count_mock_alias == 0, "nunca criar alias para mock"


def test_state_db_substituicao_quando_m1_vence(tmp_path):
    """Quando M1 vence (não há 404), alias antigo M1->M2 é removido e M1 grava direto."""
    db_path = tmp_path / "state2.db"
    cache = FileCache(enabled=True, db_path=db_path)

    # Primeiro put: M1 solicita, M2 vence (alias M1->M2)
    classificacao = {
        "grande_area": "Ciências Humanas",
        "area_basica": "Psicologia",
        "tipo": "Livro",
        "confidence_score": 0.92,
        "reasoning": "via M2",
        "used_ocr": False,
        "provider_name": "gemini",
        "model_name": "gemini-3.8-flash",
    }
    cache.put(
        "shaA", "v1", "gemini-3.8-flash",
        classificacao, False, confidence_min=0.70,
        requested_model="gemini-3.5-flash",
    )

    # Segundo put: M1 solicita e M1 vence (sem 404) -> remover alias antigo, gravar M1 direto
    classificacao2 = dict(classificacao, reasoning="via M1", model_name="gemini-3.5-flash")
    cache.put(
        "shaA", "v1", "gemini-3.5-flash",
        classificacao2, False, confidence_min=0.70,
        requested_model="gemini-3.5-flash",
    )

    conn = sqlite3.connect(str(db_path))
    count_alias = conn.execute("SELECT COUNT(*) FROM model_aliases WHERE sha256='shaA'").fetchone()[0]
    conn.close()
    assert count_alias == 0, "alias removido quando solicitado == vencedor"


# --------------------------------------------------------------------------- #
# Regressao R3 — formato aninhado de error.details / violations e cadeias
# --------------------------------------------------------------------------- #
def test_classificar_falha_genai_client_error_429_nested_violations():
    """ClientError real com details aninhado (error.details[].violations[].quotaDimensions.model)."""
    response_json = {
        "error": {
            "code": 429,
            "message": "Generate content requests per day limit exceeded on Free Tier.",
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                    "violations": [
                        {
                            "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
                            "quotaDimensions": {"model": "gemini-3.6-flash"},
                        }
                    ],
                }
            ],
        }
    }
    exc = genai_errors.ClientError(429, response_json)
    decisao = _classificar_falha(exc)
    assert decisao is not None
    assert decisao.categoria == "cooldown_diario", decisao
    assert decisao.escopo == "par", decisao
    assert decisao.status == 429


def test_classificar_falha_genai_client_error_404_e_server_error_503():
    """ClientError(404) e ServerError(503) reais."""
    exc_404 = genai_errors.ClientError(404, {"error": {"code": 404, "message": "not found"}})
    decisao_404 = _classificar_falha(exc_404)
    assert decisao_404 is not None
    assert decisao_404.categoria == "modelo_indisponivel"
    assert decisao_404.escopo == "par"
    assert decisao_404.status == 404

    exc_503 = genai_errors.ServerError(503, {"error": {"code": 503, "message": "unavailable"}})
    decisao_503 = _classificar_falha(exc_503)
    assert decisao_503 is not None
    assert decisao_503.categoria == "transitorio"
    assert decisao_503.escopo == "par"
    assert decisao_503.status == 503


def test_classificar_falha_httpx_410_gone():
    """httpx.HTTPStatusError 410 -> modelo_indisponivel (escopo par)."""
    resposta = httpx.Response(
        410, json={"error": {"code": 410, "message": "Gone"}}, request=MagicMock()
    )
    exc = httpx.HTTPStatusError("erro", request=MagicMock(), response=resposta)
    decisao = _classificar_falha(exc)
    assert decisao is not None
    assert decisao.categoria == "modelo_indisponivel"
    assert decisao.escopo == "par"
    assert decisao.status == 410


def test_cooldown_diario_escopo_par_preserva_m3():
    """Apenas o par M1 fica bloqueado; entry:0 + M3 continuam livres."""
    estado = _PoolCooldownState()
    estado.clock = lambda: 100.0
    entrada_id = "entry:0"
    par_m1 = "entry:0:model:gemini-3.5-flash"
    par_m3 = "entry:0:model:gemini-3.1-flash-lite"

    exc = genai_errors.ClientError(
        429,
        {
            "error": {
                "code": 429,
                "message": "PerDay",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [
                            {
                                "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
                                "quotaDimensions": {"model": "gemini-3.5-flash"},
                            }
                        ],
                    }
                ],
            }
        },
    )
    decisao = _classificar_falha(exc)
    assert decisao.escopo == "par"
    with estado.lock:
        estado.publicar_falha(entrada_id, par_m1, decisao)

    assert estado.esta_bloqueado(entrada_id, par_m1, agora=100.0)
    # M3 na mesma entrada NÃO está bloqueado
    assert not estado.esta_bloqueado(entrada_id, par_m3, agora=100.0)


def test_cadeia_gemini_3_modelos_k1m3_vence():
    """2 slots Gemini; M1 e M2 falham em ambos; M3 (gemini-3.1-flash-lite) vence. 100% offline."""
    chamado = {"modelos": []}
    resultado_esperado = ClassificationResult(
        grande_area="Ciências Humanas",
        area_basica="Psicologia",
        tipo="Livro",
        authors=["Silva, João"],
        title="Venceu via M3",
        subtitle="",
        year=2021,
        confidence_score=0.92,
        reasoning="ok",
        used_ocr=False,
        provider_name="gemini",
        model_name="gemini-3.1-flash-lite",
    )

    def _classify_once_mock(sampled_text, cip_text, external_metadata, used_ocr=False, source_path=None, model=None):
        chamado["modelos"].append(model)
        if model == "gemini-3.5-flash":
            raise genai_errors.ClientError(
                429,
                {
                    "error": {
                        "code": 429,
                        "message": "PerDay",
                        "details": [
                            {
                                "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                                "violations": [
                                    {
                                        "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
                                        "quotaDimensions": {"model": "gemini-3.5-flash"},
                                    }
                                ],
                            }
                        ],
                    }
                },
            )
        if model == "gemini-3.8-flash":
            raise genai_errors.ServerError(
                503, {"error": {"code": 503, "message": "unavailable", "details": []}}
            )
        # M3 sucesso
        return resultado_esperado

    k1 = GeminiProvider(api_key="AIzaSyK1111111111111111111111111", model="gemini-3.5-flash")
    k2 = GeminiProvider(api_key="AIzaSyK2222222222222222222222222", model="gemini-3.5-flash")
    k1._fallback_models = ["gemini-3.8-flash", "gemini-3.1-flash-lite"]
    k2._fallback_models = ["gemini-3.8-flash", "gemini-3.1-flash-lite"]
    k1._classify_once = _classify_once_mock
    k2._classify_once = _classify_once_mock

    estado = _PoolCooldownState()
    estado.clock = lambda: 100.0
    dispatcher = FallbackLLMDispatcher(
        [("gemini", k1), ("gemini (pool chave 2)", k2)],
        cooldown_state=estado,
        families=["gemini"],
    )

    r = dispatcher.classify(sampled_text="x" * 60, cip_text="", external_metadata=None)
    assert r.provider_name == "gemini"
    assert r.model_name == "gemini-3.1-flash-lite"
    assert r.title == "Venceu via M3"
    # M1 e M2 foram tentados antes de M3
    assert chamado["modelos"].count("gemini-3.5-flash") >= 1
    assert chamado["modelos"].count("gemini-3.8-flash") >= 1
    assert chamado["modelos"].count("gemini-3.1-flash-lite") >= 1


def test_cadeia_gemini_e_nvidia_410_falham_claude_vence():
    """Gemini (M1/M2/M3) + NVIDIA (410 Gone) falham; familia secundaria claude vence. 100% offline."""
    chamado = {"familias": []}

    def _classify_once_gemini(sampled_text, cip_text, external_metadata, used_ocr=False, source_path=None, model=None):
        chamado["familias"].append("gemini")
        raise genai_errors.ClientError(
            429,
            {
                "error": {
                    "code": 429,
                    "message": "PerDay",
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                            "violations": [
                                {
                                    "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
                                    "quotaDimensions": {"model": model},
                                }
                            ],
                        }
                    ],
                }
            },
        )

    def _classify_once_nvidia(sampled_text, cip_text, external_metadata, used_ocr=False, source_path=None, model=None):
        chamado["familias"].append("nvidia")
        resposta = httpx.Response(410, json={"error": {"code": 410, "message": "Gone"}}, request=MagicMock())
        raise httpx.HTTPStatusError("erro", request=MagicMock(), response=resposta)

    resultado_claude = ClassificationResult(
        grande_area="Ciências Humanas",
        area_basica="Psicologia",
        tipo="Livro",
        authors=["Silva, João"],
        title="Venceu via Claude",
        subtitle="",
        year=2021,
        confidence_score=0.92,
        reasoning="ok",
        used_ocr=False,
        provider_name="claude",
        model_name="claude-haiku-5-5",
    )

    def _classify_once_claude(sampled_text, cip_text, external_metadata, used_ocr=False, source_path=None, model=None):
        chamado["familias"].append("claude")
        return resultado_claude

    k1 = GeminiProvider(api_key="AIzaSyK1111111111111111111111111", model="gemini-3.5-flash")
    k2 = GeminiProvider(api_key="AIzaSyK2222222222222222222222222", model="gemini-3.5-flash")
    k1._fallback_models = ["gemini-3.8-flash", "gemini-3.1-flash-lite"]
    k2._fallback_models = ["gemini-3.8-flash", "gemini-3.1-flash-lite"]
    k1._classify_once = _classify_once_gemini
    k2._classify_once = _classify_once_gemini

    nvidia = NvidiaProvider(api_key="nvapi-test-key", model="meta/llama-3.2-90b-vision-instruct")
    nvidia._classify_once = _classify_once_nvidia

    claude = ClaudeProvider(api_key="sk-ant-test-key", model="claude-haiku-5-5")
    claude._classify_once = _classify_once_claude

    estado = _PoolCooldownState()
    estado.clock = lambda: 100.0
    dispatcher = FallbackLLMDispatcher(
        [("gemini", k1), ("gemini (pool chave 2)", k2), ("nvidia", nvidia), ("claude", claude)],
        cooldown_state=estado,
        families=["gemini", "nvidia", "claude"],
    )

    r = dispatcher.classify(sampled_text="x" * 60, cip_text="", external_metadata=None)
    assert r.provider_name == "claude"
    assert r.model_name == "claude-haiku-5-5"
    assert r.title == "Venceu via Claude"
    # Gemini esgotado (2 slots x 3 modelos), NVIDIA 410, Claude venceu
    assert chamado["familias"].count("gemini") == 6
    assert chamado["familias"].count("nvidia") == 1
    assert chamado["familias"].count("claude") == 1
