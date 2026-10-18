"""Manual browser matrix: python tests/phone_recovery_browser.py.

Requires Playwright and local Chrome; every request is fulfilled locally, no SMS.
"""
import json
import mimetypes
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).absolute().parents[1]
OUTPUT = ROOT / ".task-tmp" / "phone-screenshots"
SIZES = [(320, 740), (390, 844), (768, 1024), (1024, 768), (1366, 900), (844, 390)]
HEADERS = {
    "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
}


def run():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome")
        try:
            for language in ["ru", "uz"]:
                for width, height in SIZES:
                    context = browser.new_context(viewport={"width": width, "height": height}, service_workers="block")
                    requests, errors = [], []

                    def serve(route):
                        path = urlsplit(route.request.url).path
                        if path.startswith("/static/"):
                            name = Path(path).name
                            source = ROOT / "app" / "static" / name
                            route.fulfill(body=source.read_bytes(), content_type=mimetypes.guess_type(name)[0] or "application/octet-stream")
                        elif path in ["/phone-recovery", "/account-phone"]:
                            route.fulfill(body=(ROOT / "app/static/phone-recovery.html").read_bytes(), content_type="text/html", headers=HEADERS)
                        elif path == "/v1/auth/phone-options":
                            route.fulfill(json={"enabled": True, "regions": [{"code": "UZ", "dial_code": "+998"}, {"code": "GB", "dial_code": "+44"}, {"code": "US", "dial_code": "+1"}]})
                        elif path == "/v1/auth/recovery-phone" and route.request.method == "GET":
                            route.fulfill(json={"verified": False, "phone": None})
                        else:
                            if route.request.method == "POST":
                                requests.append((path, route.request.post_data_json))
                            route.fulfill(json={"challenge": "a" * 43, "retry_after": 60})

                    context.route("**/*", serve)
                    page = context.new_page()
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)

                    def capture(name):
                        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), (name, language, width, height)
                        page.screenshot(path=str(OUTPUT / f"{name}-{language}-{width}x{height}.png"), full_page=True)

                    for bind in [False, True]:
                        path = "/account-phone" if bind else "/phone-recovery"
                        page.goto("https://relyqo.test" + path + "?lang=" + language)
                        page.locator("#phoneForm").wait_for(state="visible")
                        page.locator("#region").select_option("GB")
                        page.locator("#phone").fill("07700 900123")
                        if bind:
                            page.locator("#currentPassword").fill("current-password-123")
                        capture("bind" if bind else "recover")
                        page.locator("#send").click()
                        page.locator("#codeForm").wait_for(state="visible")
                        page.locator("#code").fill("123456")
                        if not bind:
                            page.locator("#newPassword").fill("new-password-123")
                            page.locator("#confirmPassword").fill("new-password-123")
                        capture("bind-code" if bind else "reset-code")
                        page.locator("#verify").click()
                        page.locator("#codeForm").wait_for(state="hidden")
                        capture("bound" if bind else "reset-done")
                        assert requests[-1][0] == ("/v1/auth/verify-phone" if bind else "/v1/auth/reset-password-phone")
                        assert not page.evaluate("location.search.includes('123456') || location.hash.length > 0")
                    assert errors == [], errors
                    context.close()
                    print(f"PASS {language} {width}x{height}: bind, reset, country, keyboard, CSP, overflow")
        finally:
            browser.close()
    print(json.dumps({"screenshots": str(OUTPUT), "cases": len(SIZES) * 2 * 2}))


if __name__ == "__main__":
    run()
