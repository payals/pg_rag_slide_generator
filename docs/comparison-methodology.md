# Deck Comparison Methodology

This document describes how `scripts/compare_decks.py` evaluates a raw LLM-generated slide deck against a control plane-generated baseline. The comparison uses three independent layers, each designed to catch different types of differences.

## Why Three Layers?

No single evaluation method is sufficient:

- **Structural metrics** count what's present but can't judge quality.
- **Automated text metrics** measure content overlap deterministically but can't assess correctness or reasoning.
- **LLM pairwise comparison** handles nuance and quality but is non-deterministic.

By combining all three, readers can triangulate: if the LLM says the raw deck has strong content coverage but the TF-IDF metric shows 52%, that's a signal worth investigating.

## Layer 1: Structural Metrics

**What it measures:** Objective counts extracted from raw HTML.

| Metric | Method |
|--------|--------|
| Total slides | Count `<section>` tags |
| Slide types | Match CSS classes for known types (statement, split, flow, code, diagram, bullets) |
| Code blocks | Count `<pre class="code-block">` elements |
| Curated images | Count `class="slide-image"` wrapper divs |
| Inline SVGs | Count `<svg>` tags |
| Speaker notes | Count `<aside class="notes">` elements |
| File size | `stat()` on the HTML file |

**Properties:**
- Fully deterministic
- Reproducible across runs
- Cannot assess content quality

## Layer 2: Automated Text Metrics

**What it measures:** Content overlap and semantic similarity between extracted slide text.

### Text Extraction

Before computing metrics, slide text is extracted from both HTML files. The extraction:

- Splits HTML into `<section>` blocks
- Strips HTML tags and decodes entities (`&lt;` becomes `<`, `&#39;` becomes `'`)
- Replaces `<svg>` elements with `[inline SVG diagram]` markers (preserves the fact that diagrams exist without leaking garbled SVG text labels)
- Replaces `<div class="slide-image">` elements with `[curated image]` markers (makes baseline images visible to the evaluator)
- Preserves code block content with language labels (e.g., `[Code block (sql)]`)
- Includes speaker notes (up to 300 chars per slide)

This balanced extraction ensures neither deck's visual elements are invisible to the evaluator.

### Content Coverage (TF-IDF Cosine Similarity)

Measures what fraction of the baseline's important terms and phrases appear in the raw LLM deck.

- Uses `sklearn.TfidfVectorizer` with unigram and bigram features, English stop words removed.
- Computes cosine similarity between the TF-IDF vectors of both full deck texts.
- Score ranges from 0.0 (no overlap) to 1.0 (identical term usage).

**Basis:** TF-IDF weighting was introduced by Salton & Buckley (1988) and remains a standard in information retrieval. This metric is analogous to ROUGE-1/ROUGE-2 (Lin, 2004) but uses TF-IDF weighting instead of raw n-gram counts, giving more weight to distinctive terms.

**Limitation:** Rewards lexical overlap. Two sentences conveying the same meaning in different words will score low.

### Semantic Similarity (BERTScore-style)

Measures how semantically similar the slide content is, independent of exact wording.

- Embeds each slide's text using `sentence-transformers` model `all-MiniLM-L6-v2`.
- For each baseline slide, finds the best-matching raw LLM slide by cosine similarity.
- Reports the average of these best-match scores.

**Basis:** Adapted from BERTScore (Zhang et al., 2020), which uses contextual embeddings for evaluation. Our implementation operates at slide-level granularity rather than token-level, since slides are the natural unit of comparison.

**Limitation:** A raw deck that covers the same topics in a different order will score lower on diagonal matches, though the best-match approach mitigates this.

### Technical Vocabulary

Counts how many domain-specific Postgres terms appear in each deck.

- Maintains a curated list of Postgres-specific terms: `pgvector`, `pg_trgm`, `tsvector`, `SECURITY INVOKER`, `<=>`, `gate_log`, etc.
- Exact case-insensitive string matching against extracted slide text.
- Reports: how many baseline terms appear in the raw deck, which terms are baseline-only, and which are raw-only.

**Properties:**
- Fully deterministic
- Reports the specific terms found/missing, not just a score
- The term list is curated, which means it reflects what this project considers important (this is documented, not hidden)
- Terms unique to the raw deck (e.g., PostGIS, FDW) are tracked and displayed in "Raw LLM only"

