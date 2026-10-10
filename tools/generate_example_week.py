"""生成示例排班周数据（确定性可复现）。

这不是求解器，只是用来产出「合法示例数据」的辅助脚本：
按「累计排班次数最少者优先」的贪心策略填满每日岗位，
保证值班次日有值出、每日休息人数不超上限。
v0.2 的 CP-SAT 求解器上线后会取代它。

用法::

    python tools/generate_example_week.py [输出目录]

默认输出到 examples/radiology/assignments/2026-W42.csv。
"""

from __future__ import annotations

import datetime as dt
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from medshift import Scheduler, load_config  # noqa: E402
from medshift.models import Assignment, ShiftKind, StaffGroup  # noqa: E402
from medshift.validator import Validator  # noqa: E402

WEEK_START = dt.date(2026, 10, 12)
GROUPS = (StaffGroup.DIAGNOSIS, StaffGroup.TECHNICIAN, StaffGroup.NURSING)


def _is_night(config, position) -> bool:
    shift = config.shift_by_code(position.shift_code)
    return bool(shift and shift.kind is ShiftKind.NIGHT)


def build_week(config, week_start: dt.date = WEEK_START) -> list[Assignment]:
    """贪心填表：值班优先 → 普通岗位 → 其余排休／值出。"""
    days = [week_start + dt.timedelta(days=i) for i in range(7)]

    slots_by_group: dict[StaffGroup, list[str]] = {}
    for group in GROUPS:
        codes: list[str] = []
        for position in config.positions_of_group(group):
            codes.extend([position.id] * position.daily_need)
        # 优先级高的（值班）先排
        codes.sort(key=lambda pid: -config.position_by_id(pid).priority)
        slots_by_group[group] = codes

    assignments: list[Assignment] = []
    used_today: dict[dt.date, set[str]] = defaultdict(set)
    post_night: dict[dt.date, set[str]] = defaultdict(set)
    total_count: Counter[str] = Counter()
    duty_count: Counter[str] = Counter()

    # 周一的下夜班来自「上周日」——单周数据里没有那条值班记录，
    # 但现实排班中这几位确实在值出。为每个夜班岗位补一位。
    for position in config.positions:
        if not _is_night(config, position) or position.group is None:
            continue
        pool = [s for s in config.members_of(position.group) if s.night_eligible]
        if pool:
            post_night[days[0]].add(pool[-1].id)

    for day in days:
        for group in GROUPS:
            available = [
                s for s in config.members_of(group) if s.id not in post_night[day]
            ]

            for position_id in slots_by_group[group]:
                position = config.position_by_id(position_id)
                candidates = [
                    s
                    for s in available
                    if s.id not in used_today[day]
                    and s.can_take(*position.required_skills)
                    and (not _is_night(config, position) or s.night_eligible)
                ]
                if not candidates:
                    continue

                is_night = _is_night(config, position)
                if is_night:
                    # 值班名额优先分给「值班次数最少」的人，保证夜班均摊
                    candidates.sort(
                        key=lambda s: (duty_count[s.id], total_count[s.id], s.id)
                    )
                else:
                    candidates.sort(key=lambda s: (total_count[s.id], s.id))
                chosen = candidates[0]

                assignments.append(
                    Assignment(
                        staff_id=chosen.id,
                        date=day,
                        shift_code=position.shift_code,
                        position_id=position.id,
                    )
                )
                used_today[day].add(chosen.id)
                total_count[chosen.id] += 1

                if _is_night(config, position):
                    duty_count[chosen.id] += 1
                    post_night[day + dt.timedelta(days=1)].add(chosen.id)

    for day in days:
        for person in config.assignable_staff():
            if person.id in used_today[day]:
                continue
            if person.id in post_night[day]:
                assignments.append(
                    Assignment(staff_id=person.id, date=day, shift_code="POST_DUTY")
                )
                total_count[person.id] += 1
            else:
                assignments.append(
                    Assignment(staff_id=person.id, date=day, shift_code="OFF")
                )

    assignments.sort(key=lambda a: (a.date, a.staff_id))
    return assignments


def main() -> int:
    out_dir = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else ROOT / "examples" / "radiology" / "assignments"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    config = load_config(ROOT / "examples" / "radiology")
    assignments = build_week(config)

    out_path = out_dir / f"{WEEK_START.isocalendar()[0]}-W{WEEK_START.isocalendar()[1]:02d}.csv"
    Scheduler(config).save_assignments(assignments, out_path)

    report = Validator(config).check(assignments)
    print(f"已生成 {out_path}（{len(assignments)} 条记录）")
    print(report.summary())
    for violation in report.violations:
        print(f"  · {violation}")

    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
