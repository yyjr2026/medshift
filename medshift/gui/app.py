"""medshift 图形界面（本地 Web 版）—— Flask 应用与 REST API。

设计要点
--------
* **不重复实现任何排班逻辑**：校验、统计、导出全部委托给
  :class:`~medshift.scheduler.Scheduler`，界面层只做「展示 + 编辑」；
* 前端只与 JSON 打交道，后端不渲染业务数据；
* 所有接口返回 JSON，异常统一为 ``{"error": "..."}`` + 合适的状态码。
"""

import datetime as dt
import tempfile
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file

from ..errors import MedShiftError
from ..exporters import read_assignments, write_assignments
from ..models import Assignment
from ..scheduler import Scheduler

GROUP_LABELS = {
    "diagnosis": "诊断组",
    "technician": "技术组",
    "nursing": "护理组",
    "other": "其他",
}
GROUP_ORDER = ["diagnosis", "technician", "nursing", "other"]
WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def create_app(
    config_dir: str | Path,
    assignments_file: str | Path | None = None,
    *,
    export_dir: str | Path | None = None,
) -> Flask:
    """构造 Flask 应用。

    Args:
        config_dir: 科室配置目录（含 staff.yaml 等）。
        assignments_file: 初始打开的排班 CSV；留空则取 assignments/ 下最后一个。
        export_dir: 导出 Excel 的落地目录；默认用系统临时目录。
    """
    config_path = Path(config_dir).resolve()
    scheduler = Scheduler.from_config_dir(config_path)
    dept = scheduler.config

    assignments_dir = config_path / "assignments"
    export_path = (
        Path(export_dir).resolve()
        if export_dir
        else Path(tempfile.gettempdir()) / "medshift-export"
    )
    export_path.mkdir(parents=True, exist_ok=True)

    if assignments_file is not None:
        preset_csv = Path(assignments_file)
        if not preset_csv.is_absolute():
            preset_csv = (config_path / preset_csv).resolve()
    else:
        preset_csv = None

    app = Flask(__name__)
    app.json.ensure_ascii = False  # 中文原样输出，不转义成 \uXXXX

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _all_csv() -> list[Path]:
        if not assignments_dir.is_dir():
            return []
        return sorted(assignments_dir.glob("*.csv"))

    def _default_csv() -> Path | None:
        if preset_csv is not None and preset_csv.is_file():
            return preset_csv
        files = _all_csv()
        return files[-1] if files else None

    def _existing_csv(rel: str | None) -> Path | None:
        """把前端传来的文件名解析为 assignments 下的真实路径（防目录穿越）。"""
        if not rel:
            return None
        candidate = assignments_dir / Path(rel).name
        return candidate if candidate.is_file() else None

    def _target_csv(rel: str | None) -> Path:
        """保存目标的解析：允许新建文件。"""
        name = Path(rel).name if rel else ""
        if not name:
            existing = _default_csv()
            if existing is not None:
                return existing
            name = "assignments.csv"
        if not name.lower().endswith(".csv"):
            name += ".csv"
        assignments_dir.mkdir(parents=True, exist_ok=True)
        return assignments_dir / name

    def _serialize(item: Assignment) -> dict:
        return {
            "staff_id": item.staff_id,
            "date": item.date.isoformat(),
            "shift_code": item.shift_code,
            "position_id": item.position_id or "",
            "tags": list(item.tags),
        }

    def _parse_items(raw: object) -> list[Assignment]:
        """把前端 JSON 转成 Assignment 列表。"""
        items: list[Assignment] = []
        for row in raw or []:  # type: ignore[union-attr]
            if not isinstance(row, dict):
                raise ValueError("每条排班记录必须是对象")
            staff_id = str(row["staff_id"]).strip()
            shift_code = str(row["shift_code"]).strip()
            if not staff_id or not shift_code:
                raise ValueError("staff_id 与 shift_code 不能为空")
            items.append(
                Assignment(
                    staff_id=staff_id,
                    date=dt.date.fromisoformat(str(row["date"])),
                    shift_code=shift_code,
                    position_id=(str(row.get("position_id") or "").strip() or None),
                    tags=[str(t) for t in (row.get("tags") or [])],
                )
            )
        return items

    def _dump_report(report) -> dict:
        def one(v) -> dict:
            return {
                "code": v.code,
                "message": v.message,
                "severity": v.severity.value,
                "date": v.date.isoformat() if v.date else "",
                "staff_id": v.staff_id or "",
                "position_id": v.position_id or "",
            }

        return {
            "ok": report.ok,
            "summary": report.summary(),
            "errors": [one(v) for v in report.errors],
            "warnings": [one(v) for v in report.warnings],
        }

    def _config_payload() -> dict:
        present = {s.group.value for s in dept.staff}
        return {
            "name": dept.name,
            "description": dept.description or "",
            "config_dir": str(config_path),
            "groups": [
                {"value": g, "label": GROUP_LABELS.get(g, g)}
                for g in GROUP_ORDER
                if g in present
            ],
            "staff": [
                {
                    "id": s.id,
                    "name": s.name,
                    "group": s.group.value,
                    "title": s.title or "",
                    "skills": list(s.skills),
                    "night_eligible": s.night_eligible,
                    "status": s.status.value,
                    "supervisor_id": s.supervisor_id or "",
                    "is_trainee": s.is_trainee,
                    "rosterable": s.is_rosterable,
                    "can_hold_position": s.can_hold_position,
                    "note": s.note or "",
                }
                for s in dept.staff
            ],
            "shifts": [
                {
                    "code": s.code,
                    "name": s.name,
                    "kind": s.kind.value,
                    "start": s.start or "",
                    "end": s.end or "",
                    "is_night": s.is_night,
                    "weight": s.weight,
                    "color": s.color or "",
                    "follow_shift": s.follow_shift or "",
                }
                for s in dept.shifts
            ],
            "positions": [
                {
                    "id": p.id,
                    "name": p.name,
                    "shift_code": p.shift_code,
                    "daily_need": p.daily_need,
                    "required_skills": list(p.required_skills),
                    "group": p.group.value if p.group else "",
                    "priority": p.priority,
                    "note": p.note or "",
                }
                for p in dept.positions
            ],
            "rules": {
                "max_off_per_day": dict(dept.rules.max_off_per_day),
                "min_night_eligible": dict(dept.rules.min_night_eligible),
                "max_night_per_month": dept.rules.max_night_per_month,
            },
            "calendar": {
                "holidays": {d.isoformat(): n for d, n in dept.calendar.holidays.items()},
                "anchors": {d.isoformat(): n for d, n in dept.calendar.anchors.items()},
                "adjusted_workdays": [
                    d.isoformat() for d in dept.calendar.adjusted_workdays
                ],
            },
        }

    # ------------------------------------------------------------------
    # 页面
    # ------------------------------------------------------------------

    @app.get("/")
    def index():
        return render_template("index.html", dept_name=dept.name)

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------

    @app.get("/api/state")
    def api_state():
        """一次性返回界面所需的全部数据。"""
        rel = request.args.get("file")
        path = _existing_csv(rel) if rel else None
        if path is None:
            # 未指定、或指定的文件不存在（含非法路径）时，回落到默认文件
            path = _default_csv()
        items: list[Assignment] = []
        if path is not None:
            try:
                items = read_assignments(path)
            except MedShiftError as exc:
                return jsonify({"error": str(exc)}), 400

        if items:
            days = sorted({a.date for a in items})
        else:
            # 空文件时给出一整周（本周一至周日）作为可编辑骨架
            today = dt.date.today()
            monday = today - dt.timedelta(days=today.weekday())
            days = [monday + dt.timedelta(days=i) for i in range(7)]

        return jsonify(
            {
                "config": _config_payload(),
                "files": [
                    {"name": p.name, "label": p.stem} for p in _all_csv()
                ],
                "current_file": path.name if path else "",
                "days": [d.isoformat() for d in days],
                "weekday_labels": WEEKDAY_LABELS,
                "assignments": [_serialize(a) for a in items],
                "report": _dump_report(scheduler.check(items)),
                "stats": [s.model_dump() for s in scheduler.stats(items)],
            }
        )

    @app.post("/api/check")
    def api_check():
        """对前端当前编辑中的排班做一次完整校验。"""
        body = request.get_json(silent=True) or {}
        try:
            items = _parse_items(body.get("assignments"))
        except (KeyError, ValueError, TypeError) as exc:
            return jsonify({"error": f"排班数据格式错误：{exc}"}), 400
        return jsonify(_dump_report(scheduler.check(items)))

    @app.post("/api/save")
    def api_save():
        """把当前排班写回 CSV。"""
        body = request.get_json(silent=True) or {}
        try:
            items = _parse_items(body.get("assignments"))
        except (KeyError, ValueError, TypeError) as exc:
            return jsonify({"error": f"排班数据格式错误：{exc}"}), 400

        target = _target_csv(body.get("file"))
        write_assignments(items, target)
        return jsonify(
            {"ok": True, "file": target.name, "count": len(items)}
        )

    @app.post("/api/export")
    def api_export():
        """导出 Excel 周表，返回下载地址。"""
        body = request.get_json(silent=True) or {}
        try:
            items = _parse_items(body.get("assignments"))
        except (KeyError, ValueError, TypeError) as exc:
            return jsonify({"error": f"排班数据格式错误：{exc}"}), 400

        stem = Path(str(body.get("file") or "排班表")).stem or "排班表"
        out_name = f"{stem}.xlsx"
        out_path = export_path / out_name
        try:
            scheduler.export_excel(items, out_path)
        except MedShiftError as exc:
            return jsonify({"error": str(exc)}), 400

        return jsonify(
            {"ok": True, "name": out_name, "url": f"/api/download/{out_name}"}
        )

    @app.get("/api/download/<path:name>")
    def api_download(name: str):
        target = export_path / Path(name).name
        if not target.is_file():
            return jsonify({"error": "文件不存在或已过期"}), 404
        return send_file(target, as_attachment=True, download_name=target.name)

    # ------------------------------------------------------------------
    # 异常
    # ------------------------------------------------------------------

    @app.errorhandler(MedShiftError)
    def on_medshift_error(exc):
        return jsonify({"error": str(exc)}), 400

    @app.errorhandler(500)
    def on_server_error(exc):  # pragma: no cover - 兜底分支
        return jsonify({"error": "服务器内部错误"}), 500

    return app
