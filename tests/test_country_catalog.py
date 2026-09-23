import uuid

from fastapi.testclient import TestClient

from app.db import Base, SessionLocal, engine
from app.main import app
from app.models import Branch, ManualPlace, Organization
from app.geography import COUNTRY_CITIES, location_catalog


def test_starter_countries_and_cities_are_selectable_without_creating_organizations():
    directory = location_catalog([], include_starter=True)
    assert len(directory) == 8
    assert sum(len(country["cities"]) for country in directory) == 40
    assert all(country["card_count"] == 0 for country in directory)
    assert all(city["label_ru"] and city["label_uz"] for country in directory for city in country["cities"])
    Base.metadata.create_all(engine)
    client = TestClient(app)
    response = client.get("/v1/public/rated-organizations", params={"include_unrated": True, "country_code": "TR", "city": "Анкара", "q": uuid.uuid4().hex})
    assert response.status_code == 200
    data = response.json()
    assert set(COUNTRY_CITIES) <= set(data["facets"]["countries"])
    assert data["items"] == [] and data["total"] == 0
    assert any(city["city"] == "Ankara" and city["country_code"] == "TR" for city in data["facets"]["cities"])


def test_new_service_categories_and_city_aliases_filter_real_public_records():
    Base.metadata.create_all(engine)
    suffix = uuid.uuid4().hex
    with SessionLocal() as db:
        clinic = Organization(name=f"Clinic {suffix}", category="CLINIC", profile_status="PUBLISHED")
        repair = Organization(name=f"Repair {suffix}", category="HOME_REPAIR", profile_status="PUBLISHED")
        db.add_all([clinic, repair])
        db.flush()
        db.add_all([
            Branch(organization_id=clinic.id, name="Clinic branch", city="Самарканд", country_code="UZ"),
            Branch(organization_id=repair.id, name="Repair branch", city="Samarkand", country_code="UZ"),
            Branch(organization_id=repair.id, name="Outside starter list", city="Nukus", country_code="UZ"),
        ])
        db.commit()
    client = TestClient(app)
    categories = {row["code"]: row for row in client.get("/v1/public/service-categories").json()["items"]}
    for code in ("CLINIC", "DENTAL", "FITNESS", "TRAVEL_AGENCY", "DELIVERY", "CLEANING", "HOME_REPAIR", "LANGUAGE_SCHOOL"):
        assert code in categories and categories[code]["label"]
    path = "/v1/public/rated-organizations"
    for spelling in ("Samarkand", "Самарканд", "Samarqand"):
        data = client.get(path, params={"include_unrated": True, "country_code": "UZ", "city": spelling, "q": suffix, "category": "HEALTH"}).json()
        assert data["total"] == 1 and data["items"][0]["category"] == "CLINIC"
        uz = next(country for country in data["geography"] if country["country_code"] == "UZ")
        assert sum(city["city"] == "Samarkand" for city in uz["cities"]) == 1
        assert any(city["city"] == "Nukus" for city in uz["cities"])
    repairs = client.get(path, params={"include_unrated": True, "q": suffix, "category": "HOME_REPAIR"}).json()
    assert repairs["total"] == 2 and all(row["category"] == "HOME_REPAIR" for row in repairs["items"])


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
    region = client.get(path, params={"include_unrated": True, "q": suffix, "country_code": "UZ", "region_code": "10"}).json()
    assert region["total"] == 2 and all(row["region_code"] == "10" for row in region["items"])
    capital = client.get(path, params={"include_unrated": True, "q": suffix, "country_code": "UZ", "region_code": "13"}).json()
    assert capital["total"] == 1 and capital["items"][0]["city"] == "Tashkent"
    assert client.get(path, params={"include_unrated": True, "q": suffix, "country_code": "UZ", "region_code": "14"}).json()["total"] == 0
    assert client.get(path, params={"country_code": "KZ", "region_code": "10"}).status_code == 422
    first = client.get(path, params={"include_unrated": True, "q": suffix, "limit": 1}).json()
    second = client.get(path, params={"include_unrated": True, "q": suffix, "limit": 1, "offset": 1}).json()
    assert first["has_more"] and first["items"][0]["object_key"] != second["items"][0]["object_key"]
    rated = client.get(path, params={"include_unrated": True, "q": suffix, "score_type": "RATED"}).json()
    assert rated["total"] == 0
