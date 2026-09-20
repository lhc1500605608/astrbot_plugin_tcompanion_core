# TCompanion Core — 冻结契约 v1

本文件是 Phase 1 冻结契约的**唯一事实来源**。字段的类型、可缺省性与降级行为一旦
发布即冻结；变更需新开 `v2` 章节并同步 `CONTRACT_API_VERSION`。

- 契约版本：`api_version = 1`
- 插件：`astrbot_plugin_tcompanion_core`
- 代码入口：`core/contract.py`

## 1. 通用约定

- 所有契约方法均为 `async`（为 v2 的异步 I/O 预留，避免签名破坏）。
- 返回值为 JSON 可序列化的 `dict`（`dataclass` 通过 `to_dict()` 展开）。
- **每个方法都有降级路径**：存储/上游失败时返回降级结构，不向调用方抛异常。
- 时间字段统一为 ISO-8601 字符串（UTC，`+00:00`）。
- **不存消息原文**：任何表/字段只保存派生值或聚合值（见 §5）。

### 降级标记

除 `get_contract_info()` 外，所有返回值都带 `degraded: bool`：

| 值 | 含义 |
| --- | --- |
| `false` | 数据完整，来自存储或调度演算 |
| `true` | 使用了兜底默认值（存储缺失/异常、persona 未配置等） |

## 2. `get_contract_info() -> dict`

契约元信息。**这是 kanjyou fail-closed 的覆写注入点**（可子类覆写或 monkeypatch）。

| 字段 | 类型 | 可缺省 | 说明 |
| --- | --- | --- | --- |
| `api_version` | `int` | 否 | 契约版本，当前恒为 `1` |
| `plugin` | `str` | 否 | 固定 `astrbot_plugin_tcompanion_core` |
| `plugin_version` | `str` | 否 | 插件版本 |
| `schema_version` | `int` | 否 | SQLite schema 版本；存储异常时为 `0` |
| `capabilities` | `dict[str, bool]` | 否 | `life_state` / `schedule` / `relationship` / `motivation` / `proactive` |

`capabilities` 在 Phase 1 的取值：`life_state/schedule/relationship/motivation/
open_threads/quota=true`，`proactive=false`（companion-core 从不自己发送/调度，
只提供输入与回执）。

## 3. `get_life_state(persona_id) -> dict | None`

当日简化 LifeState。

| 字段 | 类型 | 可缺省 | 说明 |
| --- | --- | --- | --- |
| `persona_id` | `str` | 否 | 人格 ID |
| `activity` | `str` | 否 | 活动标识（如 `working` / `idle`） |
| `energy` | `float` | 否 | 精力 `0.0`–`1.0` |
| `scene` | `str` | 否 | 场景标识，可为空串 |
| `summary` | `str` | 否 | 中文短摘要，可为空串 |
| `as_of` | `str` | 否 | 快照时间（ISO-8601） |
| `degraded` | `bool` | 否 | 见 §1 |

`persona_id` 为空时返回 `None`；存储异常时返回 `degraded=true` 的空态。

## 4. `get_relationship(umo, persona_id=None) -> dict`

关系投影。`stage` 取 5 档之一（`陌生/眼熟/熟悉/亲近/亲密`）；无数据、
群聊会话或异常时返回中性默认且 `degraded=true`。纯读，无副作用。

| 字段 | 类型 | 可缺省 | 说明 |
| --- | --- | --- | --- |
| `umo` | `str` | 否 | 统一消息来源标识（回显） |
| `persona_id` | `str \| None` | 是 | 指定人格；缺省表示取最近关系 |
| `stage` | `str` | 否 | 关系阶段；无数据时 `陌生` |
| `closeness` | `float` | 否 | v1 冻结键，恒等于 `affinity` |
| `affinity` | `float` | 否 | 好感分 `0.0`–`1.0`（T2 加法式新增） |
| `bond` | `bool` | 否 | 专属联结标记（T2 加法式新增） |
| `degraded` | `bool` | 否 | 无数据/群聊/异常时为 `true` |

> **群聊隔离**：群会话（`umo` 含 `GroupMessage`）不读取也不更新私聊
> `(persona_id, user_id)` 关系，`get_relationship` 恒返回中性默认 +
> `degraded=true`（见 §9 与 design-brief §7-5）。

