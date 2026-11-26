"""Testes unitários para scripts/validate_onedrive_protocol.py.

Foco no comportamento do parâmetro --desde NNNN:
- desvio de sequência/frontmatter com numero < desde → AVISO [historico], exit 0
- desvio de sequência/frontmatter com numero >= desde → ERRO, exit 1
- segredo em mensagem com numero < desde → SEMPRE ERRO, exit 1
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "validate_onedrive_protocol.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("validate_onedrive_protocol", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _escreve_frontmatter_valido(caminho: Path) -> None:
    caminho.write_text(
        "---\n"
        "slug: teste\n"
        "data: 2026-11-01\n"
        "---\n"
        "\n"
        "corpo da mensagem\n",
        encoding="utf-8",
    )


def _escreve_sem_frontmatter(caminho: Path) -> None:
    caminho.write_text("sem frontmatter aqui\n", encoding="utf-8")


def _escreve_com_segredo(caminho: Path) -> None:
    caminho.write_text(
        "---\n"
        "slug: dez\n"
        "---\n"
        "\n"
        "contém sk-abcdef1234567890 chave secreta\n",
        encoding="utf-8",
    )


def _estado_consistente(canal: Path, ultimo_mac: str, ultimo_win: str) -> None:
    (canal / "estado_mac.json").write_text(
        json.dumps(
            {
                "baseline_main": "a" * 40,
                "ultimo_enviado_mac": ultimo_mac,
                "ultimo_lido_win": ultimo_win,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (canal / "estado_win.json").write_text(
        json.dumps(
            {
                "ultimo_enviado_win": ultimo_win,
                "ultimo_lido_mac": ultimo_mac,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _cenario(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Cria estrutura de diretórios e retorna (mac_dir, win_dir, canal_dir)."""
    mac_dir = tmp_path / "mac_para_win"
    win_dir = tmp_path / "win_para_mac"
    canal_dir = tmp_path / "chefes_mac_win"
    mac_dir.mkdir(parents=True)
    win_dir.mkdir(parents=True)
    canal_dir.mkdir(parents=True)
    return mac_dir, win_dir, canal_dir


def _replica_em_ambos(mac_dir: Path, win_dir: Path, nome: str, conteudo_fn) -> Path:
    """Escreve a mesma mensagem em mac_para_win e win_para_win, retorna o caminho em mac."""
    conteudo_fn(mac_dir / nome)
    conteudo_fn(win_dir / nome)
    return mac_dir / nome


def _rodar(mod, monkeypatch, mac_dir: Path, win_dir: Path, canal_dir: Path, argv: list[str]) -> int:
    monkeypatch.setattr(mod, "MAC_DIR", mac_dir)
    monkeypatch.setattr(mod, "WIN_DIR", win_dir)
    monkeypatch.setattr(mod, "CANAL_DIR", canal_dir)
    import sys

    argv_backup = sys.argv
    sys.argv = ["validate_onedrive_protocol.py"] + argv
    try:
        codigo = mod.main()
    finally:
        sys.argv = argv_backup
    return codigo


def test_desvio_historico_abaixo_desde_sai_zero(monkeypatch, tmp_path):
    """Desvio de sequência com numero < desde → AVISO, exit 0."""
    mod = _load_module()
    mac_dir, win_dir, canal_dir = _cenario(tmp_path)

    # 0001 ok, 0003 ok -> desvio (esperado 2, achou 3), numero 3 < 80 -> AVISO
    _replica_em_ambos(mac_dir, win_dir, "0001_2026-11-01_primeira.md", _escreve_frontmatter_valido)
    _replica_em_ambos(mac_dir, win_dir, "0003_2026-11-03_terceira.md", _escreve_frontmatter_valido)
    _estado_consistente(canal_dir, "0003_2026-11-03_terceira.md", "0003_2026-11-03_terceira.md")

    codigo = _rodar(mod, monkeypatch, mac_dir, win_dir, canal_dir, ["--desde", "0080"])
    assert codigo == 0


