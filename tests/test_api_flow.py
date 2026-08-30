from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.db import Base, SessionLocal, engine
from app.main import app
from app.models import Branch, Organization, User, VisitToken
from app.security import create_token, password_hash, token_hash, verify_password
from app.config import settings
import uuid
from urllib.parse import parse_qs, urlsplit

OWNER_TEST_PASSWORD = "owner-test-password-123"
REVIEW_TEST_PASSWORD = "review-test-password-123"


def test_qr_rating_score_flow():
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        org = Organization(name="Flow Test")
        db.add(org)
        db.flush()
        branch = Branch(organization_id=org.id, name="Main")
        db.add(branch)
        db.flush()
        token, _ = create_token(branch.id)
        db.add(
            VisitToken(
                branch_id=branch.id,
                token_hash=token_hash(token),
                expires_at=datetime.utcnow() + timedelta(hours=1),
            )
        )
        db.commit()
        org_id = org.id
    client = TestClient(app)
    verified = client.post("/v1/visits/verify-token", json={"token": token})
    assert verified.status_code == 200
    rated = client.post(
        "/v1/ratings",
        json={
            "visit_id": verified.json()["visit_id"],
            "overall": 10,
            "food": 8,
            "service": 8,
            "cleanliness": 8,
            "value": 8,
        },
    )
    assert rated.status_code == 200
    assert rated.json()["relyqo_score"] == 88.0
    assert (
        client.post("/v1/visits/verify-token", json={"token": token}).status_code == 409
    )
    public = client.get(f"/v1/organizations/{org_id}/score")
    assert public.json()["calculation"] == "deterministic_weighted_ces_v1"


def test_demo_visit_url():
    Base.metadata.create_all(engine)
    response = TestClient(app).post("/v1/demo/visit")
    assert response.status_code == 200
    assert "?token=" in response.json()["visit_url"]


