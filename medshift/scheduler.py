"""Scheduler——面向使用者的门面（Facade）。

把「加载配置 → 读排班数据 → 校验 → 导出」这条链路收在一个类里，
CLI 与第三方代码都通过它调用 medshift。

v0.1 只提供**校验与导出**；自动求解（``solve``）在 v0.2 实现，
当前会明确抛出 NotSupportedError，而不是静默返回空结果。
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Iterable

from .config_loader import load_config
from .errors import NotSupportedError
from .exporters import export_week, read_assignments, write_assignments
from .models import Assignment, DeptConfig
from .models.stat import StaffStat
from .stats import compute_stats
from .validator import ValidationReport, Validator


class Scheduler:
    """排班器门面。"""

    def __init__(self, config: DeptConfig) -> None:
        self.config = config
        self.validator = Validator(config)

    # ------------------------------------------------------------------
    # 构造
    # ------------------------------------------------------------------

    @classmethod
    def from_config_dir(cls, config_dir: str | Path) -> "Scheduler":
        """从配置目录构造。"""
        return cls(load_config(config_dir))

    # ------------------------------------------------------------------
    # 数据进出
    # ------------------------------------------------------------------

    def load_assignments(self, path: str | Path) -> list[Assignment]:
        """读取 CSV 排班数据。"""
        return read_assignments(path)

    def save_assignments(self, assignments: Iterable[Assignment], path: str | Path) -> Path:
        """写出 CSV 排班数据。"""
        return write_assignments(assignments, path)

    # ------------------------------------------------------------------
    # 校验
    # ------------------------------------------------------------------

    def check(self, assignments: Iterable[Assignment]) -> ValidationReport:
        """校验排班数据。"""
        return self.validator.check(assignments)

    # ------------------------------------------------------------------
    # 自动求解（v0.2）
    # ------------------------------------------------------------------

    def solve(
        self,
        week_start: dt.date,
        *,
        time_limit_s: int = 30,
        seed: int = 0,
    ) -> list[Assignment]:
        """自动生成一周排班。

        v0.2 将接入 OR-Tools CP-SAT 求解器；当前版本尚未实现。
        """
        raise NotSupportedError(
            "自动求解将在 v0.2 提供。v0.1 请先用 Excel/CSV 手工排班，"
            "再用 `medshift check` 校验、`medshift export` 出表。"
        )

    # ------------------------------------------------------------------
    # 统计与导出
    # ------------------------------------------------------------------

    def stats(self, assignments: Iterable[Assignment]) -> list[StaffStat]:
        """按人汇总出勤、夜班与加权分。"""
        return compute_stats(self.config, assignments)

    def export_excel(
        self,
        assignments: Iterable[Assignment],
        out_path: str | Path,
        week_start: dt.date | None = None,
    ) -> Path:
        """导出周排班表。"""
        return export_week(self.config, list(assignments), out_path, week_start)
