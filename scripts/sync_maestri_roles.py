"""Sincronização somente leitura/correção de papéis Maestri (.maestri/roles).

Verifica e, opcionalmente, corrige os arquivos de definição de papel
(role.json / AGENTS.md / CLAUDE.md) dentro de .maestri/roles/, alinhando-os
com ROLE_DEFINITIONS e removendo termos obsoletos/frases truncadas.

Não grava nada a menos que --apply seja passado. Com --check apenas reporta.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Repositório e diretório de papéis
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
ROLES_DIR_DEFAULT = REPO_ROOT / ".maestri" / "roles"

# ---------------------------------------------------------------------------
# Definição canônica de papéis: {role_id_uuid_lower: (nome_exato,)}
# Os 9 UUIDs reais e nomes canônicos extraídos de .maestri/roles/<uuid>/role.json
# do repositório principal (dcprj/tomus).
# ---------------------------------------------------------------------------
ROLE_DEFINITIONS: dict[str, tuple[str]] = {
    "22b7268e-6cf4-4f34-bb86-e849b89194ca": ("Lead Orchestrator & Principal Systems Architect",),
    "35890b7d-4a6f-4f1a-8353-fe8725ff7115": ("Release & GitOps Manager",),
    "3c1e4550-14dd-4cb8-9ff6-6eb9781d32fd": ("Taxonomy & Deduplication Architect",),
    "7293a094-3208-472f-b9dd-7d3b1b11ac43": ("Information Security & AppSec Specialist",),
    "88078ee3-6ec8-4106-af30-0f46fed427f4": ("UX/UI & Desktop GUI Architect",),
    "d3140326-80b8-41c2-ad20-1ff18fddf0f0": ("Foundation Engineer",),
    "d9e11213-2adc-4e23-a013-90ba23b11301": ("Assistente de Pauta do Chefe",),
    "da0dcc7f-cc13-4b49-92b3-03963c7dfb3f": ("Extractors Engineer",),
    "ef95033c-74b7-4671-9627-8914219c1d11": ("Pipeline & CLI Engineer",),
}

# ---------------------------------------------------------------------------
# Termos proibidos / obsoletos que não devem aparecer nos arquivos de papel.
# ---------------------------------------------------------------------------
TERMOS_PROIBIDOS = [
    "BiblioTEC",
    "dcprj/bibliotec",
    "docs/designs/bibliotec.md",
    "Docling OCR",
    "DocumentStream",
    "do .",
    "repositório .",
    "para o (",
    "Backlog .",
]

# Regex precisas para evitar falso positivo em "do ." e "repositório ."
RE_DO_PONTO = re.compile(r"\bdo \.")
RE_REPOSITORIO_PONTO = re.compile(r"\brepositório \.")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sincroniza papéis Maestri (.maestri/roles) com ROLE_DEFINITIONS."
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=REPO_ROOT,
        help="Raiz do repositório (default: derivada do caminho deste script).",
    )
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument(
        "--check",
        action="store_true",
        help="Apenas verifica e reporta divergências (não altera nada).",
    )
    grupo.add_argument(
        "--apply",
        action="store_true",
        help="Aplica correções nos arquivos de papel.",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Substituições corretas e idempotentes
# ---------------------------------------------------------------------------
def _corrigir_texto(texto: str) -> str:
    """Aplica substituições corretas e idempotentes ao texto.

    A ordem é intencional para evitar falsos positivos (ex.: "Tomus Tomus")
    e para que a aplicação repetida não altere mais o texto após a primeira.
    O caminho físico do filesystem (/Users/dario/.../bibliotec) é preservado.
    """
    substituicoes = [
        # OCR: a frase completa primeiro, depois o fallback isolado.
        ("Docling OCR com DocumentStream", "OCR seletivo local com PyMuPDF + RapidOCR/ONNXRuntime"),
        ("Docling OCR", "RapidOCR/ONNXRuntime"),
        # Evitar "Tomus Tomus": trata BiblioTEC adjacente a Tomus primeiro.
        ("BiblioTEC Tomus", "Tomus"),
        ("Tomus BiblioTEC", "Tomus"),
        ("BiblioTEC", "Tomus"),
        ("dcprj/bibliotec", "dcprj/tomus"),
        ("docs/designs/bibliotec.md", "docs/historico/tomus.md"),
        # Reparos de frases truncadas.
        ("do .", "do Tomus."),
        ("no repositório .", "no repositório dcprj/tomus."),
        ("para o (", "para o Tomus ("),
        ("Backlog .", "Backlog Tomus."),
    ]
    for velho, novo in substituicoes:
        texto = texto.replace(velho, novo)
    return texto


def _termos_proibidos_no_texto(texto: str) -> list[str]:
    """Retorna os termos proibidos encontrados no texto (busca precisa)."""
    encontrados: list[str] = []
    for termo in TERMOS_PROIBIDOS:
        if termo in ("do .", "repositório ."):
            continue  # tratados por regex abaixo
        if termo in texto:
            encontrados.append(termo)
    if RE_DO_PONTO.search(texto):
        encontrados.append("do .")
    if RE_REPOSITORIO_PONTO.search(texto):
        encontrados.append("repositório .")
    # deduplicar preservando ordem
    vistos = set()
    unicos: list[str] = []
    for t in encontrados:
        if t not in vistos:
            vistos.add(t)
            unicos.append(t)
    return unicos


def _ler_json(caminho: Path) -> dict | None:
    try:
        return json.loads(caminho.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None


def _arquivos_papel(role_dir: Path) -> dict[str, Path | None]:
    return {
        "role.json": role_dir / "role.json",
        "AGENTS.md": role_dir / "AGENTS.md",
        "CLAUDE.md": role_dir / "CLAUDE.md",
    }


def _conteudo_arquivos(role_dir: Path) -> dict[str, str]:
    conteudos: dict[str, str] = {}
    for nome, caminho in _arquivos_papel(role_dir).items():
        if caminho is not None and caminho.is_file():
            try:
                conteudos[nome] = caminho.read_text(encoding="utf-8-sig")
            except OSError:
                conteudos[nome] = ""
    return conteudos


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------
def check(roles_dir: Path) -> int:
    """Verifica os papéis e retorna 0 se tudo estiver consistente, 1 caso
    contrário. Se roles_dir não existir, retorna 0 com mensagem informativa."""
    if not roles_dir.is_dir():
        print(f"[check] {roles_dir} não existe (ex.: CI sem .maestri/roles) — nada a verificar.")
        return 0

    erros: list[str] = []

    # Cada ID esperado em ROLE_DEFINITIONS deve existir como diretório.
    for role_id, (nome_esperado,) in ROLE_DEFINITIONS.items():
        role_dir = roles_dir / role_id
        if not role_dir.is_dir():
            erros.append(f"role_id ausente: {role_id} ({nome_esperado}) esperado em {role_dir}")
            continue

        conteudos = _conteudo_arquivos(role_dir)

        # Verificar role.json "name"
        caminho_role_json = role_dir / "role.json"
        role_json = _ler_json(caminho_role_json) if caminho_role_json.is_file() else None
        if role_json is None:
            erros.append(f"{role_id}: role.json não pôde ser lido ou está ausente")
        else:
            nome_atual = role_json.get("name")
            if nome_atual != nome_esperado:
                erros.append(
                    f"{role_id}: role.json name='{nome_atual}' diverge do esperado '{nome_esperado}'"
                )
            # Validar termos proibidos nos campos decodificados (prompt/name),
            # pois barras escapadas (\\/) no texto bruto mascaram os termos.
            campos_decodificados = ""
            for campo in ("name", "prompt"):
                valor = role_json.get(campo)
                if isinstance(valor, str):
                    campos_decodificados += valor + "\n"
            for termo in _termos_proibidos_no_texto(campos_decodificados):
                erros.append(f"{role_id}/role.json[campo decodificado]: termo obsoleto encontrado '{termo}'")

        # Verificar termos proibidos em role.json / AGENTS.md / CLAUDE.md
        for nome_arquivo, texto in conteudos.items():
            if nome_arquivo == "role.json":
                texto_bruto = (role_dir / "role.json").read_text(encoding="utf-8-sig")
            else:
                texto_bruto = texto
            for termo in _termos_proibidos_no_texto(texto_bruto):
                erros.append(f"{role_id}/{nome_arquivo}: termo obsoleto encontrado '{termo}'")

    if erros:
        print(f"[check] {len(erros)} divergência(s) encontrada(s):")
        for e in erros:
            print(f"  - {e}")
        return 1
    print("[check] Todos os papéis estão consistentes com ROLE_DEFINITIONS.")
    return 0


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------
def apply(roles_dir: Path) -> int:
    """Correge os textos nos arquivos de papel e retorna 0."""
    if not roles_dir.is_dir():
        print(f"[apply] {roles_dir} não existe — nada a aplicar.")
        return 0

    for role_id, (nome_esperado,) in ROLE_DEFINITIONS.items():
        role_dir = roles_dir / role_id
        if not role_dir.is_dir():
            continue

        # Corrigir role.json (texto bruto, gravado SEM BOM: encoding="utf-8")
        caminho_role_json = role_dir / "role.json"
        if caminho_role_json.is_file():
            try:
                texto_bruto = caminho_role_json.read_text(encoding="utf-8-sig")
            except OSError:
                texto_bruto = ""
            texto_corrigido = _corrigir_texto(texto_bruto)
            if texto_corrigido != texto_bruto:
                caminho_role_json.write_text(texto_corrigido, encoding="utf-8")

            role_json = _ler_json(caminho_role_json)
            if role_json is not None:
                alterado = False
                if role_json.get("name") != nome_esperado:
                    role_json["name"] = nome_esperado
                    alterado = True
                # Corrigir campo prompt (decodificado: barras \\/ viram /,
                # revelando termos obsoletos mascarados no texto bruto).
                prompt_atual = role_json.get("prompt")
                if isinstance(prompt_atual, str):
                    # Normalizar barras escapadas (\\/) para / antes de
                    # corrigir: role.json reais usam \\/ e os termos
                    # proibidos usam /. Sem isso, as substituições nao
                    # encontrariam os termos mascarados.
                    prompt_normalizado = prompt_atual.replace("\\/", "/")
                    prompt_corrigido = _corrigir_texto(prompt_normalizado)
                    if prompt_corrigido != prompt_atual:
                        role_json["prompt"] = prompt_corrigido
                        alterado = True
                if alterado:
                    try:
                        caminho_role_json.write_text(
                            json.dumps(role_json, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8",
                        )
                    except OSError:
                        pass

        # Corrigir AGENTS.md e CLAUDE.md (gravados SEM BOM: encoding="utf-8")
        for nome_arquivo in ("AGENTS.md", "CLAUDE.md"):
            caminho = role_dir / nome_arquivo
            if not caminho.is_file():
                continue
            try:
                texto_bruto = caminho.read_text(encoding="utf-8-sig")
            except OSError:
                continue
            texto_corrigido = _corrigir_texto(texto_bruto)
            if texto_corrigido != texto_bruto:
                caminho.write_text(texto_corrigido, encoding="utf-8")

    print("[apply] Correções aplicadas nos papéis encontrados.")
    return 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    roles_dir = args.repo / ".maestri" / "roles"
    if args.check:
        return check(roles_dir)
    if args.apply:
        return apply(roles_dir)
    # default: apenas check
    return check(roles_dir)


if __name__ == "__main__":
    sys.exit(main())
