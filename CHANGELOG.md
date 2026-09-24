# Changelog

All notable changes to this project will be documented in this file.

## [1.9.0] - 2026-09-24

### Added
- **Shared identity map (offline person fallback)**: read-only consumption of
  `<plugin_data>/_shared/identity_map.json` (single writer: tmemory). When the
  online bridge yields no person, `resolve_person` looks up the normalized
  `(adapter, adapter_user_id)` — WebChat `webchat!<user>!<conv>` decoded to the
  sender id. **Fail-closed** (missing/corrupt/wrong-version → `None`), mtime
  cached, groups never touch the file; without an export file every contract
  output is byte-identical to v1.8.0. `docs/CONTRACT.md` §20.
- `capabilities["identity_map"] = true` (additive key; `api_version` stays `1`,
  no schema change — still `8`).
- Tests: `tests/test_identity_map.py`.

### Changed
- Status panel person/merge cards group rows by `person_key` and drop the
  "may be the same person" heuristic labels; merge target preselects the
  canonical key (i18n cleanup in en/zh).

## [1.8.0] - 2026-09-24

### Added
- **Person merge**: WebUI People/Merge card (`POST /person/merge` + rollback),
  bind-time migrate/prompt, `Store.migrate/judge/list_person_key_candidates`
  helpers; `capabilities["person_merge"] = true` (additive, `api_version` stays
  `1`, no schema change). Tests: `tests/test_person_merge.py`.

## [1.7.0] - 2026-09-24

### Added
- **Life content (见闻)**: `get_life_content` / `refresh_life_content`,
  `life_content` table (schema `7 → 8`, pure additive), `content` config group
  (off by default), bounded generation with SSRF guard and optional
  summarizer; `capabilities["life_content"] = true`. `docs/CONTRACT.md` §19.
  Tests: `tests/test_life_content.py`.

## [1.6.0] - 2026-09-23

### Added
- **Group understanding (3-A)**: `record_group_activity(umo, *, member_id,
  topic, now)` stores bounded per-group aggregates only (hourly/day counts, a
  sanitized short topic label, last activity) plus a local member familiarity
  counter keyed `group:<session>#<member>`. **Never raw text, never merged with
  a private `person`, never aggregated across groups.** Private scopes are a
  no-op (`isolated=true`).
- `get_group_context(umo, persona_id=None, *, member_id=None)`: group →
  `{group:{member_count, activity_level, topic, topic_age_min, last_activity},
  participation:{allow, reason, cooldown_remaining_sec, hourly_remaining},
  member:{member_key, familiarity, is_known}, degraded}`; private or a disabled
  section → `isolated=true`. The advisory gate order is `cooldown` (default
  90s) → `hourly_limit` (default 6/h) → `group_busy` (default 120/h) → `ok`.
- `get_proactive_context` group branch gains the optional `group` /
  `participation` keys (private-only keys stay absent for groups).
- **Growth (3-C)**: `get_growth_context(umo, persona_id=None)` derives
  `{growth:{level, progress, max_level, traits}, drift:{warmth_delta,
  verbosity_delta}}` deterministically from the existing ledger (affinity/stage,
  emotion events, active days) — zero LLM, zero new ingest. `expression_decision`
  adds a bounded growth drift onto `style_hints.warmth` (`+0.00`~`drift_cap`,
  hard cap `0.05`) and **never changes `mode`**. Groups → isolated empty.
- **Config**: new `group` and `growth` groups (`_conf_schema.json`) with
  user-facing copy only (what it does / default / unit).
- **Storage**: schema `v6 → v7`, pure additive `CREATE TABLE IF NOT EXISTS`
  (`group_activity`, `group_members`, `growth_state` with `reset_at`);
  migration is idempotent and never rewrites existing rows.
- **Contract**: `capabilities` gains `group_aware: true` and `growth: true`;
  `api_version` stays `1`.
