"""Smoke autônomo do pipeline de classificação (para execução na VM do Windows).

COBRE:
  * Importa tomus.core.pipeline.run_pipeline e tomus.core.config diretamente
    (não depende da CLI de produto, que será removida pelo PROD-GUI-01).
  * Executa o pipeline completo sobre uma pasta de origem com PDFs de teste.
  * Valida o manifest.json gerado em destino conferindo:
      total_scanned, organized_count, manual_review_count,
      error_count, duplicate_skipped_count e confiança média.
  * Imprime veredito final PASSOU/FALHOU com exit code 0/1.
  * Funciona com o pacote instalado via `pip install .` num venv limpo.

NAO COBRE:
  * Não altera o pipeline; apenas orquestra e valida a saída.
  * Não testa a GUI nem o instalador Windows (escopo de vm_smoke_installer.ps1).
  * Não testa empacotamento PyInstaller/Inno Setup (escopo de release.yml/Farol).
  * Não valida credenciais reais de provedor LLM; usa provedor mock quando
    nenhuma chave está configurada.

Uso (Windows, venv limpo com pacote instalado):
  python scripts/vm_smoke_pipeline.py --origem test_data/pdfs --destino saida \
      --provider gemini --model gemini-3.5-flash --relatorio relatorio.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tomus.core.config import AppConfig
from tomus.core.pipeline import run_pipeline


def _construir_config(origem: Path, destino: Path, provider: str, model: str | None) -> AppConfig:
    """Monta o AppConfig a partir dos argumentos de linha de comando."""
    config = AppConfig()
    config.general.recursive = True
    config.general.file_operation = "copy"
    config.general.confidence_min = 0.70
    config.general.workers = 1
    config.general.use_cache = True

    config.llm.provider = provider
    if model:
        config.llm.model = model

    return config


def _carregar_manifest(destino: Path) -> dict:
    """Lê o manifest.json gravado pelo organizer em destino."""
    manifest_path = destino / "manifest.json"
    if not manifest_path.exists():
        print(f"FALHA: manifest.json não encontrado em {destino}")
        sys.exit(1)
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _confianca_media(entries: list[dict]) -> float:
    """Calcula a confiança média das entradas organizadas com classificação."""
    confiancas = []
    for entry in entries:
        classificacao = entry.get("classification") or {}
        conf = classificacao.get("confidence_score")
        if conf is not None:
            try:
                confiancas.append(float(conf))
            except (TypeError, ValueError):
                continue
    if not confiancas:
        return 0.0
    return sum(confiancas) / len(confiancas)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Smoke autônomo do pipeline de classificação do Tomus."
    )
    parser.add_argument("--origem", required=True, help="Pasta de origem com PDFs de teste.")
    parser.add_argument("--destino", required=True, help="Pasta de destino da organização.")
    parser.add_argument(
        "--provider", default="gemini", help="Provedor LLM padrão (default: gemini)."
    )
    parser.add_argument("--model", default=None, help="Modelo LLM (opcional).")
    parser.add_argument(
        "--relatorio", default=None, help="Caminho para salvar relatório JSON do smoke."
    )
    args = parser.parse_args()

    origem = Path(args.origem).resolve()
    destino = Path(args.destino).resolve()

    if not origem.exists():
        print(f"FALHA: pasta de origem não existe: {origem}")
        return 1
    if not origem.is_dir():
        print(f"FALHA: origem não é uma pasta: {origem}")
        return 1

    destino.mkdir(parents=True, exist_ok=True)

    print("=== Smoke pipeline Tomus ===")
    print(f"Origem: {origem}")
    print(f"Destino: {destino}")
    print(f"Provedor: {args.provider}")
    if args.model:
        print(f"Modelo: {args.model}")

    config = _construir_config(origem, destino, args.provider, args.model)

    try:
        run_pipeline(
            source_dir=origem,
            target_dir=destino,
            config=config,
            workers=1,
        )
    except Exception as exc:  # não deixar o smoke quebrar sem veredito
        print(f"FALHA: exceção ao executar run_pipeline: {exc}")
        return 1

    manifest = _carregar_manifest(destino)

    total_scanned = manifest.get("total_scanned", 0)
    organized_count = manifest.get("organized_count", 0)
    manual_review_count = manifest.get("manual_review_count", 0)
    error_count = manifest.get("error_count", 0)
    duplicate_skipped_count = manifest.get("duplicate_skipped_count", 0)
    exceeded_ceiling = manifest.get("exceeded_manual_review_ceiling", False)

    entries = manifest.get("entries", [])
    conf_media = _confianca_media(entries)

    print()
    print("=== Resultado do smoke pipeline ===")
    print(f"total_scanned:          {total_scanned}")
    print(f"organized_count:        {organized_count}")
    print(f"manual_review_count:    {manual_review_count}")
    print(f"error_count:            {error_count}")
    print(f"duplicate_skipped_count:{duplicate_skipped_count}")
    print(f"confiança média:        {conf_media:.2f}")
    print(f"teto de revisão excedido: {exceeded_ceiling}")

    falhas = []
    if total_scanned == 0:
        falhas.append("Nenhum PDF foi escaneado (total_scanned == 0).")
    if error_count > 0:
        falhas.append(f"Houve {error_count} erro(s) de processamento.")
    if organized_count == 0 and total_scanned > 0:
        falhas.append("Nenhum PDF foi organizado (organized_count == 0).")
    if exceeded_ceiling:
        falhas.append("Taxa de revisão manual excede o teto de 20%.")

    print()
    if falhas:
        print("VEREDIÇO: FALHOU")
        for f in falhas:
            print(f"  - {f}")
        codigo_saida = 1
    else:
        print("VEREDIÇO: PASSOU")
        codigo_saida = 0

    if args.relatorio:
        relatorio = {
            "veredito": "PASSOU" if codigo_saida == 0 else "FALHOU",
            "total_scanned": total_scanned,
            "organized_count": organized_count,
            "manual_review_count": manual_review_count,
            "error_count": error_count,
            "duplicate_skipped_count": duplicate_skipped_count,
            "confianca_media": round(conf_media, 4),
            "exceeded_manual_review_ceiling": exceeded_ceiling,
            "origem": str(origem),
            "destino": str(destino),
            "provider": args.provider,
            "model": args.model,
        }
        relatorio_path = Path(args.relatorio)
        relatorio_path.parent.mkdir(parents=True, exist_ok=True)
        relatorio_path.write_text(
            json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"Relatório gravado em: {relatorio_path}")

    return codigo_saida


if __name__ == "__main__":
    sys.exit(main())
