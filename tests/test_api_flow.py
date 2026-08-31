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
from types import SimpleNamespace
import sys
import app.main as main_module
from app.ai import generate_business_insight

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


def test_nearby_page_and_maps_config_are_private_by_default(monkeypatch):
    page = TestClient(app).get("/nearby")
    assert page.status_code == 200
    assert page.headers["cache-control"] == "no-store, max-age=0"
    assert "RELYQO NEARBY" in page.text
    assert "navigator.geolocation" in page.text
    assert "не сохраняется RELYQO" in page.text
    assert "Оценить в RELYQO" in page.text
    assert "Verified Score по QR" in page.text
    assert "♡ Избранные" in page.text
    assert "relyqo_favorites_v1" in page.text
    assert 'id="radius"' in page.text
    assert "radius:zoneRadius*1000" in page.text
    assert 'id="resultLimit"' in page.text
    assert "searchCenters" in page.text
    assert "до 100" in page.text

    monkeypatch.setattr(settings, "google_maps_browser_key", "browser-key")
    config = TestClient(app).get("/v1/public/maps-config")
    assert config.status_code == 200
    assert config.headers["cache-control"] == "no-store, max-age=0"
    assert config.json() == {
        "configured": True,
        "browser_key": "browser-key",
        "search_radius_km": 15,
        "google_result_limit_per_search": 20,
        "location_storage": "none",
    }


def test_community_rating_is_public_one_per_browser_and_separate_from_score():
    Base.metadata.create_all(engine)
    client = TestClient(app)
    rating_page = client.get("/community-rate")
    assert rating_page.status_code == 200
    assert rating_page.headers["cache-control"] == "no-store, max-age=0"
    assert "Community Score" in rating_page.text
    assert "не меняет официальный RELYQO Score" in rating_page.text

    before = client.get("/v1/business/fregat").json()["relyqo_score"]
    object_key = f"google:test-{uuid.uuid4()}"
    body = {
        "object_key": object_key,
        "source": "GOOGLE",
        "overall": 8,
        "quality": 8,
        "service": 8,
        "cleanliness": 8,
        "value": 8,
    }
    created = client.post("/v1/community-ratings", json=body)
    assert created.status_code == 200
    assert created.json()["status"] == "COMMUNITY_PUBLISHED"
    assert created.json()["community_score"] == 80.0
    assert created.json()["rating_count"] == 1
    assert created.json()["included_in_relyqo_score"] is False
    assert "httponly" in created.headers["set-cookie"].lower()
    assert client.post("/v1/community-ratings", json=body).status_code == 409

    summary = client.get(
        "/v1/community-ratings/summary", params={"object_key": object_key}
    )
    assert summary.status_code == 200
    assert summary.json()["community_score"] == 80.0
    assert summary.json()["rating_count"] == 1
    assert client.get("/v1/business/fregat").json()["relyqo_score"] == before


def test_public_nearby_branches_only_returns_active_partners_in_radius():
    Base.metadata.create_all(engine)
    name = f"Nearby {uuid.uuid4()}"
    with SessionLocal() as db:
        organization = Organization(name=name, city="Tashkent", score=81.2)
        db.add(organization)
        db.flush()
        db.add_all(
            [
                Branch(
                    organization_id=organization.id,
                    name="Nearby branch",
                    address="Test address",
                    city="Tashkent",
                    country_code="UZ",
                    latitude=41.3000,
                    longitude=69.2500,
                    active=True,
                ),
                Branch(
                    organization_id=organization.id,
                    name="Inactive branch",
                    latitude=41.3001,
                    longitude=69.2501,
                    active=False,
                ),
                Branch(
                    organization_id=organization.id,
                    name="Far branch",
                    latitude=42.3000,
                    longitude=70.2500,
                    active=True,
                ),
            ]
        )
        db.commit()

    response = TestClient(app).post(
        "/v1/public/branches/nearby",
        json={"latitude": 41.3, "longitude": 69.25, "radius_km": 15},
    )
    assert response.status_code == 200
    payload = response.json()
    matching = [item for item in payload["items"] if item["organization"] == name]
    assert len(matching) == 1
    assert matching[0]["branch"] == "Nearby branch"
    assert matching[0]["rating_requires_verified_visit"] is True
    assert payload["location_stored"] is False
    assert payload["rating_policy"] == "QR_VERIFIED_VISIT_ONLY"


def test_public_nearby_branches_rejects_invalid_coordinates():
    response = TestClient(app).post(
        "/v1/public/branches/nearby",
        json={"latitude": 91, "longitude": 69.25},
    )
    assert response.status_code == 422


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


def test_ai_insights_are_owner_only_read_only_and_optional(monkeypatch):
    Base.metadata.create_all(engine)
    settings.owner_password = OWNER_TEST_PASSWORD
    public = TestClient(app)
    assert public.get("/v1/business/fregat/ai-insights").status_code == 401

    owner = TestClient(app)
    assert owner.post(
        "/v1/auth/login",
        json={"username": "fregat-owner", "password": OWNER_TEST_PASSWORD},
    ).status_code == 200
    monkeypatch.setattr(settings, "openai_api_key", None)
    assert owner.get("/v1/business/fregat/ai-insights").status_code == 503

    monkeypatch.setattr(settings, "openai_api_key", "test-api-key")
    monkeypatch.setattr(settings, "openai_model", "test-model")
    main_module._ai_cache.clear()
    main_module._ai_last_request.clear()
    captured = {}

    def fake_insight(metrics):
        captured.update(metrics)
        return "1. Ранний сигнал.\n2. Сильная сторона.\n3. Проверка.\n4. Действия."

    monkeypatch.setattr(main_module, "generate_business_insight", fake_insight)
    before = owner.get("/v1/business/fregat").json()
    generated = owner.get("/v1/business/fregat/ai-insights")
    after = owner.get("/v1/business/fregat").json()
    assert generated.status_code == 200
    assert generated.json()["model"] == "test-model"
    assert generated.json()["cached"] is False
    assert captured["score_source"] == "deterministic_weighted_ces_v1"
    assert "organization_id" not in captured
    assert before["relyqo_score"] == after["relyqo_score"]
    assert before["rating_count"] == after["rating_count"]
    assert all(value is False for value in after["permissions"].values())
    assert after["ai"]["affects_score"] is False
    assert owner.post("/v1/business/fregat/ai-insights", json={}).status_code == 405


def test_openai_request_is_aggregate_only_and_not_stored(monkeypatch):
    captured = {}

    class FakeResponses:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(output_text="Безопасная агрегированная рекомендация")

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.responses = FakeResponses()

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    monkeypatch.setattr(settings, "openai_api_key", "test-secret")
    monkeypatch.setattr(settings, "openai_model", "test-model")
    result = generate_business_insight(
        {
            "relyqo_score": 38.4,
            "included_rating_count": 4,
            "category_scores": {"service": 32.5},
        }
    )
    assert result == "Безопасная агрегированная рекомендация"
    assert captured["model"] == "test-model"
    assert captured["reasoning"] == {"effort": "low"}
    assert captured["store"] is False
    assert captured["text"] == {"verbosity": "low"}
    assert "test-secret" not in captured["input"]
    assert "не изменяй RELYQO Score" in captured["instructions"]
