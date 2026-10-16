from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import json
from urllib.error import HTTPError
from urllib.parse import parse_qs

import phonenumbers
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.config import settings
from app.db import Base, get_db
from app.models import (
    AccountPhone,
    AuthSession,
    PhoneChallenge,
    RecoveryRateLimit,
    User,
)
from app.security import password_hash, token_hash, verify_password
from app import phone_recovery as sms

PASSWORD = "test-original-password"
NEW = "test-new-password-123"
PHONE = "+998901234567"
SID = "VE" + "a" * 32


@pytest.fixture(params=["twilio", "eskiz"])
def setup(tmp_path, monkeypatch, request):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'phone.db'}",
        connect_args={"check_same_thread": False, "timeout": 20},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    def database():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = database
    monkeypatch.setattr(sms, "SessionLocal", factory)
    for key, value in dict(
        sms_provider=request.param,
        eskiz_email="sms@example.test",
        eskiz_password="test-only-password",
        eskiz_sender="4546",
        eskiz_message_template="RELYQO: Tasdiqlash kodi {code}. Kodni hech kimga bermang.",
        sms_otp_secret="test-only-otp-secret-32-characters-long",
        twilio_account_sid="AC" + "a" * 32,
        twilio_auth_token="test-only-secret",
        twilio_verify_service_sid="VA" + "b" * 32,
        sms_allowed_regions="UZ,US,GB,DE,TR,JP,CA,KZ",
    ).items():
        monkeypatch.setattr(settings, key, value)
    sent, checks = [], []
    monkeypatch.setattr(sms, "provider_start", lambda phone: sent.append(phone) or SID)
    monkeypatch.setattr(sms.secrets, "randbelow", lambda maximum: 123456)
    monkeypatch.setattr(
        sms.sms_eskiz, "send_code", lambda phone, code: sent.append(phone)
    )

    def check(sid, phone, code):
        checks.append((sid, phone, code))
        return code == "123456"

    monkeypatch.setattr(sms, "provider_check", check)
    with factory() as db:
        user = User(
            username="phone-test",
            password_hash=password_hash(PASSWORD),
            role="CONSUMER",
        )
        db.add(user)
        db.commit()
        uid = user.id
    client = TestClient(app)
    assert (
        client.post(
            "/v1/auth/login", json={"username": "phone-test", "password": PASSWORD}
        ).status_code
        == 200
    )
    yield client, factory, uid, sent, checks
    client.close()
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def clear_limits(factory):
    with factory() as db:
        db.execute(delete(RecoveryRateLimit))
        db.commit()


def bind(setup, phone=PHONE, region="UZ"):
    client, factory, _, sent, _ = setup
    result = client.post(
        "/v1/auth/recovery-phone",
        json={"phone": phone, "region": region, "current_password": PASSWORD},
    )
    assert result.status_code == 202, result.text
    assert sent
    body = {"challenge": result.json()["challenge"], "code": "123456"}
    assert client.post("/v1/auth/verify-phone", json=body).status_code == 200
    clear_limits(factory)
    return body


def request_reset(client, phone=PHONE, region="UZ"):
    response = client.post(
        "/v1/auth/forgot-password-phone", json={"phone": phone, "region": region}
    )
    assert response.status_code == 202, response.text
    return {
        "challenge": response.json()["challenge"],
        "code": "123456",
        "new_password": NEW,
        "confirm_password": NEW,
    }


@pytest.mark.parametrize("region", ["UZ", "US", "GB", "DE", "TR", "JP", "CA", "KZ"])
def test_international_numbers_bind_and_normalize(setup, region):
    example = phonenumbers.example_number_for_type(
        region, phonenumbers.PhoneNumberType.MOBILE
    )
    local = phonenumbers.format_number(example, phonenumbers.PhoneNumberFormat.NATIONAL)
    if settings.sms_provider == "eskiz" and region != "UZ":
        response = setup[0].post(
            "/v1/auth/recovery-phone",
            json={
                "phone": local,
                "region": region,
                "current_password": PASSWORD,
            },
        )
        assert response.status_code == 422 and not setup[3]
        assert setup[0].get("/v1/auth/phone-options").json()["regions"] == [
            {"code": "UZ", "dial_code": "+998"}
        ]
        return
    bind(setup, local, region)
    status = setup[0].get("/v1/auth/recovery-phone").json()
    assert status == {
        "verified": True,
        "phone": phonenumbers.format_number(
            example, phonenumbers.PhoneNumberFormat.E164
        ),
    }


