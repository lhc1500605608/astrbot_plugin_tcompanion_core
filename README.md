# TCompanion Core

<div align="center">
  <img src="./logo.png" alt="TCompanion Core" width="180">
</div>

TCompanion 核心基座（Phase 1）：为 AstrBot 提供**冻结契约 v1**、SQLite 持久化与
简化版 LifeState / 周模板 Schedule。

## 能力（Phase 1）

- `main.py` Star 骨架，持有 AstrBot `context`；**不自起调度器、不主动发消息**。
- 契约 v1（`core/contract.py`）：`get_contract_info()` / `get_proactive_context()` /
  `get_life_state()` / `get_relationship()`，全部 `async` 且带降级路径。
- SQLite schema v1（`core/db.py`）：`personas` / `life_state_daily` / `life_schedule` /
  `relationships` / `affinity_ledger` / `interaction_stats` / `open_threads` /
  `motivation_log`；**不存消息原文**。
- LifeState（`activity/energy/scene/summary/as_of`）+ 周模板生成当日事件
  （`core/life_state.py`）。
- Kanjyou 情感层 fail-closed 门（`core/kanjyou.py`）：`api_version != 1` 时拒绝并返回
  空结果。

契约字段、可缺省性与降级矩阵见 **[docs/CONTRACT.md](docs/CONTRACT.md)**。

## 开发

```bash
uv venv .venv
uv pip install --python .venv pytest pytest-asyncio ruff

.venv/bin/ruff check .        # 全绿
.venv/bin/python -m pytest    # 单测
```

## 目录

```
main.py            # Star 骨架（context 持有、DB 初始化、诊断指令）
core/contract.py   # 冻结契约 v1
core/db.py         # SQLite schema + 幂等迁移
core/store.py      # 存储读写（仅派生值，无消息原文）
core/life_state.py # LifeState + WeeklySchedule
core/kanjyou.py    # kanjyou fail-closed 门
docs/CONTRACT.md   # 契约文档
tests/             # 单测
```

## 约束（Phase 1）

- 仅 LifeState(简版) + Schedule；不碰关系/动机（T2/T3）。
- 不读 tmemory、不存消息原文。
