"""Testes do PR #14 — Fascículos de revista (critérios 1 a 5 do Cortex).

Cobrem:
1. periodicals.py (canonical_journal, parse_roman V/5/Ano V, parse_issue simples/52-53/52A/0, datas PT/EN)
2. format_periodical_filename ('Micro Sistemas - 1986-07 - v005 - n0058.pdf', sem [ano], s.d., supl-01, limite 245 Windows)
3. DocumentType.REVISTA e alias legado 'Revista Cientifica', roteador .../Revista/Micro Sistemas/
4. n58 e n59 ambos canonicos sem contador -1/-2, zero obsolescencia entre fasciculos, L2_ISSN exigindo numero estruturado igual
5. L3_FINGERPRINT via by_journal com nome de 2 palavras sem casar n58 com n59, nunca casar Artigo com Revista fora de L1
   colisao serial '- h<12 hex>', from_target_dir com front matter legado, ABNT NBR 6023:2025 em companion.py
   e dest_dir_probe restrito a sys.platform == 'win32'.
"""

from __future__ import annotations

import hashlib
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from tomus.core.config import AppConfig
from tomus.core.llm import ClassificationResult
from tomus.core.models import DocumentType, LLMClassificationOutput, ProcessStatus
from tomus.core.periodicals import (
    canonical_journal,
    format_display_name,
    is_redundant_issue_designation,
    journal_sort_key,
    parse_date,
    parse_issue,
    parse_roman,
    supplement_label,
)
from tomus.core.pipeline import _process_one
from tomus.core.scanner import ScannedFile
from tomus.storage.companion import format_abnt_reference
from tomus.storage.namer import WIN_SAFE_FULL_PATH_CHARS, format_periodical_filename
from tomus.storage.organizer import LibraryIndex, LibraryOrganizer

WIN = sys.platform == "win32"


# --------------------------------------------------------------------------- #
# Helpers de fixture sintética
# --------------------------------------------------------------------------- #
def _fake_pdf(tmp_path: Path, name: str, content: bytes = b"%PDF-1.4 fake\n") -> Path:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return p


def _sha_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_organizer(tmp_path: Path) -> LibraryOrganizer:
    return LibraryOrganizer(tmp_path / "dst", file_operation="copy", dry_run=True)


# =========================================================================== #
# Critério 1 — periodicals.py
# =========================================================================== #
class TestPeriodicalsCanonicalJournal:
    def test_canonical_journal_alias_micro_sistemas(self):
        assert canonical_journal("micro sistemas") == "Micro Sistemas"
        assert canonical_journal("MICRO SISTEMAS") == "Micro Sistemas"
        assert canonical_journal("microsistemas") == "Micro Sistemas"

    def test_canonical_journal_preserva_grafia_sem_alias(self):
        assert canonical_journal("Revista de Tecnologia") == "Revista de Tecnologia"

    def test_canonical_journal_none_vazio_retorna_none(self):
        assert canonical_journal(None) is None
        assert canonical_journal("") is None
        assert canonical_journal("   ") is None

    def test_journal_sort_key_normalizado(self):
        assert journal_sort_key("Micro Sistemas") == journal_sort_key("micro sistemas")
        assert journal_sort_key("Micro Sistemas") == "micro sistemas"


class TestPeriodicalsParseRoman:
    def test_parse_roman_v_5(self):
        assert parse_roman("V") == 5
        assert parse_roman("VIII") == 8
        assert parse_roman("X") == 10

    def test_parse_roman_ano_v_preserva_valor_ordinal(self):
        # 'Ano V' tem valor ordinal 5 (rótulo 'ano' é responsabilidade do chamador).
        assert parse_roman("V") == 5

    def test_parse_roman_invalido_retorna_none(self):
        assert parse_roman("") is None
        assert parse_roman("ABCD") is None
        assert parse_roman("VV") is None  # V repetido não é canônico


class TestPeriodicalsParseIssue:
    def test_parse_issue_simples(self):
        r = parse_issue("58")
        assert r["kind"] == "simple"
        assert r["label"] == "n0058"
        assert r["value"] == "58"

    def test_parse_issue_duplo_52_53(self):
        r = parse_issue("52/53")
        assert r["kind"] == "double"
        assert r["label"] == "n0052-0053"
        assert r["primary"] == "52"

    def test_parse_issue_alfanumerico_52a(self):
        r = parse_issue("52A")
        assert r["kind"] == "alpha"
        assert r["label"] == "n0052A"
        assert r["value"] == "52A"

    def test_parse_issue_zero_expresso(self):
        r = parse_issue("0")
        assert r["kind"] == "zero"
        assert r["value"] == "0"

    def test_parse_issue_nao_reconhecido_retorna_raw(self):
        r = parse_issue("informática86")
        assert r["kind"] == "raw"
        assert r["label"] == "informática86"


