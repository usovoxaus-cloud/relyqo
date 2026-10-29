"""Deterministic RU / Uzbek Latin and Cyrillic matching, without an AI call."""
import re
import unicodedata

CYRILLIC = dict(zip("абвгдеёзийклмнопрстуфхыэьъ", (
    "a", "b", "v", "g", "d", "e", "yo", "z", "i", "y", "k", "l", "m", "n",
    "o", "p", "r", "s", "t", "u", "f", "x", "i", "e", "", "",
)))
CYRILLIC.update({"ж": "j", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
                 "ю": "yu", "я": "ya", "ў": "o", "ғ": "g", "қ": "q", "ҳ": "h"})
ALIASES = {
    "FOOD": "ресторан кафе еда restoran kafe ovqat",
    "HOTEL": "гостиница отель mehmonxona hotel",
    "EDUCATION": "образование школа обучение maktab talim oquv",
    "HEALTH": "клиника здоровье больница klinika shifoxona sogliq",
    "BEAUTY": "салон красота парикмахерская salon gozallik sartarosh",
    "RETAIL": "магазин покупки dokon savdo",
    "AUTO_SERVICE": "автосервис авто ремонт avtoservis tamir",
    "ENTERTAINMENT": "развлечения отдых dam olish kongilochar",
    "PROFESSIONAL_SERVICE": "услуги xizmat professional",
}


def normalize_search(value):
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    value = "".join(CYRILLIC.get(char, char) for char in value)
    value = re.sub("['‘’ʻʼ`ʹ]", "", value)
    return " ".join(re.sub(r"[^\w]+", " ", value).split())


def search_matches(query, value):
    # Search accepts common Latin spellings of Cyrillic names. Do not change
    # normalize_search: duplicate detection still needs its existing semantics.
    def key(text):
        text = re.sub(r"c(?=[eiy])", "s", normalize_search(text))
        return re.sub(r"c(?!h)", "k", text).replace("x", "ks")

    searchable = key(value)
    compact = "".join(searchable.split())
    return all(token in searchable or token in compact for token in key(query).split())
