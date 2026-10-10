"""medshift 异常层次。

所有自定义异常都继承 MedShiftError，方便调用方一次捕获。
"""

from __future__ import annotations


class MedShiftError(Exception):
    """所有 medshift 异常的基类。"""


class ConfigError(MedShiftError):
    """配置文件缺失、格式错误或引用不完整。"""

    def __init__(self, problems: list[str] | str) -> None:
        if isinstance(problems, str):
            problems = [problems]
        self.problems = list(problems)
        super().__init__("；".join(self.problems))


class AssignmentFormatError(MedShiftError):
    """排班数据文件格式不正确。"""


class NotSupportedError(MedShiftError):
    """该能力尚未在当前版本实现。"""
