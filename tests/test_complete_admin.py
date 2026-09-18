from datetime import datetime
from hashlib import sha256
from io import BytesIO
import json
from zipfile import ZipFile
from xml.etree import ElementTree as ET

import pytest
from sqlalchemy import select, create_engine
from app.models import (
    User,
    Organization,
    Rating,
    Visit,
    Branch,
    ModerationCase,
    ImprovementAction,
)
from app.backups import unpack_snapshot, restore_snapshot
from app.security import password_hash
import app.admin_workflow as workflow
from test_admin_analytics import PASSWORD, PERIOD, data as shared_data

data = shared_data


def rating(db, org_id, user_id, at, score=9, included=True):
    branch = db.scalar(select(Branch).where(Branch.organization_id == org_id))
    visit = Visit(branch_id=branch.id, verified_at=at)
    db.add(visit)
    db.flush()
    db.add(
        Rating(
            visit_id=visit.id,
            organization_id=org_id,
            consumer_user_id=user_id,
            overall=score,
            food=score,
            service=score,
            cleanliness=score,
            value=score,
            ces=score * 10,
            trust_weight=1,
            included=included,
            created_at=at,
        )
    )


def test_comparison_cohorts_respect_scope_inclusion_and_sources(data):
    client, factory, ids = data
    with factory() as db:
        rating(db, ids["restaurant"], ids["one"], datetime(2026, 8, 30))
        rating(db, ids["restaurant"], ids["two"], datetime(2026, 8, 29), included=False)
        rating(db, ids["clinic"], ids["two"], datetime(2026, 8, 28))
        db.commit()
    d = client.get(
        "/v1/admin/analytics?" + PERIOD + "&entity=org:" + ids["restaurant"]
    ).json()
    assert d["summary"]["respondents"] == 2
    assert (
        d["summary"]["new_respondents"],
        d["summary"]["returning_respondents"],
        d["summary"]["repeat_respondents"],
    ) == (1, 1, 1)
    assert d["comparison"]["period"] == {
        "start": "2026-08-29",
        "end": "2026-08-31",
        "timezone": "UTC",
    }
    assert d["comparison"]["summary"]["included"] == 2
    assert d["comparison"]["delta"]["satisfied_percent"] == -50
    community = client.get(
        "/v1/admin/analytics?"
        + PERIOD
        + "&source=community&entity=org:"
        + ids["restaurant"]
    ).json()
    assert community["summary"]["new_respondents"] == 1
    assert community["summary"]["returning_respondents"] == 0
    assert community["comparison"]["delta"]["satisfied_percent"] is None


def test_excel_is_valid_private_aggregate_workbook_without_formulas(data):
    client, factory, ids = data
    dangerous = '=HYPERLINK("https://example.test","click")'
    with factory() as db:
        db.get(Organization, ids["restaurant"]).name = dangerous
        db.commit()
    r = client.get("/v1/admin/analytics/export.xlsx?" + PERIOD)
    assert r.status_code == 200 and "no-store" in r.headers["cache-control"]
    with ZipFile(BytesIO(r.content)) as archive:
        ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        root = ET.fromstring(archive.read("xl/worksheets/sheet2.xml"))
        assert dangerous in [n.text for n in root.findall(".//m:t", ns)]
        assert root.findall(".//m:f", ns) == []
        assert (
            "private-one@example.test"
            not in b"".join(archive.read(n) for n in archive.namelist()).decode()
        )
    import openpyxl

    book = openpyxl.load_workbook(BytesIO(r.content))
    assert len(book.worksheets) == 4
    assert any(
        cell.value == dangerous and cell.data_type == "s"
        for row in book.worksheets[1]
        for cell in row
    )