- **Rollback**: disabling `group.enabled` / `growth.enabled` — or setting
  `growth.reset` — falls back to the previous behaviour; missing/erroring data
  degrades per-capability and never raises.
- `docs/CONTRACT.md` §17, §18.

## [1.5.1] - 2026-09-23

### Changed
- **Display name**: 插件外显名统一为 **Hearthlight · 守灯**（插件标识名
  `astrbot_plugin_tcompanion_core`、行为、配置键与契约均不变）；README 标题、
  插件库/面板显示名与状态页标题同步更新。

## [1.5.0] - 2026-09-23

### Added
- **Person identity bridge**: `MemoryBridge.resolve_person(umo)` consumes the
  memory plugin's public read-only `resolve_person` (probed with `hasattr`),
  returning the authoritative `person_id` (= `canonical_user_id`) for private
  scopes. Results are cached per `umo` for `memory_bridge.ttl_min`, including
  negative results. **Fail-closed**: missing/disabled/timeout/error/group/empty
  all return `None`, and the caller falls back to `parse_umo()` — v1.4.0
  behaviour.
- **Person-keyed private state (v1.5)**: private relationship / affinity /
  emotion / life-line / ledger / diary rows move from `(persona_id, user_id)` to
  `(persona_id, person_id)`; all read and write paths resolve the identity the
  same way. **Groups stay `group:<session_id>` and never aggregate across
  people.** Person is decoupled from persona (same person + different bot
  persona stays two rows).
- **Contract increment**: `get_contract_info().capabilities` gains
  `identity_binding: true`; `get_proactive_context` gains the optional
  `person_id` key (private scopes only, omitted when unresolved so the output
  stays byte-identical to v1.4.0). `api_version` stays `1`; no schema change
  (still `v6`).
