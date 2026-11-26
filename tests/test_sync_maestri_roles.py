"""Testes unitários para scripts/sync_maestri_roles.py.

Cobre --check e --apply em tmp_path, incluindo:
- ID de papel ausente
- name divergente no role.json
- termo obsoleto nos arquivos de papel
- frase truncada nos arquivos de papel
- ausência de .maestri/roles retornando 0
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "sync_maestri_roles.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("sync_maestri_roles", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _escreve_role(role_dir: Path, nome: str, conteudo_agents: str, conteudo_claude: str) -> None:
    role_dir.mkdir(parents=True, exist_ok=True)
    (role_dir / "role.json").write_text(
        json.dumps({"name": nome}, ensure_ascii=False, indent=2),
        encoding="utf-8-sig",
    )
    (role_dir / "AGENTS.md").write_text(conteudo_agents, encoding="utf-8-sig")
    (role_dir / "CLAUDE.md").write_text(conteudo_claude, encoding="utf-8-sig")


def _cria_estrutura_roles(tmp_path: Path, mod) -> Path:
    roles_dir = tmp_path / ".maestri" / "roles"
    for role_id, (nome,) in mod.ROLE_DEFINITIONS.items():
        _escreve_role(
            roles_dir / role_id.lower(),
            nome,
            f"# {nome}\nConteúdo válido do {nome}.\n",
            f"# {nome}\nCLAUDE válido do {nome}.\n",
        )
    return roles_dir


def _rodar(mod, monkeypatch, args: list[str]) -> int:
    import sys

    argv_backup = sys.argv
    sys.argv = ["sync_maestri_roles.py"] + args
    try:
        return mod.main(args)
    finally:
        sys.argv = argv_backup


def test_check_tudo_consistente_retorna_zero(monkeypatch, tmp_path):
    mod = _load_module()
    _cria_estrutura_roles(tmp_path, mod)
    codigo = _rodar(mod, monkeypatch, ["--repo", str(tmp_path), "--check"])
    assert codigo == 0


def test_check_roles_dir_ausente_retorna_zero(monkeypatch, tmp_path):
    mod = _load_module()
    # tmp_path sem .maestri/roles
    codigo = _rodar(mod, monkeypatch, ["--repo", str(tmp_path), "--check"])
    assert codigo == 0


def test_check_id_ausente_falha(monkeypatch, tmp_path):
    mod = _load_module()
    roles_dir = tmp_path / ".maestri" / "roles"
    roles_dir.mkdir(parents=True)
    # remove um ID esperado (não cria o diretório)
    codigo = _rodar(mod, monkeypatch, ["--repo", str(tmp_path), "--check"])
    assert codigo == 1


def test_check_name_divergente_falha(monkeypatch, tmp_path):
    mod = _load_module()
    roles_dir = _cria_estrutura_roles(tmp_path, mod)
    # diverge o name de um role específico
    primeiro_id = next(iter(mod.ROLE_DEFINITIONS))
    role_dir = roles_dir / primeiro_id.lower()
    (role_dir / "role.json").write_text(
        json.dumps({"name": "Nome Errado"}, ensure_ascii=False, indent=2),
        encoding="utf-8-sig",
    )
    codigo = _rodar(mod, monkeypatch, ["--repo", str(tmp_path), "--check"])
    assert codigo == 1


def test_check_termo_obsoleto_falha(monkeypatch, tmp_path):
    mod = _load_module()
    roles_dir = _cria_estrutura_roles(tmp_path, mod)
    primeiro_id = next(iter(mod.ROLE_DEFINITIONS))
    role_dir = roles_dir / primeiro_id.lower()
    (role_dir / "AGENTS.md").write_text(
        "# Atlas\nEste texto menciona BiblioTEC e Docling OCR com DocumentStream.\n",
        encoding="utf-8-sig",
    )
    codigo = _rodar(mod, monkeypatch, ["--repo", str(tmp_path), "--check"])
    assert codigo == 1


def test_check_frase_truncada_falha(monkeypatch, tmp_path):
    mod = _load_module()
    roles_dir = _cria_estrutura_roles(tmp_path, mod)
    primeiro_id = next(iter(mod.ROLE_DEFINITIONS))
    role_dir = roles_dir / primeiro_id.lower()
    (role_dir / "CLAUDE.md").write_text(
        "# Claude\nBacklog . e do . estão truncados.\n",
        encoding="utf-8-sig",
    )
    codigo = _rodar(mod, monkeypatch, ["--repo", str(tmp_path), "--check"])
    assert codigo == 1


def test_apply_corrige_termos_e_name(monkeypatch, tmp_path):
    mod = _load_module()
    roles_dir = _cria_estrutura_roles(tmp_path, mod)
    primeiro_id = next(iter(mod.ROLE_DEFINITIONS))
    nome_esperado = mod.ROLE_DEFINITIONS[primeiro_id][0]
    role_dir = roles_dir / primeiro_id.lower()

    # name divergente + termos obsoletos + frases truncadas
    (role_dir / "role.json").write_text(
        json.dumps({"name": "Nome Errado"}, ensure_ascii=False, indent=2),
        encoding="utf-8-sig",
    )
    (role_dir / "AGENTS.md").write_text(
        "# Atlas\nBiblioTEC e dcprj/bibliotec e docs/designs/bibliotec.md.\n"
        "Docling OCR com DocumentStream aqui.\n",
        encoding="utf-8-sig",
    )
    (role_dir / "CLAUDE.md").write_text(
        "# Claude\nBacklog . e do . e no repositório . e para o (.\n",
        encoding="utf-8-sig",
    )

    codigo_aplicar = _rodar(mod, monkeypatch, ["--repo", str(tmp_path), "--apply"])
    assert codigo_aplicar == 0

    # Após apply, check deve passar
    codigo_check = _rodar(mod, monkeypatch, ["--repo", str(tmp_path), "--check"])
    assert codigo_check == 0

    # Verificar name alinhado
    role_json = json.loads((role_dir / "role.json").read_text(encoding="utf-8-sig"))
    assert role_json["name"] == nome_esperado

    # Verificar termos corrigidos
    agents = (role_dir / "AGENTS.md").read_text(encoding="utf-8-sig")
    assert "BiblioTEC" not in agents
    assert "dcprj/bibliotec" not in agents
    assert "docs/designs/bibliotec.md" not in agents
    assert "Docling OCR" not in agents
    assert "DocumentStream" not in agents
    assert "Tomus" in agents

    claude = (role_dir / "CLAUDE.md").read_text(encoding="utf-8-sig")
    assert "Backlog ." not in claude
    assert "do ." not in claude
    assert "no repositório ." not in claude
    assert "para o (" not in claude
    assert "Backlog Tomus." in claude
    assert "do Tomus." in claude


def test_check_e_apply_role_json_com_barras_escapadas(monkeypatch, tmp_path):
    """role.json com barras escapadas (\\/) nos campos decodificados deve ser
    detectado por check() e corrigido por apply()."""
    mod = _load_module()
    roles_dir = _cria_estrutura_roles(tmp_path, mod)
    primeiro_id = next(iter(mod.ROLE_DEFINITIONS))
    nome_esperado = mod.ROLE_DEFINITIONS[primeiro_id][0]
    role_dir = roles_dir / primeiro_id.lower()

    # role.json com barras escapadas mascarando termos obsoletos nos campos
    # decodificados (prompt e name).
    role_json_bruto = {
        "name": nome_esperado,
        "prompt": (
            "Veja docs\\/designs\\/bibliotec.md e dcprj\\/bibliotec. "
            "Docling OCR com DocumentStream aqui. BiblioTEC esta no texto."
        ),
    }
    (role_dir / "role.json").write_text(
        json.dumps(role_json_bruto, ensure_ascii=False, indent=2),
        encoding="utf-8-sig",
    )

    # check deve falhar (termos proibidos nos campos decodificados).
    codigo_check = _rodar(mod, monkeypatch, ["--repo", str(tmp_path), "--check"])
    assert codigo_check == 1

    # apply deve corrigir.
    codigo_aplicar = _rodar(mod, monkeypatch, ["--repo", str(tmp_path), "--apply"])
    assert codigo_aplicar == 0

    # Após apply, check deve passar.
    codigo_check2 = _rodar(mod, monkeypatch, ["--repo", str(tmp_path), "--check"])
    assert codigo_check2 == 0

    # Verificar que o prompt foi corrigido (sem termos obsoletos, com barras
    # normais agora, pois json.dumps não escapa /).
    role_json_final = json.loads((role_dir / "role.json").read_text(encoding="utf-8-sig"))
    prompt_final = role_json_final["prompt"]
    assert "docs/designs/bibliotec.md" not in prompt_final
    assert "dcprj/bibliotec" not in prompt_final
    assert "Docling OCR" not in prompt_final
    assert "DocumentStream" not in prompt_final
    assert "BiblioTEC" not in prompt_final
    assert "docs/historico/tomus.md" in prompt_final
    assert "dcprj/tomus" in prompt_final
    assert "RapidOCR/ONNXRuntime" in prompt_final
    assert "Tomus" in prompt_final
    assert role_json_final["name"] == nome_esperado
