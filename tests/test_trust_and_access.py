"""End-to-end business rules for the trust release, using isolated databases."""

from datetime import datetime, timedelta
from io import BytesIO
import base64
import json
import re

import pytest
from cryptography.exceptions import InvalidTag
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.main import app
from app.db import Base, get_db
from app.models import (
    Branch,
    CommunityRating,
    FeedbackSignal,
    MailDelivery,
    ManualPlace,
    ModerationCase,
    Organization,
    RatingPhoto,
    User,
)
from app.security import password_hash
from app.config import settings
from app.backups import create_snapshot, restore_snapshot, unpack_snapshot
from app.feedback import photo_digest
import app.password_recovery as recovery
import app.operations as operations

PASSWORD = "trust-test-password-2026"
PHRASE = "separate-backup-passphrase-2026"


@pytest.fixture
def trust(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'source.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    def database():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = database
    monkeypatch.setattr(recovery, "SessionLocal", factory)
    monkeypatch.setattr(operations, "SessionLocal", factory)
    monkeypatch.setattr(settings, "openai_api_key", None)
    monkeypatch.setattr(settings, "resend_api_key", "test-not-real")
    monkeypatch.setattr(settings, "recovery_email_from", "noreply@example.test")
    monkeypatch.setattr(settings, "public_base_url", "https://relyqo.onrender.com")
    mailbox = []
    monkeypatch.setattr(
        recovery, "send_email", lambda *args: mailbox.append(args) or "provider-test-id"
    )
    monkeypatch.setattr(
        operations,
        "send_email",
        lambda *args: mailbox.append(args) or "provider-test-id",
    )
    with factory() as db:
        admin = User(
            username="trust-admin",
            role="RELYQO_ADMIN",
            password_hash=password_hash(PASSWORD),
        )
        consumer = User(
            username="trust-user",
            role="CONSUMER",
            password_hash=password_hash(PASSWORD),
        )
        org = Organization(name="Trust organization", category="RESTAURANT")
        place = ManualPlace(
            identity_hash="test-hash",
            name="User place",
            category="OTHER",
            description="A test place",
            address="Test street",
            city="Tashkent",
            country_code="UZ",
            latitude=41,
            longitude=69,
            created_by_hash="test",
        )
        db.add_all([admin, consumer, org, place])
        db.flush()
        branch = Branch(organization_id=org.id, name="Test branch", active=True)
        db.add(branch)
        db.commit()
        ids = {
            "admin": admin.id,
            "consumer": consumer.id,
            "org": org.id,
            "branch": branch.id,
            "place": place.id,
        }

    def client(username):
        c = TestClient(app)
        assert (
            c.post(
                "/v1/auth/login", json={"username": username, "password": PASSWORD}
            ).status_code
            == 200
        )
        return c

    yield client("trust-admin"), client("trust-user"), factory, ids, mailbox, engine
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def rating_body(trust, **changes):
    body = {
        "object_key": "relyqo:" + trust[3]["branch"],
        "source": "RELYQO_PARTNER",
        "category": "RESTAURANT",
        "overall": 3,
        "quality": 4,
        "service": 3,
        "cleanliness": 5,
        "value": 4,
    }
    return {**body, **changes}


def test_registration_email_verification_and_login_alias(trust):
    _, _, factory, _, mailbox, _ = trust
    c = TestClient(app)
    r = c.post(
        "/v1/consumer/register",
        json={
            "username": "mail-trust",
            "password": PASSWORD,
            "email": "New@Example.Test",
            "language": "uz",
        },
    )
    assert r.status_code == 200 and r.json()["email_verification_requested"]
    assert "tasdiqlang" in mailbox[-1][1] and "?lang=uz#token=" in mailbox[-1][2]
    assert (
        TestClient(app)
        .post(
            "/v1/auth/login",
            json={"username": "new@example.test", "password": PASSWORD},
        )
        .status_code
        == 401
    )
    token = re.search(r"#token=([\w-]+)", mailbox[-1][2]).group(1)
    assert c.post("/v1/auth/verify-email", json={"token": token}).status_code == 200
    assert (
        TestClient(app)
        .post(
            "/v1/auth/login",
            json={"username": "new@example.test", "password": PASSWORD},
        )
        .status_code
        == 200
    )
    with factory() as db:
        assert db.scalar(select(MailDelivery.status)) == "ACCEPTED"


def test_invalid_email_does_not_create_user(trust):
    c = TestClient(app)
    r = c.post(
        "/v1/consumer/register",
        json={"username": "bad-email", "password": PASSWORD, "email": "broken"},
    )
    assert r.status_code == 422 and PASSWORD not in r.text
    with trust[2]() as db:
        assert not db.scalar(select(User).where(User.username == "bad-email"))


def test_reasons_are_private_and_aggregated_without_comment(trust):
    admin, consumer, _, _, _, _ = trust
    secret = "Private text with person@example.test"
    r = consumer.post(
        "/v1/community-ratings",
        json=rating_body(
            trust, reasons=["LONG_WAIT", "LONG_WAIT", "UNCLEAR_PRICE"], comment=secret
        ),
    )
    assert r.status_code == 200
    assert secret not in r.text
    detail = consumer.get("/v1/consumer/ratings/" + r.json()["rating_id"]).json()
    assert detail["feedback"]["reasons"] == ["LONG_WAIT", "UNCLEAR_PRICE"]
    assert detail["feedback"]["comment"] == secret
    report = admin.get("/v1/admin/analytics?source=community").json()
    assert {r["code"]: r["count"] for r in report["summary"]["reasons"]} == {
        "LONG_WAIT": 1,
        "UNCLEAR_PRICE": 1,
    }
    assert secret not in json.dumps(report)
    feed = admin.get("/v1/admin/control/feedback").json()
    assert feed["items"][0]["rating"]["comment"] == secret
    assert consumer.get("/v1/admin/control/feedback").status_code == 403
    public = TestClient(app).get(
        "/v1/community-ratings/summary",
        params={"object_key": rating_body(trust)["object_key"]},
    )
    assert secret not in public.text
    assert (
        consumer.post(
            "/v1/community-ratings", json=rating_body(trust, reasons=["UNKNOWN"])
        ).status_code
        == 422
    )


def test_duplicate_photo_creates_private_signal_without_changing_score(trust):
    admin, c, factory, ids, _, _ = trust
    stream = BytesIO()
    Image.new("RGB", (4, 4), "blue").save(stream, format="PNG")
    photo = "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode()
    first = c.post(
        "/v1/community-ratings", json=rating_body(trust, photo_data_url=photo)
    )
    assert first.status_code == 200
    second = c.post(
        "/v1/community-ratings",
        json=rating_body(
            trust,
            object_key="manual:" + ids["place"],
            source="MANUAL",
            category="OTHER",
            photo_data_url=photo,
        ),
    )
    assert second.status_code == 200
    assert "signals" not in second.text
    cases = admin.get("/v1/admin/control/cases").json()["items"]
    assert len(cases) == 1 and "изображение" in cases[0]["details"]
    assert cases[0]["rating"]["included"] is True
    assert c.get("/v1/admin/control/cases").status_code == 403
    assert c.get(cases[0]["photo_url"]).status_code == 403
    assert admin.get(cases[0]["photo_url"]).status_code == 200
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(FeedbackSignal)) == 2


