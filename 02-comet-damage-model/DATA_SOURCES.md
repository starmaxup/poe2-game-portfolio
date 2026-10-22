# 数据来源说明 / Data Sources

本目录的 `comet_model.py` 输入数据分为两类：**真实来源** 与 **代表性量级**。
这样做是为了在「可复现的建模方法论」与「不虚构精确 DPS」之间保持诚实。

> v3.4 起，模型另外显式区分了「**数据来源**」与「**建模假设**」：
> - 数据来源（技能基础、宝石乘区、穿透）= 真实 wiki 数据，见下文一~二。
> - 建模假设（施法时间口径、BD 量级）= 可辩护的工程选择，见下文四、五，均可切换/复现。

---

## 一、技能基础数值（真实来源 ✅）

来源：**poewiki — Comet**
`https://poe2wiki.net/wiki/Comet`
抓取时间：2026-10-22（版本 0.3.0+，当前正式版本）

| 字段 | 值（宝石 20 级） | 说明 |
| --- | --- | --- |
| 基础冰冷伤害 | 829 ~ 1243 | 直接取自 wiki 成长表 |
| 施法时间 | 1.0 s | |
| 落点延迟 | +1.0 s（总施法时间） | wiki 原文 “+1 second to Total Cast Time” |
| 暴击率 | 13% | |
| 暴击伤害倍率 | 1.50x | PoE 系列基础暴击倍率默认值 |
| 影响半径 | 2.8 m | |
| 蓝耗 | 173 | 20 级 |

模型内置 `COMET_GEM_TABLE`（1~20 级完整成长表，同来源），
可用 `CometSkill.from_gem_level(n)` 取任意等级的**真实**基础值。

> 注：旧版占位值 787~1181（20 级）对应更早补丁，已在 v3.3 废弃。

---

## 二、辅助宝石「更多」乘区与穿透（真实来源 ✅）

| 模型字段 | 真实数值 | 来源 |
| --- | --- | --- |
| `MoreMod(1.25, 'elemental')` | 元素集中 Elemental Focus：25% more 元素伤害 | poewiki Elemental Focus（static_stat1_value=25） |
| `MoreMod(1.30, 'area')` | 范围集中 Concentrated Area：30% more 范围伤害 | poewiki / poe2db.tw Concentrated Area |
| `cold_penetration_pct=0.30` | 冰冷穿透 Cold Penetration：穿透 30% 冰抗 | poewiki Cold Penetration |

> 这些数值直接来自辅助宝石的官方/社区 wiki，可作真实输入使用。

---

## 三、BD 的 inc / flat / 暴击（代表性量级 ⚠️）

`inc_spell / inc_cold / inc_elemental / inc_area / flat_cold / cast_speed_pct /
crit_chance_add / crit_mult_add / cold_exposure_pct` 为**典型终局冰法构筑的量级**，
取自公开 BD 指南（如 Frostbolt Comet / Stormweaver、CoC Comet 等）的常规装备与天赋水平，
**并非某一套具体 BD 的精确拷贝**。

参考构筑指南（量级来源，非精确数据）：
- https://www.poe-vault.com/poe2/sorceress/stormweaver/frostbolt-comet-build-guide
- https://www.sportskeeda.com/mmo/path-exile-2-coc-comet-sorceress-build-guide

> 原因：精确的「增加 X% 伤害」合计需要具体角色 Path of Building（PoB）导出，
> 不同角色/装备差异极大，无法用单一公开网页直接获得可复现的聚合值。
> 因此这里使用「量级合理、可辩护」的代表值，并在代码注释中标注。

---

## 四、施法时间口径（三种一等公民口径）【v3.5 重做】

模型对「一次循环用多久」支持三种口径，由 `CometModel(..., cast_time_mode=...)` 选择（`anim = base_cast/(1+cs)`）：

| 口径 | 公式 | 物理含义 | 默认 |
| --- | --- | --- | --- |
| `serial_complete` 串行(完成计时) | `anim + fall_delay` | 必须等上一发「落地（施法完成计）」才能放下一发 | 否 |
| `serial_start` 串行(开始计时) | `max(anim, fall_delay)` | 施法动画与落点延迟重叠，瓶颈取较慢者（v3.4 初版 'pipelined' 改名） | 否 |
| `pipelined` 真流水线 | `anim` | 彗星可多颗同时下落，每 anim 秒稳定落一发，施速直接生效 | **是** |

以演示 BD（施速 35% → anim≈0.74s，落点延迟 1.0s）为例：

| 口径 | 循环时间 | 单目标 DPS |
| --- | --- | --- |
| serial_complete | 1.741s | 9,928 |
| serial_start | 1.000s | 17,282 |
| pipelined | 0.741s | 23,330 |

