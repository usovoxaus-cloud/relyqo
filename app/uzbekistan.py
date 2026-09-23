"""Source-backed Uzbekistan search regions; no synthetic business records."""
import json
import unicodedata
from pathlib import Path

DATA = json.loads((Path(__file__).parent / "static/uzbekistan.json").read_text())
REGIONS = {row["code"]: row for row in DATA["regions"]}
CITIES = DATA["cities"]


def location_key(value):
    return "".join(c for c in unicodedata.normalize("NFKD", value or "").casefold() if c.isalnum())


_aliases = {}
for city in CITIES:
    for alias in [city["city"], *city["aliases"]]:
        _aliases.setdefault(location_key(alias), set()).add(city["region_code"])


def region_for_city(city, country):
    if country != "UZ":
        return ""
    codes = _aliases.get(location_key(city), set())
    return next(iter(codes)) if len(codes) == 1 else ""
