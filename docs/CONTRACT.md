# TCompanion Core — 冻结契约 v1（v1.10 修订）

本文件是 Phase 1 冻结契约的**唯一事实来源**。字段的类型、可缺省性与降级行为一旦
发布即冻结；变更需新开 `v2` 章节并同步 `CONTRACT_API_VERSION`。

- 契约版本：`api_version = 1`（**v1.10 为纯向后兼容增量**，见 §11–§21）
- 插件：`astrbot_plugin_tcompanion_core`（`plugin_version = 1.10.0`）
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
> 4. schema 升级到 `5`（`open_threads` 生命周期加列，纯增量、回填、不改旧行）；
> 5. `get_contract_info()` 追加**可选**键 `open_thread`（生效配置回显）；生命周期
>    由两条读取路径幂等驱动，支持 `open_thread.enabled=false` 整体关闭（§13.3）。
>
> v1.3 变更摘要（不破坏任何 v1.x 客户端）：
> 1. `capabilities` **保持 `dict[str, bool]`**，仅追加 `memory_bridge`；
> 2. `get_proactive_context` 追加**可选**键 `memory`（只读消费关联记忆插件的
>    公共召回/画像 API；不可用时该键**整体缺省**，输出与 v1.2.0 逐字节一致）；
> 3. `expression_decision` 在读到画像时仅把 `style_hints["warmth"]` 上调 ≤ +0.05
>    （`mode` 不变；群聊/无记忆不变）；
> 4. `fuse_motivation` 追加可选入参 `memory_hints`（仅影响候选**排序**，门控/生命周期不变）；
> 5. 无新表、无 schema 变更，`schema_version` 仍为 `5`。
>
> v1.4 变更摘要（不破坏任何 v1.x 客户端）：
> 1. `capabilities` **保持 `dict[str, bool]`**，仅追加 `life_line`；
> 2. 新增 `get_life_line(umo, day=None)` / `get_diary(umo, day=None)`（同时挂
>    Star 实例与 `ContractV1`）；群聊返回隔离/缺省值；
> 3. `get_proactive_context` 追加**可选**键 `life_detail`（天气/用餐/睡眠/安静/日记，
>    **仅私聊**；关闭或群聊时该键缺省）；
> 4. `fuse_motivation` 追加可选入参 `quiet`（门控优先级 `unanswered_streak` >
>    `quiet_hours` > `quota`；命中时 `quota.allow=false` 且
>    `motivation.blocked_reason="quiet_hours"`）；
> 5. `LifeState` 追加**可选**字段 `weather`/`meal`/`sleep`/`quiet`（缺省时结构与 v1.3.0
>    逐字段一致）；schema 升级到 `6`（三张纯增量新表）。
>
> v1.5 变更摘要（不破坏任何 v1.x 客户端）：
> 1. `capabilities` **保持 `dict[str, bool]`**，仅追加 `identity_binding`；
> 2. 私聊关系/好感/情绪/生活线/账本键由 `(persona_id, user_id)` 改为
>    `(persona_id, person_id)`（`person_id` 来自记忆桥 `resolve_person(umo)`；
>    **不可用时 fail-closed 退回 `parse_umo().user_id`，行为同 v1.4.0**）；
>    **群聊仍 `group:<session_id>`，不跨人**；
> 3. `get_proactive_context` 追加**可选**键 `person_id`（**仅私聊**且解析成功；
>    否则整键缺省，输出与 v1.4.0 逐字节一致）；
> 4. 新增一次性、幂等、可回滚的 `Store.migrate_person_keys`（`POST /person/migrate`
>    + `/person/migrate/rollback`）；无 schema 变更（仍 `6`）。
>
> v1.6 变更摘要（不破坏任何 v1.x 客户端）：
> 1. `capabilities` **保持 `dict[str, bool]`**，仅追加 `group_aware` / `growth`；
> 2. 新增 `record_group_activity` / `get_group_context` / `get_growth_context`
>    （同时挂 Star 实例与 `ContractV1`）；
> 3. `get_proactive_context` **群分支**追加**可选**键 `group` / `participation`
>    （私聊专属键对群**保持缺席**）；
> 4. `expression_decision` 私聊叠加**有界**成长漂移（`style_hints["warmth"]`
>    `+0.00`~`drift_cap`，硬上限 `0.05`，**永不改 `mode`**）；群聊不变；
> 5. schema 升级到 `7`（三张纯增量新表，见 §7）；关 `group.enabled` /
>    `growth.enabled` 或置 `growth.reset` → 回落 v1.5.x 行为。

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
| `capabilities` | `dict[str, bool]` | 否 | `life_state` / `schedule` / `relationship` / `motivation` / `open_threads` / `quota` / `proactive` / `emotion` / `expression` / `open_threads_followup` / `memory_bridge` / `life_line` / `identity_binding` / `group_aware` / `growth` |
| `open_thread` | `dict` | 否（v1.2 新增） | 生效后的未完话题配置（默认值已补齐）：`{enabled, max_open, ttl_days, expire_days, followup_max}` |

`capabilities` 恒为 **`dict[str, bool]`**（v1.0.0 起即是 map，从未是数组；改成
数组属于破坏性变更，见 §8）。取值：`life_state/schedule/relationship/motivation/
open_threads/quota=true`，`proactive=false`（companion-core 从不自己发送/调度，
只提供输入与回执）；v1.1 追加 `emotion=true` / `expression=true`；v1.2 追加
`open_threads_followup=true`（下游据此决定是否走未完话题续接链路）；v1.3 追加
`memory_bridge=true`（装配了可选的只读记忆桥，见 §14；该位表示**能力存在**，
不表示关联记忆插件已安装——实际可用性由运行时降级决定）；v1.6 追加
`group_aware=true` / `growth=true`（群聊理解与成长能力存在，见 §17/§18；实际生效
仍受各自 `enabled` 开关约束）。

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

