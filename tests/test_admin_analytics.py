from datetime import datetime
import json
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.db import Base, get_db
from app.models import (
    Branch,
    CommunityRating,
    ManualPlace,
    Organization,
    Rating,
    ServiceCategory,
    User,
    Visit,
)
from app.security import password_hash
from app.config import settings
import app.analytics as analytics
from app.ai import generate_admin_analytics, AIServiceError

PASSWORD = "analytics-fixture-password"
PERIOD = "start=2026-09-01&end=2026-09-03"


@pytest.fixture
def data(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'analytics.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    def database():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = database
    monkeypatch.setattr(settings, "openai_api_key", "test-key-never-send")
    analytics._cache.clear()
    analytics._last_request.clear()
    analytics._busy.clear()
    with factory() as db:
        admin = User(
            username="analytics-admin",
            role="RELYQO_ADMIN",
            password_hash=password_hash(PASSWORD),
        )
        one = User(
            username="private-one@example.test",
            role="CONSUMER",
            password_hash=password_hash(PASSWORD),
        )
        two = User(
            username="private-two@example.test",
            role="CONSUMER",
            password_hash=password_hash(PASSWORD),
        )
        restaurant = Organization(name="Test Restaurant", category="RESTAURANT")
        clinic = Organization(name="Test Clinic", category="HEALTH")
        db.add_all([admin, one, two, restaurant, clinic])
        db.flush()
        branches = [
            Branch(organization_id=restaurant.id, name="First"),
            Branch(organization_id=restaurant.id, name="Second"),
            Branch(organization_id=clinic.id, name="Clinic"),
        ]
        db.add_all(branches)
        db.flush()
        for index, (branch, user, score, included) in enumerate(
            [
                (branches[0], one, 9, True),
                (branches[1], one, 3, True),
                (branches[0], two, 8, True),
                (branches[0], None, 6, True),
                (branches[0], one, 1, False),
                (branches[2], one, 4, True),
            ]
        ):
            visit = Visit(branch_id=branch.id, verified_at=datetime(2026, 9, 1))
            db.add(visit)
            db.flush()
            db.add(
                Rating(
                    visit_id=visit.id,
                    organization_id=branch.organization_id,
                    consumer_user_id=user.id if user else None,
                    overall=score,
                    food=score,
                    service=score,
                    cleanliness=score,
                    value=score,
                    ces=score * 10,
                    trust_weight=1,
                    included=included,
                    status="ACCEPTED" if included else "PENDING_REVIEW",
                    created_at=datetime(2026, 9, 2),
                )
            )
        db.add(Visit(branch_id=branches[0].id, verified_at=datetime(2026, 9, 3)))
        old = Visit(branch_id=branches[0].id, verified_at=datetime(2026, 8, 31))
        db.add(old)
        db.flush()
        db.add(
            Rating(
                visit_id=old.id,
                organization_id=restaurant.id,
                overall=10,
                food=10,
                service=10,
                cleanliness=10,
                value=10,
                ces=100,
                trust_weight=1,
                created_at=datetime(2026, 8, 31),
            )
        )
        place = ManualPlace(
            name="Test School",
            identity_hash="school",
            category="EDUCATION",
            description="Test description",
            address="Test address",
            city="Tashkent",
            country_code="UZ",
            latitude=41,
            longitude=69,
            created_by_hash="creator",
        )
        db.add(place)
        db.flush()
        for i, (key, user, score) in enumerate(
            [
                (f"relyqo:{branches[0].id}", one, 10),
                (f"relyqo:{branches[1].id}", one, 6),
                (f"manual:{place.id}", two, 4),
            ]
        ):
            db.add(
                CommunityRating(
                    object_key=key,
                    consumer_user_id=user.id,
                    source="MANUAL" if key.startswith("manual") else "RELYQO_PARTNER",
                    category="OTHER",
                    rater_hash=f"rater-{i}",
                    overall=score,
                    quality=score,
                    service=score,
                    cleanliness=score,
                    value=score,
                    community_score=score * 10,
                    created_at=datetime(2026, 9, 2),
                )
            )
        db.commit()
        ids = {
            "admin": admin.id,
            "restaurant": restaurant.id,
            "clinic": clinic.id,
            "one": one.id,
            "two": two.id,
        }
    client = TestClient(app)
    assert (
        client.post(
            "/v1/auth/login", json={"username": "analytics-admin", "password": PASSWORD}
        ).status_code
        == 200
    )
    yield client, factory, ids
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def report(client, extra=""):
    response = client.get("/v1/admin/analytics?" + PERIOD + extra)
    assert response.status_code == 200, response.text
    assert "no-store" in response.headers["cache-control"]
    return response.json()


def test_exact_counts_deduplication_denominators_and_date_boundaries(data):
    client, _, _ = data
    result = report(client)
    s = result["summary"]
    assert (s["verified_visits"], s["submitted"], s["included"], s["excluded"]) == (
        7,
        6,
        5,
        1,
    )
    assert (s["respondents"], s["anonymous"]) == (2, 1)
    assert (
        s["satisfied"],
        s["neutral"],
        s["dissatisfied"],
        s["satisfied_percent"],
    ) == (2, 1, 2, 40.0)
    assert s["dimensions"]["overall"] == 6
    assert [row["included"] for row in result["trend"]] == [0, 5, 0]
    assert [row["verified_visits"] for row in result["trend"]] == [6, 0, 1]
    restaurant = next(
        row for row in result["organizations"] if row["name"] == "Test Restaurant"
    )
    assert (
        restaurant["respondents"],
        restaurant["verified_visits"],
        restaurant["satisfied_percent"],
    ) == (2, 6, 50)
    serialized = json.dumps(result)
    assert (
        "private-one" not in serialized
        and PASSWORD not in serialized
        and "rater-" not in serialized
    )


def test_community_is_separate_and_resolves_partner_branches(data):
    result = report(data[0], "&source=community")
    s = result["summary"]
    assert s["verified_visits"] is None
    assert (
        s["included"],
        s["respondents"],
        s["satisfied"],
        s["neutral"],
        s["dissatisfied"],
    ) == (3, 2, 1, 1, 1)
    assert {row["code"] for row in result["categories"]} == {"RESTAURANT", "EDUCATION"}
    restaurant = next(
        row for row in result["organizations"] if row["name"] == "Test Restaurant"
    )
    assert restaurant["included"] == 2 and restaurant["respondents"] == 1


def test_filters_empty_states_and_invalid_dates(data):
    client, _, ids = data
    result = report(client, "&entity=org:" + ids["clinic"])
    assert result["summary"]["included"] == 1
    assert result["summary"]["dissatisfied"] == 1
    assert len(result["organizations"]) == 1
    empty = report(client, "&category=EDUCATION")
    assert empty["summary"]["satisfied_percent"] is None
    assert all(value is None for value in empty["summary"]["dimensions"].values())
    assert (
        client.get("/v1/admin/analytics?start=2026-09-02&end=2026-09-01").status_code
        == 422
    )
    assert (
        client.get("/v1/admin/analytics?start=2020-01-01&end=2026-01-01").status_code
        == 422
    )
    assert client.get("/v1/admin/analytics?source=all").status_code == 422
    assert client.get("/v1/admin/analytics?category=UNKNOWN").status_code == 422
    assert client.get("/v1/admin/analytics?entity=unknown").status_code == 404


@pytest.mark.parametrize(
    "role",
    ["CONSUMER", "BUSINESS_OWNER", "FREGAT_OWNER", "FREGAT_STAFF", "RELYQO_REVIEWER"],
)
def test_every_other_role_is_denied_analytics_ai_and_category_writes(data, role):
    client, factory, ids = data
    with factory() as db:
        db.get(User, ids["admin"]).role = role
        db.commit()
    assert client.get("/v1/admin/analytics").status_code == 403
    assert client.post("/v1/admin/analytics/insights").status_code == 403
    assert (
        client.post(
            "/v1/admin/service-categories", json={"label": "New category"}
        ).status_code
        == 403
    )


def test_unauthenticated_users_get_no_analytics(data):
    client, _, _ = data
    client.cookies.clear()
    assert client.get("/v1/admin/analytics").status_code == 401
    assert client.post("/v1/admin/analytics/insights").status_code == 401
    assert (
        client.post(
            "/v1/admin/service-categories", json={"label": "New category"}
        ).status_code
        == 401
    )
    shell = client.get("/admin/analytics")
    assert 'id="content" hidden' in shell.text
    assert "Test Restaurant" not in shell.text
    assert "frame-ancestors" in shell.headers["content-security-policy"]


def test_ai_receives_only_aggregates_caches_and_cannot_modify_ratings(
    data, monkeypatch
):
    client, factory, ids = data
    calls = []
    monkeypatch.setattr(
        analytics,
        "generate_admin_analytics",
        lambda context: calls.append(context) or "Проверяемый вывод.",
    )
    before = report(client)
    first = client.post("/v1/admin/analytics/insights?" + PERIOD)
    assert first.status_code == 200, first.text
    assert first.json()["cached"] is False
    second = client.post("/v1/admin/analytics/insights?" + PERIOD)
    assert second.json()["cached"] is True and len(calls) == 1
    encoded = json.dumps(calls[0])
    for secret in [
        ids["one"],
        ids["two"],
        ids["admin"],
        PASSWORD,
        "private-one@example.test",
        "rater-",
    ]:
        assert secret not in encoded
    assert report(client) == before
    assert (
        client.post(
            "/v1/admin/analytics/insights?" + PERIOD + "&source=community"
        ).status_code
        == 429
    )


def test_ai_missing_configuration_or_provider_error_preserves_statistics(
    data, monkeypatch
):
    client, _, _ = data
    monkeypatch.setattr(settings, "openai_api_key", None)
    assert client.post("/v1/admin/analytics/insights?" + PERIOD).status_code == 503
    assert report(client)["summary"]["included"] == 5
    monkeypatch.setattr(settings, "openai_api_key", "fixture")

    def fail(_):
        raise AIServiceError("private provider detail")

    monkeypatch.setattr(analytics, "generate_admin_analytics", fail)
    failed = client.post("/v1/admin/analytics/insights?" + PERIOD)
    assert failed.status_code == 502 and "private provider detail" not in failed.text
    assert report(client)["summary"]["included"] == 5


def test_category_creation_is_persistent_validated_and_available_in_registration(data):
    client, factory, _ = data
    response = client.post(
        "/v1/admin/service-categories",
        json={"label": "  Ветеринарная   хирургия  ", "group": "HEALTH"},
    )
    assert response.status_code == 201, response.text
    category = response.json()
    code = category["code"]
    assert category["label"] == "Ветеринарная хирургия"
    with factory() as db:
        assert db.get(ServiceCategory, code).group_code == "HEALTH"
    assert (
        client.post(
            "/v1/admin/service-categories",
            json={"label": "ветеринарная хирургия", "group": "HEALTH"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/v1/admin/service-categories", json={"label": "<script>bad</script>"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/v1/admin/service-categories",
            json={"label": "Another", "group": "UNKNOWN"},
        ).status_code
        == 422
    )
    body = {
        "username": "new-business",
        "password": PASSWORD,
        "organization_name": "New vet",
        "category": code,
        "description": "An example clinic",
        "address": "A street 1",
        "city": "Tashkent",
        "country_code": "UZ",
        "latitude": 41.3,
        "longitude": 69.2,
    }
    registered = client.post("/v1/business-owner/register", json=body)
    assert registered.status_code == 200, registered.text
    assert registered.json()["category"] == code
    # Categories themselves are public; statistics remain private.
    client.cookies.clear()
    assert category in client.get("/v1/public/service-categories").json()["items"]
    assert client.get("/v1/public/rankings?category=" + code).status_code == 200
    assert (
        client.get("/v1/public/rated-organizations?category=" + code).status_code == 200
    )


def test_unknown_categories_cannot_be_invented_through_public_forms(data):
    client, _, _ = data
    body = {
        "name": "Somewhere",
        "category": "UNKNOWN",
        "description": "An example description",
        "address": "A street 1",
        "city": "Tashkent",
        "country_code": "UZ",
        "latitude": 41.3,
        "longitude": 69.2,
    }
    assert client.post("/v1/public/manual-places", json=body).status_code == 422


def test_admin_model_request_uses_aggregates_without_storage(monkeypatch):
    captured = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.responses = self

        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(output_text="Вывод по данным.")

    monkeypatch.setattr(settings, "openai_api_key", "test")
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    assert generate_admin_analytics({"summary": {"included": 10}}) == "Вывод по данным."
    assert captured["store"] is False
    assert json.loads(captured["input"]) == {"summary": {"included": 10}}
    assert "недоверенные данные" in captured["instructions"]
