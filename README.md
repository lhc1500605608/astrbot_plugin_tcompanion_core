# TCompanion Core

<div align="center">
  <img src="./logo.png" alt="TCompanion Core" width="180">
</div>

TCompanion 核心基座：为 AstrBot 提供**冻结契约 v1（v1.1 增量）**、SQLite 持久化、
简化版 LifeState / 周模板 Schedule，以及情绪事件账本与七档表达决策。

## 能力

- `main.py` Star 骨架，持有 AstrBot `context`；**不自起调度器、不主动发消息**。
- 契约 v1（`core/contract.py`）：`get_contract_info()` / `get_proactive_context()` /
  `get_life_state()` / `get_relationship()`，全部 `async` 且带降级路径。
- v1.1 新增（Phase 2-A/C）：`record_emotion_event()` / `get_emotion_context()` /
  `expression_decision()`；`get_proactive_context()` 追加可选 `emotion_state` /
  `expression`（老客户端忽略未知键即不碎）。
- SQLite schema v4（`core/db.py`）：`personas` / `life_state_daily` / `life_schedule` /
  `relationships` / `affinity_ledger` / `interaction_stats` / `open_threads` /
  `motivation_log` / `emotion_events`；**不存消息原文**。
- LifeState（`activity/energy/scene/summary/as_of`）+ 周模板生成当日事件
  （`core/life_state.py`）。
- 情绪账本与表达档位（`core/emotion.py`）：6 类零 LLM 事件、24h 半衰情绪值、7 档表达；
  **群聊禁止亲密档**且不继承私聊情绪。
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
core/emotion.py    # 情绪事件账本 + 七档表达决策（Phase 2-A/C）
core/kanjyou.py    # kanjyou fail-closed 门
_conf_schema.json  # emotion / expression 配置组
docs/CONTRACT.md   # 契约文档
tests/             # 单测
```

## 约束

- `api_version` 恒为 `1`，仅向后兼容增量（capabilities 保持 `dict`）。
- 不读 tmemory、不存消息原文；群聊不记账且禁止亲密档。
- companion-core 不自起调度器、不自己发消息。