下游消费者（kanjyou 等）的聚合入口。**纯读业务状态**：不改写关系/情绪/账本
（业务状态变更只经 `on_proactive_outcome` 与 observe 钩子）。读取路径上仅有**幂等
维护写**：未完话题生命周期推进（§13.3）与生活线惰性合成（睡眠窗/用餐事件/日记，
§15）——因为 core 自身不启动调度器。v1 全字段如下：

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
| `memory` | `dict` | 否（v1.3 新增） | 记忆桥只读载荷（§14.2）；桥不可用/无数据时**整键缺省**；群聊只含 `snippets` |
| `life_detail` | `dict` | 否（v1.4 新增） | `{weather, meal, sleep, quiet, diary}`（§15.2）；**仅启用且私聊**，群聊/关闭时**整键缺省** |
| `person_id` | `str` | 否（v1.5 新增） | 私聊回显的权威 Person（= 记忆插件 `canonical_user_id`）；解析成功才出现，群聊或桥不可用时**整键缺省**（§16） |
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
- 两条读取路径（`get_proactive_context` / `get_open_threads`）在返回前各做一次
  幂等的生命周期推进（§13.3）；`open_thread.enabled=false` 时整体关闭：不推进、
  不返回候选，四个方法均按关闭处理（`reason=disabled`）。
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

## 7. SQLite schema（`schema_version = 8`）

库文件：`get_astrbot_plugin_data_path()/astrbot_plugin_tcompanion_core/tcompanion_core.sqlite3`。

表：`personas` / `life_state_daily` / `life_schedule` / `relationships` /
`affinity_ledger` / `interaction_stats` / `open_threads` / `motivation_log` /
`emotion_events` / `sleep_windows` / `life_events` / `life_diary` /
`group_activity` / `group_members` / `growth_state` / `life_content`
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

v6（v1.4，Phase 2-D）为**纯增量**：新增三张表，`CREATE TABLE IF NOT EXISTS` +
> 索引，**不触碰任何既有表或旧行**，重复执行不报错。旧代码（v1.3.x）不查询新表，
> 可安全共存，无需回滚。

- `sleep_windows(persona_id, user_id, day, start_min, end_min, source)` —— 每日推断/
  默认睡眠窗口，主键 `(persona_id, user_id, day)`；`source` = `inferred|default|manual`。
- `life_events(persona_id, user_id, ts, kind, payload_json, dedupe_key)` —— 结构化生活
  事件，`UNIQUE(persona_id, user_id, dedupe_key)` + `INSERT OR IGNORE`（用餐键
  `meal:{slot}:{day}`）；`payload_json` 仅结构化字段。
- `life_diary(persona_id, user_id, day, summary, mood)` —— 每日合成小结，`UNIQUE(...)`；
  `summary` 为**确定性模板合成**（非用户原文）。

> v1/v2 表仅存派生值、无消息原文，故重构/追加均安全；迁移仍幂等：
> 重复 `apply_migrations()` 不改写 `schema_meta`。全新库会依次执行 v1→v8；
> 既有 v2–v7 库会安全原地升级到 v8。

v7（v1.6，Phase 3-A/3-C）为**纯增量**：新增三张表，`CREATE TABLE IF NOT EXISTS`
+ 索引，**不触碰任何既有表或旧行**，重复执行不报错。旧代码（v1.5.x）不查询新表，
可安全共存，无需回滚。

- `group_activity(umo, message_count, hour_key, hour_count, day, day_count, topic,
  topic_ts, last_activity_ts, last_participation_ts, part_hour_key,
  part_hour_count, updated_at)` —— 每群一行的**有界计数**（时/日活动量、参与闸门
  窗口、末日活跃）；`topic` 为 `sanitize_thread_title` 清洗后的**短标签**，主键 `umo`。
- `group_members(umo, member_key, familiarity, msg_count, first_seen_ts,
  last_seen_ts)` —— 群内**局部**成员熟悉度，主键 `(umo, member_key)`；`member_key`
  形如 `group:<session_id>#<user_id>`，**不与私聊 `person` 合并、不跨群聚合**。
- `growth_state(persona_id, user_id, level, xp, reset_at, updated_at)` —— 成长等级
  高水位（`level`/`xp` 只升不降）与 `reset_at`（清零回退），主键 `(persona_id, user_id)`。

v8（v1.7，Phase 3-B）为**纯增量**：新增一张表，`CREATE TABLE IF NOT EXISTS` +
唯一索引/查询索引，**不触碰任何既有表或旧行**，重复执行不报错。旧代码（v1.6.x）
不查询新表，可安全共存，无需回滚。

- `life_content(persona_id, ts, kind, source_ref, summary, tags, dedupe_key,
  expires_at)` —— persona 作用域的见闻/话题素材（**不绑用户身份**）；唯一索引
  `(persona_id, dedupe_key)` 去重，查询索引 `(persona_id, ts)`。`source_ref` =
  `sha256(来源 URL)` 截断（去敏不可逆）；`summary` 为**去 HTML 后截断**的短文本
  （≤ `content_max_chars`），**不存外部原文全文**；`expires_at` 为空或到期时间。

**隐私不变式**：以上任何表都不含消息原文/正文列。`group_activity.topic` 为短标签、
`life_state_daily.summary` 为模型生成的当日生活摘要、`open_threads.title` 为话题标题，
均非消息原文。

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
- **不泄露标签**：`open_thread` 候选的 `reason` 为**不含短标签**的泛化措辞
  （`OPEN_THREAD_REASON`），短标签只保留在审计用的 `label` 字段。原因：`reason`
  会被下游直接注入 prompt，若携带标签将绕过续接闸门（冷却/次数上限/开关，
  TMEAAA-504）。标签只经 `open_thread_details` → 闸门续接块注入（§13.4）。

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

### 13.3 生命周期（`Store.expire_open_threads` → 读取路径触发，core 侧）

- `open` → 超 `ttl_days`（默认 3）未提及 → `stale`（仍存，下游不作为续接候选）。
- `stale`/`open` → 超 `expire_days`（默认 14）未提及 → `closed(reason=expired)`。
- 被回应/完成 → `close_open_thread(reason=answered)`，不再作为候选。
- 单 `(umo, persona_id)` 的 `open` 超 `max_open`（默认 20）→ 按 `last_seen_ts` LRU
  关闭最旧，`closed_reason='superseded'`。阈值**全局**，不随关系阶段变化。

