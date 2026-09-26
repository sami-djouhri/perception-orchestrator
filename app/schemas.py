"""Pydantic-Schemas v1 für Perception-Pipeline.

Quelle der Wahrheit: docs/jetson-nano/04-datenmodell-json.md
Breaking Changes -> v2-Modul parallel anlegen, dieses Modul nicht modifizieren.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

SchemaVersion = Literal["v1"]
JobKind = Literal[
    "image", "screenshot", "document", "quality", "compare", "embed", "preprocess"
]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


class ExecMeta(BaseModel):
    host: str
    started_at: datetime
    finished_at: datetime
    exec_ms: int = Field(ge=0)
    model_versions: dict[str, str] = Field(default_factory=dict)


class ConfidentField(BaseModel):
    value: str | float | int | None = None
    confidence: Confidence = 0.0


class OcrPayload(BaseModel):
    text: str
    lang: str = "deu"
    confidence_avg: Confidence = 0.0
    page_count: int = 1
    blocks: list[dict] = Field(default_factory=list)


class ImageResult(BaseModel):
    image_kind: Literal[
        "photo", "product", "hardware", "diagram", "chart", "art", "other"
    ]
    tags: list[str] = Field(default_factory=list)
    objects: list[dict] = Field(default_factory=list)
    short_caption: str = ""
    ocr: OcrPayload | None = None
    exif: dict | None = None


class ScreenshotResult(BaseModel):
    screenshot_kind: Literal[
        "terminal",
        "home_assistant",
        "shop",
        "error_dialog",
        "chat",
        "browser",
        "code_editor",
        "other",
    ]
    ocr: OcrPayload
    ui_hints: dict = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    summary: str = ""


class DocumentMetadata(BaseModel):
    absender: ConfidentField = Field(default_factory=ConfidentField)
    datum: ConfidentField = Field(default_factory=ConfidentField)
    frist: ConfidentField = Field(default_factory=ConfidentField)
    aktenzeichen: ConfidentField = Field(default_factory=ConfidentField)
    rechnungsnummer: ConfidentField = Field(default_factory=ConfidentField)
    betrag_eur: ConfidentField = Field(default_factory=ConfidentField)
    prioritaet: ConfidentField = Field(default_factory=ConfidentField)


class SortSuggestion(BaseModel):
    target_path: str
    confidence: Confidence


class DocumentResult(BaseModel):
    document_kind: Literal[
        "rechnung",
        "mahnung",
        "behoerde",
        "bank",
        "versicherung",
        "arzt",
        "vertrag",
        "arbeit",
        "ihk_schule",
        "steuer",
        "sonstiges",
    ]
    kind_confidence: Confidence
    metadata: DocumentMetadata = Field(default_factory=DocumentMetadata)
    ocr: OcrPayload
    summary: str = ""
    tags: list[str] = Field(default_factory=list)
    sort_suggestion: SortSuggestion | None = None


class QualityResult(BaseModel):
    sharpness: Confidence
    exposure: Literal["ok", "under", "over"]
    is_screenshot: bool
    kind: Literal["photo", "screenshot", "scan", "graphic", "unknown"]
    issues: list[str] = Field(default_factory=list)
    recommend_action: Literal["keep", "review", "low_quality"]


class ComparePair(BaseModel):
    a_sha: str
    b_sha: str
    distance: float
    similarity: Confidence
    verdict: Literal["identical", "near_duplicate", "similar", "different"]
    best_pick_sha: str | None = None
    reason: str = ""


class CompareResult(BaseModel):
    pairs: list[ComparePair]


class EmbedResult(BaseModel):
    model: str
    dim: int
    embedding: list[float]


class PerceptionEnvelope(BaseModel):
    """Wrapper, den Nano in JEDER Antwort liefert."""

    model_config = ConfigDict(extra="forbid")

    schema_version: SchemaVersion = "v1"
    kind: JobKind
    job_id: str
    sha256: str
    source_path: str
    exec: ExecMeta
    result: dict
    warnings: list[str] = Field(default_factory=list)
    review_required: bool = False
    review_reasons: list[str] = Field(default_factory=list)


# --- Review-Eintrag (Pi-DB) ---


class ReviewEntry(BaseModel):
    review_id: str
    sha256: str
    kind: JobKind
    reasons: list[str]
    proposed_action: str
    proposed_target: str | None = None
    created_at: datetime
    status: Literal["open", "approved", "rejected", "changed"] = "open"
    reviewer: str | None = None
