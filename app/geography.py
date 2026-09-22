"""Starter locations for browsing, independent of organization coverage.

City keys are stable filter values. Labels/aliases never create organizations or
infer a missing country. Additional locations from public records are retained.
"""

COUNTRY_CITIES = {
    "UZ": [
        ("Tashkent", "Ташкент", "Toshkent"),
        ("Samarkand", "Самарканд", "Samarqand"),
        ("Bukhara", "Бухара", "Buxoro"),
        ("Namangan", "Наманган", "Namangan"),
        ("Andijan", "Андижан", "Andijon"),
    ],
    "KZ": [
        ("Almaty", "Алматы", "Olmaota"),
        ("Astana", "Астана", "Ostona"),
        ("Shymkent", "Шымкент", "Chimkent"),
        ("Karaganda", "Караганда", "Qarag‘anda"),
        ("Turkistan", "Туркестан", "Turkiston"),
    ],
    "KG": [
        ("Bishkek", "Бишкек", "Bishkek"),
        ("Osh", "Ош", "O‘sh"),
        ("Jalal-Abad", "Джалал-Абад", "Jalolobod"),
        ("Karakol", "Каракол", "Qorako‘l"),
        ("Tokmok", "Токмок", "To‘qmoq"),
    ],
    "TJ": [
        ("Dushanbe", "Душанбе", "Dushanbe"),
        ("Khujand", "Худжанд", "Xo‘jand"),
        ("Bokhtar", "Бохтар", "Boxtar"),
        ("Kulob", "Куляб", "Ko‘lob"),
        ("Istaravshan", "Истаравшан", "Istaravshan"),
    ],
    "AZ": [
        ("Баку", "Баку", "Boku"),
        ("Ganja", "Гянджа", "Ganja"),
        ("Sumgayit", "Сумгаит", "Sumqayit"),
        ("Sheki", "Шеки", "Sheki"),
        ("Lankaran", "Ленкорань", "Lankaron"),
    ],
    "GE": [
        ("Tbilisi", "Тбилиси", "Tbilisi"),
        ("Batumi", "Батуми", "Batumi"),
        ("Kutaisi", "Кутаиси", "Kutaisi"),
        ("Rustavi", "Рустави", "Rustavi"),
        ("Gori", "Гори", "Gori"),
    ],
    "TR": [
        ("Istanbul", "Стамбул", "Istanbul"),
        ("Ankara", "Анкара", "Anqara"),
        ("Antalya", "Анталья", "Antaliya"),
        ("Izmir", "Измир", "Izmir"),
        ("Bursa", "Бурса", "Bursa"),
    ],
    "AE": [
        ("Dubai", "Дубай", "Dubay"),
        ("Abu Dhabi", "Абу-Даби", "Abu-Dabi"),
        ("Sharjah", "Шарджа", "Sharja"),
        ("Ajman", "Аджман", "Ajman"),
        ("Ras Al Khaimah", "Рас-эль-Хайма", "Ras al-Xayma"),
    ],
}

CITY_ALIASES = {
    (country, alias.casefold()): key
    for country, cities in COUNTRY_CITIES.items()
    for key, ru, uz in cities
    for alias in (key, ru, uz)
}
CITY_ALIASES.update({("AZ", "baku"): "Баку", ("AZ", "bakı"): "Баку"})


def directory_city(value, country=""):
    value = " ".join((value or "").split())
    return CITY_ALIASES.get(((country or "").upper(), value.casefold()), value)


def location_catalog(items, *, include_starter=False):
    locations = {}
    if include_starter:
        for country, cities in COUNTRY_CITIES.items():
            locations[country] = {
                key: {"city": key, "label_ru": ru, "label_uz": uz, "card_count": 0}
                for key, ru, uz in cities
            }
    for item in items:
        country = item.get("country_code") or ""
        name = item.get("city") or ""
        cities = locations.setdefault(country, {})
        city = cities.setdefault(name, {"city": name, "card_count": 0})
        city["card_count"] += 1
    return [
        {
            "country_code": country,
            "card_count": sum(city["card_count"] for city in cities.values()),
            "cities": list(cities.values()),
        }
        for country, cities in locations.items()
    ]
