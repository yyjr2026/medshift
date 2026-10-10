"""科室配置（DeptConfig）——所有配置文件的聚合根。

一个科室的全部排班知识都收敛到这一个对象：
人员名单、班次字典、岗位需求、规则、日历。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from .calendar import Calendar
from .position import Position
from .rule import Rules
from .shift import Shift, ShiftKind
from .staff import Staff, StaffGroup


class DeptConfig(BaseModel):
    """一个科室的完整排班配置。"""

    model_config = ConfigDict(extra="ignore")

    name: str = "未命名科室"
    description: str | None = None
    staff: list[Staff] = Field(default_factory=list)
    shifts: list[Shift] = Field(default_factory=list)
    positions: list[Position] = Field(default_factory=list)
    rules: Rules = Field(default_factory=Rules)
    calendar: Calendar = Field(default_factory=Calendar)

    _staff_index: dict[str, Staff] = PrivateAttr(default_factory=dict)
    _shift_index: dict[str, Shift] = PrivateAttr(default_factory=dict)
    _position_index: dict[str, Position] = PrivateAttr(default_factory=dict)

    def model_post_init(self, __context: object) -> None:
        self.rebuild_index()

    def rebuild_index(self) -> None:
        """重建 id 索引。直接改动列表后需调用一次。"""
        self._staff_index = {s.id: s for s in self.staff}
        self._shift_index = {s.code: s for s in self.shifts}
        self._position_index = {p.id: p for p in self.positions}

    # ---------- 单条查询 ----------

    def staff_by_id(self, staff_id: str) -> Staff | None:
        return self._staff_index.get(staff_id)

    def shift_by_code(self, code: str) -> Shift | None:
        return self._shift_index.get(code)

    def position_by_id(self, position_id: str) -> Position | None:
        return self._position_index.get(position_id)

    # ---------- 集合查询 ----------

    def rosterable_staff(self) -> list[Staff]:
        """参与排班的人员。"""
        return [s for s in self.staff if s.is_rosterable]

    def assignable_staff(self) -> list[Staff]:
        """可被分配岗位的人员（排除进修／实习人员）。"""
        return [s for s in self.staff if s.can_hold_position]

    def members_of(self, group: StaffGroup) -> list[Staff]:
        """取某组可分配岗位的人员。"""
        return [s for s in self.assignable_staff() if s.group is group]

    def trainees(self) -> list[Staff]:
        """进修／实习人员。"""
        return [s for s in self.staff if s.is_trainee]

    def positions_of_group(self, group: StaffGroup) -> list[Position]:
        return [p for p in self.positions if p.group is group]

    def night_shifts(self) -> list[Shift]:
        """所有计入夜班的班次。"""
        return [s for s in self.shifts if s.is_night or s.kind is ShiftKind.NIGHT]

    def night_eligible_staff(self) -> list[Staff]:
        return [s for s in self.rosterable_staff() if s.night_eligible]

    def off_shift_codes(self) -> set[str]:
        """所有属于「休息」的班次代码。"""
        return {s.code for s in self.shifts if s.is_off}

    # ---------- 完整性校验 ----------

    def validate_references(self) -> list[str]:
        """检查交叉引用是否存在、编号是否唯一。

        返回人类可读的问题列表；空列表表示配置自洽。
        """
        problems: list[str] = []

        for label, items, key in (
            ("staff", self.staff, "id"),
            ("shifts", self.shifts, "code"),
            ("positions", self.positions, "id"),
        ):
            seen: set[str] = set()
            for item in items:
                value = getattr(item, key)
                if value in seen:
                    problems.append(f"{label}.{key} 重复：{value}")
                seen.add(value)

        shift_codes = {s.code for s in self.shifts}
        for position in self.positions:
            if position.shift_code not in shift_codes:
                problems.append(
                    f"岗位 {position.id} 引用了不存在的班次：{position.shift_code}"
                )

        for shift in self.shifts:
            if shift.follow_shift and shift.follow_shift not in shift_codes:
                problems.append(
                    f"班次 {shift.code} 引用了不存在的联动班次：{shift.follow_shift}"
                )

        staff_ids = {s.id for s in self.staff}
        for person in self.staff:
            if person.supervisor_id and person.supervisor_id not in staff_ids:
                problems.append(
                    f"人员 {person.id} 引用了不存在的带教老师：{person.supervisor_id}"
                )

        known_groups = {g.value for g in StaffGroup}
        for group in self.rules.max_off_per_day:
            if group not in known_groups:
                problems.append(f"rules.max_off_per_day 含未知组别：{group}")

        return problems
