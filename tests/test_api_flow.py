from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from app.db import Base, SessionLocal, engine
from app.main import app
from app.models import Branch, Organization, VisitToken
from app.security import create_token, token_hash
from app.config import settings
import uuid


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
    settings.owner_password = "владелец-test-password"
    reference = f"TEST-{uuid.uuid4()}"
    client = TestClient(app)
    body = {"password": settings.owner_password, "transaction_reference": reference}
    issued = client.post("/v1/owner/visit-token", json=body)
    assert issued.status_code == 200
    assert "/v1/qr.png?token=" in issued.json()["qr_url"]
    assert client.post("/v1/owner/visit-token", json=body).status_code == 409


def test_business_fregat_is_read_only():
    Base.metadata.create_all(engine)
    client = TestClient(app)
    client.get("/fregat", follow_redirects=False)
    response = client.get("/v1/business/fregat")
    assert response.status_code == 200
    assert all(value is False for value in response.json()["permissions"].values())
    assert client.post("/v1/business/fregat", json={}).status_code == 405


def test_business_page_loads_data_inline_without_cache():
    response = TestClient(app).get("/business")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, max-age=0"
    assert "loadDashboard()" in response.text
    assert 'id="content" class="grid"' in response.text
    assert "/static/business.js" not in response.text
