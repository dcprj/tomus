"""Teste de regressão para a ordem dos passos no job ``release`` do
``.github/workflows/release.yml``.

Causa do defeito (issue): o passo ``Verificar consistência de versão``
(que lê ``pyproject.toml``) era executado **antes** do passo ``Checkout do
código``, que ainda não havia baixado o repositório. Resultado:
``FileNotFoundError: [Errno 2] No such file or directory: 'pyproject.toml'``
e o job ``release`` falhava, impedindo a publicação da release.

Regra correta: ``Checkout do código`` deve vir **antes** de qualquer passo
que leia arquivos do repositório (como ``pyproject.toml``), preservando a
validação de versão (tag vs ``pyproject.toml``) sem desativá-la.
"""

from __future__ import annotations

from pathlib import Path

RELEASE_YML = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "release.yml"


def _release_job_steps(text: str) -> list[str]:
    """Extrai os nomes dos steps (``name:``) do job ``release`` em ordem.

    Implementação leve e intencionalmente simples: após encontrar a linha
    ``release:`` (cabeçalho do job), coleta todas as linhas ``- name:`` que
    estejam indentadas (pertencentes ao job), parando ao encontrar outro job
    de mesmo nível de indentação (ex.: ``  build-macos:``) ou fim do arquivo.
    Não depende de PyYAML para evitar dependência extra no teste.
    """
    lines = text.splitlines()
    steps: list[str] = []
    in_release_job = False
    for line in lines:
        if not in_release_job:
            if line.strip() == "release:":
                in_release_job = True
            continue
        # Estamos dentro do job release. Outro job de mesmo nível inicia com
        # exatamente 2 espaços seguidos de nome do job e dois pontos.
        if line.startswith("  ") and not line.startswith("   ") and ":" in line and line.strip().endswith(":"):
            # Pode ser um novo job (ex.: "  build-macos:") ou uma chave de
            # nível de job. Se for um novo job (não é um step), pare.
            stripped = line.strip()
            if stripped.endswith(":") and not stripped.startswith("-"):
                break
            continue
        if "- name:" in line:
            steps.append(line.split("- name:", 1)[1].strip())
    return steps


def _passo_posicao(steps: list[str], nome_passos: str) -> int | None:
    """Retorna o índice (base 0) do passo cujo nome contém ``nome_passos``."""
    for i, s in enumerate(steps):
        if nome_passos in s:
            return i
    return None


class TestReleaseJobOrdemDePassos:
    """Garante que o checkout precede a leitura de arquivos do repositório."""

    def test_release_job_existe(self) -> None:
        """O job ``release`` deve estar definido no workflow."""
        text = RELEASE_YML.read_text(encoding="utf-8")
        assert "release:" in text

    def test_checkout_antes_da_versao(self) -> None:
        """O passo Checkout do código deve vir ANTES de Verificar consistência de versão.

        O checkout baixa o repositório (incluindo ``pyproject.toml``); a
        verificação de versão lê esse arquivo. Se a ordem for invertida, o
        job release falha com FileNotFoundError porque ``pyproject.toml``
        ainda nao foi baixado.
        """
        text = RELEASE_YML.read_text(encoding="utf-8")
        steps = _release_job_steps(text)

        checkout_idx = _passo_posicao(steps, "Checkout do código")
        versao_idx = _passo_posicao(steps, "Verificar consistência de versão")

        # Ambos os passos devem existir no job release.
        assert checkout_idx is not None, "Passo 'Checkout do código' não encontrado no job release"
        assert versao_idx is not None, "Passo 'Verificar consistência de versão' não encontrado no job release"

        # O checkout deve anteceder a leitura da versão.
        assert checkout_idx < versao_idx, (
            "Ordem incorreta: 'Checkout do código' (índice "
            f"{checkout_idx}) vem depois de 'Verificar consistência de versão' "
            f"(índice {versao_idx}). O checkout deve vir primeiro para que "
            "pyproject.toml exista quando a versão for lida."
        )

    def test_validaacao_de_versao_preservada(self) -> None:
        """A validação de versão (tag vs pyproject.toml) não deve ser removida."""
        text = RELEASE_YML.read_text(encoding="utf-8")
        assert "Verificar consistência de versão" in text
        assert "pyproject.toml" in text
        assert "EXPECTED_TAG" in text
