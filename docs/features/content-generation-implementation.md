# AI Content Generation & Nurture Automation — Phase 5 Implementation

**Task:** t_7da4e966 · **Owner:** ai-agent-engineer · **Date:** 2026-09-14
**Repo:** `H:/AI-Agent-Platform/backend`

## Goal

Implement AI-driven nurture-content generation and automation so the platform
can automatically produce **personalized** nurture content from customer
segment / lifecycle-stage / tag signals.

## Core pipeline

The intelligence layer follows the same understand → remember → determine →
select → generate → evaluate pipeline as Phase 2:

```
Understand (objective / segment / stage / tags)
   → Remember (persona, customer context)
   → Select strategy (llm | deterministic template)
   → Generate (LLM completion OR template render)
   → Evaluate (deterministic 5-dimension quality + relevance)
   → Persist (ContentGeneration audit row, optional ContentItem)
   → Inject (attach to a NurturePlan step)
```

## Design decisions (owner: ai-agent-engineer)

1. **Pure, testable core + thin platform adapter.**
   - `ContentGenerator`, `ContentQualityEvaluator`, and `content_templates`
     are **pure Python** (no DB / LLM / FastAPI imports) — reproducible and
     unit-testable offline.
   - `ContentGenerationService` is the thin **platform adapter** that wires
     the core to optional persistence (`ContentGeneration` audit log),
     content-library persistence, and NurturePlan step injection.
   - This separates AI logic from platform logic (a standing mandate).

2. **LLM is an *optional injected dependency*.**
   - `ContentGenerator` accepts an optional `llm_provider` (a small protocol:
     `healthy()`, `async complete(system, messages) -> str`).
   - No provider wired, provider unhealthy, or LLM output that fails the
     quality bar → the generator transparently falls back to the
     deterministic template path, so generation **always** returns a usable,
     quality-scored result.
   - Every result carries `strategy` and, on fallback, a `fallback_reason`,
     making behavior **explainable** and **auditable**.

3. **Deterministic quality gate (no LLM, fully testable).**
   - `ContentQualityEvaluator` scores content across five weighted dimensions
     (relevance, personalization, completeness, consistency, safety) into a
     0–5 overall score + pass/fail against a configurable threshold
     (default 4.0). Hallucination / fabricated-claim patterns are penalized
     on the safety dimension.

## API Endpoints

All routes are served from `app.routers.content_generation` under the
`/api/v1/content` prefix.

### `POST /api/v1/content/generate`

Generate personalized nurture content. Returns a quality-scored
`GeneratedContent`. Runs the LLM when a healthy provider is wired; otherwise
the deterministic template path. Optionally persists to the content library
when `save_to_library=true`.

**Request (`ContentGenerationRequest`):**

| Field | Type | Notes |
|---|---|---|
| `account_id` | UUID | required |
| `content_type` | enum | `text` \| `image` \| `video` \| `pdf` \| `html` (default `text`) |
| `objective` | str? | `welcome` \| `nurture` \| `reactivation` \| `cross_sell` \| `support` |
| `channel` | str? | `wechat` \| `wechat_work` \| `email` \| `sms` \| … |
| `persona_name` | str? | persona to layer into the copy |
| `segment_id` | UUID? | customer segment |
| `segment_name` | str? | human-readable segment label |
| `stage_code` | str? | lifecycle stage code |
| `stage_name` | str? | lifecycle stage label |
| `customer_tags` | [str] | tag signals to personalize against |
| `customer_name` | str? | personalizes the greeting/body |
| `tone` | str? | `warm` \| `professional` \| `playful` |
| `length` | enum | `short` \| `medium` \| `long` (default `medium`) |
| `language` | str | default `zh` |
| `include_cta` | bool | default `true` |
| `save_to_library` | bool | default `false` |
| `category` | str? | content category to tag the persisted item |
| `tags` | [str] | extra tags merged into the result |

