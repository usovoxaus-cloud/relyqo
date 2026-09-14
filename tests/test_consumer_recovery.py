import uuid

from fastapi.testclient import TestClient

from app.db import Base, engine
from app.main import app


def test_consumer_has_one_time_self_service_recovery():
    Base.metadata.create_all(engine)
    username = f"recover-consumer-{uuid.uuid4().hex[:10]}"
    original_password = "consumer-original-123"
    replacement_password = "consumer-recovered-456"
    client = TestClient(app)

    registered = client.post(
        "/v1/consumer/register",
        json={"username": username, "password": original_password},
    )
    assert registered.status_code == 200
    initial_code = registered.json()["recovery_code"]
    assert initial_code.startswith("relyqo-")
    assert registered.json()["recovery_code_warning"] == "SAVE_NOW_SHOWN_ONCE"

    rotated = client.post(
        "/v1/auth/recovery-code",
        json={"current_password": original_password},
    )
    assert rotated.status_code == 200
    rotated_code = rotated.json()["recovery_code"]
    assert rotated_code.startswith("relyqo-")
    assert rotated_code != initial_code

    recovery_client = TestClient(app)
    old_code = recovery_client.post(
        "/v1/auth/recover",
        json={
            "username": username,
            "recovery_code": initial_code,
            "new_password": replacement_password,
        },
    )
    assert old_code.status_code == 401

    recovered = recovery_client.post(
        "/v1/auth/recover",
        json={
            "username": username,
            "recovery_code": rotated_code,
            "new_password": replacement_password,
        },
    )
    assert recovered.status_code == 200
    assert recovered.json()["status"] == "ACCOUNT_RECOVERED"
    assert client.get("/v1/auth/me").status_code == 401

    reused = recovery_client.post(
        "/v1/auth/recover",
        json={
            "username": username,
            "recovery_code": rotated_code,
            "new_password": "consumer-third-password-789",
        },
    )
    assert reused.status_code == 401

    assert TestClient(app).post(
        "/v1/auth/login",
        json={"username": username, "password": original_password},
    ).status_code == 401
    assert TestClient(app).post(
        "/v1/auth/login",
        json={"username": username, "password": replacement_password},
    ).status_code == 200


def test_consumer_recovery_ui_is_visible():
    client = TestClient(app)
    page = client.get("/me")
    recover = client.get("/recover")
    assert page.status_code == 200
    assert recover.status_code == 200
    assert "Восстановить пароль по резервному коду" in page.text
    assert 'id="recoveryCodeForm"' in page.text
    assert 'id="newRecoveryNotice"' in page.text
    assert "Войти в Мой RELYQO" in recover.text
    assert "Для потребителя резервный код показывается при регистрации" in recover.text
