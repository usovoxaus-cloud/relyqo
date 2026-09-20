import uuid

from fastapi.testclient import TestClient

from app.db import Base, SessionLocal, engine
from app.main import app
from app.models import Branch, ManualPlace, Organization


def test_country_city_catalog_includes_public_unrated_branches_and_excludes_private_places():
    Base.metadata.create_all(engine)
    suffix = uuid.uuid4().hex
    with SessionLocal() as db:
        public = Organization(name=f"Directory {suffix}", profile_status="PUBLISHED")
        hidden = Organization(name=f"Private {suffix}", profile_status="SELF_REGISTERED")
        db.add_all([public, hidden])
        db.flush()
        branches = [
            Branch(organization_id=public.id, name="First", city="Tashkent", country_code="UZ"),
            Branch(organization_id=public.id, name="Second", city="Samarkand", country_code="UZ"),
            Branch(organization_id=public.id, name="Foreign", city="Almaty", country_code="KZ"),
            Branch(organization_id=public.id, name="Closed", city="Private City", country_code="UZ", active=False),
            Branch(organization_id=hidden.id, name="Hidden", city="Hidden City", country_code="UZ"),
        ]
        place = ManualPlace(identity_hash=suffix, name=f"Manual {suffix}", category="OTHER", description="Public manual organization", address="Street 1", city="Samarkand", country_code="UZ", latitude=39.65, longitude=66.96, created_by_hash=suffix)
        db.add_all([*branches, place])
        db.commit()
        branch_keys = {f"relyqo:{b.id}" for b in branches[:3]}
        hidden_keys = {f"relyqo:{b.id}" for b in branches[3:]}
        manual_key = f"manual:{place.id}"
    client = TestClient(app)
    path = "/v1/public/rated-organizations"
    assert client.get(path, params={"q": suffix}).json()["total"] == 0
    result = client.get(path, params={"include_unrated": True, "q": suffix, "limit": 100})
    assert result.status_code == 200
    data = result.json()
    keys = {item["object_key"] for item in data["items"]}
    assert keys == branch_keys | {manual_key}
    assert not keys & hidden_keys
    assert data["includes_unrated"] is True
    assert all(item["verified_rating_count"] == 0 for item in data["items"])
    uz = next(country for country in data["geography"] if country["country_code"] == "UZ")
    assert {"Tashkent", "Samarkand"} <= {city["city"] for city in uz["cities"]}
    assert "Hidden City" not in {city["city"] for city in uz["cities"]}
    selected = client.get(path, params={"include_unrated": True, "q": suffix, "country_code": "UZ", "city": "Samarkand"}).json()
    assert selected["total"] == 2
    assert all(item["city"] == "Samarkand" and item["country_code"] == "UZ" for item in selected["items"])
    first = client.get(path, params={"include_unrated": True, "q": suffix, "limit": 1}).json()
    second = client.get(path, params={"include_unrated": True, "q": suffix, "limit": 1, "offset": 1}).json()
    assert first["has_more"] and first["items"][0]["object_key"] != second["items"][0]["object_key"]
    rated = client.get(path, params={"include_unrated": True, "q": suffix, "score_type": "RATED"}).json()
    assert rated["total"] == 0
