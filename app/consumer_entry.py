"""Consumer entry screens and validated return destinations."""
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import Cookie, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from .db import get_db
from .web_ui import STATIC

CONSUMER_PAGES = {
    "/", "/consumer", "/rate", "/nearby", "/community-rate", "/place",
    "/rankings", "/me", "/me/rating", "/me/requests", "/notifications",
}


def safe_destination(value: str) -> str:
    if re.search(r"[\\\x00-\x20\x7f]", value) or not value.startswith("/") or value.startswith("//"):
        return "/consumer"
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.path not in CONSUMER_PAGES:
        return "/consumer"
    return value


def entry_location(request: Request) -> str:
    destination = request.url.path
    if request.url.query:
        destination += "?" + request.url.query
    params = {"return_to": safe_destination(destination)}
    language = request.query_params.get("lang") or request.cookies.get("relyqo_language")
    if language in {"ru", "uz"}:
        params["lang"] = language
    return "/welcome?" + urlencode(params)


def require_consumer_page(request: Request, db: Session = Depends(get_db),
                          relyqo_session: str | None = Cookie(default=None)):
    # Import at request time to reuse the authoritative session checks without a cycle.
    from .main import session_user
    try:
        return session_user(relyqo_session, db, "CONSUMER")
    except HTTPException as error:
        if error.status_code not in {401, 403}:
            raise
        raise HTTPException(303, "Войдите в аккаунт", headers={
            "Location": entry_location(request), "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
        }) from error


def require_account_page(request: Request, db: Session = Depends(get_db),
                         relyqo_session: str | None = Cookie(default=None)):
    from .main import session_user
    try:
        return session_user(relyqo_session, db)
    except HTTPException as error:
        if error.status_code != 401:
            raise
        raise HTTPException(303, "Войдите в аккаунт", headers={
            "Location": entry_location(request), "Cache-Control": "no-store",
        }) from error


def register_consumer_entry(app, session_user):
    @app.get("/welcome", include_in_schema=False)
    def welcome(request: Request, db: Session = Depends(get_db),
                relyqo_session: str | None = Cookie(default=None)):
        headers = {"Cache-Control": "no-store, max-age=0", "Referrer-Policy": "no-referrer"}
        try:
            session_user(relyqo_session, db, "CONSUMER")
        except HTTPException as error:
            if error.status_code not in {401, 403}:
                raise
            return HTMLResponse((STATIC / "welcome.html").read_text(encoding="utf-8"), headers=headers)
        destination = safe_destination(request.query_params.get("return_to", "/consumer"))
        language = request.query_params.get("lang")
        if language in {"ru", "uz"}:
            parts = urlsplit(destination)
            query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key != "lang"]
            destination = urlunsplit(("", "", parts.path, urlencode(query + [("lang", language)]), parts.fragment))
        return RedirectResponse(destination, status_code=303, headers=headers)
