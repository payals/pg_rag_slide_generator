"""
LLM Client for slide generation (model from Postgres config table).

Wraps OpenAI API with:
- Prompt formatting using templates from PROMPT_TEMPLATES.md
- JSON response parsing with validation
- Retry logic with exponential backoff
- Error handling for common failure modes
"""

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Optional

import httpx
from openai import AsyncOpenAI, APIError, RateLimitError, APIConnectionError

from src.content_utils import walk_content_data
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from src.models import SlideSpec, get_slide_type, INTENT_TYPE_MAP, SLIDE_TYPE_CONFIGS, PROMPT_TEMPLATES


# =============================================================================
# LLM RESPONSE DATACLASS (for cost tracking)
# =============================================================================

@dataclass
class LLMResponse:
    """Structured response from call_llm() that preserves token usage for cost tracking.
    
    Note: If tenacity retries on rate limit, intermediate failed attempts are billed
    by OpenAI but their usage is lost (tenacity returns only the final successful call).
    Acceptable for demo accuracy.
    """
    text: str
    prompt_tokens: int
    completion_tokens: int

# Configure logging
logger = logging.getLogger(__name__)

# Secrets/infra from env
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE")
OPENAI_USER = os.getenv("OPENAI_USER")
SSL_VERIFY = os.getenv("SSL_VERIFY", "true").lower() != "false"

# Operational config loaded from Postgres via src.config
from src import config

# Import get_target_slides from renderer (DB-backed)
from src.renderer import get_target_slides

# LLM client singleton
_llm_client: Optional[AsyncOpenAI] = None


async def get_llm_client() -> AsyncOpenAI:
    """Get or create the async OpenAI client for chat completions."""
    global _llm_client
    
    if _llm_client is None:
        if not OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY environment variable not set")
        
        http_client = None if SSL_VERIFY else httpx.AsyncClient(verify=False)
        client_kwargs = {"api_key": OPENAI_API_KEY}
        if OPENAI_API_BASE:
            client_kwargs["base_url"] = OPENAI_API_BASE
        if http_client:
            client_kwargs["http_client"] = http_client
        
        _llm_client = AsyncOpenAI(**client_kwargs)
    
    return _llm_client




def _get_output_schema_for_type(slide_type: str) -> str:
    """Return the prompt schema for the given slide type from DB cache.

    Falls back to bullets schema if the type is not found.
    """
    config = SLIDE_TYPE_CONFIGS.get(slide_type)
    if config:
        return config["prompt_schema"]
    bullets_config = SLIDE_TYPE_CONFIGS.get("bullets")
    if bullets_config:
        return bullets_config["prompt_schema"]
    return ""