## 5. `get_proactive_context(umo, persona_id=None) -> dict`

下游消费者（kanjyou 等）的聚合入口。**纯读、无副作用**（状态变更只经
`on_proactive_outcome` 与 observe 钩子）。v1 全字段如下：

| 字段 | 类型 | 必含 | 说明 |
| --- | --- | --- | --- |
| `api_version` | `int` | 是 | 恒为 `1` |
| `umo` | `str` | 是 | 回显入参 |
| `persona_id` | `str \| None` | 是 | 回显/解析所得人格；无则 `None` |
| `life_state` | `dict \| None` | 否 | §3 的结构；无 persona 或失败为 `None` |
| `relationship` | `dict \| None` | 否 | `{stage, affinity, bond, mode}`（§5.1） |
| `expression_hints` | `dict \| None` | 否 | `{address, warmth, proactive_bias}`（§5.1） |
| `motivation` | `dict \| None` | 否 | `{reason, score, adopted, blocked_reason, candidates}`（§10） |
| `open_threads` | `str[]` | 否 | 短标签列表；缺省 `[]`；群聊恒 `[]` |
| `quota` | `dict` | 是 | `{hourly_remaining, daily_remaining, allow}` |
| `unanswered_streak` | `int` | 是 | 连续未回应的主动消息数；缺省 `0` |
| `degraded` | `bool` | 是 | 存储异常 / `life_state` 缺失或降级时为 `true` |

**逐字段兜底**：每个域独立解析，任一域异常只让该字段退回默认，不阻断其余字段；
调用方须逐字段 `.get()` 兜底。除 `api_version` 外全部可缺省。

### 5.1 `relationship` / `expression_hints` 派生（确定性）

- `mode`：`陌生→疏离`、`眼熟→礼貌`、`熟悉→放松`、`亲近→亲近`、`亲密→亲密`；
  持有 `bond` 时为 `默契`。
- `expression_hints`：按阶段给出 `address`（陌生/眼熟为「您」，其余「你」）、
  `warmth`、`proactive_bias`；`bond` 使 `warmth +0.1`（上限 1.0）；正的
  `proactive_bias` 乘以 `ignored_decay_factor`（§9.3），负值不变。
  **这些只是给下游表达层的输入**，companion-core 不生成话术。

### 5.2 `quota`（advisory）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `hourly_remaining` | `int` | 每小时剩余额度（上限 1） |
| `daily_remaining` | `int` | 每日剩余额度（上限 3） |
| `allow` | `bool` | `hourly_remaining > 0 and daily_remaining > 0` |

> `quota.allow` 只是**软闸建议**；与 kanjyou 现有安全闸并存，后者仍是权威。
> companion-core 自身**不发送、不调度**：`capabilities.proactive=false`。

群聊隔离：`umo` 含 `GroupMessage` 时 `relationship` 返回中性默认、`open_threads`
恒为 `[]`、`unanswered_streak=0`，不泄露私聊关系/话题。

## 5b. `on_proactive_outcome(umo, *, sent, reason_code, replied=False, ...) -> dict`

写回执：落 `motivation_log` 审计行并更新 `interaction_stats`（streak/账本）。

| 参数/字段 | 类型 | 说明 |
| --- | --- | --- |
| `umo` | `str` | 会话标识；群聊直接 `isolated=true` 且不写私聊状态 |
| `sent` | `bool` | 是否成功发出 |
| `reason_code` | `str` | 动机/拦截原因码（可追溯） |
| `replied` | `bool` | 用户是否已回；`true` 时 streak 归零 |
| `event_id` | `str \| None` | 可选幂等键 |

返回 `{applied, duplicate, isolated, dynamics?}`。

**幂等**：以 `(persona_id, user_id, receipt_key)` 去重；`receipt_key` 取
`event_id`，缺省为 `day|sent|reason_code|replied` 桶。重放不重复计数
streak/账本。`dynamics` 为 `interaction_stats` 投影（§9.3）。

## 5c. `open_threads` 派生（仅短标签）

- 由调用方（observe 钩子）从会话提取**短标签**（如「周末电影推荐未给」），
  经 `Store.upsert_open_thread()` 落库；`sanitize_thread_title()` 强制折叠空白
  并截断到 40 字符，**绝不存消息原文**。
