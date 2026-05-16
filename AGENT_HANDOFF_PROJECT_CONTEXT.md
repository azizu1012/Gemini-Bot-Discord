# Azuris External Agent Handoff Context

## 1. Objective

This document is a compact but actionable context package for external analysis
agents that cannot receive the full codebase in one prompt.

Project goals:

- Run a reliable Discord AI assistant with tool-augmented reasoning.
- Maintain useful long-term memory.
- Enforce privacy boundaries in multi-user environments.
- Support moderated shared knowledge.

## 2. Runtime Architecture

### Entry layer

- `main.py`: thin entrypoint.
- `run_bot.py`: canonical launcher (bot-only or bot + Flask server).
- `run_bot.sh`: Linux/Ubuntu launcher with PM2 modes (`--pm2`, `--pm2-fresh`).

### Core orchestration

- `src/handlers/bot_core.py`
  - Discord bot lifecycle.
  - Slash command registration.
  - Admin interaction UI, including dropdown/pagination flows.
- `src/handlers/message_handler.py`
  - Main per-message pipeline.
  - Context assembly.
  - Model calls.
  - Tool loop integration.
  - Response cleanup.
  - Persistence hooks.

### Tool abstraction

- `src/tools/tools.py`
  - Tool declarations.
  - Dispatch bridge from model tool-calls to concrete Python handlers.

### Memory intelligence and policy

- `src/managers/note_manager.py`
  - Note classification.
  - Safety filters.
  - Scope policy.
  - Candidate-global promotion logic.

### Persistence

- `src/database/repository.py`
  - SQLite operations.
  - Fresh-schema bootstrap for new DB files.
  - Compatibility check + auto-rebuild for legacy/incompatible schema files.
  - Index/column ensure path for safe runtime startup.
  - Note/message retrieval APIs.
  - Global-note moderation queries.

### Prompt and behavior

- `src/core/system_prompt.py`
  - Assistant behavior contract.
  - Memory operation expectations.
  - Safety constraints.
- `src/core/prompt_loader.py`
  - Runtime prompt composition/loading.

## 3. End-to-End Message Flow

1. Discord receives a DM or mention.
2. `message_handler` validates and prepares request context.
3. Recent history is pulled from DB (DB-first runtime memory path).
4. Reasoning loop runs and may call tools.
5. Final synthesis stage builds the user-facing response.
6. Response is cleaned and returned to Discord.
7. User/assistant turns are persisted to DB.

## 4. Current Memory Strategy

### 4.1 Scope model

- `user`: default for personal memory.
- `candidate_global`: shared-fact candidate state.
- `global`: approved/promoted shared knowledge.

### 4.2 Classification model

Notes are classified at save-time into types such as:

- `personal_preference`
- `global_knowledge`
- `blocked`

The blocked path is used for unsafe patterns, such as impersonation,
harassment, or dox-like cues.

### 4.3 Promotion logic

Global facts rely on normalized text plus `fact_hash`, and distinct-user
confirmations, before promotion to shared scope.

### 4.4 Retrieval policy

- User scope is prioritized.
- Global scope is included only when query intent indicates shared/common
  knowledge retrieval.

## 5. Database Snapshot

Primary tables:

- `messages(user_id, role, content, timestamp)`
- `user_notes(user_id, note_id, content, metadata, created_at, scope, importance, updated_at, is_active, note_type, fact_hash)`

Notable implementation details:

- New DB files are initialized with fresh target schema.
- Legacy or incompatible schema is detected and rebuilt automatically.
- Query indexes are present for user history and scoped note retrieval.
- APIs include list/demote capabilities for global notes.

## 6. Tooling and Integrations

Declared tools:

1. `web_search`
2. `get_weather`
3. `calculate`
4. `save_note`
5. `retrieve_notes`
6. `image_recognition`

Search strategy:

- Primary path: DuckDuckGo stream-based.
- Fallback providers: SerpAPI, Tavily, Exa (if keys are available and
  fallback conditions are met).
- Canonical cache key normalization for near-equivalent queries.
- Context-sensitive cache TTL (general vs time-sensitive).
- Inflight dedup for concurrent identical queries.
- Failed-query cooldown to prevent repeated provider spam when external
  sources are unstable.
- Deep-read hardening with short retry, boilerplate filtering, and empty-
  evidence caching.

## 7. Runtime Stability Knobs (Env-driven)

Key production controls exposed in config/env:

- `REASONING_MAX_API_RETRIES`
- `REASONING_MAX_LOOPS`
- `FINAL_MAX_API_RETRIES`
- `FALLBACK_MAX_API_RETRIES`
- `SEARCH_ENABLE_EXTRA_RETRIEVAL_PASS`
- `SEARCH_ALLOW_PARTIAL_ANSWER`

Operational launcher support:

- `run_bot.sh --pm2` for managed PM2 runtime.
- `run_bot.sh --pm2-fresh` for clean PM2 refresh (`pm2 update`, remove old
  app, clear `__pycache__`/`*.pyc`, restart with `--update-env`).

## 8. Admin and Moderation Surface

Relevant commands include:

- `/global-notes`
- `/global-note-demote`

Current UX improvements:

- Dropdown selection.
- Pagination.
- Clearer detail rendering for moderation.

## 9. What Is Already Improved

- Memory tool contract is DB-backed (no fake/stub behavior for
  save/retrieve path).
- Runtime memory direction is DB-first.
- Fresh-schema bootstrap + incompatible-schema auto-rebuild path is active.
- Hybrid scope model is introduced.
- Guardrails against abusive memory poisoning are in place.
- Global memory moderation flows are available via admin commands.
- `web_search` now includes canonical cache keys, TTL-by-context,
  inflight dedup, failed-query cooldown, and stronger deep-read behavior.
- Retry/loop budgets are environment-controlled for production stability.

## 10. Known Gaps and Risks to Analyze Next

1. Classification depth is still heuristic and can miss nuanced abuse or
   context.
2. Global fact merge quality depends on normalization/hash quality.
3. Retrieval ranking can be improved beyond basic ordering/filtering.
4. Deep automated tests around memory policy regressions are still missing.
5. Observability can be improved (stage latency, policy counters,
   moderation audit logs).

## 11. Recommended Next Technical Plan

### Phase A: safety and correctness tests

- Add targeted tests for:
  - User scope isolation.
  - Global promotion thresholds.
  - Demotion behavior.
  - Blocked note scenarios.

### Phase B: observability

- Add metrics for:
  - Reasoning stage latency.
  - Tool-call success/failure.
  - DB query latency.
  - Promotion/demotion counts.

### Phase C: retrieval quality

- Improve ranking by combining:
  - Scope priority.
  - Recency.
  - Importance.
  - Lexical relevance.

### Phase D: scalability strategy

- Keep repository interface stable.
- Prepare adapter-based migration path for PostgreSQL when
  concurrency/scale justifies it.

## 12. Prompt to Give the Next Agent

Use this prompt for external analysis:

```text
Analyze this Azuris architecture and propose a concrete implementation roadmap for memory reliability, moderation safety, retrieval quality, and scalability. Prioritize steps with test strategy, measurable acceptance criteria, and migration risk notes (SQLite to PostgreSQL), while preserving current runtime behavior.
```
