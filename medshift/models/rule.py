"""排班规则（Rules）数据模型。

规则分两类：
* **硬约束**——违反即为错误（每日休息上限、岗位配额、值班配值出…）
* **软约束**——用于求解器打分（夜班均衡、节假日公平…）

v0.1 只做硬约束校验，软约束字段先预留。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Rules(BaseModel):
    """一个科室的排班规则集合。"""

    model_config = ConfigDict(extra="ignore")

    max_off_per_day: dict[str, int] = Field(
        default_factory=dict,
        description="每天最多几人休息，按组别配置，如 {diagnosis: 3, technician: 4}",
    )
    min_night_eligible: dict[str, int] = Field(
        default_factory=dict,
        description="各组至少需要多少人参与夜班（用于人力评估，非硬校验）",
    )
    max_night_per_month: int | None = Field(
        default=None, description="每人每月夜班次数上限（软约束）"
    )
    min_rest_gap_h: int = Field(
        default=12, description="两次值班之间至少间隔的小时数（软约束）"
    )
    max_consecutive_work_days: int | None = Field(
        default=None, description="连续出勤天数上限（软约束）"
    )
    night_balance_weight: float = Field(
        default=10.0, description="夜班均衡在目标函数中的权重"
    )
    holiday_weight: float = Field(
        default=2.0, description="节假日值班的加权倍数"
    )
    rotation: dict[str, Any] = Field(
        default_factory=dict,
        description="轮岗配置，如 {technician: weekly, attach_students: true}",
    )

    # ---- v0.2 求解器参数 ----

    target_off_per_week: int = Field(
        default=2, description="每人每周期望休息天数（首要目标）"
    )
    min_off_per_week: int = Field(
        default=1, description="人力紧张时允许的最低每周休息天数（次要目标）"
    )
    solve_time_limit_s: int = Field(default=30, description="求解时限（秒）")

    def off_quota(self, group: str) -> int | None:
        """取某组别的每日休息上限。"""
        return self.max_off_per_day.get(group)
