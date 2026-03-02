"""
Pydantic models for MCP Server tool inputs and outputs.

These models provide type-safe interfaces for all MCP tools,
matching the Postgres schema custom types and function signatures.

Enum classes (DocType, SlideIntent, etc.) have been removed.
Valid values are loaded from pg_enum at startup via src.config.VALID_ENUMS.
"""

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# -----------------------------------------------------------------------------
# Intent-to-Type Mapping (DB read-through cache)
# -----------------------------------------------------------------------------


@dataclass
class IntentTypeInfo:
    slide_type: str
    require_image: bool
    sort_order: int = 0
    suggested_title: str = ""
    requirements: str = ""
    is_generatable: bool = True
    related_intents: list[str] = field(default_factory=list)


INTENT_TYPE_MAP: dict[str, IntentTypeInfo] = {}


async def load_intent_type_map() -> dict[str, IntentTypeInfo]:
    """Load intent-to-slide-type mapping from Postgres.

    Called once at orchestrator startup. The DB table is the single
    source of truth; this dict is a read-through cache for prompt
    selection and image search gating.
    """
    global INTENT_TYPE_MAP
    from src.db import get_connection

    async with get_connection() as conn:
        rows = await conn.fetch(
            "SELECT intent::text, slide_type::text, require_image, "
            "sort_order, suggested_title, requirements, is_generatable, "
            "COALESCE(related_intents, '{}') AS related_intents "
            "FROM intent_type_map "
            "ORDER BY sort_order"
        )
        INTENT_TYPE_MAP.clear()
        INTENT_TYPE_MAP.update({
            row["intent"]: IntentTypeInfo(
                slide_type=row["slide_type"],
                require_image=row["require_image"],
                sort_order=row["sort_order"],
                suggested_title=row["suggested_title"],
                requirements=row["requirements"],
                is_generatable=row["is_generatable"],
                related_intents=list(row["related_intents"]),
            )
            for row in rows
        })
    return INTENT_TYPE_MAP


def get_slide_type(intent: str) -> str:
    """Look up slide type for an intent, defaulting to 'bullets'."""
    info = INTENT_TYPE_MAP.get(intent)
    return info.slide_type if info else "bullets"


def should_select_image(intent: str) -> bool:
    """Check if this intent's slide type requires an image."""
    info = INTENT_TYPE_MAP.get(intent)
    return info.require_image if info else False


def extract_slide_text(draft: dict) -> list[str]:
    """Return meaningful text segments from any slide type.
    
    Used by grounding (embed each item), novelty (" ".join()),
    and image search (" ".join()) as a drop-in for bullets.
    
    Falls back to draft["bullets"] when the type-specific content_data
    fields are empty (e.g. LLM produced generic bullets format despite
    slide_type being overridden).
    """
    slide_type = draft.get("slide_type", "bullets")
    cd = draft.get("content_data") or {}
    title = draft.get("title", "")

    result: list[str] = []
    if slide_type == "statement":
        parts = [cd.get("statement", ""), cd.get("subtitle", "")]
        result = [p for p in parts if p]
    elif slide_type == "split":
        left_title = cd.get("left_title", "")
        right_title = cd.get("right_title", "")
        left = [f"{title} – {left_title}: {item}" for item in cd.get("left_items", []) if item]
        right = [f"{title} – {right_title}: {item}" for item in cd.get("right_items", []) if item]
        result = left + right
    elif slide_type == "flow":
        # Prefix with title so short step labels embed better against source chunks
        result = [
            f"{title}: {s.get('label', '')} – {s.get('caption', '')}".strip()
            for s in cd.get("steps", [])
        ]
    elif slide_type == "code":
        result = cd.get("explain_bullets", []) + [cd.get("code_block", "")]
        result = [r for r in result if r]
    elif slide_type == "diagram":
        # Prefix with title so short callouts embed better against source chunks
        callouts = cd.get("callouts", [])
        result = [f"{title}: {c}" for c in callouts if c]
        caption = cd.get("caption", "")
        if caption:
            result.append(caption)
    else:
        result = draft.get("bullets", [])

    if not result and draft.get("bullets"):
        result = draft.get("bullets", [])

    return result


STATIC_SLIDES: dict[str, dict] = {}


