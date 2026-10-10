"""medshift 图形界面（本地 Web 版）—— Flask 应用与 REST API。

设计要点
--------
* **不重复实现任何排班逻辑**：校验、统计、导出全部委托给
  :class:`~medshift.scheduler.Scheduler`，界面层只做「展示 + 编辑」；
* 前端只与 JSON 打交道，后端不渲染业务数据；
* 所有接口返回 JSON，异常统一为 ``{"error": "..."}`` + 合适的状态码。
"""

import datetime as dt
import re
import tempfile
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file

from ..errors import MedShiftError
from ..exporters import read_assignments, write_assignments
from ..models import Assignment, Shift, ShiftKind, Staff, StaffGroup, StaffStatus
from ..scheduler import Scheduler

GROUP_LABELS = {
    "diagnosis": "诊断组",
    "technician": "技术组",
    "nursing": "护理组",
    "other": "其他",
}
GROUP_ORDER = ["diagnosis", "technician", "nursing", "other"]

# 在岗状态的中文名，用于新增人员表单与列表标签
STATUS_LABELS = {
    "active": "在岗",
    "rotated": "派驻他科",
    "leave": "长期假",
    "training": "外出规培",
}
WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# 班次类别的中文名，用于前端下拉与错误提示
SHIFT_KIND_LABELS = {
    "day": "出勤（正班）",
    "night": "值班（昼夜连续）",
    "evening": "中晚班",
    "backup": "备班",
    "post_night": "值出（下夜班）",
    "off": "休息",
    "other": "其他",
}

# 新增班次时默认配色（按类别），与示例配置的色系保持一致
DEFAULT_COLORS = {
    "day": "DDEBF7",
    "night": "F8CBAD",
    "evening": "FFF2CC",
    "backup": "EDEDED",
    "post_night": "E7E6E6",
    "off": "F2F2F2",
    "other": "EDEDED",
}