def test_photo_hash_ignores_file_metadata():
    from PIL.PngImagePlugin import PngInfo

    im = Image.new("RGB", (4, 4), "red")
    a = BytesIO()
    b = BytesIO()
    info = PngInfo()
    info.add_text("caption", "different")
    im.save(a, format="PNG")
    im.save(b, format="PNG", pnginfo=info)
    assert a.getvalue() != b.getvalue()
    assert photo_digest(a.getvalue()) == photo_digest(b.getvalue())


def test_reject_community_removes_from_summary_and_allows_appeal(trust):
    admin, c, factory, ids, _, _ = trust
    r = c.post("/v1/community-ratings", json=rating_body(trust)).json()
    rid = r["rating_id"]
    with factory() as db:
        case = ModerationCase(
            case_key="manual-test",
            kind="SIGNAL",
            object_key="relyqo:" + ids["branch"],
            rating_id=rid,
            rating_type="COMMUNITY",
            details=json.dumps({"signals": ["RATING_BURST"]}),
        )
        db.add(case)
        db.commit()
        cid = case.id
    endpoint = f"/v1/admin/control/cases/{cid}/decision"
    decision = {
        "decision": "REJECT",
        "note": "Confirmed test evidence from administrator",
    }
    assert c.post(endpoint, json=decision).status_code == 403
    assert admin.post(endpoint, json=decision).status_code == 200
    assert admin.post(endpoint, json=decision).status_code == 409
    summary = c.get(
        "/v1/community-ratings/summary",
        params={"object_key": "relyqo:" + ids["branch"]},
    ).json()
    assert summary["rating_count"] == 0
    report = admin.get("/v1/admin/analytics?source=community").json()
    assert report["summary"]["included"] == 0 and report["summary"]["excluded"] == 1
    appeal = c.post(
        "/v1/consumer/complaints",
        json={
            "object_key": "relyqo:" + ids["branch"],
            "rating_id": rid,
            "message": "Please reconsider the documented visit.",
        },
    )
    assert appeal.status_code == 201
    assert len(c.get("/v1/consumer/complaints").json()["items"]) == 1
    assert (
        admin.post(
            "/v1/admin/control/cases/" + appeal.json()["id"] + "/decision",
            json={
                "decision": "APPROVE",
                "note": "Evidence reviewed; original rating is valid.",
            },
        ).status_code
        == 200
    )
    assert (
        c.get(
            "/v1/community-ratings/summary",
            params={"object_key": "relyqo:" + ids["branch"]},
        ).json()["rating_count"]
        == 1
    )
    assert (
        c.post(
            "/v1/consumer/complaints",
            json={
                "object_key": "relyqo:" + ids["branch"],
                "rating_id": rid,
                "message": "Cannot appeal an included rating.",
            },
        ).status_code
        == 422
    )