async def load_static_slides() -> dict[str, dict]:
    """Load static slides (title, thanks) from Postgres.

    Returns dict keyed by intent string with full row data.
    Called once at startup; cached for the duration of the run.
    """
    global STATIC_SLIDES
    from src.db import get_connection

    async with get_connection() as conn:
        rows = await conn.fetch(
            "SELECT intent::text, title, subtitle, slide_type::text, "
            "bullets, content_data, speaker_notes, "
            "speaker, job_title, company, company_url, event, "
            "image_path, image_alt "
            "FROM static_slide"
        )
        STATIC_SLIDES.clear()
        STATIC_SLIDES.update({
            row["intent"]: {
                "intent": row["intent"],
                "title": row["title"],
                "subtitle": row["subtitle"] or "",
                "slide_type": row["slide_type"],
                "bullets": json.loads(row["bullets"]) if row["bullets"] else [],
                "content_data": json.loads(row["content_data"]) if row["content_data"] else {},
                "speaker_notes": row["speaker_notes"] or "",
                "speaker": row["speaker"] or "",
                "job_title": row["job_title"] or "",
                "company": row["company"] or "",
                "company_url": row["company_url"] or "",
                "event": row["event"] or "",
                "image_path": row["image_path"] or "",
                "image_alt": row["image_alt"] or "",
            }
            for row in rows
        })
    return STATIC_SLIDES


SECTION_DIVIDERS_CACHE: list[dict] = []


async def load_section_dividers() -> list[dict]:
    """Load section dividers from Postgres, sorted by sort_order.

    Returns list of dicts with after_intent, title, subtitle, image_filename.
    Called once at startup; cached for the duration of the run.
    """
    global SECTION_DIVIDERS_CACHE
    from src.db import get_connection

    async with get_connection() as conn:
        rows = await conn.fetch(
            "SELECT after_intent::text, title, subtitle, image_filename, sort_order "
            "FROM section_divider "
            "ORDER BY sort_order"
        )
        SECTION_DIVIDERS_CACHE.clear()
        SECTION_DIVIDERS_CACHE.extend([
            {
                "after_intent": row["after_intent"],
                "title": row["title"],
                "subtitle": row["subtitle"] or "",
                "image_filename": row["image_filename"] or "",
                "sort_order": row["sort_order"],
            }
            for row in rows
        ])
    return SECTION_DIVIDERS_CACHE


THEMES_CACHE: dict[str, dict] = {}


async def load_themes() -> dict[str, dict]:
    """Load theme configurations from Postgres.

    Returns dict keyed by theme name with display_name, css_overrides, is_active.
    Only active themes are loaded. Called once at startup; cached for the run.
    """
    global THEMES_CACHE
    from src.db import get_connection

    async with get_connection() as conn:
        rows = await conn.fetch(
            "SELECT name, display_name, css_overrides, is_active "
            "FROM theme "
            "WHERE is_active = true"
        )
        THEMES_CACHE.clear()
        THEMES_CACHE.update({
            row["name"]: {
                "name": row["name"],
                "display_name": row["display_name"],
                "css_overrides": row["css_overrides"],
                "is_active": row["is_active"],
            }
            for row in rows
        })
    return THEMES_CACHE


SLIDE_TYPE_CONFIGS: dict[str, dict] = {}


async def load_slide_type_configs() -> dict[str, dict]:
    """Load slide type configurations from Postgres.

    Returns dict keyed by slide_type string with prompt_schema, content_fields.
    Called once at startup; cached for the duration of the run.
    """
    global SLIDE_TYPE_CONFIGS
    from src.db import get_connection

    async with get_connection() as conn:
        rows = await conn.fetch(
            "SELECT slide_type::text, prompt_schema, content_fields, html_fragment "
            "FROM slide_type_config"
        )
        SLIDE_TYPE_CONFIGS.clear()
        SLIDE_TYPE_CONFIGS.update({
            row["slide_type"]: {
                "slide_type": row["slide_type"],
                "prompt_schema": row["prompt_schema"],
                "content_fields": json.loads(row["content_fields"])
                    if isinstance(row["content_fields"], str)
                    else dict(row["content_fields"]),
                "html_fragment": row["html_fragment"],
            }
            for row in rows
        })
    return SLIDE_TYPE_CONFIGS


PROMPT_TEMPLATES: dict[str, dict] = {}


async def load_prompt_templates() -> dict[str, dict]:
    """Load active prompt templates from Postgres.

    Returns dict keyed by purpose string with system_prompt, user_prompt.
    Only active templates loaded (partial unique index ensures one per purpose).
    Called once at startup; cached for the duration of the run.
    """
    global PROMPT_TEMPLATES
    from src.db import get_connection

    async with get_connection() as conn:
        rows = await conn.fetch(
            "SELECT purpose, version, system_prompt, user_prompt "
            "FROM prompt_template "
            "WHERE is_active = true"
        )
        PROMPT_TEMPLATES.clear()
        PROMPT_TEMPLATES.update({
            row["purpose"]: {
                "purpose": row["purpose"],
                "version": row["version"],
                "system_prompt": row["system_prompt"],
                "user_prompt": row["user_prompt"],
            }
            for row in rows
        })
    return PROMPT_TEMPLATES