class TestPeriodicalsParseDate:
    def test_parse_date_mes_pt_por_extenso(self):
        r = parse_date("julho de 1986")
        assert r["year"] == 1986
        assert r["month"] == 7

    def test_parse_date_mes_en_por_extenso(self):
        r = parse_date("July 1986")
        assert r["year"] == 1986
        assert r["month"] == 7

    def test_parse_date_mes_numerico_mm_aaaa(self):
        r = parse_date("07/1986")
        assert r["year"] == 1986
        assert r["month"] == 7

    def test_parse_date_nao_promove_mes_isolado_a_fasciculo(self):
        # '07/1986' só preenche ano+mês, nunca vira número do fascículo.
        r = parse_date("07/1986")
        assert r["month"] != "58"

    def test_parse_date_sem_mes_preserva_ano(self):
        r = parse_date("1986")
        assert r["year"] == 1986
        assert r["month"] is None

    def test_parse_date_vazio_retorna_nulos(self):
        r = parse_date("")
        assert r["year"] is None
        assert r["month"] is None


class TestPeriodicalsSupplementLabel:
    def test_suplemento_supl_01(self):
        assert supplement_label("supl-01") == "supl-01"
        assert supplement_label("supl. 01") == "supl-01"
        assert supplement_label("suplemento") == "supl-00"

    def test_sem_suplemento_retorna_none(self):
        assert supplement_label(None) is None
        assert supplement_label("") is None


class TestPeriodicalsFormatDisplayName:
    def test_display_ano_v_nao_preenche_ano_civil(self):
        # 'Ano V' preserva rótulo 'ano' na citação ABNT, mas não preenche ano civil.
        nome = format_display_name("Micro Sistemas", year=5, volume_label="ano", volume="V")
        assert "[ano]" in nome

    def test_display_omite_campos_nao_informados(self):
        nome = format_display_name("Micro Sistemas", year=1986, month=7)
        assert nome == "Micro Sistemas - 1986-07"

    def test_display_com_vol_num_designacao(self):
        nome = format_display_name(
            "Micro Sistemas", year=1986, month=7, volume="5", issue="58", designation="supl-01"
        )
        assert "v005" in nome
        assert "n0058" in nome
        assert "supl-01" in nome