@pytest.mark.parametrize("role", sorted(sms.EMAIL_RECOVERY_ROLES))
def test_roles_can_bind_personal_phone(setup, role):
    with setup[1]() as db:
        db.get(User, setup[2]).role = role
        db.commit()
    bind(setup)


def test_full_reset_revokes_sessions_and_replay(setup):
    client, factory, uid, _, _ = setup
    bind(setup)
    old_cookie = client.cookies.get("relyqo_session")
    body = request_reset(client)
    with factory() as db:
        challenge = db.get(PhoneChallenge, token_hash(body["challenge"]))
        assert challenge and challenge.attempts == 0
        assert "123456" not in {str(v) for v in challenge.__dict__.values()}
        assert challenge.provider == settings.sms_provider
        if settings.sms_provider == "eskiz":
            assert len(challenge.code_digest) == 64
            assert challenge.verification_sid is None
    assert client.post("/v1/auth/reset-password-phone", json=body).status_code == 200
    assert client.get("/v1/auth/me").status_code == 401
    with TestClient(app) as other:
        other.cookies.set("relyqo_session", old_cookie)
        assert other.get("/v1/auth/me").status_code == 401
        assert (
            other.post(
                "/v1/auth/login", json={"username": "phone-test", "password": PASSWORD}
            ).status_code
            == 401
        )
        assert (
            other.post(
                "/v1/auth/login", json={"username": "phone-test", "password": NEW}
            ).status_code
            == 200
        )
    assert client.post("/v1/auth/reset-password-phone", json=body).status_code == 400
    with factory() as db:
        assert verify_password(NEW, db.get(User, uid).password_hash)
        assert all(row.revoked_at for row in db.scalars(select(AuthSession)).all()[:-1])


def test_unknown_number_identical_response_and_no_delivery(setup):
    client, factory, _, sent, _ = setup
    bind(setup)
    known = client.post(
        "/v1/auth/forgot-password-phone", json={"phone": PHONE, "region": "UZ"}
    ).json()
    sent.clear()
    unknown = client.post(
        "/v1/auth/forgot-password-phone",
        json={"phone": "+998901234568", "region": "UZ"},
    ).json()
    assert known.keys() == unknown.keys()
    assert len(known.pop("challenge")) == len(unknown.pop("challenge")) == 43
    assert known == unknown and not sent
    with factory() as db:
        assert (
            db.scalar(
                select(PhoneChallenge).where(PhoneChallenge.phone == "+998901234568")
            )
            is None
        )


def test_unverified_phone_cannot_reset_and_binding_requires_password(setup):
    client, _, _, sent, _ = setup
    assert (
        client.post(
            "/v1/auth/recovery-phone",
            json={"phone": PHONE, "region": "UZ", "current_password": "wrong-password"},
        ).status_code
        == 401
    )
    body = request_reset(client)
    assert not sent
    assert client.post("/v1/auth/reset-password-phone", json=body).status_code == 400


@pytest.mark.parametrize(
    "phone,region",
    [
        ("12345", "UZ"),
        (PHONE, "US"),
        (PHONE + " ext123", "UZ"),
        ("+998;alert(1)", "UZ"),
    ],
)
def test_bad_numbers_never_send(setup, phone, region):
    assert (
        setup[0]
        .post("/v1/auth/forgot-password-phone", json={"phone": phone, "region": region})
        .status_code
        == 422
    )
    assert not setup[3]


def test_wrong_codes_exhaust_persistent_attempts(setup):
    client, factory, _, _, checks = setup
    bind(setup)
    body = request_reset(client)
    checks.clear()
    for _ in range(5):
        assert (
            client.post(
                "/v1/auth/reset-password-phone", json={**body, "code": "000000"}
            ).status_code
            == 400
        )
        clear_limits(factory)
    assert client.post("/v1/auth/reset-password-phone", json=body).status_code == 400
    assert len(checks) == (5 if settings.sms_provider == "twilio" else 0)
    with factory() as db:
        assert db.get(PhoneChallenge, token_hash(body["challenge"])).attempts == 5


@pytest.mark.parametrize("change", ["expired", "password", "phone", "inactive", "role"])
def test_stale_proof_cannot_reset(setup, change):
    client, factory, uid, _, _ = setup
    bind(setup)
    body = request_reset(client)
    with factory() as db:
        user = db.get(User, uid)
        if change == "expired":
            db.get(PhoneChallenge, token_hash(body["challenge"])).expires_at = (
                datetime.utcnow() - timedelta(seconds=1)
            )
        elif change == "password":
            user.password_hash = password_hash("changed-elsewhere")
        elif change == "phone":
            db.get(AccountPhone, uid).phone = "+998901234568"
        elif change == "inactive":
            user.active = False
        else:
            user.role = "DISABLED"
        db.commit()
    assert client.post("/v1/auth/reset-password-phone", json=body).status_code == 400
    with factory() as db:
        assert not verify_password(NEW, db.get(User, uid).password_hash)


