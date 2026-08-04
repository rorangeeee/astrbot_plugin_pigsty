# AstrBot Pigsty Foundation Design

## 目标

在 `C:\Users\wkc20\astrbot_plugin_pigsty` 建立独立于 AstrBot 部署目录的插件项目。第一阶段只交付可加载的插件骨架、严格类型化的小猪数据模型、每位主人独立的 JSON 仓储，以及验证这些边界的自动化测试。

`pig add`、改名、喂食、玩耍、时间演化和 LLM 自然语言行为解析不属于本阶段；它们将在后续阶段建立在本数据层上。

## 项目布局

```text
astrbot_plugin_pigsty/
├── main.py
├── metadata.yaml
├── _conf_schema.json
├── requirements.txt
├── pyproject.toml
├── README.md
├── core/
│   ├── __init__.py
│   ├── identity.py
│   ├── models.py
│   └── repository.py
├── tests/
│   ├── test_identity.py
│   ├── test_models.py
│   └── test_repository.py
└── docs/superpowers/
    ├── specs/
    └── plans/
```

各文件只承担一个职责：`main.py` 负责 AstrBot 接入，`identity.py` 负责会话身份与文件键，`models.py` 负责数据契约，`repository.py` 负责持久化。

## 配置和作用域

插件配置项 `pigsty_scope` 允许 `global` 和 `group` 两个值，默认值为 `global`。

- `global`：同一平台上的同一主人在所有群聊和私聊共享一个猪圈。
- `group`：群聊按平台、群 ID、主人 ID 隔离；私聊没有群 ID，因此仍落入该平台主人的全局私聊空间。
- 平台 ID 是身份的一部分，避免 QQ、Telegram 等平台上相同文本用户 ID 发生碰撞。
- 切换配置只改变后续读取的数据空间，不自动复制、合并或删除另一作用域的数据。

仓储不会直接把外部 ID 拼入路径。它对规范化身份字符串计算 SHA-256，使用摘要作为目录名和文件名，防止路径穿越、非法字符及可枚举文件名。

## 小猪数据模型

`Pig` 使用 Pydantic v2 严格模型。JSON 中保存以下字段：

| 字段 | 类型 | 约束与含义 |
| --- | --- | --- |
| `pig_id` | UUID 字符串 | 创建时生成；内部使用，聊天输出不得展示 |
| `member_platform_id` | 字符串 | 被加入猪圈的群友所属平台 |
| `member_user_id` | 字符串 | 被加入猪圈的群友平台用户 ID |
| `name` | 字符串 | 1–32 个非空字符；默认命名在后续 `pig add` 阶段定义 |
| `age_days` | 整数 | 大于等于 0，表示当前模拟年龄天数 |
| `weight_kg` | 浮点数 | 大于 0，单位千克 |
| `health` | 整数 | 0–100 |
| `mood` | 整数 | 0–100 |
| `energy` | 整数 | 0–100 |
| `born_at` | UTC 时间 | 模拟出生时间，为后续时间演化提供基准 |
| `created_at` | UTC 时间 | 记录创建时间 |
| `updated_at` | UTC 时间 | 最近一次状态变化时间 |
| `last_state_update_at` | UTC 时间 | 最近一次执行自然时间演化的时间 |

第一阶段的模型工厂默认值为：`age_days=0`、`weight_kg=5.0`、`health=100`、`mood=70`、`energy=80`。所有时间使用带时区的 UTC ISO 8601 字符串。

每份主人文件使用 `PigstyDocument` 模型：

```json
{
  "schema_version": 1,
  "scope": "global",
  "platform_id": "aiocqhttp",
  "owner_user_id": "123456",
  "group_id": null,
  "pigs": []
}
```

`schema_version` 为将来的显式迁移保留。读取未知版本必须报错，不能猜测或静默覆盖。

## JSON 仓储

`JsonPigstyRepository` 接收 AstrBot 插件数据目录，向其下的 `owners/` 写入文件：

```text
owners/
├── global/<owner-identity-hash>.json
├── private/<owner-identity-hash>.json
└── groups/<group-identity-hash>/<owner-identity-hash>.json
```

仓储提供最小接口：

- `load(identity) -> PigstyDocument`：文件不存在时返回与身份匹配的空猪圈，不立即写盘。
- `save(document) -> None`：验证模型后以 UTF-8、格式化 JSON 写入。
- `update(identity, mutation) -> PigstyDocument`：在仓储锁内执行读取、变更和写入，供后续命令避免并发丢失更新。

文件写入先写同目录临时文件并刷新，然后通过 `os.replace` 原子替换目标。JSON 语法错误、模型校验错误和不支持的 schema 版本统一转换为带路径信息的 `PigstyDataError`。仓储不得在读取失败后重建空文件。

第一阶段使用仓储级 `anyio.Lock` 保证同一进程内更新串行化。文件操作通过 `anyio.to_thread.run_sync` 执行，避免阻塞 AstrBot 事件循环。

## AstrBot 接入

`main.py` 中的 `PigstyPlugin` 继承 `astrbot.api.star.Star`：

- 构造时读取 `pigsty_scope`，通过 `StarTools.get_data_dir("astrbot_plugin_pigsty")` 获取持久化目录并创建仓储。
- 提供 `pig status` 基础命令，用于显示当前作用域和数据层已就绪，不创建或修改小猪。
- `terminate()` 保持异步生命周期接口；本阶段没有长驻任务或需关闭的资源。
- 业务模型与仓储不得导入 `astrbot.*`，从而可以在未启动 AstrBot 的环境中测试。

插件元数据声明 `astrbot_version: ">=4.16,<5"`，配置 schema 将 `pigsty_scope` 显示为全局/按群选择框。

## 测试策略

实现严格遵循红—绿—重构：

1. `test_identity.py`：验证全局、群聊、私聊作用域解析，以及哈希路径不包含外部 ID。
2. `test_models.py`：验证默认状态、隐藏 UUID、数值边界、空名称、带时区时间和 JSON 往返。
3. `test_repository.py`：验证不存在文件返回空猪圈、不同主人隔离、不同群隔离、全局跨群共享、原子写入、并发更新和损坏文件拒绝覆盖。
4. 对 `main.py` 仅做导入/骨架测试；实际平台命令行为留到增加 `pig add` 时做 AstrBot 集成测试。

质量门为 `ruff format --check .`、`ruff check .`、`basedpyright` 和 `pytest`。所有测试使用临时目录，不读取或修改真实 AstrBot 部署数据。

## 非目标与后续扩展点

本阶段不会实现：群友 @ 解析、重复收养规则、命名、喂食、玩耍、死亡/疾病、时间 Tick、批量行为、自然语言意图识别、LLM Tool、管理员迁移命令或 Dashboard 页面。

后续功能必须通过 `JsonPigstyRepository.update()` 修改模型，并由单独的领域服务计算状态变化；LLM 只产生受约束的行为意图，不能直接生成或覆盖 JSON。
