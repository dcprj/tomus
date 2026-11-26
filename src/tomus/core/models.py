"""Entidades de domínio e contratos de dados do Tomus (Seção 3 do design)."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DocumentType(str, Enum):
    """Tipos documentais fechados do Tomus."""

    LIVRO = "Livro"
    REVISTA = "Revista"
    # Alias de compatibilidade: emitia "Revista Científica" anteriormente.
    REVISTA_CIENTIFICA = "Revista"
    ARTIGO = "Artigo"
    TESE_DISSERTACAO = "Tese_Dissertacao"
    OUTROS = "Outros"

    @classmethod
    def _missing_(cls, value: object) -> DocumentType:
        """Coerção retrocompatível na desserialização do enum.

        Aceita tanto o valor canônico ``Revista`` quanto o legado
        ``Revista Científica`` (e variações de acento/caixa), mapeando para
        ``REVISTA``. Outros valores desconhecidos levantam ValueError como de
        costume.
        """
        if isinstance(value, str):
            t = value.strip().lower()
            if t in ("revista", "revista científica", "revista cientifica", "periodico", "periódico"):
                return cls.REVISTA
            if t in ("tese/dissertacao", "tese_dissertacao"):
                return cls.TESE_DISSERTACAO
        return super()._missing_(value)

    def __str__(self) -> str:
        return self.value


class ProcessStatus(str, Enum):
    """Status de processamento de um arquivo no manifesto."""

    ORGANIZED = "organized"
    MANUAL_REVIEW = "manual_review"
    DUPLICATE_SKIPPED = "duplicate_skipped"
    # DUPLICATE e DUPLICATE_SKIPPED compartilham o mesmo valor persistido
    # ("duplicate_skipped"). DUPLICATE é um alias semântico mantido por
    # retrocompatibilidade; NUNCA é gravado sozinho (sempre se usa
    # ProcessStatus.DUPLICATE_SKIPPED.value na persistência). Não há alteração
    # de valor persistido e, portanto, não é necessária migração de dados nem
    # de manifesto/front matter. Qualquer leitura de "duplicate_skipped" mapeia
    # para DUPLICATE_SKIPPED (primeiro membro definido com esse valor).
    DUPLICATE = "duplicate_skipped"
    OBSOLETE = "obsolete"            # edição antiga movida para obsoletos/
    IGNORED_NON_PDF = "ignored_non_pdf"
    ERROR = "error"


class FileOperation(str, Enum):
    """Operação de sistema de arquivos."""

    COPY = "copy"
    MOVE = "move"


class ExtractedDocument(BaseModel):
    """Resultado da leitura local do PDF (Stage 1 e Stage 2)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    source_path: Path
    sha256: str
    file_size_bytes: int
    total_pages: int
    used_ocr: bool = False
    native_metadata: dict[str, Any] = Field(default_factory=dict)
    sampled_text: str = ""
    cip_text: str = ""
    detected_doi: str | None = None
    detected_isbn: str | None = None


class ExternalMetadata(BaseModel):
    """Metadados recuperados e validados do OpenAlex ou Google Books (Stage 3)."""

    source: str  # "openalex" | "google_books"
    title: str = ""
    subtitle: str = ""
    authors: list[str] = Field(default_factory=list)
    publication_year: int | None = None
    publisher: str | None = None
    city: str | None = None
    edition: str | None = None
    journal_name: str | None = None
    volume: str | None = None
    number: str | None = None
    pages: str | None = None
    doi: str | None = None
    isbn: str | None = None
    document_type_hint: str | None = None
    concepts: list[str] = Field(default_factory=list)
    match_score: float = 0.0
    match_origin: str = Field(
        default="text_search",
        description="Origem do casamento externo: exact_doi, exact_isbn ou text_search",
    )
    # Campos opcionais para fascículos de revista (PR #14).
    publication_month: int | None = None
    publication_month_end: int | None = None
    publication_year_end: int | None = None
    issn: str | None = None
    journal_genre: str | None = None
    volume_label: str | None = None
    issue_designation: str | None = None
    serial_evidence: str | None = None


class LLMClassificationOutput(BaseModel):
    """Contrato de saída estruturada do LLM validado contra a tabela CAPES/CNPq (Stage 4)."""

    grande_area: str
    area_basica: str
    subarea: str = ""
    especialidade: str = ""
    tipo: DocumentType
    authors: list[str] = Field(default_factory=list)
    title: str = ""
    subtitle: str = ""
    year: int | None = None
    publisher: str | None = None
    city: str | None = None
    edition: str | None = None
    journal_name: str | None = None
    volume: str | None = None
    number: str | None = None
    pages: str | None = None
    doi: str | None = None
    isbn: str | None = None
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    reasoning: str = Field(...)
    # Campos opcionais para fascículos de revista (PR #14).
    publication_month: int | None = None
    publication_month_end: int | None = None
    publication_year_end: int | None = None
    issn: str | None = None
    journal_genre: str | None = None
    volume_label: str | None = None
    issue_designation: str | None = None
    serial_evidence: str | None = None

    @field_validator("tipo", mode="before")
    @classmethod
    def _normalize_tipo(cls, v: Any) -> DocumentType:
        """Normaliza tipos documentais para os valores do catálogo fechado."""
        if isinstance(v, DocumentType):
            return v
        if not isinstance(v, str):
            return v
        t = v.strip().lower()
        if t in ("revista", "revista científica", "revista cientifica", "periódico", "periodico"):
            return DocumentType.REVISTA
        if t in ("tese", "dissertação", "tcc", "monografia"):
            return DocumentType.TESE_DISSERTACAO
        return v


class FileManifestEntry(BaseModel):
    """Registro individual auditável gravado em manifest.json (Stage 5)."""

    source_path: str
    destination_path: str | None = None
    sha256: str
    status: ProcessStatus
    used_ocr: bool = False
    classification: dict[str, Any] | None = None
    error_message: str | None = None


class ExecutionSummary(BaseModel):
    """Envelope raiz gravado em manifest.json e exibido ao final da CLI."""

    total_scanned: int = 0
    organized_count: int = 0
    manual_review_count: int = 0
    duplicate_skipped_count: int = 0
    obsolete_count: int = 0
    ignored_non_pdf_count: int = 0
    error_count: int = 0
    manual_review_ratio: float = 0.0
    exceeded_manual_review_ceiling: bool = False
    entries: list[FileManifestEntry] = Field(default_factory=list)


class PipelineEvent(BaseModel):
    """Evento emitido pelo orquestrador para atualizar a interface (CLI/futura GUI)."""

    stage: str
    source_path: str
    destination_path: str | None = None
    sha256: str | None = None
    status: str
    message: str
    total_files: int | None = None
    completed_files: int | None = None
    classification: dict[str, Any] | None = None
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
