"""International SMS recovery; only a verified personal phone can reset a password.

Eskiz codes are checked against a keyed digest; Twilio Verify checks its own codes.
This module never persists plaintext codes.
The public request response is independent of account existence and delivery.
"""

import base64
from datetime import datetime, timedelta
import hashlib
import hmac
import json
import logging
from pathlib import Path
import re
import secrets
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request as SMSRequest, build_opener

import phonenumbers
from fastapi import BackgroundTasks, Cookie, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import settings
from . import sms_eskiz
from .db import SessionLocal, get_db
from .models import (
    AccountPhone,
    AuditLog,
    PhoneChallenge,
    PasswordRecoveryToken,
    RecoveryRateLimit,
    User,
)
from .password_recovery import (
    EMAIL_RECOVERY_ROLES,
    NoMailRedirect,
    password_fingerprint,
)
from .security import password_hash, token_hash, verify_password

logger = logging.getLogger(__name__)
INVALID = "Код недействителен или истёк. Запросите новый SMS-код."
UNAVAILABLE = "SMS пока недоступны. Используйте email или резервный код."
GENERIC = (
    "Если номер подтверждён в аккаунте, на него придёт SMS. Код действует до 10 минут."
)


def regions():
    allowed = (
        set(settings.sms_allowed_regions.upper().replace(" ", "").split(","))
        & phonenumbers.SUPPORTED_REGIONS
    )
    # The selected Eskiz integration uses its domestic endpoint, not international SMS.
    return allowed & {"UZ"} if settings.sms_provider == "eskiz" else allowed


def configured():
    if settings.sms_provider == "eskiz":
        return bool(sms_eskiz.configured() and regions())
    return bool(
        settings.sms_provider == "twilio"
        and re.fullmatch(r"AC[0-9a-fA-F]{32}", settings.twilio_account_sid)
        and settings.twilio_auth_token
        and re.fullmatch(r"VA[0-9a-fA-F]{32}", settings.twilio_verify_service_sid)
        and regions()
    )


def require_config():
    if not configured():
        raise HTTPException(503, UNAVAILABLE)


class PhoneRequest(BaseModel):
    phone: str = Field(min_length=5, max_length=40)
    region: str = Field(pattern=r"^[A-Z]{2}$")

    @model_validator(mode="after")
    def normalize(self):
        try:
            if self.region not in phonenumbers.SUPPORTED_REGIONS or not re.fullmatch(
                r"[+0-9 ()\-]+", self.phone
            ):
                raise ValueError()
            number = phonenumbers.parse(self.phone, self.region)
            if number.extension or not phonenumbers.is_valid_number_for_region(
                number, self.region
            ):
                raise ValueError()
            self.phone = phonenumbers.format_number(
                number, phonenumbers.PhoneNumberFormat.E164
            )
        except (ValueError, phonenumbers.NumberParseException):
            raise ValueError("Проверьте страну и номер телефона.")
        return self


class BindPhone(PhoneRequest):
    current_password: str = Field(min_length=8, max_length=200)


class CheckPhone(BaseModel):
    challenge: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    code: str = Field(pattern=r"^[0-9]{4,10}$")


class ResetPhone(CheckPhone):
    new_password: str = Field(min_length=10, max_length=200)
    confirm_password: str = Field(min_length=10, max_length=200)


