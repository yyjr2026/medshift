"""统计模型。"""

from __future__ import annotations

from pydantic import BaseModel


class StaffStat(BaseModel):
    """单人排班统计。

    口径说明：``work_days`` 只统计真正的出勤班次（日班／值班／中晚班），
    值出（下夜班）单列，休息单列，三者相加等于统计区间的天数。
    """

    staff_id: str
    name: str
    group: str
    work_days: int = 0
    off_days: int = 0
    night_count: int = 0
    post_night_count: int = 0
    weighted_score: float = 0.0

    @property
    def total_days(self) -> int:
        return self.work_days + self.off_days + self.post_night_count