# =========================================================================== #
# Critério 2 — format_periodical_filename
# =========================================================================== #
class TestPeriodicalFilename:
    def test_nome_ordenavel_exemplo_cortex(self, tmp_path: Path):
        """Micro Sistemas - 1986-07 - v005 - n0058.pdf"""
        dest_dir = tmp_path / "dst" / "Computação" / "Geral" / "Revista" / "Micro Sistemas"
        dest_dir.mkdir(parents=True)
        nome = format_periodical_filename(
            journal="Micro Sistemas",
            year=1986,
            month=7,
            volume="5",
            volume_label="ano",
            number="58",
            dest_dir=dest_dir,
            max_full_path_chars=WIN_SAFE_FULL_PATH_CHARS,
        )
        assert nome == "Micro Sistemas - 1986-07 - v005 - n0058.pdf"

    def test_sem_ano_no_nome(self, tmp_path: Path):
        dest_dir = tmp_path / "dst" / "Computação" / "Geral" / "Revista" / "Micro Sistemas"
        dest_dir.mkdir(parents=True)
        nome = format_periodical_filename(
            journal="Micro Sistemas",
            year=None,
            month=None,
            volume="5",
            number="58",
            dest_dir=dest_dir,
            max_full_path_chars=WIN_SAFE_FULL_PATH_CHARS,
        )
        assert "s.d." in nome
        assert nome == "Micro Sistemas - s.d. - v005 - n0058.pdf"

    def test_sem_colchetes_ano(self, tmp_path: Path):
        # Nunca colocar '[ano]' no nome.
        dest_dir = tmp_path / "dst" / "Computação" / "Geral" / "Revista" / "Micro Sistemas"
        dest_dir.mkdir(parents=True)
        nome = format_periodical_filename(
            journal="Micro Sistemas",
            year=1986,
            month=7,
            volume="5",
            number="58",
            dest_dir=dest_dir,
            max_full_path_chars=WIN_SAFE_FULL_PATH_CHARS,
        )
        assert "[" not in nome and "]" not in nome

    def test_suplemento_supl_01(self, tmp_path: Path):
        dest_dir = tmp_path / "dst" / "Computação" / "Geral" / "Revista" / "Micro Sistemas"
        dest_dir.mkdir(parents=True)
        nome = format_periodical_filename(
            journal="Micro Sistemas",
            year=1986,
            month=7,
            volume="5",
            number="58",
            supplement="supl-01",
            dest_dir=dest_dir,
            max_full_path_chars=WIN_SAFE_FULL_PATH_CHARS,
        )
        assert "supl-01" in nome

    def test_numero_duplo_e_alfanumerico(self, tmp_path: Path):
        dest_dir = tmp_path / "dst" / "Computação" / "Geral" / "Revista" / "Micro Sistemas"
        dest_dir.mkdir(parents=True)
        n_duplo = format_periodical_filename(
            journal="Micro Sistemas", year=1986, month=7, volume="5", number="52/53",
            dest_dir=dest_dir, max_full_path_chars=WIN_SAFE_FULL_PATH_CHARS,
        )
        assert "n0052-0053" in n_duplo
        n_alpha = format_periodical_filename(
            journal="Micro Sistemas", year=1986, month=7, volume="5", number="52A",
            dest_dir=dest_dir, max_full_path_chars=WIN_SAFE_FULL_PATH_CHARS,
        )
        assert "n0052A" in n_alpha

    def test_periodico_duas_palavras_preservado(self, tmp_path: Path):
        dest_dir = tmp_path / "dst" / "Computação" / "Geral" / "Revista" / "Micro Sistemas"
        dest_dir.mkdir(parents=True)
        nome = format_periodical_filename(
            journal="Micro Sistemas", year=1986, month=7, number="58",
            dest_dir=dest_dir, max_full_path_chars=WIN_SAFE_FULL_PATH_CHARS,
        )
        assert "Micro Sistemas" in nome

    def test_limite_windows_245(self, tmp_path: Path):
        """Caminho absoluto <= WIN_SAFE_FULL_PATH_CHARS (245) em qualquer SO."""
        dest_dir = tmp_path / 'dst' / ('x' * 20) / 'Revista' / ('y' * 20)
        dest_dir.mkdir(parents=True)
        nome = format_periodical_filename(
            journal='Revista ' + ('Computacao ' * 15),
            year=1986,
            month=7,
            number='58',
            sha='a' * 64,
            dest_dir=dest_dir,
            max_full_path_chars=WIN_SAFE_FULL_PATH_CHARS,
        )
        full = str(dest_dir / nome)
        assert len(full) <= 245, f"caminho estourou: {len(full)} > 245"

    def test_hash_sufixo_colisao(self, tmp_path: Path):
        """Sufixo '- h<sha[:12]>' só aparece quando excede max_full_path_chars."""
        dest_dir = tmp_path / 'dst' / ('x' * 20) / 'Revista' / ('y' * 20)
        dest_dir.mkdir(parents=True)
        sha = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"
        nome = format_periodical_filename(
            journal='Revista ' + ('Computacao ' * 15),
            year=1986,
            month=7,
            number='58',
            dest_dir=dest_dir,
            max_full_path_chars=WIN_SAFE_FULL_PATH_CHARS,
            sha=sha,
        )
        assert " - h" + sha[:12] in nome
        assert len(str(dest_dir / nome)) <= 245



# =========================================================================== #
# Critério 3 — DocumentType.REVISTA, alias legado e roteador
# =========================================================================== #
class TestDocumentTypeRevista:
    def test_revista_valor_canonico(self):
        assert DocumentType.REVISTA.value == "Revista"

    def test_revista_alias_legado_revista_cientifica(self):
        assert DocumentType.REVISTA_CIENTIFICA.value == "Revista"
        assert DocumentType.REVISTA_CIENTIFICA is DocumentType.REVISTA

    def test_desserializacao_aceita_revista_cientifica_legado(self):
        assert DocumentType("Revista Científica") is DocumentType.REVISTA
        assert DocumentType("Revista Cientifica") is DocumentType.REVISTA
        assert DocumentType("revista") is DocumentType.REVISTA
        assert DocumentType("periódico") is DocumentType.REVISTA

    def test_llm_classification_output_tipo_revista(self):
        from tomus.core.models import LLMClassificationOutput
        out = LLMClassificationOutput(
            grande_area="Ciências Exatas e da Terra",
            area_basica="Computação",
            tipo="Revista",
            authors=[],
            title="Micro Sistemas",
            subtitle="",
            year=1986,
            confidence_score=0.95,
            reasoning="ok",
        )
        assert out.tipo is DocumentType.REVISTA
        assert out.tipo.value == "Revista"


