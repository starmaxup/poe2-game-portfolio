# 彗星落伤害模型（Python）

《流放之路2》彗星落技能的单体 / AOE 伤害期望模型，纯标准库实现。

## 文件说明

| 文件 | 作用 |
| --- | --- |
| `comet_model.py` | 核心模型：伤害流水线（基础 → inc 加法 → more 乘法 → 暴击加权 → 抗性）、DPS、击杀时间、敏感性分析 |
| `test_comet_model.py` | pytest 测试套件（12 项：暴击边界、抗性倍率、施速、scope 隔离、解析↔蒙特卡洛一致性） |
| `requirements.txt` | 依赖说明（模型本体零第三方依赖，测试需 pytest） |

## 运行

```bash
python comet_model.py     # 跑 demo，输出每击伤害 / DPS / 击杀时间
pytest -q                 # 跑测试
```