CODE_PREFIX = "S_"  # 自动生成代码时使用的前缀，便于人肉识别是界面新建的
_TIME_RE = re.compile(r"^\d{2}:\d{2}(\+1)?$")


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

    # ---------------------- 班次写入（shifts.yaml） ----------------------

    shifts_file = config_path / "shifts.yaml"

    def _next_shift_code(existing: set[str]) -> str:
        """自动生成一个未被占用的班次代码，如 S_1 / S_2。"""
        index = 1
        while f"{CODE_PREFIX}{index}" in existing:
            index += 1
        return f"{CODE_PREFIX}{index}"

    def _render_shift_block(shift: Shift) -> str:
        """把一个 Shift 渲染成与现有文件风格一致的 YAML 块（2 空格缩进）。"""
        lines = [f"  - code: {shift.code}", f"    name: {shift.name}",
                 f"    kind: {shift.kind.value}"]
        if shift.start:
            lines.append(f'    start: "{shift.start}"')
        if shift.end:
            lines.append(f'    end: "{shift.end}"')
        if shift.is_night:
            lines.append("    is_night: true")
        lines.append(f"    weight: {shift.weight:g}")
        if shift.color:
            lines.append(f"    color: {shift.color}")
        if shift.follow_shift:
            lines.append(f"    follow_shift: {shift.follow_shift}")
        return "\n".join(lines) + "\n"

    def _append_shift_to_yaml(shift: Shift) -> None:
        """把新班次**追加**到 shifts.yaml 末尾。

        刻意采用「读原文 → 行级追加 → 写回」，而不是 yaml.safe_load +
        yaml.dump 全量重写：后者会丢掉文件里的全部注释、打乱字段顺序，
        让配置文件变得难以人工维护。
        """
        text = shifts_file.read_text(encoding="utf-8") if shifts_file.exists() else ""

        stripped = text.strip()
        if not stripped:
            # 空文件或原本不存在：补上顶层键
            text = "shifts:\n"
        elif "shifts:" not in text:
            # 裸列表写法（无顶层键），直接续写
            text = text.rstrip("\n") + "\n"
        else:
            # 与上一条班次之间保留一个空行，保持文件可读
            text = text.rstrip("\n") + "\n\n"

        shifts_file.write_text(text + _render_shift_block(shift), encoding="utf-8")

    # ---------------------- 人员写入（staff.yaml） ----------------------

    staff_file = config_path / "staff.yaml"
    _ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,16}$")

    def _next_staff_id(group: str, existing: set[str]) -> str:
        """按组别生成一个未被占用的人员编号，如 D26 / T21 / N04。"""
        prefix = {"diagnosis": "D", "technician": "T", "nursing": "N"}.get(group, "X")
        index = 1
        while f"{prefix}{index:02d}" in existing:
            index += 1
        return f"{prefix}{index:02d}"

    def _render_staff_block(person: Staff) -> str:
        """把一名人员渲染成与现有 staff.yaml 风格一致的 YAML 块。"""
        lines = [
            f"  - id: {person.id}",
            f"    name: {person.name}",
            f"    group: {person.group.value}",
        ]
        if person.title:
            lines.append(f"    title: {person.title}")
        if person.skills:
            lines.append("    skills: [" + ", ".join(person.skills) + "]")
        lines.append(f"    night_eligible: {'true' if person.night_eligible else 'false'}")
        if person.rotation_offset:
            lines.append(f"    rotation_offset: {person.rotation_offset}")
        lines.append(f"    status: {person.status.value}")
        if person.supervisor_id:
            lines.append(f"    supervisor_id: {person.supervisor_id}")
        if person.note:
            lines.append(f"    note: {person.note}")
        return "\n".join(lines) + "\n"

    def _append_staff_to_yaml(person: Staff) -> None:
        """把新人员追加到 staff.yaml 末尾（保留文件原有注释与排版）。"""
        text = staff_file.read_text(encoding="utf-8") if staff_file.exists() else ""

        stripped = text.strip()
        if not stripped:
            text = "staff:\n"
        elif "staff:" not in text:
            text = text.rstrip("\n") + "\n"
        else:
            text = text.rstrip("\n") + "\n\n"

        staff_file.write_text(text + _render_staff_block(person), encoding="utf-8")

    def _remove_staff_from_yaml(staff_id: str) -> tuple[bool, list[str]]:
        """从 staff.yaml 中删掉指定 id 的条目，并解除他人的挂靠。

        以「``- id:`` 开头」为一个条目的边界：找到该行后，一直删到下一个
        同级条目的起始行（或文件末尾）。

        同时把其它条目里指向 ``staff_id`` 的 ``supervisor_id`` 行删掉——
        否则被删人员若曾是带教老师，留下的 ``supervisor_id`` 会让配置校验
        失败（"引用了不存在的带教老师"）。

        Returns:
            ``(是否删除了条目, 被解除挂靠的人员 id 列表)``
        """
        if not staff_file.exists():
            return False, []

        lines = staff_file.read_text(encoding="utf-8").splitlines(keepends=True)

        # 1) 找出所有条目的起始行，便于界定删除范围
        starts = [
            i for i, line in enumerate(lines)
            if re.match(r"^\s*-\s*id:\s*", line)
        ]

        target = None
        for i, line in enumerate(lines):
            m = re.match(r"^\s*-\s*id:\s*['\"]?([^'\"\s]+)['\"]?\s*$", line)
            if m and m.group(1) == staff_id:
                target = i
                break
        if target is None:
            return False, []

        # 2) 条目范围：从 target 到下一个条目起始行（或文件尾）
        end = len(lines)
        for s in starts:
            if s > target:
                end = s
                break
        while end < len(lines) and not lines[end].strip():
            end += 1
        if target > 0 and not lines[target - 1].strip():
            target -= 1

        del lines[target:end]

        # 3) 清掉指向该人员的 supervisor_id 行（记录受影响的人）
        kept: list[str] = []
        released: list[str] = []
        current_id: str | None = None
        for line in lines:
            m_id = re.match(r"^\s*-\s*id:\s*['\"]?([^'\"\s]+)['\"]?\s*$", line)
            if m_id:
                current_id = m_id.group(1)
                kept.append(line)
                continue
            m_sup = re.match(
                r"^\s*supervisor_id:\s*['\"]?([^'\"\s]+)['\"]?\s*$", line
            )
            if m_sup and m_sup.group(1) == staff_id:
                if current_id:
                    released.append(current_id)
                continue  # 丢弃这一行
            kept.append(line)

        content = "".join(kept)
        if content and not content.endswith("\n"):
            content += "\n"
        staff_file.write_text(content, encoding="utf-8")
        return True, released

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
            "shift_kinds": [
                {"value": k, "label": SHIFT_KIND_LABELS[k]}
                for k in SHIFT_KIND_LABELS
            ],
            "staff_groups": [
                {"value": g, "label": GROUP_LABELS.get(g, g)} for g in GROUP_ORDER
            ],
            "staff_statuses": [
                {"value": s, "label": STATUS_LABELS[s]} for s in STATUS_LABELS
            ],
            "skill_options": sorted({sk for p in dept.positions for sk in p.required_skills}),
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

    @app.post("/api/solve")
    def api_solve():
        """一键自动排班（CP-SAT）。

        请求体字段：

        * ``week_start``（可选）—— 起始日期 YYYY-MM-DD；留空取请求体
          ``days[0]``，再留空取今天所在周的周一
        * ``days``（可选，默认 7）
        * ``time_limit_s``（可选）—— 求解时限秒数
        * ``fixed``（可选）—— 需要锁定的格子列表（``staff_id`` / ``date`` /
          ``shift_code``），求解时保持不动

        成功返回 ``{ok, status, assignments, off_by_staff, stats, warnings}``；
        无解时 ``ok=False`` 并带上 ``warnings`` 说明原因，HTTP 仍是 200，
        便于前端把原因展示给用户。
        """
        from ..solver import Solver as _Solver, SolverUnavailableError

        body = request.get_json(silent=True) or {}

        raw_start = str(body.get("week_start") or "").strip()
        if not raw_start:
            days_body = body.get("days") or []
            raw_start = str(days_body[0]) if days_body else ""
        if raw_start:
            try:
                start = dt.date.fromisoformat(raw_start)
            except ValueError:
                return jsonify({"error": f"日期格式不对：{raw_start}"}), 400
        else:
            today = dt.date.today()
            start = today - dt.timedelta(days=today.weekday())

        try:
            days = int(body.get("days_count") or len(body.get("days") or []) or 7)
        except (TypeError, ValueError):
            days = 7
        days = max(1, min(days, 31))

        limit = body.get("time_limit_s")
        try:
            limit_int = int(limit) if limit not in (None, "") else None
        except (TypeError, ValueError):
            limit_int = None

        # 锁定格子
        fixed: list[Assignment] = []
        for item in body.get("fixed") or []:
            try:
                fixed.append(
                    Assignment(
                        staff_id=str(item["staff_id"]),
                        date=dt.date.fromisoformat(str(item["date"])),
                        shift_code=str(item["shift_code"]),
                    )
                )
            except (KeyError, ValueError, TypeError):
                return jsonify({"error": "固定格子数据格式错误"}), 400

        try:
            result = _Solver(dept).solve_week(
                start, days=days, time_limit_s=limit_int, fixed=fixed or None
            )
        except SolverUnavailableError as exc:
            return jsonify({"error": str(exc)}), 400
        except MedShiftError as exc:
            return jsonify({"error": str(exc)}), 400

        payload = {
            "ok": result.ok,
            "status": result.status,
            "objective": result.objective,
            "week_start": start.isoformat(),
            "days": days,
            "off_by_staff": result.off_by_staff,
            "stats": result.stats,
            "warnings": result.warnings,
            "assignments": [_serialize(a) for a in result.assignments],
        }
        return jsonify(payload)

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

    @app.post("/api/shift")
    def api_add_shift():
        """新增一个班次定义，写入 shifts.yaml。

        请求体字段：
        * ``name``（必填）—— 中文显示名，如「核医学扫描」
        * ``kind``（可选，默认 day）—— 见 SHIFT_KIND_LABELS
        * ``code``（可选）—— 留空自动生成 S_n
        * ``start`` / ``end``（可选）—— HH:MM，跨夜用 HH:MM+1
        * ``weight``（可选，默认 1.0）
        * ``is_night``（可选）—— 留空时按 kind 推断

        成功返回新班次的完整定义，供前端直接填入格子。
        """
        body = request.get_json(silent=True) or {}

        name = str(body.get("name") or "").strip()
        if not name:
            return jsonify({"error": "班次名称不能为空"}), 400
        if len(name) > 20:
            return jsonify({"error": "班次名称请控制在 20 个字符以内"}), 400

        kind_raw = str(body.get("kind") or ShiftKind.DAY.value).strip()
        try:
            kind = ShiftKind(kind_raw)
        except ValueError:
            return jsonify({"error": f"未知的班次类别：{kind_raw}"}), 400

        code = str(body.get("code") or "").strip()
        existing_codes = {s.code for s in dept.shifts}
        if code:
            if not re.fullmatch(r"[A-Za-z0-9_\-]{1,32}", code):
                return jsonify(
                    {"error": "班次代码只能用字母、数字、下划线或短横线"}
                ), 400
            if code in existing_codes:
                return jsonify({"error": f"班次代码已存在：{code}"}), 400
        else:
            code = _next_shift_code(existing_codes)

        if any(s.name == name for s in dept.shifts):
            return jsonify({"error": f"已存在同名班次：{name}"}), 400

        start = str(body.get("start") or "").strip() or None
        end = str(body.get("end") or "").strip() or None
        for label, value in (("开始时间", start), ("结束时间", end)):
            if value and not _TIME_RE.match(value):
                return jsonify(
                    {"error": f"{label}格式应为 HH:MM（跨夜写 +1，如 08:00+1）"}
                ), 400

        if "is_night" in body and body.get("is_night") is not None:
            is_night = bool(body.get("is_night"))
        else:
            is_night = kind is ShiftKind.NIGHT

        try:
            weight = float(body.get("weight", 1.0))
        except (TypeError, ValueError):
            return jsonify({"error": "权重必须是数字"}), 400

        color = str(body.get("color") or "").strip().lstrip("#").upper() or None
        if color and not re.fullmatch(r"[0-9A-F]{6}", color):
            color = None
        if color is None:
            color = DEFAULT_COLORS.get(kind.value)

        try:
            shift = Shift(
                code=code,
                name=name,
                kind=kind,
                start=start,
                end=end,
                is_night=is_night,
                weight=weight,
                color=color,
            )
        except MedShiftError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:  # pydantic ValidationError
            return jsonify({"error": f"班次定义不合法：{exc}"}), 400

        # 写回 YAML 并同步内存配置，保证后续校验/统计立即可用
        try:
            _append_shift_to_yaml(shift)
        except OSError as exc:
            return jsonify({"error": f"写入 shifts.yaml 失败：{exc}"}), 500

        dept.shifts.append(shift)
        dept.rebuild_index()

        return jsonify(
            {
                "ok": True,
                "shift": {
                    "code": shift.code,
                    "name": shift.name,
                    "kind": shift.kind.value,
                    "start": shift.start or "",
                    "end": shift.end or "",
                    "is_night": shift.is_night,
                    "weight": shift.weight,
                    "color": shift.color or "",
                    "follow_shift": shift.follow_shift or "",
                },
                "file": shifts_file.name,
            }
        )

    @app.post("/api/staff")
    def api_add_staff():
        """新增一名人员，写入 staff.yaml。

        请求体字段：
        * ``name``（必填）—— 姓名
        * ``group``（可选，默认 other）—— diagnosis / technician / nursing / other
        * ``id``（可选）—— 留空按组别自动生成 D01 / T01 / N01 …
        * ``title``（可选）—— 职称
        * ``skills``（可选）—— 技能标签列表
        * ``night_eligible``（可选，默认 false）
        * ``status``（可选，默认 active）
        * ``supervisor_id``（可选）—— 带教老师 id，填了即为进修／实习人员
        * ``note``（可选）
        """
        body = request.get_json(silent=True) or {}

        name = str(body.get("name") or "").strip()
        if not name:
            return jsonify({"error": "姓名不能为空"}), 400
        if len(name) > 20:
            return jsonify({"error": "姓名请控制在 20 个字符以内"}), 400

        group_raw = str(body.get("group") or StaffGroup.OTHER.value).strip()
        try:
            group = StaffGroup(group_raw)
        except ValueError:
            return jsonify({"error": f"未知的人员组别：{group_raw}"}), 400

        existing_ids = {s.id for s in dept.staff}
        staff_id = str(body.get("id") or "").strip()
        if staff_id:
            if not _ID_RE.match(staff_id):
                return jsonify(
                    {"error": "人员编号只能用字母、数字、下划线或短横线（≤16 位）"}
                ), 400
            if staff_id in existing_ids:
                return jsonify({"error": f"人员编号已存在：{staff_id}"}), 400
        else:
            staff_id = _next_staff_id(group.value, existing_ids)

        if any(s.name == name for s in dept.staff):
            return jsonify({"error": f"已存在同名人员：{name}"}), 400

        title = str(body.get("title") or "").strip() or None

        skills_raw = body.get("skills") or []
        if isinstance(skills_raw, str):
            skills_raw = [p.strip() for p in skills_raw.split(",") if p.strip()]
        if not isinstance(skills_raw, list):
            return jsonify({"error": "技能标签应为数组或逗号分隔的字符串"}), 400
        skills = [str(s).strip() for s in skills_raw if str(s).strip()]

        status_raw = str(body.get("status") or StaffStatus.ACTIVE.value).strip()
        try:
            status = StaffStatus(status_raw)
        except ValueError:
            return jsonify({"error": f"未知的在岗状态：{status_raw}"}), 400

        supervisor_id = str(body.get("supervisor_id") or "").strip() or None
        if supervisor_id and supervisor_id not in existing_ids:
            return jsonify({"error": f"带教老师不存在：{supervisor_id}"}), 400

        note = str(body.get("note") or "").strip() or None

        try:
            person = Staff(
                id=staff_id,
                name=name,
                group=group,
                title=title,
                skills=skills,
                night_eligible=bool(body.get("night_eligible", False)),
                status=status,
                supervisor_id=supervisor_id,
                note=note,
            )
        except Exception as exc:  # pydantic ValidationError
            return jsonify({"error": f"人员信息不合法：{exc}"}), 400

        try:
            _append_staff_to_yaml(person)
        except OSError as exc:
            return jsonify({"error": f"写入 staff.yaml 失败：{exc}"}), 500

        dept.staff.append(person)
        dept.rebuild_index()

        return jsonify(
            {
                "ok": True,
                "staff": {
                    "id": person.id,
                    "name": person.name,
                    "group": person.group.value,
                    "title": person.title or "",
                    "skills": list(person.skills),
                    "night_eligible": person.night_eligible,
                    "status": person.status.value,
                    "supervisor_id": person.supervisor_id or "",
                    "is_trainee": person.is_trainee,
                    "rosterable": person.is_rosterable,
                    "can_hold_position": person.can_hold_position,
                    "note": person.note or "",
                },
                "file": staff_file.name,
            }
        )

    @app.delete("/api/staff/<staff_id>")
    def api_delete_staff(staff_id: str):
        """删除一名人员，并清理引用。

        * 从 staff.yaml 移除该条目；
        * 若有进修／实习人员挂在其名下，一并解除挂靠（置空 supervisor_id），
          避免留下悬空的 ``supervisor_id``；
        * 该人员已有的排班记录由前端在删除后同步清掉，点「保存」时随
          CSV 一起落盘——后端不在这里直接改排班文件，保持与其它编辑一致的
          心智：**排班改动统一由「保存」写入**。
        """
        person = dept.staff_by_id(staff_id)
        if person is None:
            return jsonify({"error": f"人员不存在：{staff_id}"}), 404

        try:
            removed, released = _remove_staff_from_yaml(staff_id)
        except OSError as exc:
            return jsonify({"error": f"写入 staff.yaml 失败：{exc}"}), 500

        if not removed:
            return jsonify({"error": f"staff.yaml 中未找到人员：{staff_id}"}), 404

        dept.staff = [s for s in dept.staff if s.id != staff_id]
        dept.rebuild_index()

        return jsonify(
            {
                "ok": True,
                "deleted": staff_id,
                "deleted_name": person.name,
                "released_trainees": released,
                "file": staff_file.name,
            }
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