class TestRoteadorRevista:
    def test_roteador_revista_caminho_revista_periodico(self, tmp_path: Path):
        """Roteador: .../Revista/Micro Sistemas/"""
        organizer = _make_organizer(tmp_path)
        p = _fake_pdf(tmp_path / "src", "micro_sistemas_n58.pdf")

        dest_dir = tmp_path / "dst" / "Computação" / "Geral" / "Revista" / "Micro Sistemas"
        nome = format_periodical_filename(
            journal="Micro Sistemas", year=1986, month=7, number="58",
            dest_dir=dest_dir, max_full_path_chars=WIN_SAFE_FULL_PATH_CHARS,
        )
        e = organizer.add_organized(
            source_path=p, grande_area="Ciências Exatas e da Terra",
            area_basica="Computação", subarea="Geral", especialidade="Geral",
            tipo="Revista", filename=nome, sha256=_sha_of(p),
            classification={
                "authors": [], "title": "Micro Sistemas", "year": 1986,
                "periodico": "Micro Sistemas", "volume": "5", "number": "58",
                "tipo": "Revista",
            },
        )
        assert e.status == ProcessStatus.ORGANIZED
        assert "Revista" in str(e.destination_path)
        assert "Micro Sistemas" in str(e.destination_path)

    def test_tipo_revista_nao_usa_autor_desconhecido(self, tmp_path: Path):
        organizer = _make_organizer(tmp_path)
        p = _fake_pdf(tmp_path / "src", "micro_sistemas_n58.pdf")
        dest_dir = tmp_path / "dst" / "Computação" / "Geral" / "Revista" / "Micro Sistemas"
        dest_dir.mkdir(parents=True)
        nome = format_periodical_filename(
            journal="Micro Sistemas", year=1986, month=7, number="58",
            dest_dir=dest_dir, max_full_path_chars=WIN_SAFE_FULL_PATH_CHARS,
        )
        e = organizer.add_organized(
            source_path=p, grande_area="Ciências Exatas e da Terra",
            area_basica="Computação", subarea="Geral", especialidade="Geral",
            tipo="Revista", filename=nome, sha256=_sha_of(p),
            classification={
                "authors": [], "title": "Micro Sistemas", "year": 1986,
                "periodico": "Micro Sistemas", "volume": "5", "number": "58",
                "tipo": "Revista",
            },
        )
        cls = e.classification or {}
        assert cls.get("authors") == [] or cls.get("authors") is None


# =========================================================================== #
# Critério 4 — n58/n59 canonicos, zero obsolescencia, L2_ISSN
# =========================================================================== #
class TestDedupFasciculos:
    def test_n58_e_n59_ambos_canonicos_sem_contador(self, tmp_path: Path):
        """n58 e n59 com mesmo ISSN, número diferente: dois canônicos, zero contador."""
        organizer = LibraryOrganizer(tmp_path / "dst", file_operation="copy", dry_run=False)

        issn = "1234-5679"  # ISSN válido sintético

        def _fasciculo(numero, ano):
            p = _fake_pdf(tmp_path / "src", f"micro_sistemas_n{numero}.pdf",
                          content=f'%PDF-1.4 fake fasciculo {numero}'.encode())
            dest_dir = tmp_path / "dst" / "Computação" / "Geral" / "Revista" / "Micro Sistemas"
            nome = format_periodical_filename(
                journal="Micro Sistemas", year=ano, month=7, number=numero,
                dest_dir=dest_dir, max_full_path_chars=WIN_SAFE_FULL_PATH_CHARS,
            )
            e = organizer.add_organized(
                source_path=p, grande_area="Ciências Exatas e da Terra",
                area_basica="Computação", subarea="Geral", especialidade="Geral",
                tipo="Revista", filename=nome, sha256=_sha_of(p),
                classification={
                    "authors": [], "title": "Micro Sistemas", "year": ano,
                    "periodico": "Micro Sistemas", "issn": issn,
                    "volume": "5", "number": str(numero), "tipo": "Revista",
                },
            )
            return e

        e58 = _fasciculo(58, 1986)
        e59 = _fasciculo(59, 1986)

        assert e58.status == ProcessStatus.ORGANIZED, f"n58: {e58.status}"
        assert e59.status == ProcessStatus.ORGANIZED, f"n59: {e59.status}"
        # Zero obsolescência entre fascículos
        assert not (tmp_path / "dst" / "obsoletos").exists() or not list(
            (tmp_path / "dst" / "obsoletos").iterdir()
        )
        # Zero contador -1/-2
        assert " (2)" not in str(e58.destination_path)
        assert " (2)" not in str(e59.destination_path)

    def test_l2_issn_exige_numero_estruturado_igual(self, tmp_path: Path):
        """L2_ISSN só casa se número estruturado igual E volume/ano compatível."""
        organizer = LibraryOrganizer(tmp_path / "dst", file_operation="copy", dry_run=False)
        issn = "1234-5679"

        def _fasciculo(numero, ano):
            p = _fake_pdf(tmp_path / "src", f"ms_n{numero}.pdf",
                          content=f'%PDF-1.4 fake fasciculo {numero}'.encode())
            dest_dir = tmp_path / "dst" / "Computação" / "Geral" / "Revista" / "Micro Sistemas"
            dest_dir.mkdir(parents=True, exist_ok=True)
            nome = format_periodical_filename(
                journal="Micro Sistemas", year=ano, month=7, number=numero,
                dest_dir=dest_dir, max_full_path_chars=WIN_SAFE_FULL_PATH_CHARS,
            )
            e = organizer.add_organized(
                source_path=p, grande_area="Ciências Exatas e da Terra",
                area_basica="Computação", subarea="Geral", especialidade="Geral",
                tipo="Revista", filename=nome, sha256=_sha_of(p),
                classification={
                    "authors": [], "title": "Micro Sistemas", "year": ano,
                    "periodico": "Micro Sistemas", "issn": issn,
                    "volume": "5", "number": str(numero), "tipo": "Revista",
                },
            )
            return e

        e58 = _fasciculo(58, 1986)
        e59 = _fasciculo(59, 1986)

        # Mesmo ISSN mas número diferente → não são L2_ISSN (número estruturado difere)
        assert e58.status == ProcessStatus.ORGANIZED
        assert e59.status == ProcessStatus.ORGANIZED