## Layer 3: Pairwise LLM Comparison

**What it measures:** Qualitative content quality across six axes, evaluated by an LLM.

### Method

Uses pairwise preference evaluation: for each axis, the LLM picks which deck is better and by what margin. This avoids the scale calibration problem inherent in numeric scoring (where different evaluators interpret "7/10" differently).

**Basis:** This approach follows the methodology used by:
- **Chatbot Arena** (Zheng et al., 2023) -- pairwise human preference judgments for LLM evaluation
- **MT-Bench** (Zheng et al., 2023) -- automated pairwise comparison using GPT-4 as judge
- **G-Eval** (Liu et al., 2023) -- LLM-based evaluation with structured criteria
- **Prometheus** (Kim et al., 2024) -- fine-tuned evaluator models with explicit rubrics

### Why Pairwise Instead of Numeric Scores?

We initially used numeric delta scoring (baseline = 10/10, raw LLM scored relative to it). This had several problems:

1. **Scale calibration**: The LLM interpreted "7/10" differently across runs
2. **Generosity bias**: Without anchored rubrics, the LLM gave inflated scores (e.g., 6/10 for code examples when there were zero code blocks)
3. **Inconsistent sensitivity**: Small rubric wording changes caused large score swings

Pairwise comparison eliminates these issues. The LLM only needs to answer "which is better and by how much?" -- a simpler cognitive task that produces more consistent results.

### Talk Context

The prompt provides high-level context about the talk's purpose and audience:

> This is a 25-minute conference talk at SCaLE 23x (a Linux/open-source conference) for an audience of developers and DBAs. The topic is "Postgres as an AI Control Plane" -- arguing that Postgres features can replace scattered AI infrastructure services. The audience expects concrete Postgres examples, not marketing-level abstractions.

This context helps the evaluator judge relevance (a SCaLE audience expects implementation detail) without biasing toward either deck's specific approach. It does not describe what the talk should cover (e.g., no mention of specific gates, tools, or schemas).

### Axes

| Axis | What it evaluates | Rubric guidance |
|------|-------------------|-----------------|
| Specificity | Does the deck name real Postgres features at implementation level (operators, functions, schemas) vs. category level? | Distinguishes feature categories ("RLS") from implementation details ("SECURITY INVOKER") |
| Accuracy | Are technical claims verifiably correct? | Looks for hallucinated function/operator names, wrong syntax, incorrect version claims, features attributed to wrong extensions. Vague-but-safe claims don't count as accurate -- precision matters |
| Repetition | Does the deck avoid restating the same points across slides? | Explicit slide-count thresholds: slightly = 2 slides overlap; moderately = 3-4; significantly = 5+ |
| Technical depth | Does it provide implementation details vs. abstractions? | Schemas, queries, function signatures vs. marketing-level descriptions |
| Code examples | Does it include real, runnable code blocks? | Counts actual `<pre>` blocks, not inline code mentions in bullets |
| Formatting | Does it have visual variety and structural diversity? | Curated images, inline diagrams, code blocks, multiple slide layouts |

### Margin Scale

Rather than numeric scores, the LLM reports an ordinal margin:

| Margin | Meaning |
|--------|---------|
| tie | Essentially equivalent on this axis |
| slightly | Minor edge; reasonable people could disagree |
| moderately | Clear difference with concrete evidence |
| significantly | Large gap; one deck is much stronger |

### Output Format

The LLM returns structured JSON with a winner, margin, and evidence-based reason for each axis, plus 3-5 key differences. The script renders this as a table with a summary line (e.g., "Baseline wins 5, 1 tie").

## Fairness Controls

### Bidirectional Evaluation

