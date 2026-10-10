"""排班校验器——v0.1 的核心。

给定一份排班结果（若干 Assignment），逐条检查硬约束是否被违反，
输出结构化的 Violation 列表。校验项包括：

======================  ==========================================
代码                     含义
======================  ==========================================
UNKNOWN_STAFF            排给了配置里不存在的人
UNKNOWN_SHIFT            使用了未定义的班次代码
UNKNOWN_POSITION         引用了未定义的岗位
INACTIVE_STAFF           给非在岗人员（规培／产假／派驻）排了班
DUPLICATE_ASSIGNMENT     同一人同一天被排了多个班次
SKILL_MISMATCH           人员技能不满足岗位要求
GROUP_MISMATCH           人员在非本组岗位（提醒级）
NIGHT_NOT_ELIGIBLE       不参与夜班的人被排了夜班（提醒级）
POSITION_UNDERSTAFFED    某岗位某天人数不足
OFF_QUOTA_EXCEEDED       某组某天休息人数超出上限
NIGHT_NOT_FOLLOWED       值班次日没有排联动班次（值出）
======================  ==========================================
"""

from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict
from enum import Enum
from typing import Iterable

from pydantic import BaseModel, Field

from .models import Assignment, DeptConfig, ShiftKind

WORKING_KINDS = {ShiftKind.DAY, ShiftKind.NIGHT, ShiftKind.EVENING}


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


class Violation(BaseModel):
    """一条违规记录。"""

    code: str
    message: str
    severity: Severity = Severity.ERROR
    date: dt.date | None = None
    staff_id: str | None = None
    position_id: str | None = None

    def __str__(self) -> str:  # pragma: no cover - 仅用于展示
        parts = [self.severity.value.upper(), self.code]
        if self.date:
            parts.append(self.date.isoformat())
        if self.staff_id:
            parts.append(self.staff_id)
        return f"[{'/'.join(parts)}] {self.message}"


class ValidationReport(BaseModel):
    """校验报告。"""

    violations: list[Violation] = Field(default_factory=list)

    @property
    def errors(self) -> list[Violation]:
        return [v for v in self.violations if v.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Violation]:
        return [v for v in self.violations if v.severity is Severity.WARNING]

    @property
    def ok(self) -> bool:
        """无 error 即为通过。"""
        return not self.errors

    def by_code(self) -> dict[str, int]:
        return dict(Counter(v.code for v in self.violations))

    def summary(self) -> str:
        if not self.violations:
            return "校验通过：未发现任何问题。"
        counts = "，".join(f"{code}×{n}" for code, n in sorted(self.by_code().items()))
        verdict = "通过" if self.ok else "未通过"
        return (
            f"校验{verdict}：{len(self.errors)} 个错误、"
            f"{len(self.warnings)} 个提醒（{counts}）"
        )