def test_fregat_qr_redirect():
    Base.metadata.create_all(engine)
    response = TestClient(app).get("/fregat", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/?token=")


def test_owner_issues_one_qr_per_receipt():
    Base.metadata.create_all(engine)
    settings.owner_password = OWNER_TEST_PASSWORD
    reference = f"TEST-{uuid.uuid4()}"
    client = TestClient(app)
    assert client.post(
        "/v1/auth/login",
        json={"username": "fregat-owner", "password": OWNER_TEST_PASSWORD},
    ).status_code == 200
    body = {"transaction_reference": reference}
    issued = client.post("/v1/owner/visit-token", json=body)
    assert issued.status_code == 200
    assert "/v1/qr.png?token=" in issued.json()["qr_url"]
    assert client.post("/v1/owner/visit-token", json=body).status_code == 409


def test_owner_manages_staff_and_staff_qr_is_auditable():
    Base.metadata.create_all(engine)
    settings.owner_password = OWNER_TEST_PASSWORD
    username = f"cashier-{uuid.uuid4().hex[:8]}"
    staff_password = "cashier-password-123"
    owner = TestClient(app)
    assert owner.post(
        "/v1/auth/login",
        json={"username": "fregat-owner", "password": OWNER_TEST_PASSWORD},
    ).status_code == 200
    created = owner.post(
        "/v1/owner/staff",
        json={"username": username, "password": staff_password},
    )
    assert created.status_code == 200
    staff_id = created.json()["id"]
    with SessionLocal() as db:
        user = db.get(User, staff_id)
        assert user.role == "FREGAT_STAFF"
        assert verify_password(staff_password, user.password_hash)
    staff = TestClient(app)
    assert staff.post(
        "/v1/auth/login",
        json={"username": username, "password": staff_password},
    ).status_code == 200
    reference = f"STAFF-{uuid.uuid4()}"
    issued = staff.post(
        "/v1/owner/visit-token",
        json={"transaction_reference": reference},
    )
    assert issued.status_code == 200
    assert staff.get("/v1/owner/qr-log").status_code == 403
    assert staff.get("/v1/review/ratings").status_code == 403
    log = owner.get("/v1/owner/qr-log")
    assert log.status_code == 200
    item = next(
        item for item in log.json()["items"] if item["transaction_reference"] == reference
    )
    assert item["issued_by"] == username
    assert item["status"] == "ACTIVE"
    assert owner.post(
        f"/v1/owner/staff/{staff_id}/status", json={"active": False}
    ).status_code == 200
    assert staff.get("/v1/auth/me").status_code == 401
    assert staff.post(
        "/v1/owner/visit-token",
        json={"transaction_reference": f"DENIED-{uuid.uuid4()}"},
    ).status_code == 401


def test_business_fregat_is_read_only():
    Base.metadata.create_all(engine)
    client = TestClient(app)
    client.get("/fregat", follow_redirects=False)
    response = client.get("/v1/business/fregat")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, max-age=0"
    data = response.json()
    assert all(value is False for value in data["permissions"].values())
    pilot = data["pilot"]
    assert pilot["sample_target"] == 20
    assert pilot["remaining_to_target"] == max(0, 20 - data["rating_count"])
    assert pilot["incomplete_visits"] == max(
        0, data["verified_visits"] - pilot["submitted_ratings"]
    )
    expected_completion = (
        round(pilot["submitted_ratings"] / data["verified_visits"] * 100, 1)
        if data["verified_visits"]
        else 0.0
    )
    assert pilot["completion_rate"] == expected_completion
    if data["rating_count"]:
        assert (
            pilot["strongest_category"]["score"]
            >= pilot["weakest_category"]["score"]
        )
    assert client.post("/v1/business/fregat", json={}).status_code == 405


def test_business_page_loads_data_inline_without_cache():
    response = TestClient(app).get("/business")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, max-age=0"
    assert "loadDashboard()" in response.text
    assert 'id="content" class="grid"' in response.text
    assert "Пилот по текущим данным" in response.text
    assert "/static/business.js" not in response.text


def test_contradictory_rating_requires_independent_review():
    Base.metadata.create_all(engine)
    settings.owner_password = OWNER_TEST_PASSWORD
    settings.review_password = REVIEW_TEST_PASSWORD
    client = TestClient(app)
    redirect = client.get("/fregat", follow_redirects=False)
    initial = client.get("/v1/business/fregat").json()
    token = parse_qs(urlsplit(redirect.headers["location"]).query)["token"][0]
    visit = client.post("/v1/visits/verify-token", json={"token": token}).json()
    submitted = client.post(
        "/v1/ratings",
        json={
            "visit_id": visit["visit_id"],
            "overall": 10,
            "food": 1,
            "service": 1,
            "cleanliness": 1,
            "value": 1,
        },
    )
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "PENDING_REVIEW"
    assert submitted.json()["included_in_rating"] is False
    assert submitted.json()["rating_count"] == initial["rating_count"]
    assert client.get("/v1/review/ratings").status_code == 401
    assert client.post(
        "/v1/auth/login",
        json={"username": "fregat-owner", "password": OWNER_TEST_PASSWORD},
    ).status_code == 200
    assert client.get("/v1/review/ratings").status_code == 403
    assert client.post(
        "/v1/auth/login",
        json={"username": "relyqo-reviewer", "password": REVIEW_TEST_PASSWORD},
    ).status_code == 200
    assert client.post(
        "/v1/owner/visit-token",
        json={"transaction_reference": f"DENIED-{uuid.uuid4()}"},
    ).status_code == 403
    queue = client.get("/v1/review/ratings").json()
    item = next(
        item
        for item in queue["items"]
        if item["rating_id"] == submitted.json()["rating_id"]
    )
    decision = client.post(
        f"/v1/review/ratings/{item['review_id']}/decision",
        json={"decision": "APPROVE"},
    )
    assert decision.status_code == 200
    assert decision.json()["included_in_rating"] is True
    assert decision.json()["rating_count"] == initial["rating_count"] + 1


def test_review_page_is_not_cached():
    response = TestClient(app).get("/review")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, max-age=0"
    assert "RELYQO OWNER REVIEW" in response.text


def test_staff_page_is_not_cached():
    response = TestClient(app).get("/staff")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, max-age=0"
    assert "RELYQO STAFF" in response.text


def test_account_password_is_hashed_and_logout_revokes_session():
    Base.metadata.create_all(engine)
    settings.review_password = REVIEW_TEST_PASSWORD
    client = TestClient(app, base_url="https://testserver")
    login = client.post(
        "/v1/auth/login",
        json={"username": "relyqo-reviewer", "password": REVIEW_TEST_PASSWORD},
    )
    assert login.status_code == 200
    assert "httponly" in login.headers["set-cookie"].lower()
    assert "secure" in login.headers["set-cookie"].lower()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == "relyqo-reviewer"))
        assert user.password_hash != REVIEW_TEST_PASSWORD
        assert verify_password(REVIEW_TEST_PASSWORD, user.password_hash)
    assert client.get("/v1/auth/me").status_code == 200
    assert client.post("/v1/auth/logout").status_code == 200
    assert client.get("/v1/auth/me").status_code == 401


