# -*- coding: utf-8 -*-
"""
彗星落 (Comet, PoE2) 伤害期望模型 —— 可验证版 v3.5
===================================================
变更（v3.4 -> v3.5）：
  - 【施法时间三口径】v3.4 的 'pipelined'（=max(anim,fall)）被指出仍是「修正串行」，不是真流水线。
    现 total_cast_time(mode) 支持三种一等公民口径：
      · 'serial_complete' 串行(完成计时): anim + fall_delay      —— 最保守，v3.3 旧口径
      · 'serial_start'    串行(开始计时): max(anim, fall_delay)   —— v3.4 初版 'pipelined'（改名澄清）
      · 'pipelined'       真流水线:        anim                   —— 可多颗同落，每 anim 落一发，施速生效（默认）
    默认 cast_time_mode='pipelined'（真流水线）；tooltip_dps_model(dps_uses_cast_speed) 当 True 时走当前口径，
    当 False 时固定用 (base_cast_time + fall_delay) 作为「tooltip 展示用施法时间」（不含施速、不读 cast_time_mode）。
    三口径差异与「fall_delay 计时起点」假设见 DATA_SOURCES.md 第四节（审阅者必问，主动写明）。
  - 【Bug 修复·sensitivity 口径继承】sensitivity() 构造扰动模型时漏传 cast_time_mode，
    导致 base 与扰动模型口径可能不一致（base=serial 时整张表会错）。现 m2 继承 self.cast_time_mode。
  - 【Issue 2·敏感性标签·延续】sensitivity() 每个参数标注真实扰动语义（相对−20% / 绝对−0.20 冰抗 /
    绝对−0.20 暴击率 / 全部more×0.8），表头「负向扰动 / 正向扰动 / DPS变化%」。
  - 技能基础数值(CometSkill)来自真实来源：poewiki 当前版本(0.3.0+)宝石成长表，20 级基础冰冷 829~1243。
  - 演示 BD 为「有据可查的参考 BD」：more 乘区与穿透取自真实辅助宝石数值，其余 inc/flat/暴击为典型终局冰法量级。
  - 保留 demo()：仅 `python comet_model.py` 时运行；TooltipRef 默认留空，请填入你的游戏内 tooltip 做真实校验。
  - 模型全部计算公式与 pytest(15 项用例) 保持自洽；本版修正「施法时间假设」与「敏感性标签」，不改动伤害流水线。

数据来源（详见仓库 02-comet-damage-model/DATA_SOURCES.md）：
  - 技能基础：https://poe2wiki.net/wiki/Comet （2026-10-22 抓取，版本 0.3.0+）
  - 辅助宝石：Elemental Focus / Concentrated Area / Cold Penetration 等同上 wiki 与 https://poe2db.tw
  - 参考构筑：Frostbolt Comet（Stormweaver）等公开 BD 指南（数值为代表性量级，非精确拷贝）
诚实声明：本模型是「可验证的建模方法论框架」。技能基础为真实 wiki 数据；BD 为基于真实辅助宝石的
        参考构筑，精确 DPS 需以你自己的游戏内 tooltip / Path of Building 导出为准。
"""

import random
import copy
import csv
import json
from dataclasses import dataclass, field

RESIST_FLOOR = -2.0
DEFAULT_SEED = 12345
VALID_SCOPES = {'global', 'spell', 'cold', 'fire', 'lightning', 'elemental', 'area'}

# —— 真实数据：彗星落宝石 1~20 级成长表（来源 poewiki "Comet"，版本 0.3.0+，2026-10-22 抓取）——
# 字段: (mana_cost, base_cold_min, base_cold_max)
COMET_GEM_TABLE = {
    1:  (17,  24,   36),
    2:  (20,  33,   49),
    3:  (23,  45,   67),
    4:  (27,  59,   88),
    5:  (31,  74,  111),
    6:  (36,  92,  138),
    7:  (41, 112,  168),
    8:  (46, 135,  202),
    9:  (52, 161,  241),
    10: (59, 190,  285),
    11: (67, 223,  335),
    12: (75, 261,  391),
    13: (84, 304,  456),
    14: (93, 353,  529),
    15: (104, 408, 613),
    16: (115, 472, 708),
    17: (128, 544, 816),
    18: (142, 627, 940),
    19: (157, 721, 1081),
    20: (173, 829,  1243),
}

