"""GUI 后端（Flask 应用）的接口测试。

配置会先复制到临时目录，避免写到仓库里的示例数据。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

pytest.importorskip("flask")

from medshift.gui import create_app  # noqa: E402


@pytest.fixture
def config_dir(tmp_path: Path, example_dir: Path) -> Path:
    """把示例配置整体复制到临时目录，隔离写入。"""
    target = tmp_path / "dept"
    shutil.copytree(example_dir, target)
    return target


@pytest.fixture
def client(config_dir: Path, tmp_path: Path):
    app = create_app(config_dir, export_dir=tmp_path / "export")
    app.config.update(TESTING=True)
    return app.test_client()


def _state(client, **params) -> dict:
    res = client.get("/api/state", query_string=params)
    assert res.status_code == 200, res.data
    return res.get_json()


# ----------------------------------------------------------------------
# 页面
# ----------------------------------------------------------------------


def test_index_renders(client):
    res = client.get("/")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "medshift" in html
    assert "排班器" in html


# ----------------------------------------------------------------------
# GET /api/state
# ----------------------------------------------------------------------


def test_state_returns_full_payload(client):
    data = _state(client)
    cfg = data["config"]
    assert cfg["name"]
    assert len(cfg["staff"]) == 26
    assert len(cfg["shifts"]) == 18
    assert len(cfg["positions"]) == 15
    assert data["current_file"] == "2026-W42.csv"
    assert len(data["assignments"]) == 168
    assert data["report"]["ok"] is True
    assert isinstance(data["stats"], list) and data["stats"]
    assert len(data["days"]) == 7
    assert data["weekday_labels"][0] == "周一"


def test_state_groups_are_ordered_and_labelled(client):
    groups = _state(client)["config"]["groups"]
    assert [g["value"] for g in groups] == ["diagnosis", "technician", "nursing"]
    assert groups[0]["label"] == "诊断组"


def test_state_falls_back_on_unknown_file(client):
    data = _state(client, file="不存在.csv")
    assert data["current_file"] == "2026-W42.csv"


def test_state_blocks_path_traversal(client):
    data = _state(client, file="../../etc/passwd")
    assert data["current_file"] == "2026-W42.csv"


def test_state_empty_file_yields_current_week(client, config_dir: Path):
    empty = config_dir / "assignments" / "empty.csv"
    empty.write_text("staff_id,date,shift_code,position_id,tags\n", encoding="utf-8")

    data = _state(client, file="empty.csv")
    assert data["assignments"] == []
    assert len(data["days"]) == 7  # 给出本周骨架，便于从零排班
    assert data["report"]["ok"] is True


def test_state_lists_csv_files(client):
    files = _state(client)["files"]
    assert [f["name"] for f in files] == ["2026-W42.csv"]


# ----------------------------------------------------------------------
# POST /api/check
# ----------------------------------------------------------------------


def test_check_detects_missing_post_duty(client):
    assignments = _state(client)["assignments"]
    trimmed = [a for a in assignments if a["shift_code"] != "POST_DUTY"]

    res = client.post("/api/check", json={"assignments": trimmed})
    assert res.status_code == 200
    report = res.get_json()
    assert report["ok"] is False
    assert any(v["code"] == "NIGHT_NOT_FOLLOWED" for v in report["errors"])


def test_check_detects_unknown_staff(client):
    res = client.post(
        "/api/check",
        json={
            "assignments": [
                {
                    "staff_id": "NOPE",
                    "date": "2026-10-12",
                    "shift_code": "DAY",
                    "position_id": "",
                    "tags": [],
                }
            ]
        },
    )
    report = res.get_json()
    assert any(v["code"] == "UNKNOWN_STAFF" for v in report["errors"])


def test_check_rejects_bad_payload(client):
    res = client.post("/api/check", json={"assignments": [{"staff_id": "D01"}]})
    assert res.status_code == 400
    assert "error" in res.get_json()


# ----------------------------------------------------------------------
# POST /api/save
# ----------------------------------------------------------------------


def test_save_roundtrip(client):
    assignments = _state(client)["assignments"]
    for item in assignments:
        if item["date"] == "2026-10-12":
            item["shift_code"] = "OFF"
            item["position_id"] = ""
            break

    res = client.post(
        "/api/save", json={"file": "2026-W42.csv", "assignments": assignments}
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] is True
    assert body["count"] == len(assignments)

    again = _state(client)["assignments"]
    assert len(again) == len(assignments)
    assert any(a["shift_code"] == "OFF" for a in again)


def test_save_creates_new_file(client, config_dir: Path):
    res = client.post(
        "/api/save",
        json={
            "file": "2026-W43.csv",
            "assignments": [
                {
                    "staff_id": "D01",
                    "date": "2026-10-12",
                    "shift_code": "OFF",
                    "position_id": "",
                    "tags": [],
                }
            ],
        },
    )
    assert res.status_code == 200
    assert (config_dir / "assignments" / "2026-W43.csv").is_file()


def test_save_rejects_bad_payload(client):
    res = client.post(
        "/api/save",
        json={
            "assignments": [
                {"staff_id": "D01", "date": "不是日期", "shift_code": "DAY"}
            ]
        },
    )
    assert res.status_code == 400
    assert "error" in res.get_json()


# ----------------------------------------------------------------------
# POST /api/export 与下载
# ----------------------------------------------------------------------


def test_export_produces_xlsx(client):
    assignments = _state(client)["assignments"]
    res = client.post(
        "/api/export", json={"file": "2026-W42.csv", "assignments": assignments}
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["name"] == "2026-W42.xlsx"

    download = client.get(body["url"])
    assert download.status_code == 200
    assert download.data[:2] == b"PK"  # xlsx 本质是 zip
    assert len(download.data) > 3000


def test_download_missing_file_returns_404(client):
    res = client.get("/api/download/nope.xlsx")
    assert res.status_code == 404


# ----------------------------------------------------------------------
# 新增班次（POST /api/shift）
# ----------------------------------------------------------------------


def test_add_shift_writes_yaml_and_returns_definition(client, config_dir: Path):
    before = (config_dir / "shifts.yaml").read_text(encoding="utf-8")

    res = client.post(
        "/api/shift",
        json={"name": "核医学扫描", "kind": "day", "start": "08:00",
              "end": "17:30", "weight": 1.5},
    )
    assert res.status_code == 200, res.data
    body = res.get_json()
    assert body["ok"] is True
    assert body["file"] == "shifts.yaml"

    shift = body["shift"]
    assert shift["name"] == "核医学扫描"
    assert shift["kind"] == "day"
    assert shift["code"] == "S_1"          # 自动生成的代码
    assert shift["weight"] == 1.5
    assert shift["color"]                   # 按类别自动配色

    after = (config_dir / "shifts.yaml").read_text(encoding="utf-8")
    # 只追加，不动原文（注释保留）
    assert after.startswith(before.rstrip())
    assert "核医学扫描" in after
    assert "# 班次字典" in after


def test_add_shift_auto_generates_incrementing_codes(client):
    codes = []
    for name in ("甲班", "乙班", "丙班"):
        res = client.post("/api/shift", json={"name": name, "kind": "day"})
        assert res.status_code == 200
        codes.append(res.get_json()["shift"]["code"])
    assert codes == ["S_1", "S_2", "S_3"]


def test_add_shift_rejects_duplicate_name(client):
    client.post("/api/shift", json={"name": "重复班"})
    res = client.post("/api/shift", json={"name": "重复班"})
    assert res.status_code == 400
    assert "同名" in res.get_json()["error"]


def test_add_shift_rejects_blank_name(client):
    res = client.post("/api/shift", json={"name": "   "})
    assert res.status_code == 400
    assert "不能为空" in res.get_json()["error"]


def test_add_shift_rejects_unknown_kind(client):
    res = client.post("/api/shift", json={"name": "怪班", "kind": "nope"})
    assert res.status_code == 400
    assert "类别" in res.get_json()["error"]


def test_add_shift_rejects_bad_time(client):
    res = client.post("/api/shift", json={"name": "怪时间", "start": "8点"})
    assert res.status_code == 400
    assert "时间" in res.get_json()["error"]


def test_add_shift_night_kind_sets_is_night(client):
    res = client.post(
        "/api/shift",
        json={"name": "二线值班", "kind": "night",
              "start": "12:00", "end": "08:00+1", "weight": 3},
    )
    assert res.status_code == 200
    assert res.get_json()["shift"]["is_night"] is True


def test_add_shift_reflects_in_state_and_check(client):
    """新增后，配置负载与校验器都应立刻认得这个班次。"""
    res = client.post("/api/shift", json={"name": "彩超", "kind": "day"})
    code = res.get_json()["shift"]["code"]

    state = _state(client)
    codes = [s["code"] for s in state["config"]["shifts"]]
    assert code in codes
    # 顺带确认类别字典也下发了
    assert any(k["value"] == "day" for k in state["config"]["shift_kinds"])

    person_id = next(s["id"] for s in state["config"]["staff"] if s["rosterable"])
    day = state["days"][0]
    res2 = client.post(
        "/api/check",
        json={"assignments": [{"staff_id": person_id, "date": day,
                               "shift_code": code, "position_id": "", "tags": []}]},
    )
    report = res2.get_json()
    assert not any(v["code"] == "UNKNOWN_SHIFT" for v in report["errors"])


def test_add_shift_persists_across_app_restart(config_dir: Path, tmp_path: Path):
    """重开应用后，新增的班次应仍在（证明真写盘了）。"""
    app1 = create_app(config_dir, export_dir=tmp_path / "e1")
    app1.test_client().post("/api/shift", json={"name": "持久化测试", "kind": "day"})

    app2 = create_app(config_dir, export_dir=tmp_path / "e2")
    state = app2.test_client().get("/api/state").get_json()
    assert any(s["name"] == "持久化测试" for s in state["config"]["shifts"])


# ----------------------------------------------------------------------
# 新增班次（POST /api/shift）
# ----------------------------------------------------------------------


def test_add_shift_writes_yaml_and_returns_definition(client, config_dir: Path):
    before = (config_dir / "shifts.yaml").read_text(encoding="utf-8")

    res = client.post(
        "/api/shift",
        json={"name": "核医学扫描", "kind": "day", "start": "08:00",
              "end": "17:30", "weight": 1.5},
    )
    assert res.status_code == 200, res.data
    body = res.get_json()
    assert body["ok"] is True
    assert body["file"] == "shifts.yaml"

    shift = body["shift"]
    assert shift["name"] == "核医学扫描"
    assert shift["kind"] == "day"
    assert shift["code"] == "S_1"          # 自动生成的代码
    assert shift["weight"] == 1.5
    assert shift["color"]                   # 按类别自动配色

    after = (config_dir / "shifts.yaml").read_text(encoding="utf-8")
    # 只追加，不动原文（注释保留）
    assert after.startswith(before.rstrip())
    assert "核医学扫描" in after
    assert "# 班次字典" in after


def test_add_shift_auto_generates_incrementing_codes(client):
    codes = []
    for name in ("甲班", "乙班", "丙班"):
        res = client.post("/api/shift", json={"name": name, "kind": "day"})
        assert res.status_code == 200
        codes.append(res.get_json()["shift"]["code"])
    assert codes == ["S_1", "S_2", "S_3"]


def test_add_shift_rejects_duplicate_name(client):
    client.post("/api/shift", json={"name": "重复班"})
    res = client.post("/api/shift", json={"name": "重复班"})
    assert res.status_code == 400
    assert "同名" in res.get_json()["error"]


def test_add_shift_rejects_blank_name(client):
    res = client.post("/api/shift", json={"name": "   "})
    assert res.status_code == 400
    assert "不能为空" in res.get_json()["error"]


def test_add_shift_rejects_unknown_kind(client):
    res = client.post("/api/shift", json={"name": "怪班", "kind": "nope"})
    assert res.status_code == 400
    assert "类别" in res.get_json()["error"]


def test_add_shift_rejects_bad_time(client):
    res = client.post("/api/shift", json={"name": "怪时间", "start": "8点"})
    assert res.status_code == 400
    assert "时间" in res.get_json()["error"]


def test_add_shift_night_kind_sets_is_night(client):
    res = client.post(
        "/api/shift",
        json={"name": "二线值班", "kind": "night",
              "start": "12:00", "end": "08:00+1", "weight": 3},
    )
    assert res.status_code == 200
    assert res.get_json()["shift"]["is_night"] is True


def test_add_shift_reflects_in_state_and_check(client):
    """新增后，配置负载与校验器都应立刻认得这个班次。"""
    res = client.post("/api/shift", json={"name": "彩超", "kind": "day"})
    code = res.get_json()["shift"]["code"]

    state = _state(client)
    codes = [s["code"] for s in state["config"]["shifts"]]
    assert code in codes
    # 顺带确认类别字典也下发了
    assert any(k["value"] == "day" for k in state["config"]["shift_kinds"])

    person_id = next(s["id"] for s in state["config"]["staff"] if s["rosterable"])
    day = state["days"][0]
    res2 = client.post(
        "/api/check",
        json={"assignments": [{"staff_id": person_id, "date": day,
                               "shift_code": code, "position_id": "", "tags": []}]},
    )
    report = res2.get_json()
    assert not any(v["code"] == "UNKNOWN_SHIFT" for v in report["errors"])


def test_add_shift_persists_across_app_restart(config_dir: Path, tmp_path: Path):
    """重开应用后，新增的班次应仍在（证明真写盘了）。"""
    app1 = create_app(config_dir, export_dir=tmp_path / "e1")
    app1.test_client().post("/api/shift", json={"name": "持久化测试", "kind": "day"})

    app2 = create_app(config_dir, export_dir=tmp_path / "e2")
    state = app2.test_client().get("/api/state").get_json()
    assert any(s["name"] == "持久化测试" for s in state["config"]["shifts"])


# ----------------------------------------------------------------------
# 新增人员（POST /api/staff）
# ----------------------------------------------------------------------


def _staff_state(client) -> list[dict]:
    return _state(client)["config"]["staff"]


def test_add_staff_writes_yaml_and_returns_entry(client, config_dir: Path):
    before = len(_staff_state(client))
    res = client.post(
        "/api/staff",
        json={
            "name": "张三",
            "group": "diagnosis",
            "title": "主治医师",
            "skills": ["CT_DIAG", "DR_DIAG"],
            "night_eligible": True,
        },
    )
    assert res.status_code == 200, res.data
    body = res.get_json()
    person = body["staff"]
    assert person["name"] == "张三"
    assert person["group"] == "diagnosis"
    assert person["night_eligible"] is True
    assert person["skills"] == ["CT_DIAG", "DR_DIAG"]
    assert person["rosterable"] is True
    assert body["file"] == "staff.yaml"

    # 真写盘了
    text = (config_dir / "staff.yaml").read_text(encoding="utf-8")
    assert "张三" in text
    assert len(_staff_state(client)) == before + 1


def test_add_staff_auto_generates_group_prefixed_id(client):
    ids = []
    for i in range(2):
        res = client.post(
            "/api/staff", json={"name": f"护理新{i}", "group": "nursing"}
        )
        ids.append(res.get_json()["staff"]["id"])
    assert all(i.startswith("N") for i in ids)
    assert len(set(ids)) == 2  # 互不重复


def test_add_staff_rejects_duplicate_name(client):
    client.post("/api/staff", json={"name": "李四", "group": "nursing"})
    res = client.post("/api/staff", json={"name": "李四", "group": "technician"})
    assert res.status_code == 400
    assert "同名" in res.get_json()["error"]


def test_add_staff_rejects_blank_name(client):
    res = client.post("/api/staff", json={"name": "   ", "group": "nursing"})
    assert res.status_code == 400
    assert "姓名" in res.get_json()["error"]


def test_add_staff_rejects_unknown_group(client):
    res = client.post("/api/staff", json={"name": "王五", "group": "不存在"})
    assert res.status_code == 400
    assert "组别" in res.get_json()["error"]


def test_add_staff_rejects_duplicate_id(client):
    existing = next(s["id"] for s in _staff_state(client))
    res = client.post(
        "/api/staff", json={"name": "重号人", "group": "nursing", "id": existing}
    )
    assert res.status_code == 400
    assert "编号已存在" in res.get_json()["error"]


def test_add_staff_accepts_comma_separated_skills(client):
    res = client.post(
        "/api/staff",
        json={"name": "逗号技", "group": "technician", "skills": "CT_SCAN, MR_SCAN"},
    )
    assert res.status_code == 200
    assert res.get_json()["staff"]["skills"] == ["CT_SCAN", "MR_SCAN"]


def test_add_staff_with_supervisor_marks_trainee(client):
    supervisor = next(s["id"] for s in _staff_state(client) if s["rosterable"])
    res = client.post(
        "/api/staff",
        json={"name": "实习生甲", "group": "diagnosis", "supervisor_id": supervisor},
    )
    person = res.get_json()["staff"]
    assert person["is_trainee"] is True
    assert person["can_hold_position"] is False


def test_add_staff_rejects_missing_supervisor(client):
    res = client.post(
        "/api/staff",
        json={"name": "实习生乙", "group": "diagnosis", "supervisor_id": "NOPE"},
    )
    assert res.status_code == 400
    assert "带教老师" in res.get_json()["error"]


def test_add_staff_non_active_status_is_not_rosterable(client):
    res = client.post(
        "/api/staff", json={"name": "产假人", "group": "nursing", "status": "leave"}
    )
    person = res.get_json()["staff"]
    assert person["status"] == "leave"
    assert person["rosterable"] is False


def test_add_staff_persists_across_app_restart(config_dir: Path, tmp_path: Path):
    app1 = create_app(config_dir, export_dir=tmp_path / "e1")
    app1.test_client().post(
        "/api/staff", json={"name": "持久化人员", "group": "nursing"}
    )

    app2 = create_app(config_dir, export_dir=tmp_path / "e2")
    state = app2.test_client().get("/api/state").get_json()
    assert any(s["name"] == "持久化人员" for s in state["config"]["staff"])


def test_config_payload_exposes_staff_options(client):
    cfg = _state(client)["config"]
    assert any(g["value"] == "diagnosis" for g in cfg["staff_groups"])
    assert any(s["value"] == "active" for s in cfg["staff_statuses"])
    assert cfg["skill_options"]  # 技能并集非空


# ----------------------------------------------------------------------
# 删除人员（DELETE /api/staff/<id>）
# ----------------------------------------------------------------------


def test_delete_staff_removes_from_yaml(client, config_dir: Path):
    target = next(s["id"] for s in _staff_state(client))
    before = len(_staff_state(client))

    res = client.delete(f"/api/staff/{target}")
    assert res.status_code == 200, res.data
    assert res.get_json()["deleted"] == target

    assert len(_staff_state(client)) == before - 1
    assert target not in (config_dir / "staff.yaml").read_text(encoding="utf-8")


def test_delete_missing_staff_returns_404(client):
    res = client.delete("/api/staff/DOES_NOT_EXIST")
    assert res.status_code == 404


def test_delete_staff_releases_trainees(client, config_dir: Path):
    """删掉带教老师后，挂在其名下的人员应自动解除挂靠，配置仍可加载。"""
    supervisor = next(s["id"] for s in _staff_state(client) if s["rosterable"])
    client.post(
        "/api/staff",
        json={"name": "随教实习生", "group": "diagnosis", "supervisor_id": supervisor},
    )

    res = client.delete(f"/api/staff/{supervisor}")
    assert res.status_code == 200
    released = res.get_json()["released_trainees"]
    assert released  # 至少释放了刚挂上去的那位

    # 关键：配置仍能被加载（不会出现悬空 supervisor_id）
    from medshift.config_loader import load_config

    cfg = load_config(config_dir)
    trainee = next(s for s in cfg.staff if s.name == "随教实习生")
    assert trainee.supervisor_id is None
    assert trainee.can_hold_position is True


def test_delete_staff_keeps_yaml_loadable_after_multiple_ops(client, config_dir: Path):
    """连续增删后 YAML 仍应可解析，且注释不丢。"""
    from medshift.config_loader import load_config

    original_comments = sum(
        1
        for line in (config_dir / "staff.yaml").read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("#")
    )

    client.post("/api/staff", json={"name": "批量甲", "group": "nursing"})
    client.post("/api/staff", json={"name": "批量乙", "group": "technician"})
    victims = [s["id"] for s in _staff_state(client)][:3]
    for vid in victims:
        client.delete(f"/api/staff/{vid}")

    cfg = load_config(config_dir)  # 不抛异常即为通过
    assert len(cfg.staff) > 0

    remaining_comments = sum(
        1
        for line in (config_dir / "staff.yaml").read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("#")
    )
    assert remaining_comments == original_comments


def test_add_then_delete_returns_to_original_count(client):
    before = len(_staff_state(client))
    res = client.post("/api/staff", json={"name": "临时人员", "group": "nursing"})
    new_id = res.get_json()["staff"]["id"]
    assert len(_staff_state(client)) == before + 1

    client.delete(f"/api/staff/{new_id}")
    assert len(_staff_state(client)) == before


# ----------------------------------------------------------------------
# 一键排一周（/api/solve）
# ----------------------------------------------------------------------

_has_ortools = True
try:  # noqa: SIM105
    from ortools.sat.python import cp_model  # noqa: F401
except ImportError:  # pragma: no cover
    _has_ortools = False

needs_solver = pytest.mark.skipif(
    not _has_ortools, reason="未安装 ortools，跳过自动排班接口测试"
)


@needs_solver
def test_solve_endpoint_returns_schedule(client):
    res = client.post(
        "/api/solve", json={"week_start": "2026-11-02", "days_count": 7}
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["status"] in ("OPTIMAL", "FEASIBLE")
    assert data["week_start"] == "2026-11-02"
    assert data["days"] == 7
    assert len(data["assignments"]) > 0
    assert not data["warnings"]
    # 每条都已序列化成前端友好的扁平结构
    sample = data["assignments"][0]
    assert set(sample) >= {"staff_id", "date", "shift_code", "position_id", "tags"}
    assert isinstance(sample["date"], str)


@needs_solver
def test_solve_endpoint_result_passes_check(client):
    """一键排出来的结果直接送校验应当零问题。"""
    solve = client.post(
        "/api/solve", json={"week_start": "2026-11-09", "days_count": 7}
    ).get_json()
    assert solve["ok"]
    report = client.post(
        "/api/check", json={"assignments": solve["assignments"]}
    ).get_json()
    assert report["ok"] is True, report


@needs_solver
def test_solve_endpoint_honours_days_count(client):
    data = client.post(
        "/api/solve", json={"week_start": "2026-11-16", "days_count": 3}
    ).get_json()
    assert data["ok"]
    dates = sorted({a["date"] for a in data["assignments"]})
    assert len(dates) == 3


@needs_solver
def test_solve_endpoint_uses_days_array_when_no_week_start(client):
    data = client.post(
        "/api/solve",
        json={"days": ["2026-11-23", "2026-11-24", "2026-11-25", "2026-11-26"]},
    ).get_json()
    assert data["ok"]
    assert data["week_start"] == "2026-11-23"
    assert data["days"] == 4


@needs_solver
def test_solve_endpoint_reports_infeasible_without_crashing(client):
    """把诊断组砍到 3 人后求解应返回 ok=False + 说明，而不是 500。"""
    members = _staff_state(client)
    victims = [
        s["id"] for s in members
        if s["group"] == "diagnosis" and not s.get("is_trainee")
    ][3:]
    for vid in victims:
        assert client.delete(f"/api/staff/{vid}").status_code == 200

    res = client.post(
        "/api/solve", json={"week_start": "2026-11-30", "days_count": 7}
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is False
    assert data["warnings"]


def test_solve_endpoint_rejects_bad_week_start(client):
    res = client.post("/api/solve", json={"week_start": "not-a-date"})
    assert res.status_code == 400
    assert "error" in res.get_json()


def test_solve_endpoint_rejects_bad_fixed(client):
    res = client.post(
        "/api/solve",
        json={"week_start": "2026-12-07", "fixed": [{"staff_id": "D01"}]},
    )
    assert res.status_code == 400
    assert "error" in res.get_json()


@needs_solver
def test_solve_endpoint_lock_keeps_fixed_cells(client):
    """勾选「保留改动」时，锁定的格子必须在结果里保持不变。"""
    data = client.post(
        "/api/solve",
        json={
            "week_start": "2026-12-14",
            "days_count": 7,
            "fixed": [
                {"staff_id": "D01", "date": "2026-12-16", "shift_code": "OFF"}
            ],
        },
    ).get_json()
    assert data["ok"], data["warnings"]
    locked = [
        a for a in data["assignments"]
        if a["staff_id"] == "D01" and a["date"] == "2026-12-16"
    ]
    assert len(locked) == 1 and locked[0]["shift_code"] == "OFF"


def test_index_has_solve_controls(client):
    html = client.get("/").get_data(as_text=True)
    for token in (
        "btn-solve", "solve-panel", "solve-start", "solve-days",
        "solve-lock", "solve-run", "solve-cancel", "solve-mask",
    ):
        assert token in html, f"模板缺少 {token}"
