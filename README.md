# TCompanion Core

<div align="center">
  <img src="./logo.png" alt="TCompanion Core" width="180">
</div>

TCompanion 核心基座：为 AstrBot 提供持久化的关系好感度、生活状态与情绪表达档位，
供上层插件（如 kanjyou）读取使用。

## 能力

- 关系好感度与互动统计：按对话累积好感度，带每日上下限；**不保存消息原文**。
- 生活状态与日程：生成角色当天的活动、精力、场景与一句话摘要。
- 情绪事件与表达档位：根据对话识别感谢、误解、敷衍等情绪，输出对应的表达档位；
  **群聊不会出现亲密档位**，也不继承私聊情绪。
- 可选记忆桥接：若安装了记忆插件（如 tmemory），只读获取其用户画像与回忆，让主动
  内容与语气更贴合对方；未安装或读取失败时自动忽略，行为与未开启时完全一致，
  群聊不会使用画像。
- 对外接口（契约）：`get_contract_info()` / `get_proactive_context()` /
  `get_life_state()` / `get_relationship()` / `record_emotion_event()` /
  `get_emotion_context()` / `expression_decision()`，全部异步、缺失数据时自动降级。
- 本插件**不主动发消息、不自起调度器**，仅提供数据与决策。

## 界面

- 状态面板：`pages/status`，可查看各角色的好感度与生活状态。

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
core/contract.py   # 对外接口（契约）
core/db.py         # SQLite 建表与迁移
core/store.py      # 存储读写（仅派生值，无消息原文）
core/life_state.py # 生活状态与周模板日程
core/emotion.py    # 情绪事件与表达档位
core/memory_bridge.py # 记忆插件的只读桥接（可选）
core/kanjyou.py    # kanjyou 接入门禁
_conf_schema.json  # emotion / expression / open_thread / memory_bridge 配置组
docs/CONTRACT.md   # 接口字段与降级说明
tests/             # 单测
```

## 约束

- 只读取记忆插件的公开接口，不写入、不保存消息原文；未安装记忆插件时不受影响。
- 群聊不记好感度、不出现亲密档位，也不使用用户画像。
- 本插件不主动发消息、不自己起调度器。

接口字段、可缺省性与降级矩阵见 **[docs/CONTRACT.md](docs/CONTRACT.md)**。