**触发点（core 不引入调度器）**：`get_proactive_context` 与 `get_open_threads`
两条读取路径在读取前各调用一次 `Store.expire_open_threads(cfg)`。理由：下游
决策循环本来就会调用这两个入口，生命周期随消费自然推进；代价固定为三条有界
SQL，对给定 `now` 幂等；无需新增任务/钩子，也不改变 `capabilities.proactive=false`
（core 仍不发送、不调度）。

**配置读取**：`core/motivation.py::parse_open_thread_config()` 解析 AstrBot 配置组
`open_thread`，映射为 `OpenThreadConfig{enabled, max_open, ttl_days, expire_days,
followup_max}`（缺省/异常回退到上述默认值；`get_contract_info().open_thread`
回显生效值）。配置对象每次读取时重新解析，故配置页热更新立即生效。

- `enabled=false`：上述四个契约方法全部按关闭处理（`record_open_thread` →
  `applied=false, reason=disabled`；`get_open_threads` → `[]`；
  `close_open_thread` / `mark_thread_followup` → `reason=disabled`），且**不推进**生命周期；
  `get_proactive_context` 的 `open_threads` / `open_thread_details` 恒为 `[]`。
- `followup_max` 由 core 透出（`get_contract_info().open_thread`），供下游作为续接
  次数上限使用（core 自身不消费该值）。

### 13.4 消费契约（kanjyou 侧，见 plan §5）

`get_proactive_context().open_thread_details` 中 `status=open` 且 `confidence ≥ 0.6`
的条目才可作为续接候选；每次主动消息**至多续接 1 条**，且需满足冷却
（`last_followup_ts`）、`followup_count < followup_max`、最小间隔、`quota.allow`、
`unanswered_streak < 3`、`expression.proactive_bias ≥ 0` 等闸门。发送成功后调用
`mark_thread_followup` 递增计数。core 缺失 / `api_version≠1` / 无
`open_threads_followup` capability → 下游完全不调用（= 现状，零回归）。

## 14. 记忆桥（v1.3 · Phase 2-E）

实现：`core/memory_bridge.py`（桥 + 配置解析）+ `core/contract.py`（三个消费点）。
**无新表、无 schema 变更**（`schema_version` 仍为 `5`），`api_version` 仍为 `1`。

### 14.1 只读桥（`MemoryBridge`）

- 经 `context.get_registered_star(plugin_name)` 解析关联记忆插件；`activated=False`
  或缺省即视为不可用。`plugin_name` 默认 `astrbot_plugin_tmemory`（可配置）。
- 只调用两个**公共只读** API：`recall_for_prompt(umo, query, session_type, limit)`
  与 `get_profile_for_prompt(umo, query, limit, session_type)`（后者用 `hasattr`
  探测，缺失即只给 `snippets`）。
- 每次调用用 `asyncio.wait_for` 包裹，超时 `memory_bridge_timeout_sec`（默认 2s，
  硬上限 10s）；结果按 `umo|会话类型|query` 做 TTL 缓存（默认 5 分钟），
  缓存内不重复查库（命中/空结果都会缓存）。
- **fail-closed**：插件缺失 / `enabled=false` / 超时 / 任意异常 / 无数据 → 返回
  `None`，调用方**完全等同 v1.2.0**。桥自身绝不抛异常、绝不写库。
- 可观测计数（只记结果、不落内容）：`hit` / `degrade` / `timeout`
  （`MemoryBridge.stats()`；超时同时计入 `timeout` 与 `degrade`）。
- 隐私：只透传关联插件**已裁剪**的短文本（snippet ≤200 字、highlight ≤120 字、
  summary ≤200 字），不落消息原文；**群聊不读取也不返回 `profile`**。

### 14.2 `memory` 载荷（`get_proactive_context` 可选键）

```json
"memory": {
  "snippets": ["<≤200字>", "..."],              // ≤ memory_bridge_limit（默认 4）
  "profile": {                                   // 群聊整体缺省
    "facets": {"preference": 2, "task_pattern": 1},
    "summary": "<≤200字>",
    "highlights": ["<≤120字>", "..."]
  },
  "as_of": "<ISO8601>"
}
```

- 无数据 / 桥不可用 → 整个 `memory` 键**缺省**（不是空对象），输出与 v1.2.0
  逐字节一致（除 `plugin_version`）。
- 查询串为零 LLM 派生：`life.activity` + `life.scene` + 最新两条未完话题标签 +
  关系阶段，截断 ≤100 字；全空时退化为「时段 + 会话类型」。
- 画像缺失（老版记忆插件）时仍可只给 `snippets`。

### 14.3 表达微调（`expression_decision`）

- 私聊且读到画像时：`style_hints["warmth"] += 0.03`，**硬上限 = 该档基准 + 0.05**
  （`MEMORY_WARMTH_MAX_DELTA`），**永不改变 `mode`**、只升不降。
- 无记忆 / 群聊 / 异常 → 与 v1.2.0 完全一致。

### 14.4 排序微调（`fuse_motivation(memory_hints=...)`）

- 新增可选入参 `memory_hints: Sequence[str] = ()`，由契约从画像 `facets` 键与
  `highlights` 派生。候选 `label` 归一化后命中任一 hint 的 ≥2 字子串 →
  `score += 0.05`（`MEMORY_HINT_BONUS`，上界，`clamp01`），**仅在排序前生效**。
- **门控与生命周期不变**：`allow` / `adopted` / `blocked_reason` /
  `unanswered_streak` 判定不受影响，只改候选排序。

### 14.5 配置（`memory_bridge` 组，面向用户）

| 键 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `enabled` | `bool` | `true` | 启用记忆桥接（未装记忆插件时自动忽略） |
| `plugin_name` | `string` | `astrbot_plugin_tmemory` | 记忆插件名称 |
| `timeout_sec` | `float` | `2.0` | 读取等待上限（秒），超时自动跳过 |
| `limit` | `int` | `4` | 每次读取条数 |
| `ttl_min` | `int` | `5` | 缓存时间（分钟） |