def _get_prompt_template(purpose: str) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) for the given purpose from DB cache.

    Raises KeyError if purpose not found and PROMPT_TEMPLATES is populated.
    Returns empty strings if PROMPT_TEMPLATES is empty (pre-startup).
    """
    tmpl = PROMPT_TEMPLATES.get(purpose)
    if tmpl:
        return tmpl["system_prompt"], tmpl["user_prompt"]
    if PROMPT_TEMPLATES:
        raise KeyError(f"No active prompt template for purpose '{purpose}'")
    return "", ""


# =============================================================================
# RESPONSE PARSING
# =============================================================================

class LLMError(Exception):
    """Base exception for LLM errors."""
    pass


class InsufficientContextError(LLMError):
    """LLM reported insufficient context to generate slide."""
    def __init__(self, missing: str):
        self.missing = missing
        super().__init__(f"Insufficient context: {missing}")


class ParseError(LLMError):
    """Failed to parse LLM response as JSON."""
    def __init__(self, raw_response: str, error: str):
        self.raw_response = raw_response
        self.error = error
        super().__init__(f"Parse error: {error}")


_INLINE_CITATION_RE = re.compile(
    r"\s*\[[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}\]",
    re.IGNORECASE,
)


def strip_inline_citations(text: str) -> str:
    """Remove [uuid] citation references the LLM embeds in visible text."""
    return _INLINE_CITATION_RE.sub("", text).rstrip()


def _clean_slide_text(data: dict) -> dict:
    """Strip inline citation UUIDs from all visible slide text fields."""
    if "bullets" in data and isinstance(data["bullets"], list):
        data["bullets"] = [strip_inline_citations(b) for b in data["bullets"]]

    if "speaker_notes" in data and isinstance(data["speaker_notes"], str):
        data["speaker_notes"] = strip_inline_citations(data["speaker_notes"])

    cd = data.get("content_data")
    if isinstance(cd, dict):
        walk_content_data(cd, strip_inline_citations)

    return data


def parse_slide_response(response_text: str) -> dict:
    """
    Parse LLM response into slide spec dict.
    
    Raises:
        InsufficientContextError: If LLM reported insufficient context
        ParseError: If response is not valid JSON
    """
    text = response_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ParseError(response_text, str(e))
    
    if "error" in data:
        if data["error"] == "INSUFFICIENT_CONTEXT":
            raise InsufficientContextError(data.get("missing", "unknown"))
        raise LLMError(f"LLM error: {data['error']}")
    
    required_fields = ["title", "intent"]
    if data.get("slide_type", "bullets") == "bullets" and "content_data" not in data:
        required_fields.append("bullets")
    missing = [f for f in required_fields if f not in data]
    if missing:
        raise ParseError(response_text, f"Missing required fields: {missing}")
    
    data = _clean_slide_text(data)
    return data


def parse_queries_response(response_text: str) -> list[str]:
    """Parse LLM response for alternative queries."""
    text = response_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    
    try:
        data = json.loads(text)
        return data.get("queries", [])
    except json.JSONDecodeError:
        # Try to extract queries from plain text
        lines = text.split("\n")
        queries = [line.strip().strip("-").strip() for line in lines if line.strip()]
        return queries[:3] if queries else []


# =============================================================================
# PROMPT FORMATTING
# =============================================================================

def format_chunks_for_prompt(chunks: list[dict]) -> str:
    """Format retrieved chunks for inclusion in prompt."""
    formatted = []
    for chunk in chunks:
        formatted.append(f"""
<chunk id="{chunk['chunk_id']}">
  <source>{chunk.get('doc_title', 'Unknown')}</source>
  <trust_level>{chunk.get('trust_level', 'medium')}</trust_level>
  <content>{chunk['content']}</content>