def test_bind_proof_cannot_be_used_for_password_reset(setup):
    client, _, _, _, _ = setup
    response = client.post(
        "/v1/auth/recovery-phone",
        json={"phone": PHONE, "region": "UZ", "current_password": PASSWORD},
    )
    body = {
        "challenge": response.json()["challenge"],
        "code": "123456",
        "new_password": NEW,
        "confirm_password": NEW,
    }
    assert client.post("/v1/auth/reset-password-phone", json=body).status_code == 400


def test_other_session_cannot_complete_phone_binding(setup):
    client, factory, _, _, _ = setup
    response = client.post(
        "/v1/auth/recovery-phone",
        json={"phone": PHONE, "region": "UZ", "current_password": PASSWORD},
    )
    with factory() as db:
        db.add(
            User(
                username="other", password_hash=password_hash(PASSWORD), role="CONSUMER"
            )
        )
        db.commit()
    with TestClient(app) as other:
        assert (
            other.post(
                "/v1/auth/login", json={"username": "other", "password": PASSWORD}
            ).status_code
            == 200
        )
        assert (
            other.post(
                "/v1/auth/verify-phone",
                json={"challenge": response.json()["challenge"], "code": "123456"},
            ).status_code
            == 400
        )


def test_send_cooldown_and_existing_phone_uniqueness(setup):
    client, factory, _, sent, _ = setup
    bind(setup)
    sent.clear()
    request_reset(client)
    request_reset(client)
    assert sent == [PHONE]
    clear_limits(factory)
    with factory() as db:
        db.add(
            User(
                username="other", password_hash=password_hash(PASSWORD), role="CONSUMER"
            )
        )
        db.commit()
    sent.clear()
    with TestClient(app) as other:
        other.post("/v1/auth/login", json={"username": "other", "password": PASSWORD})
        response = other.post(
            "/v1/auth/recovery-phone",
            json={"phone": PHONE, "region": "UZ", "current_password": PASSWORD},
        )
        assert response.status_code == 202 and not sent
        assert (
            other.post(
                "/v1/auth/verify-phone",
                json={"challenge": response.json()["challenge"], "code": "123456"},
            ).status_code
            == 400
        )


def test_concurrent_reset_has_one_winner(setup):
    client, factory, uid, _, _ = setup
    bind(setup)
    body = request_reset(client)

    def submit(_):
        with TestClient(app) as other:
            return other.post("/v1/auth/reset-password-phone", json=body).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(submit, range(2))) == [200, 400]
    with factory() as db:
        assert verify_password(NEW, db.get(User, uid).password_hash)


def test_disabled_and_delivery_failure_do_not_leak_secrets(setup, monkeypatch, caplog):
    client, factory, _, _, _ = setup
    bind(setup)

    def broken(*args):
        raise RuntimeError("secret-phone-and-token")

    monkeypatch.setattr(sms, "provider_start", broken)
    monkeypatch.setattr(sms.sms_eskiz, "send_code", broken)
    body = request_reset(client)
    assert client.post("/v1/auth/reset-password-phone", json=body).status_code == 400
    assert "secret-phone-and-token" not in caplog.text
    monkeypatch.setattr(settings, "twilio_auth_token", "")
    monkeypatch.setattr(settings, "eskiz_password", "")
    assert client.get("/v1/auth/phone-options").json()["enabled"] is False
    assert (
        client.post(
            "/v1/auth/forgot-password-phone", json={"phone": PHONE, "region": "UZ"}
        ).status_code
        == 503
    )
    for path in ["/account-phone", "/phone-recovery", "/v1/auth/phone-options"]:
        response = client.get(path)
        assert "no-store" in response.headers["cache-control"]
        assert "test-only-secret" not in response.text