def test_desvio_acima_desde_falha(monkeypatch, tmp_path):
    """Desvio de sequência com numero >= desde → ERRO, exit 1."""
    mod = _load_module()
    mac_dir, win_dir, canal_dir = _cenario(tmp_path)

    # 0001 ok, 0085 com desvio (esperado 2, achou 85), numero 85 >= 80 -> ERRO
    _replica_em_ambos(mac_dir, win_dir, "0001_2026-11-01_primeira.md", _escreve_frontmatter_valido)
    _replica_em_ambos(mac_dir, win_dir, "0085_2026-11-05_oitentaecinco.md", _escreve_frontmatter_valido)
    _estado_consistente(canal_dir, "0085_2026-11-05_oitentaecinco.md", "0085_2026-11-05_oitentaecinco.md")

    codigo = _rodar(mod, monkeypatch, mac_dir, win_dir, canal_dir, ["--desde", "0080"])
    assert codigo == 1


def test_frontmatter_abaixo_desde_aviso(monkeypatch, tmp_path):
    """Frontmatter ausente com numero < desde → AVISO, exit 0."""
    mod = _load_module()
    mac_dir, win_dir, canal_dir = _cenario(tmp_path)

    _replica_em_ambos(mac_dir, win_dir, "0001_2026-11-01_primeira.md", _escreve_frontmatter_valido)
    _replica_em_ambos(mac_dir, win_dir, "0005_2026-11-05_cinco.md", _escreve_sem_frontmatter)  # 5 < 80 -> AVISO
    _estado_consistente(canal_dir, "0005_2026-11-05_cinco.md", "0005_2026-11-05_cinco.md")

    codigo = _rodar(mod, monkeypatch, mac_dir, win_dir, canal_dir, ["--desde", "0080"])
    assert codigo == 0


def test_segredo_abaixo_desde_sempre_falha(monkeypatch, tmp_path):
    """Segredo em mensagem com numero < desde → SEMPRE ERRO, exit 1."""
    mod = _load_module()
    mac_dir, win_dir, canal_dir = _cenario(tmp_path)

    _replica_em_ambos(mac_dir, win_dir, "0001_2026-11-01_primeira.md", _escreve_frontmatter_valido)
    _replica_em_ambos(mac_dir, win_dir, "0010_2026-11-10_dez.md", _escreve_com_segredo)  # 10 < 80, mas SEGREDO -> ERRO
    _estado_consistente(canal_dir, "0010_2026-11-10_dez.md", "0010_2026-11-10_dez.md")

    codigo = _rodar(mod, monkeypatch, mac_dir, win_dir, canal_dir, ["--desde", "0080"])
    assert codigo == 1


def test_sem_desde_comportamento_original(monkeypatch, tmp_path):
    """Sem --desde, desvio de sequência é ERRO (exit 1)."""
    mod = _load_module()
    mac_dir, win_dir, canal_dir = _cenario(tmp_path)

    _replica_em_ambos(mac_dir, win_dir, "0001_2026-11-01_primeira.md", _escreve_frontmatter_valido)
    _replica_em_ambos(mac_dir, win_dir, "0003_2026-11-03_terceira.md", _escreve_frontmatter_valido)  # desvio, sem --desde -> ERRO
    _estado_consistente(canal_dir, "0003_2026-11-03_terceira.md", "0003_2026-11-03_terceira.md")

    codigo = _rodar(mod, monkeypatch, mac_dir, win_dir, canal_dir, [])
    assert codigo == 1