class Validator:
    """把一份排班结果对着配置逐项核对。"""

    def __init__(self, config: DeptConfig) -> None:
        self.config = config

    def check(self, assignments: Iterable[Assignment]) -> ValidationReport:
        """执行全部校验。"""
        items = list(assignments)
        report = ValidationReport()

        self._check_references(items, report)
        self._check_duplicates(items, report)
        self._check_skills(items, report)
        self._check_daily_quota(items, report)
        self._check_off_quota(items, report)
        self._check_night_follow(items, report)

        return report

    # ------------------------------------------------------------------
    # 引用与状态
    # ------------------------------------------------------------------

    def _check_references(
        self, items: list[Assignment], report: ValidationReport
    ) -> None:
        for item in items:
            person = self.config.staff_by_id(item.staff_id)
            if person is None:
                report.violations.append(
                    Violation(
                        code="UNKNOWN_STAFF",
                        message=f"排班数据引用了不存在的人员：{item.staff_id}",
                        date=item.date,
                        staff_id=item.staff_id,
                    )
                )
                continue

            shift = self.config.shift_by_code(item.shift_code)
            if shift is None:
                report.violations.append(
                    Violation(
                        code="UNKNOWN_SHIFT",
                        message=f"使用了未定义的班次：{item.shift_code}",
                        date=item.date,
                        staff_id=item.staff_id,
                    )
                )
                continue

            if item.position_id and self.config.position_by_id(item.position_id) is None:
                report.violations.append(
                    Violation(
                        code="UNKNOWN_POSITION",
                        message=f"引用了未定义的岗位：{item.position_id}",
                        date=item.date,
                        staff_id=item.staff_id,
                        position_id=item.position_id,
                    )
                )

            if not person.is_rosterable and shift.kind in WORKING_KINDS:
                report.violations.append(
                    Violation(
                        code="INACTIVE_STAFF",
                        message=(
                            f"{person.name} 当前状态为 {person.status.value}，"
                            f"不应排班（{item.date} / {shift.name}）"
                        ),
                        date=item.date,
                        staff_id=item.staff_id,
                    )
                )

            if shift.kind is ShiftKind.NIGHT and not person.night_eligible:
                report.violations.append(
                    Violation(
                        code="NIGHT_NOT_ELIGIBLE",
                        message=(
                            f"{person.name} 未登记参与夜班，却被排了"
                            f"{shift.name}（{item.date}）"
                        ),
                        severity=Severity.WARNING,
                        date=item.date,
                        staff_id=item.staff_id,
                    )
                )

    def _check_duplicates(
        self, items: list[Assignment], report: ValidationReport
    ) -> None:
        seen: dict[tuple[str, dt.date], list[str]] = defaultdict(list)
        for item in items:
            seen[item.key()].append(item.shift_code)

        for (staff_id, day), codes in seen.items():
            if len(codes) > 1:
                person = self.config.staff_by_id(staff_id)
                who = person.name if person else staff_id
                report.violations.append(
                    Violation(
                        code="DUPLICATE_ASSIGNMENT",
                        message=f"{who} 在 {day} 被排了 {len(codes)} 个班次：{'、'.join(codes)}",
                        date=day,
                        staff_id=staff_id,
                    )
                )

    def _check_skills(self, items: list[Assignment], report: ValidationReport) -> None:
        for item in items:
            if not item.position_id:
                continue
            person = self.config.staff_by_id(item.staff_id)
            position = self.config.position_by_id(item.position_id)
            if person is None or position is None:
                continue

            if not person.can_take(*position.required_skills):
                missing = [s for s in position.required_skills if s not in person.skills]
                report.violations.append(
                    Violation(
                        code="SKILL_MISMATCH",
                        message=(
                            f"{person.name} 缺少岗位 {position.name} 所需技能："
                            f"{'、'.join(missing)}"
                        ),
                        date=item.date,
                        staff_id=item.staff_id,
                        position_id=item.position_id,
                    )
                )

            if position.group is not None and person.group is not position.group:
                report.violations.append(
                    Violation(
                        code="GROUP_MISMATCH",
                        message=(
                            f"{person.name}（{person.group.value}）被排在"
                            f"{position.group.value} 组的岗位 {position.name}"
                        ),
                        severity=Severity.WARNING,
                        date=item.date,
                        staff_id=item.staff_id,
                        position_id=item.position_id,
                    )
                )

    # ------------------------------------------------------------------
    # 配额
    # ------------------------------------------------------------------

    def _check_daily_quota(
        self, items: list[Assignment], report: ValidationReport
    ) -> None:
        if not items:
            return

        days = sorted({item.date for item in items})
        start, end = days[0], days[-1]
        filled: Counter[tuple[dt.date, str]] = Counter(
            (item.date, item.position_id) for item in items if item.position_id
        )

        current = start
        while current <= end:
            for position in self.config.positions:
                if position.daily_need <= 0:
                    continue
                have = filled.get((current, position.id), 0)
                if have < position.daily_need:
                    report.violations.append(
                        Violation(
                            code="POSITION_UNDERSTAFFED",
                            message=(
                                f"{current} 岗位「{position.name}」在岗 {have} 人，"
                                f"低于需求 {position.daily_need} 人"
                            ),
                            date=current,
                            position_id=position.id,
                        )
                    )
            current += dt.timedelta(days=1)

    def _check_off_quota(
        self, items: list[Assignment], report: ValidationReport
    ) -> None:
        quotas = self.config.rules.max_off_per_day
        if not quotas:
            return

        off_by_day_group: Counter[tuple[dt.date, str]] = Counter()
        for item in items:
            person = self.config.staff_by_id(item.staff_id)
            shift = self.config.shift_by_code(item.shift_code)
            if person is None or shift is None or not shift.is_off:
                continue
            off_by_day_group[(item.date, person.group.value)] += 1

        for (day, group), count in sorted(
            off_by_day_group.items(), key=lambda kv: (kv[0][0], kv[0][1])
        ):
            quota = quotas.get(group)
            if quota is not None and count > quota:
                report.violations.append(
                    Violation(
                        code="OFF_QUOTA_EXCEEDED",
                        message=(
                            f"{day} {group} 组休息 {count} 人，"
                            f"超出每日上限 {quota} 人"
                        ),
                        date=day,
                    )
                )

    # ------------------------------------------------------------------
    # 值班联动
    # ------------------------------------------------------------------

    def _check_night_follow(
        self, items: list[Assignment], report: ValidationReport
    ) -> None:
        if not items:
            return

        by_staff_day: dict[tuple[str, dt.date], str] = {
            item.key(): item.shift_code for item in items
        }

        # 单周数据的周日值班，其下夜班自然落在下一周的文件里，不作判定
        last_day = max(item.date for item in items)

        next_day_codes: set[str] = {
            s.code for s in self.config.shifts if s.kind is ShiftKind.POST_NIGHT
        }

        for item in items:
            shift = self.config.shift_by_code(item.shift_code)
            if shift is None or shift.kind is not ShiftKind.NIGHT:
                continue

            follow = shift.follow_shift
            if not follow and not next_day_codes:
                continue

            tomorrow = item.date + dt.timedelta(days=1)
            if tomorrow > last_day:
                continue

            actual = by_staff_day.get((item.staff_id, tomorrow))
            if actual is None:
                report.violations.append(
                    Violation(
                        code="NIGHT_NOT_FOLLOWED",
                        message=(
                            f"{item.date} 值班后，{tomorrow} 未排下夜班"
                            f"（应为 {follow or '值出'}）"
                        ),
                        date=tomorrow,
                        staff_id=item.staff_id,
                    )
                )
            elif follow and actual != follow:
                report.violations.append(
                    Violation(
                        code="NIGHT_NOT_FOLLOWED",
                        message=(
                            f"{item.date} 值班后，{tomorrow} 排的是 {actual}，"
                            f"应为 {follow}"
                        ),
                        date=tomorrow,
                        staff_id=item.staff_id,
                    )
                )
            elif not follow and actual not in next_day_codes:
                report.violations.append(
                    Violation(
                        code="NIGHT_NOT_FOLLOWED",
                        message=(
                            f"{item.date} 值班后，{tomorrow} 排的是 {actual}，"
                            f"应为值出"
                        ),
                        date=tomorrow,
                        staff_id=item.staff_id,
                    )
                )