- 配置对象每次读取时重新解析（热更新即时生效）；缺省/异常回退到上表默认值。
- 为兼容写作习惯，扁平键 `memory_bridge_enabled` / `memory_bridge_plugin_name` /
  `memory_bridge_timeout_sec` / `memory_bridge_limit` / `memory_bridge_ttl_min`
  同样被接受（组存在时以组为准）。

### 14.6 边界（本阶段不做）

- 不反向写入关联记忆插件；不生成/蒸馏画像。
- 不引入新的 LLM 调用（纯读 + 轻量规则）。
- 不改关联插件自身的召回注入逻辑。

## 15. 生活线（v1.4 · Phase 2-D）

实现：`core/life_line.py`（配置/时间窗/睡眠推断/日记模板）+ `core/weather.py`
（天气）+ `core/contract.py`（消费点）。schema → `6`（三张纯增量新表），`api_version`
仍为 `1`。零新增 LLM 调用；所有外部数据源 fail-closed。

### 15.1 数据模型（schema v6）

- `sleep_windows(persona_id, user_id, day, start_min, end_min, source)`：每日作息窗，
  主键 `(persona_id, user_id, day)`；`source=inferred|default|manual`。
- `life_events(persona_id, user_id, ts, kind, payload_json, dedupe_key)`：
  `UNIQUE(persona_id, user_id, dedupe_key)` + `INSERT OR IGNORE`，去重键形如
  `meal:{slot}:{day}`。
- `life_diary(persona_id, user_id, day, summary, mood)`：`UNIQUE(...)`；`summary` 为
  确定性模板合成，**不存用户原文**。
- 全部纯增量：旧库迁移无损、幂等；旧代码不查新表可共存。

### 15.2 契约增量

- `LifeState` 追加**可选**字段 `weather{code,temp,precip}` / `meal{next_window}` /
  `sleep{window,since}` / `quiet`；缺省为 `None` 且 `to_dict()` 省略，故默认结构与
  v1.3.0 逐字段一致。
- `async get_life_line(umo, day=None) -> dict`：生活线快照。私聊返回
  `{api_version, umo, persona_id, day, weather, meal, sleep, quiet, diary,
  isolated, degraded}`；**群聊**返回 `isolated=true` 且各维度为缺省；`life_line`
  关闭时返回中性缺省。逐维度独立降级。
- `async get_diary(umo, day=None) -> dict | None`：当日（或指定日）合成日记。群聊/
  关闭/无数据返回 `None`。
- `get_proactive_context` 追加**可选**键 `life_detail`
  `{weather, meal, sleep, quiet, diary}`：**仅启用且私聊**时出现，群聊/关闭时该键
  **缺省**（老客户端忽略未知键）。
- `capabilities` 追加 `life_line: true`（`dict[str, bool]` 形状不变）。

### 15.3 天气维度（`core/weather.py`）

- 免 key 内置源：Open-Meteo geocoding + forecast
  （`current=temperature_2m,weather_code,precipitation`）。
- `life_city` 为空 → 整个维度关闭；`weather_api_base` 覆盖**两个**端点（离线 stub）。
- 超时默认 3s；结果仅存**内存 TTL 缓存**（默认 45min，可清），不落库。
- **fail-closed**：无网/超时/解析失败/字段缺失 → `weather=null`，行为等同未启用。

### 15.4 睡眠推断与安静时段抑制

- 样本：私聊 scope 近 14 天交互时间戳的小时直方图（零采集，仅时间戳）。
- 推断：最长连续「零活动」小时段（≥4h，跨午夜环绕）→ 前一个活跃小时为入睡、后一个
  为起床；钳制入睡 ∈[20:00,03:00]、起床 ∈[05:00,11:00]。样本不足（<3 活跃日或
  <10 条）→ 默认 `23:00–07:30`。按日写 `sleep_windows`。
- `sleep_window_auto=false` → 只用配置 `quiet_hours`。
- 抑制（D3，**仅自主主动消息**，群聊不参与）：`fuse_motivation(quiet=true)`，
  优先级 `unanswered_streak` > `quiet_hours` > `quota`；命中 → `quota.allow=false`
  且 `motivation.blocked_reason="quiet_hours"`。例外：`proactive_opt_in=true` 或
  用户近 10 分钟内有交互。

### 15.5 用餐与日记

- 用餐：可配早/午/晚窗口；读取时若当前处于某窗口，则写入去重事件
  `life_events(meal:{slot}:{day})`。
- 日记：读取 D 日时若 D-1 无日记行，则由 D-1 的睡眠窗/用餐/活动/情绪**零 LLM 确定性
  合成**（`synthesize_diary`），`INSERT OR IGNORE`。不存用户原文。

### 15.6 配置（`life_line` 组，面向用户）

| 键 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `life_line_enabled` | `bool` | `true` | 启用生活线 |
| `life_city` | `string` | `""` | 城市；留空则不用天气 |
| `meal_reminders_enabled` | `bool` | `true` | 用餐到点关心 |
| `sleep_window_auto` | `bool` | `true` | 自动推断作息 |
| `quiet_hours` | `string` | `23:00-07:30` | 安静时段 |
| `proactive_opt_in` | `bool` | `false` | 安静时段也允许主动 |
| `breakfast_window` / `lunch_window` / `dinner_window` | `string` | `07:00-09:00` / `11:30-13:00` / `18:00-20:00` | 用餐时段 |
| `weather_api_base` | `string` | `""` | 天气接口地址（高级） |
| `weather_timeout_sec` / `weather_ttl_min` | `float` / `int` | `3.0` / `45` | 天气超时/缓存 |

- 兼容扁平键（`life_line_enabled` / `life_city` / `quiet_hours` …）与嵌套组内
  `enabled`；组存在时以组为准。配置每次读取重新解析（热更新即时生效）。

### 15.7 边界与隐私

- 未启用任何数据源（`life_line_enabled=false`）时，`get_proactive_context` 输出与
  v1.3.0 **逐字段一致**。