</chunk>""")
    return "\n".join(formatted)


def get_intent_metadata(intent: str) -> dict:
    """Get metadata for an intent from the DB-cached intent type map.

    Returns dict with 'suggested_title' and 'requirements' keys.
    Falls back to generated defaults for intents not in the map
    (e.g., before load_intent_type_map() is called, or for truly unknown intents).
    """
    info = INTENT_TYPE_MAP.get(intent)
    if info:
        return {
            "suggested_title": info.suggested_title,
            "requirements": info.requirements,
        }
    return {
        "suggested_title": intent.replace("-", " ").title(),
        "requirements": "Generate content for this slide intent",
    }


# =============================================================================
# LLM API CALLS
# =============================================================================

@retry(
    retry=retry_if_exception_type((RateLimitError, APIConnectionError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=60),
)
async def call_llm(
    system_prompt: str,
    user_prompt: str,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> LLMResponse:
    """
    Call OpenAI API with retry logic for rate limits and connection errors.
    
    Args:
        system_prompt: System message content
        user_prompt: User message content
        model: Model to use (default: config openai_model)
        temperature: Sampling temperature
        max_tokens: Maximum tokens in response
        
    Returns:
        LLMResponse with text and token usage counts
        
    Raises:
        APIError: For non-retryable API errors
    """
    temperature = temperature if temperature is not None else config.get("llm_temperature", 0.7)
    max_tokens = max_tokens if max_tokens is not None else config.get("llm_max_tokens", 2000)
    
    client = await get_llm_client()
    model = model or config.get("openai_model", "gpt-4")
    
    logger.info(f"Calling LLM: model={model}, temp={temperature}")
    
    kwargs = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if OPENAI_USER:
        kwargs["user"] = OPENAI_USER
    
    response = await client.chat.completions.create(**kwargs)
    
    text = response.choices[0].message.content
    prompt_tokens = response.usage.prompt_tokens if response.usage else 0
    completion_tokens = response.usage.completion_tokens if response.usage else 0
    
    logger.info(f"LLM response: {len(text)} chars, tokens: {prompt_tokens}+{completion_tokens}")
    
    return LLMResponse(
        text=text,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


async def draft_slide(
    intent: str,
    chunks: list[dict],
    slide_no: int,
    total_slides: Optional[int] = None,
    prior_titles: Optional[list[str]] = None,
) -> tuple[dict, LLMResponse]:
    """
    Generate a slide draft using GPT-4.
    
    Args:
        intent: Slide intent (e.g., "why-postgres")
        chunks: Retrieved chunks for context
        slide_no: Current slide number (1-based)
        total_slides: Total slides in deck
        prior_titles: Titles of previously generated slides (avoid repetition)
        
    Returns:
        Tuple of (slide spec dict, LLMResponse with usage)
        
    Raises:
        InsufficientContextError: If context is insufficient
        ParseError: If response parsing fails
    """
    # Use env default if not specified
    total_slides = total_slides if total_slides is not None else get_target_slides()
    
    metadata = get_intent_metadata(intent)
    slide_type = get_slide_type(intent)
    output_schema = _get_output_schema_for_type(slide_type)

    # Replace the generic OUTPUT FORMAT block BEFORE .format() so that
    # doubled braces {{ }} in both the target and the typed schema match.
    # (.format() converts {{ to { -- doing replace after would miss the target)
    sys_tmpl, user_tmpl = _get_prompt_template("slide_generation")
    template = sys_tmpl.replace(
        'OUTPUT FORMAT:\nReturn valid JSON matching this schema:\n{{\n'
        '  "title": "slide title",\n'
        '  "intent": "<the intent>",\n'
        '  "bullets": ["bullet 1", "bullet 2"],\n'
        '  "speaker_notes": "Explanation for presenter...",\n'
        '  "citations": [{{"chunk_id": "uuid", "doc_title": "title", "relevance": "why"}}]\n'
        '}}',
        f'OUTPUT FORMAT (slide_type={slide_type}):\n{output_schema}',
    )

    system_prompt = template.format(
        intent=intent,
        retrieved_chunks=format_chunks_for_prompt(chunks),
    )

    user_prompt = user_tmpl.format(
        intent=intent,
        suggested_title=metadata["suggested_title"],
        requirements=metadata["requirements"],
        slide_no=slide_no,
        total_slides=total_slides,
        prior_titles=", ".join(prior_titles) if prior_titles else "None yet",
    )
    
    llm_response = await call_llm(system_prompt, user_prompt)
    parsed = parse_slide_response(llm_response.text)
    parsed["slide_type"] = slide_type
    return parsed, llm_response


async def rewrite_slide_format(
    failed_slide_spec: dict,
    validation_errors: list[str],
    original_chunks: list[dict],
) -> tuple[dict, LLMResponse]:
    """Rewrite a slide to fix format validation errors (G3 fail)."""
    slide_type = failed_slide_spec.get("slide_type", "bullets")
    output_schema = _get_output_schema_for_type(slide_type)
    output_schema_rendered = output_schema.replace("{{", "{").replace("}}", "}")

    sys_tmpl, user_tmpl = _get_prompt_template("rewrite_format")

    system_prompt = sys_tmpl.format(
        output_schema=output_schema_rendered,
        failed_slide_spec=json.dumps(failed_slide_spec, indent=2),
        validation_errors="\n".join(f"- {e}" for e in validation_errors),
        original_context=format_chunks_for_prompt(original_chunks),
    )

    user_prompt = user_tmpl.format(
        specific_issues="\n".join(f"- {e}" for e in validation_errors),
    )
    
    llm_response = await call_llm(system_prompt, user_prompt)
    parsed = parse_slide_response(llm_response.text)
    parsed["slide_type"] = slide_type
    return parsed, llm_response


async def rewrite_slide_grounding(
    failed_slide_spec: dict,
    ungrounded_bullets: list[int],
    cited_chunks: list[dict],
) -> tuple[dict, LLMResponse]:
    """Rewrite a slide to fix grounding issues (G2.5 fail)."""
    slide_type = failed_slide_spec.get("slide_type", "bullets")
    output_schema = _get_output_schema_for_type(slide_type)
    output_schema_rendered = output_schema.replace("{{", "{").replace("}}", "}")

    sys_tmpl, user_tmpl = _get_prompt_template("rewrite_grounding")

    system_prompt = sys_tmpl.format(
        output_schema=output_schema_rendered,
        failed_slide_spec=json.dumps(failed_slide_spec, indent=2),
        ungrounded_bullet_indices=", ".join(str(i) for i in ungrounded_bullets),
        cited_chunks_content=format_chunks_for_prompt(cited_chunks),
    )

    user_prompt = user_tmpl.format(
        ungrounded_indices=", ".join(str(i) for i in ungrounded_bullets),
    )
    
    llm_response = await call_llm(system_prompt, user_prompt)
    parsed = parse_slide_response(llm_response.text)
    parsed["slide_type"] = slide_type
    return parsed, llm_response


async def rewrite_slide_novelty(
    failed_slide_spec: dict,
    most_similar_slide: dict,
    similarity_score: float,
    chunks: list[dict],
) -> tuple[dict, LLMResponse]:
    """Rewrite a slide to improve novelty (G4 fail)."""
    intent = failed_slide_spec.get("intent", "unknown")
    slide_type = failed_slide_spec.get("slide_type", "bullets")
    output_schema = _get_output_schema_for_type(slide_type)
    output_schema_rendered = output_schema.replace("{{", "{").replace("}}", "}")
    
    # Extract concepts from similar slide to avoid
    similar_bullets = most_similar_slide.get("bullets", [])
    concepts = ", ".join(similar_bullets[:2]) if similar_bullets else "general concepts"
    
    sys_tmpl, user_tmpl = _get_prompt_template("rewrite_novelty")

    system_prompt = sys_tmpl.format(
        intent=intent,
        output_schema=output_schema_rendered,
        concepts_from_similar_slide=concepts,
        failed_slide_spec=json.dumps(failed_slide_spec, indent=2),
        most_similar_slide=json.dumps(most_similar_slide, indent=2),
        similarity_score=f"{similarity_score:.2f}",
        retrieved_chunks=format_chunks_for_prompt(chunks),
    )

    user_prompt = user_tmpl.format(
        intent=intent,
        existing_focus=similar_bullets[0] if similar_bullets else "general points",
        alternative_focus="a different aspect of " + intent.replace("-", " "),
    )
    
    llm_response = await call_llm(system_prompt, user_prompt)
    parsed = parse_slide_response(llm_response.text)
    parsed["slide_type"] = slide_type
    return parsed, llm_response


async def generate_alternative_queries(
    intent: str,
    missing_info: str,
) -> tuple[list[str], LLMResponse]:
    """Generate alternative search queries when context is insufficient.
    
    Returns:
        Tuple of (list of queries, LLMResponse with usage)
    """
    metadata = get_intent_metadata(intent)
    
    sys_tmpl, user_tmpl = _get_prompt_template("alternative_queries")

    system_prompt = sys_tmpl.format(
        intent=intent,
        what_was_missing=missing_info,
        requirements=metadata["requirements"],
    )

    user_prompt = user_tmpl.format(
        missing_topic=missing_info,
    )
    
    llm_response = await call_llm(system_prompt, user_prompt, temperature=0.9)
    return parse_queries_response(llm_response.text), llm_response
