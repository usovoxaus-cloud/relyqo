import re
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.db import Base, get_db
from app.models import (
    User,
    ConsumerEmail,
    PasswordRecoveryToken,
    RecoveryRateLimit,
    AuthSession,
)
from app.security import password_hash, token_hash, verify_password
from app.config import settings
import app.password_recovery as recovery

PASSWORD = "original-test-password"
NEW_PASSWORD = "new-test-password-123"


@pytest.fixture
def setup(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'recovery.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    def database():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = database
    monkeypatch.setattr(recovery, "SessionLocal", factory)
    for key, value in dict(
        resend_api_key="test-only-not-a-real-key",
        recovery_email_from="noreply@example.test",
        public_base_url="https://relyqo.onrender.com",
    ).items():
        monkeypatch.setattr(settings, key, value)
    mailbox = []
    monkeypatch.setattr(recovery, "send_email", lambda *args: mailbox.append(args))
    with factory() as db:
        user = User(
            username="recovery-test",
            password_hash=password_hash(PASSWORD),
            role="CONSUMER",
        )
        db.add(user)
        db.commit()
        uid = user.id
    client = TestClient(app)
    assert (
        client.post(
            "/v1/auth/login", json={"username": "recovery-test", "password": PASSWORD}
        ).status_code
        == 200
    )
    yield client, factory, mailbox, uid
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def last_token(mailbox):
    return re.search(r"#token=([\w-]+)", mailbox[-1][2]).group(1)


def verified(setup):
    client, factory, mailbox, uid = setup
    assert (
        client.post(
            "/v1/auth/recovery-email",
            json={"email": "Person@Example.Test", "current_password": PASSWORD},
        ).status_code
        == 202
    )
    token = last_token(mailbox)
    assert (
        client.post("/v1/auth/verify-email", json={"token": token}).status_code == 200
    )
    with factory() as db:
        for row in db.scalars(select(RecoveryRateLimit)):
            db.delete(row)
        db.commit()
    return client, factory, mailbox, uid


def reset_token(setup):
    client, _, mailbox, _ = setup
    assert (
        client.post(
            "/v1/auth/forgot-password", json={"email": "person@example.test"}
        ).status_code
        == 202
    )
    return last_token(mailbox)


def reset(client, token, password=NEW_PASSWORD):
    return client.post(
        "/v1/auth/reset-password",
        json={"token": token, "new_password": password, "confirm_password": password},
    )


def test_complete_recovery_uses_existing_login_and_revokes_every_session(setup):
    client, factory, mailbox, uid = verified(setup)
    saved_cookie = client.cookies.get("relyqo_session")
    token = reset_token(setup)
    with factory() as db:
        saved = db.get(PasswordRecoveryToken, token_hash(token))
        assert saved and saved.token_hash != token and token not in str(saved.__dict__)
    assert reset(client, token).status_code == 200
    assert client.get("/v1/auth/me").status_code == 401
    with TestClient(app) as other:
        other.cookies.set("relyqo_session", saved_cookie)
        assert other.get("/v1/auth/me").status_code == 401
        assert (
            other.post(
                "/v1/auth/login",
                json={"username": "recovery-test", "password": PASSWORD},
            ).status_code
            == 401
        )
        assert (
            other.post(
                "/v1/auth/login",
                json={"username": "recovery-test", "password": NEW_PASSWORD},
            ).status_code
            == 200
        )
        assert other.post("/v1/auth/logout").status_code == 200
        assert other.get("/v1/auth/me").status_code == 401
    assert reset(client, token).status_code == 400
    with factory() as db:
        assert verify_password(NEW_PASSWORD, db.get(User, uid).password_hash)
        assert all(row.revoked_at for row in db.scalars(select(AuthSession)))
    assert "Пароль RELYQO изменён" in mailbox[-1][1]
    assert NEW_PASSWORD not in str(mailbox)


def test_unknown_address_has_identical_response_and_no_email(setup):
    client, _, mailbox, _ = verified(setup)
    mailbox.clear()
    unknown = client.post(
        "/v1/auth/forgot-password", json={"email": "unknown@example.test"}
    )
    assert mailbox == []
    known = client.post(
        "/v1/auth/forgot-password", json={"email": "person@example.test"}
    )
    assert (known.status_code, known.json()) == (unknown.status_code, unknown.json())
    assert len(mailbox) == 1
    for _ in range(5):
        assert (
            client.post(
                "/v1/auth/forgot-password", json={"email": "person@example.test"}
            ).json()
            == known.json()
        )
    assert len(mailbox) == 3


def test_binding_requires_current_password_and_verification(setup):
    client, factory, mailbox, uid = setup
    assert (
        client.post(
            "/v1/auth/recovery-email",
            json={"email": "person@example.test", "current_password": "wrong-password"},
        ).status_code
        == 401
    )
    assert not mailbox
    assert (
        client.post(
            "/v1/auth/recovery-email",
            json={"email": "person@example.test", "current_password": PASSWORD},
        ).status_code
        == 202
    )
    token = last_token(mailbox)
    with factory() as db:
        assert db.get(ConsumerEmail, uid) is None
    mailbox.clear()
    client.post("/v1/auth/forgot-password", json={"email": "person@example.test"})
    assert not mailbox
    assert (
        client.post("/v1/auth/verify-email", json={"token": token}).status_code == 200
    )
    assert (
        client.post("/v1/auth/verify-email", json={"token": token}).status_code == 400
    )


def test_expired_wrong_purpose_and_password_mismatch_do_not_change_password(setup):
    client, factory, mailbox, uid = verified(setup)
    token = reset_token(setup)
    assert (
        client.post("/v1/auth/verify-email", json={"token": token}).status_code == 400
    )
    assert (
        client.post(
            "/v1/auth/reset-password",
            json={
                "token": token,
                "new_password": NEW_PASSWORD,
                "confirm_password": "other-password",
            },
        ).status_code
        == 422
    )
    with factory() as db:
        db.get(PasswordRecoveryToken, token_hash(token)).expires_at = (
            datetime.utcnow() - timedelta(seconds=1)
        )
        db.commit()
    assert reset(client, token).status_code == 400
    assert reset(client, "x" * 43).status_code == 400
    with factory() as db:
        assert verify_password(PASSWORD, db.get(User, uid).password_hash)


def test_existing_password_change_invalidates_pending_email_and_reset_tokens(setup):
    client, factory, _, uid = verified(setup)
    token = reset_token(setup)
    assert (
        client.post(
            "/v1/auth/change-password",
            json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        ).status_code
        == 200
    )
    assert reset(client, token, "another-password-123").status_code == 400


def test_disabled_and_non_consumer_users_cannot_recover(setup):
    client, factory, mailbox, uid = verified(setup)
    token = reset_token(setup)
    with factory() as db:
        db.get(User, uid).active = False
        db.commit()
    assert reset(client, token).status_code == 400
    mailbox.clear()
    client.post("/v1/auth/forgot-password", json={"email": "person@example.test"})
    assert mailbox == []
    with factory() as db:
        user = db.get(User, uid)
        user.active = True
        user.role = "RELYQO_REVIEWER"
        db.commit()
    client.post("/v1/auth/forgot-password", json={"email": "person@example.test"})
    assert mailbox == []
    assert reset(client, token).status_code == 400


def test_missing_mail_configuration_is_an_honest_global_failure(setup, monkeypatch):
    client, _, mailbox, _ = setup
    monkeypatch.setattr(settings, "resend_api_key", "")
    for address in ["person@example.test", "unknown@example.test"]:
        response = client.post("/v1/auth/forgot-password", json={"email": address})
        assert response.status_code == 503
        assert "временно недоступна" in response.json()["detail"]
    assert not mailbox


def test_email_delivery_failure_invalidates_link_and_does_not_log_secrets(
    setup, monkeypatch, caplog
):
    client, factory, mailbox, uid = verified(setup)

    def fail(*args):
        raise RuntimeError("secret password and token must not be logged")

    monkeypatch.setattr(recovery, "send_email", fail)
    assert (
        client.post(
            "/v1/auth/forgot-password", json={"email": "person@example.test"}
        ).status_code
        == 202
    )
    with factory() as db:
        tokens = list(
            db.scalars(
                select(PasswordRecoveryToken).where(
                    PasswordRecoveryToken.purpose == "reset"
                )
            )
        )
        assert tokens and all(t.consumed_at for t in tokens)
    assert "secret password" not in caplog.text
    assert "delivery failed" in caplog.text


def test_urls_are_fixed_and_reset_pages_have_no_tracking(setup, monkeypatch):
    client, _, mailbox, _ = verified(setup)
    client.post(
        "/v1/auth/forgot-password",
        headers={"Host": "attacker.example"},
        json={"email": "person@example.test"},
    )
    assert "https://relyqo.onrender.com/reset-password#token=" in mailbox[-1][2]
    assert "attacker" not in mailbox[-1][2]
    for path in ["/forgot-password", "/reset-password", "/verify-email"]:
        page = client.get(path)
        assert page.status_code == 200
        assert page.headers["referrer-policy"] == "no-referrer"
        assert "no-store" in page.headers["cache-control"]
        assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
        assert "ads.js" not in page.text and "google" not in page.text.lower()
    for origin in [
        "http://production.example",
        "https://example.test/evil",
        "https://u:p@example.test",
        "https://example.test?redirect=evil",
    ]:
        monkeypatch.setattr(settings, "public_base_url", origin)
        assert (
            client.post(
                "/v1/auth/forgot-password", json={"email": "person@example.test"}
            ).status_code
            == 503
        )


def test_email_already_attached_to_other_user_cannot_be_claimed(setup):
    client, factory, mailbox, uid = setup
    with factory() as db:
        other = User(
            username="other", password_hash=password_hash(PASSWORD), role="CONSUMER"
        )
        db.add(other)
        db.flush()
        db.add(ConsumerEmail(user_id=other.id, email="person@example.test"))
        db.commit()
    client.post(
        "/v1/auth/recovery-email",
        json={"email": "person@example.test", "current_password": PASSWORD},
    )
    assert (
        client.post(
            "/v1/auth/verify-email", json={"token": last_token(mailbox)}
        ).status_code
        == 400
    )
    with factory() as db:
        assert db.get(ConsumerEmail, uid) is None


def test_simultaneous_token_replay_has_only_one_winner(setup):
    verified(setup)
    token = reset_token(setup)

    def attempt(n):
        with TestClient(app) as client:
            return reset(client, token, f"concurrent-password-{n}").status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, [1, 2])) == [200, 400]


