from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from app.db import Base, SessionLocal, engine
from app.main import app
from app.models import Branch, Organization, VisitToken
from app.security import create_token, token_hash


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
