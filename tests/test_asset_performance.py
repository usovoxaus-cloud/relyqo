from fastapi.testclient import TestClient
from app.main import app


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
