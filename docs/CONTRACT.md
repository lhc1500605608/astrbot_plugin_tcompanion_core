# TCompanion Core — 冻结契约 v1（v1.2 修订）

本文件是 Phase 1 冻结契约的**唯一事实来源**。字段的类型、可缺省性与降级行为一旦
发布即冻结；变更需新开 `v2` 章节并同步 `CONTRACT_API_VERSION`。

- 契约版本：`api_version = 1`（**v1.2 为纯向后兼容增量**，见 §11/§12/§13）
- 插件：`astrbot_plugin_tcompanion_core`（`plugin_version = 1.2.0`）
- 代码入口：`core/contract.py`

> v1.1 变更摘要（不破坏任何 v1.0.0 客户端）：
> 1. `capabilities` **保持 `dict[str, bool]`**，仅追加 `emotion` / `expression`；
> 2. 新增 `record_emotion_event` / `get_emotion_context` / `expression_decision`；
> 3. `get_proactive_context` 追加**可选**键 `emotion_state` / `expression`；
> 4. schema 升级到 `4`（新表 `emotion_events` + `affinity_ledger.event_type`）。
> `api_version` 恒为 `1`；老客户端忽略未知键即不受影响。
>
> v1.2 变更摘要（不破坏任何 v1.x 客户端）：
> 1. `capabilities` **保持 `dict[str, bool]`**，仅追加 `open_threads_followup`；
> 2. 新增 `record_open_thread` / `get_open_threads` / `close_open_thread` /
>    `mark_thread_followup`（同时挂 Star 实例与 `ContractV1`）；
> 3. `get_proactive_context` 追加**可选**键 `open_thread_details`，
>    `motivation.candidates[]` 追加可选 `thread_id`；`open_threads`（`str[]`）**冻结不变**；
> 4. schema 升级到 `5`（`open_threads` 生命周期加列，纯增量、回填、不改旧行）。

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
| `capabilities` | `dict[str, bool]` | 否 | `life_state` / `schedule` / `relationship` / `motivation` / `open_threads` / `quota` / `proactive` / `emotion` / `expression` / `open_threads_followup` |

`capabilities` 恒为 **`dict[str, bool]`**（v1.0.0 起即是 map，从未是数组；改成
数组属于破坏性变更，见 §8）。取值：`life_state/schedule/relationship/motivation/
open_threads/quota=true`，`proactive=false`（companion-core 从不自己发送/调度，
只提供输入与回执）；v1.1 追加 `emotion=true` / `expression=true`；v1.2 追加
`open_threads_followup=true`（下游据此决定是否走未完话题续接链路）。

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
| `open_threads` | `str[]` | 否 | 短标签列表（**冻结**）；缺省 `[]`；群聊恒 `[]` |
| `open_thread_details` | `dict[]` | 否（v1.2 新增） | `{thread_id,label,kind,status,last_seen,followup_count,confidence}`；缺省 `[]`；群聊恒 `[]`（§13） |
| `quota` | `dict` | 是 | `{hourly_remaining, daily_remaining, allow}` |
| `unanswered_streak` | `int` | 是 | 连续未回应的主动消息数；缺省 `0` |
| `emotion_state` | `dict \| None` | 否（v1.1 新增） | `{state, valence, last_event, as_of}`（§11.3）；群聊恒 `None` |
| `expression` | `dict \| None` | 否（v1.1 新增） | `{mode, style_hints, reason}`（§12）；群聊为抑制后的安全档 |
| `degraded` | `bool` | 是 | 存储异常 / `life_state` 缺失或降级时为 `true` |

> `emotion_state` / `expression` 是 v1.1 的**可选追加键**：老客户端（kanjyou
> v2.5.0）忽略未知键即不碎；情绪只影响 `motivation` 评分（负向降权，**绝不提升**）
> 与 `expression.style_hints.proactive_bias`，`quota` 结构保持冻结不变。
> `open_thread_details` 是 v1.2 的**可选追加键**（与冻结的 `open_threads` 同批次、
> 同顺序）；每条 `motivation.candidates[]` 追加可选 `thread_id`，供下游在发送后续接
> 回执（`mark_thread_followup`）。

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

- 由调用方（observe 钩子）从会话提取**短标签**（如「周末电影推荐未给」），经
  `record_open_thread()`（写入侧）落库；`sanitize_thread_title()` 强制折叠空白并
  截断到 40 字符，`thread_id_for()` 由 `kind|规范化标签` 派生稳定 id，
  **绝不存消息原文**（§13）。
