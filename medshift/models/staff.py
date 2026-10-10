"""人员（Staff）数据模型。

一个科室的排班对象既包括正式在岗人员，也包括进修生、实习生。
后者不单独占岗，通过 ``supervisor_id`` 挂在带教老师名下。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class StaffGroup(str, Enum):
    """人员组别。不同组别适用不同的岗位配额与休息上限。"""

    DIAGNOSIS = "diagnosis"      # 诊断组（医师）
    TECHNICIAN = "technician"    # 技术组（技师）
    NURSING = "nursing"          # 护理／登记组
    OTHER = "other"


class StaffStatus(str, Enum):
    """在岗状态。非 ACTIVE 的人员不参与排班。"""

    ACTIVE = "active"        # 正常在岗
    ROTATED = "rotated"      # 派驻其他科室（如介入导管室轮转）
    LEAVE = "leave"          # 长期假（产假、病假）
    TRAINING = "training"    # 外出规培／进修


class Staff(BaseModel):
    """一名人员。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    group: StaffGroup = StaffGroup.OTHER
    title: str | None = Field(default=None, description="职称，如 attending / senior")
    skills: list[str] = Field(
        default_factory=list,
        description="可胜任的岗位技能标签，需与 Position.required_skills 对应",
    )
    night_eligible: bool = Field(default=False, description="是否参与夜班轮值")
    rotation_offset: int = Field(
        default=0,
        description="整组平移轮岗的起始偏移量，用于错开同组人员的岗位",
    )
    status: StaffStatus = StaffStatus.ACTIVE
    supervisor_id: str | None = Field(
        default=None,
        description="带教老师 id（进修／实习人员填写），排班时随带教老师同格显示",
    )
    note: str | None = None

    @property
    def is_rosterable(self) -> bool:
        """是否参与排班。"""
        return self.status == StaffStatus.ACTIVE

    @property
    def is_trainee(self) -> bool:
        """是否进修／实习人员。"""
        return self.supervisor_id is not None

    @property
    def can_hold_position(self) -> bool:
        """能否占用岗位。

        进修／实习人员随带教老师行动，在表上出现但不单独占岗，
        因此不参与岗位分配与休息统计。
        """
        return self.is_rosterable and not self.is_trainee

    def can_take(self, *required_skills: str) -> bool:
        """是否满足岗位所需技能（无技能要求时恒为真）。"""
        if not required_skills:
            return True
        return all(skill in self.skills for skill in required_skills)