def test_notifications_thresholds_read_receipts_and_resolution(data, monkeypatch):
    client, factory, ids = data
    monkeypatch.setattr(workflow, "today", lambda: datetime(2026, 9, 18).date())
    with factory() as db:
        row = ModerationCase(
            case_key="complaint-test",
            kind="COMPLAINT",
            object_key="org:" + ids["restaurant"],
            details="Private complaint",
        )
        db.add(row)
        db.get(Organization, ids["clinic"]).profile_status = "SELF_REGISTERED"
        for i in range(10):
            rating(db, ids["restaurant"], ids["one"], datetime(2026, 9, 6), 9)
            rating(
                db,
                ids["restaurant"],
                ids["one"],
                datetime(2026, 9, 13),
                3 if i < 4 else 9,
            )
        # Excluded feedback and today's partial data must not affect the signal.
        for i in range(20):
            rating(db, ids["clinic"], ids["two"], datetime(2026, 9, 18), 1)
        db.commit()
        case_id = row.id
    d = client.get("/v1/admin/notifications").json()
    assert d["unread"] == 3
    risk = next(r for r in d["items"] if r["kind"] == "SATISFACTION")
    assert (
        risk["current_percent"],
        risk["previous_percent"],
        risk["current_count"],
    ) == (40, 0, 10)
    assert "Private complaint" not in json.dumps(d)
    key = "case:" + case_id
    for _ in range(2):
        assert (
            client.post(
                "/v1/admin/notifications/read", json={"keys": [key]}
            ).status_code
            == 200
        )
    assert client.get("/v1/admin/notifications").json()["unread"] == 2
    with factory() as db:
        db.get(ModerationCase, case_id).status = "DISMISSED"
        db.commit()
    assert len(client.get("/v1/admin/notifications").json()["items"]) == 2
    assert (
        client.post(
            "/v1/admin/notifications/read", json={"keys": ["made-up"]}
        ).status_code
        == 422
    )