def test_password_change_reset_and_login_lockout():
    Base.metadata.create_all(engine)
    settings.owner_password = OWNER_TEST_PASSWORD
    username = f"secure-{uuid.uuid4().hex[:8]}"
    original = "staff-original-password"
    changed = "staff-changed-password"
    reset = "staff-reset-password"
    owner = TestClient(app)
    assert owner.post(
        "/v1/auth/login",
        json={"username": "fregat-owner", "password": OWNER_TEST_PASSWORD},
    ).status_code == 200
    created = owner.post(
        "/v1/owner/staff",
        json={"username": username, "password": original},
    ).json()

    first_session = TestClient(app)
    second_session = TestClient(app)
    assert first_session.post(
        "/v1/auth/login", json={"username": username, "password": original}
    ).status_code == 200
    assert second_session.post(
        "/v1/auth/login", json={"username": username, "password": original}
    ).status_code == 200
    changed_response = first_session.post(
        "/v1/auth/change-password",
        json={"current_password": original, "new_password": changed},
    )
    assert changed_response.status_code == 200
    assert changed_response.json()["login_required"] is True
    assert first_session.get("/v1/auth/me").status_code == 401
    assert second_session.get("/v1/auth/me").status_code == 401
    assert TestClient(app).post(
        "/v1/auth/login", json={"username": username, "password": original}
    ).status_code == 401

    active_session = TestClient(app)
    assert active_session.post(
        "/v1/auth/login", json={"username": username, "password": changed}
    ).status_code == 200
    reset_response = owner.post(
        f"/v1/owner/staff/{created['id']}/reset-password",
        json={"new_password": reset},
    )
    assert reset_response.status_code == 200
    assert active_session.get("/v1/auth/me").status_code == 401
    assert TestClient(app).post(
        "/v1/auth/login", json={"username": username, "password": changed}
    ).status_code == 401
    assert TestClient(app).post(
        "/v1/auth/login", json={"username": username, "password": reset}
    ).status_code == 200

    for attempt in range(5):
        response = TestClient(app).post(
            "/v1/auth/login",
            json={"username": username, "password": f"wrong-password-{attempt}"},
        )
    assert response.status_code == 429
    assert TestClient(app).post(
        "/v1/auth/login", json={"username": username, "password": reset}
    ).status_code == 429
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == username))
        assert user.failed_login_attempts == 5
        assert user.locked_until > datetime.utcnow()


def test_one_time_recovery_code_revokes_sessions_and_resets_password():
    Base.metadata.create_all(engine)
    username = f"review-{uuid.uuid4().hex[:8]}"
    original = "review-original-password"
    replacement = "review-recovered-password"
    with SessionLocal() as db:
        user = User(
            username=username,
            password_hash=password_hash(original),
            role="RELYQO_REVIEWER",
        )
        db.add(user)
        db.commit()
        user_id = user.id

    first_session = TestClient(app)
    second_session = TestClient(app)
    for client in (first_session, second_session):
        assert client.post(
            "/v1/auth/login",
            json={"username": username, "password": original},
        ).status_code == 200
    assert first_session.post(
        "/v1/auth/recovery-code",
        json={"current_password": "incorrect-current-password"},
    ).status_code == 401
    recovery_response = first_session.post(
        "/v1/auth/recovery-code", json={"current_password": original}
    )
    assert recovery_response.status_code == 200
    recovery_code = recovery_response.json()["recovery_code"]
    assert recovery_code.startswith("relyqo-")
    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user.recovery_code_hash == token_hash(recovery_code)
        assert recovery_code not in user.recovery_code_hash

    recovered = TestClient(app).post(
        "/v1/auth/recover",
        json={
            "username": username,
            "recovery_code": recovery_code,
            "new_password": replacement,
        },
    )
    assert recovered.status_code == 200
    assert first_session.get("/v1/auth/me").status_code == 401
    assert second_session.get("/v1/auth/me").status_code == 401
    assert TestClient(app).post(
        "/v1/auth/login", json={"username": username, "password": original}
    ).status_code == 401
    assert TestClient(app).post(
        "/v1/auth/login", json={"username": username, "password": replacement}
    ).status_code == 200
    assert TestClient(app).post(
        "/v1/auth/recover",
        json={
            "username": username,
            "recovery_code": recovery_code,
            "new_password": "another-recovery-password",
        },
    ).status_code == 401
    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user.recovery_code_hash is None


def test_recovery_page_is_not_cached():
    response = TestClient(app).get("/recover")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, max-age=0"
    assert "RELYQO RECOVERY" in response.text
