"""medshift — 医技科室排班器。

用一套声明式 YAML 配置描述人员、班次、岗位与规则，
把「每天谁在哪个岗位、谁值班、谁休息」这件事变得可校验、可导出、可复现。

v0.1 能力：配置加载与自洽校验、排班数据校验、Excel 周表导出、统计汇总。
v0.2 计划：OR-Tools CP-SAT 自动求解。
"""

from .config_loader import load_config
from .errors import (
    AssignmentFormatError,
    ConfigError,
    MedShiftError,
    NotSupportedError,
)
from .models import (
    Assignment,
    Calendar,
    DeptConfig,
    Position,
    Rules,
    Shift,
    ShiftKind,
    Staff,
    StaffGroup,
    StaffStatus,
)
from .scheduler import Scheduler, StaffStat
from .validator import Severity, ValidationReport, Validator, Violation

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "load_config",
    "Scheduler",
    "StaffStat",
    "Validator",
    "ValidationReport",
    "Violation",
    "Severity",
    "DeptConfig",
    "Staff",
    "StaffGroup",
    "StaffStatus",
    "Shift",
    "ShiftKind",
    "Position",
    "Assignment",
    "Rules",
    "Calendar",
    "MedShiftError",
    "ConfigError",
    "AssignmentFormatError",
    "NotSupportedError",
]
