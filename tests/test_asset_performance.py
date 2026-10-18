from fastapi.testclient import TestClient
from app.main import app
from app.static_assets import StaticAssets, assets
from app.web_ui import consumer_html
from hashlib import sha256
from html import unescape
import re
from urllib.parse import parse_qs, urlsplit


def test_public_assets_cache_and_revalidate_without_cookie_variants():
    client = TestClient(app)
    first = client.get("/static/nearby.js", headers={"Accept-Language": "uz"})
    assert first.status_code == 200
    assert first.headers["cache-control"] == "public, max-age=300, must-revalidate"
    assert "cookie" not in first.headers.get("vary", "").lower()
    assert "accept-language" not in first.headers.get("vary", "").lower()
    second = client.get(
        "/static/nearby.js", headers={"If-None-Match": first.headers["etag"]}
    )
    assert second.status_code == 304 and second.content == b""
    assert second.headers["cache-control"] == first.headers["cache-control"]
    assert first.headers["server-timing"].startswith("app;dur=")


def test_pages_and_private_api_do_not_acquire_public_caching():
    client = TestClient(app)
    for path in ["/nearby", "/admin/control", "/me", "/v1/admin/control/feedback"]:
        response = client.get(path)
        assert "public" not in response.headers.get("cache-control", "")
        if path.startswith("/v1/"):
            assert response.status_code == 401
        else:
            assert response.status_code == 200
            assert "no-store" in response.headers["cache-control"]
    response = client.get("/static/missing.js")
    assert response.status_code == 404
    assert "public" not in response.headers.get("cache-control", "")


def test_entry_and_consumer_assets_have_content_urls_and_immutable_responses():
    client = TestClient(app)
    entry = client.get("/welcome")
    consumer = consumer_html("nearby.html")
    for content, headers in [(entry.text, entry.headers), (consumer.body.decode(), consumer.headers)]:
        assert "no-store" in headers["cache-control"]
        urls = re.findall(r'(?:src|href|content)="(/static/[^\"]+)"', content)
        assert len(urls) >= 4
        for value in urls:
            url = unescape(value)
            parts = urlsplit(url)
            version = parse_qs(parts.query)["v"]
            response = client.get(url)
            assert response.status_code == 200
            assert version == [sha256(response.content).hexdigest()]
            assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
            assert "cookie" not in response.headers.get("vary", "").lower()
            again = client.get(url, headers={"If-None-Match": response.headers["etag"]})
            assert again.status_code == 304
            assert again.headers["cache-control"] == response.headers["cache-control"]


def test_modified_assets_get_new_urls_and_old_hashes_are_not_cached(tmp_path):
    file = tmp_path / "app.js"
    file.write_bytes(b"first")
    manifest = StaticAssets(tmp_path)
    first = manifest.url("/static/app.js?v=manual&other=1#anchor")
    file.write_bytes(b"second-version")
    second = manifest.url("/static/app.js?v=manual&other=1#anchor")
    assert first != second
    assert "other=1" in second and second.endswith("#anchor")
    old = parse_qs(urlsplit(first).query)["v"]
    current = parse_qs(urlsplit(second).query)["v"]
    assert manifest.cache_control("/static/app.js", old) == "no-store"
    assert "immutable" in manifest.cache_control("/static/app.js", current)
    assert manifest.cache_control("/static/app.js", current * 2) == "no-store"
    file.unlink()
    assert manifest.url("/static/app.js") == "/static/app.js"


def test_untrusted_or_non_asset_urls_never_gain_immutable_caching():
    client = TestClient(app)
    for value in [
        "/static/../main.py", "/static/%2e%2e/main.py", "/static/welcome.html",
        "/static/sw.js", "/v1/auth/me", "//evil.test/static/nearby.js",
        "https://evil.test/static/nearby.js", "/static/missing.js",
    ]:
        assert assets.url(value) == value
    stale = client.get("/static/nearby.js?v=" + "0" * 64)
    assert stale.status_code == 200 and stale.headers["cache-control"] == "no-store"
    for path in ["/static/welcome.html", "/sw.js", "/v1/auth/me", "/welcome"]:
        response = client.get(path + "?v=" + assets.digest("/static/nearby.js"))
        assert "immutable" not in response.headers.get("cache-control", "")


def test_versioning_preserves_markup_and_unrelated_links(tmp_path):
    (tmp_path / "app.js").write_text("fixture", encoding="utf-8")
    manifest = StaticAssets(tmp_path)
    text = "<head><script src='/static/app.js?v=1&amp;x=2'></script></head>" \
        '<body><a href="/static/app.js?v=1">Download</a>' \
        '<script src="https://other.test/static/app.js"></script></body>'
    result = manifest.html(text)
    assert "&amp;v=" in result
    assert '<a href="/static/app.js?v=1">Download</a>' in result
    assert '<script src="https://other.test/static/app.js"></script>' in result
