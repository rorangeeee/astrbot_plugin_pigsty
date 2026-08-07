# Pigsty 宏观命令与数据库设计

## 目标

在现有 Pigsty foundation 上增加第一批可用业务能力：

- 固化每位命令调用者独立的 Pigsty JSON database 模板；
- 实现 `pig add`，创建一只不绑定群成员的独立随机小猪；
- 实现 `pig add @用户`，把一个用户作为可选成员属性写入调用者自己的猪圈；
- 实现 `pig show`，列出调用者当前 database 中的小猪。

本阶段只做宏观创建和查看，不实现改名、喂食、玩耍、成长、死亡/疾病、时间 Tick、批量行为、LLM 意图识别、管理员迁移或 Dashboard。

## 已确认的产品规则

1. **Database owner 是命令调用者。** 被 @ 用户永远不会替代调用者成为 database owner。
2. **每个用户一个自己的 database。** 继续通过当前 `pigsty_scope`、平台 ID、调用者 ID 和可选群 ID 生成 `SessionIdentity`，继续使用 `JsonPigstyRepository` 的 SHA-256 路径。
3. **随机小猪是独立实体。** `pig add` 不查询群成员列表，不伪造成员 ID；它只生成随机 Pig UUID 和格式为 `小猪-xxxxxxxx` 的随机显示名，基础状态沿用当前 Pig 默认值。
4. **@ 关系是 Pig 的附属属性。** `pig add @用户` 将当前事件的平台 ID 和目标用户 ID 写到新 Pig 上，但仍写入调用者的 database。
5. **重复关联拒绝。** 同一 database 中，同一平台 ID + 用户 ID 的已关联 Pig 不允许再次添加；独立随机 Pig 不受该规则限制。
6. **一个命令最多一个目标。** 没有有效目标时创建独立 Pig；恰好一个具体 `Comp.At` 时创建关联 Pig；多个目标、`all` 或无法读取目标 ID 时返回用法错误。Self mention 可以作为明确目标，但不改变 database owner。

## 数据模型与 Database 模板

### `Pig`

保留现有严格冻结 Pydantic 模型和状态字段。将以下两个关联字段改为成对可选：

```python
member_platform_id: str | None = None
member_user_id: str | None = None
```

二者必须同时为 `None` 或同时为非空字符串；已有包含字符串的 JSON 继续有效。其余字段和默认值保持不变：

- `pig_id`：UUID，创建时生成；
- `name`：`小猪-` 加 8 位 UUID 十六进制片段；
- `age_days=0`、`weight_kg=5.0`、`health=100`、`mood=70`、`energy=80`；
- 四个时间字段使用带时区的 UTC 时间。

### `PigstyDocument`

继续作为一位 database owner 的完整 JSON 模板：

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

`schema_version` 继续为 `1`。本次是对 Pig 关联字段的向后兼容放宽，不需要迁移脚本。缺失文件的 `load()` 仍返回匹配 identity 的空 document，但不创建文件；第一次 `pig add` 才写盘。

## 核心服务边界

新增 AstrBot-independent 的 Pig 创建/业务服务模块，例如 `core/service.py`，只依赖 `core.models`、`core.identity` 和 `JsonPigstyRepository`。

服务提供以下职责：

- 创建独立随机 Pig；
- 创建带成员关联的 Pig；
- 在 repository `update()` 锁内追加 Pig；
- 按 `member_platform_id + member_user_id` 检查重复关联；
- 读取当前 document 供 `pig show` 使用。

所有写操作必须通过 `JsonPigstyRepository.update()` 完成，不能在命令层手工执行 `load → 修改 → save`，以保留现有进程内并发更新保护和原子写入语义。

## AstrBot 适配层

`main.py` 继续是唯一 AstrBot 依赖入口。适配层只负责把真实事件转换成核心服务需要的数据：

- `event.get_sender_id()` → database owner user ID；
- `event.get_platform_id()` → platform ID；
- `event.get_group_id()` → optional group ID；
- `event.get_messages()` → 消息组件列表。

@ 解析使用 AstrBot 公开组件 API：

