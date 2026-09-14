"""Email recovery for existing CONSUMER accounts; uses the normal users and sessions."""

from datetime import datetime, timedelta
import logging
import re
import secrets
import json
from urllib.request import Request as MailRequest, HTTPRedirectHandler, build_opener
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import BackgroundTasks, Cookie, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .config import settings
from .db import get_db, SessionLocal
from .models import (
    User,
    ConsumerEmail,
    PasswordRecoveryToken,
    RecoveryRateLimit,
    AuditLog,
)
from .security import password_hash, token_hash, verify_password

logger = logging.getLogger(__name__)
GENERIC = "Если адрес подтверждён в RELYQO, на него придёт письмо. Проверьте входящие и папку «Спам»."
INVALID = "Ссылка недействительна или срок её действия истёк. Запросите новое письмо."


class EmailRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        value = value.strip().lower()
        # Deliberately support common ASCII mailboxes, without ambiguous Unicode normalization.
        if not re.fullmatch(
            r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+",
            value,
        ):
            raise ValueError("Введите корректный email")
        return value


class BindEmail(EmailRequest):
    current_password: str = Field(min_length=8, max_length=200)


class TokenRequest(BaseModel):
    token: str = Field(min_length=40, max_length=100)


class ResetPassword(TokenRequest):
    new_password: str = Field(min_length=10, max_length=200)
    confirm_password: str = Field(min_length=10, max_length=200)


def recovery_origin():
    value = settings.public_base_url.rstrip("/")
    url = urlsplit(value)
    local = url.hostname in {"localhost", "127.0.0.1", "::1"}
    if (
        not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path
        or not (
            url.scheme == "https"
            or (local and url.scheme == "http" and settings.recovery_allow_local_urls)
        )
    ):
        raise ValueError("PUBLIC_BASE_URL must be a trusted HTTPS origin")
    return value


def require_mail_configuration():
    try:
        recovery_origin()
        if not settings.resend_api_key or not settings.recovery_email_from:
            raise ValueError("Recovery email not configured")
        EmailRequest(email=settings.recovery_email_from)
    except ValueError:
        raise HTTPException(
            503, "Отправка писем временно недоступна. Попробуйте позже."
        )


class NoMailRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the email API credential to a redirect target.
        return None


def send_email(address, subject, text):
    request = MailRequest(
        "https://api.resend.com/emails",
        data=json.dumps(
            {
                "from": settings.recovery_email_from,
                "to": [address],
                "subject": subject,
                "text": text,
            }
        ).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + settings.resend_api_key,
            "Content-Type": "application/json",
            "User-Agent": "RELYQO-Recovery/1",
        },
        method="POST",
    )
    with build_opener(NoMailRedirect()).open(request, timeout=10) as response:
        if response.status not in {200, 201, 202} or not json.load(response).get("id"):
            raise RuntimeError("Email provider did not accept the message")


def limited(db, scope, identifier, maximum):
    now = datetime.utcnow()
    window = now.replace(minute=0, second=0, microsecond=0)
    key = token_hash(f"{scope}:{identifier}:{window.isoformat()}")
    # Atomic DB-backed counters shared between processes, no plaintext IP/email stored here.
    if db.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    statement = insert(RecoveryRateLimit).values(
        key=key, count=1, expires_at=window + timedelta(hours=1)
    )
    count = db.scalar(
        statement.on_conflict_do_update(
            index_elements=["key"], set_={"count": RecoveryRateLimit.count + 1}
        ).returning(RecoveryRateLimit.count)
    )
    db.execute(delete(RecoveryRateLimit).where(RecoveryRateLimit.expires_at < now))
    db.commit()
    return count > maximum


def ip_limit(db, request):
    # Trust only the ASGI client address; deployment must trust forwarded headers only from its proxy.
    ip = request.client.host if request.client else "unknown"
    if limited(db, "recovery-ip", ip, 30):
        raise HTTPException(
            429,
            "Слишком много попыток. Попробуйте через час.",
            headers={"Retry-After": "3600"},
        )