### 关键假设：fall_delay 的「计时起点」
三种口径的根本差异，在于把落点延迟的**计时起点**放在哪里——这是一个**模型假设**，不是从游戏源码验证的真理：

- **fall_delay 从「施法开始」计时**：落点延迟与施法动画天然并行，不该被施速影响（当前实现 `fall_delay_affected_by_cast_speed=False` 即如此）。此时 `serial_start = max(anim, fall)` 与 `pipelined = anim` 都合理，区别只在「是否允许多颗彗星同时下落」。
- **fall_delay 从「施法完成」计时**：上一发必须「落地（完成+延迟）」才能放下一发，应回到 `serial_complete = anim + fall`。

**默认选 `pipelined = anim` 的理由**：PoE2 的彗星落允许多颗彗星同时处于下落状态，稳定状态下「每 anim 秒落一发」是真实持续输出的上限；且游戏内 tooltip 通常按「每施法时间」(=anim) 展示 DPS，二者一致，便于用 `verify()` 对照。若你实测 tooltip 更接近串行结果，把 `cast_time_mode='serial_complete'` 或 `'serial_start'` 即可——三种口径全部开放、可切换、可复现。

### 诚实边界（审阅者必问，主动说清）
- 上述口径是工程假设，并非绝对真理。作品集里应写明：「模型支持三种施法时间口径，默认真流水线，DPS 区间约 9,928~23,330」。
- 不要把任一数字宣称为「PoE2 彗星落的真实 DPS」；它取决于你填入的 BD 与游戏内 tooltip。
- `sensitivity()` 严格继承 `cast_time_mode`，基准与扰动模型口径一致（v3.5 修复了 `m2` 漏传口径的隐患，并有 T8 测试钉死）。
- 在 `pipelined = anim` 口径下，施速直接缩短 anim，故 `cast_speed_pct` 敏感性**非零**（演示约 −5.2%）；而在 `serial_start` 口径下，当 anim < fall_delay 时落点延迟成硬瓶颈，施速敏感性才趋于 0。

## 五、敏感性分析的扰动语义【v3.4 修正】

`sensitivity()` 不再对所有参数共用 “Δ-20%” 表头（那对绝对量有误导性），而是为每个参数标注**真实扰动语义**：

| 参数类型 | 扰动语义（默认 ±20% 基准） | 举例 |
| --- | --- | --- |
| `inc_*` / `flat_*` | 相对 ±20%（×(1±0.2)） | inc_cold 1.10 → 0.88 |
| `cold_penetration_pct` / `cold_exposure_pct` | 绝对 ±0.20 冰抗（百分点） | 0.30 → 0.10（相对 −67%） |
| `crit_chance_add` | 绝对 ±0.20 暴击率（百分点） | 0.32 → 0.12 |
| `crit_mult_add` | 绝对 ±0.10 暴击倍率（0.5×Δ映射） | — |
| `more_all` | 全部 more 各自 ×(1±0.2) | 1.25 → 1.00 |

表中「**DPS变化%**」列才是跨参数可比的敏感度指标（相对基准 DPS 的变化百分比）；「扰动」列仅说明该参数被改动了多少，不暗示「都是 −20%」。

## 六、如何做真实校验（你的游戏内 tooltip）

模型专门保留了 `TooltipRef` 用于真实校验：

```python
from comet_model import CometModel, CometSkill, Build, Target, TooltipRef, MoreMod

skill = CometSkill.from_gem_level(20)
build = Build(...)  # 把你的实际 BD 数值填进来
target = Target(enemy_hp=500_000, enemies_in_radius=1)

# 把游戏内 Comet 面板的「每击伤害」与「DPS」填进来：
tip = TooltipRef(
    per_hit_min=?, per_hit_max=?,   # 面板「伤害」区间
    dps=?,                          # 面板 DPS
    dps_includes_crit=True, dps_includes_aoe=False, dps_uses_cast_speed=True,
)
m = CometModel(skill, build, target, tip)
ok, rep = m.verify()   # 模型输出将与你的 tooltip 对照，误差<5% 即 PASS
```

只要把你自己的 BD 数值 + 游戏内 tooltip 喂进去，`verify()` 就能给出模型与真实面板的对比——
这才是本模型「可验证」的核心价值。

---

## 七、诚实声明

本模型是**可验证的建模方法论框架**：
- 技能基础 = 真实 wiki 数据；
- 辅助宝石乘区/穿透 = 真实 wiki 数据；
- BD 的 inc/flat/暴击 = 代表性量级（基于公开指南，非精确拷贝）；
- 最终 DPS 是否「等于现实」取决于你填入的 BD 与 tooltip 是否真实。

简历 / 作品集中应表述为「搭建了可验证的伤害期望模型框架（解析解 ↔ 蒙特卡洛 ↔ 游戏内 tooltip 三方校验）」，
**不要**表述为「分析了 PoE2 真实 BD 伤害」。
