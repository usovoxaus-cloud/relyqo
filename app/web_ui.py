"""Shared consumer page shell; business and administration use separate navigation."""
from pathlib import Path

from fastapi.responses import HTMLResponse

from .config import settings

STATIC = Path(__file__).parent / "static"
CONSUMER_TABS = (
    ("search", "/consumer", "Найти"),
    ("rate", "/rate", "Оценить"),
    ("account", "/me", "Профиль"),
)


def consumer_html(filename: str, *, active_tab: str | None = None) -> HTMLResponse:
    content = (STATIC / filename).read_text(encoding="utf-8")
    active = "rate" if filename in {"index.html", "community-rate.html"} else (
        "account" if filename in {"me.html", "rating-detail.html"} else "search"
    )
    if active_tab in {key for key, _, _ in CONSUMER_TABS}:
        active = active_tab
    links = "".join(
        f'<a href="{href}"' + (' aria-current="page"' if key == active else "")
        + f'>{label}</a>' for key, href, label in CONSUMER_TABS
    )
    navigation = (
        '<header class="consumerHeader"><a class="consumerBrand" href="/consumer">'
        '<span aria-hidden="true">R</span>RELYQO</a>'
        '<nav class="consumerNav" aria-label="Основная навигация">'
        + links + '</nav></header>'
    )
    content = content.replace("<!--consumer-navigation-->", navigation)
    if filename == "index.html" and not settings.demo_mode:
        content = content.replace(
            'id="demo" class="secondary"',
            'id="demo" class="secondary hidden" disabled aria-hidden="true"', 1,
        )
    content = content.replace(
        "</head>", '<link rel="stylesheet" href="/static/consumer-nav.css?v=1">'
        '<link rel="stylesheet" href="/static/engagement.css?v=1"><script src="/static/engagement.js?v=release-20261005" defer></script>'
        '<link rel="stylesheet" href="/static/ads.css?v=ads-3"></head>', 1,
    ).replace(
        "</body>", '<script src="/static/ads.js?v=ads-3"></script></body>', 1,
    )
    return HTMLResponse(content, headers={"Cache-Control": "no-store, max-age=0"})

