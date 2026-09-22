"""Public AI search planning; grounded city choices, no generated businesses."""

import hashlib
import json
from collections import OrderedDict, deque
from pathlib import Path
from threading import Lock, BoundedSemaphore
from time import monotonic
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .ai import AIServiceError, AIUnavailableError, generate_search_plan
from .categories import category_catalog
from .config import settings
from .db import get_db

router = APIRouter(prefix="/v1/public/search")
CITY_DATA = json.loads((Path(__file__).parent / "static/search-cities.json").read_text())["countries"]
_cache = OrderedDict()
_requests = OrderedDict()
_lock = Lock()
_slots = BoundedSemaphore(2)
_global_requests = deque()


class CityChoice(BaseModel):
    country_code: str = Field(pattern="^[A-Z]{2}$")
    language: Literal["ru", "uz"] = "ru"


class SearchChoice(CityChoice):
    city: str = Field(min_length=1, max_length=80)
    category: str = Field(default="ALL", max_length=40)
    query: str = Field(default="", max_length=160)


def cities_for(country):
    if country not in CITY_DATA:
        raise HTTPException(422, "Выберите страну из списка")
    return CITY_DATA[country]


def cached_ai(key, request, context, fallback, ttl):
    now = monotonic()
    with _lock:
        cached = _cache.get(key)
        if cached and cached[0] > now:
            _cache.move_to_end(key)
            return {**cached[1], "cached": True}
    if not settings.openai_api_key:
        return {**fallback, "ai_generated": False, "ai_status": "NOT_CONFIGURED"}
    # Bound public-provider spend and concurrent work, without storing raw IPs.
    client = hashlib.sha256((settings.qr_secret + (request.client.host if request.client else "unknown")).encode()).hexdigest()
    with _lock:
        recent = [t for t in _requests.get(client, []) if now - t < 60]
        while _global_requests and now - _global_requests[0] >= 60:
            _global_requests.popleft()
        if len(recent) >= 12 or len(_global_requests) >= 40:
            return {**fallback, "ai_generated": False, "ai_status": "BUSY"}
        if not _slots.acquire(blocking=False):
            return {**fallback, "ai_generated": False, "ai_status": "BUSY"}
        _requests[client] = [*recent, now]
        _requests.move_to_end(client)
        while len(_requests) > 512:
            _requests.popitem(last=False)
        _global_requests.append(now)
    try:
        result = generate_search_plan(context)
        answer = {**result, "ai_generated": True, "ai_status": "OPENAI"}
    except (AIServiceError, AIUnavailableError):
        answer = {**fallback, "ai_generated": False, "ai_status": "TEMPORARY_ERROR"}
        ttl = 30
    finally:
        _slots.release()
    with _lock:
        _cache[key] = (now + ttl, answer)
        _cache.move_to_end(key)
        while len(_cache) > 256:
            _cache.popitem(last=False)
    return {**answer, "cached": False}


@router.get("/cities")
def search_cities(country_code: str):
    return {"country_code": country_code, "items": cities_for(country_code), "source": "GeoNames"}


@router.post("/cities/recommend")
def recommend_cities(body: CityChoice, request: Request):
    cities = cities_for(body.country_code)
    context = {
        "task": "cities", "country": body.country_code, "language": body.language,
        "cities": [{"id": row["id"], "name": row["city"]} for row in cities[:80]],
    }
    answer = cached_ai(("cities", body.country_code, body.language), request, context,
                       {"city_ids": [], "terms": "", "category": "ALL"}, 86400)
    allowed = {row["id"] for row in cities}
    ids = list(dict.fromkeys(str(value) for value in answer.get("city_ids", []) if str(value) in allowed))[:12]
    # A model may select from the source, never add unverified city names.
    return {"country_code": body.country_code, "recommended_ids": ids,
            "ai_generated": bool(answer["ai_generated"] and ids), "ai_status": answer["ai_status"]}


@router.post("/plan")
def plan_search(body: SearchChoice, request: Request, db: Session = Depends(get_db)):
    cities = cities_for(body.country_code)
    city = next((row for row in cities if row["city"] == body.city or row["id"] == body.city), None)
    if not city:
        raise HTTPException(422, "Выберите город выбранной страны")
    categories = {row["code"]: row["label"] for row in category_catalog(db)}
    if body.category != "ALL" and body.category != "FOOD" and body.category not in categories:
        raise HTTPException(422, "Выберите сферу услуг из списка")
    categories.update({"ALL": "организации и услуги", "FOOD": "рестораны и кафе"})
    fallback = {"terms": body.query.strip() or categories[body.category], "category": body.category, "city_ids": []}
    context = {"task": "search", "country": body.country_code, "city": city["city"],
               "category": body.category, "categories": categories, "query": body.query.strip(), "language": body.language}
    key = ("search", body.country_code, city["id"], body.category, body.query.strip().casefold(), body.language)
    answer = cached_ai(key, request, context, fallback, 900)
    terms = str(answer.get("terms") or fallback["terms"]).strip()[:160]
    category = answer.get("category") if body.category == "ALL" else body.category
    if category not in categories:
        category = body.category
    return {
        "text_query": f"{terms}, {city['city']}, {body.country_code}",
        "category": category, "city": city, "country_code": body.country_code,
        "ai_generated": answer["ai_generated"], "ai_status": answer["ai_status"],
        "cached": answer.get("cached", False),
    }