- `get_proactive_context` 取最近 `updated_at` 的前 3 条 **open** 标签，冻结的
  `open_threads`（`str[]`）与新的 `open_thread_details`（含 `thread_id`/`kind`/
  `status`/`last_seen`/`followup_count`/`confidence`）来自同一批次、同一顺序。
- `get_open_threads()` 返回 `open` + `stale`（按新鲜度排序），供下游自行按状态过滤。
- 与 tmemory 边界：原文只存 tmemory；companion-core 不直连 tmemory。

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

### 6.1 Star 暴露面（跨插件真机边界）

下游插件（kanjyou `CompanionContextAdapter`）通过
`context.get_registered_star(name).star_cls` 拿到 **Star 实例**，再
`getattr(star, "<method>")` 调用。因此契约方法必须同时挂载在 Star 实例
（`main.py` 的 `TCompanionCore`）上，而不只是私有 `self.contract`：每个方法
都是指向 `ContractV1` 的薄委托（`main._contract()`）。缺失即真机静默降级
（fail-closed，TMEAAA-454）。Star 未初始化时委托抛 `RuntimeError`，调用方按
fail-closed 处理。回归由 `tests/test_star_surface.py` 钉住：断言 Star 的公开
async 面与 `ContractV1` 完全一致。

## 7. SQLite schema（`schema_version = 5`）

库文件：`get_astrbot_plugin_data_path()/astrbot_plugin_tcompanion_core/tcompanion_core.sqlite3`。

表：`personas` / `life_state_daily` / `life_schedule` / `relationships` /
`affinity_ledger` / `interaction_stats` / `open_threads` / `motivation_log` /
`emotion_events`（另有迁移元表 `schema_meta`）。

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

v4（v1.1，Phase 2-A）为**纯增量**：新增 `emotion_events` 表（主键
`(persona_id, user_id, dedupe_key)` + `(persona_id, user_id, ts)` 索引），并为
`affinity_ledger` 追加 `event_type` 列。列变更带 `PRAGMA table_info` 存在性 guard，
重复执行不报错；**不改写任何旧行**，旧代码（v1.0.0）仍可读写（不查
`emotion_events`；`affinity_ledger` 用显式列名插入，新列取默认 `''`），故无需回滚。

- `emotion_events(persona_id, user_id, dedupe_key, ts, event_type, delta, reason,
  day)` —— 只追加；`delta` 为**逐事件规范值**（`±0.03` 内），不含消息原文。

v5（v1.2，Phase 2-B）为**纯增量**：为 `open_threads` 追加生命周期列 `kind`（默认
`'topic'`）/ `last_seen_ts` / `last_followup_ts` / `followup_count`（默认 `0`）/
`source` / `confidence`（默认 `0.0`）/ `dedupe_key`（可空）/ `closed_reason`，并将
`last_seen_ts` 一次性回填为 `updated_at`。所有 `ALTER TABLE` 均带 `PRAGMA table_info`
存在性 guard，重复执行不报错；回填只作用于空值，**不改写任何旧行的既有列**。旧代码
（v1.1.x）用显式列名插入，新列自动取默认值，故无需回滚。新增索引
`(umo, persona_id, status, last_seen_ts)` 与 `(umo, persona_id, dedupe_key)`。

> v1/v2 表仅存派生值、无消息原文，故重构/追加均安全；迁移仍幂等：
> 重复 `apply_migrations()` 不改写 `schema_meta`。全新库会依次执行 v1→v5；
> 既有 v2/v3/v4 库会安全原地升级到 v5。

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
| 每日负向 Δ 上限（v1.1） | `-0.06` | `apply_emotion_affinity_delta` + `ledger_daily_negative` |
| 去重键 | `(persona_id, user_id, event_id)` | `affinity_ledger` 主键，重复幂等 |
| 负数事件（v1.0） | 不扣分 | `cap_event_delta` 返回 `0`（仅 Phase 1 正向路径） |
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

## 11. 情绪事件账本（v1.1 · Phase 2-A）

实现：`core/emotion.py`（纯逻辑）+ `core/store.py`（`apply_emotion_event` 落库）。
契约 API 版本仍为 `api_version = 1`（仅 schema 升级到 4，字段/方法为加法式）。

### 11.1 `record_emotion_event(umo, *, event_type, reason="", dedupe_key=None, now=None) -> dict`