- **群聊剥离**全部 `life_detail`/私聊生活线；只存结构化字段（码/时段/计数/合成摘要），
  **不存用户原文**；天气仅内存缓存、可清。
- 位置/周期/梦境**不在本阶段**（不加开关、不落配置）。本阶段不引入新的 LLM 调用。

## 16. 人物身份绑定与 person 键（v1.5）

> 目标：让**同一个人**在多个适配器（aiocqhttp / astrbook / …）下被视为同一个「人物」，
> 换渠道不再等于换人。**身份权威在记忆插件（tmemory）**，companion-core 只**只读消费**；
> 契约 `api_version` 仍为 `1`，本节均为加法。

### 16.1 身份桥（`MemoryBridge.resolve_person(umo)`）

- 通过 `hasattr` 探测并调用记忆插件公开的只读 `resolve_person(umo)`：
  私聊返回 `{person_id, adapter, adapter_user_id, is_group}`，其中
  `person_id = canonical_user_id`；群聊返回 `is_group=true` 且 `person_id=""`。
- 结果按 **umo** 做 TTL 缓存（默认与 `memory_bridge.ttl_min` 同源，`0` 表示不缓存），
  避免逐消息查询；连**负结果**（解析不到）也会缓存，防止击穿。
- **Fail-closed**：桥未装配 / 记忆插件未安装或未启用 / 缺少该方法 / 超时（默认 ≤2s）/
  任何异常 / 空结果 → 一律返回 `None`，由调用方退回 `parse_umo()`，行为同 v1.4.0。
  只读：不写库、不隐式建绑定、不传递任何消息原文。

### 16.2 person 键（私聊）/ 群聊隔离

- **私聊**：关系/好感/情绪/生活线/账本/日记的存储键由 `(persona_id, user_id)` 改为
  `(persona_id, person_id)`。`get_relationship` / `get_proactive_context` /
  `get_emotion_context` / `expression_decision` / `get_life_line` / `get_diary` /
  `get_open_threads` 等读路径与 `record_emotion_event` / `on_proactive_outcome` 等写
  路径统一走身份解析，保证同一 Person 读写同一份。
- **Person 与 persona 解耦**：绑定只作用于「人」，不同 bot persona 仍是各自独立的一份。
- **群聊**：键保持 `group:<session_id>`，且**永不跨人聚合**；绑定不影响群聊隔离。

### 16.3 一次性幂等迁移（`POST /person/migrate`）

- 入参：`{person_id, aliases[]}`，`aliases` 为该 Person 名下各适配器的旧键（如
  `adapter:user`）。迁移把旧键行并入 `(persona_id, person_id)`。
- **先备份**：改动前把受影响行（旧键 + 目标键）写成 JSON 备份
  （`data/plugin_data/<plugin>/person_migrations/person_migrate_<person>_<ts>.json`）。
- **幂等**：第二次调用时旧键已无行 → `noop=true`，不重复写备份。
- **回滚**：`POST /person/migrate/rollback`（`{backup_path?}`，缺省取最新备份）删除本次
  目标/旧键行并回填备份行。
- **群聊行不迁移**：`group:*` 键被显式跳过。
- 合并语义：`relationships`/`interaction_stats` 聚合（好感取较大值、计数求和、
  时间取较新、streak 取较大）；追加型账本（`emotion_events`/`affinity_ledger`/
  `motivation_log`/`sleep_windows`/`life_events`/`life_diary`）按行唯一键改键，
  冲突时保留目标键行。**不在每条消息上运行**，仅由 `POST /person/migrate` 或
  Star 的 `migrate_person(...)` 手动/配置触发。

### 16.4 契约增量

- `get_contract_info().capabilities["identity_binding"] = true`（该位表示**能力存在**，
  实际可用性由运行时桥的降级决定）。
- `get_proactive_context` 追加可选 `person_id`（仅私聊解析成功时）。
- `Store.migrate_person_keys(...)` / `Store.rollback_person_migration(...)`；Star 面
  `migrate_person(...)` / `rollback_person_migration(...)` 与两条 Web API 路由。
- **无 schema 变更**（`schema_version` 仍为 `6`）。

## 17. 群聊理解（v1.6 · Phase 3-A）

> 实现：`core/group.py`（纯逻辑）+ `core/store.py`（落库）+ `core/contract.py`（投影）。
> 契约 `api_version` 仍为 `1`，全部为加法。**群聊只用群的上下文与群内轻量状态**，
> 绝不读取/注入私聊关系、情绪、生活线或画像，也不跨群聚合。

### 17.1 群/成员派生

- **群内成员为局部匿名键** `group:<session_id>#<member_id>`（`member_key_for`），
  **不与私聊 `person` 合并、不跨群聚合**；`member_id` 被裁剪为短串。
- 群派生块：`{member_count, activity_level, topic, topic_age_min, last_activity}`。
  - `activity_level` ∈ `low|medium|high`，按当前小时消息数与 `busy_group_threshold`
    分桶（`≥阈值` 为 `high`，`≥阈值/3` 为 `medium`，否则 `low`）。
  - `topic` 为消费者提交并经 `sanitize_thread_title` 清洗的**短标签**（可缺省），
    `topic_age_min` 为其距 `now` 的分钟数（无话题为 `null`）；**不存原文**。
- `member` 块：`{member_key, familiarity, is_known}`；成员跟踪关闭或未提供
  `member_id` 时 `member_key=""`、`familiarity=0`、`is_known=false`。

### 17.2 参与闸门（advisory，固定理由码）

`evaluate_participation` 按**稳定优先级**给出建议：`cooldown` → `hourly_limit` →
`group_busy` → `ok`。core 只给建议，**从不自己发送**。

| 字段 | 说明 |
| --- | --- |
| `allow` | 是否建议接话 |
| `reason` | `ok` / `cooldown` / `hourly_limit` / `group_busy`（关闭时为 `disabled`） |
| `cooldown_remaining_sec` | 距上次接话满 `min_reply_gap_sec`（默认 90s）的剩余秒数 |
| `hourly_remaining` | 本小时剩余可接话次数（上限 `hourly_limit`，默认 6） |