The LLM can declare either deck the winner on any axis. The prompt explicitly supports both `"A"` (baseline) and `"B"` (raw LLM) as winners, with no cap or bias language. In practice, the raw LLM deck can and does win on some axes (e.g., repetition if it's more concise).

### Evidence Requirement

Every judgment must cite specific text from the slides. The prompt states: "Every judgment MUST cite specific evidence from the slide text." Reasons without evidence are a signal of unreliable evaluation.

### Balanced Visual Element Extraction

Both decks' visual elements are represented as markers in the extracted text:

- Baseline's `<div class="slide-image">` elements become `[curated image]` markers
- Raw LLM's `<svg>` elements become `[inline SVG diagram]` markers

This prevents either deck's visual content from being invisible to the evaluator. Without these markers, the baseline's 4 curated images were hidden (causing the raw LLM to falsely win on formatting), and with raw SVG text leaked, the raw LLM received inflated credit for garbled SVG label text that appeared as intentional diagrams.

### Deterministic Cross-Check

Layer 2 (automated metrics) provides deterministic scores that cannot be influenced by LLM bias. If Layer 3 claims the raw deck has equivalent content but Layer 2 shows 52% coverage and 0.69 semantic similarity, readers can identify the discrepancy.

### Low Temperature

The LLM is called with `temperature=0.3` to reduce variance between runs. This doesn't eliminate non-determinism but makes results more consistent.

### Reproducibility

| Layer | Deterministic? | Notes |
|-------|---------------|-------|
| Structural metrics | Yes | Same HTML always produces same counts |
| TF-IDF coverage | Yes | Same text always produces same score |
| Semantic similarity | Yes* | Deterministic for a given model version |
| Technical vocabulary | Yes | Exact string matching |
| Pairwise comparison | No | LLM output varies between runs |

## Known Limitations

1. **Provenance disclosure:** The prompt tells the LLM that Deck A used a multi-step pipeline with gates while Deck B is a single LLM call. This context helps the evaluator understand structural differences but could bias it toward Deck A. The prompt now explicitly notes that the topic is public knowledge and RAG doesn't surface novel data, which partially mitigates this bias. A fully blinded comparison would remove provenance entirely at the cost of less informed structural judgments.

2. **Curated vocabulary bias:** The technical vocabulary list includes terms from both decks, but the coverage fraction measures "how many baseline terms does the raw deck use." Terms unique to the raw deck are tracked and displayed but don't affect the fraction. This is by design (we're measuring how well the raw deck covers what the baseline covers) but means the metric is inherently baseline-centric.

3. **Single evaluator:** Layer 3 uses one LLM call. Production evaluation systems like Chatbot Arena use thousands of human judges. Our single-call approach is practical but noisier.

4. **Temperature non-determinism:** Even at 0.3, the pairwise comparison may produce different winners on marginal axes across runs.

5. **SVG quality not assessed:** The `[inline SVG diagram]` marker tells the evaluator that a diagram exists but not whether it renders correctly. Broken or garbled SVGs receive the same marker as well-formed ones.

## What Drives the Gap

An honest accounting of *why* the baseline deck scores higher.

**Critical context: this topic does not favor RAG.** The subject matter -- Postgres features, pgvector, MCP, SQL security primitives -- is entirely public knowledge already present in GPT-5's training data. RAG retrieves Postgres documentation fragments, but the LLM already knows everything those fragments contain. RAG provides zero information advantage here. This means the comparison is actually a harder test for the control plane: it can't win by knowing more, only by *organizing and validating* better.

### Pipeline orchestration (~80% of the gap)

The baseline's advantages come primarily from the multi-step pipeline, not retrieval:

| Advantage | Pipeline feature | Would RAG alone provide this? |
|-----------|-----------------|-------------------------------|
| No 6-slide repetition of the same theme | Quality gates reject redundant slides | No |
| Diverse slide types (code, split, diagram) | Structured schema enforcement | No |
| Progressive narrative arc | Per-slide generation with context from previous slides | No |
| Curated images on architecture slides | Image selection pipeline | No |
| Real SQL examples on dedicated code slides | Slide type forces code content | Partially |

### RAG specificity constraint (~20% of the gap)

RAG contributes, but not in its usual way. Normally RAG's value is access to information the model doesn't have (proprietary data, recent docs, internal knowledge bases). Here, that value is zero -- the LLM already knows all of this. RAG's only contribution is as a **specificity constraint**: retrieval narrows the LLM to particular examples (`<=>` operator, `SECURITY INVOKER`, `gate_log` schema) instead of letting it generate generic descriptions from memory. The LLM *knows* about `SECURITY INVOKER`, but without retrieval nudging it toward that specific fragment, it defaults to the more common "row-level security" abstraction. This is a real but modest benefit -- specificity steering, not knowledge augmentation.

