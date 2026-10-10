"""班次（Shift）数据模型。

班次是排班的原子单位：正班、值班、中晚班、值出、休……
每个班次自行声明时间区间，求解器与校验器据此判断冲突。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ShiftKind(str, Enum):
    """班次类别，决定校验规则。"""

    DAY = "day"                # 正班（日班）
    NIGHT = "night"            # 值班（含夜间）
    EVENING = "evening"        # 中晚班（午间＋晚间，不通宵）
    POST_NIGHT = "post_night"  # 值出（夜班次日的下夜班）
    BACKUP = "backup"          # 备班（床边待命等）
    OFF = "off"                # 休息
    OTHER = "other"


class Shift(BaseModel):
    """一个班次定义。"""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(description="班次代码，排班数据中引用它，如 DUTY / CT1_SCAN")
    name: str = Field(description="中文显示名，如「值班」「CT1扫描」")
    kind: ShiftKind = ShiftKind.OTHER
    start: str | None = Field(default=None, description="开始时间 HH:MM，无固定时间留空")
    end: str | None = Field(
        default=None,
        description="结束时间 HH:MM；跨夜用 HH:MM+1 表示次日",
    )
    is_night: bool = Field(default=False, description="是否计入夜班次数")
    weight: float = Field(default=1.0, description="绩效／工时权重分")
    color: str | None = Field(default=None, description="导出 Excel 时的填充色，如 FF378ADD")
    follow_shift: str | None = Field(
        default=None,
        description="联动班次代码：本班次必须出现在该班次的次日（典型：值出 → 值班）",
    )

    @property
    def is_working(self) -> bool:
        """是否为出勤班次（休息不算）。"""
        return self.kind is not ShiftKind.OFF

    @property
    def is_off(self) -> bool:
        return self.kind is ShiftKind.OFF

    @property
    def spans_next_day(self) -> bool:
        """该班次是否跨夜到次日。"""
        return bool(self.end and self.end.endswith("+1"))
