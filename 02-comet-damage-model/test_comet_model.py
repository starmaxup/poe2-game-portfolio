# -*- coding: utf-8 -*-
"""
comet_model.py 的标准 pytest 测试工程
=====================================
运行:
    pip install pytest
    pytest -q

覆盖:
    - 原 run_tests() 全部测试点 T1..T6（T3 参数化 3 例）
    - A/B 验证: A/B1 蒙特卡洛 vs 解析；A/B2 Tooltip 自洽
每个测试通过 pytest.fixture 提供基准模型，并用 copy.deepcopy 隔离可变对象，
测试之间互不污染。
"""

import copy

import pytest

from comet_model import (
    CometModel,
    CometSkill,
    Build,
    Target,
    TooltipRef,
    MoreMod,
    DEFAULT_SEED,
)


@pytest.fixture
def base_model():
    """提供一份全新的基准 CometModel，每个测试独立获取（函数级 fixture）。"""
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
    return CometModel(skill, build, target, tip)


def _noncrit_avg(m: CometModel) -> float:
    return (m._per_hit('cold', False, 'avg') + m._per_hit('fire', False, 'avg')) * m.b.hits_per_cast


def _crit_avg(m: CometModel) -> float:
    return (m._per_hit('cold', True, 'avg') + m._per_hit('fire', True, 'avg')) * m.b.hits_per_cast


# ---------------- T1: 暴击率 0% -> 期望 = 非暴击均值 ----------------
def test_T1_crit_zero_equals_noncrit(base_model):
    m = copy.deepcopy(base_model)
    m.b.crit_chance_add = -m.s.base_crit_chance
    expected = _noncrit_avg(m)
    actual = m.avg_damage_per_cast()
    assert actual == pytest.approx(expected), \
        f"T1 暴击0% 应等于非暴击均值: actual={actual}, expected={expected}"


# ---------------- T2: 暴击率 100% -> 期望 = 暴击均值 ----------------
def test_T2_crit_full_equals_crit(base_model):
    m = copy.deepcopy(base_model)
    m.b.crit_chance_add = 1.0 - m.s.base_crit_chance
    expected = _crit_avg(m)
    actual = m.avg_damage_per_cast()
    assert actual == pytest.approx(expected), \
        f"T2 暴击100% 应等于暴击均值: actual={actual}, expected={expected}"


# ---------------- T3: 抗性 +0/+50/-50% -> 倍率 1.0/0.5/1.5 ----------------
@pytest.mark.parametrize("res,exp_mult", [
    (0.0, 1.0),
    (0.5, 0.5),
    (-0.5, 1.5),
])
def test_T3_resist_mult(base_model, res, exp_mult):
    m = copy.deepcopy(base_model)
    m.b.enemy_cold_res = res
    m.b.cold_exposure_pct = 0.0
    m.b.cold_penetration_pct = 0.0
    actual = m._resist_mult('cold')
    assert actual == pytest.approx(exp_mult), \
        f"T3 抗性{res:+.0%} 倍率应为 {exp_mult}, got {actual}"


# ---------------- T4: 施法速度变化 -> DPS 倍率符合施法时间公式 ----------------
def test_T4_cast_speed_dps_ratio(base_model):
    m = copy.deepcopy(base_model)
    cs_new = m.b.cast_speed_pct + 1.0
    b2 = copy.deepcopy(m.b)
    b2.cast_speed_pct = cs_new
    m2 = CometModel(m.s, b2, m.t, m.tip)
    actual_ratio = m2.single_target_dps() / m.single_target_dps()
    expected_ratio = m._cast_speed_dps_ratio(m.b.cast_speed_pct, cs_new)
    assert actual_ratio == pytest.approx(expected_ratio), \
        f"T4 施速DPS倍率不符: actual={actual_ratio}, expected={expected_ratio}"


# ---------------- T5a: 回响命中×2 时间×1 -> DPS×2 ----------------
def test_T5a_echo_hits_x2_time_x1_dps_x2(base_model):
    m = copy.deepcopy(base_model)
    base = m.single_target_dps()
    b2 = copy.deepcopy(m.b)
    b2.hits_per_cast = 2.0
    b2.cast_time_mult = 1.0
    m2 = CometModel(m.s, b2, m.t, m.tip)
    ratio = m2.single_target_dps() / base
    assert ratio == pytest.approx(2.0), f"T5a 应 DPS×2, got {ratio}"