def issue_email(user_id, email, purpose, fingerprint=None):
    """Run after the uniform HTTP response. Tokens never enter logs or API responses."""
    with SessionLocal() as db:
        user = (
            db.get(User, user_id)
            if user_id
            else db.scalar(
                select(User)
                .join(ConsumerEmail, ConsumerEmail.user_id == User.id)
                .where(ConsumerEmail.email == email)
            )
        )
        if not user or not user.active or user.role != "CONSUMER":
            return
        if fingerprint and token_hash(user.password_hash) != fingerprint:
            return
        if purpose == "reset":
            verified = db.get(ConsumerEmail, user.id)
            if not verified or verified.email != email:
                return
        now = datetime.utcnow()
        raw = secrets.token_urlsafe(32)
        token = PasswordRecoveryToken(
            token_hash=token_hash(raw),
            user_id=user.id,
            email=email,
            purpose=purpose,
            password_fingerprint=token_hash(user.password_hash),
            expires_at=now + timedelta(minutes=30),
        )
        db.execute(
            delete(PasswordRecoveryToken).where(
                PasswordRecoveryToken.expires_at < now - timedelta(days=1)
            )
        )
        db.add(token)
        db.commit()
        route = "reset-password" if purpose == "reset" else "verify-email"
        title = (
            "Сброс пароля RELYQO" if purpose == "reset" else "Подтвердите email RELYQO"
        )
        link = f"{recovery_origin()}/{route}#token={raw}"
        try:
            send_email(
                email,
                title,
                f"{title}\n\nОткройте ссылку в течение 30 минут:\n{link}\n\nЕсли вы не запрашивали это письмо, проигнорируйте его. Никому не передавайте ссылку.",
            )
        except Exception:
            db.execute(
                update(PasswordRecoveryToken)
                .where(PasswordRecoveryToken.token_hash == token.token_hash)
                .values(consumed_at=now)
            )
            db.commit()
            logger.error("Recovery email delivery failed; token invalidated")


def notify_reset(email):
    try:
        send_email(
            email,
            "Пароль RELYQO изменён",
            "Пароль вашего аккаунта RELYQO изменён. Все прежние сессии завершены. Если это были не вы, запросите восстановление на сайте RELYQO.",
        )
    except Exception:
        logger.error("Password change notification delivery failed")