零 LLM：事件由 kanjyou 侧按词表/回执状态机判定后上报，core 只落账。

| `event_type` | 含义 | `delta` |
| --- | --- | --- |
| `valued_reply` | 主动消息在回复窗口内收到回应 | `+0.03` |
| `ignored_proactive` | 主动消息在忽略窗口内无回应 | `-0.02` |
| `gratitude` | 命中感谢词表 | `+0.02` |
| `misunderstood` | 命中误解/不满词表 | `-0.03` |
| `sudden_warmth` | 命中关心/温柔词表 | `+0.02` |
| `cold_shoulder` | 连续敷衍计数达阈值 | `-0.01` |

返回：`{applied, duplicate, isolated, event, affinity, stage, persona_id, degraded}`
（`event = {event_type, delta, ts, day, dedupe_key}`，无原文）。降级路径附 `reason`
（`bad_umo` / `group_isolated` / `unknown_event_type` / `storage_error`）。

- **幂等/互斥**：主键 `(persona_id, user_id, dedupe_key)`。两类主动回执
  （`valued_reply` / `ignored_proactive`）**共用** `proactive:{send_ts}` 键 → 先到者
  落库，后到者返回 `duplicate=true` 且不改账。单条入站消息也只结算一次
  （`msg:{message_id}`，缺省 `msg:{umo}:{int(ts)}`）；缺省键为
  `{day}|{event_type}`（每日每型至多一次）。
- **群聊隔离**：群会话 `isolated=true`，不写账、不改关系。
- **fail-closed**：未知 `event_type` 拒绝；存储异常返回 `degraded=true` 且不抛。
- **账本**：情感权重入 `emotion_events`（规范 delta）；好感变更入 `affinity_ledger`
  （写 `event_type` 列），受每日 `+0.10` / `-0.06` 与好感下限 `0.0` 约束（§9.2）。

### 11.2 `get_emotion_context(umo, persona_id=None) -> dict`

纯读、确定性、有界。返回 `{state, valence, recent, last_event, as_of, degraded}`：

- `valence = Σ delta_i × 0.5^(age_hours/24)`（72h 窗口、半衰 24h），clamp `[-1, 1]`。
- `recent`：最多 5 条 `{event_type, delta, ts}`，**绝不会含消息原文**。
- 群聊 / 异常：返回降级中性态（`平静` / `0.0` / `[]`，`degraded=true`）。

### 11.3 情绪状态（优先级首命中）

| 优先级 | `state` | 条件 |
| --- | --- | --- |
| 1 | `受伤` | 12h 内出现 `misunderstood` **或** `valence ≤ -0.35` |
| 2 | `回避` | `unanswered_streak ≥ 2` **或** 48h 内 `ignored_proactive ≥ 2` **或** `valence ≤ -0.15` |
| 3 | `期待` | 12h 内正向事件 ≥ 1 **且** `valence ≥ +0.15` |
| 4 | `开心` | `valence ≥ +0.25` |
| 5 | `平静` | 其余 |

## 12. 表达决策（v1.1 · Phase 2-C）

### 12.1 `expression_decision(umo, persona_id=None) -> dict`

返回 `{api_version, mode, style_hints, reason, degraded}`，同样纯读、无副作用。

`mode ∈ {回避, 受伤, 放松, 活泼, 温暖, 亲近, 爱意}`，私聊按优先级首命中：

| 优先级 | `mode` | 条件 |
| --- | --- | --- |
| 1 | `回避` | `emotion.state == 回避` 或 `unanswered_streak ≥ 2` |
| 2 | `受伤` | `emotion.state == 受伤` |
| 3 | `爱意` | `bond` 且 `stage == 亲密` 且 `valence ≥ 0` |
| 4 | `亲近` | `stage ∈ {亲近, 亲密}` |
| 5 | `温暖` | `stage ≥ 熟悉` 且 `valence ≥ 0` |
| 6 | `活泼` | `valence ≥ +0.2` 且 `energy ≥ 0.6` |
| 7 | `放松` | 兜底 |

`style_hints = {tone, warmth, length_bias, proactive_bias}`（基准表见
`core/emotion.py::STYLE_HINTS`）。`reason` 为人类可读理由，供日志/面板。

### 12.2 群聊硬抑制

群会话**永不**产生 `回避/受伤/亲近/爱意`：越档即回落 `放松`，`warmth` 再被
`min(warmth, 0.55)` 截断，且不继承私聊情绪/关系。该抑制在 companion-core 与
kanjyou 两层各执行一次（纵深防御）。