- `get_proactive_context` 取最近 `updated_at` 的前 3 条 open 标签。
- 与 tmemory 边界：原文只存 tmemory；companion-core Phase 1 不直连 tmemory。

## 6. Kanjyou fail-closed 门（`core/kanjyou.py`）

`KanjyouGate.ensure_supported()` 校验 `api_version == 1`，否则抛
`ContractVersionError`。触发 fail-closed 的条件：

| 条件 | 结果 |
| --- | --- |
| 合约对象无 `get_contract_info` | `ContractVersionError` |
| `get_contract_info()` 抛异常 | `ContractVersionError` |
| 返回值非 mapping | `ContractVersionError` |
| 缺 `api_version` 或 `!= 1` | `ContractVersionError` |
| 通过校验但 `get_proactive_context` 失败 | `guarded_proactive_context` 返回 `None` |

`guarded_proactive_context()` 捕获上述错误并返回 `None`（**不发任何内容**）。
测试注入点：向 `KanjyouGate(contract)` 传入任意实现对象，或子类覆写
`ContractV1.get_contract_info()`。

## 7. SQLite schema（`schema_version = 3`）

库文件：`get_astrbot_plugin_data_path()/astrbot_plugin_tcompanion_core/tcompanion_core.sqlite3`。

表：`personas` / `life_state_daily` / `life_schedule` / `relationships` /
`affinity_ledger` / `interaction_stats` / `open_threads` / `motivation_log`
（另有迁移元表 `schema_meta`）。

v2（T2）将关系三表重构为真实模型，键均为 `(persona_id, user_id)`：

- `relationships(persona_id, user_id, affinity, stage, bond, last_active_day,
  last_decay_day, updated_at)` —— 主键 `(persona_id, user_id)`。
- `affinity_ledger(persona_id, user_id, event_id, delta, reason, day,
  created_at)` —— 去重主键 `(persona_id, user_id, event_id)`，只追加。
- `interaction_stats(persona_id, user_id, message_count, proactive_sent,
  proactive_replied, unanswered_streak, reply_delay_sum, reply_delay_count,
  pending_proactive_at, last_interaction_at, updated_at)`。

v3（T3）为 `motivation_log` 追加审计列（`ALTER TABLE`，加法式）：
`umo` / `user_id` / `candidates_json` / `selected_reason` / `adopted` /
`blocked_reason` / `reason_code` / `receipt_key`；索引
`(persona_id, user_id, created_at)` 与唯一索引
`(persona_id, user_id, receipt_key)`（回执幂等）。`open_threads` 增加
`(umo, status, updated_at)` 作用域索引。

> v1/v2 表仅存派生值、无消息原文，故重构/追加均安全；迁移仍幂等：
> 重复 `apply_migrations()` 不改写 `schema_meta`。全新库会依次执行 v1→v3；
> 既有 v2 库会安全升级到 v3。

**隐私不变式**：以上任何表都不含消息原文/正文列。`life_state_daily.summary`
为模型生成的当日生活摘要，`open_threads.title` 为话题标题，均非消息原文。

迁移幂等：`core.db.apply_migrations()` 仅执行 `version > current` 的脚本；
重复调用不改写 `schema_meta`，`Store.migrate()` 可安全重复执行。

## 8. 冻结与变更流程

1. 任何字段的类型/可缺省性变更 → 新开 `v2` 章节。
2. `CONTRACT_API_VERSION` 同步递增。
3. 下游（kanjyou）通过 fail-closed 门感知版本，拒绝未知版本。

## 9. 关系 5 档与好感账本规则（T2）

实现：`core/relationship.py`（纯逻辑）+ `core/store.py`（落库）。契约 API 版本
仍为 `api_version = 1`（仅 schema 升级到 2，字段为加法式，向后兼容）。

### 9.1 五个阶段（阈值）

| 档 | 名称 | `affinity` 区间 |
| --- | --- | --- |
| 1 | 陌生 | `[0.00, 0.20)` |
| 2 | 眼熟 | `[0.20, 0.40)` |
| 3 | 熟悉 | `[0.40, 0.60)` |
| 4 | 亲近 | `[0.60, 0.80)` |
| 5 | 亲密 | `[0.80, 1.00]` |