def test_actions_baseline_immutable_history_conflicts_and_partial_observation(
    data, monkeypatch
):
    client, factory, ids = data
    monkeypatch.setattr(workflow, "today", lambda: datetime(2026, 9, 18).date())
    body = {
        "title": "Проверить ожидание",
        "recommendation": "Измерить ожидание и проверить новую организацию очереди.",
        "start": "2026-09-01",
        "end": "2026-09-03",
        "entity": "org:" + ids["restaurant"],
    }
    r = client.post("/v1/admin/actions", json=body)
    assert r.status_code == 201, r.text
    action = r.json()
    identifier = action["id"]
    before = action["baseline"]
    assert before["included"] == 4
    assert (
        client.post(
            "/v1/admin/actions/" + identifier,
            json={
                "status": "IN_PROGRESS",
                "note": "Проводим замеры очереди",
                "version": 1,
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/v1/admin/actions/" + identifier,
            json={"status": "DONE", "note": "Проверили и внедрили", "version": 1},
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/v1/admin/actions/" + identifier,
            json={"status": "DONE", "note": "Проверили и внедрили", "version": 2},
        ).status_code
        == 200
    )
    with factory() as db:
        row = db.get(ImprovementAction, identifier)
        row.completed_at = datetime(2026, 9, 16, 12)
        rating(db, ids["restaurant"], ids["one"], datetime(2026, 9, 17), 8)
        rating(db, ids["restaurant"], ids["one"], datetime(2026, 9, 18), 1)
        db.commit()
    d = client.get("/v1/admin/actions/" + identifier + "/result").json()
    assert d["action"]["baseline"] == before
    assert len(d["history"]) == 2
    assert d["after"]["summary"]["included"] == 1
    assert d["measurement"] == {
        "start": "2026-09-17",
        "expected_end": "2026-09-19",
        "complete": False,
        "observed_days": 1,
        "planned_days": 3,
    }
    assert (
        client.post(
            "/v1/admin/actions/" + identifier,
            json={"status": "OPEN", "note": "Изменить опыт", "version": 3},
        ).status_code
        == 409
    )
    assert (
        client.post("/v1/admin/actions", json={**body, "end": "2026-09-18"}).status_code
        == 422
    )


@pytest.mark.parametrize(
    "role",
    ["CONSUMER", "BUSINESS_OWNER", "FREGAT_OWNER", "FREGAT_STAFF", "RELYQO_REVIEWER"],
)
def test_new_admin_routes_reject_all_other_roles(data, role):
    client, factory, ids = data
    with factory() as db:
        db.get(User, ids["admin"]).role = role
        db.commit()
    for url in [
        "/v1/admin/notifications",
        "/v1/admin/actions",
        "/v1/admin/actions/unknown/result",
        "/v1/admin/analytics/export.xlsx",
        "/v1/admin/backups/windows.zip",
    ]:
        assert client.get(url).status_code == 403, url
    for url, body in [
        ("/v1/admin/notifications/read", {"keys": []}),
        ("/v1/admin/backups/client", {"current_password": PASSWORD}),
        ("/v1/admin/backups/client/revoke", {}),
        (
            "/v1/admin/actions",
            {"title": "Action test", "recommendation": "Recommendation test"},
        ),
        (
            "/v1/admin/actions/x",
            {"status": "DONE", "note": "Completed note", "version": 1},
        ),
    ]:
        assert client.post(url, json=body).status_code == 403, url


def test_scoped_backup_export_receipt_restore_and_revoke(data, tmp_path):
    client, factory, ids = data
    response = client.post(
        "/v1/admin/backups/client", json={"current_password": PASSWORD}
    )
    assert response.status_code == 201, response.text
    token = response.json()["token"]
    headers = {"Authorization": "Bearer " + token}
    assert (
        client.get("/v1/admin/operations").json()["local_backups"]["status"]
        == "awaiting_first_backup"
    )
    downloaded = client.get("/v1/admin/backups/windows.zip")
    with ZipFile(BytesIO(downloaded.content)) as archive:
        assert {
            "SETUP.cmd",
            "Setup.ps1",
            "Backup.ps1",
            "server.json",
            "README.txt",
        } == set(archive.namelist())
        assert token.encode() not in b"".join(
            archive.read(n) for n in archive.namelist()
        )
    saved_cookie = client.cookies.get("relyqo_session")
    client.cookies.clear()
    assert client.get("/v1/admin/analytics", headers=headers).status_code == 401
    phrase = "separate-long-backup-password"
    r = client.post(
        "/v1/backup-client/export", headers=headers, json={"passphrase": phrase}
    )
    assert r.status_code == 200, r.text
    assert token.encode() not in r.content
    assert sha256(r.content).hexdigest() == r.headers["X-Backup-SHA256"]
    data = unpack_snapshot(r.content, phrase)
    assert len(data["tables"]["users"]) == 3
    target = create_engine("sqlite:///" + str(tmp_path / "restore.db"))
    restored = restore_snapshot(target, r.content, phrase)
    assert restored["rows"] > 0
    with pytest.raises(ValueError):
        restore_snapshot(target, r.content, phrase)
    assert (
        client.post(
            "/v1/backup-client/receipt", headers=headers, json={"sha256": "0" * 64}
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/v1/backup-client/receipt",
            headers=headers,
            json={"sha256": r.headers["X-Backup-SHA256"]},
        ).status_code
        == 200
    )
    client.cookies.set("relyqo_session", saved_cookie)
    assert (
        client.get("/v1/admin/operations").json()["local_backups"]["status"] == "recent"
    )
    assert client.post("/v1/admin/backups/client/revoke").status_code == 200
    assert (
        client.post(
            "/v1/backup-client/export", headers=headers, json={"passphrase": phrase}
        ).status_code
        == 401
    )
    assert (
        client.get("/v1/admin/operations").json()["local_backups"]["status"]
        == "disabled"
    )


def test_backup_key_invalid_after_password_change_and_unknown_receipt(data):
    client, factory, ids = data
    token = client.post(
        "/v1/admin/backups/client", json={"current_password": PASSWORD}
    ).json()["token"]
    headers = {"Authorization": "Bearer " + token}
    assert (
        client.post(
            "/v1/backup-client/receipt", headers=headers, json={"sha256": "a" * 64}
        ).status_code
        == 409
    )
    with factory() as db:
        user = db.get(User, ids["admin"])
        user.password_hash = password_hash("a-different-long-password")
        db.commit()
    assert (
        client.post(
            "/v1/backup-client/export",
            headers=headers,
            json={"passphrase": "a-long-encryption-passphrase"},
        ).status_code
        == 401
    )