- **One-time idempotent migration**: `Store.migrate_person_keys(person_id,
  aliases)` merges each adapter's legacy private rows into `(persona_id,
  person_id)`, writing a JSON backup first. A repeat call is a no-op; group rows
  are never migrated. `Store.rollback_person_migration(backup_path=None)`
  restores the pre-migration rows. Exposed as `POST /person/migrate` and
  `POST /person/migrate/rollback` plus Star delegates
  `migrate_person` / `rollback_person_migration`. Never runs per message.
- `docs/CONTRACT.md` §16.

### Notes
- With the memory plugin unavailable the private key reverts to
  `parse_umo().user_id` and every payload matches v1.4.0 (regression-guarded).
- Migration merges `relationships`/`interaction_stats` (affinity max, counters
  summed, timestamps newest, streak max) and re-keys the append-only ledgers,
  keeping the target row on conflict.

## [1.4.0] - 2026-09-23

### Added
- **Life line (Phase 2-D)**: schema **v6** adds three additive tables —
  `sleep_windows` (`persona_id,user_id,day,start_min,end_min,source`),
  `life_events` (`persona_id,user_id,ts,kind,payload_json,dedupe_key`,
  `UNIQUE(persona_id,user_id,dedupe_key)` + `INSERT OR IGNORE`) and `life_diary`
  (`persona_id,user_id,day,summary,mood`, `UNIQUE(persona_id,user_id,day)`).
  Pure increment: no existing table/row is touched; old code keeps working.
- **`LifeState` optional fields** `weather` / `meal` / `sleep` / `quiet`
  (v1.4 additive). Defaults stay `None` and `to_dict()` omits them, so the
  default structure is byte-identical to v1.3.0.
- **Weather dimension** (`core/weather.py`): zero-key Open-Meteo geocoding +
  forecast (`current=temperature_2m,weather_code,precipitation`), in-memory TTL
  cache (45 min, never persisted), 3s timeout, **fail-closed** on no network /
  timeout / parse error. `weather_api_base` overrides both endpoints (offline
  stub); an empty `life_city` turns the dimension off.
- **Sleep-window inference** (`core/life_line.py`): a 14-day hour-of-day
  histogram of recent private interactions infers onset/wake from the longest
  zero-activity block (>=4h, wrap-aware), clamped to onset `20:00–03:00` / wake
  `05:00–11:00`; insufficient samples fall back to `23:00–07:30`. Stored per day
  with `source=inferred|default`.
- **Meal windows**: configurable breakfast/lunch/dinner windows; entering a
  window records a deduped `life_events` row (`meal:{slot}:{day}`).
- **Daily diary** (zero LLM): reading a day lazily synthesizes the previous
  day's diary deterministically from its sleep window, meal slots, activity and
  emotion — `INSERT OR IGNORE`, never raw text.
- **Quiet-hours suppression**: `fuse_motivation(quiet=...)` gate priority is
  `unanswered_streak` > `quiet_hours` > `quota`; under quiet the payload reports
  `quota.allow=false` and `motivation.blocked_reason="quiet_hours"`.
  `proactive_opt_in` or an interaction in the last 10 minutes exempts; group
  scopes never participate.
- **Contract**: `get_life_line(umo, day=None) -> dict`,
  `get_diary(umo, day=None) -> dict | None`, and the optional
  `get_proactive_context` key `life_detail` (weather/meal/sleep/quiet/diary;
  private scopes only, group scopes stripped). `capabilities` gains
  `life_line: true`; `api_version` stays `1`.
- **Config group** `life_line` (`life_line_enabled` / `life_city` /
  `meal_reminders_enabled` / `sleep_window_auto` / `quiet_hours` /
  `proactive_opt_in` / meal windows + advanced weather keys). Existing keys,
  defaults and behaviour are unchanged.
- `docs/CONTRACT.md` §15; schema §7 updated to v6.

### Notes
- `api_version` stays `1`. With the life line disabled the
  `get_proactive_context` output is field-for-field identical to v1.3.0.
- Privacy: group scopes expose no life line/private detail; only structured
  fields are stored (codes/windows/counts/a synthesized summary), never raw
  message text; weather lives only in an in-memory, clearable cache.

## [1.3.0] - 2026-09-22

### Added
- **Optional memory bridge (Phase 2-E)**: `core/memory_bridge.py::MemoryBridge`
  resolves a memory plugin through the star registry (activated check) and calls
  its public read-only APIs (`recall_for_prompt`, plus `get_profile_for_prompt`
  probed with `hasattr`). Each call is wrapped in `asyncio.wait_for` (default 2s)
  and results are cached per scope for a short TTL. Fail-closed: a missing
  plugin / disabled switch / timeout / error / no data all return `None`, so the
  output stays byte-identical to v1.2.0. Read-only, no raw text, counters only
  (`hit`/`degrade`/`timeout`).
- **`get_proactive_context` additive key `memory`**: optional
  `{snippets, profile{facets,summary,highlights}, as_of}`; absent entirely when
  the bridge is unavailable or has no data. Group scopes receive `snippets`
  only — the profile is never fetched or returned for a group.
- **`expression_decision` memory nudge**: with a profile (private scope) the
  `style_hints["warmth"]` rises by at most +0.05 (base + `MEMORY_WARMTH_MAX_DELTA`),
  never changing `mode`; groups and memory-less scopes are unchanged.
- **`fuse_motivation(memory_hints=...)`**: an additive, ranking-only signal — a
  candidate whose label overlaps a profile-derived hint gains at most +0.05;
  gates (`allow`/`adopted`/`blocked_reason`) and lifecycle are untouched.
- **`get_contract_info().capabilities`** gains `memory_bridge: true` (map shape
  stays `dict[str, bool]`).
- **Config group** `memory_bridge` (`enabled`/`plugin_name`/`timeout_sec`/
  `limit`/`ttl_min`); flat `memory_bridge_*` keys are accepted too.
- `docs/CONTRACT.md` §14.

### Notes
- `api_version` stays `1`; no schema change (`schema_version` stays `5`).
- Read-only bridge: companion-core never writes to the memory plugin, and never
  relays or stores message bodies. No new LLM calls.

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