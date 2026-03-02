# Extending the System

How to add slide types, intents, themes, content sources, and prompts — almost entirely through SQL.

## Adding a New Slide Type

Example: adding a `timeline` slide type.

### Step 1: Extend the enum

```sql
ALTER TYPE slide_type ADD VALUE 'timeline';
```

### Step 2: Insert configuration

```sql
INSERT INTO slide_type_config (slide_type, prompt_schema, content_fields, html_fragment)
VALUES (
  'timeline',
  '{"type": "object", "properties": {"events": {"type": "array", "items": {"type": "object", "properties": {"year": {"type": "string"}, "description": {"type": "string"}}}}}}',
  '{"events": ["year", "description"]}',
  '{% for event in slide.content_data.events %}<div class="timeline-event"><span class="year">{{ event.year }}</span><p>{{ event.description }}</p></div>{% endfor %}'
);
```

The `fn_validate_type_config` trigger automatically validates that all `content_fields` keys appear in `html_fragment` — if they don't, the INSERT is rejected.

### Step 3: Update fragment order

No code change required. `_FRAGMENT_ORDER` is now derived dynamically from the `slide_type_config` table — any new type added via `INSERT` is automatically included. See [rendering.md](rendering.md) for how fragment composition works.

### Step 4: Map intents to the new type (optional)

```sql
INSERT INTO intent_type_map (intent, slide_type, sort_order, suggested_title, requirements, is_generatable)
VALUES ('timeline-overview', 'timeline', 18, 'Project Timeline', 'Show key milestones chronologically', true);
```

### Step 5: Content field traversal

If `content_data` introduces new field names, update `content_fields` in `slide_type_config`. The `walk_content_data()` function in `src/content_utils.py` uses the DB-derived field map automatically — no code change needed for citation stripping or text extraction.

### Step 6: Restart the application

Config tables are cached at startup.

## Adding a New Intent

```sql
INSERT INTO intent_type_map (
  intent, slide_type, sort_order, suggested_title,
  requirements, is_generatable, related_intents,
  require_image, min_bullets, max_bullets, max_bullet_words
)
VALUES (
  'security-model', 'bullets', 14,
  'Security Model',
  'Explain the security architecture including RLS, encryption, and access control',
  true,
  ARRAY['schema-security', 'architecture'],
  false, 3, 6, 20
);
```

The `sort_order` determines when this intent is generated relative to others. `related_intents` tells the LLM which existing slides provide relevant context.

**Note:** New `slide_intent` enum values require `ALTER TYPE slide_intent ADD VALUE 'security-model';` first.

## Adding a New Theme

```sql
INSERT INTO theme (name, css_overrides)
VALUES ('ocean', '
  --bg-color: #0a1628;
  --text-color: #e0e8f0;
  --accent-color: #3b82f6;
  --heading-color: #60a5fa;
  --code-bg: #1e293b;
');
```

Then use with `--theme ocean` on the CLI.

## Adding Content Sources

### Markdown files

1. Place markdown files in `content/external/` (or any directory)
2. Add YAML frontmatter:

```yaml
---
title: "Document Title"
doc_type: external
trust_level: medium
tags: [postgres, security]
---
```

3. Run ingestion:

```bash
python -m src.ingest
```

Content is chunked (700 tokens, 100 overlap), embedded, and stored with deduplication by content hash. The G0 gate validates each document before chunking.

### Trust levels

| Level | Use for |
|-------|---------|
| `high` | Your own content, official documentation |
| `medium` | Vetted blog posts, quality technical writing |
| `low` | External articles, general references |

### Images

1. Place images in `content/images/` with JSON sidecar files:

```json
{
  "caption": "Architecture diagram showing the data flow",
  "alt_text": "Data flow from ingestion through generation to rendering",
  "style": "diagram",
  "use_cases": ["architecture", "what-we-built"],
  "license": "CC-BY-4.0",
  "attribution": "Author Name"
}
```

2. Run image ingestion:

```bash
python -m src.ingest_images
```

## Modifying Prompts

Prompts are versioned in the `prompt_template` table. To change a prompt:

```sql
-- Deactivate the current version
UPDATE prompt_template SET is_active = false WHERE purpose = 'draft_slide' AND is_active = true;

-- Insert the new version
INSERT INTO prompt_template (purpose, system_prompt, user_prompt, is_active)
VALUES ('draft_slide', 'New system prompt...', 'New user prompt...', true);
```

A partial unique index enforces that exactly one row per `purpose` can have `is_active = true`. Attempting to activate two prompts for the same purpose will fail.

Restart the application to pick up the change (config is cached at startup).

## Pre-Demo Verification Checklist

Condensed from the full manual test checklist:

### Database Foundation
- [ ] `psql $DATABASE_URL -c "SELECT count(*) FROM chunk;"` — chunks exist
- [ ] `psql $DATABASE_URL -c "SELECT count(*) FROM intent_type_map;"` — returns 17
- [ ] `psql $DATABASE_URL -c "SELECT count(*) FROM slide_type_config;"` — returns 6
- [ ] `psql $DATABASE_URL -c "SELECT count(*) FROM prompt_template WHERE is_active;"` — returns 5

### Content Ingestion
- [ ] `python -m src.ingest` — completes without errors
- [ ] Chunks have embeddings: `SELECT count(*) FROM chunk WHERE embedding IS NOT NULL;`

### Test Generation
- [ ] `python -m src.orchestrator --topic "Postgres as an AI Control Plane"` — completes successfully
- [ ] `python -m src.run_report --deck-id <uuid> --verbose` — shows pass rates and cost

### Live Server
- [ ] `python -m src.server --topic "Postgres as an AI Control Plane" --theme postgres` — browser opens, slides stream in
- [ ] Status panel shows phase transitions and gate results

### Output Rendering
- [ ] `python -m src.renderer --deck-id <uuid> --theme postgres --output output/deck.html` — renders without errors
- [ ] Open `output/deck.html` — all slide types render correctly, navigation works, speaker notes toggle (S key)
