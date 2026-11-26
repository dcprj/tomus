"""Validação somente leitura do protocolo OneDrive (canal Mac <-> Windows).

Verifica:
  1. Sequência numérica dos arquivos de mensagem (NNNN_YYYY-MM-DD_slug.md).
  2. Presença e validade do YAML frontmatter em cada mensagem.
  3. Ausência de segredos (chaves API, tokens) no conteúdo das mensagens.
  4. Consistência dos cursores estado_*.json (baseline_main vs main atual,
     ultimo_enviado/ultimo_lido coerentes com os arquivos presentes).

Opção --desde NNNN: a partir de qual número de mensagem as validações de
sequência e frontmatter passam a ser ERRO bloqueante. Mensagens anteriores
a NNNN reportam desvios de sequência/frontmatter como AVISO [historico]
(não contam como erro nem falham o exit code). SEGREDO em qualquer mensagem
(mesmo < NNNN) e inconsistência de estado_*.json sempre são ERRO bloqueante
(exit code 1).

Não grava nada no OneDrive. Apenas lê e reporta.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

CANAL_DIR = Path("/Users/dario/Library/CloudStorage/OneDrive-Pessoal/comunicacao_mac_win/chefes_mac_win")
MAC_DIR = CANAL_DIR / "mac_para_win"
WIN_DIR = CANAL_DIR / "win_para_mac"

# Variável de ambiente para sobrescrever o canal OneDrive (útil em CI/outros SO).
ENV_CANAL_DIR = "TOMUS_ONEDRIVE_CANAL_DIR"

# Padrão de nome de arquivo: NNNN_YYYY-MM-DD_slug.md
# Aceita tanto underline quanto hífen entre a data e o slug (append-only do
# OneDrive da equipe Windows, não renomeável após envio).
ARQUIVO_RE = re.compile(r"^(\d{4})_(\d{4}-\d{2}-\d{2})[_-]([a-z0-9-]+)\.md$")

# Padrões de possíveis segredos (apenas heurística de leitura)
SEGREDO_RE = re.compile(
    r"(AIza[Sy][A-Za-z0-9_-]{8,}|sk-[A-Za-z0-9]{8,}|gh[pousr][A-Za-z0-9]{8,}|"
    r"nvapi-[A-Za-z0-9._-]{20,}|gsk-[A-Za-z0-9._-]{20,}|gsh_[A-Za-z0-9._-]{20,}|"
    r"sk-ant-[A-Za-z0-9-]{8,}|AKIA[0-9A-Z]{16})"
)


def listar_mensagens(diretorio: Path) -> list[tuple[int, str, Path]]:
    """Lista arquivos de mensagem válidos (NNNN_data_slug.md) ordenados."""
    resultado = []
    if not diretorio.is_dir():
        return resultado
    for arquivo in sorted(diretorio.glob("*.md")):
        m = ARQUIVO_RE.match(arquivo.name)
        if m:
            numero = int(m.group(1))
            resultado.append((numero, arquivo.name, arquivo))
    return sorted(resultado, key=lambda x: x[0])


def verificar_sequencia(
    mensagens: list[tuple[int, str, Path]], desde: int | None
) -> tuple[list[str], list[str]]:
    """Verifica se a sequência numérica é contínua a partir de 1.

    Retorna (avisos, erros). Quando `desde` é informado, desvios com
    numero < desde viram AVISO [historico]; desvios >= desde são ERRO.
    """
    avisos: list[str] = []
    erros: list[str] = []
    esperado = 1
    for numero, nome, _ in mensagens:
        if numero != esperado:
            msg = f"sequência interrompida: esperado {esperado}, encontrado {numero} ({nome})"
            if desde is not None and numero < desde:
                avisos.append(f"AVISO [historico]: {msg}")
            else:
                erros.append(msg)
        esperado = numero + 1
    return avisos, erros


def verificar_frontmatter(
    mensagens: list[tuple[int, str, Path]], desde: int | None
) -> tuple[list[str], list[str]]:
    """Verifica se cada mensagem tem YAML frontmatter válido.

    Retorna (avisos, erros). Mesmo comportamento de `desde` da sequência:
    numero < desde vira AVISO [historico]; >= desde é ERRO.
    """
    avisos: list[str] = []
    erros: list[str] = []
    for numero, nome, arquivo in mensagens:
        try:
            texto = arquivo.read_text(encoding="utf-8")
        except OSError as exc:
            msg = f"{nome}: não pôde ser lido ({exc})"
            erros.append(msg)
            continue
        if not texto.startswith("---\n"):
            msg = f"{nome}: frontmatter YAML ausente ou malformado"
            if desde is not None and numero < desde:
                avisos.append(f"AVISO [historico]: {msg}")
            else:
                erros.append(msg)
            continue
        # Encontrar o fechamento do frontmatter
        partes = texto.split("\n---\n", 1)
        if len(partes) < 2:
            msg = f"{nome}: frontmatter YAML incompleto (sem fechamento)"
            if desde is not None and numero < desde:
                avisos.append(f"AVISO [historico]: {msg}")
            else:
                erros.append(msg)
    return avisos, erros


def verificar_segredos(
    mensagens: list[tuple[int, str, Path]],
) -> tuple[list[str], list[str]]:
    """Verifica se nenhuma mensagem contém segredos (chaves, tokens).

    SEGREDO em qualquer mensagem (mesmo < desde) é sempre ERRO bloqueante.
    """
    avisos: list[str] = []
    erros: list[str] = []
    for _, nome, arquivo in mensagens:
        try:
            texto = arquivo.read_text(encoding="utf-8")
        except OSError as exc:
            erros.append(f"{nome}: não pôde ser lido ({exc})")
            continue
        if SEGREDO_RE.search(texto):
            erros.append(f"{nome}: possível segredo (chave/token) detectado no conteúdo")
    return avisos, erros


def verificar_estado_estado(
    estado_mac_path: Path,
    estado_win_path: Path,
    mensagens_mac: list,
    mensagens_win: list,
) -> tuple[list[str], list[str]]:
    """Verifica consistência dos arquivos estado_*.json.

    Sempre ERRO bloqueante, independente de `desde`.
    """
    avisos: list[str] = []
    erros: list[str] = []

    # Carregar estado_mac.json
    try:
        estado_mac = json.loads(estado_mac_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        erros.append(f"estado_mac.json: não pôde ser lido ({exc})")
        estado_mac = {}

    # Carregar estado_win.json
    try:
        estado_win = json.loads(estado_win_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        erros.append(f"estado_win.json: não pôde ser lido ({exc})")
        estado_win = {}

    # Verificar baseline_main
    baseline_main = estado_mac.get("baseline_main")
    if baseline_main:
        # baseline_main deve ser um hash SHA-1 de 40 caracteres
        if not re.fullmatch(r"[0-9a-f]{40}", baseline_main):
            erros.append(f"estado_mac.json: baseline_main '{baseline_main}' não é um SHA-1 válido")
    else:
        erros.append("estado_mac.json: baseline_main ausente")

    # Verificar ultimo_enviado_mac e ultimo_lido_win existem entre as mensagens
    ultimo_enviado_mac = estado_mac.get("ultimo_enviado_mac")
    if ultimo_enviado_mac:
        nomes_mac = {nome for _, nome, _ in mensagens_mac}
        if ultimo_enviado_mac not in nomes_mac:
            erros.append(f"estado_mac.json: ultimo_enviado_mac '{ultimo_enviado_mac}' não encontrado em mac_para_win/")

    ultimo_lido_win = estado_mac.get("ultimo_lido_win")
    if ultimo_lido_win:
        nomes_win = {nome for _, nome, _ in mensagens_win}
        if ultimo_lido_win not in nomes_win:
            erros.append(f"estado_mac.json: ultimo_lido_win '{ultimo_lido_win}' não encontrado em win_para_mac/")

    ultimo_enviado_win = estado_win.get("ultimo_enviado_win")
    if ultimo_enviado_win:
        nomes_win = {nome for _, nome, _ in mensagens_win}
        if ultimo_enviado_win not in nomes_win:
            erros.append(f"estado_win.json: ultimo_enviado_win '{ultimo_enviado_win}' não encontrado em win_para_mac/")

    ultimo_lido_mac = estado_win.get("ultimo_lido_mac")
    if ultimo_lido_mac:
        nomes_mac = {nome for _, nome, _ in mensagens_mac}
        if ultimo_lido_mac not in nomes_mac:
            erros.append(f"estado_win.json: ultimo_lido_mac '{ultimo_lido_mac}' não encontrado em mac_para_win/")

    return avisos, erros


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validação somente leitura do protocolo OneDrive (Mac <-> Windows)."
    )
    parser.add_argument(
        "--desde",
        type=int,
        default=None,
        metavar="NNNN",
        help="A partir de qual número de mensagem (NNNN) sequencia e frontmatter "
        "passam a ser ERRO bloqueante. Anteriores viram AVISO [historico].",
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=None,
        metavar="CAMINHO",
        help="Canal OneDrive a validar (sobrepõe TOMUS_ONEDRIVE_CANAL_DIR e o "
        "fallback macOS). Precedência: --dir > TOMUS_ONEDRIVE_CANAL_DIR > CANAL_DIR.",
    )
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    desde = args.desde

    # Precedência: --dir > TOMUS_ONEDRIVE_CANAL_DIR > CANAL_DIR (fallback macOS).
    # Quando --dir ou a variável de ambiente são informados, usa o canal
    # derivado deles. Caso contrário, respeita MAC_DIR/WIN_DIR/CANAL_DIR como
    # estão (permitindo monkeypatch nos testes existentes sem mutar globals()).
    uso_override = args.dir is not None or os.environ.get(ENV_CANAL_DIR) is not None
    if uso_override:
        canal_dir = Path(args.dir or os.environ.get(ENV_CANAL_DIR))
        mac_dir = canal_dir / "mac_para_win"
        win_dir = canal_dir / "win_para_mac"
    else:
        canal_dir = CANAL_DIR
        mac_dir = MAC_DIR
        win_dir = WIN_DIR

    todos_erros: list[str] = []

    # Listar mensagens
    mensagens_mac = listar_mensagens(mac_dir)
    mensagens_win = listar_mensagens(win_dir)

    print(f"mac_para_win/: {len(mensagens_mac)} mensagem(ns)")
    print(f"win_para_mac/: {len(mensagens_win)} mensagem(ns)")
    if desde is not None:
        print(f"--desde {desde:04d}: mensagens abaixo desse número reportam AVISO [historico]")

    # 1. Sequência numérica
    avisos_seq, erros_seq = verificar_sequencia(mensagens_mac, desde)
    av_win, er_win = verificar_sequencia(mensagens_win, desde)
    avisos_seq += av_win
    erros_seq = erros_seq + er_win
    for a in avisos_seq:
        print(a)
    if erros_seq:
        for e in erros_seq:
            print(f"ERRO [sequência]: {e}")
        todos_erros.extend(erros_seq)
    else:
        print("[OK] Sequência numérica contínua em ambos os canais")

    # 2. Frontmatter YAML
    avisos_fm, erros_fm = verificar_frontmatter(mensagens_mac, desde)
    av_win, er_win = verificar_frontmatter(mensagens_win, desde)
    avisos_fm += av_win
    erros_fm = erros_fm + er_win
    for a in avisos_fm:
        print(a)
    if erros_fm:
        for e in erros_fm:
            print(f"ERRO [frontmatter]: {e}")
        todos_erros.extend(erros_fm)
    else:
        print("[OK] Frontmatter YAML válido em todas as mensagens")

    # 3. Ausência de segredos (SEGREDO em qualquer mensagem é sempre ERRO)
    _, erros_sec = verificar_segredos(mensagens_mac)
    _, erros_sec_win = verificar_segredos(mensagens_win)
    erros_sec = erros_sec + erros_sec_win
    if erros_sec:
        for e in erros_sec:
            print(f"ERRO [segredo]: {e}")
        todos_erros.extend(erros_sec)
    else:
        print("[OK] Nenhum segredo (chave/token) encontrado nas mensagens")

    # 4. Consistência dos estado_*.json (sempre ERRO bloqueante)
    estado_mac_path = canal_dir / "estado_mac.json"
    estado_win_path = canal_dir / "estado_win.json"
    _, erros_est = verificar_estado_estado(
        estado_mac_path, estado_win_path, mensagens_mac, mensagens_win
    )
    if erros_est:
        for e in erros_est:
            print(f"ERRO [estado]: {e}")
        todos_erros.extend(erros_est)
    else:
        print("[OK] estado_mac.json e estado_win.json consistentes")

    if todos_erros:
        print(f"\n{len(todos_erros)} erro(s) encontrado(s).")
        return 1
    print("\nTodas as validações passaram.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