- 群繁忙：本群当前小时消息数 `≥ busy_group_threshold`（默认 120）→ `group_busy`。
- **读取即占用**：`get_group_context` 是**决策端点**；当 `allow=true` 时该次调用会
  **消耗**一个建议槽（推进冷却与小时计数），窗口内重复调用即返回 `cooldown`。
  `get_proactive_context` 群分支与 `record_group_activity` 只**读取**建议，不占用。

### 17.3 契约增量

- `capabilities["group_aware"] = true`。
- `record_group_activity(umo, *, member_id=None, topic=None, now=None) -> dict`：
  仅群范围写有界计数（私聊 no-op `isolated=true`，关闭该组亦 no-op）；返回
  `{applied, isolated, group, degraded}`（`group` 同 §17.1 派生块）。
- `get_group_context(umo, persona_id=None, *, member_id=None) -> dict`：
  - 群：`{api_version, umo, is_group: true, group, participation, member, degraded: false}`；
  - 私聊：`{is_group: false, isolated: true}`；`group.enabled=false` 时群亦返回
    `isolated: true` 空结构（fail-closed）。
- `get_proactive_context` 群分支追加**可选**键 `group` / `participation`（关闭或失败
  时缺省；私聊专属键对群仍**保持缺席**）。

### 17.4 配置（`group` 组，面向用户）

| 键 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `enabled` | `bool` | `true` | 启用群聊理解 |
| `participation_enabled` | `bool` | `true` | 启用群内参与建议 |
| `min_reply_gap_sec` | `int` | `90` | 群内最短接话间隔（秒） |
| `hourly_limit` | `int` | `6` | 每小时最多接话次数 |
| `busy_group_threshold` | `int` | `120` | 群繁忙判定（条/小时） |
| `member_tracking_enabled` | `bool` | `true` | 记录群成员熟悉度 |

### 17.5 边界与隐私

- **群聊绝不泄露**私聊 `relationship` / `emotion_state` / `life_detail` /
  `memory(profile)` / `person_id`；这些键对群**保持缺席**。
- `group.enabled=false` → `get_group_context` / `record_group_activity` 均为空
  (`isolated=true`)，`get_proactive_context` 群分支不带 `group`/`participation`，
  行为同 v1.5.x。数据源异常 → 该能力缺省，不抛错。

## 18. 成长（v1.6 · Phase 3-C，轻量）

> 实现：`core/growth.py`（纯逻辑）+ `core/store.py`（高水位）+ `core/contract.py`（投影）。
> **由既有账本确定性派生**（affinity/stage、情绪事件、活跃天数），**零 LLM、零新
> ingest**；契约 `api_version` 仍为 `1`，全部为加法。

### 18.1 派生规则（确定性、有界）

- `xp = clamp01(affinity) * max_level + min(1, active_days / 30)`（`derive_xp`）；
  `level = min(max_level, floor(xp))`，`progress = xp - level`（满级为 `1.0`）。
- `traits`：由阶段/活跃天数/正向事件比例派生的**短标签**（如 `熟悉`/`亲近`/`常来`/
  `熟客`/`开朗`），最多少量、无原文。
- `drift = {warmth_delta, verbosity_delta}`：`warmth_delta = drift_cap * level/max_level`，
  `verbosity_delta = 0.5 * warmth_delta`；`drift_cap` 硬上限 `0.05`。
- **高水位**：`growth_state.level`/`xp` 只升不降（好感衰减不致回退），读路径幂等写回。

### 18.2 契约增量

- `capabilities["growth"] = true`。
- `get_growth_context(umo, persona_id=None) -> dict`：
  - 私聊：`{api_version, umo, persona_id, is_group: false, isolated: false,
    growth: {level, progress, max_level, traits}, drift: {warmth_delta,
    verbosity_delta}, degraded: false}`；
  - 群 → `isolated: true` 空（`growth=null`，零漂移）；`growth.enabled=false` 或
    `reset=true` → 空结构（`growth=null`，零漂移），`reset` 同时清零存储。
- `expression_decision`：私聊在记忆微调之后叠加**有界**成长漂移，仅上调
  `style_hints["warmth"]`（`+0.00`~`drift_cap`，封顶 `1.0`），**永不改变 `mode`**；
  群聊不变。`growth` 关闭或 `reset` 时不产生任何漂移（回落 v1.5.x 表达）。

### 18.3 配置（`growth` 组，面向用户）

| 键 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `enabled` | `bool` | `true` | 启用成长 |
| `max_level` | `int` | `10` | 成长等级上限 |
| `drift_cap` | `float` | `0.05` | 表达暖度提升上限（`0`~`0.05`） |
| `reset` | `bool` | `false` | 清零成长并回落既有行为 |

### 18.4 边界

- 群聊无成长（`isolated` 空）；成长**不引入**新表以外的写入、不新增 LLM 调用、
  不存原文。能力缺失/异常 → 该能力缺省，行为同 v1.5.x，不抛错。

## 19. 内容生活 · 见闻（v1.7 · Phase 3-B）

> 实现：`core/life_content.py`（纯逻辑：配置/解析/去重/截断/护栏）+ `core/store.py`
> （`life_content` 表，schema **v8**）+ `core/contract.py`（取源/生成/读取投影）。
> 契约 `api_version` 仍为 `1`，全部为**加法**；`get_proactive_context` **不变**，
> 见闻由消费方（如 kanjyou）**按需单独读取**。默认关。

### 19.1 接口

- `get_life_content(persona_id, window=72h, kind=None) -> dict`
  - `{api_version, persona_id, items: [{ts, kind, source_ref, summary, tags,
    expires_at}], degraded}`；纯读、**绝不抛错**。
  - 关 / 空 persona / 存储异常 → 空 `items`（存储异常置 `degraded=true`）。
  - `window` 接受 `timedelta` 或小时数（`int`/`float`），缺省近 72 小时；`kind`
    过滤 `rss` / `topic`。读取前惰性清理已过期行。
