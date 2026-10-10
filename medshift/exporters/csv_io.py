"""排班数据的 CSV 读写。

CSV 是 v0.1 的「手工排班」载体：排班员先在 Excel 里排，导出为 CSV，
medshift 负责校验与再导出。列定义::

    staff_id,date,shift_code,position_id,tags

``date`` 为 ISO 格式（2026-10-12），``tags`` 用 ``|`` 分隔。
"""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path
from typing import Iterable

from ..errors import AssignmentFormatError
from ..models import Assignment

CSV_HEADER = ["staff_id", "date", "shift_code", "position_id", "tags"]
TAG_SEPARATOR = "|"


def read_assignments(path: str | Path) -> list[Assignment]:
    """从 CSV 读取排班数据。

    Raises:
        AssignmentFormatError: 文件缺失、表头不符或行内容无法解析。
    """
    path = Path(path)
    if not path.exists():
        raise AssignmentFormatError(f"排班数据文件不存在：{path}")

    assignments: list[Assignment] = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise AssignmentFormatError(f"{path.name} 是空文件")

        missing = [col for col in ("staff_id", "date", "shift_code") if col not in reader.fieldnames]
        if missing:
            raise AssignmentFormatError(
                f"{path.name} 表头缺少必需列：{'、'.join(missing)}"
            )

        for lineno, row in enumerate(reader, start=2):
            staff_id = (row.get("staff_id") or "").strip()
            date_text = (row.get("date") or "").strip()
            shift_code = (row.get("shift_code") or "").strip()

            if not staff_id or not date_text or not shift_code:
                raise AssignmentFormatError(
                    f"{path.name} 第 {lineno} 行缺少 staff_id/date/shift_code"
                )

            try:
                day = dt.date.fromisoformat(date_text)
            except ValueError as exc:
                raise AssignmentFormatError(
                    f"{path.name} 第 {lineno} 行日期格式应为 YYYY-MM-DD，实际为 {date_text!r}"
                ) from exc

            position_id = (row.get("position_id") or "").strip() or None
            raw_tags = (row.get("tags") or "").strip()
            tags = [t for t in raw_tags.split(TAG_SEPARATOR) if t] if raw_tags else []

            assignments.append(
                Assignment(
                    staff_id=staff_id,
                    date=day,
                    shift_code=shift_code,
                    position_id=position_id,
                    tags=tags,
                )
            )

    return assignments


def write_assignments(assignments: Iterable[Assignment], path: str | Path) -> Path:
    """把排班数据写为 CSV。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    rows = sorted(assignments, key=lambda a: (a.date, a.staff_id))
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(CSV_HEADER)
        for item in rows:
            writer.writerow(
                [
                    item.staff_id,
                    item.date.isoformat(),
                    item.shift_code,
                    item.position_id or "",
                    TAG_SEPARATOR.join(item.tags),
                ]
            )
    return path