class ImageMetadata(BaseModel):
    """Validator for image JSON sidecar files."""
    caption: str = Field(..., min_length=10, description="Descriptive caption")
    alt_text: str = Field(..., min_length=5, description="Accessibility text")
    use_cases: list[str] = Field(default_factory=list)
    license: str = Field(..., min_length=2, description="License (required)")
    attribution: str = Field(..., min_length=2, description="Attribution (required)")
    style: Optional[str] = None

    @field_validator("style")
    @classmethod
    def validate_style(cls, v):
        if v is None:
            return v
        from src.config import VALID_ENUMS
        valid = VALID_ENUMS.get("image_style", set())
        if valid and v not in valid:
            raise ValueError(f"Invalid image style: {v}")
        return v


class ImageAsset(BaseModel):
    """Database representation of an image."""
    image_id: UUID
    doc_id: UUID
    storage_path: str
    caption: str
    alt_text: str
    use_cases: list[str]
    license: str
    attribution: str
    style: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None


class ImageSearchResult(BaseModel):
    """Result from image search."""
    image_id: UUID
    storage_path: str
    caption: str
    alt_text: str
    use_cases: list[str]
    style: Optional[str] = None
    similarity: float


class ImageFilters(BaseModel):
    """Filters for image search."""
    use_cases: Optional[list[str]] = None
    style: Optional[str] = None
    min_score: float = 0.5


# -----------------------------------------------------------------------------
# Input Models (Tool Parameters)
# -----------------------------------------------------------------------------


class SearchFilters(BaseModel):
    """Filters for hybrid search."""
    doc_type: Optional[str] = Field(default=None, description="Filter by document type")
    trust_level: Optional[str] = Field(default=None, description="Filter by trust level")
    tags: Optional[list[str]] = Field(default=None, description="Filter by tags (any match)")

    @field_validator("doc_type")
    @classmethod
    def validate_doc_type(cls, v):
        if v is None:
            return v
        from src.config import VALID_ENUMS
        valid = VALID_ENUMS.get("doc_type", set())
        if valid and v not in valid:
            raise ValueError(f"Invalid doc_type: {v}")
        return v

    @field_validator("trust_level")
    @classmethod
    def validate_trust_level(cls, v):
        if v is None:
            return v
        from src.config import VALID_ENUMS
        valid = VALID_ENUMS.get("trust_level", set())
        if valid and v not in valid:
            raise ValueError(f"Invalid trust_level: {v}")
        return v


class SlideSpec(BaseModel):
    """Specification for a slide."""
    intent: str = Field(..., description="Purpose of the slide")
    title: str = Field(..., description="Slide title")
    slide_type: str = Field(default="bullets", description="Slide layout type")
    bullets: list[str] = Field(default_factory=list, description="Bullet points (2-3 items)")
    content_data: Optional[dict] = Field(default=None, description="Type-specific content data")
    speaker_notes: Optional[str] = Field(default=None, description="Speaker notes for presenter")
    citations: list[dict] = Field(default_factory=list, description="Source citations [{chunk_id, title, url}]")
    image_id: Optional[UUID] = Field(default=None, description="Optional image asset ID")

    @field_validator("intent")
    @classmethod
    def validate_intent(cls, v):
        from src.config import VALID_ENUMS
        valid = VALID_ENUMS.get("slide_intent", set())
        if valid and v not in valid:
            raise ValueError(f"Invalid intent: {v}")
        return v

    @field_validator("slide_type")
    @classmethod
    def validate_slide_type(cls, v):
        from src.config import VALID_ENUMS
        valid = VALID_ENUMS.get("slide_type", set())
        if valid and v not in valid:
            raise ValueError(f"Invalid slide_type: {v}")
        return v


class StyleContract(BaseModel):
    """Style configuration for deck generation."""
    tone: Optional[str] = Field(default="technical", description="Presentation tone")
    audience: Optional[str] = Field(default="developers", description="Target audience")
    bullet_style: Optional[str] = Field(default="concise", description="Bullet point style")


# -----------------------------------------------------------------------------
# Output Models (Tool Results)
# -----------------------------------------------------------------------------


