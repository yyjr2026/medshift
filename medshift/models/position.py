"""岗位（Position）数据模型。

岗位描述「每天需要几个人、在哪个班次、需要什么技能」。
校验器据此检查排班的岗位配额是否被填满。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .staff import StaffGroup


class Position(BaseModel):
    """一个岗位需求。"""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="岗位代码，如 CT1_SCAN / CT_DIAG")
    name: str = Field(description="岗位中文名，如「CT1扫描」")
    shift_code: str = Field(description="对应的班次代码，需存在于 shifts.yaml")
    daily_need: int = Field(default=1, ge=0, description="每日需要的人数")
    required_skills: list[str] = Field(
        default_factory=list,
        description="胜任该岗位所需的技能标签，需与 Staff.skills 对应",
    )
    group: StaffGroup | None = Field(
        default=None,
        description="建议由哪个组承担；留空表示不限组别",
    )
    priority: int = Field(
        default=0,
        description="岗位优先级，数值越大越先被满足（求解器用）",
    )
    note: str | None = None
