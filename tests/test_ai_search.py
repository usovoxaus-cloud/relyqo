import uuid

import pytest
from fastapi.testclient import TestClient

from app import search
from app.ai import AIServiceError
from app.config import settings
from app.db import Base, engine
from app.main import app


@pytest.fixture
def client(monkeypatch):
    Base.metadata.create_all(engine)
    search._cache.clear()
    search._requests.clear()
    search._global_requests.clear()
    monkeypatch.setattr(settings, "openai_api_key", "test-only")
    return TestClient(app)


def test_country_selection_loads_source_cities_and_rejects_unknown_countries(client):
    data = client.get("/v1/public/search/cities?country_code=UZ").json()
    assert len(data["items"]) > 50 and data["source"] == "GeoNames"
    assert any(row["city"] == "Nukus" for row in data["items"])
    assert not any(row["city"] == "Istanbul" for row in data["items"])
    assert client.get("/v1/public/search/cities?country_code=XX").status_code == 422


def test_uzbekistan_regions_are_complete_and_cities_belong_to_the_selected_region(client, monkeypatch):
    from app.uzbekistan import DATA, region_for_city
    assert len(DATA["regions"]) == 14
    assert {row["region_code"] for row in DATA["cities"]} == {row["code"] for row in DATA["regions"]}
    for code, city in [("13", "Tashkent"), ("10", "Samarkand"), ("09", "Nukus")]:
        response = client.get("/v1/public/search/cities", params={"country_code": "UZ", "region_code": code})
        assert response.status_code == 200
        assert any(row["city"] == city for row in response.json()["items"])
        assert all(row["region_code"] == code for row in response.json()["items"])
    assert region_for_city("Toshkent", "UZ") == "13"
    assert region_for_city("Chirchiq", "UZ") == "14"
    assert region_for_city("Tashkent", "KZ") == ""
    assert client.get("/v1/public/search/cities?country_code=UZ&region_code=99").status_code == 422
    monkeypatch.setattr(search, "generate_search_plan", lambda ctx: {"city_ids": [], "terms": "стоматология", "category": "DENTAL"})
    body = {"country_code": "UZ", "region_code": "10", "city": "ALL", "query": "вылечить зуб"}
    plan = client.post("/v1/public/search/plan", json=body)
    assert plan.status_code == 200 and plan.json()["ai_generated"]
    assert plan.json()["text_query"].endswith(", Samarqand viloyati, UZ")
    assert client.post("/v1/public/search/plan", json={**body, "city": "Tashkent"}).status_code == 422
    assert client.post("/v1/public/search/plan", json={**body, "country_code": "KZ"}).status_code == 422


def test_ai_can_rank_only_existing_cities_of_selected_country_and_results_are_cached(client, monkeypatch):
    allowed = search.CITY_DATA["UZ"][0]["id"]
    foreign = search.CITY_DATA["TR"][0]["id"]
    calls = []

    def suggest(context):
        calls.append(context)
        return {"city_ids": [foreign, allowed, allowed, "invented-city"], "terms": "", "category": "ALL"}

    monkeypatch.setattr(search, "generate_search_plan", suggest)
    for _ in range(2):
        data = client.post("/v1/public/search/cities/recommend", json={"country_code": "UZ"}).json()
        assert data["recommended_ids"] == [allowed] and data["ai_generated"]
    assert len(calls) == 1


def test_ai_interprets_search_without_changing_explicit_location_or_category(client, monkeypatch):
    monkeypatch.setattr(search, "generate_search_plan", lambda context: {"city_ids": [], "terms": "стоматология для детей", "category": "DENTAL"})
    body = {"country_code": "UZ", "city": "Tashkent", "query": "вылечить зуб ребёнку"}
    data = client.post("/v1/public/search/plan", json=body).json()
    assert data["ai_generated"] and data["category"] == "DENTAL"
    assert data["text_query"].endswith(", Tashkent, UZ")
    assert data["city"]["latitude"] > 40
    explicit = client.post("/v1/public/search/plan", json={**body, "category": "CLINIC"}).json()
    assert explicit["category"] == "CLINIC"
    assert client.post("/v1/public/search/plan", json={**body, "city": "Istanbul"}).status_code == 422
    assert client.post("/v1/public/search/plan", json={**body, "category": "UNKNOWN"}).status_code == 422


def test_provider_failure_and_public_budget_leave_plain_search_available(client, monkeypatch):
    calls = []

    def fail(context):
        calls.append(context)
        raise AIServiceError("private provider credentials must not leak")

    monkeypatch.setattr(search, "generate_search_plan", fail)
    body = {"country_code": "UZ", "city": "Tashkent", "category": "CLEANING"}
    result = client.post("/v1/public/search/plan", json=body)
    assert result.status_code == 200
    assert not result.json()["ai_generated"] and "credentials" not in result.text
    assert "Клининг" in result.json()["text_query"]
    monkeypatch.setattr(search, "generate_search_plan", lambda context: {"city_ids": [], "terms": context["query"], "category": "ALL"})
    for _ in range(13):
        result = client.post("/v1/public/search/plan", json={**body, "query": uuid.uuid4().hex})
    assert result.json()["ai_status"] == "BUSY" and not result.json()["ai_generated"]
