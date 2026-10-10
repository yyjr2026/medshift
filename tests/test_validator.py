"""校验器测试——每条硬约束都要有一条对应的失败用例。"""

from __future__ import annotations

import datetime as dt

import pytest

from medshift.models import Assignment
from medshift.validator import Severity, Validator


@pytest.fixture
def clean(assignments):
    return list(assignments)


def test_example_week_passes(config, clean):
    report = Validator(config).check(clean)
    assert report.ok, report.violations
    assert report.violations == []
    assert report.summary().startswith("校验通过")


def test_duplicate_assignment(config, clean):
    dup = Assignment(
        staff_id=clean[0].staff_id,
        date=clean[0].date,
        shift_code="OFF",
    )
    report = Validator(config).check(clean + [dup])
    assert "DUPLICATE_ASSIGNMENT" in report.by_code()


def test_position_understaffed(config, clean):
    target = next(a for a in clean if a.position_id == "CT_DIAG")
    remaining = [a for a in clean if a is not target]
    report = Validator(config).check(remaining)
    codes = report.by_code()
    assert "POSITION_UNDERSTAFFED" in codes
    assert not report.ok


def test_off_quota_exceeded(config, clean):
    strict = config.model_copy(deep=True)
    strict.rules.max_off_per_day["diagnosis"] = 0
    report = Validator(strict).check(clean)
    assert "OFF_QUOTA_EXCEEDED" in report.by_code()


def test_night_not_followed(config, clean):
    by_key = {(a.staff_id, a.date): a for a in clean}
    target = None
    for item in clean:
        if item.shift_code != "POST_DUTY":
            continue
        prev = by_key.get((item.staff_id, item.date - dt.timedelta(days=1)))
        if prev is not None and prev.shift_code.startswith("DUTY_"):
            target = item
            break

    assert target is not None, "示例数据里应存在「值班→次日值出」的配对"
    remaining = [a for a in clean if a is not target]
    report = Validator(config).check(remaining)
    assert "NIGHT_NOT_FOLLOWED" in report.by_code()


def test_last_day_duty_is_not_flagged(config, clean):
    """周日值班的下夜班落在下周文件里，不应误报。"""
    last_day = max(a.date for a in clean)
    sunday_duty = [a for a in clean if a.date == last_day and a.shift_code.startswith("DUTY_")]
    assert sunday_duty, "示例数据里周日应有值班"
    report = Validator(config).check(clean)
    assert not [v for v in report.violations if v.date == last_day + dt.timedelta(days=1)]


def test_unknown_staff_and_shift(config, clean):
    extra = [
        Assignment(staff_id="GHOST", date=clean[0].date, shift_code="OFF"),
        Assignment(staff_id=clean[0].staff_id, date=clean[0].date, shift_code="NO_SUCH"),
    ]
    report = Validator(config).check(clean + extra)
    codes = report.by_code()
    assert "UNKNOWN_STAFF" in codes
    assert "UNKNOWN_SHIFT" in codes


def test_inactive_staff_assigned(config, clean):
    extra = Assignment(
        staff_id="D10",  # 派驻介入导管室
        date=clean[0].date,
        shift_code="DAY",
    )
    report = Validator(config).check(clean + [extra])
    assert "INACTIVE_STAFF" in report.by_code()


def test_skill_mismatch(config, clean):
    extra = Assignment(
        staff_id="N01",  # 护士，无 CT 诊断技能
        date=clean[0].date,
        shift_code="CT_DIAG",
        position_id="CT_DIAG",
    )
    report = Validator(config).check(clean + [extra])
    codes = report.by_code()
    assert "SKILL_MISMATCH" in codes
    assert "GROUP_MISMATCH" in codes


def test_night_not_eligible_is_warning(config, clean):
    extra = Assignment(
        staff_id="D09",  # 不参与夜班
        date=clean[0].date,
        shift_code="DUTY_DIAG",
        position_id="DUTY_DIAG",
    )
    report = Validator(config).check(clean + [extra])
    warnings = [v for v in report.violations if v.severity is Severity.WARNING]
    assert any(v.staff_id == "D09" for v in warnings)


def test_report_summary_and_counts(config, clean):
    report = Validator(config).check(clean)
    assert report.by_code() == {}
    assert "未发现任何问题" in report.summary()
