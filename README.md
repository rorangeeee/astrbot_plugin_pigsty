# astrbot_plugin_pigsty

Pigsty 是一个独立于 AstrBot 部署目录的群友小猪圈插件项目。

## 第一阶段

- 提供可加载的 `PigstyPlugin` 骨架和 `pig status` 基础命令。
- 使用 Pydantic v2 严格模型保存小猪状态。
- 使用按平台、主人和作用域隔离的原子 JSON 仓储。
- 不实现 `pig add`、改名、喂食、玩耍、时间演化或 LLM 自然语言解析。

## 本地验证

```powershell
uv sync
uv run pytest -q
uv run ruff format --check .
uv run ruff check .
uv run basedpyright
```

插件运行时由 AstrBot 提供 `astrbot.*` 依赖；`core/` 不依赖 AstrBot，因此可以独立测试。