def consume_token(db, raw, purpose):
    now = datetime.utcnow()
    token = db.get(PasswordRecoveryToken, token_hash(raw))
    if (
        not token
        or token.purpose != purpose
        or token.consumed_at
        or token.expires_at <= now
    ):
        raise HTTPException(400, INVALID)
    user = db.scalar(select(User).where(User.id == token.user_id).with_for_update())
    if (
        not user
        or not user.active
        or user.role != "CONSUMER"
        or token.password_fingerprint != token_hash(user.password_hash)
    ):
        raise HTTPException(400, INVALID)
    result = db.execute(
        update(PasswordRecoveryToken)
        .where(
            PasswordRecoveryToken.token_hash == token.token_hash,
            PasswordRecoveryToken.consumed_at.is_(None),
            PasswordRecoveryToken.expires_at > now,
        )
        .values(consumed_at=now)
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(400, INVALID)
    return user, token


def register_recovery_routes(app, session_user, revoke_user_sessions):
    @app.middleware("http")
    async def recovery_response_headers(request, call_next):
        response = await call_next(request)
        if request.url.path in {
            "/v1/auth/recovery-email",
            "/v1/auth/forgot-password",
            "/v1/auth/verify-email",
            "/v1/auth/reset-password",
        }:
            response.headers["Cache-Control"] = "no-store, max-age=0"
            response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/v1/auth/recovery-email")
    def email_status(
        response: Response,
        relyqo_session: str | None = Cookie(default=None),
        db: Session = Depends(get_db),
    ):
        user = session_user(relyqo_session, db, "CONSUMER")
        email = db.get(ConsumerEmail, user.id)
        response.headers["Cache-Control"] = "no-store"
        return {"email": email.email if email else None, "verified": bool(email)}

    @app.post("/v1/auth/recovery-email", status_code=202)
    def bind_email(
        body: BindEmail,
        request: Request,
        response: Response,
        tasks: BackgroundTasks,
        relyqo_session: str | None = Cookie(default=None),
        db: Session = Depends(get_db),
    ):
        user = session_user(relyqo_session, db, "CONSUMER")
        require_mail_configuration()
        ip_limit(db, request)
        if limited(db, "bind-user", user.id, 3):
            raise HTTPException(429, "Слишком много попыток. Попробуйте через час.")
        if not verify_password(body.current_password, user.password_hash):
            raise HTTPException(401, "Текущий пароль указан неверно")
        if limited(db, "mail-email", body.email, 3):
            raise HTTPException(429, "Слишком много писем. Попробуйте через час.")
        tasks.add_task(
            issue_email, user.id, body.email, "verify", token_hash(user.password_hash)
        )
        response.headers["Cache-Control"] = "no-store"
        return {
            "message": "Запрос принят. Откройте ссылку в письме, чтобы подтвердить адрес."
        }

    @app.post("/v1/auth/forgot-password", status_code=202)
    def forgot(
        body: EmailRequest,
        request: Request,
        response: Response,
        tasks: BackgroundTasks,
        db: Session = Depends(get_db),
    ):
        require_mail_configuration()
        ip_limit(db, request)
        if not limited(db, "mail-email", body.email, 3):
            tasks.add_task(issue_email, None, body.email, "reset")
        response.headers["Cache-Control"] = "no-store"
        return {"message": GENERIC}

    @app.post("/v1/auth/verify-email")
    def verify_email(
        body: TokenRequest,
        request: Request,
        response: Response,
        db: Session = Depends(get_db),
    ):
        ip_limit(db, request)
        user, token = consume_token(db, body.token, "verify")
        email = db.get(ConsumerEmail, user.id)
        if email:
            email.email = token.email
            email.verified_at = datetime.utcnow()
        else:
            db.add(ConsumerEmail(user_id=user.id, email=token.email))
        try:
            db.execute(
                update(PasswordRecoveryToken)
                .where(PasswordRecoveryToken.user_id == user.id)
                .values(consumed_at=datetime.utcnow())
            )
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                400, "Не удалось подтвердить адрес. Укажите другую почту в кабинете."
            )
        response.headers["Cache-Control"] = "no-store"
        return {
            "message": "Email подтверждён. Теперь он доступен для восстановления пароля."
        }

    @app.post("/v1/auth/reset-password")
    def reset(
        body: ResetPassword,
        request: Request,
        response: Response,
        tasks: BackgroundTasks,
        db: Session = Depends(get_db),
    ):
        ip_limit(db, request)
        if body.new_password != body.confirm_password:
            raise HTTPException(422, "Пароли не совпадают")
        user, token = consume_token(db, body.token, "reset")
        email = db.get(ConsumerEmail, user.id)
        if not email or email.email != token.email:
            db.rollback()
            raise HTTPException(400, INVALID)
        old_hash = user.password_hash
        result = db.execute(
            update(User)
            .where(User.id == user.id, User.password_hash == old_hash)
            .values(
                password_hash=password_hash(body.new_password),
                failed_login_attempts=0,
                locked_until=None,
            )
        )
        if result.rowcount != 1:
            db.rollback()
            raise HTTPException(400, INVALID)
        revoke_user_sessions(user.id, db)
        db.execute(
            update(PasswordRecoveryToken)
            .where(PasswordRecoveryToken.user_id == user.id)
            .values(consumed_at=datetime.utcnow())
        )
        db.add(
            AuditLog(
                actor_type="CONSUMER",
                action="AUTH_PASSWORD_RECOVERED",
                entity_type="USER",
                entity_id=user.id,
            )
        )
        db.commit()
        response.delete_cookie("relyqo_session", path="/")
        response.headers["Cache-Control"] = "no-store"
        tasks.add_task(notify_reset, token.email)
        return {
            "message": "Пароль изменён. Войдите с новым паролем. Все прежние сессии завершены."
        }

    def recovery_page():
        return FileResponse(
            Path(__file__).parent / "static" / "password-recovery.html",
            headers={
                "Cache-Control": "no-store, max-age=0",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
            },
        )

    for path in ["/forgot-password", "/reset-password", "/verify-email"]:
        app.add_api_route(path, recovery_page, methods=["GET"], include_in_schema=False)