**Response (`GeneratedContent`):** `title`, `body`, `summary`, `content_type`,
`tags`, `category`, `quality` (score / passed / threshold / dimensions /
issues), `strategy` (`llm` \| `template`), `fallback_used`,
`fallback_reason`, plus `generation_id` / `content_item_id` when persisted.

### `POST /api/v1/content/evaluate`

Score an existing piece of content against its intended context (no
generation performed). Returns a `QualityEvaluation`.

**Request (`ContentEvaluationRequest`):** `content` (required, min 1 char),
`title?`, `objective?`, `segment_name?`, `stage_name?`, `expected_tags[]`,
`persona_name?`, `max_length` (default 2000).

**Response (`QualityEvaluation`):** `score` (0–5), `passed`, `threshold`,
`dimensions{relevance,personalization,completeness,consistency,safety}`,
`issues[]`.

### `POST /api/v1/content/nurture/inject`

Generate (or reuse an existing library item) and attach the content to a
NurturePlan step, linking the generation into the audit log.

**Request (`ContentInjectionRequest`):**

| Field | Type | Notes |
|---|---|---|
| `plan_id` | UUID | target nurture plan (required) |
| `account_id` | UUID | owns the content (required) |
| `step_order` | int? | omit to auto-append after the highest existing step |
| `trigger_type` | enum | `time_based` \| `event_based` \| `behavior_based` \| `manual` |
| `delay_hours` | int | default 0, ≥ 0 |
| `content_id` | UUID? | reuse an existing library item for the step |
| `generate` | ContentGenerationRequest? | generate new content instead |
| `config` | object | extra config stored on the step |

Provide **either** `generate` **or** `content_id`; both omitted → 400.

**Response (`ContentInjectionResponse`):** `content_item_id`, `step_id`,
`step_order`, `content` (the `GeneratedContent`, or a library-item view),
`created_step`. 400 on validation errors; 500 on DB errors.

### `GET /api/v1/content/history`

Query the content-generation audit log (the `ContentGeneration` table),
newest first.

**Query params:** `account_id` (required), `source?`
(`ai_content` \| `ai_nurture`), `strategy?` (`llm` \| `template` \|
`library`), `content_id?`, `nurture_plan_id?`, `limit` (default 50, ≤ 200),
`offset` (default 0).

**Response (`GenerationHistoryResponse`):** `items[]` (each a
`GenerationHistoryItem` with input/output snapshots, quality score, linked
content/plan/step ids, processing time), `total`, `limit`, `offset`.

## Data model

`ContentGeneration` (`content_generation` table) — one row per AI
content-generation invocation: the personalization context, strategy,
fallback flags, quality score/pass verdict, links to the persisted
`ContentItem` and the `NurturePlan` step it was injected into, plus
input/output JSONB snapshots for reproducibility.

## Testing

`tests/test_content_generation.py` — 33 tests covering:
- template engine (all objectives, tones, CTA, html, tag merge/dedupe)
- quality evaluator (dimension bounds, safety penalties, relevance, verdicts)
- generator core (strategy selection, healthy/unhealthy/exception/bad-JSON
  fallbacks, length steering, prompt binding, JSON parsing)
- service (pure generation without DB, audit-log persistence, evaluation
  delegation, injection reuse + generate paths, history requiring DB)
- router (all four endpoints registered on the app; service dependency wiring)

All 33 tests pass; combined with the sibling `test_nurture_plan*` and
`test_content_library` suites (94 tests) there is no regression.

## Acceptance criteria — status

- [x] AI content generation interface callable — `POST /generate` (template + optional LLM)
- [x] Generated content linkable to a NurturePlan step — `POST /nurture/inject`
- [x] Content quality evaluation logic usable — `POST /evaluate` + `ContentQualityEvaluator`
- [x] Generation history queryable — `GET /history` over `ContentGeneration`
- [x] Integration tests pass — 33/33 in `test_content_generation.py`

## Out of scope (per task)

Full AI content strategy, multi-language generation, content copyright
review, real-time content-generation optimization.
