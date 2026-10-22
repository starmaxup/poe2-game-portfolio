# -*- coding: utf-8 -*-
"""
彗星落 (Comet, PoE2) 伤害期望模型 —— 可验证版 v3.2
===================================================
变更（v3.1 -> v3.2）：
  - 移除手写 run_tests() 与 __main__ 演示打印，改由 pytest 工程覆盖（见 test_comet_model.py）。
  - 保留 demo() 函数：仅在 `python comet_model.py` 时运行，pytest 不导入执行。
  - CometModel 的全部 dataclass、公开方法与计算公式原样保留，数值结果不变。
  - 火之灌注附加伤害设在「技能副本 skill_fire」上（模型读 CometSkill.fire_infusion_dmg_*），
    不再放在 Build 上。
  - TooltipRef 的 dps_includes_crit / dps_uses_cast_speed / dps_includes_aoe 分支已在
    tooltip_dps_model() 内实现，由测试 A/B2 验证。
"""

import random
import copy
import csv
import json
from dataclasses import dataclass, field

RESIST_FLOOR = -2.0
DEFAULT_SEED = 12345
VALID_SCOPES = {'global', 'spell', 'cold', 'fire', 'lightning', 'elemental', 'area'}


@dataclass
class CometSkill:
    gem_level: int = 20
    base_cold_min: float = 787.0
    base_cold_max: float = 1181.0
    base_cast_time: float = 1.0
    fall_delay: float = 1.0
    base_crit_chance: float = 0.13
    base_crit_mult: float = 1.50
    radius_m: float = 2.8
    mana_cost: float = 173.0
    fire_infusion_dmg_min: float = 0.0
    fire_infusion_dmg_max: float = 0.0
    fall_delay_affected_by_cast_speed: bool = False


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
    def __init__(self, skill: CometSkill, build: Build, target: Target, tip: TooltipRef):
        self.s = skill
        self.b = build
        self.t = target
        self.tip = tip
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

    def total_cast_time(self) -> float:
        if self.s.fall_delay_affected_by_cast_speed:
            raw = (self.s.base_cast_time + self.s.fall_delay) / (1.0 + self.b.cast_speed_pct)
        else:
            raw = self.s.base_cast_time / (1.0 + self.b.cast_speed_pct) + self.s.fall_delay
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

    def _cast_speed_dps_ratio(self, cs_old: float, cs_new: float) -> float:
        def t(cs):
            if self.s.fall_delay_affected_by_cast_speed:
                return (self.s.base_cast_time + self.s.fall_delay) / (1 + cs)
            return self.s.base_cast_time / (1 + cs) + self.s.fall_delay
        return t(cs_old) / t(cs_new)

    def sensitivity(self, deltas=None):
        if deltas is None:
            deltas = [-0.2, -0.1, 0.1, 0.2]
        base = self.single_target_dps()
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
                m2 = CometModel(self.s, b2, self.t, self.tip)
                new = m2.single_target_dps()
                impacts.append((d, (new - base) / base * 100 if base else 0.0))
            minus = impacts[0][1]
            plus = impacts[-1][1]
            rows.append((attr, minus, plus, max(abs(minus), abs(plus))))
        rows.sort(key=lambda r: -r[3])
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
        }

    @classmethod
    def from_dict(cls, d):
        skill = CometSkill(**d["skill"])
        mms = tuple(MoreMod(**m) if isinstance(m, dict) else m for m in d["build"]["more_multipliers"])
        bd = dict(d["build"]); bd["more_multipliers"] = mms
        build = Build(**bd)
        target = Target(**d["target"])
        tip = TooltipRef(**d["tooltip"])
        return cls(skill, build, target, tip)

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
        rows = [
            ["指标", "数值"],
            ["暴击率", f"{cc*100:.1f}%"],
            ["暴击倍率", f"{cm:.2f}x"],
            ["非暴击每击(冰冷 均值)", f"{nc:,.0f}"],
            ["暴击每击(冰冷 均值)", f"{cr:,.0f}"],
            ["暴击期望伤害贡献", f"{self.crit_dps_contribution():.1f}%"],
            ["每施法平均伤害", f"{self.avg_damage_per_cast():,.1f}"],
            ["总施法时间(s)", f"{self.total_cast_time():.3f}"],
            ["每秒施法数", f"{self.casts_per_sec():.3f}"],
            ["单目标DPS", f"{self.single_target_dps():,.1f}"],
            ["AoE总DPS(敌人数=%d)" % self.t.enemies_in_radius, f"{self.aoe_total_dps():,.1f}"],
            ["击杀用时(s)", f"{self.kill_time():.1f}"],
        ]
        with open(path, "w", encoding="utf-8", newline="") as f:
            csv.writer(f).writerows(rows)

    def export_sensitivity_csv(self, path):
        rows = [["参数", "Δ-20%", "Δ+20%", "最大|Δ|"]]
        for attr, minus, plus, mag in self.sensitivity():
            rows.append([attr, f"{minus:+.1f}", f"{plus:+.1f}", f"{mag:.1f}"])
        with open(path, "w", encoding="utf-8", newline="") as f:
            csv.writer(f).writerows(rows)

    def export_csv(self, path):
        self.export_metrics_csv(path)
        sens_path = path.replace(".csv", "_sensitivity.csv") if path.endswith(".csv") else path + "_sensitivity.csv"
        self.export_sensitivity_csv(sens_path)
        return path, sens_path