### What this means for the talk's thesis

This attribution actually strengthens the talk's argument. The claim isn't "RAG makes things better" -- it's **"a structured control plane with validation produces better output than a single unconstrained LLM call, even when the LLM already knows the subject matter."** The control plane is the point, not the retrieval. RAG is one tool in the control plane, but gates, structured types, and multi-step generation do most of the heavy lifting.

## Design Decisions

### Why We Moved From Delta Scoring to Pairwise

The comparison script initially used baseline-relative delta scoring (-10 to +2 per axis). We switched to pairwise for three reasons:

1. Numeric scores were inconsistent across runs despite detailed rubrics
2. The LLM struggled to calibrate deltas (e.g., giving -2 for repetition when 7 slides repeated the same theme)
3. Pairwise "which is better?" is a simpler judgment that the LLM performs more reliably

### Why We Added Talk Context

The evaluator initially had no information about the audience or purpose. This meant it couldn't distinguish between content that's good for a marketing audience vs. a technical conference. Adding high-level context ("SCaLE 23x, developers and DBAs, expects concrete Postgres examples") improved relevance judgments without biasing toward either deck's specific approach.

## Multi-Run Aggregation

Single LLM evaluation runs are noisy -- even at temperature 0.3, marginal axes can flip between runs. To produce stable results, the comparison system supports multiple runs with majority-vote aggregation.

### How It Works

Each run of `compare_decks.py --analyze --store` writes a row to the `comparison_run` table in Postgres, capturing the full per-axis results (winner, margin, reason) as JSONB alongside the deterministic Layer 2 metrics. The `comparison_summary.py` script then aggregates across runs:

1. **Per-axis majority vote**: for each axis, the winner that appears in the most runs wins
2. **Margin consensus**: the most common margin among runs where the majority winner won
3. **Confidence levels**:
   - *unanimous* (100%): same winner every run -- high-confidence result
   - *strong* (>75%): clear majority -- reliable result
   - *weak* (50-75%): slim majority -- axis is genuinely borderline
   - *split* (<50%): no majority -- axis is too close to call

### Why This Matters

Production evaluation systems like Chatbot Arena use thousands of human judgments. Our single-call approach is practical but noisier. Multi-run aggregation mitigates this: axes where the baseline wins unanimously (e.g., code examples at 5/5) are clearly pipeline-driven advantages, while axes with weak confidence (e.g., accuracy at 3/5) signal genuinely marginal differences where neither deck clearly dominates.

### Storage Schema

Results are stored in the `comparison_run` table (migration 014), which holds both deterministic metrics (TF-IDF, semantic similarity, vocabulary counts) and the full pairwise JSON per run. This allows retrospective re-aggregation if rubrics change.

## References

- Lin, C.Y. (2004). ROUGE: A Package for Automatic Evaluation of Summaries. *Text Summarization Branches Out*.
- Salton, G. & Buckley, C. (1988). Term-weighting approaches in automatic text retrieval. *Information Processing & Management*, 24(5).
- Zhang, T. et al. (2020). BERTScore: Evaluating Text Generation with BERT. *ICLR 2020*.
- Liu, Y. et al. (2023). G-Eval: NLG Evaluation using GPT-4 with Better Human Alignment. *EMNLP 2023*.
- Kim, S. et al. (2024). Prometheus: Inducing Fine-grained Evaluation Capability in Language Models. *ICLR 2024*.
- Zheng, L. et al. (2023). Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena. *NeurIPS 2023*.

## Usage

```bash
# Single comparison
python scripts/compare_decks.py                          # Layer 1 only (structural metrics)
python scripts/compare_decks.py --analyze                # All three layers
python scripts/compare_decks.py --raw X.html --control Y.html --analyze

# Multi-run with storage
python scripts/compare_decks.py --analyze --store        # Single run, store to Postgres
python scripts/compare_decks.py --analyze --store --runs 5  # 5 runs, store all

# Aggregated summary
python scripts/comparison_summary.py                     # Latest deck pair
python scripts/comparison_summary.py --last 10           # Last 10 runs
python scripts/comparison_summary.py --raw X.html        # Specific raw deck
python scripts/comparison_summary.py --all               # All runs, grouped by deck pair
```
