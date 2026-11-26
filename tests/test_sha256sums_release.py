"""Testes de regressão para geração e verificação do SHA256SUMS.txt da release.

Causa do defeito (issue): o ``.github/workflows/release.yml`` gerava o
``SHA256SUMS.txt`` com caminhos completos do workspace::

    sha256sum release-assets/macos/*.dmg release-assets/windows/*.exe > SHA256SUMS.txt

produzindo entradas como::

    <hash>  release-assets/macos/Tomus-1.4.1-macOS.dmg
    <hash>  release-assets/windows/Tomus_Setup_v1.4.1_Windows_x64.exe

Quando o usuário baixa os assets do GitHub Release, ele obtém apenas os nomes de
arquivo base (ex.: ``Tomus-1.4.1-macOS.dmg``), sem o prefixo
``release-assets/macos/``. Assim, ``sha256sum -c SHA256SUMS.txt`` falha com
``No such file or directory`` e os checksums publicados não são verificáveis.

Correção: gerar o ``SHA256SUMS.txt`` com nomes relativos (somente o basename de
cada asset), de modo que::

    sha256sum -c SHA256SUMS.txt

funcione quando o usuário coloca os assets baixados e o ``SHA256SUMS.txt`` no
mesmo diretório. A correção preserva a compatibilidade Mac (.dmg) e
Windows (.exe) e é independente do SO do runner de CI.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

# Nome dos assets esperados (conforme build_macos.sh e build_windows.ps1).
MACOS_DMG = "Tomus-1.4.1-macOS.dmg"
WINDOWS_EXE = "Tomus_Setup_v1.4.1_Windows_x64.exe"


def _sha256sum_file(path: Path) -> str:
    """Retorna a linha no formato do GNU coreutils: '<hash>  <nome>'."""
    h = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"{h}  {path.name}"


def _gerar_sha256sums_com_nomes_relativos(assets: list[Path]) -> str:
    """Simula a geração correta do SHA256SUMS.txt (apenas nomes relativos)."""
    linhas = [_sha256sum_file(p) for p in assets]
    return "\n".join(linhas) + "\n"


def _gerar_sha256sums_com_caminhos_completos(assets: list[Path]) -> str:
    """Simula o comportamento defeituoso atual do release.yml.

    O release.yml grava caminhos relativos ao workspace do CI
    (``release-assets/macos/Tomus-1.4.1-macOS.dmg``), não apenas o basename.
    """
    linhas = []
    for p in assets:
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        # Caminho relativo ao workspace do CI (o defeito), não o basename.
        if p.name == MACOS_DMG:
            rel = f"release-assets/macos/{p.name}"
        else:
            rel = f"release-assets/windows/{p.name}"
        linhas.append(f"{h}  {rel}")
    return "\n".join(linhas) + "\n"


def _executa_sha256sum_check(conteudo_sums: str, workdir: Path) -> subprocess.CompletedProcess:
    """Escreve o SHA256SUMS.txt em workdir e executa sha256sum -c nele.

    Escreve com LF puro (``newline=""``) para evitar que o Windows converta
    ``\\n`` em CRLF, o que faria o ``sha256sum.exe -c`` tratar o ``\\r`` como
    parte do nome do arquivo (ex.: ``asset.exe\\r``) e falhar a verificação.
    """
    sums_path = workdir / "SHA256SUMS.txt"
    sums_path.write_text(conteudo_sums, encoding="utf-8", newline="")
    # No Windows o comando é sha256sum.exe / no Linux/macOS sha256sum.
    cmd = "sha256sum.exe" if sys.platform.startswith("win") else "sha256sum"
    return subprocess.run(
        [cmd, "-c", "SHA256SUMS.txt"],
        cwd=str(workdir),
        capture_output=True,
        text=True,
    )


@pytest.fixture
def assets_fake(tmp_path: Path) -> list[Path]:
    """Cria dois assets falsos (macOS .dmg e Windows .exe) num diretório tmp."""
    macos = tmp_path / MACOS_DMG
    windows = tmp_path / WINDOWS_EXE
    macos.write_bytes(b"conteudo fake macOS dmg")
    windows.write_bytes(b"conteudo fake Windows exe")
    return [macos, windows]


class TestSha256SumsNomesRelativos:
    """Verifica que nomes relativos tornam os checksums verificáveis pelo usuário."""

    def test_geracao_usa_apenas_nome_de_arquivo(self, assets_fake: list[Path]) -> None:
        """A geração correta deve conter apenas o basename, não o caminho completo."""
        conteudo = _gerar_sha256sums_com_nomes_relativos(assets_fake)
        for asset in assets_fake:
            assert asset.name in conteudo
            # O caminho completo do workspace NÃO deve aparecer.
            assert str(asset) not in conteudo
            assert "release-assets" not in conteudo

    def test_verificacao_passa_com_nomes_relativos_no_mesmo_diretorio(
        self, assets_fake: list[Path], tmp_path: Path
    ) -> None:
        """sha256sum -c deve passar quando assets + SHA256SUMS estão no mesmo dir."""
        conteudo = _gerar_sha256sums_com_nomes_relativos(assets_fake)
        # Simula o usuário: coloca assets + SHA256SUMS no mesmo diretório.
        usuario_dir = tmp_path / "usuario"
        usuario_dir.mkdir()
        for asset in assets_fake:
            (usuario_dir / asset.name).write_bytes(asset.read_bytes())
        resultado = _executa_sha256sum_check(conteudo, usuario_dir)
        assert resultado.returncode == 0, resultado.stderr
        for asset in assets_fake:
            assert f"{asset.name}: OK" in resultado.stdout

    def test_caminhos_completos_falham_no_contexto_do_usuario(
        self, assets_fake: list[Path], tmp_path: Path
    ) -> None:
        """Reproduz o defeito: caminhos completos fazem sha256sum -c falhar."""
        conteudo_defeituoso = _gerar_sha256sums_com_caminhos_completos(assets_fake)
        usuario_dir = tmp_path / "usuario"
        usuario_dir.mkdir()
        for asset in assets_fake:
            (usuario_dir / asset.name).write_bytes(asset.read_bytes())
        resultado = _executa_sha256sum_check(conteudo_defeituoso, usuario_dir)
        assert resultado.returncode != 0
        assert "No such file or directory" in resultado.stderr or \
               "não encontrado" in resultado.stderr or \
               "Não foi possível" in resultado.stderr


class TestSha256SumsFormatoPadrao:
    """Garante o formato padrão do GNU coreutils (<hash>  <nome>, dois espaços)."""

    def test_linha_tem_formato_hash_duplo_espaco_nome(self, assets_fake: list[Path]) -> None:
        conteudo = _gerar_sha256sums_com_nomes_relativos(assets_fake)
        for linha in conteudo.strip().splitlines():
            partes = linha.split("  ")
            assert len(partes) == 2, f"Linha não segue o formato <hash>  <nome>: {linha!r}"
            hash_hex, nome = partes
            assert len(hash_hex) == 64
            int(hash_hex, 16)  # deve ser hexadecimal válido
            assert nome in {MACOS_DMG, WINDOWS_EXE}

    def test_arquivo_nao_vazio_e_contém_ambos_assets(self, assets_fake: list[Path]) -> None:
        conteudo = _gerar_sha256sums_com_nomes_relativos(assets_fake)
        assert MACOS_DMG in conteudo
        assert WINDOWS_EXE in conteudo
        assert conteudo.count("\n") == 2  # duas linhas + newline final