# ---------------- T5b: 回响命中×2 时间×2 -> DPS×1 ----------------
def test_T5b_echo_hits_x2_time_x2_dps_x1(base_model):
    m = copy.deepcopy(base_model)
    base = m.single_target_dps()
    b2 = copy.deepcopy(m.b)
    b2.hits_per_cast = 2.0
    b2.cast_time_mult = 2.0
    m2 = CometModel(m.s, b2, m.t, m.tip)
    ratio = m2.single_target_dps() / base
    assert ratio == pytest.approx(1.0), f"T5b 应 DPS×1, got {ratio}"


# ---------------- T6a: 火伤不吃 inc_cold（含防假 PASS 的 fire_base>0） ----------------
def test_T6a_fire_not_affected_by_inc_cold(base_model):
    skill_fire = copy.deepcopy(base_model.s)
    skill_fire.fire_infusion_dmg_min = 500.0
    skill_fire.fire_infusion_dmg_max = 500.0
    b = copy.deepcopy(base_model.b)
    b.use_fire_infusion = True
    m = CometModel(skill_fire, b, base_model.t, base_model.tip)
    fire_base = m._per_hit('fire', False, 'avg')
    # 防假 PASS：确认火伤基础确实 > 0，否则“无变化”是空真
    assert fire_base > 0, f"防假PASS: 火伤基础应 > 0, got {fire_base}"
    b2 = copy.deepcopy(b)
    b2.inc_cold += 1.0
    m2 = CometModel(skill_fire, b2, base_model.t, base_model.tip)
    fire_after = m2._per_hit('fire', False, 'avg')
    assert fire_after == pytest.approx(fire_base), \
        f"火伤不应受 inc_cold 影响: before={fire_base}, after={fire_after}"


# ---------------- T6b: 火伤吃 inc_fire，实际比值 ≈ inc_after/inc_before ----------------
def test_T6b_fire_affected_by_inc_fire(base_model):
    skill_fire = copy.deepcopy(base_model.s)
    skill_fire.fire_infusion_dmg_min = 500.0
    skill_fire.fire_infusion_dmg_max = 500.0
    b = copy.deepcopy(base_model.b)
    b.use_fire_infusion = True
    m = CometModel(skill_fire, b, base_model.t, base_model.tip)
    inc_before = m._inc_for('fire')
    fire_before = m._per_hit('fire', False, 'avg')
    b2 = copy.deepcopy(b)
    b2.inc_fire += 1.0
    m2 = CometModel(skill_fire, b2, base_model.t, base_model.tip)
    inc_after = m2._inc_for('fire')
    fire_after = m2._per_hit('fire', False, 'avg')
    expected_ratio = inc_after / inc_before
    actual_ratio = fire_after / fire_before if fire_before else 0.0
    assert actual_ratio == pytest.approx(expected_ratio, rel=1e-9), \
        f"火伤应随 inc_fire 线性变化: expected={expected_ratio}, actual={actual_ratio}"


# ---------------- T7: 暴击伤害 = 非暴击伤害 × 暴击倍率 ----------------
def test_T7_crit_damage_equals_noncrit_times_critmult(base_model):
    m = copy.deepcopy(base_model)
    for dtype in ('cold', 'fire'):
        nc = m.noncrit_hit(dtype, 'avg')
        cr = m.crit_hit(dtype, 'avg')
        cm = m.crit_multiplier()
        assert cr == pytest.approx(nc * cm, rel=1e-9), \
            f"T7 {dtype} 暴击伤害应=非暴击×暴击倍率: noncrit={nc}, crit={cr}, mult={cm}"


# ---------------- A/B1: 蒙特卡洛均值 ≈ 解析均值（固定 seed） ----------------
def test_AB1_monte_carlo_vs_analytic(base_model):
    m = copy.deepcopy(base_model)
    mc = m.monte_carlo_avg(n=100_000, seed=DEFAULT_SEED)
    an = m.avg_damage_per_cast()
    assert mc == pytest.approx(an, rel=0.01), \
        f"A/B1 蒙特卡洛与解析偏差过大: mc={mc}, an={an}"


