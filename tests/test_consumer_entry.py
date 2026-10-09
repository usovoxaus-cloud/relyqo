from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.consumer_entry import safe_destination
from app.db import Base, SessionLocal, engine
from app.main import app
from app.models import AuthSession, User
from app.security import token_hash
from test_program_structure import account


@pytest.mark.parametrize("path", ["/", "/consumer", "/rate", "/nearby", "/community-rate", "/place", "/rankings", "/me", "/me/rating", "/me/requests", "/notifications"])
def test_guest_sees_separate_entry_before_consumer_pages(path):
    client = TestClient(app)
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 303
    assert parse_qs(urlsplit(response.headers["location"]).query)["return_to"] == [path]
    assert "no-store" in response.headers["cache-control"]
    page = client.get(response.headers["location"])
    assert page.status_code == 200 and 'id="registerForm"' in page.text
    assert 'id="loginForm" hidden' in page.text
    assert "consumerNav" not in page.text and "directoryPanel" not in page.text
    assert "data-consumer-authenticated" not in page.text


def test_registration_login_and_logout_open_the_correct_screen():
    Base.metadata.create_all(engine)
    client = TestClient(app)
    username = "entry-" + uuid4().hex
    response = client.post("/v1/consumer/register", json={"username": username, "password": "fixture-entry-password", "language": "uz"})
    assert response.status_code == 200 and response.json()["recovery_code"]
    assert client.cookies.get("relyqo_session")
    page = client.get("/welcome?lang=uz")
    assert page.url.path == "/consumer" and page.url.params["lang"] == "uz"
    assert 'data-consumer-authenticated="true"' in page.text
    assert 'id="directoryPanel"' in page.text
    assert 'id="loginForm"' not in client.get("/me").text
    assert 'id="directoryPanel"' in client.get("/").text
    assert client.post("/v1/auth/logout").status_code == 200
    assert client.get("/consumer").url.path == "/welcome"
    login = client.post("/v1/auth/login", json={"username": username, "password": "fixture-entry-password"})
    assert login.status_code == 200
    assert client.get("/welcome").url.path == "/consumer"


def test_qr_and_rating_destination_survive_login_redirect():
    client, _ = account("CONSUMER")
    for destination in ["/rate?token=fixture.signed&lang=uz", "/community-rate?object_key=manual%3Afixture&name=Test%20Place", "/me/requests?rating_id=fixture"]:
        guest = TestClient(app).get(destination, follow_redirects=False)
        welcome = client.get(guest.headers["location"], follow_redirects=False)
        assert welcome.status_code == 303
        assert urlsplit(welcome.headers["location"]).path == urlsplit(destination).path
        assert parse_qs(urlsplit(welcome.headers["location"]).query) == parse_qs(urlsplit(destination).query)


@pytest.mark.parametrize("state", ["expired", "revoked", "disabled", "wrong_role"])
def test_invalid_consumer_session_cannot_skip_entry(state):
    client, ids = account("RELYQO_ADMIN" if state == "wrong_role" else "CONSUMER")
    with SessionLocal() as db:
        session = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash(client.cookies.get("relyqo_session"))))
        if state == "expired": session.expires_at = datetime.utcnow() - timedelta(seconds=1)
        if state == "revoked": session.revoked_at = datetime.utcnow()
        if state == "disabled": db.get(User, ids[2]).active = False
        db.commit()
    assert client.get("/consumer").url.path == "/welcome"
    assert client.get("/welcome").status_code == 200
    assert client.get("/admin").status_code == 200
    for path in ["/terms", "/privacy", "/recover", "/forgot-password"]:
        assert TestClient(app).get(path).url.path == path


@pytest.mark.parametrize("value", ["https://evil.test", "//evil.test", "///evil.test", "/\\evil.test", "/consumer/../welcome", "/%2f%2fevil.test", "/welcome", "/admin", "/me/", "/\nconsumer"])
def test_return_destination_never_escapes_or_loops(value):
    assert safe_destination(value) == "/consumer"