# —— 数据来源登记（供审计 / 作品集展示）——
DATA_SOURCES = {
    "skill_base": "poewiki.net/wiki/Comet (v0.3.0+, 2026-10-22)",
    "support_more_elemental_focus": "poewiki Elemental Focus: 25% more Elemental Damage",
    "support_more_concentrated_area": "poewiki/poe2db Concentrated Area: 30% more Area Damage",
    "support_cold_penetration": "poewiki Cold Penetration: penetrate 30% Cold Resistance",
    "reference_build": "Frostbolt Comet 等公开 BD 指南（量级参考，非精确拷贝）",
    "tooltip_check": "请用你游戏内的 Comet tooltip 覆盖 TooltipRef 做真实校验",
}


@dataclass
class CometSkill:
    gem_level: int = 20
    base_cold_min: float = 829.0
    base_cold_max: float = 1243.0
    base_cast_time: float = 1.0
    fall_delay: float = 1.0
    base_crit_chance: float = 0.13
    base_crit_mult: float = 1.50
    radius_m: float = 2.8
    mana_cost: float = 173.0
    fire_infusion_dmg_min: float = 0.0
    fire_infusion_dmg_max: float = 0.0


    @classmethod
    def from_gem_level(cls, level: int = 20) -> "CometSkill":
        """按真实宝石成长表取某等级的技能基础数值（poewiki，版本 0.3.0+）。"""
        if level not in COMET_GEM_TABLE:
            raise ValueError(f"Comet 仅支持 1~20 级，收到 {level}")
        mana, cmin, cmax = COMET_GEM_TABLE[level]
        return cls(gem_level=level, base_cold_min=float(cmin), base_cold_max=float(cmax),
                   mana_cost=float(mana))


@dataclass
class MoreMod:
    value: float
    scope: str

    def __post_init__(self):
        if self.scope not in VALID_SCOPES:
            raise ValueError(f"MoreMod.scope 非法: {self.scope!r}，可选 {sorted(VALID_SCOPES)}")
        if self.value <= 0:
            raise ValueError(f"MoreMod.value 必须 > 0，当前 {self.value}")


@dataclass
class Build:
    flat_cold: float = 0.0
    flat_fire: float = 0.0
    flat_lightning: float = 0.0

    inc_spell: float = 0.0
    inc_cold: float = 0.0
    inc_fire: float = 0.0
    inc_lightning: float = 0.0
    inc_elemental: float = 0.0
    inc_area: float = 0.0
    inc_against_frozen: float = 0.0

    more_multipliers: tuple = field(default_factory=lambda: ())

    cast_speed_pct: float = 0.0
    crit_chance_add: float = 0.0
    crit_mult_add: float = 0.0

    enemy_cold_res: float = 0.0
    cold_exposure_pct: float = 0.0
    cold_penetration_pct: float = 0.0
    enemy_fire_res: float = 0.0
    fire_exposure_pct: float = 0.0
    fire_penetration_pct: float = 0.0

    hits_per_cast: float = 1.0
    cast_time_mult: float = 1.0
    use_fire_infusion: bool = False


@dataclass
class Target:
    enemy_hp: float = 500_000.0
    enemies_in_radius: int = 1
    is_frozen: bool = False


@dataclass
class TooltipRef:
    per_hit_min: float = 0.0
    per_hit_max: float = 0.0
    dps: float = 0.0
    tolerance: float = 0.05
    dps_includes_crit: bool = True
    dps_includes_aoe: bool = False
    dps_uses_cast_speed: bool = True


SCOPE_FOR = {
    'cold': {'global', 'spell', 'cold', 'elemental', 'area'},
    'fire': {'global', 'spell', 'fire', 'elemental', 'area'},
    'lightning': {'global', 'spell', 'lightning', 'elemental', 'area'},
}


