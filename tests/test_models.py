"""数据模型层测试。"""

from __future__ import annotations

import datetime as dt

import pytest

from medshift.models import (
    Assignment,
    Calendar,
    DeptConfig,
    Position,
    Shift,
    ShiftKind,
    Staff,
    StaffGroup,
    StaffStatus,
)


def test_staff_skill_check():
    doctor = Staff(id="D1", name="甲", group=StaffGroup.DIAGNOSIS, skills=["CT_DIAG"])
    assert doctor.can_take("CT_DIAG")
    assert not doctor.can_take("MR_DIAG")
    assert doctor.can_take()  # 无技能要求时恒为真


def test_trainee_cannot_hold_position():
    trainee = Staff(
        id="D99",
        name="进修甲",
        group=StaffGroup.DIAGNOSIS,
        supervisor_id="D01",
        night_eligible=False,
    )
    assert trainee.is_trainee
    assert trainee.is_rosterable
    assert not trainee.can_hold_position


def test_inactive_staff_not_rosterable():
    rotated = Staff(id="D10", name="医师10", status=StaffStatus.ROTATED)
    assert not rotated.is_rosterable
    assert not rotated.can_hold_position


def test_shift_kind_helpers():
    off = Shift(code="OFF", name="休", kind=ShiftKind.OFF)
    night = Shift(code="DUTY", name="值班", kind=ShiftKind.NIGHT, end="08:00+1")

    assert off.is_off and not off.is_working
    assert night.is_working and night.spans_next_day


def test_calendar_rest_day():
    cal = Calendar(
        holidays={dt.date(2026, 10, 1): "国庆节"},
        adjusted_workdays=[dt.date(2026, 10, 10)],
        anchors={dt.date(2026, 2, 16): "除夕"},
    )
    assert cal.is_holiday(dt.date(2026, 10, 1))
    assert cal.label(dt.date(2026, 2, 16)) == "除夕"
    assert cal.label(dt.date(2026, 10, 1)) == "国庆节"
    assert not cal.is_rest_day(dt.date(2026, 10, 10))  # 调休上班
    assert cal.is_rest_day(dt.date(2026, 10, 3))  # 周六


def test_config_indexes_and_queries(config: DeptConfig):
    assert config.staff_by_id("D01") is not None
    assert config.shift_by_code("OFF") is not None
    assert config.position_by_id("CT_DIAG").daily_need == 2
    assert config.staff_by_id("NOPE") is None

    diagnosis = config.members_of(StaffGroup.DIAGNOSIS)
    assert all(s.can_hold_position for s in diagnosis)
    assert config.trainees()


def test_validate_references_detects_duplicates():
    bad = DeptConfig(
        name="t",
        staff=[Staff(id="A", name="甲"), Staff(id="A", name="乙")],
        shifts=[Shift(code="S", name="班")],
        positions=[Position(id="P", name="岗", shift_code="MISSING")],
    )
    problems = bad.validate_references()
    assert any("重复" in p for p in problems)
    assert any("不存在的班次" in p for p in problems)


def test_assignment_key():
    item = Assignment(staff_id="D1", date=dt.date(2026, 10, 12), shift_code="OFF")
    assert item.key() == ("D1", dt.date(2026, 10, 12))


def test_dept_config_rejects_bad_field():
    with pytest.raises(Exception):
        Staff(id="X", name="甲", unknown_field=1)
