# 彗星落伤害模型（Python）

《流放之路2》彗星落技能的单体 / AOE 伤害期望模型，纯标准库实现。

## 文件说明

| 文件 | 作用 |
| --- | --- |
| `comet_model.py` | 核心模型：伤害流水线（基础 → inc 加法 → more 乘法 → 暴击加权 → 抗性）、DPS、击杀时间、敏感性分析 |
| `test_comet_model.py` | pytest 测试套件（14 项：暴击边界、抗性倍率、施速、scope 隔离、解析↔蒙特卡洛一致性；v3.5 新增 T8 敏感性口径继承、T9 三口径排序） |
| `requirements.txt` | 依赖说明（模型本体零第三方依赖，测试需 pytest） |
| `DATA_SOURCES.md` | **数据来源与诚实声明**：哪些输入是真实 wiki 数据、哪些是代表性量级、如何用游戏内 tooltip 做真实校验 |

## 数据来源（v3.3 起）

- **技能基础（真实）**：poewiki 彗星落成长表（版本 0.3.0+），20 级基础冰冷 829~1243、施法 1.0s、暴击 13%、+1s 落点延迟。`COMET_GEM_TABLE` 含 1~20 级完整真实成长，可用 `CometSkill.from_gem_level(n)` 取任意等级。
- **辅助宝石 more 乘区 / 穿透（真实）**：Elemental Focus 25% more 元素、Concentrated Area 30% more 范围、Cold Penetration 穿透 30% 冰抗（均取自 poewiki / poe2db）。
- **BD 的 inc/flat/暴击（代表性量级）**：典型终局冰法构筑水平，基于公开 BD 指南，非精确拷贝。
- **真实校验入口**：`TooltipRef` 填入你的游戏内 tooltip，`verify()` 即可模型 vs 面板对比（误差 <5% PASS）。

## 施法时间口径（v3.5 起·三种一等公民口径）

`total_cast_time()` 支持三种口径，由构造参数 `cast_time_mode` 选择（默认 `pipelined` = 真流水线）：

- `serial_complete`（最保守）：`施法动画 + 落点延迟`，必须等上一发落地才能放下一发。v3.3 旧口径。
- `serial_start`：`max(施法动画, 落点延迟)`，施法动画与落点延迟重叠取较慢者。v3.4 初版 `pipelined`（改名澄清）。
- `pipelined`（默认·真流水线）：`施法动画`，彗星可多颗同落，每施法动画落一发，施速直接生效。

演示 BD 下三口径 DPS：serial_complete ≈ 9,928 / serial_start ≈ 17,282 / pipelined ≈ 23,330。

> 三种口径的根本差异是「落点延迟的计时起点」这一假设，并非绝对真理。详见 `DATA_SOURCES.md` 第四节（审阅者必问，已主动写明）。`sensitivity()` 严格继承 `cast_time_mode`，基准与扰动模型口径一致。

## 敏感性分析标签（v3.4 修正）

`sensitivity()` 为每个参数标注**真实扰动语义**（相对 −20% / 绝对 −0.20 冰抗 / 绝对 −0.20 暴击率 / 全部 more ×0.8），不再用误导性的统一 “Δ-20%” 表头。详见 `DATA_SOURCES.md` 第五节。

> 诚实声明：本模型是「可验证的建模方法论框架」，不是对某一真实 BD 的精确复现。详见 `DATA_SOURCES.md`。

## 运行

```bash
python comet_model.py     # 跑 demo，输出每击伤害 / DPS / 击杀时间
pytest -q                 # 跑测试（需安装 pytest）
```
