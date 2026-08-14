# Pigsty 初始数值随机设计

## 目标

每只小猪生成时，体重、健康、心情、体力四项基础数值各自独立掷点，
按 75/15/8/2 的概率落入四档偏移；落出 75% 正常档的数值在 `pig add` 播报中标记。

## 已确认的产品规则

1. 参与字段为 `weight_kg`、`health`、`mood`、`energy`；`age_days` 保持 0（百分比偏移对 0 无意义）。
2. 每项数值独立掷档，互不影响。
3. 偏移方向双向随机（可低于初始值）。
4. 2% 档只要求偏移幅度不小于 50%，在模型全局约束内取值；体重只有下限（>0kg），字面意义上无上限。
5. 落出 75% 正常档的数值，在生成播报中追加"体质异变"标记；全部正常时不追加，保持既有文本。
6. 掷点结果随 `Pig` 持久化；`schema_version` 保持 1，模型结构不变。

## 档位表

| 概率 | 偏移幅度 | 采样方式 |
| --- | --- | --- |
| 75% | ≤5% | `base × uniform(0.95, 1.05)` |
| 15% | 5%–20% | `base × uniform(0.05, 0.20)`，方向 ± |
| 8% | 20%–50% | `base × uniform(0.20, 0.50)`，方向 ± |
| 2% | ≥50% | 见下 |

2% 档取值：

- 有界字段（健康/心情/体力）：在 `[0, base×0.5]` 与 `[base×1.5, 100]` 的有效子区间内按区间长度加权均匀采样（如健康 base=100 时上区间为空，只在 `[0, 50]` 采样）。
- 体重：负侧在 `(0, 2.5kg]` 均匀采样；正侧从 `1.5×base + Exp(λ=0.5)` 重尾分布采样，无硬上限（均值约 3.5×base ≈ 17.5kg，远超均值的事件概率按指数衰减）。

## 取整与约束

- 健康/心情/体力：四舍五入为整数，夹紧到 `[0, 100]`。
- 体重：保留两位小数，夹紧到 `≥ 0.01kg`；模型无上限。
- 档位语义按取整前的掷点值判定；取整只带来 ±0.005kg / ±0.5 数值的舍入差。

## 播报格式

任一数值落出 75% 档时，`pig add` 播报追加标记：

```text
已添加独立小猪：小猪-1a2b3c4d（体质异变：体重 7.5kg，心情 45）
已将用户 123456 添加为小猪：小猪-1a2b3c4d（体质异变：健康 12）
```

全部正常时文本与既有契约完全一致，不追加任何后缀。

## 架构与数据流

- `core/randomizer.py`：纯掷点模块。`roll_initial_stats(rng)` 返回 `InitialStatsRoll`（含各字段取值与档位），通过 `RandomSource` 协议注入随机源以便测试；未注入时使用系统熵初始化的 `random.Random()`。
- `core/service.py`：`add_random` / `add_member` 先掷点再构造 `Pig`，返回 `PigCreation(pig, roll)`；写入仍走 `JsonPigstyRepository.update()` 原子路径，重复关联检查不变。
- `main.py`：适配层根据 `roll.anomalies` 渲染"体质异变"标记；`pig show` 继续展示持久化数值，无需改动。

## 错误与并发

- 随机逻辑不抛领域异常；掷点结果经过严格模型校验（越界已被取整/夹紧）。
- 重复关联仍抛 `DuplicateMemberPigError`，不写盘。
- 无 schema 变更、无迁移；旧 JSON 文件直接兼容。

## 测试策略

- `tests/test_randomizer.py`：档位阈值、各档边界、双向符号、2% 档全局约束、体重无上限、异常收集、种子可复现、档位分布、模型边界恒成立。全部纯函数测试，不依赖临时目录。
- `tests/test_service.py`：掷点值进入 `Pig` 并持久化；`PigCreation` 报告异常字段；既有 add/rename/show 契约保持。
- `tests/test_plugin.py`：打桩固定掷点，断言播报标记文本与无标记文本；随机场景下从播报剥离标记后缀再断言既有契约。
- `tests/conftest.py`：提供 `ScriptedRng` 脚本化随机源。

## 预期修改文件

- 新增 `core/randomizer.py`、`tests/test_randomizer.py`、`tests/conftest.py`。
- 修改 `core/service.py`、`core/__init__.py`、`main.py`、`tests/test_service.py`、`tests/test_plugin.py`、`pyproject.toml`（如 Ruff 要求）、`README.md`。
