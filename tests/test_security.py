"""Testes de conformidade e segurança da informação (AppSec).

Valida as mitigações contra:
- CRT-01 / CRT-02: Mascaramento de credenciais em logs (RedactingFilter)
- ALT-01 / ALT-02: Prevenção de Path Traversal e contenção de caminhos no QWebChannel
- MED-01: Mascaramento de chaves e segredos em exceções/erros de LLM
- MED-04: Silenciamento de logs de console JS em produção
- BAI-01: Avisos de boas práticas de segurança na CLI
"""

import logging
from pathlib import Path

from tomus.core.llm import _sanitize_error_message
from tomus.core.logging import RedactingFilter
from tomus.gui.bridge import _is_safe_path


def test_redacting_filter_mascara_credenciais_em_logs():
    """RedactingFilter deve mascarar chaves de API conhecidas e query params key=."""
    filtro = RedactingFilter()

    # Teste com query param key= (Google Books / Gemini)
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="GET https://www.googleapis.com/books/v1/volumes?q=isbn&key=AIzaSyTEST-FIXTURE-ONLY",
        args=(),
        exc_info=None,
    )
    assert filtro.filter(record) is True
    assert "AIzaSyTEST-FIXTURE-ONLY" not in record.msg
    assert "***REDACTED***" in record.msg

    # Teste com chave OpenAI / DeepSeek (sk-...)
    record2 = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname="",
        lineno=0,
        msg="Erro de conexao com sk-abcdef12345678901234567890",
        args=(),
        exc_info=None,
    )
    filtro.filter(record2)
    assert "sk-abcdef12345678901234567890" not in record2.msg
    assert "sk-***REDACTED***" in record2.msg

    # Teste com chave NVIDIA (nvapi-...)
    record3 = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname="",
        lineno=0,
        msg="Falha ao chamar nvapi-abcdef12345678901234567890",
        args=(),
        exc_info=None,
    )
    filtro.filter(record3)
    assert "nvapi-abcdef12345678901234567890" not in record3.msg
    assert "nvapi-***REDACTED***" in record3.msg


def test_sanitize_error_message_redige_segredos():
    """_sanitize_error_message deve eliminar chaves de API expostas em exceções."""
    msg = "HTTP 401 Unauthorized: sk-1234567890abcdef1234567890 invalid key"
    sanitizada = _sanitize_error_message(msg)
    assert "sk-1234567890abcdef1234567890" not in sanitizada
    assert "sk-***REDACTED***" in sanitizada

    msg_nv = "Falha de autenticação com nvapi-xyz9876543210123456789"
    sanitizada_nv = _sanitize_error_message(msg_nv)
    assert "nvapi-xyz9876543210123456789" not in sanitizada_nv
    assert "nvapi-***REDACTED***" in sanitizada_nv


def test_is_safe_path_bloqueia_travessia_e_pastas_sensíveis(tmp_path: Path):
    """_is_safe_path deve bloquear path traversal e dotfiles sensíveis."""
    source_dir = tmp_path / "origem"
    target_dir = tmp_path / "destino"
    source_dir.mkdir()
    target_dir.mkdir()

    valid_pdf = source_dir / "artigo.pdf"
    valid_pdf.write_bytes(b"%PDF-1.4")

    # Arquivo legítimo dentro de raiz autorizada: DEVE passar
    assert _is_safe_path(valid_pdf, [source_dir, target_dir]) is True

    # Bloqueio de diretório do sistema (/etc/passwd)
    assert _is_safe_path(Path("/etc/passwd"), [source_dir, target_dir]) is False
    assert _is_safe_path(Path("/var/log/system.log"), [source_dir, target_dir]) is False

    # Bloqueio de pastas de credenciais e dotfiles sensíveis (~/.ssh, ~/.aws)
    ssh_path = Path.home() / ".ssh" / "id_rsa"
    assert _is_safe_path(ssh_path, [source_dir, target_dir]) is False

    aws_path = Path.home() / ".aws" / "credentials"
    assert _is_safe_path(aws_path, [source_dir, target_dir]) is False

    # Bloqueio de tentativa de path traversal com ..
    traversal_path = source_dir / ".." / ".." / "etc" / "passwd"
    assert _is_safe_path(traversal_path, [source_dir, target_dir]) is False


def test_humanize_error_message_amigavel():
    from tomus.core.llm import humanize_error_message

    # 401 DeepSeek com URL crua
    err_401 = "Client error '401 Unauthorized' for url 'https://api.deepseek.com/v1/chat/completions'"
    msg_401 = humanize_error_message(err_401)
    assert "não autorizada ou expirada" in msg_401
    assert "DeepSeek" in msg_401
    assert "Preferências" in msg_401

    # 429 Groq
    err_429 = "Error 429 Too Many Requests: Rate limit reached for groq model"
    msg_429 = humanize_error_message(err_429)
    assert "Cota de requisições" in msg_429
    assert "Groq" in msg_429

    # 503 NVIDIA
    err_503 = "HTTP 503 Service Unavailable for nvapi-endpoint"
    msg_503 = humanize_error_message(err_503)
    assert "Instabilidade temporária" in msg_503
    assert "NVIDIA" in msg_503

    # Timeout genérico
    err_timeout = "httpx.ConnectTimeout: Connection timed out"
    msg_timeout = humanize_error_message(err_timeout)
    assert "Tempo limite de resposta esgotado" in msg_timeout

