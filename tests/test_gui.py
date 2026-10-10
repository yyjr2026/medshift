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
    assert len(cfg["staff"]) == 25
    assert len(cfg["shifts"]) == 16
    assert len(cfg["positions"]) == 12
    assert data["current_file"] == "2026-W42.csv"
    assert len(data["assignments"]) == 161
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
