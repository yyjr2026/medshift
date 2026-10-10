"""配置加载测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from medshift import load_config
from medshift.errors import ConfigError
from medshift.models import ShiftKind, StaffGroup


def test_load_example_config(config):
    assert config.name
    assert len(config.staff) == 26
    assert len(config.assignable_staff()) == 24
    assert len(config.trainees()) == 1
    assert config.validate_references() == []


def test_yaml_off_is_not_boolean(config):
    """YAML 1.1 会把裸写的 OFF 解析成布尔值，加载器必须纠正。"""
    off = config.shift_by_code("OFF")
    assert off is not None
    assert off.kind is ShiftKind.OFF

    kind_off = [s for s in config.shifts if s.kind is ShiftKind.OFF]
    assert len(kind_off) == 1


def test_shift_follow_relation(config):
    duty = config.shift_by_code("DUTY_DIAG")
    assert duty is not None
    assert duty.kind is ShiftKind.NIGHT
    assert duty.follow_shift == "POST_DUTY"


def test_groups_are_complete(config):
    assert len(config.members_of(StaffGroup.DIAGNOSIS)) == 9
    assert len(config.members_of(StaffGroup.TECHNICIAN)) == 12
    assert len(config.members_of(StaffGroup.NURSING)) == 3


def test_missing_required_file(tmp_path: Path, example_dir: Path):
    target = tmp_path / "broken"
    target.mkdir()
    for name in ("dept.yaml", "staff.yaml", "shifts.yaml"):
        (target / name).write_text(
            (example_dir / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    with pytest.raises(ConfigError) as exc:
        load_config(target)
    assert "positions.yaml" in str(exc.value)


def test_unknown_reference_rejected(tmp_path: Path, example_dir: Path):
    target = tmp_path / "badref"
    target.mkdir()
    for name in ("dept.yaml", "staff.yaml", "shifts.yaml", "rules.yaml", "calendar.yaml"):
        (target / name).write_text(
            (example_dir / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    (target / "positions.yaml").write_text(
        "positions:\n  - id: X\n    name: 空岗\n    shift_code: NOT_EXIST\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError) as exc:
        load_config(target)
    assert "NOT_EXIST" in str(exc.value)


def test_invalid_field_reports_filename(tmp_path: Path, example_dir: Path):
    target = tmp_path / "badfield"
    target.mkdir()
    for name in ("dept.yaml", "shifts.yaml", "positions.yaml", "rules.yaml", "calendar.yaml"):
        (target / name).write_text(
            (example_dir / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    (target / "staff.yaml").write_text(
        "staff:\n  - id: A\n    name: 甲\n    typo_field: 1\n", encoding="utf-8"
    )
    with pytest.raises(ConfigError) as exc:
        load_config(target)
    assert "staff.yaml" in str(exc.value)


def test_missing_directory():
    with pytest.raises(ConfigError):
        load_config(Path("definitely/not/here"))