class ChunkResult(BaseModel):
    """Result from hybrid search."""
    chunk_id: UUID
    doc_id: UUID
    content: str
    doc_title: str
    trust_level: str
    semantic_score: float
    lexical_score: float
    combined_score: float
    semantic_rank: int
    lexical_rank: int


class ChunkDetail(BaseModel):
    """Detailed chunk information."""
    chunk_id: UUID
    doc_id: UUID
    content: str
    content_hash: str
    section_header: Optional[str]
    token_count: Optional[int]
    doc_title: str
    doc_type: str
    trust_level: str
    tags: list[str]


class NoveltyResult(BaseModel):
    """Result from novelty check."""
    is_novel: bool
    max_similarity: float
    most_similar_slide_no: Optional[int]
    most_similar_intent: Optional[str]


class GroundingResult(BaseModel):
    """Result from grounding check."""
    is_grounded: bool
    ungrounded_bullets: list[int]
    min_similarity: float
    grounding_details: list[dict]


class ValidationResult(BaseModel):
    """Result from structure/citation validation."""
    is_valid: bool
    errors: list[str]


class CitationValidationResult(BaseModel):
    """Result from citation validation."""
    is_valid: bool
    citation_count: int
    errors: list[str]


class CommitResult(BaseModel):
    """Result from slide commit."""
    success: bool
    slide_id: Optional[UUID]
    errors: list[str]


class DeckState(BaseModel):
    """Current state of a deck."""
    deck: dict
    coverage: dict
    health: dict
    slides: Optional[list[dict]]


class RunReport(BaseModel):
    """Comprehensive report for a deck generation run."""
    deck_id: UUID
    generated_at: str
    summary: dict
    coverage: dict
    gate_summary: Optional[dict]
    top_failure_reasons: Optional[list[dict]]
    slides: Optional[list[dict]]


# -----------------------------------------------------------------------------
# Error Models
# -----------------------------------------------------------------------------


class MCPError(BaseModel):
    """Standard error response."""
    error: str
    code: str
    details: Optional[dict] = None


# -----------------------------------------------------------------------------
# Orchestrator State Models
# -----------------------------------------------------------------------------


class SlideStatus(str, Enum):
    """Status of a slide in the generation process."""
    PENDING = "pending"
    GENERATING = "generating"
    VALIDATING = "validating"
    COMMITTED = "committed"
    FAILED = "failed"
    NEEDS_MANUAL_REVIEW = "needs_manual_review"


class GateResult(BaseModel):
    """Result of a gate validation."""
    gate_name: str
    passed: bool
    score: Optional[float] = None
    errors: list[str] = Field(default_factory=list)
    details: Optional[dict] = None

    @field_validator("gate_name")
    @classmethod
    def validate_gate_name(cls, v):
        from src.config import VALID_GATE_NAMES
        if VALID_GATE_NAMES and v not in VALID_GATE_NAMES:
            raise ValueError(f"Invalid gate_name: {v}")
        return v


class SlideGenerationState(BaseModel):
    """State for a single slide being generated."""
    intent: str
    slide_no: int
    status: SlideStatus = SlideStatus.PENDING
    retries: int = 0
    chunks: list[dict] = Field(default_factory=list)
    draft: Optional[dict] = None
    gate_results: list[GateResult] = Field(default_factory=list)
    error: Optional[str] = None


class OrchestratorState(BaseModel):
    """
    Complete state for the slide generation orchestrator.
    
    This is the central state object that flows through the LangGraph state machine.
    """
    # Deck identification
    deck_id: str
    run_id: Optional[str] = None
    
    # Overridden at runtime by get_target_slides() which reads from DB
    target_slides: int = 15
    max_retries_per_slide: int = 3
    max_total_retries: int = 20
    
    # Current position
    current_intent: Optional[str] = None
    current_slide_no: int = 0
    
    # Tracking
    prior_titles: list[str] = Field(default_factory=list)
    generated_slides: list[str] = Field(default_factory=list)  # List of intents completed
    failed_intents: list[str] = Field(default_factory=list)
    
    # Retry counters
    slide_retries: int = 0
    total_retries: int = 0
    
    # Current slide state
    current_chunks: list[dict] = Field(default_factory=list)
    current_draft: Optional[dict] = None
    current_gate_results: list[GateResult] = Field(default_factory=list)
    
    # Completion flags
    is_complete: bool = False
    error: Optional[str] = None
    
    # Run metrics
    llm_calls: int = 0
    embeddings_generated: int = 0
    
    class Config:
        """Allow arbitrary types for flexibility."""
        arbitrary_types_allowed = True
