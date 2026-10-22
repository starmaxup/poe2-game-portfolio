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
    ├── test_comet_model.py          # pytest 测试套件（12 项）
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
  → ÷ 施法时间 = DPS / 击杀时间
```

模型特点：
- **纯 Python 标准库**，无第三方依赖即可运行。
- **解析解 ↔ 蒙特卡洛（10 万抽样）双重校验**，误差 < 1%。
- **12 项 pytest 测试**覆盖：暴击边界、抗性倍率、施法速度/DPS、scope 隔离、解析↔模拟一致性等。
- 支持回填游戏内 tooltip 数值，做口径自洽校验（`TooltipRef` + `verify()`）。

### 运行方式

```bash
cd 02-comet-damage-model

pip install -r requirements.txt      # 仅需 pytest
python comet_model.py                # 运行 demo：输出每击伤害 / DPS / 击杀时间
pytest -q                            # 运行 12 项测试 → 12 passed
```

## 诚实性说明（Important）

本仓库中的 **彗星落伤害模型使用示例 / 占位数值**，用于演示「可验证的建模方法论框架」
与「测试闭环」，并非真实 PoE2 数据。若填入游戏内真实 tooltip 数值并通过校验，
方可表述为「已用真实 BD 校验通过」。

---

© 余浩杰 · 游戏策划实习生作品集
