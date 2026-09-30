"""Navigation compatibility and business tenant/role isolation."""
from datetime import datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

import app.main as main
from app.config import settings
from app.db import Base, SessionLocal, engine
from app.models import AuthSession, Branch, Organization, Rating, User, Visit
from app.security import password_hash, token_hash


def account(role="BUSINESS_OWNER", *, name=None, category="EDUCATION", score=80):
    Base.metadata.create_all(engine)
    raw = uuid4().hex
    with SessionLocal() as db:
        org = Organization(name=name or "Structure " + raw, category=category, city="Tashkent", score=score, rating_count=1)
        db.add(org); db.flush()
        branch = Branch(organization_id=org.id, name="Main", city="Tashkent", active=True)
        db.add(branch); db.flush()
        visit = Visit(branch_id=branch.id)
        db.add(visit); db.flush()
        db.add(Rating(visit_id=visit.id, organization_id=org.id, overall=score // 10, food=score // 10,
                      service=score // 10, cleanliness=score // 10, value=score // 10, ces=score, trust_weight=1))
        user = User(username="structure-" + raw, password_hash=password_hash("structure-test-password"), role=role, organization_id=org.id)
        db.add(user); db.flush()
        db.add(AuthSession(user_id=user.id, token_hash=token_hash(raw), expires_at=datetime.utcnow() + timedelta(hours=1)))
        db.commit()
        ids = org.id, branch.id, user.id
    client = TestClient(main.app)
    client.cookies.set("relyqo_session", raw)
    return client, ids


def test_search_entry_and_old_qr_urls_keep_distinct_flows():
    client = TestClient(main.app)
    search = client.get("/consumer")
    assert 'id="directoryPanel"' in search.text
    assert '<a href="/nearby" aria-current="page">Найти</a>' in search.text
    assert 'id="token"' not in search.text
    for url in ["/", "/rate", "/?token=old-link", "/consumer?token=old-link"]:
        page = client.get(url)
        assert page.status_code == 200
        assert 'id="token"' in page.text
        assert '<a href="/rate" aria-current="page">Оценить</a>' in page.text
        assert "no-store" in page.headers["cache-control"]
    for url in ["/nearby", "/place", "/rankings", "/community-rate", "/me", "/me/rating"]:
        page = client.get(url)
        assert page.text.count('class="consumerNav"') == 1
        assert all(f'href="{path}"' in page.text for path in ["/nearby", "/rate", "/me"])


def test_business_dashboard_only_uses_authenticated_organization():
    first, a = account(score=80)
    second, b = account(score=30)
    for client, own, foreign, expected in [(first, a, b, 80), (second, b, a, 30)]:
        response = client.get("/v1/business-owner/dashboard", params={"organization_id": foreign[0]})
        data = response.json()
        assert response.status_code == 200
        assert "no-store" in response.headers["cache-control"]
        assert data["organization"]["id"] == own[0]
        assert data["metrics"]["food"] == expected
        assert data["metric_labels"]["food"] == "Качество обучения"
        assert not any(data["permissions"].values())
    public = TestClient(main.app)
    assert public.get("/v1/business-owner/dashboard").status_code == 401
    assert public.get("/v1/business-owner/ai-insights").status_code == 401
    for role in ["BUSINESS_STAFF", "FREGAT_STAFF", "CONSUMER", "RELYQO_ADMIN"]:
        client, _ = account(role)
        assert client.get("/v1/business-owner/dashboard").status_code == 403
        assert client.get("/v1/business-owner/ai-insights").status_code == 403


def test_ai_cache_does_not_cross_same_name_businesses(monkeypatch):
    name = "Same school " + uuid4().hex
    first, a = account(name=name)
    second, b = account(name=name)
    monkeypatch.setattr(settings, "openai_api_key", "local-test")
    main._ai_cache.clear(); main._ai_last_request.clear()
    payloads = []
    monkeypatch.setattr(main, "generate_business_insight", lambda data: payloads.append(data) or "Проверяемые рекомендации")
    for client in [first, second]:
        response = client.get("/v1/business-owner/ai-insights")
        assert response.status_code == 200
        assert response.json()["cached"] is False
    assert len(payloads) == 2
    assert all(p["organization"] == name and p["category"] == "EDUCATION" for p in payloads)
    assert all("organization_id" not in p and "username" not in p for p in payloads)
    assert second.get("/v1/business-owner/ai-insights").json()["cached"] is True
    with SessionLocal() as db:
        assert all(db.get(Organization, ids[0]).score == 80 for ids in [a, b])


def test_generic_staff_is_scoped_and_qr_respects_partner_status():
    first, a = account()
    second, _ = account()
    username = "cashier-" + uuid4().hex
    created = first.post("/v1/owner/staff", json={"username": username, "password": "structure-staff-password"})
    assert created.status_code == 200
    assert created.json()["role"] == "BUSINESS_STAFF"
    staff_id = created.json()["id"]
    assert any(u["id"] == staff_id for u in first.get("/v1/owner/staff").json()["items"])
    assert all(u["id"] != staff_id for u in second.get("/v1/owner/staff").json()["items"])
    assert second.post(f"/v1/owner/staff/{staff_id}/status", json={"active":False}).status_code == 404
    assert second.post(f"/v1/owner/staff/{staff_id}/reset-password", json={"new_password":"another-test-password"}).status_code == 404
    staff = TestClient(main.app)
    assert staff.post("/v1/auth/login", json={"username":username, "password":"structure-staff-password"}).status_code == 200
    for path in ["/v1/owner/staff", "/v1/owner/qr-log", "/v1/business-owner/profile", "/v1/admin/dashboard"]:
        assert staff.get(path).status_code == 403
    issued = staff.post("/v1/owner/visit-token", json={"transaction_reference":"scope-1"})
    assert issued.status_code == 200
    assert issued.json()["organization_id"] == a[0]
    assert issued.json()["branch_id"] == a[1]
    assert staff.post("/v1/owner/visit-token", json={"transaction_reference":"scope-1"}).status_code == 409
    with SessionLocal() as db:
        db.get(Organization, a[0]).profile_status = "PUBLISHED"
        db.commit()
    assert staff.post("/v1/owner/visit-token", json={"transaction_reference":"scope-2"}).status_code == 403
    assert first.post("/v1/owner/staff/" + staff_id + "/status", json={"active":False}).status_code == 200
    assert staff.post("/v1/owner/visit-token", json={"transaction_reference":"scope-3"}).status_code == 401


def test_admin_registry_includes_published_profiles_and_literal_search():
    admin, _ = account("RELYQO_ADMIN")
    marker = "Registry " + uuid4().hex
    owner, ids = account(name=marker + "%_", category="HEALTH")
    assert owner.get("/v1/admin/organizations").status_code == 403
    assert TestClient(main.app).get("/v1/admin/organizations").status_code == 401
    response = admin.get("/v1/admin/organizations", params={"q": marker + "%_"})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1 and data["next_offset"] is None
    assert data["items"][0]["id"] == ids[0]
    assert data["items"][0]["branches"][0]["id"] == ids[1]
    assert admin.get("/v1/admin/organizations", params={"offset":-1}).status_code == 422
