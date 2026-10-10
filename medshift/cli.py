"""medshift 命令行入口。

用法::

    medshift init my-dept
    medshift validate --config my-dept
    medshift solve --config my-dept --week-start 2026-10-12
    medshift check --config my-dept --assignments my-dept/assignments/2026-W42.csv
    medshift export --config my-dept --assignments ... --out 2026-W42.xlsx
    medshift stats --config my-dept --assignments ...

注意：本模块刻意不使用 ``from __future__ import annotations``，
因为 Typer 需要读取真实的类型注解来生成命令行参数。
"""

import datetime as dt
import shutil
import sys
from pathlib import Path
from typing import Optional

import typer

from .config_loader import load_config
from .errors import AssignmentFormatError, ConfigError, MedShiftError
from .scheduler import Scheduler

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="medshift — 医技科室排班器（v0.2：配置校验 + 自动排班 + 排班检查 + Excel 导出）",
)

def _resource_path(*parts: str) -> Path:
    """定位随包分发的资源目录，兼容源码运行与打包冻结两种形态。

    源码运行时基准目录是仓库根；用 PyInstaller 打包后基准目录是解包临时目录
    （``sys._MEIPASS``），示例配置由 ``--add-data`` 一并放入。
    """
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).resolve().parent.parent
    return base.joinpath(*parts)


EXAMPLES_DIR = _resource_path("examples", "radiology")


def _fail(message: str, code: int = 1) -> None:
    typer.secho(message, fg=typer.colors.RED, err=True)
    raise typer.Exit(code=code)


def _ok(message: str) -> None:
    typer.secho(message, fg=typer.colors.GREEN)


@app.command()
def init(
    target: Path = typer.Argument(..., help="要生成配置的目录"),
    force: bool = typer.Option(False, "--force", help="目标目录已存在时覆盖"),
) -> None:
    """生成一份配置骨架（以放射科为例）。"""
    if target.exists() and any(target.iterdir()) and not force:
        _fail(f"目录已存在且非空：{target}（如需覆盖请加 --force）")

    if not EXAMPLES_DIR.is_dir():
        _fail(f"找不到模板目录：{EXAMPLES_DIR}")

    target.mkdir(parents=True, exist_ok=True)
    for src in sorted(EXAMPLES_DIR.glob("*.yaml")):
        shutil.copy2(src, target / src.name)

    _ok(f"已生成配置骨架：{target}")
    typer.echo("下一步：编辑 staff.yaml / positions.yaml，然后运行 "
               f"`medshift validate --config {target}`")


@app.command()
def validate(
    config: Path = typer.Option(Path("."), "--config", "-c", help="配置目录"),
) -> None:
    """校验配置文件本身是否完整、自洽。"""
    try:
        dept = load_config(config)
    except ConfigError as exc:
        _fail("配置存在问题：")
        for problem in exc.problems:
            typer.echo(f"  · {problem}", err=True)
        raise typer.Exit(code=1) from exc

    _ok(f"配置合法：{dept.name}")
    trainees = dept.trainees()
    inactive = [s for s in dept.staff if not s.is_rosterable]
    typer.echo(
        f"  人员 {len(dept.staff)} 人"
        f"（可排班 {len(dept.assignable_staff())}"
        f"、进修实习 {len(trainees)}"
        f"、离岗 {len(inactive)}）"
    )
    typer.echo(
        f"  班次 {len(dept.shifts)} 个｜岗位 {len(dept.positions)} 个"
        f"｜节假日 {len(dept.calendar.holidays)} 天"
    )


@app.command()
def solve(
    config: Path = typer.Option(Path("."), "--config", "-c", help="配置目录"),
    week_start: Optional[str] = typer.Option(
        None, "--week-start", help="排班起始日期 YYYY-MM-DD（默认下周一）"
    ),
    days: int = typer.Option(7, "--days", help="排多少天"),
    out: Optional[Path] = typer.Option(
        None, "--out", "-o", help="输出 CSV 路径（默认写入 assignments/ 下按 ISO 周命名）"
    ),
    time_limit: Optional[int] = typer.Option(
        None, "--time-limit", help="求解时限（秒），留空用 rules.yaml 里的值"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="只求解不落盘，打印结果与统计"
    ),
) -> None:
    """自动排班（CP-SAT 求解一周）。"""
    try:
        from .solver import SolverUnavailableError, solve_week as run_solve
    except ImportError:  # pragma: no cover - 兜底
        _fail("求解器模块不可用")
        return

    try:
        dept = load_config(config)
    except ConfigError as exc:
        _fail("配置存在问题：")
        for problem in exc.problems:
            typer.echo(f"  · {problem}", err=True)
        raise typer.Exit(code=1) from exc

    # 起始日期：默认取「下一个周一」
    if week_start:
        try:
            start = dt.date.fromisoformat(week_start)
        except ValueError:
            _fail(f"日期格式不对：{week_start}（应为 YYYY-MM-DD）")
            return
    else:
        today = dt.date.today()
        start = today + dt.timedelta(days=(7 - today.weekday()) % 7 or 7)

    typer.echo(
        f"正在求解 {start.isoformat()} 起 {days} 天的排班"
        f"（{dept.name}，{len(dept.assignable_staff())} 名可排班人员）…"
    )

    try:
        result = run_solve(dept, start, days=days, time_limit_s=time_limit)
    except SolverUnavailableError as exc:
        _fail(str(exc))
        return

    if not result.ok:
        _fail(f"求解失败：{result.status}")
        for warning in result.warnings:
            typer.echo(f"  · {warning}", err=True)
        raise typer.Exit(code=1)

    _ok(f"求解成功：{result.status}（目标值 {result.objective:.0f}）")
    typer.echo(f"  排班记录 {len(result.assignments)} 条")

    offs = list(result.off_by_staff.values())
    if offs:
        typer.echo(
            f"  每人休息天数：最少 {min(offs)} 天，最多 {max(offs)} 天"
        )
    optional = result.stats.get("optional_filled") or {}
    if optional:
        detail = "、".join(f"{k} {v} 天" for k, v in optional.items())
        typer.echo(f"  可选岗位：{detail}")

    if dry_run:
        typer.echo("（--dry-run：结果未写入文件）")
        return

    if out is None:
        iso = start.isocalendar()
        out = Path(config) / "assignments" / f"{iso[0]}-W{iso[1]:02d}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        scheduler = Scheduler.from_config_dir(config)
        scheduler.save_assignments(result.assignments, out)
    except MedShiftError as exc:
        _fail(str(exc))
        return

    _ok(f"已写入：{out}")
    typer.echo(f"下一步：`medshift check -c {config} -a {out}` 复核，"
               f"或 `medshift gui -c {config}` 在图形界面里微调")