def test_estado_inconsistente_sempre_falha_independente_desde(monkeypatch, tmp_path):
    """estado_*.json inconsistente → ERRO mesmo com --desde."""
    mod = _load_module()
    mac_dir, win_dir, canal_dir = _cenario(tmp_path)

    _replica_em_ambos(mac_dir, win_dir, "0001_2026-11-01_primeira.md", _escreve_frontmatter_valido)
    # ultimo_enviado_mac aponta para mensagem inexistente
    (canal_dir / "estado_mac.json").write_text(
        json.dumps(
            {
                "baseline_main": "a" * 40,
                "ultimo_enviado_mac": "9999_2026-11-99_inexistente.md",
                "ultimo_lido_win": "0001_2026-11-01_primeira.md",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (canal_dir / "estado_win.json").write_text(
        json.dumps(
            {
                "ultimo_enviado_win": "0001_2026-11-01_primeira.md",
                "ultimo_lido_mac": "0001_2026-11-01_primeira.md",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    codigo = _rodar(mod, monkeypatch, mac_dir, win_dir, canal_dir, ["--desde", "0080"])
    assert codigo == 1


def test_aceita_hifen_apos_data(monkeypatch, tmp_path):
    """Arquivo NNNN_YYYY-MM-DD-slug.md (hífen após a data) é aceito e exit 0.

    A equipe Windows envia nomes em OneDrive append-only (não renomeáveis),
    ex.: 0083_2026-11-25-smoke-v141-pdf-bloqueado-aprovacao.md. O ARQUIVO_RE
    deve reconhecer tanto '_' quanto '-' entre a data e o slug, e o cursor
    de estado_*.json que referencia esse nome deve ser considerado consistente.
    """
    mod = _load_module()
    mac_dir, win_dir, canal_dir = _cenario(tmp_path)

    nome_hifen = "0083_2026-11-25-smoke-v141-pdf-bloqueado-aprovacao.md"
    _replica_em_ambos(mac_dir, win_dir, nome_hifen, _escreve_frontmatter_valido)
    # Único arquivo: sequência 1 -> 83 é desvio, mas 83 < 0084 vira AVISO
    # [historico], não erro. Exit 0 desde que o hífen seja reconhecido.
    _estado_consistente(canal_dir, nome_hifen, nome_hifen)

    codigo = _rodar(mod, monkeypatch, mac_dir, win_dir, canal_dir, ["--desde", "0084"])
    assert codigo == 0


def test_dir_sobrescreve_canal_default(monkeypatch, tmp_path):
    """--dir aponta para canal válido mesmo com MAC_DIR/WIN_DIR/CANAL_DIR inválidos (precedência real)."""
    mod = _load_module()

    # Canal válido (com a mensagem).
    canal_valido = tmp_path / "canal_valido"
    mac_valido = canal_valido / "mac_para_win"
    win_valido = canal_valido / "win_para_mac"
    mac_valido.mkdir(parents=True)
    win_valido.mkdir(parents=True)
    _replica_em_ambos(mac_valido, win_valido, "0001_2026-11-01_primeira.md", _escreve_frontmatter_valido)
    _estado_consistente(canal_valido, "0001_2026-11-01_primeira.md", "0001_2026-11-01_primeira.md")

    # Canal inválido (vazio) — monkeypatchado nas globais para provar que --dir prevalece.
    canal_invalido = tmp_path / "canal_invalido"
    mac_invalido = canal_invalido / "mac_para_win"
    win_invalido = canal_invalido / "win_para_mac"
    mac_invalido.mkdir(parents=True)
    win_invalido.mkdir(parents=True)
    monkeypatch.setattr(mod, "MAC_DIR", mac_invalido)
    monkeypatch.setattr(mod, "WIN_DIR", win_invalido)
    monkeypatch.setattr(mod, "CANAL_DIR", canal_invalido)

    import sys

    argv_backup = sys.argv
    sys.argv = ["validate_onedrive_protocol.py", "--dir", str(canal_valido), "--desde", "0080"]
    try:
        codigo = mod.main()
    finally:
        sys.argv = argv_backup
    assert codigo == 0


def test_variavel_ambiente_sobrescreve_canal(monkeypatch, tmp_path):
    """TOMUS_ONEDRIVE_CANAL_DIR aponta para canal válido mesmo com globais inválidas (precedência real)."""
    mod = _load_module()

    # Canal válido (com a mensagem).
    canal_valido = tmp_path / "canal_valido"
    mac_valido = canal_valido / "mac_para_win"
    win_valido = canal_valido / "win_para_mac"
    mac_valido.mkdir(parents=True)
    win_valido.mkdir(parents=True)
    _replica_em_ambos(mac_valido, win_valido, "0001_2026-11-01_primeira.md", _escreve_frontmatter_valido)
    _estado_consistente(canal_valido, "0001_2026-11-01_primeira.md", "0001_2026-11-01_primeira.md")

    # Canal inválido (vazio) — monkeypatchado nas globais para provar que o env prevalece.
    canal_invalido = tmp_path / "canal_invalido"
    mac_invalido = canal_invalido / "mac_para_win"
    win_invalido = canal_invalido / "win_para_mac"
    mac_invalido.mkdir(parents=True)
    win_invalido.mkdir(parents=True)
    monkeypatch.setenv(mod.ENV_CANAL_DIR, str(canal_valido))
    monkeypatch.setattr(mod, "MAC_DIR", mac_invalido)
    monkeypatch.setattr(mod, "WIN_DIR", win_invalido)
    monkeypatch.setattr(mod, "CANAL_DIR", canal_invalido)

    import sys

    argv_backup = sys.argv
    sys.argv = ["validate_onedrive_protocol.py", "--desde", "0080"]
    try:
        codigo = mod.main()
    finally:
        sys.argv = argv_backup
    assert codigo == 0
