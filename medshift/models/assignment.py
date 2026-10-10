"""排班结果（Assignment）数据模型。

一条 Assignment = 某人 · 某天 · 某班次（可选带岗位）。
它是排班表的「一格」，也是 CSV 导入导出的基本行。
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field


class Assignment(BaseModel):
    """一次排班记录。"""

    model_config = ConfigDict(extra="forbid")

    staff_id: str
    date: dt.date
    shift_code: str
    position_id: str | None = Field(
        default=None,
        description="占用的岗位；一个班次可对应多个岗位，也可不占岗",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="叠加状态标记，如 backup（备班）、makeup（补班）",
    )

    def key(self) -> tuple[str, dt.date]:
        """人员＋日期，用于查重。"""
        return (self.staff_id, self.date)