```python
import astrbot.api.message_components as Comp

for segment in event.get_messages():
    if isinstance(segment, Comp.At):
        target_user_id = segment.qq
```

禁止依赖 `astrbot.core.message.*` 内部组件。缺失必要 owner/platform 信息时返回边界错误，不静默写入共享 database。

## 命令契约

### `pig add`

调用核心服务在调用者的 identity 中追加独立 Pig，成功返回：

```text
已添加独立小猪：小猪-xxxxxxxx
```

不向用户暴露 Pig UUID，也不创建成员关联。

### `pig add @用户`

从消息组件提取一个具体目标 ID，在调用者的 identity 中追加关联 Pig，成功返回：

```text
已将用户 <user_id> 添加为小猪：小猪-xxxxxxxx
```

重复关联返回提示且不写盘；多个 @、`all` 或无效目标返回：

```text
用法：pig add [@用户]
```

### `pig show`

只加载调用者的 identity。空 database 返回：

```text
你的猪圈还是空的，发送 pig add 添加一只小猪。
```

非空 database 按 `pigs` 的持久化顺序输出序号、名称、独立/关联状态和基础状态（体重、健康、心情、体力）。关联 Pig 显示目标用户 ID；Pig UUID 永不输出。

### 其他输入

保留 `pig status` 的 foundation readiness 响应；未知 action 返回对应使用提示，不修改 database。

## 错误与并发

- 重复关联使用明确的领域异常或结果类型，由适配层转换为用户可读提示；不使用空 catch 或静默覆盖。
- 损坏 JSON、未知 schema、模型校验失败继续由 `PigstyDataError` 处理，禁止恢复为空 database。
- 添加操作统一在 repository lock 内完成，确保并发 `pig add` 不丢失已经存在的 Pig。
- `pig show` 不写盘，缺失文件不因查看命令产生空文件。

## 测试策略

### 核心模型/服务

- 独立随机 Pig 的成员字段均为 `None`，名称格式正确，默认状态正确；
- 关联 Pig 的两个成员字段同时存在；单字段关联被拒绝；
- 同一 owner database 可以保存多个独立 Pig；
- 同一 platform/user 关联重复时拒绝；不同 user 或不同 owner 可添加；
- 并发追加保留所有成功添加结果。

### AstrBot 边界

扩展测试桩以覆盖公开事件契约：`get_sender_id()`、`get_platform_id()`、`get_group_id()`、`get_messages()`，并提供 `Comp.At(qq=...)`。

边界测试必须证明：

- 无 @ 的 `pig add` 写入调用者 database；
- `pig add @user` 仍写入调用者 database，只把 target ID 放入 Pig；
- `pig show` 只读取调用者 database；
- global/group/platform/owner 隔离仍由 `SessionIdentity` 保证；
- 输出不包含 Pig UUID。

所有测试继续使用临时目录和 fake AstrBot runtime，不读取真实 AstrBot 部署数据。

## 参考实现

本设计参考本机 `data/plugins/astrbot_plugin_rollpig` 的公开 API 使用方式：

- 用 `event.get_sender_id()` 固定 owner；
- 用 `astrbot.api.message_components.Comp.At` 读取 @ 目标；
- 不把被 @ 用户覆盖成 owner；
- 不复制其简单 JSON persistence、缺少 platform/group 隔离的 owner key 或内部组件导入。

## 预期修改文件

- `core/models.py`：放宽成员关联字段并补充成对校验；
- `core/service.py`：新增纯核心创建、去重和原子追加服务；
- `main.py`：新增事件 identity 解析、@ 解析、`pig add` 与 `pig show`；
- `typings/astrbot/api/event.pyi`：补齐公开事件方法签名；
- `typings/astrbot/api/message_components.pyi`：补齐 `Comp.At` 类型；
- `tests/fake_runtime/astrbot/api/event.py` 与 `tests/fake_runtime/astrbot/api/message_components.py`：补齐测试 runtime；
- `tests/test_models.py`、新服务测试、`tests/test_plugin.py`：锁定核心和边界契约；
- `README.md`：更新命令和当前阶段范围。
