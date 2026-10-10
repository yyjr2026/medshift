"""配置加载：把目录下的 YAML 读成 DeptConfig。

约定的目录布局::

    my-dept/
    ├── dept.yaml         # 科室名（可选）
    ├── staff.yaml        # 人员
    ├── shifts.yaml       # 班次字典
    ├── positions.yaml    # 岗位需求
    ├── rules.yaml        # 规则
    └── calendar.yaml     # 节假日（可选）

每个文件既可以是裸列表／裸字典，也可以是带顶层键的字典
（``staff:`` / ``shifts:`` / ``positions:``），两种写法都接受。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .errors import ConfigError
from .models import Calendar, DeptConfig, Position, Rules, Shift, Staff

REQUIRED_FILES: dict[str, str] = {
    "staff.yaml": "staff",
    "shifts.yaml": "shifts",
    "positions.yaml": "positions",
    "rules.yaml": "rules",
}
OPTIONAL_FILES: tuple[str, ...] = ("dept.yaml", "calendar.yaml")


class _ConfigLoader(yaml.SafeLoader):
    """YAML 1.1 会把 off / on / yes / no 解析成布尔值。

    排班场景里 ``OFF``（休息）、``on`` 这类班次代码很常见，
    被解析成 ``False`` 会导致莫名其妙的报错。这里只认
    ``true`` / ``false`` 两个词，其余原样保留为字符串。
    """

    def construct_yaml_bool(self, node: yaml.Node) -> object:
        value = str(self.construct_scalar(node)).strip()
        if value.lower() in ("true", "false"):
            return value.lower() == "true"
        return value


_ConfigLoader.add_constructor(
    "tag:yaml.org,2002:bool", _ConfigLoader.construct_yaml_bool
)


def _read_yaml(path: Path) -> Any:
    """读取一个 YAML 文件；不存在返回 None。"""
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            return yaml.load(fh, Loader=_ConfigLoader)
    except yaml.YAMLError as exc:  # pragma: no cover - 依赖具体 YAML 文本
        raise ConfigError(f"{path.name} 不是合法 YAML：{exc}") from exc


def _unwrap(data: Any, key: str) -> Any:
    """允许「裸列表」与「带顶层键的字典」两种写法。"""
    if data is None:
        return []
    if isinstance(data, dict) and key in data:
        return data[key]
    return data


def _wrap_validation_error(filename: str, exc: ValidationError) -> ConfigError:
    problems: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err["loc"])
        problems.append(f"{filename} → {loc}: {err['msg']}")
    return ConfigError(problems)


def load_config(config_dir: str | Path) -> DeptConfig:
    """从目录加载配置。

    Args:
        config_dir: 配置目录。

    Raises:
        ConfigError: 目录不存在、必需文件缺失、格式错误或引用不完整。
    """
    config_dir = Path(config_dir)
    if not config_dir.is_dir():
        raise ConfigError(f"配置目录不存在：{config_dir}")

    missing = [name for name in REQUIRED_FILES if not (config_dir / name).exists()]
    if missing:
        raise ConfigError([f"缺少必需配置文件：{name}" for name in missing])

    dept_meta = _read_yaml(config_dir / "dept.yaml") or {}
    if not isinstance(dept_meta, dict):
        raise ConfigError("dept.yaml 应为字典，例如 name: 放射科")

    raw_staff = _unwrap(_read_yaml(config_dir / "staff.yaml"), "staff")
    raw_shifts = _unwrap(_read_yaml(config_dir / "shifts.yaml"), "shifts")
    raw_positions = _unwrap(_read_yaml(config_dir / "positions.yaml"), "positions")
    raw_rules = _read_yaml(config_dir / "rules.yaml") or {}
    raw_calendar = _read_yaml(config_dir / "calendar.yaml") or {}

    try:
        staff = [Staff(**item) for item in raw_staff]
    except ValidationError as exc:
        raise _wrap_validation_error("staff.yaml", exc) from exc

    try:
        shifts = [Shift(**item) for item in raw_shifts]
    except ValidationError as exc:
        raise _wrap_validation_error("shifts.yaml", exc) from exc

    try:
        positions = [Position(**item) for item in raw_positions]
    except ValidationError as exc:
        raise _wrap_validation_error("positions.yaml", exc) from exc

    try:
        rules = Rules(**(raw_rules if isinstance(raw_rules, dict) else {}))
    except ValidationError as exc:
        raise _wrap_validation_error("rules.yaml", exc) from exc

    try:
        calendar = Calendar(**(raw_calendar if isinstance(raw_calendar, dict) else {}))
    except ValidationError as exc:
        raise _wrap_validation_error("calendar.yaml", exc) from exc

    config = DeptConfig(
        name=dept_meta.get("name", config_dir.name),
        description=dept_meta.get("description"),
        staff=staff,
        shifts=shifts,
        positions=positions,
        rules=rules,
        calendar=calendar,
    )

    problems = config.validate_references()
    if problems:
        raise ConfigError(problems)

    return config
