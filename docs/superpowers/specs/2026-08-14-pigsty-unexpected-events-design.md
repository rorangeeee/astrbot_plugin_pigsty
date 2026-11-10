# Pigsty 突发事件设计

## 目标

引入突发事件（`unexpected_events`）：每只小猪每天独立掷骰判定，触发后在当天
9:00–18:00 间随机时刻推送消息；事件数值遵循每日演化规则，描述由默认对话大模型
构造（不带人格设定），并写入小猪数据库。

## 已确认的产品规则

1. **判定粒度**：每只小猪独立掷骰；pity 状态（`unexpected_chance_percent`、
   `unexpected_last_rolled_at`）存于小猪自身，随文档持久化。
2. **概率阶梯**：基础 20%；当天未触发则次日 +10%（20→30→…→100，封顶）；
   触发后次日重置 20%。
3. **判定时刻**：与例行演化同一天概念（9:00 触发判定）。同一 GMT+8 自然日内
   每只小猪最多掷一次（按 `unexpected_last_rolled_at` 判重）。
4. **影响数值**：随机 1 或 2 项（各 50%，两项不重复）；每项受影响数值独立掷档
   （与初始数值随机同一机制，相对**当前值**、方向双向随机）：

   | 概率 | 偏移幅度 | 采样方式 |
   | --- | --- | --- |
   | 75% | ≤5% | `当前值 × uniform(0.95, 1.05)` |
   | 15% | 5%–20% | `当前值 × uniform(0.05, 0.20)`，方向 ± |
   | 8% | 20%–50% | `当前值 × uniform(0.20, 0.50)`，方向 ± |
   | 2% | ≥50% | 有界字段在 `[0, 当前值×0.5] ∪ [当前值×1.5, 100]` 有效子区间均匀；体重负侧 `(0, 当前值×0.5]` 均匀、正侧重尾分布无上限 |

   复用 `core/randomizer.py` 的 `StatSpec`/`roll_stat`（以当前值为 base）；结果记录为
   相对当前值的带符号 delta。应用时夹紧到模型边界；只更新 `updated_at`，
   **不改** `last_state_update_at`（演化欠账标记语义不变）。
5. **推送时刻**：当天 GMT+8 9:00–18:00 均匀随机；若触发发生在 18:00 之后
   （启动补触发），随机时刻已过则立即推送。
6. **推送位置**：每只小猪单独保存 `push_origin`，新猪默认绑定添加时的群聊或
   私聊，独立于猪圈数据作用域。通过 AstrBot `MessageSession` 和 `MessageType`
   构造目标：`平台实例ID:GroupMessage:群ID` 或 `平台实例ID:FriendMessage:用户ID`。
   `pig bind <序号/all>` 将自己当前猪圈中的指定小猪或全部小猪绑定到命令所在会话。
   未绑定的旧猪仅记录事件，不安排推送；`pig show` 仅对未绑定的猪显示“未绑定”。
   已排队的通知在发送前读取最新绑定，换绑后发送到新会话，小猪被移除则取消通知。
7. **LLM 构造**：向默认对话大模型发起一次询问，不携带人格/系统提示词，仅发送
   小猪名字、变化项与数值以及构造请求 prompt，要求只回复事件描述；调用失败或
   返回空白时回退为数值变化摘要。
8. **数据留痕**：事件以 `unexpected_events` 类别写入文档 `events`，`occurred_at`
   为随机推送时刻；`pig diary` 自动展示（非例行事件）。

## 模板（本设计随功能一并落地）

LLM 构造请求 prompt：

```text
请根据以下信息为一只宠物小猪编写一条突发事件描述。
小猪名字：{name}
数值变化：{changes}
要求：仅输出事件描述本身（一句话，不超过50字），不要输出任何其他内容。
```

用户推送消息模板：

```text
⚠️ 突发事件：{position}. {name}
{description}
（数值变化：{changes}）
```

## 架构与数据流

- `core/unexpected.py`（新增，纯函数）：pity 阶梯 `next_chance`、同日判重
  `already_rolled_today`、单猪掷骰 `roll_unexpected_for_pig`、1–2 项采样
  `roll_stat_changes`、变化应用 `apply_stat_changes`、窗口时刻
  `pick_unexpected_moment`。四档掷点复用 `randomizer` 的 `StatSpec`/`roll_stat`
  （以当前值为 base）与 `RandomSource` 协议。
- `core/models.py`：`Pig` 新增 `unexpected_chance_percent`（默认 20，20–100）与
  `unexpected_last_rolled_at`（默认 None，UTC 规范化）；旧 JSON 直接兼容。
- `core/service.py`：`roll_unexpected_all(now, rng)` 遍历所有文档掷骰并持久化 pity，
  返回触发草稿 `UnexpectedOutcome(identity, pig, changes)`；`apply_unexpected_event`
  在仓储锁内应用变化并追加事件，目标不存在抛 `UnexpectedPigNotFoundError`。
- `main.py`：`_run_daily_tick` 在演化之后掷骰；每个触发草稿经 LLM seam 取描述、
  应用并记录事件、按随机时刻调度推送。后台循环统一管理「下一个 9:00」与「最早
  待发推送」两个唤醒点；`terminate()` 取消任务。
- AstrBot 边界 seam：`LlmClient`（`context.get_using_provider_async(umo)` +
  `Provider.text_chat(prompt, context=[], system_prompt="")`）与 `PigstyPusher`
  （`context.send_message(umo, MessageChain().message(text))`）；均可注入测试替身，
  第三方调用失败仅记日志、不中断例行流程。

## 容错与限制

- LLM 失败/无提供商 → 描述回退为「数值变化：…」；推送失败 → 记日志，事件与数据
  变更不受影响（用户仍可通过 `pig diary` 查看）。
- 插件在掷骰与推送之间重启会丢失当次推送（数据与事件已落库，仅推送丢失）。
- 空猪圈不掷骰、pity 不变。

## 测试策略

- `tests/test_unexpected.py`（纯函数）：概率阶梯、GMT+8 同日判重、触发/未触发路径、
  1–2 项采样与范围、变化应用与夹紧、演化标记不变、随机时刻窗口。
- `tests/test_models.py`：新字段默认值、范围校验、UTC 规范化、旧 JSON 兼容。
- `tests/test_service.py`：跨文档掷骰收集触发草稿、同日幂等、空仓库、
  事件应用与留痕、目标缺失报错。
- `tests/test_plugin.py`（子进程边界）：以 pity=100 武装单只小猪，注入假
  LLM/推送器，断言 prompt 内容、事件落库、定时推送文本模板与 `pig diary` 展示。
- `typings/` 与 `tests/fake_runtime/`：补齐 `Provider/LLMResponse/MessageChain` 与
  `Context` 的 LLM/主动消息公开面。

## 预期修改文件

- 新增 `core/unexpected.py`、`tests/test_unexpected.py`、
  `typings/astrbot/api/provider.pyi`、`tests/fake_runtime/astrbot/api/provider.py`。
- 修改 `core/models.py`、`core/service.py`、`core/__init__.py`、`main.py`、
  `pyproject.toml`（BLE001 豁免）、`typings/astrbot/api/event.pyi`、
  `typings/astrbot/api/star.pyi`、`tests/fake_runtime/astrbot/api/event.py`、
  `tests/fake_runtime/astrbot/api/star.py`、`tests/test_models.py`、
  `tests/test_service.py`、`tests/test_plugin.py`、`README.md`。
