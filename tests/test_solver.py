"""CP-SAT 自动排班求解器测试。

这些用例覆盖：

* 求解器能在一周内找出可行解（``OPTIMAL`` / ``FEASIBLE``）；
* 产出的排班满足全部**硬约束**（一人一天一班、岗位凑齐、技能匹配、
  夜班配值出、连续出勤上限）；
* 休息目标「尽量休两天、不够休一天」被正确表达（没人零休息）；
* 可选岗位（MR审／DR审）逻辑——人力富余才排，不富余时留空；
* 求解器不可用时的报错路径。

若环境未安装 ``ortools``，整个模块会被跳过。
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict

import pytest

from medshift import solver as solver_mod
from medshift.models import (
    Assignment,
    ShiftKind,
    Staff,
    StaffGroup,
    StaffStatus,
)
from medshift.solver import Solver, SolveResult, SolverUnavailableError, solve_week

pytestmark = pytest.mark.skipif(
    solver_mod.cp_model is None,
    reason="未安装 ortools，跳过求解器测试",
)

WEEK_START = dt.date(2026, 10, 12)


# ----------------------------------------------------------------------
# 夹具
# ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def week(config) -> SolveResult:
    """求解示例配置的一周排班，供多个用例共用。"""
    return Solver(config).solve_week(WEEK_START, time_limit_s=60)


@pytest.fixture(scope="module")
def schedule(week: SolveResult) -> dict:
    """把结果整理成便于断言的索引结构。"""
    by_person_day: dict[tuple[str, dt.date], list[Assignment]] = defaultdict(list)
    for a in week.assignments:
        by_person_day[(a.staff_id, a.date)].append(a)
    return {
        "by_person_day": by_person_day,
        "dates": sorted({a.date for a in week.assignments}),
    }


# ----------------------------------------------------------------------
# 基本可用性
# ----------------------------------------------------------------------


def test_solver_reports_available():
    assert solver_mod.cp_model is not None


def test_solve_week_returns_ok(week: SolveResult):
    assert week.ok, f"求解失败：{week.status} {week.warnings}"
    assert week.status in ("OPTIMAL", "FEASIBLE")
    assert not week.warnings


def test_solve_week_covers_every_person_every_day(week: SolveResult, config):
    dates = [WEEK_START + dt.timedelta(days=i) for i in range(7)]
    for person in config.staff:
        if not person.can_hold_position:
            continue
        days = {a.date for a in week.assignments if a.staff_id == person.id}
        assert days == set(dates), f"{person.id} 缺少排班：{set(dates) - days}"


def test_module_level_helper_matches_class(config):
    r1 = solve_week(config, WEEK_START, time_limit_s=30)
    assert r1.ok
    assert len(r1.assignments) == len(Solver(config).solve_week(
        WEEK_START, time_limit_s=30
    ).assignments)


# ----------------------------------------------------------------------
# 硬约束：一人一天一班
# ----------------------------------------------------------------------


def test_one_shift_per_person_per_day(schedule):
    for key, items in schedule["by_person_day"].items():
        codes = [a.shift_code for a in items]
        assert len(codes) == 1, f"{key} 一天排了多个班次：{codes}"


# ----------------------------------------------------------------------
# 硬约束：岗位配额
# ----------------------------------------------------------------------


def test_required_positions_are_staffed(week: SolveResult, config, schedule):
    for day in schedule["dates"]:
        for pos in config.positions:
            if not pos.is_required or pos.daily_need <= 0:
                continue
            got = sum(
                1
                for a in week.assignments
                if a.date == day and a.position_id == pos.id
            )
            assert got >= pos.daily_need, (
                f"{day} 岗位 {pos.id} 只有 {got} 人，需 {pos.daily_need} 人"
            )


def test_optional_positions_never_exceed_need(week: SolveResult, config, schedule):
    for day in schedule["dates"]:
        for pos in config.positions:
            if not pos.is_optional:
                continue
            got = sum(
                1
                for a in week.assignments
                if a.date == day and a.position_id == pos.id
            )
            assert got <= pos.daily_need


def test_nursing_daily_coverage(week: SolveResult, config, schedule):
    """护士三人：每天保证一个登记、一个正班。"""
    nursing_ids = {p.id for p in config.staff if p.group is StaffGroup.NURSING}
    for day in schedule["dates"]:
        shifts = {
            a.shift_code
            for a in week.assignments
            if a.date == day and a.staff_id in nursing_ids
        }
        assert "REGISTER" in shifts, f"{day} 缺少登记岗"
        assert "DAY" in shifts, f"{day} 缺少护理正班"


def test_technician_dr_and_ct2_coverage(week: SolveResult, schedule):
    """DR 投照每天 2 名技师；CT2 每天 2 名技师。"""
    for day in schedule["dates"]:
        dr = sum(
            1 for a in week.assignments
            if a.date == day and a.position_id == "DR_RADIOGRAPH"
        )
        ct2 = sum(
            1 for a in week.assignments
            if a.date == day and a.position_id == "CT2_SCAN"
        )
        assert dr == 2, f"{day} DR 投照 {dr} 人，应为 2"
        assert ct2 == 2, f"{day} CT2 扫描 {ct2} 人，应为 2"


# ----------------------------------------------------------------------
# 硬约束：技能匹配
# ----------------------------------------------------------------------


def test_position_holders_have_required_skills(week: SolveResult, config):
    for a in week.assignments:
        if a.position_id is None:
            continue
        pos = config.position_by_id(a.position_id)
        assert pos is not None
        person = config.staff_by_id(a.staff_id)
        assert person is not None
        assert person.can_take(*pos.required_skills), (
            f"{person.id} 不具备 {pos.id} 所需技能 {pos.required_skills}"
        )


def test_position_shift_codes_line_up(week: SolveResult, config):
    """占岗者的班次必须与该岗位声明的班次一致。"""
    for a in week.assignments:
        if a.position_id is None:
            continue
        pos = config.position_by_id(a.position_id)
        if pos is None:
            continue
        assert a.shift_code == pos.shift_code, (
            f"{a.staff_id} {a.date} 占岗 {pos.id} 但班次是 {a.shift_code}"
        )


# ----------------------------------------------------------------------
# 硬约束：夜班 → 值出
# ----------------------------------------------------------------------


def _is_kind(config, code: str, kind: ShiftKind) -> bool:
    shift = config.shift_by_code(code)
    return shift is not None and shift.kind is kind


def test_night_duty_gets_post_duty_next_day(week: SolveResult, config, schedule):
    night_by_person: dict[str, set[dt.date]] = defaultdict(set)
    for a in week.assignments:
        if _is_kind(config, a.shift_code, ShiftKind.NIGHT):
            night_by_person[a.staff_id].add(a.date)

    last_day = max(schedule["dates"])
    for sid, days in night_by_person.items():
        for d in days:
            nd = d + dt.timedelta(days=1)
            if nd > last_day:
                continue  # 周期末日的次日在下一周，本周期不判定
            has_post = any(
                a.staff_id == sid
                and a.date == nd
                and _is_kind(config, a.shift_code, ShiftKind.POST_NIGHT)
                for a in week.assignments
            )
            assert has_post, f"{sid} 在 {d} 值夜班，但 {nd} 没有值出"


def test_post_duty_always_follows_a_night(week: SolveResult, config):
    night_by_person: dict[str, set[dt.date]] = defaultdict(set)
    for a in week.assignments:
        if _is_kind(config, a.shift_code, ShiftKind.NIGHT):
            night_by_person[a.staff_id].add(a.date)

    for a in week.assignments:
        if not _is_kind(config, a.shift_code, ShiftKind.POST_NIGHT):
            continue
        assert (a.date - dt.timedelta(days=1)) in night_by_person[a.staff_id], (
            f"{a.staff_id} 在 {a.date} 出现无前置夜班的值出"
        )


def test_night_person_has_no_other_shift_next_day(week: SolveResult, config):
    night_by_person: dict[str, set[dt.date]] = defaultdict(set)
    for a in week.assignments:
        if _is_kind(config, a.shift_code, ShiftKind.NIGHT):
            night_by_person[a.staff_id].add(a.date)

    by_key = {
        (a.staff_id, a.date): a.shift_code for a in week.assignments
    }
    for sid, days in night_by_person.items():
        for d in days:
            code = by_key.get((sid, d + dt.timedelta(days=1)))
            if code is None:
                continue
            shift = config.shift_by_code(code)
            assert shift is not None and shift.kind is ShiftKind.POST_NIGHT, (
                f"{sid} 值班次日排了 {code}，应为值出"
            )


def test_night_only_goes_to_eligible_people(week: SolveResult, config):
    for a in week.assignments:
        if not _is_kind(config, a.shift_code, ShiftKind.NIGHT):
            continue
        person = config.staff_by_id(a.staff_id)
        assert person is not None and person.night_eligible, (
            f"{a.staff_id} 不具备夜班资格却被排了夜班"
        )


# ----------------------------------------------------------------------
# 硬约束：连续出勤
# ----------------------------------------------------------------------


def test_consecutive_work_days_within_limit(week: SolveResult, config):
    limit = config.rules.max_consecutive_work_days
    if not limit:
        return
    worked: dict[str, set[dt.date]] = defaultdict(set)
    for a in week.assignments:
        shift = config.shift_by_code(a.shift_code)
        if shift is not None and shift.kind is not ShiftKind.OFF:
            worked[a.staff_id].add(a.date)

    for sid, days in worked.items():
        ordered = sorted(days)
        run = 1
        for i in range(1, len(ordered)):
            if (ordered[i] - ordered[i - 1]).days == 1:
                run += 1
                assert run <= limit, f"{sid} 连续出勤 {run} 天，超过上限 {limit}"
            else:
                run = 1


# ----------------------------------------------------------------------
# 软目标：休息天数
# ----------------------------------------------------------------------


def test_everyone_gets_at_least_min_off(week: SolveResult, config):
    """「如果不够人排班，就休一天」——没人应该零休息。"""
    minimum = config.rules.min_off_per_week
    if minimum <= 0:
        return
    for person in config.staff:
        if not person.can_hold_position:
            continue
        off = week.off_by_staff.get(person.id, 0)
        assert off >= minimum, f"{person.id} 只休了 {off} 天，少于最低 {minimum} 天"


def test_off_days_reflect_assignment_sheet(week: SolveResult, config):
    """统计出的休息天数应与排班表里的 OFF 格数一致。"""
    off_codes = {s.code for s in config.shifts if s.kind is ShiftKind.OFF}
    counted: dict[str, int] = defaultdict(int)
    for a in week.assignments:
        if a.shift_code in off_codes:
            counted[a.staff_id] += 1
    for sid, n in week.off_by_staff.items():
        assert counted[sid] == n, f"{sid} 休息统计不一致：{counted[sid]} vs {n}"


def test_people_do_not_all_rest_same_day(week: SolveResult, config, schedule):
    """休息应被摊开：任何一天都不能让整组人都不上班。"""
    for day in schedule["dates"]:
        by_group: dict[StaffGroup, list[str]] = defaultdict(list)
        for a in week.assignments:
            if a.date != day:
                continue
            person = config.staff_by_id(a.staff_id)
            if person is not None:
                by_group[person.group].append(a.shift_code)
        off_codes = {s.code for s in config.shifts if s.kind is ShiftKind.OFF}
        for group, codes in by_group.items():
            assert any(c not in off_codes for c in codes), (
                f"{day} {group.value} 全组休息"
            )


# ----------------------------------------------------------------------
# 软目标：夜班均衡
# ----------------------------------------------------------------------


def test_night_load_is_reasonably_balanced(week: SolveResult, config):
    counts = [
        sum(
            1
            for a in week.assignments
            if a.staff_id == p.id and _is_kind(config, a.shift_code, ShiftKind.NIGHT)
        )
        for p in config.staff
        if p.can_hold_position and p.night_eligible
    ]
    if not counts:
        return
    # 允许一定波动，但极差不应失控（例如某人包揽一半值班）
    assert max(counts) - min(counts) <= 3, f"夜班分布失衡：{sorted(counts)}"


# ----------------------------------------------------------------------
# 可选岗位：人力富余才排
# ----------------------------------------------------------------------


def test_optional_positions_filled_when_surplus(config):
    """给诊断组加 2 人后，MR审／DR审应被排上。"""
    local = config.model_copy(deep=True)
    for i, sid in enumerate(("D20", "D21")):
        local.staff.append(
            Staff(
                id=sid,
                name=f"临时医师{i + 1}",
                group=StaffGroup.DIAGNOSIS,
                status=StaffStatus.ACTIVE,
                skills=["CT_DIAG", "DR_DIAG", "MR_DIAG", "REVIEW"],
                night_eligible=True,
            )
        )
    local.rebuild_index()
    result = Solver(local).solve_week(WEEK_START, time_limit_s=60)
    assert result.ok
    filled = result.stats.get("optional_filled", {})
    assert filled.get("MR审", 0) + filled.get("DR审", 0) >= 1, (
        f"有人力富余却没排审片岗：{filled}"
    )


def test_optional_positions_are_not_hard_required(config):
    """缺少审片人力时，求解仍应成功（可选岗位允许空缺）。"""
    result = Solver(config).solve_week(WEEK_START, time_limit_s=60)
    assert result.ok


def test_optional_position_marked_in_config(config):
    audit = [p for p in config.positions if p.id in ("MR_AUDIT", "DR_AUDIT")]
    assert len(audit) == 2
    for pos in audit:
        assert pos.is_optional and not pos.is_required


# ----------------------------------------------------------------------
# 固定格子
# ----------------------------------------------------------------------


def test_fixed_cells_are_respected(config):
    """把某人的某天固定为夜班，结果里必须保持。"""
    person = next(
        p for p in config.staff if p.can_hold_position and p.night_eligible
    )
    day = WEEK_START + dt.timedelta(days=2)
    result = Solver(config).solve_week(
        WEEK_START,
        time_limit_s=60,
        fixed=[Assignment(staff_id=person.id, date=day, shift_code="DUTY_DIAG")],
    )
    assert result.ok, f"固定格子后无解：{result.warnings}"
    got = [
        a for a in result.assignments
        if a.staff_id == person.id and a.date == day
    ]
    assert len(got) == 1 and got[0].shift_code == "DUTY_DIAG"


def test_fixed_off_day_is_respected(config):
    person = next(p for p in config.staff if p.can_hold_position)
    day = WEEK_START + dt.timedelta(days=3)
    result = Solver(config).solve_week(
        WEEK_START,
        time_limit_s=60,
        fixed=[Assignment(staff_id=person.id, date=day, shift_code="OFF")],
    )
    assert result.ok
    got = [
        a for a in result.assignments
        if a.staff_id == person.id and a.date == day
    ]
    assert len(got) == 1 and got[0].shift_code == "OFF"


# ----------------------------------------------------------------------
# 结果结构与统计
# ----------------------------------------------------------------------


def test_result_stats_shape(week: SolveResult):
    stats = week.stats
    assert stats["days"] == 7
    assert stats["people"] > 0
    assert "off_min" in stats and "off_max" in stats
    assert isinstance(stats["optional_filled"], dict)


def test_no_assignments_for_unavailable_staff(week: SolveResult, config):
    """派驻／进修实习人员不应出现在排班表里。"""
    for a in week.assignments:
        person = config.staff_by_id(a.staff_id)
        assert person is not None
        assert person.can_hold_position, f"{a.staff_id} 不可排班却出现在结果中"


def test_assignments_are_sorted_by_date_and_staff(week: SolveResult):
    keys = [(a.date, a.staff_id) for a in week.assignments]
    assert keys == sorted(keys)


# ----------------------------------------------------------------------
# 错误路径
# ----------------------------------------------------------------------


def test_solver_unavailable_error_message(monkeypatch, config):
    """未装 ortools 时应给出可操作的提示。"""
    monkeypatch.setattr(solver_mod, "cp_model", None)
    with pytest.raises(SolverUnavailableError) as exc:
        Solver(config).solve_week(WEEK_START)
    assert "ortools" in str(exc.value)


def test_infeasible_when_group_has_too_few_people(config):
    """把诊断组砍到只剩 3 人（不足 6 个岗位），应报无解且给出提示。"""
    local = config.model_copy(deep=True)
    local.staff = [
        s for s in local.staff
        if s.group is not StaffGroup.DIAGNOSIS or s.id in ("D01", "D02", "D03")
    ]
    local.rebuild_index()
    result = Solver(local).solve_week(WEEK_START, time_limit_s=30)
    assert not result.ok
    assert result.warnings


def test_days_parameter_is_honoured(config):
    result = Solver(config).solve_week(WEEK_START, days=3, time_limit_s=30)
    assert result.ok
    assert {a.date for a in result.assignments} == {
        WEEK_START + dt.timedelta(days=i) for i in range(3)
    }
