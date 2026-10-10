"""命令行接口测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from medshift.cli import app

runner = CliRunner()


def test_validate_ok(example_dir: Path):
    result = runner.invoke(app, ["validate", "--config", str(example_dir)])
    assert result.exit_code == 0
    assert "配置合法" in result.output


def test_validate_missing_config(tmp_path: Path):
    result = runner.invoke(app, ["validate", "--config", str(tmp_path / "nope")])
    assert result.exit_code == 1


def test_check_ok(example_dir: Path, example_csv: Path):
    result = runner.invoke(
        app,
        ["check", "--config", str(example_dir), "--assignments", str(example_csv)],
    )
    assert result.exit_code == 0
    assert "校验通过" in result.output


def test_check_verbose_lists_violations(tmp_path: Path, example_dir: Path, example_csv: Path):
    lines = example_csv.read_text(encoding="utf-8").splitlines()
    header, rows = lines[0], lines[1:]

    # 删掉一条 CT 诊断岗记录，制造「岗位人数不足」
    kept: list[str] = []
    removed = False
    for row in rows:
        if not removed and ",CT_DIAG,CT_DIAG" in row:
            removed = True
            continue
        kept.append(row)
    assert removed, "示例数据里应存在 CT_DIAG 岗位记录"

    broken = tmp_path / "broken.csv"
    broken.write_text("\n".join([header, *kept]) + "\n", encoding="utf-8")

    result = runner.invoke(
        app,
        ["check", "-c", str(example_dir), "-a", str(broken), "--verbose"],
    )
    assert result.exit_code == 1
    assert "POSITION_UNDERSTAFFED" in result.output


def test_export_command(tmp_path: Path, example_dir: Path, example_csv: Path):
    out = tmp_path / "cli.xlsx"
    result = runner.invoke(
        app,
        [
            "export",
            "-c",
            str(example_dir),
            "-a",
            str(example_csv),
            "-o",
            str(out),
            "--week-start",
            "2026-10-12",
        ],
    )
    assert result.exit_code == 0
    assert out.exists()


def test_stats_command(example_dir: Path, example_csv: Path):
    result = runner.invoke(
        app, ["stats", "-c", str(example_dir), "-a", str(example_csv)]
    )
    assert result.exit_code == 0
    assert "加权分" in result.output


def test_init_creates_config(tmp_path: Path):
    target = tmp_path / "new-dept"
    result = runner.invoke(app, ["init", str(target)])
    assert result.exit_code == 0
    for name in ("staff.yaml", "shifts.yaml", "positions.yaml", "rules.yaml"):
        assert (target / name).exists()


def test_init_refuses_overwrite(tmp_path: Path):
    target = tmp_path / "existing"
    target.mkdir()
    (target / "keep.txt").write_text("x", encoding="utf-8")
    result = runner.invoke(app, ["init", str(target)])
    assert result.exit_code == 1
