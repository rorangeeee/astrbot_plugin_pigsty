# astrbot_plugin_pigsty

Pigsty 是一个独立于 AstrBot 部署目录的群友小猪圈插件项目。

## 第一阶段

- 提供可加载的 `PigstyPlugin` 骨架和 `pig status` 基础命令。
- 使用 Pydantic v2 严格模型保存小猪状态。
- 使用按平台、主人和作用域隔离的原子 JSON 仓储。
- 不实现改名、喂食、玩耍、时间演化或 LLM 自然语言解析。

## 当前命令

- `pig status`：查看数据层状态和当前作用域。
- `pig add`：在调用者自己的猪圈中添加一只独立小猪；独立小猪可以重复添加。
- `pig add @用户`：在调用者自己的猪圈中添加一只与目标用户关联的小猪。被 @ 用户只作为小猪的关联属性，不会成为数据库主人；同一数据库内相同平台和用户的关联组合不能重复添加。
- `pig show`：按保存顺序查看调用者猪圈中的小猪及基础状态，不展示内部 UUID。猪圈为空时会提示 `你的猪圈还是空的，使用 pig add 添加一只小猪吧。`

未知命令会提示：`用法：pig status | pig add [@用户] | pig show`。

## 数据归属与作用域

- 每位命令调用者拥有自己的数据库，所有添加和查看操作都以调用者为准。
- `global` 作用域按平台和调用者隔离；`group` 作用域还会按群组隔离。

## 本地验证

```powershell
uv sync
uv run pytest -q
uv run ruff format --check .
uv run ruff check .
uv run basedpyright
```

插件运行时由 AstrBot 提供 `astrbot.*` 依赖；`core/` 不依赖 AstrBot，因此可以独立测试。
