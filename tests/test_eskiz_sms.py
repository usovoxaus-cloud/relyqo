from datetime import datetime, timedelta
from io import BytesIO
import json
from urllib.error import HTTPError
from urllib.parse import parse_qs

import pytest
from sqlalchemy import create_engine, inspect, text

from app.config import settings
from app.models import PhoneChallenge
from app import phone_recovery as recovery
from app import sms_eskiz as eskiz


@pytest.fixture
def configured(monkeypatch):
    for name, value in {
        "sms_provider": "eskiz",
        "sms_allowed_regions": "UZ,US,KZ",
        "eskiz_email": "test@example.test",
        "eskiz_password": "test-only-password",
        "eskiz_sender": "4546",
        "eskiz_message_template": "RELYQO: Tasdiqlash kodi {code}. Kodni hech kimga bermang.",
        "sms_otp_secret": "independent-test-secret-at-least-32-characters",
    }.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(eskiz, "_token", "")
    monkeypatch.setattr(eskiz, "_expires", 0)
    monkeypatch.setattr(eskiz, "_credentials_digest", "")


def test_transport_auth_cache_exact_recipient_and_template(configured, monkeypatch):
    requests = []

    class Opener:
        def open(self, request, timeout):
            requests.append(request)
            assert timeout == 10
            assert request.full_url.startswith("https://notify.eskiz.uz/api/")
            data = (
                {"data": {"token": "test-token-abcdefghijklmnopqrstuvwxyz"}}
                if request.full_url.endswith("auth/login")
                else {"id": "provider-message-id", "status": "waiting"}
            )
            return BytesIO(json.dumps(data).encode())

    monkeypatch.setattr(eskiz, "build_opener", lambda handler: Opener())
    eskiz.send_code("+998901234567", "012345")
    eskiz.send_code("+998901234568", "654321")
    assert len(requests) == 3
    assert parse_qs(requests[0].data.decode()) == {
        "email": [settings.eskiz_email],
        "password": [settings.eskiz_password],
    }
    assert requests[0].get_header("Authorization") is None
    assert (
        requests[1].get_header("Authorization")
        == "Bearer test-token-abcdefghijklmnopqrstuvwxyz"
    )
    assert parse_qs(requests[1].data.decode()) == {
        "mobile_phone": ["998901234567"],
        "message": ["RELYQO: Tasdiqlash kodi 012345. Kodni hech kimga bermang."],
        "from": ["4546"],
    }
    assert (
        eskiz.NoMailRedirect().redirect_request(
            None, None, 302, "", {}, "https://evil.test"
        )
        is None
    )


@pytest.mark.parametrize(
    "name,value",
    [
        ("eskiz_email", ""),
        ("eskiz_password", ""),
        ("sms_otp_secret", "short"),
        ("eskiz_message_template", "no placeholder"),
        ("eskiz_message_template", "{code} {code}"),
        ("eskiz_message_template", "{code}" + "a" * 155),
        ("eskiz_message_template", "Код {code}"),
        ("eskiz_sender", "evil\r\nheader"),
        ("sms_allowed_regions", "US"),
        ("sms_provider", "typo"),
    ],
)
def test_invalid_settings_disable_sms(configured, monkeypatch, name, value):
    monkeypatch.setattr(settings, name, value)
    assert recovery.configured() is False


@pytest.mark.parametrize(
    "result",
    [
        {},
        {"id": "id", "status": "failed"},
        {"status": "waiting"},
        {"id": 123, "status": "waiting"},
    ],
)
def test_rejected_or_malformed_send_is_not_accepted(configured, monkeypatch, result):
    monkeypatch.setattr(eskiz, "access_token", lambda: "test-token")
    monkeypatch.setattr(eskiz, "request", lambda *args: result)
    with pytest.raises(ValueError):
        eskiz.send_code("+998901234567", "123456")


@pytest.mark.parametrize(
    "phone,code",
    [
        ("+14155552671", "123456"),
        ("+998901234567", "12345"),
        ("+998901234567", "abcdef"),
    ],
)
def test_invalid_destination_or_code_never_authenticates(
    configured, monkeypatch, phone, code
):
    monkeypatch.setattr(
        eskiz, "access_token", lambda: pytest.fail("must not authenticate")
    )
    with pytest.raises(ValueError):
        eskiz.send_code(phone, code)


@pytest.mark.parametrize("status", [401, 429, 500])
def test_send_errors_are_not_retried(configured, monkeypatch, status):
    calls = []
    monkeypatch.setattr(eskiz, "_token", "cached-test-token")
    monkeypatch.setattr(eskiz, "access_token", lambda: "cached-test-token")

    def fail(*args):
        calls.append(args[0])
        raise HTTPError("https://notify.eskiz.uz", status, "test", {}, None)

    monkeypatch.setattr(eskiz, "request", fail)
    with pytest.raises(HTTPError):
        eskiz.send_code("+998901234567", "123456")
    assert calls == ["message/sms/send"]
    assert bool(eskiz._token) == (status != 401)


def test_digest_bound_to_challenge_and_server_secret(configured, monkeypatch):
    challenge = PhoneChallenge(
        token_hash="a" * 64,
        user_id="test-user",
        phone="+998901234567",
        purpose="reset",
        password_fingerprint="b" * 64,
    )
    digest = recovery.otp_digest(challenge, "123456")
    assert len(digest) == 64 and "123456" not in digest
    for field, value in [
        ("token_hash", "c" * 64),
        ("user_id", "other"),
        ("phone", "+998901234568"),
        ("purpose", "bind"),
        ("password_fingerprint", "d" * 64),
    ]:
        before = getattr(challenge, field)
        setattr(challenge, field, value)
        assert recovery.otp_digest(challenge, "123456") != digest
        setattr(challenge, field, before)
    monkeypatch.setattr(
        settings, "sms_otp_secret", "another-independent-key-at-least-32-characters"
    )
    assert recovery.otp_digest(challenge, "123456") != digest


def test_upgrade_0032_preserves_legacy_challenge(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config

    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    config = Config("alembic.ini")
    command.upgrade(config, "0032")
    engine = create_engine(url)
    # Legacy 0001 uses current metadata on fresh DBs; reproduce the actual 0032 schema.
    with engine.begin() as db:
        db.execute(text("ALTER TABLE phone_challenges DROP COLUMN code_digest"))
        db.execute(text("ALTER TABLE phone_challenges DROP COLUMN provider"))
        db.execute(
            text(
                "INSERT INTO phone_challenges (token_hash,user_id,phone,purpose,password_fingerprint,verification_sid,expires_at,attempts) VALUES (:token,'existing-user','+998901234567','reset',:fingerprint,:sid,:expires,2)"
            ),
            {
                "token": "a" * 64,
                "fingerprint": "b" * 64,
                "sid": "VE" + "c" * 32,
                "expires": datetime.utcnow() + timedelta(minutes=10),
            },
        )
    command.upgrade(config, "head")
    with engine.connect() as db:
        row = db.execute(
            text(
                "SELECT provider,code_digest,attempts,verification_sid FROM phone_challenges"
            )
        ).one()
        assert tuple(row) == ("twilio", None, 2, "VE" + "c" * 32)
    command.downgrade(config, "0032")
    assert "provider" not in {
        c["name"] for c in inspect(engine).get_columns("phone_challenges")
    }
    with engine.connect() as db:
        assert db.scalar(text("SELECT count(*) FROM phone_challenges")) == 1
    engine.dispose()