- `refresh_life_content(persona_id=None) -> dict`
  - `{applied, generated, skipped_reason, degraded}`；**有界生成**、**绝不抛错**。
  - 关 → `skipped_reason="disabled"`；无来源 → `"no_sources"`；未到最小刷新间隔
    → `"min_interval"`；当日额度用尽 → `"daily_limit"`；生成 0 条 → `"empty"`；
    异常 → `"error"`（`degraded=true`）。`applied = generated > 0`。
- `capabilities["life_content"] = true`（新增键，旧 core 无该键 → 消费方
  fail-closed）。

### 19.2 生成流水线（低频、有界）

1. **闸门**：`disabled` → `no_sources` → 最小刷新间隔 `MIN_REFRESH_INTERVAL_MIN`
   （内部常量，默认 **120 分钟**，按该 persona 最新见闻 `ts` 计）→ 每日条数上限
   `content_max_items_per_day`（1–3，默认 2）。
2. **静态话题池**：`content_topics` 每项生成一条 `kind="topic"`（`dedupe_key` 基于
   话题文本，重复刷新不再新增）。
3. **RSS/Atom 源**：`content_sources` 逐条取源（stdlib `xml.etree`，无新依赖）；
   每来源超时 + 总超时预算；`http(s)` 白名单且**拒绝** localhost/私网/回环/链路本地
   字面量（SSRF 护栏，见 §19.4）。
4. **落库**：`summary = truncate(strip_html(标题或摘要), content_max_chars)`，
   `expires_at = now + content_ttl_days`；`unique(persona_id, dedupe_key)` +
   `INSERT OR IGNORE` 去重（重复项只刷新 `expires_at`，不新增行、不改 `ts`）。
5. **可选摘要**：`content_summarize=false`（默认）时**零 LLM**，只存去 HTML 截断
   文本；`true` 时用**注入式 summarizer**（`ContractV1(..., content_summarizer=)`，
   签名为 `async (text, provider_id) -> str | None`）整理成一句话，**超时/异常/无
   provider → 回退截断文本**，失败静默。

### 19.3 退化矩阵

| 条件 | 读取 | 生成 |
| --- | --- | --- |
| `content_enabled=false`（默认） | 空 `items`，`degraded=false` | `applied=false`, `disabled` |
| 无 `sources`/`topics` | 空 | `no_sources` |
| 未到最小刷新间隔 | 正常返回已有条目 | `min_interval` |
| 当日额度用尽 | 正常返回已有条目 | `daily_limit` |
| 来源不可达/超时/解析失败 | 正常返回已有条目 | 该源跳过，`degraded=true`，其余源继续 |
| 摘要失败/无 provider | — | 回退截断文本，静默 |
| 存储异常 | 空 `items`，`degraded=true` | `applied=false`, `error` |

### 19.4 护栏与隐私（硬性）

- **默认关**；开启后才取源。**失败静默**：任何取源/解析/摘要/存储失败都不 raise、
  不影响主动发送。
- **成本上限**：每日条数（1–3）+ 最小刷新间隔（120min）+ 每来源/总超时 + 摘要
  超时。
- **SSRF 护栏**：来源仅 `http(s)`，拒绝 `localhost` / `.local` / 私网 / 回环 /
  链路本地 / 保留 / 组播 / 未指定地址字面量。
- **无原文、无隐私外发**：只存去 HTML 截断摘要；`source_ref` 为 URL 的
  `sha256` 截断（不可逆去敏）；见闻**不绑用户身份**，**不采集用户聊天、不把用户
  数据当查询**。
- **默认关回退**：`content_enabled=false` 时无表写入、无网络、无 LLM 调用；
  `get_proactive_context` 与契约输出与 v1.6.0 逐字节一致。

### 19.5 配置（`content` 组，面向用户）

| 键 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `content_enabled` | `bool` | `false` | 启用见闻 |
| `content_sources` | `list[str]` | `[]` | RSS/Atom 地址（仅 `http(s)`） |
| `content_topics` | `list[str]` | `[]` | 手填兴趣/话题 |
| `content_max_items_per_day` | `int` | `2` | 每天最多条数（1–3） |
| `content_summarize` | `bool` | `false` | 用模型整理成一句话 |
| `content_provider_id` | `string` | `""` | 整理用模型（留空用当前会话模型） |
| `content_max_chars` | `int` | `80` | 每条摘要最大字数 |
| `content_ttl_days` | `int` | `14` | 见闻保留天数（过期自动清理） |

内部常量（不暴露）：`MIN_REFRESH_INTERVAL_MIN`（默认 120）、每来源超时
`CONTENT_SOURCE_TIMEOUT_SEC`、总超时 `CONTENT_TOTAL_TIMEOUT_SEC`、摘要超时
`CONTENT_SUMMARIZE_TIMEOUT_SEC`。

## 20. 共享身份映射（只读消费，v1.9）

> 目标：当**在线身份桥不可用**（记忆插件未安装/未启用/超时/离线/独立运行）时，
> companion-core 仍能把 `(adapter, adapter_user_id)` 解析为**同一个 canonical Person**。
> 实现：`core/identity_map.py`（只读、按 mtime 缓存）+ `MemoryBridge.resolve_person` 回退。
> 契约 `api_version` 仍为 `1`，本节为加法。

### 20.1 位置与格式（权威方 = tmemory）

- 文件：`<AstrBot data>/plugin_data/_shared/identity_map.json`（两插件同机同库各自解析，
  同一路径）。companion-core 侧解析见 `core/paths.py::get_shared_data_dir()`。
- **单一写者 = 记忆插件（tmemory）**；companion-core **只读**，绝不写、不建目录。
- 格式（`version = 1`）：

```json
{
  "version": 1,
  "authority": "tmemory",
  "updated_at": "...",
  "persons": {"<canonical_user_id>": {"display_name": "", "bindings": [...], "updated_at": "..."}},
  "index": {"<adapter>:<adapter_user_id>": "<canonical_user_id>"}
}
```

- 只消费 `index`：键 = `f"{adapter}:{adapter_user_id}"`，其中 `adapter_user_id` = 权威方
  写入的 **sender id**（`event.get_sender_id()`），值 = canonical（= `person_id`）。
