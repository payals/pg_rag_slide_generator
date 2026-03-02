BEGIN;

-- =============================================================================
-- Migration 012: Populate slide_type_config.html_fragment (Tier 3)
-- =============================================================================
--
-- Populates the html_fragment column for all 6 slide types. Each fragment
-- contains ONLY the type-specific Jinja2 HTML (no if/elif wrappers).
--
-- The fn_validate_type_config trigger validates on each UPDATE that every
-- scalar and list field in content_fields appears as a substring in
-- html_fragment. Nested fields (flow type's steps/label/caption) are
-- validated against prompt_schema only, not html_fragment.
--
-- Safety:
--   - Single transaction (atomic rollback on failure)
--   - UPDATE only (rows exist from migration 011)
--   - Trigger validates each UPDATE
--   - Idempotent: re-running overwrites html_fragment with the same value
--
-- Run with: psql -d slide_gen -U slide_gen -f db/migrations/012_render_fragments.sql

-- ---------------------------------------------------------------------------
-- A. statement fragment
-- ---------------------------------------------------------------------------

UPDATE slide_type_config SET html_fragment =
$$<p class="statement-text">{{ slide.content_data.statement | default('') }}</p>
{% if slide.content_data.subtitle %}
<p class="statement-subtitle">{{ slide.content_data.subtitle }}</p>
{% endif %}$$
WHERE slide_type = 'statement';

-- ---------------------------------------------------------------------------
-- B. split fragment
-- ---------------------------------------------------------------------------

UPDATE slide_type_config SET html_fragment =
$$<div class="split-layout">
    <div class="split-col">
        <h3>{{ slide.content_data.left_title | default('') }}</h3>
        <ul>{% for item in slide.content_data.left_items | default([]) %}<li>{{ item }}</li>{% endfor %}</ul>
    </div>
    <div class="split-col">
        <h3>{{ slide.content_data.right_title | default('') }}</h3>
        <ul>{% for item in slide.content_data.right_items | default([]) %}<li>{{ item }}</li>{% endfor %}</ul>
    </div>
</div>$$
WHERE slide_type = 'split';

-- ---------------------------------------------------------------------------
-- C. flow fragment
-- ---------------------------------------------------------------------------

UPDATE slide_type_config SET html_fragment =
$$<div class="flow-pipeline">
    {% for step in slide.content_data.steps | default([]) %}
    {% if loop.first %}
    <div class="flow-step">
        <span class="flow-label">{{ step.label | default('') }}</span>
        {% if step.caption %}<span class="flow-caption">{{ step.caption }}</span>{% endif %}
    </div>
    {% else %}
    <div class="flow-pair">
        <span class="flow-arrow">&#8594;</span>
        <div class="flow-step">
            <span class="flow-label">{{ step.label | default('') }}</span>
            {% if step.caption %}<span class="flow-caption">{{ step.caption }}</span>{% endif %}
        </div>
    </div>
    {% endif %}
    {% endfor %}
</div>$$
WHERE slide_type = 'flow';

-- ---------------------------------------------------------------------------
-- D. code fragment
-- ---------------------------------------------------------------------------

UPDATE slide_type_config SET html_fragment =
$$<pre class="code-block" data-language="{{ slide.content_data.language | default('') }}"><code>{{ slide.content_data.code_block | default('') }}</code></pre>
{% for b in slide.content_data.explain_bullets | default([]) %}
<p class="code-explain">{{ b }}</p>
{% endfor %}$$
WHERE slide_type = 'code';

-- ---------------------------------------------------------------------------
-- E. diagram fragment
-- ---------------------------------------------------------------------------

UPDATE slide_type_config SET html_fragment =
$$<div class="diagram-content">
{% for c in slide.content_data.callouts | default([]) %}
<p class="diagram-callout">{{ c }}</p>
{% endfor %}
{% if slide.content_data.caption %}
<p class="diagram-caption">{{ slide.content_data.caption }}</p>
{% endif %}
</div>$$
WHERE slide_type = 'diagram';

-- ---------------------------------------------------------------------------
-- F. bullets fragment (default/fallback type)
-- ---------------------------------------------------------------------------

UPDATE slide_type_config SET html_fragment =
$${% if slide.bullets %}
<ul>
    {% for bullet in slide.bullets %}
    <li>{{ bullet }}</li>
    {% endfor %}
</ul>
{% endif %}$$
WHERE slide_type = 'bullets';

-- ---------------------------------------------------------------------------
-- G. Verification
-- ---------------------------------------------------------------------------

DO $$
DECLARE
    v_null_count INT;
    v_total INT;
BEGIN
    SELECT count(*) INTO v_total FROM slide_type_config;
    SELECT count(*) INTO v_null_count FROM slide_type_config WHERE html_fragment IS NULL;

    IF v_total != 6 THEN
        RAISE EXCEPTION 'Expected 6 slide_type_config rows, found %', v_total;
    END IF;

    IF v_null_count != 0 THEN
        RAISE EXCEPTION 'Expected 0 NULL html_fragment values, found %', v_null_count;
    END IF;

    RAISE NOTICE '✓ Migration 012 applied successfully';
    RAISE NOTICE '  slide_type_config: % rows with html_fragment populated', v_total;
END $$;

COMMIT;