def test_plain_complaint_can_only_be_closed_with_answer(trust):
    admin, c, _, ids, _, _ = trust
    r = c.post(
        "/v1/consumer/complaints",
        json={
            "object_key": "manual:" + ids["place"],
            "message": "Address appears incorrect; please verify.",
        },
    )
    assert r.status_code == 201
    path = "/v1/admin/control/cases/" + r.json()["id"] + "/decision"
    assert (
        admin.post(
            path,
            json={
                "decision": "REJECT",
                "note": "Cannot change a rating without a rating.",
            },
        ).status_code
        == 422
    )
    assert (
        admin.post(
            path,
            json={
                "decision": "DISMISS",
                "note": "The location has been reviewed by the administrator.",
            },
        ).status_code
        == 200
    )
    assert "reviewed" in c.get("/v1/consumer/complaints").json()["items"][0]["answer"]
    assert TestClient(app).get("/v1/consumer/complaints").status_code == 401


@pytest.mark.parametrize(
    "role",
    ["CONSUMER", "BUSINESS_OWNER", "FREGAT_OWNER", "FREGAT_STAFF", "RELYQO_REVIEWER"],
)
def test_all_nonadmins_denied_control_backup_and_operations(trust, role):
    _, c, factory, ids, _, _ = trust
    with factory() as db:
        db.get(User, ids["consumer"]).role = role
        db.commit()
    for path in [
        "/v1/admin/control/cases",
        "/v1/admin/control/feedback",
        "/v1/admin/operations",
    ]:
        assert c.get(path).status_code == 403
    assert (
        c.post(
            "/v1/admin/backups/export",
            json={
                "current_password": PASSWORD,
                "passphrase": PHRASE,
                "confirm_passphrase": PHRASE,
            },
        ).status_code
        == 403
    )


def test_snapshot_roundtrip_and_overwrite_protection(trust, tmp_path):
    _, c, factory, ids, _, engine = trust
    image = BytesIO()
    Image.new("RGB", (2, 2), "red").save(image, format="PNG")
    c.post(
        "/v1/community-ratings",
        json=rating_body(
            trust,
            reasons=["LONG_WAIT"],
            comment="Preserve this comment",
            photo_data_url="data:image/png;base64,"
            + base64.b64encode(image.getvalue()).decode(),
        ),
    )
    raw = create_snapshot(engine, PHRASE)
    assert b"Preserve this comment" not in raw and PASSWORD.encode() not in raw
    assert unpack_snapshot(raw, PHRASE)["format"] == 1
    with pytest.raises(InvalidTag):
        unpack_snapshot(raw, PHRASE + "wrong")
    with pytest.raises(InvalidTag):
        unpack_snapshot(raw[:-1] + bytes([raw[-1] ^ 1]), PHRASE)
    target = create_engine(f"sqlite:///{tmp_path / 'restored.db'}")
    result = restore_snapshot(target, raw, PHRASE)
    assert result["rows"] > 0
    with Session(target) as db:
        assert db.get(User, ids["consumer"]).username == "trust-user"
        assert db.scalar(select(CommunityRating.comment)) == "Preserve this comment"
        assert db.scalar(select(RatingPhoto.image_data)) == image.getvalue()
    with pytest.raises(ValueError, match="empty"):
        restore_snapshot(target, raw, PHRASE)
    target.dispose()


def test_backup_requires_reauthentication_and_matching_passwords(trust):
    admin, _, _, _, _, _ = trust
    body = {
        "current_password": "wrong-password",
        "passphrase": PHRASE,
        "confirm_passphrase": PHRASE,
    }
    assert admin.post("/v1/admin/backups/export", json=body).status_code == 401
    body["current_password"] = PASSWORD
    body["confirm_passphrase"] = PHRASE + "x"
    assert admin.post("/v1/admin/backups/export", json=body).status_code == 422
    body["confirm_passphrase"] = PHRASE
    r = admin.post("/v1/admin/backups/export", json=body)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert unpack_snapshot(r.content, PHRASE)["tables"]["users"]


