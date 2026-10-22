# PoE2 游戏策划作品集 · Game Design Portfolio

> 一个游戏策划实习生的**可验证**作品集：标准拆解案 + 可运行数值模型。

## 项目结构

```
poe2-game-portfolio/
├── 01-game-design/
│   ├── 《流放之路：降临》拆解案.md      # 全案 GDD 拆解（8 大模块）
│   └── assets/
│       └── core-loop.png            # 核心循环流程图
└── 02-comet-damage-model/
    ├── comet_model.py               # 彗星落技能伤害期望模型（Python）
    ├── test_comet_model.py          # pytest 测试套件（15 项用例）
    ├── DATA_SOURCES.md              # 数据来源与假设（真实 wiki 值 vs 代表性量级）
    ├── README.md                    # 模型详细说明（含施法时间三口径）
    └── requirements.txt             # 运行依赖说明
```

## 01 · 游戏拆解案

对《流放之路：降临》（Path of Exile 2）的标准化拆解，覆盖 8 大模块：
核心定位与商业复盘、玩家体验溯源、核心玩法循环、全链路系统架构、内容/关卡体系、
数值闭环与经济体系、叙事体系、优点/缺陷/可落地改进方案。

## 02 · 彗星落伤害模型

把技能伤害拆解为一条可复用的流水线：

```
基础 + 固定
  → × inc（加法区）
  → × more（乘法区，带 scope 标签：global/spell/cold/fire/area…）
  → 暴击加权（noncrit×命中率 + crit×暴击倍率×暴击率）
  → × 抗性减免（含 -200% 抗性地板）
  → 每击伤害
  → ÷ 施法时间（三口径：serial_complete / serial_start / pipelined）
  → DPS / 击杀时间
```

模型特点：

- **纯 Python 标准库**，无第三方依赖即可运行。
- **解析解 ↔ 蒙特卡洛（10 万抽样）双重校验**，误差 < 1%。
- **15 项 pytest 测试**覆盖：暴击边界、抗性倍率、施法速度/DPS、scope 隔离、解析↔模拟一致性、敏感性口径继承、三口径排序等。
- **施法时间三口径**：`serial_complete`（施法动画 + 落点延迟）/ `serial_start`（取较慢者）/ `pipelined`（真流水线，默认），可切换、可复现。
- 支持回填游戏内 tooltip 数值，做口径自洽校验（`TooltipRef` + `verify()`）。
- **数据来源分层**：技能基础与辅助宝石乘区取自 poewiki 真实数值；BD 的 inc/flat/暴击聚合为代表性量级（详见 `DATA_SOURCES.md`）。

### 运行方式

```bash
cd 02-comet-damage-model

pip install -r requirements.txt      # 仅需 pytest
python comet_model.py                # 运行 demo：输出每击伤害 / 三口径 DPS / 击杀时间
pytest -q                            # 运行 15 项测试用例 → 15 passed
```

## 诚实性说明（Important）

本仓库的彗星落伤害模型，输入数据分两层：

- **真实来源**：技能基础数值（20 级 829~1243 冰冷、施法 1.0s、暴击 13%、+1s 落点延迟、蓝耗 173）与辅助宝石乘区（元素集中 25% more、范围集中 30% more、冰冷穿透 30%），均取自 poewiki / poe2db。
- **代表性量级**：BD 的 inc / flat / 暴击聚合等，取自公开 BD 指南的典型终局冰法量级，**不是**某一具体角色的精确 PoB 导出值。

施法时间口径是模型**假设**（默认 `pipelined`），并非游戏源码验证结论；三种口径的 DPS 结果区间约 9,928 ~ 23,330。

因此本作品集应表述为「搭建了可验证的伤害期望模型（解析解 ↔ 蒙特卡洛 ↔ 游戏内 tooltip 三方校验）」，**不应**表述为「分析了 PoE2 真实 BD 伤害」。若填入自己的游戏内 tooltip 并通过 `verify()`，方可称「已用真实 BD 校验通过」。

---

© 余浩杰 · 游戏策划实习生作品集
