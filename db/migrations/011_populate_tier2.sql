BEGIN;

-- =============================================================================
-- Migration 011: Populate Tier 2 tables (slide_type_config + prompt_template)
-- =============================================================================
--
-- Populates tables created by migration 010 with data currently hardcoded
-- in src/llm.py. After this migration + Python switchover, the constants
-- can be deleted.
--
-- Safety:
--   - ON CONFLICT DO NOTHING for idempotency
--   - Single transaction (atomic rollback on failure)
--   - fn_validate_type_config trigger validates each INSERT
--
-- Run with: psql -d slide_gen -U slide_gen -f db/migrations/011_populate_tier2.sql

-- ---------------------------------------------------------------------------
-- A. slide_type_config: 6 rows (one per slide type)
-- ---------------------------------------------------------------------------

INSERT INTO slide_type_config (slide_type, prompt_schema, content_fields)
VALUES ('statement',
$$Return valid JSON matching this schema:
{{
  "title": "slide title (max 60 chars)",
  "intent": "<the intent>",
  "slide_type": "statement",
  "content_data": {{
    "statement": "One powerful sentence (8-90 chars)",
    "subtitle": "Optional supporting line (max 120 chars)"
  }},
  "bullets": [],
  "speaker_notes": "Explanation for presenter...",
  "citations": [{{"chunk_id": "uuid", "doc_title": "title", "relevance": "why"}}]
}}$$,
'{"scalar": ["statement", "subtitle"], "list": [], "nested": {}}'::jsonb)
ON CONFLICT DO NOTHING;

INSERT INTO slide_type_config (slide_type, prompt_schema, content_fields)
VALUES ('split',
$$Return valid JSON matching this schema:
{{
  "title": "slide title (max 60 chars)",
  "intent": "<the intent>",
  "slide_type": "split",
  "content_data": {{
    "left_title": "Left column heading",
    "left_items": ["item 1", "item 2"],
    "right_title": "Right column heading",
    "right_items": ["item 1", "item 2"]
  }},
  "bullets": [],
  "speaker_notes": "Explanation for presenter...",
  "citations": [{{"chunk_id": "uuid", "doc_title": "title", "relevance": "why"}}]
}}$$,
'{"scalar": ["left_title", "right_title"], "list": ["left_items", "right_items"], "nested": {}}'::jsonb)
ON CONFLICT DO NOTHING;

INSERT INTO slide_type_config (slide_type, prompt_schema, content_fields)
VALUES ('flow',
$$Return valid JSON matching this schema:
{{
  "title": "slide title (max 60 chars)",
  "intent": "<the intent>",
  "slide_type": "flow",
  "content_data": {{
    "steps": [
      {{"label": "Step name (2-30 chars)", "caption": "Brief description (0-60 chars)"}},
      {{"label": "Step name", "caption": "Brief description"}}
    ]
  }},
  "bullets": [],
  "speaker_notes": "Explanation for presenter...",
  "citations": [{{"chunk_id": "uuid", "doc_title": "title", "relevance": "why"}}]
}}$$,
'{"scalar": [], "list": [], "nested": {"steps": ["label", "caption"]}}'::jsonb)
ON CONFLICT DO NOTHING;

INSERT INTO slide_type_config (slide_type, prompt_schema, content_fields)
VALUES ('code',
$$Return valid JSON matching this schema:
{{
  "title": "slide title (max 60 chars)",
  "intent": "<the intent>",
  "slide_type": "code",
  "content_data": {{
    "language": "sql|python|json|bash|ts|plaintext",
    "code_block": "actual code (8-15 lines, max 80 chars/line)",
    "explain_bullets": ["Short explanation bullet"]
  }},
  "bullets": [],
  "speaker_notes": "Explanation for presenter...",
  "citations": [{{"chunk_id": "uuid", "doc_title": "title", "relevance": "why"}}]
}}$$,
'{"scalar": ["code_block", "language"], "list": ["explain_bullets"], "nested": {}}'::jsonb)
ON CONFLICT DO NOTHING;

INSERT INTO slide_type_config (slide_type, prompt_schema, content_fields)
VALUES ('diagram',
$$Return valid JSON matching this schema:
{{
  "title": "slide title (max 60 chars)",
  "intent": "<the intent>",
  "slide_type": "diagram",
  "content_data": {{
    "callouts": ["Short callout (max 40 chars)", "Another callout"],
    "caption": "Optional diagram description (max 120 chars)"
  }},
  "bullets": [],
  "speaker_notes": "Explanation for presenter...",
  "citations": [{{"chunk_id": "uuid", "doc_title": "title", "relevance": "why"}}]
}}$$,
'{"scalar": ["caption"], "list": ["callouts"], "nested": {}}'::jsonb)
ON CONFLICT DO NOTHING;

INSERT INTO slide_type_config (slide_type, prompt_schema, content_fields)
VALUES ('bullets',
$$Return valid JSON matching this schema:
{{
  "title": "slide title (max 60 chars)",
  "intent": "<the intent>",
  "slide_type": "bullets",
  "bullets": ["bullet 1 (max 15 words)", "bullet 2"],
  "speaker_notes": "Explanation for presenter...",
  "citations": [{{"chunk_id": "uuid", "doc_title": "title", "relevance": "why"}}]
}}$$,
'{"scalar": [], "list": ["bullets"], "nested": {}}'::jsonb)
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- B. prompt_template: 5 rows (one per purpose)
-- ---------------------------------------------------------------------------