def test_transport_checks_response_identity_and_keeps_credentials_server_side(
    monkeypatch,
):
    monkeypatch.setattr(settings, "sms_provider", "twilio")
    monkeypatch.setattr(settings, "twilio_account_sid", "AC" + "a" * 32)
    monkeypatch.setattr(settings, "twilio_auth_token", "test-only-secret")
    monkeypatch.setattr(settings, "twilio_verify_service_sid", "VA" + "b" * 32)
    monkeypatch.setattr(settings, "sms_allowed_regions", "UZ,GB")
    result = {
        "sid": SID,
        "status": "pending",
        "to": PHONE,
        "service_sid": settings.twilio_verify_service_sid,
        "channel": "sms",
    }
    requests = []

    class Opener:
        def open(self, request, timeout):
            from io import BytesIO

            requests.append(request)
            assert timeout == 10
            return BytesIO(json.dumps(result).encode())

    monkeypatch.setattr(sms, "build_opener", lambda handler: Opener())
    assert sms.provider_start(PHONE) == SID
    assert requests[-1].full_url.endswith("/Verifications")
    assert parse_qs(requests[-1].data.decode()) == {"To": [PHONE], "Channel": ["sms"]}
    result["status"] = "approved"
    assert sms.provider_check(SID, PHONE, "123456")
    assert requests[-1].full_url.endswith("/VerificationCheck")
    assert parse_qs(requests[-1].data.decode())["VerificationSid"] == [SID]
    result["to"] = "+998901234568"
    assert not sms.provider_check(SID, PHONE, "123456")
    assert (
        sms.NoMailRedirect().redirect_request(
            None, None, 302, "", {}, "https://evil.test"
        )
        is None
    )


@pytest.mark.parametrize("status", [400, 404, 429])
def test_provider_missing_or_expired_verification_is_not_approved(monkeypatch, status):
    def fail(*args):
        raise HTTPError("https://verify.twilio.com", status, "test", {}, None)

    monkeypatch.setattr(sms, "provider_request", fail)
    assert not sms.provider_check(SID, PHONE, "123456")


def test_upgrade_preserves_users_and_adds_phone_tables(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    database_url = f"sqlite:///{tmp_path / 'upgrade.db'}"
    engine = create_engine(database_url)
    new_tables = {"account_phones", "phone_challenges"}
    Base.metadata.create_all(
        engine,
        tables=[
            table
            for table in Base.metadata.sorted_tables
            if table.name not in new_tables
        ],
    )
    with sessionmaker(engine)() as db:
        db.add(
            User(
                username="preserved-phone-migration",
                role="CONSUMER",
                password_hash=password_hash(PASSWORD),
            )
        )
        db.commit()
    monkeypatch.setattr(settings, "database_url", database_url)
    config = Config("alembic.ini")
    command.stamp(config, "0031")
    command.upgrade(config, "head")
    assert new_tables.issubset(inspect(engine).get_table_names())
    with sessionmaker(engine)() as db:
        assert verify_password(PASSWORD, db.scalar(select(User)).password_hash)
    command.downgrade(config, "0031")
    assert not new_tables.intersection(inspect(engine).get_table_names())
    assert "users" in inspect(engine).get_table_names()
    engine.dispose()


def test_global_budget_blocks_send_without_changing_public_response(setup):
    client, factory, _, sent, _ = setup
    bind(setup)
    sent.clear()
    with factory() as db:
        sms.limited(db, "budget-hour", "all", 100)
        counter = db.scalar(select(RecoveryRateLimit))
        counter.count = 100
        db.commit()
    body = request_reset(client)
    assert not sent
    assert client.post("/v1/auth/reset-password-phone", json=body).status_code == 400


def test_unconfirmed_replacement_keeps_existing_phone(setup):
    client, factory, uid, _, _ = setup
    bind(setup)
    result = client.post(
        "/v1/auth/recovery-phone",
        json={"phone": "+998901234568", "region": "UZ", "current_password": PASSWORD},
    )
    assert result.status_code == 202
    assert client.get("/v1/auth/recovery-phone").json()["phone"] == PHONE
    assert (
        client.post(
            "/v1/auth/verify-phone",
            json={"challenge": result.json()["challenge"], "code": "000000"},
        ).status_code
        == 400
    )
    with factory() as db:
        assert db.get(AccountPhone, uid).phone == PHONE


def test_switching_provider_rejects_outstanding_proof(setup, monkeypatch):
    client = setup[0]
    bind(setup)
    body = request_reset(client)
    monkeypatch.setattr(
        settings,
        "sms_provider",
        "twilio" if settings.sms_provider == "eskiz" else "eskiz",
    )
    assert client.post("/v1/auth/reset-password-phone", json=body).status_code == 400


def test_eskiz_secret_rotation_rejects_outstanding_proof(setup, monkeypatch):
    client, factory, _, _, _ = setup
    monkeypatch.setattr(settings, "sms_provider", "eskiz")
    bind(setup)
    body = request_reset(client)
    monkeypatch.setattr(
        settings, "sms_otp_secret", "rotated-test-secret-at-least-32-characters"
    )
    assert client.post("/v1/auth/reset-password-phone", json=body).status_code == 400
    clear_limits(factory)
    body = request_reset(client)
    assert client.post("/v1/auth/reset-password-phone", json=body).status_code == 200
