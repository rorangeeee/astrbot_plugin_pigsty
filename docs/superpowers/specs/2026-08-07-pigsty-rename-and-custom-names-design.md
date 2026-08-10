# Pigsty 改名与自定义名称设计

## 目标

在现有 Pigsty 命令基础上增加：

- `pig add 名字`：创建独立小猪并使用自定义名称；
- `pig add @用户 名字`：创建关联小猪并使用自定义名称；
- `pig rename 序号 新名字`：按 `pig show` 展示的 1-based 序号改名。

未提供名称时继续使用现有的 `小猪-xxxxxxxx` 自动命名。名称支持空格，内部数据模型仍要求名称为非空、最多 32 个字符的字符串。

## 已确认的产品规则

1. **保留现有命令入口。** 继续使用 `@filter.command("pig")`，不改成 command group。
2. **名称支持空格。** 适配层从 `event.message_str` 中定位 action 后，读取剩余纯文本并去除首尾空白，保留中间空格。
3. **@ 目标仍来自消息组件。** `event.get_messages()` 中恰好一个具体 `At` 才是关联目标；名称不从 At 文本推断。多个 At、空白 ID 和 `all` 仍返回用法错误。
4. **rename 使用展示序号。** `pig show` 中第一只小猪的序号为 1，第二只为 2；序号映射到持久化 `pigs` 元组的创建顺序。无需向用户暴露 UUID。
5. **改名只修改名称和更新时间。** `pig_id`、成员关联、基础状态、创建时间和持久化顺序保持不变；`updated_at` 更新为当前 UTC 时间。
6. **无名称 add 保持兼容。** `pig add` 与 `pig add @用户` 的自动命名、重复成员保护和现有成功文本继续有效。

## 命令契约

### `pig add`

| 输入 | 行为 |
| --- | --- |
| `pig add` | 创建独立小猪，名称为 `小猪-xxxxxxxx` |
| `pig add 名字` | 创建独立小猪，名称为剩余文本 |
| `pig add @用户` | 创建关联小猪，自动命名 |
| `pig add @用户 名字` | 创建关联小猪，名称为剩余文本 |

成功文本保持现有格式，只替换最终名称：

```text
已添加独立小猪：<name>
已将用户 <user_id> 添加为小猪：<name>
```

缺少或非法目标、重复关联、名称为空或超过模型限制时，不写入数据库并返回用户可读的用法/错误提示。

### `pig rename`

```text
pig rename <序号> <新名字>
```

成功返回：

```text
已将第 <序号> 只小猪改名为：<新名字>
```

序号无法解析为正整数、超出当前猪圈范围或缺少新名字时，不写入数据库并返回：

```text
用法：pig rename <序号> <新名字>
```

未知 action 的总用法同步包含：

```text
用法：pig status | pig add [@用户] [名字] | pig rename <序号> <新名字> | pig show
```

## 架构与数据流

### AstrBot 适配层：`main.py`

- 保留处理器的 `action` 参数，避免依赖 AstrBot 对多词字符串参数的 token 化行为。
- 新增一个供 `add` 和 `rename` 共用的纯文本尾部解析路径：在 `event.message_str` 中定位当前 action token，返回其后的完整文本。
- 在项目的 AstrBot stub 中声明 `message_str` 公开字段，保持适配层的严格类型检查。
- 继续用现有 `_member_target_for_event()` 解析 At 组件。
- `add` 将尾部文本作为 `str | None` 传给服务；空尾部表示使用默认名称。
- `rename` 将尾部文本拆成第一个 token（正整数序号）和剩余完整名称，序号在适配层解析为 `int` 后传给服务。
- 只在适配层把领域异常转换为用户可读文本；核心层不依赖 AstrBot。

### 核心服务：`core/service.py`

- 扩展 `add_random()` 和 `add_member()`，接受可选名称；名称缺省时继续生成 UUID 派生名称。
- 新增按 1-based 序号改名的方法，使用 `JsonPigstyRepository.update()` 在同一锁内完成读取、定位、校验和写入。
- 序号越界抛出明确的领域异常；名称仍通过现有 `Pig` Pydantic 模型校验。
- 改名返回更新后的 `Pig`，供适配层生成成功文本。

### 持久化与模型

- `core/models.py` 不改变 schema 版本或字段结构。
- 使用现有不可变模型复制/验证路径更新名称和 `updated_at`。
- 不新增迁移、不新增兼容层；旧 JSON 文件可直接读取。

## 错误与并发

- 所有 add/rename 写操作继续使用 repository 的原子 `update()`，不在命令层执行 `load → 修改 → save`。
- 越界序号和重复成员使用 typed domain exceptions，由 `main.py` 转换为稳定用户文本。
- 名称边界复用 `Pig.name` 的非空和最大长度约束；命令层不静默截断名称。
- 失败的解析、校验或领域操作不应改变持久化文档。

## 测试策略

### 服务层：`tests/test_service.py`

- 自定义名称的独立 add 会持久化完整多词名称。
- 自定义名称的关联 add 会持久化完整多词名称和成员关联。
- 无名称 add 仍生成 `小猪-xxxxxxxx`。
- rename 会保留 UUID、成员关联、状态和顺序，只更新名称与 `updated_at`。
- rename 越界不写入数据库。

### AstrBot 边界：`tests/test_plugin.py` 与 fake runtime

- fake `AstrMessageEvent` 增加 `message_str`，模拟 AstrBot 的纯文本消息字段。
- 覆盖 `pig add 名字`、`pig add @用户 名字`、无名称 add、`pig rename 2 新 名字` 和 show 输出。
- 覆盖缺少名称、非法序号、越界序号、多个 At 和重复成员，确认失败后数据不变。
- 继续确认输出不暴露 UUID，且目标用户不会成为 database owner。

### 文档：`README.md`

- 删除“暂不实现改名”的过时说明。
- 添加自定义名称、改名序号和完整命令用法。

## 预期修改文件

- `main.py`：解析名称尾部、扩展 add、添加 rename 和用户提示。
- `core/service.py`：可选名称和按序号原子改名。
- `tests/fake_runtime/astrbot/api/event.py`：支持 `message_str`。
- `typings/astrbot/api/event.pyi`：声明 `AstrMessageEvent.message_str`。
- `tests/test_service.py`：核心服务回归测试。
- `tests/test_plugin.py`：命令边界和用户输出测试。
- `README.md`：同步命令契约。