@app.command()
def check(
    config: Path = typer.Option(Path("."), "--config", "-c", help="配置目录"),
    assignments: Path = typer.Option(..., "--assignments", "-a", help="排班 CSV 文件"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="列出每条问题"),
) -> None:
    """校验一份排班数据是否满足全部硬约束。"""
    try:
        scheduler = Scheduler.from_config_dir(config)
        items = scheduler.load_assignments(assignments)
        report = scheduler.check(items)
    except (ConfigError, AssignmentFormatError) as exc:
        _fail(str(exc))
        return
    except MedShiftError as exc:
        _fail(str(exc))
        return

    typer.echo(report.summary())

    if verbose:
        for violation in report.violations:
            colour = (
                typer.colors.RED if violation.severity.value == "error" else typer.colors.YELLOW
            )
            typer.secho(f"  · {violation}", fg=colour)

    if not report.ok:
        raise typer.Exit(code=1)


@app.command()
def export(
    config: Path = typer.Option(Path("."), "--config", "-c", help="配置目录"),
    assignments: Path = typer.Option(..., "--assignments", "-a", help="排班 CSV 文件"),
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="输出 .xlsx 路径"),
    week_start: Optional[str] = typer.Option(
        None, "--week-start", help="周一日期 YYYY-MM-DD，留空自动推断"
    ),
) -> None:
    """把排班数据导出为 Excel 周表。"""
    try:
        scheduler = Scheduler.from_config_dir(config)
        items = scheduler.load_assignments(assignments)
        start = dt.date.fromisoformat(week_start) if week_start else None
        if out is None:
            out = assignments.with_suffix(".xlsx")
        path = scheduler.export_excel(items, out, start)
    except (ConfigError, AssignmentFormatError, ValueError) as exc:
        _fail(str(exc))
        return

    _ok(f"已导出：{path}")
    typer.echo(f"  共 {len(items)} 条排班记录")


@app.command()
def stats(
    config: Path = typer.Option(Path("."), "--config", "-c", help="配置目录"),
    assignments: Path = typer.Option(..., "--assignments", "-a", help="排班 CSV 文件"),
) -> None:
    """按人汇总出勤天数、夜班次数与加权分。"""
    try:
        scheduler = Scheduler.from_config_dir(config)
        items = scheduler.load_assignments(assignments)
        rows = scheduler.stats(items)
    except (ConfigError, AssignmentFormatError) as exc:
        _fail(str(exc))
        return

    header = f"{'姓名':<8}{'组别':<8}{'出勤':>5}{'休息':>5}{'夜班':>5}{'值出':>5}{'加权分':>8}"
    typer.echo(header)
    typer.echo("-" * len(header.encode("gbk", errors="ignore")))
    for row in rows:
        typer.echo(
            f"{row.name:<8}{row.group:<8}{row.work_days:>5}{row.off_days:>5}"
            f"{row.night_count:>5}{row.post_night_count:>5}{row.weighted_score:>8}"
        )


@app.command()
def gui(
    config: Path = typer.Option(Path("."), "--config", "-c", help="配置目录"),
    assignments: Optional[Path] = typer.Option(
        None, "--assignments", "-a", help="初始打开的排班 CSV；留空取最新一个"
    ),
    port: int = typer.Option(8765, "--port", help="监听端口（被占用时自动顺延）"),
    no_browser: bool = typer.Option(False, "--no-browser", help="不自动打开浏览器"),
) -> None:
    """打开图形界面（本地网页，浏览器里排班）。"""
    try:
        from .gui import serve
    except ImportError:
        _fail('未安装图形界面依赖，请先执行：pip install "medshift[gui]"')
        return

    if not Path(config).is_dir():
        _fail(f"配置目录不存在：{config}")
        return

    typer.echo("正在启动图形界面…")
    try:
        serve(config, assignments, port=port, open_browser=not no_browser)
    except RuntimeError as exc:
        _fail(str(exc))


def main() -> None:
    """控制台脚本入口。"""
    try:
        app()
    except MedShiftError as exc:  # pragma: no cover - 兜底
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        sys.exit(1)


if __name__ == "__main__":  # pragma: no cover
    main()