def test_ip_rate_limit_and_validation(setup):
    client, _, _, _ = setup
    for i in range(30):
        assert (
            client.post(
                "/v1/auth/forgot-password", json={"email": f"unknown{i}@example.test"}
            ).status_code
            == 202
        )
    assert (
        client.post(
            "/v1/auth/forgot-password", json={"email": "unknown@example.test"}
        ).status_code
        == 429
    )
    assert (
        client.post("/v1/auth/forgot-password", json={"email": "not-email"}).status_code
        == 422
    )


def test_migration_from_0019_preserves_users(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    database_url = f"sqlite:///{tmp_path / 'old-schema.db'}"
    engine = create_engine(database_url)
    new_names = {"consumer_emails", "password_recovery_tokens", "recovery_rate_limits"}
    Base.metadata.create_all(
        engine,
        tables=[
            table
            for table in Base.metadata.sorted_tables
            if table.name not in new_names
        ],
    )
    with sessionmaker(engine)() as db:
        db.add(
            User(
                username="preserved",
                password_hash=password_hash(PASSWORD),
                role="CONSUMER",
            )
        )
        db.commit()
    monkeypatch.setattr(settings, "database_url", database_url)
    config = Config("alembic.ini")
    command.stamp(config, "0019")
    command.upgrade(config, "head")
    assert new_names.issubset(set(inspect(engine).get_table_names()))
    with sessionmaker(engine)() as db:
        assert verify_password(
            PASSWORD,
            db.scalar(select(User).where(User.username == "preserved")).password_hash,
        )
    engine.dispose()


def test_fresh_database_migration(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    database_url = f"sqlite:///{tmp_path / 'fresh-schema.db'}"
    monkeypatch.setattr(settings, "database_url", database_url)
    command.upgrade(Config("alembic.ini"), "head")
    engine = create_engine(database_url)
    assert "consumer_emails" in inspect(engine).get_table_names()
    engine.dispose()


def test_resend_transport_uses_https_and_rejects_redirects(monkeypatch):
    import io
    import json

    monkeypatch.setattr(settings, "resend_api_key", "test-only-key")
    monkeypatch.setattr(settings, "recovery_email_from", "noreply@example.test")
    requests = []

    class Reply(io.BytesIO):
        status = 200

    class Opener:
        def open(self, request, timeout):
            requests.append(request)
            assert timeout == 10
            return Reply(b'{"id":"test-email-id"}')

    monkeypatch.setattr(recovery, "build_opener", lambda handler: Opener())
    recovery.send_email("person@example.test", "Subject", "Test message")
    request = requests[0]
    assert request.full_url == "https://api.resend.com/emails"
    assert request.get_header("Authorization") == "Bearer test-only-key"
    assert json.loads(request.data)["to"] == ["person@example.test"]
    assert (
        recovery.NoMailRedirect().redirect_request(
            None, None, 302, "", {}, "https://attacker.test"
        )
        is None
    )


def test_local_recovery_links_require_explicit_opt_in(monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "http://localhost:8767")
    monkeypatch.setattr(settings, "recovery_allow_local_urls", False)
    with pytest.raises(ValueError):
        recovery.recovery_origin()
    monkeypatch.setattr(settings, "recovery_allow_local_urls", True)
    assert recovery.recovery_origin() == "http://localhost:8767"


def test_binding_bad_password_attempts_are_limited_per_user(setup):
    client, _, mailbox, _ = setup
    body = {"email": "person@example.test", "current_password": "wrong-test-password"}
    for _ in range(3):
        assert client.post("/v1/auth/recovery-email", json=body).status_code == 401
    assert client.post("/v1/auth/recovery-email", json=body).status_code == 429
    assert mailbox == []
