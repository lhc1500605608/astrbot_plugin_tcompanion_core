# Changelog

All notable changes to this project will be documented in this file.

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