def provider_request(resource, fields):
    require_config()
    credential = base64.b64encode(
        f"{settings.twilio_account_sid}:{settings.twilio_auth_token}".encode()
    ).decode()
    request = SMSRequest(
        f"https://verify.twilio.com/v2/Services/{settings.twilio_verify_service_sid}/{resource}",
        data=urlencode(fields).encode("ascii"),
        headers={
            "Authorization": f"Basic {credential}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    # Never forward a provider credential on redirects or log response bodies.
    with build_opener(NoMailRedirect()).open(request, timeout=10) as response:
        return json.load(response)


def otp_digest(challenge, code):
    # A database dump alone must not allow enumerating the one million possible codes.
    # Binding the digest to this challenge prevents moving proofs between accounts.
    message = json.dumps(
        [
            "eskiz-otp-v1",
            challenge.token_hash,
            challenge.user_id,
            challenge.phone,
            challenge.purpose,
            challenge.password_fingerprint,
            code,
        ],
        separators=(",", ":"),
    )
    return hmac.new(
        settings.sms_otp_secret.encode(), message.encode(), hashlib.sha256
    ).hexdigest()


def provider_start(phone):
    result = provider_request("Verifications", {"To": phone, "Channel": "sms"})
    if not (
        result.get("status") == "pending"
        and result.get("to") == phone
        and result.get("service_sid") == settings.twilio_verify_service_sid
        and re.fullmatch(r"VE[0-9a-fA-F]{32}", result.get("sid", ""))
    ):
        raise ValueError("SMS provider rejected verification")
    return result["sid"]


def provider_check(sid, phone, code):
    try:
        result = provider_request(
            "VerificationCheck", {"VerificationSid": sid, "Code": code}
        )
    except HTTPError as error:
        if error.code in {400, 404, 429}:
            return False
        raise
    return (
        result.get("status") == "approved"
        and result.get("sid") == sid
        and result.get("to") == phone
        and result.get("channel") == "sms"
        and result.get("service_sid") == settings.twilio_verify_service_sid
    )


def limited(db, scope, identifier, maximum, seconds=3600):
    now = datetime.utcnow()
    epoch = datetime(1970, 1, 1)
    window = int((now - epoch).total_seconds()) // seconds
    key = token_hash(f"sms:{scope}:{identifier}:{seconds}:{window}")
    if db.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    statement = insert(RecoveryRateLimit).values(
        key=key, count=1, expires_at=epoch + timedelta(seconds=(window + 1) * seconds)
    )
    count = db.scalar(
        statement.on_conflict_do_update(
            index_elements=["key"], set_={"count": RecoveryRateLimit.count + 1}
        ).returning(RecoveryRateLimit.count)
    )
    db.execute(delete(RecoveryRateLimit).where(RecoveryRateLimit.expires_at < now))
    db.execute(
        delete(PhoneChallenge).where(
            PhoneChallenge.expires_at < now - timedelta(days=1)
        )
    )
    db.commit()
    return count > maximum


def ip_limit(db, request):
    if limited(db, "ip", request.client.host if request.client else "unknown", 30):
        raise HTTPException(
            429,
            "Слишком много попыток. Попробуйте через час.",
            headers={"Retry-After": "3600"},
        )


def issue_sms(raw, phone, purpose, user_id=None, fingerprint=None):
    try:
        require_config()
        with SessionLocal() as db:
            if purpose == "reset":
                account = db.scalar(
                    select(AccountPhone).where(AccountPhone.phone == phone)
                )
                if not account:
                    return
                user_id = account.user_id
            user = db.get(User, user_id)
            if not user or not user.active or user.role not in EMAIL_RECOVERY_ROLES:
                return
            current = password_fingerprint(user)
            if fingerprint and current != fingerprint:
                return
            if purpose == "bind":
                owner = db.scalar(
                    select(AccountPhone).where(AccountPhone.phone == phone)
                )
                if owner and owner.user_id != user.id:
                    return
            if limited(db, "budget-hour", "all", 100) or limited(
                db, "budget-day", "all", 500, 86400
            ):
                return
            now = datetime.utcnow()
            db.execute(
                update(PhoneChallenge)
                .where(
                    PhoneChallenge.user_id == user_id, PhoneChallenge.purpose == purpose
                )
                .values(consumed_at=now)
            )
            challenge = PhoneChallenge(
                token_hash=token_hash(raw),
                user_id=user_id,
                phone=phone,
                purpose=purpose,
                password_fingerprint=current,
                provider=settings.sms_provider,
                expires_at=now + timedelta(minutes=10),
            )
            db.add(challenge)
            db.commit()
            if challenge.provider == "eskiz":
                code = f"{secrets.randbelow(1000000):06d}"
                digest = otp_digest(challenge, code)
                sms_eskiz.send_code(phone, code)
                proof = {"code_digest": digest}
            else:
                proof = {"verification_sid": provider_start(phone)}
            db.execute(
                update(PhoneChallenge)
                .where(
                    PhoneChallenge.token_hash == token_hash(raw),
                    PhoneChallenge.consumed_at.is_(None),
                )
                .values(**proof)
            )
            db.commit()
    except Exception:
        # No phone, code, credentials or raw provider exception in logs.
        logger.warning("SMS verification delivery failed")


def check_challenge(db, body, purpose, owner_id=None):
    require_config()
    now = datetime.utcnow()
    challenge_id = token_hash(body.challenge)
    condition = [
        PhoneChallenge.token_hash == challenge_id,
        PhoneChallenge.purpose == purpose,
        PhoneChallenge.consumed_at.is_(None),
        PhoneChallenge.expires_at > now,
        PhoneChallenge.attempts < 5,
        PhoneChallenge.provider == settings.sms_provider,
        or_(
            and_(
                PhoneChallenge.provider == "twilio",
                PhoneChallenge.verification_sid.is_not(None),
            ),
            and_(
                PhoneChallenge.provider == "eskiz",
                PhoneChallenge.code_digest.is_not(None),
            ),
        ),
    ]
    if owner_id:
        condition.append(PhoneChallenge.user_id == owner_id)
    count = db.execute(
        update(PhoneChallenge)
        .where(*condition)
        .values(attempts=PhoneChallenge.attempts + 1)
    ).rowcount
    db.commit()  # Failed checks must spend an attempt, even on provider/network errors.
    if count != 1:
        raise HTTPException(400, INVALID)
    challenge = db.get(PhoneChallenge, challenge_id)
    sid, phone = challenge.verification_sid, challenge.phone
    try:
        if challenge.provider == "eskiz":
            approved = len(body.code) == 6 and hmac.compare_digest(
                otp_digest(challenge, body.code), challenge.code_digest
            )
        else:
            approved = provider_check(sid, phone, body.code)
    except Exception:
        logger.warning("SMS verification check unavailable")
        raise HTTPException(503, UNAVAILABLE)
    if not approved:
        raise HTTPException(400, INVALID)
    db.expire_all()
    user = db.scalar(select(User).where(User.id == challenge.user_id).with_for_update())
    if (
        not user
        or not user.active
        or user.role not in EMAIL_RECOVERY_ROLES
        or password_fingerprint(user) != challenge.password_fingerprint
    ):
        db.rollback()
        raise HTTPException(400, INVALID)
    claimed = db.execute(
        update(PhoneChallenge)
        .where(
            PhoneChallenge.token_hash == challenge_id,
            PhoneChallenge.consumed_at.is_(None),
            PhoneChallenge.expires_at > datetime.utcnow(),
        )
        .values(consumed_at=datetime.utcnow())
    ).rowcount
    if claimed != 1:
        db.rollback()
        raise HTTPException(400, INVALID)
    # Verify may reuse a SID during its validity window. Approval can be used once.
    if sid:
        db.execute(
            update(PhoneChallenge)
            .where(
                PhoneChallenge.provider == "twilio",
                PhoneChallenge.verification_sid == sid,
            )
            .values(consumed_at=datetime.utcnow())
        )
    return user, challenge


def register_phone_routes(app, session_user, revoke_user_sessions):
    @app.middleware("http")
    async def phone_headers(request, call_next):
        response = await call_next(request)
        if request.url.path in {
            "/v1/auth/phone-options",
            "/v1/auth/recovery-phone",
            "/v1/auth/verify-phone",
            "/v1/auth/forgot-password-phone",
            "/v1/auth/reset-password-phone",
        }:
            response.headers["Cache-Control"] = "no-store, max-age=0"
            response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/v1/auth/phone-options")
    def options():
        return {
            "enabled": configured(),
            "regions": [
                {
                    "code": region,
                    "dial_code": f"+{phonenumbers.country_code_for_region(region)}",
                }
                for region in sorted(regions())
            ],
        }

    @app.get("/v1/auth/recovery-phone")
    def status(
        relyqo_session: str | None = Cookie(default=None), db: Session = Depends(get_db)
    ):
        user = session_user(relyqo_session, db, EMAIL_RECOVERY_ROLES)
        phone = db.get(AccountPhone, user.id)
        return {"verified": bool(phone), "phone": phone.phone if phone else None}

    def request_sms(body, request, tasks, db, user=None):
        require_config()
        if body.region not in regions():
            raise HTTPException(422, "SMS для этой страны пока недоступны.")
        ip_limit(db, request)
        if user:
            if limited(db, "bind-user", user.id, 5):
                raise HTTPException(429, "Слишком много попыток. Попробуйте через час.")
            if not verify_password(body.current_password, user.password_hash):
                raise HTTPException(401, "Текущий пароль указан неверно")
        raw = secrets.token_urlsafe(32)
        if not limited(db, "phone-minute", body.phone, 1, 60) and not limited(
            db, "phone-hour", body.phone, 3
        ):
            tasks.add_task(
                issue_sms,
                raw,
                body.phone,
                "bind" if user else "reset",
                user.id if user else None,
                password_fingerprint(user) if user else None,
            )
        return {
            "challenge": raw,
            "message": GENERIC
            if not user
            else "Запрос принят. Введите код из SMS для подтверждения номера.",
            "retry_after": 60,
        }

    @app.post("/v1/auth/recovery-phone", status_code=202)
    def bind(
        body: BindPhone,
        request: Request,
        tasks: BackgroundTasks,
        relyqo_session: str | None = Cookie(default=None),
        db: Session = Depends(get_db),
    ):
        user = session_user(relyqo_session, db, EMAIL_RECOVERY_ROLES)
        return request_sms(body, request, tasks, db, user)

    @app.post("/v1/auth/forgot-password-phone", status_code=202)
    def forgot(
        body: PhoneRequest,
        request: Request,
        tasks: BackgroundTasks,
        db: Session = Depends(get_db),
    ):
        return request_sms(body, request, tasks, db)

    @app.post("/v1/auth/verify-phone")
    def verify(
        body: CheckPhone,
        request: Request,
        relyqo_session: str | None = Cookie(default=None),
        db: Session = Depends(get_db),
    ):
        owner = session_user(relyqo_session, db, EMAIL_RECOVERY_ROLES)
        ip_limit(db, request)
        user, challenge = check_challenge(db, body, "bind", owner.id)
        phone = db.get(AccountPhone, user.id)
        if phone:
            phone.phone, phone.verified_at = challenge.phone, datetime.utcnow()
        else:
            db.add(AccountPhone(user_id=user.id, phone=challenge.phone))
        try:
            db.execute(
                update(PhoneChallenge)
                .where(PhoneChallenge.user_id == user.id)
                .values(consumed_at=datetime.utcnow())
            )
            db.add(
                AuditLog(
                    actor_type=user.role,
                    action="AUTH_PHONE_VERIFIED",
                    entity_type="USER",
                    entity_id=user.id,
                )
            )
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(400, INVALID)
        return {
            "message": "Телефон подтверждён. Теперь можно восстанавливать пароль по SMS."
        }

    @app.post("/v1/auth/reset-password-phone")
    def reset(
        body: ResetPhone,
        request: Request,
        response: Response,
        db: Session = Depends(get_db),
    ):
        ip_limit(db, request)
        if body.new_password != body.confirm_password:
            raise HTTPException(422, "Пароли не совпадают")
        user, challenge = check_challenge(db, body, "reset")
        phone = db.get(AccountPhone, user.id)
        if not phone or phone.phone != challenge.phone:
            db.rollback()
            raise HTTPException(400, INVALID)
        changed = db.execute(
            update(User)
            .where(User.id == user.id, User.password_hash == user.password_hash)
            .values(
                password_hash=password_hash(body.new_password),
                failed_login_attempts=0,
                locked_until=None,
            )
        ).rowcount
        if changed != 1:
            db.rollback()
            raise HTTPException(400, INVALID)
        revoke_user_sessions(user.id, db)
        db.execute(
            update(PhoneChallenge)
            .where(PhoneChallenge.user_id == user.id)
            .values(consumed_at=datetime.utcnow())
        )
        db.execute(
            update(PasswordRecoveryToken)
            .where(PasswordRecoveryToken.user_id == user.id)
            .values(consumed_at=datetime.utcnow())
        )
        db.add(
            AuditLog(
                actor_type=user.role,
                action="AUTH_PASSWORD_RECOVERED_SMS",
                entity_type="USER",
                entity_id=user.id,
            )
        )
        db.commit()
        response.delete_cookie("relyqo_session", path="/")
        return {
            "message": "Пароль изменён. Войдите с новым паролем. Все прежние сессии завершены."
        }

    def page():
        return FileResponse(
            Path(__file__).parent / "static" / "phone-recovery.html",
            headers={
                "Cache-Control": "no-store, max-age=0",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
            },
        )

    for path in ["/phone-recovery", "/account-phone"]:
        app.add_api_route(path, page, methods=["GET"], include_in_schema=False)