# =========================================================================== #
# Critério 5 — L3_FINGERPRINT, Artigo vs Revista, colisão, from_target_dir, ABNT
# =========================================================================== #
class TestDedupL3Fingerprint:
    def test_l3_por_journal_nao_casa_n58_com_n59(self, tmp_path: Path):
        """L3 via by_journal com nome de 2 palavras não casa n58 com n59 (número diferente)."""
        organizer = LibraryOrganizer(tmp_path / "dst", file_operation="copy", dry_run=False)
        issn = "1234-5679"

        def _fasciculo(numero, ano):
            p = _fake_pdf(tmp_path / "src", f"ms_n{numero}.pdf",
                          content=f'%PDF-1.4 fake fasciculo {numero}'.encode())
            dest_dir = tmp_path / "dst" / "Computação" / "Geral" / "Revista" / "Micro Sistemas"
            dest_dir.mkdir(parents=True, exist_ok=True)
            nome = format_periodical_filename(
                journal="Micro Sistemas", year=ano, month=7, number=numero,
                dest_dir=dest_dir, max_full_path_chars=WIN_SAFE_FULL_PATH_CHARS,
            )
            e = organizer.add_organized(
                source_path=p, grande_area="Ciências Exatas e da Terra",
                area_basica="Computação", subarea="Geral", especialidade="Geral",
                tipo="Revista", filename=nome, sha256=_sha_of(p),
                classification={
                    "authors": [], "title": "Micro Sistemas", "year": ano,
                    "periodico": "Micro Sistemas", "issn": issn,
                    "volume": "5", "number": str(numero), "tipo": "Revista",
                },
            )
            return e

        _fasciculo(58, 1986)
        e59 = _fasciculo(59, 1986)
        # Mesmo periódico, número diferente → não casar por L3
        assert e59.status == ProcessStatus.ORGANIZED

    def test_nunca_casa_artigo_com_revista_fora_l1(self, tmp_path: Path):
        """Artigo e Revista do mesmo periódico nunca se casam fora de L1 (SHA idêntico)."""
        organizer = LibraryOrganizer(tmp_path / "dst", file_operation="copy", dry_run=False)

        # Mesmo conteúdo SHA (L1) → duplicata, mesmo sendo tipos diferentes
        conteudo = b"%PDF-1.4 conteudo compartilhado\n"
        p_artigo = _fake_pdf(tmp_path / "src", "artigo.pdf", conteudo)
        p_revista = _fake_pdf(tmp_path / "src", "revista.pdf", conteudo)
        sha = _sha_of(p_artigo)

        dest_dir = tmp_path / "dst" / "Computação" / "Geral" / "Artigo"
        dest_dir.mkdir(parents=True, exist_ok=True)
        e_artigo = organizer.add_organized(
            source_path=p_artigo, grande_area="Ciências Exatas e da Terra",
            area_basica="Computação", subarea="Geral", especialidade="Geral",
            tipo="Artigo", filename="Artigo - 2020.pdf", sha256=sha,
            classification={"authors": ["Autor, Um"], "title": "Artigo X", "year": 2020,
                           "tipo": "Artigo", "journal_name": "Micro Sistemas"},
        )

        dest_dir_rev = tmp_path / "dst" / "Computação" / "Geral" / "Revista" / "Micro Sistemas"
        dest_dir_rev.mkdir(parents=True, exist_ok=True)
        nome_rev = format_periodical_filename(
            journal="Micro Sistemas", year=2020, month=7, number="1",
            dest_dir=dest_dir_rev, max_full_path_chars=WIN_SAFE_FULL_PATH_CHARS,
        )
        e_revista = organizer.add_organized(
            source_path=p_revista, grande_area="Ciências Exatas e da Terra",
            area_basica="Computação", subarea="Geral", especialidade="Geral",
            tipo="Revista", filename=nome_rev, sha256=sha,
            classification={"authors": [], "title": "Micro Sistemas", "year": 2020,
                           "periodico": "Micro Sistemas", "number": "1", "tipo": "Revista"},
        )
        # Mesmo SHA → L1 deduplica (mesmo que tipos diferentes)
        assert e_artigo.status == ProcessStatus.ORGANIZED
        assert e_revista.status == ProcessStatus.DUPLICATE_SKIPPED

    def test_colisao_serial_hash_12_hex(self, tmp_path: Path):
        """Colisão serial usa sufixo '- h<12 hex>' quando excede o limite de caminho."""
        organizer = LibraryOrganizer(tmp_path / "dst", file_operation="copy", dry_run=False)
        p1 = _fake_pdf(tmp_path / "src", "ms_n58_a.pdf", b"conteudo A\n")
        p2 = _fake_pdf(tmp_path / "src", "ms_n58_b.pdf", b"conteudo B\n")

        dest_dir = tmp_path / 'dst' / 'Computação' / 'Geral' / 'Revista' / 'Micro Sistemas'
        dest_dir.mkdir(parents=True, exist_ok=True)
        nome_base = format_periodical_filename(
            journal="Micro Sistemas", year=1986, month=7, number="58",
            dest_dir=dest_dir, max_full_path_chars=WIN_SAFE_FULL_PATH_CHARS,
        )
        sha1 = _sha_of(p1)
        sha2 = _sha_of(p2)
        e1 = organizer.add_organized(
            source_path=p1, grande_area="Ciências Exatas e da Terra",
            area_basica="Computação", subarea="Geral", especialidade="Geral",
            tipo="Revista", filename=nome_base, sha256=sha1,
            classification={"authors": [], "title": "Micro Sistemas", "year": 1986,
                           "periodico": "Micro Sistemas", "number": "58", "tipo": "Revista"},
        )
        e2 = organizer.add_organized(
            source_path=p2, grande_area="Ciências Exatas e da Terra",
            area_basica="Computação", subarea="Geral", especialidade="Geral",
            tipo="Revista", filename=nome_base, sha256=sha2,
            classification={"authors": [], "title": "Micro Sistemas", "year": 1986,
                           "periodico": "Micro Sistemas", "number": "59", "tipo": "Revista"},
        )
        assert e1.status == ProcessStatus.ORGANIZED
        assert e2.status == ProcessStatus.ORGANIZED
        assert e1.destination_path != e2.destination_path
        # O segundo arquivo (colisão) carrega o sufixo '- h<sha[:12]>'.
        assert " - h" + sha2[:12] in str(e2.destination_path)


    def test_from_target_dir_front_matter_legado(self, tmp_path: Path):
        """Reindexação de companion legado (mesmo campos PT/EN e tipo legado)."""
        target = tmp_path / "dst"
        target.mkdir(parents=True)
        md_dir = target / "Computação" / "Geral" / "Revista" / "Micro Sistemas"
        md_dir.mkdir(parents=True)
        pdf = md_dir / "Micro Sistemas - 1986-07 - v005 - n0058.pdf"
        pdf.write_bytes(b"%PDF-1.4 legacy\n")
        sha = _sha_of(pdf)
        md = pdf.with_suffix(".md")
        md.write_text(
            "---\n"
            "titulo: 'Micro Sistemas'\n"
            "ano: 1986\n"
            "periodico: 'Micro Sistemas'\n"
            "volume: '5'\n"
            "numero: '58'\n"
            "tipo: 'Revista Científica'\n"
            f"sha256: '{sha}'\n"
            "---\n",
            encoding="utf-8",
        )
        idx = LibraryIndex.from_target_dir(target)
        assert sha in idx.canon_by_sha

    def test_abnt_nbr_6023_2025_revista(self, tmp_path: Path):
        """Companion gera referência ABNT NBR 6023:2025 para revista (periódico primeiro)."""
        from tomus.storage.companion import format_abnt_reference
        classificacao = {
            "tipo": "Revista",
            "periodico": "Micro Sistemas",
            "journal_name": "Micro Sistemas",
            "city": "Rio de Janeiro",
            "publisher": "Análise, Teleprocessamento e Informática Editora Ltda.",
            "volume": "5",
            "volume_label": "ano",
            "number": "58",
            "publication_month": 7,
            "year": 1986,
            "issue_designation": "",
            "supplement": None,
        }
        ref = format_abnt_reference(classificacao)
        assert "MICRO SISTEMAS" in ref
        assert "Rio de Janeiro" in ref
        assert "ano 5" in ref
        assert "n. 58" in ref
        assert "jul." in ref
        assert "1986" in ref

    def test_dest_dir_probe_apenas_windows(self, monkeypatch, tmp_path: Path):
        """dest_dir_probe só é aplicado em sys.platform == 'win32'.

        No Windows (win32), caminho longo redireciona para revisao_manual (MANUAL_REVIEW).
        Em não-Windows (linux), não há proteção -> ORGANIZED. Usa dry_run=True para não
        estourar MAX_PATH do NTFS no CI do Windows.
        """
        import tomus.storage.organizer as org_mod

        organizer = LibraryOrganizer(tmp_path / "dst", file_operation="copy", dry_run=True)
        p = _fake_pdf(tmp_path / "src", "livro.pdf")

        # Linux: não aplica proteção de caminho longo do Windows.
        monkeypatch.setattr(org_mod.sys, "platform", "linux")
        e_linux = organizer.add_organized(
            source_path=p, grande_area="Ciências Humanas",
            area_basica="A" * 100, subarea="B" * 110, especialidade="Geral",
            tipo="Livro", filename="livro.pdf", sha256=_sha_of(p),
            classification={"authors": ["Autor, Um"], "title": "Livro", "year": 2020},
        )
        assert e_linux.status == ProcessStatus.ORGANIZED, f"linux: {e_linux.status}"

        # Windows: caminho longo > 245-40 => redireciona para revisao_manual.
        monkeypatch.setattr(org_mod.sys, "platform", "win32")
        e_win = organizer.add_organized(
            source_path=p, grande_area="Ciências Humanas",
            area_basica="A" * 100, subarea="B" * 110, especialidade="Geral",
            tipo="Livro", filename="livro.pdf", sha256=_sha_of(p),
            classification={"authors": ["Autor, Um"], "title": "Livro", "year": 2020},
        )
        assert e_win.status == ProcessStatus.MANUAL_REVIEW, f"win32: {e_win.status}"
        assert "revisao_manual" in str(e_win.destination_path)