def demo():
    """仅 `python comet_model.py` 时运行；pytest 不导入执行。"""
    skill = CometSkill()
    build = Build(
        flat_cold=350.0,
        inc_spell=1.20, inc_cold=1.50, inc_elemental=0.80, inc_area=0.40,
        more_multipliers=(MoreMod(1.30, 'elemental'), MoreMod(1.25, 'area')),
        cast_speed_pct=0.30,
        crit_chance_add=0.25, crit_mult_add=0.50,
        cold_exposure_pct=0.20, cold_penetration_pct=0.25,
        hits_per_cast=1.0, cast_time_mult=1.0,
    )
    target = Target(enemy_hp=500_000, enemies_in_radius=1)
    tip = TooltipRef()

    m = CometModel(skill, build, target, tip)
    print("=" * 64)
    print("彗星落 (Comet) 伤害期望模型 v3.2 —— 演示 (pytest 请运行: pytest -q)")
    print("=" * 64)
    print(f"暴击率 / 暴击倍率        : {m.crit_hit_chance()*100:.1f}% / {m.crit_multiplier():.2f}x")
    print(f"单次命中(冰冷 非暴/暴击) : {m.noncrit_hit('cold','avg'):,.0f} / {m.crit_hit('cold','avg'):,.0f}")
    print(f"暴击期望伤害贡献         : {m.crit_dps_contribution():.1f}%")
    print(f"每施法平均伤害          : {m.avg_damage_per_cast():,.0f}")
    print(f"总施法时间              : {m.total_cast_time():.3f} s")
    print(f"单目标 DPS              : {m.single_target_dps():,.0f}")
    print(f"AoE 总伤(敌人数=1)      : {m.aoe_total_dps():,.0f}")
    print(f"击杀 50万血 用时         : {m.kill_time():.1f} s")
    print("-" * 64)

    print("【A/B】解析 vs 蒙特卡洛 + Tooltip 校验:")
    ok, rep = m.verify()
    for name, a, name2, b, note, passed in rep:
        print(f"  {name} {a} | {name2} {b} | {note} -> {'PASS' if passed else 'FAIL'}")
    print(f"  => {'ALL PASS ✅' if ok else 'CHECK ❌'}")

    print("-" * 64)
    print("【敏感性分析】单目标 DPS 对参数 ±20% 的响应（按最大|Δ|排序）:")
    print(f"  {'参数':<26}{'Δ-20%':>10}{'Δ+20%':>10}")
    for attr, minus, plus, mag in m.sensitivity():
        print(f"  {attr:<26}{minus:>+9.1f}%{plus:>+10.1f}%")

    p1, p2 = m.export_csv("comet_model_output.csv")
    print("-" * 64)
    print(f"已导出: {p1} / {p2}")


if __name__ == "__main__":
    demo()