class CometModel:
    def __init__(self, skill: CometSkill, build: Build, target: Target, tip: TooltipRef,
                 cast_time_mode: str = "pipelined"):
        """
        cast_time_mode: 施法时间口径（三选一，详见 DATA_SOURCES.md 第四节）
          'serial_complete' 串行(完成计时): anim + fall_delay      —— 最保守，v3.3 旧口径
          'serial_start'    串行(开始计时): max(anim, fall_delay)   —— v3.4 初版 'pipelined'（改名）
          'pipelined'       真流水线:        anim                   —— 可多颗同落，每 anim 落一发（默认）
        """
        self.s = skill
        self.b = build
        self.t = target
        self.tip = tip
        self.cast_time_mode = cast_time_mode
        self._validate()

    def _crit_chance(self) -> float:
        return min(max(self.s.base_crit_chance + self.b.crit_chance_add, 0.0), 1.0)

    def _crit_mult(self) -> float:
        return self.s.base_crit_mult + self.b.crit_mult_add

    def _resist_mult(self, dtype: str) -> float:
        if dtype == 'fire':
            eff = self.b.enemy_fire_res - self.b.fire_exposure_pct - self.b.fire_penetration_pct
        elif dtype == 'cold':
            eff = self.b.enemy_cold_res - self.b.cold_exposure_pct - self.b.cold_penetration_pct
        else:
            eff = 0.0
        eff = max(eff, RESIST_FLOOR)
        return 1.0 - eff

    def _inc_for(self, dtype: str) -> float:
        f = 1.0
        f += self.b.inc_spell
        f += self.b.inc_area
        if self.t.is_frozen:
            f += self.b.inc_against_frozen
        f += self.b.inc_elemental
        if dtype == 'cold':
            f += self.b.inc_cold
        elif dtype == 'fire':
            f += self.b.inc_fire
        elif dtype == 'lightning':
            f += self.b.inc_lightning
        return f

    def _more_for(self, dtype: str) -> float:
        m = 1.0
        allow = SCOPE_FOR[dtype]
        for mod in self.b.more_multipliers:
            if mod.scope in allow:
                m *= mod.value
        return m

    def _base_which(self, dtype: str, which: str) -> float:
        if dtype == 'cold':
            if which == 'min':
                return self.s.base_cold_min
            if which == 'max':
                return self.s.base_cold_max
            return (self.s.base_cold_min + self.s.base_cold_max) / 2.0
        elif dtype == 'fire':
            if not self.b.use_fire_infusion:
                return 0.0
            fmin, fmax = self.s.fire_infusion_dmg_min, self.s.fire_infusion_dmg_max
            if which == 'min':
                return fmin
            if which == 'max':
                return fmax
            return (fmin + fmax) / 2.0
        return 0.0

    def _flat_for(self, dtype: str) -> float:
        if dtype == 'cold':
            return self.b.flat_cold
        if dtype == 'fire':
            return self.b.flat_fire
        if dtype == 'lightning':
            return self.b.flat_lightning
        return 0.0

    def _per_hit(self, dtype: str, crit: bool, which: str) -> float:
        base = self._base_which(dtype, which)
        flat = self._flat_for(dtype)
        dmg = (base + flat) * self._inc_for(dtype) * self._more_for(dtype)
        if crit:
            dmg *= self._crit_mult()
        dmg *= self._resist_mult(dtype)
        return dmg

    def avg_hit_type(self, dtype: str) -> float:
        cc = self._crit_chance()
        non = self._per_hit(dtype, False, 'avg')
        cri = self._per_hit(dtype, True, 'avg')
        return non * (1 - cc) + cri * cc

    def avg_damage_per_cast(self) -> float:
        return (self.avg_hit_type('cold') + self.avg_hit_type('fire')) * self.b.hits_per_cast

    def average_hit(self) -> float:
        return self.avg_damage_per_cast()

    # ---------------- 暴击伤害（显式功能块） ----------------
    # 底层计算已在 _per_hit(dtype, crit=True) 中乘 _crit_mult() 完成；
    # 以下方法把“暴击伤害”提升为一等公民，便于单独展示与验证。
    def noncrit_hit(self, dtype: str = 'cold', which: str = 'avg') -> float:
        """非暴击单次命中伤害（不含暴击倍率）。"""
        return self._per_hit(dtype, False, which)

    def crit_hit(self, dtype: str = 'cold', which: str = 'avg') -> float:
        """暴击单次命中伤害 = 非暴击伤害 × 暴击倍率。"""
        return self._per_hit(dtype, True, which)

    def crit_multiplier(self) -> float:
        """当前暴击伤害倍率（基础 + 附加），如 1.50 表示暴击造成 150% 伤害。"""
        return self._crit_mult()

    def crit_hit_chance(self) -> float:
        """当前有效暴击率（已夹紧到 [0,1]）。"""
        return self._crit_chance()

    def crit_dps_contribution(self) -> float:
        """暴击机制对每施法期望伤害的增益占比（相对“无暴击”基线），单位 %。
        例：50.0 表示因暴击机制，每施法期望伤害比完全没有暴击时高 50%。
        公式: (avg - noncrit_avg) / noncrit_avg × 100。"""
        non = (self.noncrit_hit('cold', 'avg') + self.noncrit_hit('fire', 'avg')) * self.b.hits_per_cast
        avg = self.avg_damage_per_cast()
        if non <= 0:
            return 0.0
        return (avg - non) / non * 100.0

    def total_cast_time(self, mode: str = None) -> float:
        """单次循环的施法时间（秒）。支持三种口径（均由 CometModel(cast_time_mode=...) 选择）：

        'serial_complete' : 串行(完成计时) = anim + fall_delay
                            必须等上一发「落地（施法完成计）」才能放下一发；最保守，v3.3 旧口径。
        'serial_start'    : 串行(开始计时) = max(anim, fall_delay)
                            施法动画与落点延迟重叠，瓶颈取较慢；v3.4 初版 'pipelined'，现改名以澄清。
        'pipelined'       : 真流水线 = anim
                            彗星可多颗同时下落，每 anim 秒稳定落一发；施速直接生效。最贴近游戏内 tooltip
                            的 cast_time 口径（tooltip 通常按「每施法时间」算 DPS）。默认。

        其中 anim = base_cast_time / (1 + cast_speed_pct)。
        当 fall_delay 从「施法开始」计时时，它与 anim 天然并行，不应被施速影响
        （fall_delay_affected_by_cast_speed=False 即如此）。三种口径差异与「fall_delay 计时起点」
        假设见 DATA_SOURCES.md 第四节。
        """
        if mode is None:
            mode = self.cast_time_mode
        cs = self.b.cast_speed_pct
        anim = self.s.base_cast_time / (1.0 + cs)
        fall = self.s.fall_delay  # 固定落地延迟，不吃施速

        if mode == 'serial_complete':
            raw = anim + fall
        elif mode == 'serial_start':
            raw = max(anim, fall)
        elif mode == 'pipelined':
            raw = anim
        else:
            raise ValueError(f"未知 cast_time_mode: {mode!r}")
        return raw * self.b.cast_time_mult

    def casts_per_sec(self) -> float:
        t = self.total_cast_time()
        return 1.0 / t if t > 0 else 0.0

    def single_target_dps(self) -> float:
        return self.avg_damage_per_cast() * self.casts_per_sec()

    def aoe_total_dps(self) -> float:
        return self.single_target_dps() * max(self.t.enemies_in_radius, 1)

    def kill_time(self) -> float:
        st = self.single_target_dps()
        if st <= 0:
            return float('inf')
        return self.t.enemy_hp / st

    def monte_carlo_avg(self, n: int = 100_000, seed: int = DEFAULT_SEED) -> float:
        rng = random.Random(seed)
        cc = self._crit_chance()
        total = 0.0
        for _ in range(n):
            crit = rng.random() < cc
            total += self._per_hit('cold', crit, 'avg') + self._per_hit('fire', crit, 'avg')
        return total / n * self.b.hits_per_cast

    def _validate(self):
        errs = []
        if self.cast_time_mode not in ('serial_complete', 'serial_start', 'pipelined'):
            errs.append("cast_time_mode 必须是 'serial_complete' / 'serial_start' / 'pipelined'")
        if self.b.cast_time_mult <= 0:
            errs.append("cast_time_mult 必须 > 0")
        if not (-1.0 <= self.b.crit_chance_add <= 1.0):
            errs.append("crit_chance_add 应在 [-1,1]（附加暴击率，可为负）")
        eff_cc = min(max(self.s.base_crit_chance + self.b.crit_chance_add, 0.0), 1.0)
        if not (0.0 <= eff_cc <= 1.0):
            errs.append(f"有效暴击率越界: {eff_cc:.3f}")
        if self.s.base_cold_max < self.s.base_cold_min:
            errs.append("base_cold_max < base_cold_min")
        if self.s.fire_infusion_dmg_max < self.s.fire_infusion_dmg_min:
            errs.append("fire_infusion_dmg_max < fire_infusion_dmg_min")
        for mod in self.b.more_multipliers:
            if mod.scope not in VALID_SCOPES:
                errs.append(f"more scope 非法: {mod.scope!r}")
        if errs:
            raise ValueError("Build 输入非法: " + "; ".join(errs))

    def per_hit_range_noncrit(self):
        cmin = self._per_hit('cold', False, 'min') + self._per_hit('fire', False, 'min')
        cmax = self._per_hit('cold', False, 'max') + self._per_hit('fire', False, 'max')
        return cmin, cmax

    def tooltip_dps_model(self) -> float:
        """按 TooltipRef 的口径还原「游戏内 tooltip DPS」：
        - dps_includes_crit=True/False：用含暴击/仅非暴击的每施法伤害。
        - dps_uses_cast_speed=True：用当前 cast_time_mode 的 casts_per_sec（与默认 DPS 口径一致）。
        - dps_uses_cast_speed=False：固定用 (base_cast_time + fall_delay) 作为 tooltip 展示用施法时间
          （不含施速、不读 cast_time_mode）——对应「tooltip 通常不把落点延迟/施速折算进循环」的展示口径。
        - dps_includes_aoe=True：再乘敌人数。
        注意：这是「还原 tooltip 显示值」的模型，与 single_target_dps() 的「真实持续输出 DPS」可能是两个不同数字，
              差异来源正是上面 three 口径假设，作品集里需区分清楚。
        """
        if self.tip.dps_includes_crit:
            dmg = self.avg_damage_per_cast()
        else:
            dmg = (self._per_hit('cold', False, 'avg') + self._per_hit('fire', False, 'avg')) \
                  * self.b.hits_per_cast

        if self.tip.dps_uses_cast_speed:
            cps = self.casts_per_sec()
        else:
            t = (self.s.base_cast_time + self.s.fall_delay) * self.b.cast_time_mult
            cps = 1.0 / t if t > 0 else 0.0

        st = dmg * cps
        if self.tip.dps_includes_aoe:
            st *= max(self.t.enemies_in_radius, 1)
        return st

    def verify(self):
        rep = []
        ok = True
        mc = self.monte_carlo_avg()
        an = self.avg_damage_per_cast()
        rel = abs(mc - an) / an if an else 0
        c1 = rel < 0.01
        ok &= c1
        rep.append(("解析均值", f"{an:,.0f}", "蒙特卡洛", f"{mc:,.0f}", f"误差 {rel*100:.2f}%", c1))
        if self.tip.per_hit_max > 0:
            lo, hi = self.per_hit_range_noncrit()
            in_range = (lo >= self.tip.per_hit_min * (1 - self.tip.tolerance)
                        and hi <= self.tip.per_hit_max * (1 + self.tip.tolerance))
            ok &= in_range
            rep.append(("Tooltip每击", f"[{self.tip.per_hit_min:,.0f}~{self.tip.per_hit_max:,.0f}]",
                        "模型(非暴)", f"[{lo:,.0f}~{hi:,.0f}]", "对照", in_range))
        if self.tip.dps > 0:
            md = self.tooltip_dps_model()
            rel = abs(md - self.tip.dps) / self.tip.dps
            c3 = rel < self.tip.tolerance
            ok &= c3
            flags = ("含暴击" if self.tip.dps_includes_crit else "不含暴击") + \
                    ("/含AoE" if self.tip.dps_includes_aoe else "/单目标") + \
                    ("/含施速" if self.tip.dps_uses_cast_speed else "/无施速")
            rep.append(("Tooltip DPS", f"{self.tip.dps:,.0f}", "模型DPS", f"{md:,.0f}", flags, c3))
        return ok, rep

    def _cast_speed_dps_ratio(self, cs_old: float, cs_new: float, mode: str = None) -> float:
        """施速 cs_old→cs_new 时，DPS 的理论倍率 = t(cs_old)/t(cs_new)。
        t() 的口径必须与 single_target_dps 一致（默认走 self.cast_time_mode），否则 T4 会失配。"""
        if mode is None:
            mode = self.cast_time_mode

        def t(cs):
            anim = self.s.base_cast_time / (1 + cs)
            if mode == 'serial_complete':
                return anim + self.s.fall_delay
            elif mode == 'serial_start':
                return max(anim, self.s.fall_delay)
            elif mode == 'pipelined':
                return anim
            raise ValueError(f"未知 cast_time_mode: {mode!r}")
        return t(cs_old) / t(cs_new)

    @staticmethod
    def _perturb_label(mode: str, d: float) -> str:
        """把 (扰动类型, 数值) 翻译成人类可读的「真实扰动语义」标签。
        解决旧版所有参数共用 'Δ-20%' 表头、对绝对量（穿透/暴击率/more 乘区）造成误导的问题。"""
        s = "-" if d < 0 else "+"
        a = abs(d)
        if mode == 'pct':
            return f"{s}{a*100:.0f}% 相对 (×{1+d:.2f})"
        if mode == 'more_all':
            return f"全部 more ×{1+d:.2f}"
        if mode == 'abs_res':
            return f"{s}{a:.2f} 冰抗/暴露 (绝对)"
        if mode == 'abs_crit':
            return f"{s}{a:.2f} 暴击率 (绝对)"
        if mode == 'abs_critmult':
            return f"{s}{a*0.5:.2f} 暴击倍率 (绝对)"
        return f"{s}{a}"

    def sensitivity(self, deltas=None):
        if deltas is None:
            deltas = [-0.2, -0.1, 0.1, 0.2]
        base = self.single_target_dps()
        # (参数, 扰动语义): pct=相对±20%；abs_res=绝对±0.20 冰抗；abs_crit=绝对±0.20 暴击率；
        #                   abs_critmult=绝对±0.10 暴击倍率；more_all=全部 more 各自×(1±0.20)
        specs = [
            ('inc_spell', 'pct'),
            ('inc_cold', 'pct'),
            ('inc_fire', 'pct'),
            ('inc_elemental', 'pct'),
            ('inc_area', 'pct'),
            ('flat_cold', 'pct'),
            ('cast_speed_pct', 'pct'),
            ('cold_penetration_pct', 'abs_res'),
            ('cold_exposure_pct', 'abs_res'),
            ('crit_chance_add', 'abs_crit'),
            ('crit_mult_add', 'abs_critmult'),
            ('more_all', 'more_all'),
        ]
        rows = []
        for attr, mode in specs:
            impacts = []
            for d in deltas:
                b2 = copy.deepcopy(self.b)
                if mode == 'more_all':
                    b2.more_multipliers = tuple(
                        MoreMod(mv.value * (1 + d), mv.scope) for mv in b2.more_multipliers)
                elif mode == 'pct':
                    old = getattr(b2, attr)
                    setattr(b2, attr, old * (1 + d) if old != 0 else d)
                elif mode == 'abs_res':
                    setattr(b2, attr, getattr(b2, attr) + d)
                elif mode == 'abs_crit':
                    old = getattr(b2, attr)
                    setattr(b2, attr, max(-1.0, min(1.0, old + d)))
                elif mode == 'abs_critmult':
                    setattr(b2, attr, getattr(b2, attr) + 0.5 * d)
                m2 = CometModel(self.s, b2, self.t, self.tip, cast_time_mode=self.cast_time_mode)
                new = m2.single_target_dps()
                impacts.append((d, (new - base) / base * 100 if base else 0.0))
            minus = impacts[0][1]
            plus = impacts[-1][1]
            label_neg = self._perturb_label(mode, deltas[0])
            label_pos = self._perturb_label(mode, deltas[-1])
            rows.append((attr, label_neg, label_pos, minus, plus, max(abs(minus), abs(plus))))
        rows.sort(key=lambda r: -r[5])
        return rows

    def to_dict(self):
        bd = {}
        for k, v in self.b.__dict__.items():
            if k == "more_multipliers":
                bd[k] = [{"value": m.value, "scope": m.scope} for m in v]
            else:
                bd[k] = v
        return {
            "skill": dict(self.s.__dict__),
            "build": bd,
            "target": dict(self.t.__dict__),
            "tooltip": dict(self.tip.__dict__),
            "cast_time_mode": self.cast_time_mode,
        }

    @classmethod
    def from_dict(cls, d):
        skill = CometSkill(**d["skill"])
        mms = tuple(MoreMod(**m) if isinstance(m, dict) else m for m in d["build"]["more_multipliers"])
        bd = dict(d["build"]); bd["more_multipliers"] = mms
        build = Build(**bd)
        target = Target(**d["target"])
        tip = TooltipRef(**d["tooltip"])
        mode = d.get("cast_time_mode", "pipelined")
        return cls(skill, build, target, tip, cast_time_mode=mode)

    def to_json(self, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, path):
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    def export_metrics_csv(self, path):
        cc = self._crit_chance()
        cm = self._crit_mult()
        nc = self.noncrit_hit('cold', 'avg')
        cr = self.crit_hit('cold', 'avg')
        t_cur = self.total_cast_time()
        t_sc = self.total_cast_time('serial_complete')
        t_ss = self.total_cast_time('serial_start')
        t_pl = self.total_cast_time('pipelined')
        dmg = self.avg_damage_per_cast()
        dps_cur = self.single_target_dps()
        dps_sc = dmg / t_sc if t_sc > 0 else 0.0
        dps_ss = dmg / t_ss if t_ss > 0 else 0.0
        dps_pl = dmg / t_pl if t_pl > 0 else 0.0
        rows = [
            ["指标", "数值"],
            ["施法时间口径", self.cast_time_mode],
            ["暴击率", f"{cc*100:.1f}%"],
            ["暴击倍率", f"{cm:.2f}x"],
            ["非暴击每击(冰冷 均值)", f"{nc:,.0f}"],
            ["暴击每击(冰冷 均值)", f"{cr:,.0f}"],
            ["暴击期望伤害贡献", f"{self.crit_dps_contribution():.1f}%"],
            ["每施法期望伤害(解析)", f"{dmg:,.1f}"],
            ["总施法时间(s)[serial_complete]", f"{t_sc:.3f}"],
            ["总施法时间(s)[serial_start]", f"{t_ss:.3f}"],
            ["总施法时间(s)[pipelined]", f"{t_pl:.3f}"],
            ["单目标DPS[serial_complete]", f"{dps_sc:,.1f}"],
            ["单目标DPS[serial_start]", f"{dps_ss:,.1f}"],
            ["单目标DPS[pipelined]", f"{dps_pl:,.1f}"],
            ["AoE总DPS(敌人数=%d)" % self.t.enemies_in_radius, f"{self.aoe_total_dps():,.1f}"],
            ["击杀用时(s)[当前口径]", f"{self.kill_time():.1f}"],
        ]
        with open(path, "w", encoding="utf-8", newline="") as f:
            csv.writer(f).writerows(rows)

    def export_sensitivity_csv(self, path):
        # 表头明确区分「扰动语义」与「DPS 实际变化%」，避免旧版 'Δ-20%' 对绝对量的误导
        rows = [["参数", "负向扰动(默认−20%)", "正向扰动(+20%)",
                 "DPS变化%(负)", "DPS变化%(正)", "最大|DPS变化%|"]]
        for attr, label_neg, label_pos, minus, plus, mag in self.sensitivity():
            rows.append([attr, label_neg, label_pos, f"{minus:+.1f}", f"{plus:+.1f}", f"{mag:.1f}"])
        with open(path, "w", encoding="utf-8", newline="") as f:
            csv.writer(f).writerows(rows)

    def export_csv(self, path):
        self.export_metrics_csv(path)
        sens_path = path.replace(".csv", "_sensitivity.csv") if path.endswith(".csv") else path + "_sensitivity.csv"
        self.export_sensitivity_csv(sens_path)
        return path, sens_path