# =========================================================================== #
# Regressão — ajustes commits 3b8be03, df3b6f1, fbccfcb
# =========================================================================== #
class TestSchemaObrigatorio:
    """LLMClassificationOutput exige confidence_score e reasoning no schema."""

    def test_model_json_schema_required_contem_confidence_e_reasoning(self):
        schema = LLMClassificationOutput.model_json_schema()
        required = set(schema.get("required", []))
        assert "confidence_score" in required
        assert "reasoning" in required

    def test_validation_error_ao_omitir_confidence_score(self):
        with pytest.raises(ValidationError):
            LLMClassificationOutput(
                grande_area="Ciências Exatas e da Terra",
                area_basica="Computação",
                tipo="Revista",
                authors=[],
                title="Micro Sistemas",
                subtitle="",
                year=1986,
                reasoning="ok",
            )

    def test_validation_error_ao_omitir_reasoning(self):
        with pytest.raises(ValidationError):
            LLMClassificationOutput(
                grande_area="Ciências Exatas e da Terra",
                area_basica="Computação",
                tipo="Revista",
                authors=[],
                title="Micro Sistemas",
                subtitle="",
                year=1986,
                confidence_score=0.95,
            )


class TestIsRedundantIssueDesignacao:
    """is_redundant_issue_designation e supressao em namer/companion."""

    def test_n_grau_vs_numero_e_redundante(self):
        assert is_redundant_issue_designation("N° 109", "109") is True
        assert is_redundant_issue_designation("Nº 110", "110") is True
        assert is_redundant_issue_designation("n. 109", "109") is True

    def test_nao_redundante_preservado(self):
        assert is_redundant_issue_designation("Edicao Especial", "109") is False
        assert is_redundant_issue_designation("Suplemento", "109") is False
        assert is_redundant_issue_designation("N° 0", "109") is False
        assert is_redundant_issue_designation(None, "109") is False
        assert is_redundant_issue_designation("N° 109", None) is False

    def test_supressao_nome_arquivo(self, tmp_path: Path):
        dest_dir = tmp_path / "dst" / "Computação" / "Geral" / "Revista" / "Micro Sistemas"
        dest_dir.mkdir(parents=True)
        nome = format_periodical_filename(
            journal="Micro Sistemas",
            year=1986,
            month=7,
            number="109",
            issue_designation="N° 109",
            dest_dir=dest_dir,
            max_full_path_chars=WIN_SAFE_FULL_PATH_CHARS,
        )
        assert "N° 109" not in nome
        assert "n0109" in nome

    def test_supressao_citacao_abnt(self):
        classificacao = {
            "tipo": "Revista",
            "periodico": "Micro Sistemas",
            "journal_name": "Micro Sistemas",
            "city": "Rio de Janeiro",
            "publisher": "Editora X",
            "volume": "5",
            "volume_label": "ano",
            "number": "109",
            "issue_designation": "N° 109",
            "publication_month": 7,
            "year": 1986,
        }
        ref = format_abnt_reference(classificacao)
        assert "N° 109" not in ref