INSERT INTO prompt_template (purpose, version, is_active, system_prompt, user_prompt)
VALUES ('slide_generation', 1, true,
$$You are a technical slide content writer for a conference presentation about Postgres as an AI control plane.

CRITICAL RULES:
1. Use ONLY information from the <context> section below. Do NOT use training data.
2. Every bullet point MUST be directly supported by the provided sources.
3. If context is insufficient for a bullet, respond with:
   {{"error": "INSUFFICIENT_CONTEXT", "missing": "description of what's needed"}}
4. Keep bullets concise: max 15 words each. Shorter is better.
5. Include speaker notes that explain concepts for the presenter.
6. Cite sources using the chunk_ids provided.

OUTPUT FORMAT:
Return valid JSON matching this schema:
{{
  "title": "slide title",
  "intent": "<the intent>",
  "bullets": ["bullet 1", "bullet 2"],
  "speaker_notes": "Explanation for presenter...",
  "citations": [{{"chunk_id": "uuid", "doc_title": "title", "relevance": "why"}}]
}}

<context>
{retrieved_chunks}
</context>$$,
$$Generate slide content for intent: {intent}
Suggested title: {suggested_title}
Required elements: {requirements}

Slide number: {slide_no} of {total_slides}
Prior slide titles (avoid repetition): {prior_titles}$$)
ON CONFLICT (purpose, version) DO NOTHING;

INSERT INTO prompt_template (purpose, version, is_active, system_prompt, user_prompt)
VALUES ('rewrite_format', 1, true,
$$You are rewriting a slide that failed format validation. Fix the specific issues listed.

RULES:
1. Keep the same core content and citations.
2. Fix ONLY the issues specified in <errors>.
3. Do not add new information.
4. Output valid JSON matching the REQUIRED OUTPUT FORMAT exactly.

REQUIRED OUTPUT FORMAT:
{output_schema}

<original_slide>
{failed_slide_spec}
</original_slide>

<errors>
{validation_errors}
</errors>

<context>
{original_context}
</context>$$,
$$Rewrite this slide to fix the format errors. Keep the same message but fix:
{specific_issues}$$)
ON CONFLICT (purpose, version) DO NOTHING;

INSERT INTO prompt_template (purpose, version, is_active, system_prompt, user_prompt)
VALUES ('rewrite_grounding', 1, true,
$$You are rewriting a slide where some text segments were not grounded in the provided sources.
The ungrounded segments must be rewritten to match the source material.

RULES:
1. Rewrite ONLY the ungrounded text segments (listed below).
2. The new content must directly reflect content from the cited chunks.
3. Do not invent information - if sources don't support a claim, remove it.
4. Keep grounded content unchanged.
5. Output valid JSON matching the REQUIRED OUTPUT FORMAT exactly.

REQUIRED OUTPUT FORMAT:
{output_schema}

<original_slide>
{failed_slide_spec}
</original_slide>

<ungrounded_bullets>
{ungrounded_bullet_indices}
</ungrounded_bullets>

<context>
{cited_chunks_content}
</context>$$,
$$Rewrite bullets {ungrounded_indices} to be directly grounded in the source material.
If the sources don't support the claim, replace with something the sources DO support.$$)
ON CONFLICT (purpose, version) DO NOTHING;

INSERT INTO prompt_template (purpose, version, is_active, system_prompt, user_prompt)
VALUES ('rewrite_novelty', 1, true,
$$You are rewriting a slide that was too similar to an existing slide in the deck.
You must change the angle/focus while covering the same intent.

RULES:
1. Keep the same intent: {intent}
2. Use DIFFERENT aspects of the source material.
3. Avoid these concepts already covered: {concepts_from_similar_slide}
4. The new slide should complement, not repeat.
5. Output valid JSON matching the REQUIRED OUTPUT FORMAT exactly.

REQUIRED OUTPUT FORMAT:
{output_schema}

<rejected_slide>
{failed_slide_spec}
</rejected_slide>

<similar_existing_slide>
{most_similar_slide}
Similarity score: {similarity_score}
</similar_existing_slide>

<context>
{retrieved_chunks}
</context>$$,
$$Rewrite this slide to cover intent "{intent}" from a DIFFERENT angle.
The existing slide focuses on: {existing_focus}
Your slide should focus on: {alternative_focus}$$)
ON CONFLICT (purpose, version) DO NOTHING;

INSERT INTO prompt_template (purpose, version, is_active, system_prompt, user_prompt)
VALUES ('alternative_queries', 1, true,
$$The previous retrieval didn't return enough information for slide intent "{intent}".
Generate a better search query to find the missing information.

<missing_info>
{what_was_missing}
</missing_info>

<intent_requirements>
{requirements}
</intent_requirements>$$,
$$Generate 2-3 alternative search queries that might find content about:
{missing_topic}

Output as JSON: {{"queries": ["query1", "query2", "query3"]}}$$)
ON CONFLICT (purpose, version) DO NOTHING;

-- ---------------------------------------------------------------------------
-- C. Verification
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    v_stc_count INT;
    v_pt_count INT;
BEGIN
    SELECT count(*) INTO v_stc_count FROM slide_type_config;
    SELECT count(*) INTO v_pt_count FROM prompt_template WHERE is_active = true;

    IF v_stc_count != 6 THEN
        RAISE EXCEPTION 'Expected 6 slide_type_config rows, found %', v_stc_count;
    END IF;

    IF v_pt_count != 5 THEN
        RAISE EXCEPTION 'Expected 5 active prompt_template rows, found %', v_pt_count;
    END IF;

    RAISE NOTICE 'Migration 011 applied successfully';
    RAISE NOTICE '  slide_type_config: % rows', v_stc_count;
    RAISE NOTICE '  prompt_template: % active rows', v_pt_count;
END $$;

COMMIT;
