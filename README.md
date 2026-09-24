# Hearthlight · 守灯

<p><img alt="version" src="https://img.shields.io/badge/version-1.10.0-blue"></p>

<div align="center">
  <img src="./logo.png" alt="Hearthlight · 守灯" width="180">
</div>

Hearthlight · 守灯核心基座：为 AstrBot 提供持久化的关系好感度、生活状态与情绪表达档位，
供上层插件（如 kanjyou）读取使用。

## 能力

- 关系好感度与互动统计：按对话累积好感度，带每日上下限；**不保存消息原文**。
- 生活状态与日程：生成角色当天的活动、精力、场景与一句话摘要。
- 情绪事件与表达档位：根据对话识别感谢、误解、敷衍等情绪，输出对应的表达档位；
  **群聊不会出现亲密档位**，也不继承私聊情绪。
- 可选记忆桥接：若安装了记忆插件（如 tmemory），只读获取其用户画像与回忆，让主动
  内容与语气更贴合对方；未安装或读取失败时自动忽略，行为与未开启时完全一致，
  群聊不会使用画像。
- 生活线：可选地带上天气（填城市后自动查询）、用餐、作息与昨日小结，并在休息时段
  不主动打扰；未填城市或查询失败时自动忽略。**群聊不暴露**任何生活线信息，
  只保存结构化字段，不保存消息原文。
- 群聊理解：了解群的整体活跃度、话题与群内成员熟悉度，并按最短接话间隔、每小时
  次数与群繁忙程度给出**是否适合接话**的建议；群内状态**独立**，不读取也不混入
  私聊关系、情绪或画像，保存的只有计数与短标签。
- 成长：随相处与互动，人物的表达暖度会缓慢提升；有等级上限、可随时清零，关闭后
  回到未开启时的行为。
- 见闻：可选地让角色拥有自己的生活素材——按配置的 RSS/Atom 来源或手填话题，低频
  生成**无原文**的短见闻，供主动消息作话题候选；默认关，开启后受每日条数与刷新
  间隔限制，取源失败自动忽略。见闻**不绑用户身份**、不外发用户数据。
- 对外接口（契约）：`get_contract_info()` / `get_proactive_context()` /
  `get_life_state()` / `get_relationship()` / `record_emotion_event()` /
  `get_emotion_context()` / `expression_decision()` / `get_life_line()` /
  `get_diary()` / `record_group_activity()` / `get_group_context()` /
  `get_growth_context()` / `get_life_content()` / `refresh_life_content()`，
  全部异步、缺失数据时自动降级。
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
core/life_line.py  # 生活线：配置/时间窗/作息推断/日记合成
core/weather.py    # 天气查询（免 key，失败自动忽略）
core/emotion.py    # 情绪事件与表达档位
core/group.py      # 群聊理解：群/成员派生与参与闸门
core/growth.py     # 成长：由既有账本派生等级与表达漂移
core/memory_bridge.py # 记忆插件的只读桥接（可选）
core/kanjyou.py    # kanjyou 接入门禁
_conf_schema.json  # emotion / expression / open_thread / memory_bridge / life_line / group / growth 配置组
docs/CONTRACT.md   # 接口字段与降级说明
tests/             # 单测
```

## 约束

- 只读取记忆插件的公开接口，不写入、不保存消息原文；未安装记忆插件时不受影响。
- 群聊不记好感度、不出现亲密档位，也不使用用户画像；群内熟悉度独立记录，
  不与私聊关系合并，也不跨群聚合。
- 本插件不主动发消息、不自己起调度器。

接口字段、可缺省性与降级矩阵见 **[docs/CONTRACT.md](docs/CONTRACT.md)**。