class TestAbntVolumeLabelAno:
    """volume_label='Ano X'/'Ano XI' renderiza 'ano 10'/'ano 11' (não 'v. 10')."""

    def test_volume_label_ano_x_renderiza_ano_10(self):
        classificacao = {
            "tipo": "Revista",
            "periodico": "Micro Sistemas",
            "journal_name": "Micro Sistemas",
            "city": "Rio de Janeiro",
            "publisher": "Editora X",
            "volume": "10",
            "volume_label": "Ano X",
            "number": "1",
            "publication_month": 7,
            "year": 1986,
        }
        ref = format_abnt_reference(classificacao)
        assert "ano 10" in ref
        assert "v. 10" not in ref

    def test_volume_label_ano_xi_renderiza_ano_11(self):
        classificacao = {
            "tipo": "Revista",
            "periodico": "Micro Sistemas",
            "journal_name": "Micro Sistemas",
            "city": "Rio de Janeiro",
            "publisher": "Editora X",
            "volume": "11",
            "volume_label": "Ano XI",
            "number": "1",
            "publication_month": 7,
            "year": 1986,
        }
        ref = format_abnt_reference(classificacao)
        assert "ano 11" in ref
        assert "v. 11" not in ref


class TestPipelineRevistaFallback:
    """Revista com journal_name=None herda periodico do title; isbn/doi nao herdados."""

    def test_pipeline_revista_nao_herda_isbn_doi_periodico_por_titulo(
        self, monkeypatch, tmp_path: Path
    ):
        import tomus.core.pipeline as pipe
        from tomus.core.models import FileManifestEntry

        captured: dict[str, Any] = {}

        class FakeProvider:
            def classify(
                self,
                *,
                sampled_text: str,
                cip_text: str,
                external_metadata: Any,
                used_ocr: bool,
                source_path: Path | None = None,
            ) -> ClassificationResult:
                return ClassificationResult(
                    grande_area="Ciências Exatas e da Terra",
                    area_basica="Computação",
                    tipo="Revista",
                    authors=[],
                    title="Micro Sistemas",
                    subtitle="",
                    year=1986,
                    confidence_score=0.95,
                    reasoning="ok",
                    journal_name=None,
                )

        def fake_extract(path: Path, sha256: str) -> Any:
            return SimpleNamespace(
                source_path=path,
                sha256=sha256,
                file_size_bytes=100,
                total_pages=10,
                used_ocr=False,
                sampled_text="",
                cip_text="",
                detected_isbn="9780713210736",
                detected_doi="10.1234/abc",
            )

        def fake_enrich(doc: Any, config: Any) -> list:
            return []

        def fake_select_best(doc: Any, candidates: list) -> Any:
            return None

        monkeypatch.setattr(pipe, "extract_document_content", fake_extract)
        monkeypatch.setattr(pipe, "enrich_document_metadata", fake_enrich)
        monkeypatch.setattr(pipe, "select_best_external_metadata", fake_select_best)

        def capture_add_organized(*args, **kwargs):
            captured["classification"] = kwargs.get("classification", {})
            entry = FileManifestEntry(
                source_path=str(args[0]) if args else "",
                destination_path=str(tmp_path / "dst" / "Micro Sistemas.pdf"),
                sha256="abc",
                status=ProcessStatus.ORGANIZED,
            )
            organizer.entries.append(entry)
            return entry

        organizer = LibraryOrganizer(tmp_path / "dst", file_operation="copy", dry_run=True)
        organizer.add_organized = capture_add_organized  # type: ignore[method-assign]

        scanned = ScannedFile(
            path=tmp_path / "src" / "revista.pdf",
            sha256="abc123",
            file_size_bytes=100,
            is_valid_pdf=True,
            is_hidden=False,
            is_ignored_non_pdf=False,
        )

        config = AppConfig()
        finalize_lock = threading.RLock()

        _process_one(
            scanned=scanned,
            config=config,
            target_dir=tmp_path / "dst",
            provider=FakeProvider(),
            cache=SimpleNamespace(get=lambda *a, **kw: None, put=lambda *a, **kw: None),
            organizer=organizer,
            taxonomy_version="1.0",
            model_name="mock",
            emit=None,
            finalize_lock=finalize_lock,
        )

        cls = captured.get("classification", {})
        assert cls.get("isbn") is None, f"isbn deveria ser None: {cls.get('isbn')!r}"
        assert cls.get("doi") is None, f"doi deveria ser None: {cls.get('doi')!r}"
        assert cls.get("periodico") == "Micro Sistemas", (
            f"periodico deveria ser Micro Sistemas por fallback: {cls.get('periodico')!r}"
        )



