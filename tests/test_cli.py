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


# ----------------------------------------------------------------------
# solve —— 自动排班
# ----------------------------------------------------------------------

_has_ortools = True
try:  # noqa: SIM105
    from ortools.sat.python import cp_model  # noqa: F401
except ImportError:  # pragma: no cover
    _has_ortools = False

needs_solver = pytest.mark.skipif(
    not _has_ortools, reason="未安装 ortools，跳过 solve 命令测试"
)


@needs_solver
def test_solve_dry_run(example_dir: Path):
    result = runner.invoke(
        app,
        [
            "solve",
            "--config", str(example_dir),
            "--week-start", "2026-11-02",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "求解成功" in result.output
    assert "未写入文件" in result.output


@needs_solver
def test_solve_writes_csv_and_passes_check(tmp_path: Path, example_dir: Path):
    import shutil

    # 复制一份配置到临时目录，避免污染示例
    work = tmp_path / "dept"
    shutil.copytree(example_dir, work)
    out = work / "assignments" / "2026-W45.csv"

    result = runner.invoke(
        app,
        [
            "solve",
            "--config", str(work),
            "--week-start", "2026-11-02",
            "--out", str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    assert out.exists()

    check = runner.invoke(
        app,
        ["check", "--config", str(work), "--assignments", str(out)],
    )
    assert check.exit_code == 0, check.output
    assert "未发现任何问题" in check.output


@needs_solver
def test_solve_default_out_path(tmp_path: Path, example_dir: Path):
    import shutil

    work = tmp_path / "dept2"
    shutil.copytree(example_dir, work)
    result = runner.invoke(
        app,
        ["solve", "--config", str(work), "--week-start", "2026-11-02"],
    )
    assert result.exit_code == 0, result.output
    # 应按 ISO 周命名写入 assignments/
    assert (work / "assignments" / "2026-W45.csv").exists()


def test_solve_rejects_bad_date(example_dir: Path):
    result = runner.invoke(
        app,
        ["solve", "--config", str(example_dir), "--week-start", "13-13-13"],
    )
    assert result.exit_code == 1
    assert "日期格式" in result.output


@needs_solver
def test_solve_reports_infeasible(tmp_path: Path, example_dir: Path):
    """把诊断组砍到 3 人，solve 应以退出码 1 报无解并给出原因。"""
    import shutil

    work = tmp_path / "dept3"
    shutil.copytree(example_dir, work)
    staff_yaml = work / "staff.yaml"
    lines = staff_yaml.read_text(encoding="utf-8").splitlines()
    kept, dropped = [], False
    diag_seen = 0
    for line in lines:
        if line.strip().startswith("- id: D") and "D9" not in line:
            diag_seen += 1
            if diag_seen > 3:
                dropped = True
                continue
        if dropped and line.startswith("    "):
            continue
        dropped = False
        kept.append(line)
    staff_yaml.write_text("\n".join(kept) + "\n", encoding="utf-8")

    result = runner.invoke(
        app,
        ["solve", "--config", str(work), "--week-start", "2026-11-02", "--dry-run"],
    )
    assert result.exit_code == 1
    assert "求解失败" in result.output or "无解" in result.output


@needs_solver
def test_solve_time_limit_option(example_dir: Path):
    result = runner.invoke(
        app,
        [
            "solve",
            "--config", str(example_dir),
            "--week-start", "2026-11-02",
            "--time-limit", "20",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "求解成功" in result.output


# ----------------------------------------------------------------------
# solve —— 自动排班
# ----------------------------------------------------------------------

_has_ortools = True
try:  # noqa: SIM105
    from ortools.sat.python import cp_model  # noqa: F401
except ImportError:  # pragma: no cover
    _has_ortools = False

needs_solver = pytest.mark.skipif(
    not _has_ortools, reason="未安装 ortools，跳过 solve 命令测试"
)


@needs_solver
def test_solve_dry_run(example_dir: Path):
    result = runner.invoke(
        app,
        [
            "solve",
            "--config", str(example_dir),
            "--week-start", "2026-11-02",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "求解成功" in result.output
    assert "未写入文件" in result.output


@needs_solver
def test_solve_writes_csv_and_passes_check(tmp_path: Path, example_dir: Path):
    import shutil

    # 复制一份配置到临时目录，避免污染示例
    work = tmp_path / "dept"
    shutil.copytree(example_dir, work)
    out = work / "assignments" / "2026-W45.csv"

    result = runner.invoke(
        app,
        [
            "solve",
            "--config", str(work),
            "--week-start", "2026-11-02",
            "--out", str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    assert out.exists()

    check = runner.invoke(
        app,
        ["check", "--config", str(work), "--assignments", str(out)],
    )
    assert check.exit_code == 0, check.output
    assert "未发现任何问题" in check.output


@needs_solver
def test_solve_default_out_path(tmp_path: Path, example_dir: Path):
    import shutil

    work = tmp_path / "dept2"
    shutil.copytree(example_dir, work)
    result = runner.invoke(
        app,
        ["solve", "--config", str(work), "--week-start", "2026-11-02"],
    )
    assert result.exit_code == 0, result.output
    # 应按 ISO 周命名写入 assignments/
    assert (work / "assignments" / "2026-W45.csv").exists()


def test_solve_rejects_bad_date(example_dir: Path):
    result = runner.invoke(
        app,
        ["solve", "--config", str(example_dir), "--week-start", "13-13-13"],
    )
    assert result.exit_code == 1
    assert "日期格式" in result.output


@needs_solver
def test_solve_reports_infeasible(tmp_path: Path, example_dir: Path):
    """把诊断组砍到 3 人，solve 应以退出码 1 报无解并给出原因。"""
    import shutil

    work = tmp_path / "dept3"
    shutil.copytree(example_dir, work)
    staff_yaml = work / "staff.yaml"
    lines = staff_yaml.read_text(encoding="utf-8").splitlines()
    kept, dropped = [], False
    diag_seen = 0
    for line in lines:
        if line.strip().startswith("- id: D") and "D9" not in line:
            diag_seen += 1
            if diag_seen > 3:
                dropped = True
                continue
        if dropped and line.startswith("    "):
            continue
        dropped = False
        kept.append(line)
    staff_yaml.write_text("\n".join(kept) + "\n", encoding="utf-8")

    result = runner.invoke(
        app,
        ["solve", "--config", str(work), "--week-start", "2026-11-02", "--dry-run"],
    )
    assert result.exit_code == 1
    assert "求解失败" in result.output or "无解" in result.output


@needs_solver
def test_solve_time_limit_option(example_dir: Path):
    result = runner.invoke(
        app,
        [
            "solve",
            "--config", str(example_dir),
            "--week-start", "2026-11-02",
            "--time-limit", "20",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "求解成功" in result.output