### 12.3 与 kanjyou `persona_state` 的关系

companion 可用时 `expression.mode + style_hints` 是**档位权威约束**；kanjyou 的
`persona_state` 降为**风格细节**（数值调整总量 ≤ ±0.10，且不得改变 `mode`）。
companion 不可用 → 完全走 `persona_state`（= v2.4.0 行为，零回归）。

## 13. 未完话题续接（v1.2 · Phase 2-B）

实现：`core/motivation.py`（kind/阈值/`thread_id_for` 纯逻辑）+ `core/store.py`
（`open_threads` 落库与生命周期）+ `core/contract.py`（写入/读取/关闭/回执四方法）。
契约 API 版本仍为 `api_version = 1`（仅 schema 升级到 5，方法/字段为加法式）。

### 13.1 数据模型与去重

`open_threads` 在既有列上追加 `kind` / `last_seen_ts` / `last_followup_ts` /
`followup_count` / `source` / `confidence` / `dedupe_key` / `closed_reason`（§7 v5）。

- `kind ∈ {commitment, pending_question, plan, topic}`（未知值 fail-closed 拒绝）。
- `status ∈ {open, stale, closed}`。
- `thread_id` 由写入侧派生：`dedupe_key` 优先，否则 `thread:<sha1(kind|规范化标签)[:12]>`。
  同一 `kind|label` 重复提及命中同一行 → 只 bump `last_seen_ts`/`updated_at`，**不新增行**。
- 隐私：`title` 一律经 `sanitize_thread_title()`（折叠空白、≤40 字）；**无原文列**。

### 13.2 四个契约方法

| 方法 | 返回 | 说明 |
| --- | --- | --- |
| `record_open_thread(umo, *, label, kind, reason="", dedupe_key=None, confidence=1.0, source="", now=None)` | `dict` | 写入/刷新一条；`label` 缩短为标签 |
| `get_open_threads(umo, limit=3, persona_id=None)` | `dict[]` | 纯读；返回 `open`+`stale` |
| `close_open_thread(umo, thread_id, reason="")` | `dict` | `closed_reason ∈ {answered, expired, superseded, …}` |
| `mark_thread_followup(umo, thread_id, now=None)` | `dict` | 递增 `followup_count` + 记 `last_followup_ts` |

- `record_open_thread` 返回 `{thread_id, umo, label, kind, status, isolated, applied, degraded}`
  （群聊 `isolated=true`；未知 `kind` → `reason=unknown_kind, degraded=true`；空标签 →
  `empty_label`；存储异常 → `storage_error, degraded=true`，**绝不抛**）。
- `get_open_threads` 每条为 `{thread_id, label, kind, status, last_seen, followup_count,
  confidence}`；群聊/异常返回 `[]`。
- `close_open_thread` / `mark_thread_followup` 均按 `umo` 作用域；群聊为空操作
  （`isolated=true`）；未命中 → `closed=false` / `reason=not_found`；异常 `degraded=true`。
- **群聊隔离**：群会话不写、不读、不关闭、不回执私聊未完话题（结构隔离）。

### 13.3 生命周期（`Store.expire_open_threads`，core 侧）

- `open` → 超 `ttl_days`（默认 3）未提及 → `stale`（仍存，下游不作为续接候选）。
- `stale`/`open` → 超 `expire_days`（默认 14）未提及 → `closed(reason=expired)`。
- 被回应/完成 → `close_open_thread(reason=answered)`，不再作为候选。
- 单 `(umo, persona_id)` 的 `open` 超 `max`（默认 20）→ 按 `last_seen_ts` LRU
  关闭最旧，`closed_reason='superseded'`。阈值**全局**，不随关系阶段变化。

### 13.4 消费契约（kanjyou 侧，见 plan §5）

`get_proactive_context().open_thread_details` 中 `status=open` 且 `confidence ≥ 0.6`
的条目才可作为续接候选；每次主动消息**至多续接 1 条**，且需满足冷却
（`last_followup_ts`）、`followup_count < followup_max`、最小间隔、`quota.allow`、
`unanswered_streak < 3`、`expression.proactive_bias ≥ 0` 等闸门。发送成功后调用
`mark_thread_followup` 递增计数。core 缺失 / `api_version≠1` / 无
`open_threads_followup` capability → 下游完全不调用（= 现状，零回归）。