# ---------------- A/B2: Tooltip 自洽（把模型 DPS 填回 TooltipRef，verify 应 PASS） ----------------
def test_AB2_tooltip_self_consistent(base_model):
    m = copy.deepcopy(base_model)
    tip = TooltipRef(
        per_hit_min=0.0,
        per_hit_max=0.0,  # 跳过每击范围检查，专注 DPS 口径分支
        dps=m.tooltip_dps_model(),
        tolerance=0.05,
        dps_includes_crit=True,
        dps_includes_aoe=False,
        dps_uses_cast_speed=True,
    )
    m.tip = tip
    ok, rep = m.verify()
    assert ok, f"A/B2 Tooltip 自洽应 PASS, rep={rep}"


# ---------------- T8: sensitivity 必须继承 cast_time_mode（修复 m2 漏传口径回归） ----------------
def test_T8_sensitivity_respects_mode(base_model):
    # 默认 pipelined(真流水线=anim)：施速直接影响 DPS，cast_speed_pct 敏感性应明显 > 0
    m_pipe = copy.deepcopy(base_model)
    rows_pipe = {r[0]: r for r in m_pipe.sensitivity()}
    cs_pipe = rows_pipe['cast_speed_pct']
    assert cs_pipe[5] > 1.0, f"pipelined 下施速应影响 DPS，敏感性却={cs_pipe[5]}"

    # serial_complete(anim+fall)：施速也影响 DPS，敏感性应 > 0
    m_ser = CometModel(base_model.s, base_model.b, base_model.t, base_model.tip,
                       cast_time_mode='serial_complete')
    rows_ser = {r[0]: r for r in m_ser.sensitivity()}
    cs_ser = rows_ser['cast_speed_pct']
    assert cs_ser[5] > 1.0, f"serial_complete 下施速应影响 DPS，敏感性却={cs_ser[5]}"

    # 关键回归：若 sensitivity 内部 m2 漏传 mode，则 serial_complete 基准会被误算成 pipelined，
    # 导致 serial 下的 cast_speed 敏感性被错误压成 0 或与 pipelined 一致。此处断言二者确实不同。
    assert cs_ser[3] != pytest.approx(cs_pipe[3], rel=0.1), \
        f"serial_complete 与 pipelined 的 cast_speed 敏感性应不同（口径已正确继承）: " \
        f"ser={cs_ser[3]}, pipe={cs_pipe[3]}"


# ---------------- T9: 三口径时间/DPS 排序 与 pipelined=anim 施速敏感性 ----------------
def test_T9_three_cast_modes(base_model):
    m = copy.deepcopy(base_model)
    t_sc = m.total_cast_time('serial_complete')
    t_ss = m.total_cast_time('serial_start')
    t_pl = m.total_cast_time('pipelined')
    # 时间关系：serial_complete >= serial_start >= pipelined
    assert t_sc >= t_ss >= t_pl, f"时间排序应为 sc>=ss>=pl: {t_sc},{t_ss},{t_pl}"
    dmg = m.avg_damage_per_cast()
    d_sc, d_ss, d_pl = dmg / t_sc, dmg / t_ss, dmg / t_pl
    # DPS 反序：serial_complete <= serial_start <= pipelined
    assert d_sc <= d_ss <= d_pl, f"DPS 排序应为 sc<=ss<=pl: {d_sc},{d_ss},{d_pl}"
    # pipelined=anim：施速变化应改变 DPS（区别于 serial_start 的“落点延迟瓶颈”行为）
    m2 = copy.deepcopy(base_model)
    m2.b.cast_speed_pct = base_model.b.cast_speed_pct + 1.0
    ratio = (m.avg_damage_per_cast() / m.total_cast_time('pipelined')) / \
            (m2.avg_damage_per_cast() / m2.total_cast_time('pipelined'))
    assert ratio != pytest.approx(1.0), f"pipelined 下施速应改变 DPS，ratio={ratio}"
