"""Translate interface messages only; user content and identifiers remain untouched."""

from contextvars import ContextVar
import json
from pathlib import Path
import re
from fastapi import Cookie, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Literal
from sqlalchemy.orm import Session
from .db import get_db

language_context = ContextVar("relyqo_language", default="ru")
_dictionary = json.loads(
    (Path(__file__).parent / "static" / "i18n-uz.json").read_text()
)
_keys = sorted(
    (
        key
        for key in _dictionary
        if re.search("[А-Яа-яЁё]", key) and "<" not in key and '">' not in key
    ),
    key=len,
    reverse=True,
)
_pattern = re.compile(
    r"(?<![\w])(?:" + "|".join(re.escape(key) for key in _keys) + r")(?![\w])"
)


def translate(value, language=None):
    if (language or language_context.get()) != "uz" or not isinstance(value, str):
        return value
    normalized = " ".join(value.split())
    return _dictionary.get(normalized) or _pattern.sub(
        lambda match: _dictionary[match.group()], value
    )


class LanguagePreference(BaseModel):
    language: Literal["ru", "uz"]


def register_i18n(app, session_user):
    @app.middleware("http")
    async def language(request, call_next):
        selected = (
            request.query_params.get("lang")
            or request.cookies.get("relyqo_language")
            or request.headers.get("accept-language", "").split(",")[0][:2]
        )
        selected = selected if selected in {"ru", "uz"} else "ru"
        token = language_context.set(selected)
        try:
            response = await call_next(request)
            response.headers["Content-Language"] = selected
            response.headers["Vary"] = ", ".join(
                filter(
                    None, [response.headers.get("Vary"), "Cookie", "Accept-Language"]
                )
            )
            return response
        finally:
            language_context.reset(token)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException):
        return JSONResponse(
            {"detail": translate(error.detail)},
            status_code=error.status_code,
            headers=error.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        # Avoid reflecting submitted passwords or tokens in Pydantic error payloads.
        return JSONResponse(
            {
                "detail": translate("Проверьте введённые данные."),
                "fields": [
                    ".".join(map(str, item["loc"][1:])) for item in error.errors()
                ],
            },
            status_code=422,
        )

    @app.post("/v1/auth/language")
    def preference(
        body: LanguagePreference,
        response: Response,
        relyqo_session: str | None = Cookie(default=None),
        db: Session = Depends(get_db),
    ):
        user = session_user(relyqo_session, db)
        user.language = body.language
        db.commit()
        response.headers["Cache-Control"] = "no-store"
        return {"language": user.language}
