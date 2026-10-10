"""日历（Calendar）数据模型。

集中登记法定节假日、调休上班日，以及科室自己关注的特殊节点
（如除夕、中秋——这两个节点通常需要单独确定值班人员）。
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field


class Calendar(BaseModel):
    """一个年度的节假日与特殊日期。"""

    model_config = ConfigDict(extra="ignore")

    holidays: dict[dt.date, str] = Field(
        default_factory=dict,
        description="法定节假日，如 {2026-10-01: 国庆节}",
    )
    adjusted_workdays: list[dt.date] = Field(
        default_factory=list,
        description="调休上班日（周末但需正常上班）",
    )
    anchors: dict[dt.date, str] = Field(
        default_factory=dict,
        description="需单独安排值班的特殊节点，如 {2026-02-16: 除夕}",
    )

    def is_holiday(self, day: dt.date) -> bool:
        """是否法定节假日。"""
        return day in self.holidays

    def is_adjusted_workday(self, day: dt.date) -> bool:
        """是否调休上班日。"""
        return day in self.adjusted_workdays

    def label(self, day: dt.date) -> str | None:
        """取当天的显示标签（节点名优先于节日名）。"""
        return self.anchors.get(day) or self.holidays.get(day)

    def is_rest_day(self, day: dt.date) -> bool:
        """是否为休息日（周末且非调休上班日，或法定节假日）。"""
        if self.is_adjusted_workday(day):
            return False
        if self.is_holiday(day):
            return True
        return day.weekday() >= 5