- 升档：越过阈值即刻升。**降档迟滞 `0.02`**：需低于当前档下阈值 `0.02` 才降，
  迟滞带内保持原档（`stage_for(affinity, previous)`）。
- `bond`：仅当存在专属事件且阶段 ≥ 亲近 时为真，降至亲近以下自动回退。

### 9.2 账本规则（绝不单调膨胀）

| 规则 | 值 | 实现 |
| --- | --- | --- |
| 单次事件 Δ 上限 | `+0.03` | `cap_event_delta` |
| 每 `(persona, user)` 每日正向 Δ 上限 | `+0.10` | `effective_delta` + `ledger_daily_positive` |
| 去重键 | `(persona_id, user_id, event_id)` | `affinity_ledger` 主键，重复幂等 |
| 负数事件 | 不扣分（Phase 2 情绪账本） | `cap_event_delta` 返回 `0` |
| 无互动衰减 | 每日 `-0.005`，只向 `0` 收敛 | `decayed` / `Store.apply_decay` |

- 每次实际入账写 `affinity_ledger(delta, reason, day, created_at)`，可回溯审计。
- `Store.apply_affinity_event()` 返回 `{applied, duplicate, delta, state}`；
  `Store.apply_decay()` 幂等（同一日重复调用不重复衰减）。
- **隔离**：群聊会话不读取、不更新私聊关系（§4、§9.3）。

### 9.3 InteractionDynamics

`core/relationship.py::InteractionDynamics` + `interaction_stats`：

- `unanswered_streak`：连续「主动已发但用户未回复」计数；用户回复或
  `record_proactive_outcome(replied=True)` 归零。
- `avg_reply_delay`：`reply_delay_sum / reply_delay_count`（秒），即主动消息到
  用户回复的平均延迟。
- `ignored_decay_factor = 1 / (1 + unanswered_streak)`：被忽略越多越低，供上层
  降低主动度（design-brief §7-3），不为负、不归零。

## 10. Motivation 融合、OpenThreads 与审计（T3）

实现：`core/motivation.py`（纯逻辑）+ `core/store.py`（落库）。契约 API 版本
仍为 `api_version = 1`（仅 schema 升级到 3，字段为加法式）。

### 10.1 候选打分（确定性）

`fuse_motivation(...)` 融合 **生活事件 + 未完成话题 + 时段**，产生候选集并按
`(-score, key)` 排序；分数 clamp 到 `[0,1]` 并四舍五入到 4 位，保证同输入同输出。

| 来源 | 基础分 | 说明 |
| --- | --- | --- |
| `open_thread` | `0.70`（最新一条 `+0.15`） | 每个未完成话题一个候选 |
| `life_event` | `0.45`（`+ min(0.10, energy*0.10)`） | 当前活动 |
| `time:<window>` | `0.30` | 早/中/午/晚/深夜窗口 |

- 阶段加成：`stage × 0.05`（按 `STAGE_ORDER` 索引，最高 4 档）。
- `unanswered_streak` 衰减：所有分数乘以 `ignored_decay_factor`。
- `adopted`：`unanswered_streak >= 3` → `blocked_reason=unanswered_streak`；
  否则 `quota.allow=false` → `blocked_reason=quota`；否则采纳。
  被拦截时仍回填 `score/reason/candidates` 以便追溯。
- 返回 `motivation = {reason, score, adopted, blocked_reason, candidates[]}`。

### 10.2 `motivation_log` 审计列

`log_motivation(...)` 追加一行（只存派生值）：

| 列 | 说明 |
| --- | --- |
| `umo` / `user_id` / `persona_id` | 作用域 |
| `candidates_json` | 候选集（含 key/label/reason/score，短标签） |
| `selected_reason` | 选中理由 |
| `adopted` | 是否采纳（`sent`） |
| `blocked_reason` | 拦截原因（未发时的 `reason_code`） |
| `reason_code` | 回执原因码 |
| `receipt_key` | 幂等键（唯一索引） |
| `created_at` | 时间 |

- 面板读取：`Store.list_motivation_log()`（`main.py` 只读 Web API）。
- 额度统计：`Store.count_proactive_sent()` 数 `kind='proactive_outcome' AND
  adopted=1` 且 `created_at >= since` 的行，驱动 §5.2 的 `quota`。
