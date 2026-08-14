# Pigsty 时间演化与事件设计

## 目标

引入"事件"概念：所有对小猪数值的更改都必须通过事件触发。本次实现系统例行演化
（`regular_events`）：按 GMT+8 真实时间每天 9:00 触发，对所有小猪应用每日数值更新；
每次真实触发时实时记录事件到对应数据库，并提供 `pig diary [序号]` 展示值得记录的事件。

## 已确认的产品规则

1. **触发机制**：后台任务按 GMT+8 每天 9:00 执行；插件启动时若当天 9:00 已过则立即执行。
   停机多天恢复后，**数值演化补满所有错过的天**；但事件记录**每次真实触发实时记录一条**
   （不按错过的天回溯日期，`occurred_at` 为实际处理时间，描述为净值汇总）。
2. **每日规则**（每只小猪、每天）：
   - 年龄 `age_days` +1；
   - 体重 `weight_kg` 增长，增量在 (0, 1kg] 内随机（保留两位小数，最小 0.01kg）；
   - 心情 `mood` 随机偏移 ±5 以内，夹紧 0–100；
   - 健康 `health` 随机偏移 ±3 以内，夹紧 0–100；
   - 精力 `energy` 在 0–100 内完全随机生成。
3. **幂等**：同一 GMT+8 自然日内每只小猪最多演化一次，依据 `last_state_update_at`
   的 GMT+8 日期与今天比较；当天创建的小猪当天不演化（出生日即第 0 天）。
4. **事件记录**：每次触发为每只被演化的小猪实时记录一条例行事件，写入主人文档的
   `events` 列表；例行事件只能由系统触发，用户命令不可触发。
5. **事件类别**：`regular_events`（例行事件）本次实现；`unexpected_events`（突发事件）、
   `user_events`（用户事件）为后续功能预留。
6. **pig diary**：`pig diary` 展示整个猪圈最近 10 条值得记录的事件；`pig diary <序号>`
   展示该小猪的最近 10 条事件（序号与 `pig rename` 一致）。**例行事件不在 diary 展示**，
   只留痕于数据层。非法/越界序号返回 `用法：pig diary [序号]`。
7. **旧数据兼容**：`events` 字段带默认空元组，旧 JSON（无 `events` 键）可直接读取；
   `schema_version` 保持 1，无迁移。

## 数值模型

### `PigEvent`（新增）

| 字段 | 类型 | 约束与含义 |
| --- | --- | --- |
| `event_id` | UUID | 创建时生成，内部使用 |
| `category` | Literal | `regular_events` / `unexpected_events` / `user_events` |
| `pig_id` | UUID | 事件所属小猪的内部 ID |
| `occurred_at` | UTC 时间 | 事件真实发生时间（例行事件 = 触发处理时间，不做回溯） |
| `description` | 字符串 | 1–200 个非空字符的用户可读描述 |

`PigstyDocument` 新增 `events: tuple[PigEvent, ...] = ()`，与 `pigs` 同层存储。

## 触发与调度

- `core/evolution.py` 提供纯函数：`DAY_TZ`（固定 UTC+8）、`next_tick_at(now)`、
  `daily_tick_reached(now)`、`missed_day_count(pig, now)`、`evolve_pig_days(pig, days, occurred_at, rng)`、
  `evolve_document(document, now, rng)`。
- `core/service.py` 的 `evolve_all_due(now, rng)` 遍历仓储中所有文档
  （`repository.document_paths()` + `repository.update_path(path, mutation)`），
  逐文档原子演化；损坏文档计数为 `failed_documents`，不影响其余文档。
- `main.py` 在插件构造时启动后台 `asyncio` 循环：每次醒来先判断 GMT+8 9:00 是否已到，
  已到则执行一次演化，然后 `anyio.sleep` 到下一个 9:00；`terminate()` 取消该任务。
- 每次触发返回 `DailyTickSummary`（演化小猪数、事件数、扫描/跳过/失败文档数）留存于插件内部。

## 事件描述格式

例行事件描述为净值汇总（多天补进度时合并为一条）：

```text
年龄+1，体重+0.53kg，心情-2，健康+1，精力 65
年龄+3，体重+1.75kg，心情+0，健康+0，精力 42
```

## 命令契约

### `pig diary [序号]`

```text
你的猪圈事件记录：
1. [突发事件] 2026-08-20 09:00 · 1. 白雪 小猪：测试事件：捡到彩票
```

- 不带序号：整个猪圈最近 10 条非例行事件，新的在前；
- 带序号：该小猪最近 10 条非例行事件；
- 空结果：`你的猪圈还没有值得记录的事件。` / `这只小猪还没有值得记录的事件。`；
- 非法或越界序号：`用法：pig diary [序号]`。

未知 action 总用法同步更新：

```text
用法：pig status | pig add [@用户] [名字] | pig rename <序号> <新名字> | pig diary [序号] | pig show
```

## 架构与数据流

- `core/models.py`：新增 `PigEvent` 与文档级 `events`；时间戳校验抽取为共享私有函数。
- `core/evolution.py`：纯演化逻辑（可独立测试），复用 `randomizer.RandomSource` 注入随机源。
- `core/repository.py`：新增 `document_paths()`（发现所有持久化文档）与
  `update_path(path, mutation)`（对已发现文件做锁内读-改-原子写）；`load` 复用统一的
  `_read_existing` 校验路径（路径与文档身份一致性）。
- `core/service.py`：`evolve_all_due` 汇总调度；`list_events` 供 diary 读取。
- `main.py`：后台调度循环 + `pig diary` 渲染（GMT+8 展示时间、类别中文标签）。

## 错误与并发

- 例行演化逐文档执行；单个损坏文档（`PigstyDataError`）只计数不中断，缺失文件计为跳过。
- 所有写操作仍走仓储锁内原子写；演化与用户命令并发安全。
- 后台任务在 `terminate()` 时取消；不产生孤儿协程。

## 测试策略

- `tests/test_evolution.py`（纯函数）：9:00 边界、GMT+8 换算、欠账天数、每日规则、
  边界夹紧、多天合并为一条实时事件、非到期跳过、长期演化模型边界恒成立。
- `tests/test_models.py`：`PigEvent` 校验（类别、描述、UTC 规范化）、旧 JSON 无 `events`
  兼容、事件往返序列化。
- `tests/test_repository.py`：`document_paths` 发现、`update_path` 变更/缺失文件/身份改写拒绝。
- `tests/test_service.py`：`evolve_all_due` 跨文档演化、同日幂等、当天小猪跳过、损坏文档容错。
- `tests/test_plugin.py`：`pig diary` 用法/空记录/过滤展示/按序号过滤，`_run_daily_tick`
  触发与幂等，例行事件不出现在 diary。

## 预期修改文件

- 修改 `core/models.py`、`core/repository.py`、`core/service.py`、`core/__init__.py`、
  `main.py`、`tests/test_models.py`、`tests/test_repository.py`、`tests/test_service.py`、
  `tests/test_plugin.py`、`README.md`。
- 新增 `core/evolution.py`、`tests/test_evolution.py`。