def demo():
    """仅 `python comet_model.py` 时运行；pytest 不导入执行。
    演示使用「有据可查的参考 BD」：
      - more 乘区 / 穿透：真实辅助宝石数值（见 DATA_SOURCES / DATA_SOURCES.md）。
      - inc/flat/暴击：典型终局冰法量级（代表性值，非精确拷贝）。
      - TooltipRef 默认留空：请填入你的游戏内 Comet tooltip 数值做真实校验。
    """
    skill = CometSkill.from_gem_level(20)   # 真实基础：829~1243 冰冷 / 1.0s 施法 / 13% 暴击

    build = Build(
        # —— 装备/天赋「增加 X% 伤害」（典型终局冰法量级，代表性值）——
        flat_cold=180.0,                    # 法杖/戒指 附加冰冷伤害（T2 词缀量级）
        inc_spell=0.90,                     # 法术伤害提高（天赋 + 装备合计）
        inc_cold=1.10,                      # 冰冷伤害提高（天赋 + 装备合计）
        inc_elemental=0.60,                 # 元素伤害提高
        inc_area=0.30,                      # 范围伤害提高
        # —— more 乘区：真实辅助宝石数值（poewiki / poe2db，见 DATA_SOURCES）——
        more_multipliers=(
            MoreMod(1.25, 'elemental'),     # 元素集中 Elemental Focus：25% more 元素伤害
            MoreMod(1.30, 'area'),          # 范围集中 Concentrated Area：30% more 范围伤害
        ),
        cast_speed_pct=0.35,                # 施法速度（装备 + 天赋，代表性值）
        crit_chance_add=0.32,               # 额外暴击率（暴击天赋 + 装备，代表性值）
        crit_mult_add=0.60,                 # 额外暴击伤害（手套/天赋，代表性值）
        cold_exposure_pct=0.20,             # 元素暴露 Elemental Weakness：-20% 冰抗
        cold_penetration_pct=0.30,          # 冰冷穿透 Cold Penetration：穿透 30% 冰抗
        hits_per_cast=1.0, cast_time_mult=1.0,
    )
    target = Target(enemy_hp=500_000, enemies_in_radius=1)
    tip = TooltipRef()                      # 留空：填入游戏内 tooltip 即可自动校验

    m = CometModel(skill, build, target, tip)
    print("=" * 64)
    print("彗星落 (Comet) 伤害期望模型 v3.5 —— 演示 (pytest 请运行: pytest -q)")
    print("=" * 64)
    print(f"暴击率 / 暴击倍率        : {m.crit_hit_chance()*100:.1f}% / {m.crit_multiplier():.2f}x")
    print(f"单次命中(冰冷 非暴/暴击) : {m.noncrit_hit('cold','avg'):,.0f} / {m.crit_hit('cold','avg'):,.0f}")
    print(f"暴击期望伤害贡献         : {m.crit_dps_contribution():.1f}%")
    print(f"每施法期望伤害(解析)          : {m.avg_damage_per_cast():,.0f}")
    print("-" * 64)
    t_sc = m.total_cast_time('serial_complete')
    t_ss = m.total_cast_time('serial_start')
    t_pl = m.total_cast_time('pipelined')
    dmg = m.avg_damage_per_cast()
    print(f"施法时间口径[默认]      : {m.cast_time_mode}（serial_complete / serial_start / pipelined）")
    print(f"  serial_complete 完成计时: {t_sc:.3f}s -> DPS {dmg/t_sc:,.0f}  (anim+fall, 最保守)")
    print(f"  serial_start    开始计时: {t_ss:.3f}s -> DPS {dmg/t_ss:,.0f}  (max(anim,fall), v3.4)")
    print(f"  pipelined      真流水线: {t_pl:.3f}s -> DPS {dmg/t_pl:,.0f}  (anim, 默认·施速生效)")
    print(f"单目标 DPS[默认·pipelined]: {m.single_target_dps():,.0f}")
    print(f"AoE 总伤(敌人数=1)      : {m.aoe_total_dps():,.0f}")
    print(f"击杀 50万血 用时[默认]   : {m.kill_time():.1f} s")
    print("-" * 64)

    print("【A/B】解析 vs 蒙特卡洛 + Tooltip 校验:")
    ok, rep = m.verify()
    for name, a, name2, b, note, passed in rep:
        print(f"  {name} {a} | {name2} {b} | {note} -> {'PASS' if passed else 'FAIL'}")
    print(f"  => {'ALL PASS ✅' if ok else 'CHECK ❌'}")

    print("-" * 64)
    print("【敏感性分析】单目标 DPS 对参数扰动的响应（按最大|DPS变化%|排序）:")
    print(f"  {'参数':<24}{'负向扰动':<24}{'正向扰动':<24}{'DPS%Δ':>9}")
    for attr, label_neg, label_pos, minus, plus, mag in m.sensitivity():
        print(f"  {attr:<24}{label_neg:<24}{label_pos:<24}{minus:>+8.1f}%")
    print("  注：列宽有限，仅列负向扰动对应的 DPS 变化%；完整 ± 双侧见 comet_model_output_sensitivity.csv")
    print("  注：默认 pipelined(真流水线)=anim 下，施速直接影响 DPS，故 cast_speed_pct 敏感性不再为 0。")

    p1, p2 = m.export_csv("comet_model_output.csv")
    print("-" * 64)
    print(f"已导出: {p1} / {p2}")


if __name__ == "__main__":
    demo()
