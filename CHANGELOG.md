# Changelog

All notable changes to this project will be documented in this file.

## [1.2.0] - 2026-09-21

### Added
- **Open-thread follow-up foundation (Phase 2-B)**: schema v5 extends `open_threads`
  with lifecycle columns (`kind`/`last_seen_ts`/`last_followup_ts`/`followup_count`/
  `source`/`confidence`/`dedupe_key`/`closed_reason`), pure increment with a one-time
  `last_seen_ts = updated_at` backfill; old rows are never rewritten.
- **Contract methods** (on both `ContractV1` and the `TCompanionCore` Star surface):
  `record_open_thread`, `get_open_threads`, `close_open_thread`, `mark_thread_followup`.
  Group scopes are isolated no-ops, unknown `kind` values are rejected fail-closed,
  and storage failures degrade instead of raising.
- **`get_contract_info().capabilities`** gains `open_threads_followup: true` (map shape
  stays `dict[str, bool]`).
- **`get_proactive_context`** gains the optional `open_thread_details`
  (`thread_id/label/kind/status/last_seen/followup_count/confidence`); the frozen
  `open_threads` (`str[]`) is unchanged, and `motivation.candidates[]` now carries an
  optional `thread_id` for follow-up receipt bookkeeping.
- **Store lifecycle**: `list_open_thread_details`, `touch_open_thread`,
  `mark_thread_followup`, `close_open_thread(reason)`, `expire_open_threads`
  (TTL → `stale`, expire → `closed`, per-scope LRU eviction).
- **Config group** `open_thread` (`enabled`/`max`/`ttl_days`/`expire_days`/
  `llm_judge_enabled`/`followup_max`).
- `docs/CONTRACT.md` §13 (+ schema v5 text).

### Fixed
- **Open-thread lifecycle is now actually wired at runtime (TMEAAA-502)**: the
  `open_thread` config group was previously never read, so `ttl_days`/`expire_days`/
  `max` had no effect and stale threads kept surfacing as candidates. The two read
  paths (`get_proactive_context`, `get_open_threads`) now run one idempotent
  `expire_open_threads()` pass before reading (TTL→`stale`, expiry→`closed(expired)`,
  per-scope LRU→`closed(superseded)`), and `enabled=false` turns the whole section
  off (all four methods no-op, no candidates, no lifecycle writes).
  `get_contract_info().open_thread` echoes the effective config (defaults applied);
  config is re-parsed on every read so hot-reload takes effect without a restart.
- **Open-thread labels no longer ride `motivation.reason` (TMEAAA-504)**: the
  `open_thread` candidates used to embed the short label in their `reason`
  (`未完成话题「…」`), which downstream injects verbatim into the proactive prompt
  and thereby bypassed the follow-up gate (cooldown / `followup_max` / switch).
  The reason is now a label-free wording; the label flows only through
  `open_thread_details` → the gated follow-up block.

### Notes
- `api_version` stays `1`; all new keys are optional and older clients ignore them.
- Privacy unchanged: short labels only, no raw-text columns.

## [1.1.1] - 2026-09-21

### Changed
- Copy-only release (TMEAAA-489): rewrote all user-visible `_conf_schema.json`
  descriptions/hints, plugin description and README to drop internal terminology
  (phase/roadmap labels, internal function and key names, version behaviour notes).
  No key names, defaults or behaviour changed.

## [1.1.0] - 2026-09-21

### Added
- **Emotion Event Ledger (Phase 2-A)**: `record_emotion_event()` — idempotent per
  `(persona_id, user_id, dedupe_key)`, with the two proactive receipts sharing one
  `proactive:{send_ts}` slot so exactly one of `valued_reply` / `ignored_proactive`
  settles per send. Six zero-LLM event types; group scopes stay isolated.
- **`get_emotion_context()`**: derived state (`受伤/回避/期待/开心/平静`) + valence
  (72h window, 24h half-life, clamped `[-1, 1]`) + up to 5 recent event tags — no
  message bodies.
- **`expression_decision()` (Phase 2-C)**: seven-tier `mode` with `style_hints`
  (`tone/warmth/length_bias/proactive_bias`); group sessions are hard-suppressed to
  `放松/活泼/温暖` with `warmth <= 0.55`.
- **`get_proactive_context` additive keys**: optional `emotion_state` / `expression`
  (older clients ignore unknown keys). Negative emotion only dampens motivation.
- **SQLite schema v4** (pure increment): `emotion_events` table +
  `affinity_ledger.event_type`, with a `PRAGMA table_info` existence guard on the
  `ALTER TABLE`. In-place upgrade, no rewrite of existing rows, no rollback needed.
- **Config groups** `emotion` / `expression` (`_conf_schema.json`).
- **Read-only WebUI panel** now shows `emotion_state` / `expression.mode`.

### Fixed
- **Star 边界暴露契约方法（TMEAAA-454）**：`TCompanionCore` 现直接暴露
  `get_contract_info` / `get_proactive_context` / `record_emotion_event` /
  `get_emotion_context` / `expression_decision` / `get_life_state` /
  `get_relationship` / `on_proactive_outcome`（薄委托 `self.contract`）。此前只有
  私有 `self.contract`，kanjyou 经 `get_registered_star().star_cls` + `getattr`
  取不到方法，真机 Phase 1/2 全链路静默降级。
- **`get_proactive_context` 情绪 scope 兜底**：用户无 relationships 行时，情绪/
  streak/quota 读取改用 `resolved_persona or DEFAULT_PERSONA_ID`，与
  `record_emotion_event`（`_resolve_persona`）写入的 `default` scope 对齐；修复
  纯负面事件（affinity 下限 0.0，不落 relationships 行）下 `emotion_state` 丢失。

### Notes
- `api_version` stays `1`; `capabilities` stays a `dict[str, bool]` and only gains
  `emotion` / `expression` keys — no breaking change.
- Daily affinity caps: positive `+0.10` (shared with Phase 1), negative `-0.06`,
  affinity floor `0.0`.

## [1.0.0] - 2026-09-20

### Added
- **Frozen Contract v1**: `get_contract_info()`, `get_proactive_context()`, `get_life_state()`, `get_relationship()` — all `async` with per-field degradation.
- **SQLite Schema v3**: `personas`, `life_state_daily`, `life_schedule`, `relationships`, `affinity_ledger`, `interaction_stats`, `open_threads`, `motivation_log` — stores derived values only, no raw messages.
- **LifeState**: Simplified daily state (`activity/energy/scene/summary/as_of`) + weekly schedule template generation.
- **Kanjyou Gate**: Fail-closed contract validation (`core/kanjyou.py`) — rejects mismatched `api_version`, returns `None` instead of guessing.
- **Web API**: Read-only endpoints for `/life-state`, `/relationships`, `/motivation-log`.
- **Diagnostic Command**: `tcompanion_info` — user-triggered, shows contract version + schema version.
- **Motivation System**: `fuse_motivation()` with quota-aware proactive message budget.
- **Relationship Projection**: Per-`umo` relationship view with stage, affinity, bond tracking.
- **Open Threads**: Short-label thread tracking for conversation continuity.
- **Proactive Outcome Logging**: Idempotent receipt tracking with streak/affinity ledger updates.

### Constraints
- Phase 1 only: LifeState (simplified) + Schedule; no relationship/motivation mutations (T2/T3).
- No tmemory reads, no raw message storage.