def test_uzbek_error_and_language_persistence(trust):
    admin, c, factory, ids, _, _ = trust
    c.cookies.set("relyqo_language", "uz")
    r = c.get("/v1/admin/operations")
    assert r.status_code == 403 and not re.search("[А-Яа-я]", r.json()["detail"])
    assert r.headers["content-language"] == "uz"
    assert c.post("/v1/auth/language", json={"language": "uz"}).status_code == 200
    with factory() as db:
        assert db.get(User, ids["consumer"]).language == "uz"
    r = c.post("/v1/auth/login", json={"password": "do-not-reflect-this"})
    assert r.status_code == 422 and "do-not-reflect-this" not in r.text
    assert not re.search("[А-Яа-я]", r.json()["detail"])


def test_signal_expiry_burst_and_same_browser_explanation(trust):
    from app.feedback import record_signals

    _, _, factory, ids, _, _ = trust
    with factory() as db:
        for i in range(8):
            u = User(username=f"signal-{i}", role="CONSUMER", password_hash="test-only")
            db.add(u)
            db.flush()
            r = CommunityRating(
                object_key="manual:" + ids["place"],
                source="MANUAL",
                category="OTHER",
                rater_hash=str(i),
                consumer_user_id=u.id,
                overall=9,
                quality=9,
                service=9,
                cleanliness=9,
                value=9,
                community_score=90,
            )
            db.add(r)
            db.flush()
            signals = record_signals(
                db, r, "COMMUNITY", r.object_key, "same-signed-cookie"
            )
            if i == 2:
                assert "SHARED_BROWSER" in signals
            assert r.included
        assert "RATING_BURST" in signals
        assert db.scalar(select(FeedbackSignal.device_hash)) != "same-signed-cookie"
        old = FeedbackSignal(
            rating_id="old-rating",
            rating_type="COMMUNITY",
            object_key="old",
            created_at=datetime.utcnow() - timedelta(days=31),
        )
        db.add(old)
        db.flush()
        r = CommunityRating(
            object_key="manual:" + ids["place"],
            source="MANUAL",
            category="OTHER",
            rater_hash="next",
            overall=1,
            quality=1,
            service=1,
            cleanliness=1,
            value=1,
            community_score=10,
        )
        db.add(r)
        db.flush()
        record_signals(db, r, "COMMUNITY", r.object_key)
        assert not db.get(FeedbackSignal, old.id)


def test_incident_notifies_only_verified_admin_and_is_throttled(trust):
    from app.models import ConsumerEmail, OperationsEvent

    _, _, factory, ids, mailbox, _ = trust
    with factory() as db:
        db.add_all(
            [
                ConsumerEmail(user_id=ids["admin"], email="admin@example.test"),
                ConsumerEmail(user_id=ids["consumer"], email="consumer@example.test"),
            ]
        )
        db.commit()
    operations.report_incident()
    operations.report_incident()
    assert len(mailbox) == 1 and mailbox[0][0] == "admin@example.test"
    assert PASSWORD not in mailbox[0][2] and "nosozlik" in mailbox[0][1]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(OperationsEvent)) == 1


def test_trust_migration_preserves_old_ratings_and_defaults(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    url = f"sqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    config = Config("alembic.ini")
    command.upgrade(config, "0022")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id,username,password_hash,role,active,failed_login_attempts,created_at) VALUES ('old-user','old-user','old-hash','CONSUMER',1,0,CURRENT_TIMESTAMP)"
            )
        )
        # 0001 imports current metadata on fresh installs; explicitly emulate the deployed schema.
        for table, columns in {
            "community_ratings": ["comment", "reasons_json", "included", "status"],
            "ratings": ["comment", "reasons_json"],
            "users": ["language"],
        }.items():
            for column in columns:
                from sqlalchemy import inspect

                if column in {
                    c["name"] for c in inspect(connection).get_columns(table)
                }:
                    connection.execute(
                        text(f"ALTER TABLE {table} DROP COLUMN {column}")
                    )
        connection.execute(
            text(
                "INSERT INTO community_ratings (id,object_key,source,category,overall,quality,service,cleanliness,value,community_score,rater_hash,consumer_user_id,created_at) VALUES ('old-rating','manual:old-place','MANUAL_PLACE','OTHER',3,4,5,6,7,4.8,'old-rater','old-user',CURRENT_TIMESTAMP)"
            )
        )
    command.upgrade(config, "head")
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT overall,comment,reasons_json,included,status FROM community_ratings WHERE id='old-rating'"
            )
        ).one()
        assert tuple(row) == (3, None, "[]", 1, "ACCEPTED")
        assert (
            connection.scalar(
                text("SELECT password_hash FROM users WHERE id='old-user'")
            )
            == "old-hash"
        )
        assert (
            connection.scalar(text("SELECT language FROM users WHERE id='old-user'"))
            == "ru"
        )
    engine.dispose()
