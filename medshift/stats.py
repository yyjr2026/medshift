"""统计汇总——Excel 导出与 CLI 共用同一份实现，避免口径分叉。"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from .models import Assignment, DeptConfig, ShiftKind, StaffGroup
from .models.stat import StaffStat

GROUP_LABELS = {
    StaffGroup.DIAGNOSIS: "诊断组",
    StaffGroup.TECHNICIAN: "技术组",
    StaffGroup.NURSING: "护理组",
    StaffGroup.OTHER: "其他",
}

WORK_KINDS = {ShiftKind.DAY, ShiftKind.NIGHT, ShiftKind.EVENING, ShiftKind.BACKUP}


def compute_stats(
    config: DeptConfig, assignments: Iterable[Assignment]
) -> list[StaffStat]:
    """按人汇总出勤、夜班与加权分。

    只统计能占岗的人员；进修／实习人员随带教老师，不出现在统计里。
    """
    agg: dict[str, dict[str, float]] = defaultdict(
        lambda: {"work": 0, "off": 0, "night": 0, "post": 0, "score": 0.0}
    )

    for item in assignments:
        shift = config.shift_by_code(item.shift_code)
        if shift is None:
            continue
        bucket = agg[item.staff_id]
        bucket["score"] += shift.weight

        if shift.kind in WORK_KINDS:
            bucket["work"] += 1
        elif shift.kind is ShiftKind.POST_NIGHT:
            bucket["post"] += 1
        elif shift.kind is ShiftKind.OFF:
            bucket["off"] += 1

        if shift.kind is ShiftKind.NIGHT or shift.is_night:
            bucket["night"] += 1

    result: list[StaffStat] = []
    for person in config.assignable_staff():
        bucket = agg.get(person.id)
        if bucket is None:
            continue
        result.append(
            StaffStat(
                staff_id=person.id,
                name=person.name,
                group=GROUP_LABELS.get(person.group, person.group.value),
                work_days=int(bucket["work"]),
                off_days=int(bucket["off"]),
                night_count=int(bucket["night"]),
                post_night_count=int(bucket["post"]),
                weighted_score=round(bucket["score"], 2),
            )
        )
    return result