- 群聊**不入 index**（映射仅用于私聊 person；群聊仍 `group:<session>`）；`display_name` 可选。

### 20.1.1 会话键 normalize（v1.9，TMEAAA-578）

消费侧从 UMO 取 `(adapter, session_id)` 后，**必须 normalize 成权威方的 `adapter_user_id`**
再查 `index`；否则 `session_id` 与 `sender_id` 不等的平台会全部 miss：

- 多数适配器 `session_id == sender_id`，normalize 为恒等。
- **WebChat**：私聊 `session_id = f"webchat!{username}!{conversation}"`
  （`webchat_adapter.py`）→ 解码为 `username`（`split("!", 2)` 的第 2 段）。
- 未知形态原样返回。实现：`core/identity_map.py::normalize_adapter_user_id()`
  （`IdentityMap.lookup` 内部调用，故直接传 `parse_umo().session_id` 也能命中）。
- 权威方 tmemory 侧对同一规则做对称 decode（`adapters/event.py::get_adapter_user_id_from_umo`
  用于 umo→`identity_bindings` 回退查找），两端键空间保持一致。

### 20.2 解析优先级

companion-core 解析私聊 Person 的优先级：

1. **在线桥** `MemoryBridge.resolve_person(umo)`（见 §16.1，权威、实时）；
2. 在线桥返回 `None` 时 → **共享文件 `index`**（用 `parse_umo(umo)` 取 `(adapter, session_id)`，
   经 §20.1.1 normalize 后命中）；
3. 仍未命中 → **本地 `parse_umo()`**（关系键退回 `key.user_id`，行为同 v1.4.0）。

### 20.3 降级契约（硬性）

- **fail-closed**：文件缺失 / 不可读 / JSON 损坏 / `version` 不符 → 空索引，`lookup` 返回 `None`，
  **绝不抛异常**、绝不影响读路径。
- **逐字节兼容**：无导出文件时 `resolve_person` 的返回与 `get_proactive_context` 等契约输出
  与 v1.8.0 **逐字节一致**。
- **只读、无缓存击穿**：按文件 `st_mtime_ns` 缓存解析结果，文件变更自动重载；
  结果仍按 umo 做 TTL 缓存（与在线桥同源）。
- **群聊隔离**：群聊 scope 不查文件、不返回 person。

### 20.4 契约增量

- `get_contract_info().capabilities["identity_map"] = true`（该位表示**能力存在**，
  实际可用性由运行时是否读到文件决定）。
- **无新增公开契约方法**；`resolve_person` 为内部读取路径，`person_id` 经由既有
  可选键（§16.4）输出。**无 schema 变更**。

## 21. 跟随共享身份映射（面板 + 本地镜像 + rekey，v1.10）

> 目标（plan TMEAAA-563 rev2）：人物聚合**只跟随共享映射**，删除 v1.8 的字符串
> 启发式（`canonical_suffix` / `same_tail` / `digit_tail` 聚类）。映射来源为
> **在线 canonical / 文件 index / 本地镜像**；无映射时 `person_key = 自身键`。
> `api_version` 仍为 `1`，本章全部为加法。

### 21.1 去启发式

- 删除 `core/identity.py` 的尾号/规范尾匹配判定与 `core/store.py` 的
  `_cluster_private_entries` / `judge_person_keys` / `person_key_hints`。
- `Store.person_key_views()` 只返回 `{persona_id, user_id, rows, last_active_at}`
  （纯读、无映射）；`person_key` 由调用方按映射解析。
- 面板不再出现「疑似同人」字符串标记。

### 21.2 映射驱动的 `person_key`（面板）

- `/person/keys` → 每项新增 `person_key`；`/relationships` → `person_key` 同源。
- 解析（读路径）：在线 canonical 已持久化时即为自身键；否则查
  `IdentityMap.resolve_key(user_id)` —— 支持 `adapter:uid`、裸 sender id、
  编码 session id（WebChat `webchat!<user>!<conv>`）与 canonical 自身。
- **无映射 = 自身键**（v1.4 行为，fail-closed）；`group:*` 永不参与映射，面板返回 `""`。
- 方法：`ContractV1.resolve_person_key(user_id) -> str`（**同步**，非 async 契约面，
  故不影响 `test_star_surface::CONTRACT_METHODS`）。

### 21.3 本地镜像（独立可运行）

- 位置：`<plugin_data>/astrbot_plugin_tcompanion_core/identity_map.json`（同格式，
  **单一写者 = companion**；`core/paths.py::get_identity_mirror_path()`）。
- 共享文件可读且合法时**同步**镜像（原子 `os.replace`，内容相同则跳过）；
  共享文件缺失 / 不可读 / 损坏 / 版本不符时**回退镜像**解析。
- companion **绝不写共享文件**；镜像写入 best-effort，异常不外抛。
- `IdentityMap(path)` 注入显式路径时不写镜像（测试零副作用）；默认构造启用镜像。

### 21.4 rekey（映射驱动、幂等、可回滚）

- `ContractV1.plan_person_rekey()`（**同步、只读**）：把映射解析出 canonical 的
  孤儿私聊键按 `(persona_id, canonical)` 归组；`group:*` 与无映射键不入。
- `ContractV1.rekey_person_keys(plan=None, *, dry_run=False)`（**同步**）：复用
  `Store.migrate_person_keys`（8 表合并、先备份、幂等、群聊不动）；`dry_run=True`
  只回计划。
- 面板路由：`POST /person/rekey`（body `{dry_run?}`，默认 `true`）；回滚复用
  `POST /person/migrate/rollback`。
- 既有 `identity.auto_migrate` 的在线 canonical 探测（§未变）保留：命中孤儿键时
  自动 rekey，默认仍为**只提示不合并**。

### 21.5 降级（硬性）

- 无映射 / 无重复键时，`get_relationship` / `get_proactive_context` 等契约输出与
  v1.9.0 **逐字节一致**（`identity_map` 缺失即 §20.3 的空索引）。
- 镜像读失败同样 fail-closed 到空索引；任何映射异常不得进入读路径。
