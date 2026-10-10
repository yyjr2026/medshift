"""Scheduler——面向使用者的门面（Facade）。

把「加载配置 → 读排班数据 → 校验 → 导出」这条链路收在一个类里，
CLI 与第三方代码都通过它调用 medshift。

v0.2 起 ``solve`` 接入 OR-Tools CP-SAT 自动排班；未安装 ortools 时
会抛出明确的 SolverUnavailableError，而不是静默返回空结果。
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
        days: int = 7,
        time_limit_s: int | None = None,
        seed: int = 0,
        fixed: list[Assignment] | None = None,
    ):
        """自动生成一周排班（CP-SAT）。

        返回 :class:`~medshift.solver.SolveResult`；若模型无解，
        ``result.ok`` 为 False，``result.warnings`` 里给出原因。
        """
        from .solver import Solver as _Solver

        return _Solver(self.config).solve_week(
            week_start,
            days=days,
            time_limit_s=time_limit_s,
            seed=seed,
            fixed=fixed,
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
