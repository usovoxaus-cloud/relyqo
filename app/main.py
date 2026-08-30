from datetime import datetime, timedelta
import hmac
import json
from pathlib import Path
import re
import secrets
from threading import Lock
from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .config import settings
from .ai import AIServiceError, AIUnavailableError, generate_business_insight
from .db import get_db
from .models import (
    AuditLog,
    AuthSession,
    Branch,
    Organization,
    OwnerReview,
    Rating,
    ScoreHistory,
    Visit,
    VisitToken,
    User,
)
from .schemas import (
    AccountRecovery,
    LoginRequest,
    OwnerTokenCreate,
    PasswordChange,
    RatingCreate,
    RecoveryCodeCreate,
    ReviewDecision,
    StaffCreate,
    StaffPasswordReset,
    StaffStatus,
    VerifyVisit,
)
from .score import calculate_ces, review_reason, weighted_score
from .security import (
    create_token,
    password_hash,
    token_hash,
    verify_password,
    verify_signature,
)

app = FastAPI(title="RELYQO API", version="1.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
static = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static), name="static")


def ensure_fregat(db: Session) -> tuple[Organization, Branch]:
    org = db.scalar(select(Organization).where(Organization.name == "Fregat"))
    if not org:
        org = Organization(name="Fregat", city="Tashkent")
        db.add(org)
        db.flush()
    branch = db.scalar(
        select(Branch).where(
            Branch.organization_id == org.id,
            Branch.name == "Shota Rustaveli 69",
        )
    )
    if not branch:
        branch = Branch(organization_id=org.id, name="Shota Rustaveli 69")
        db.add(branch)
        db.flush()
    return org, branch


def issue_visit_token(
    branch: Branch, db: Session, issued_by_user_id: str | None = None
) -> str:
    token, _ = create_token(branch.id)
    db.add(
        VisitToken(
            branch_id=branch.id,
            token_hash=token_hash(token),
            expires_at=datetime.utcnow() + timedelta(hours=3),
            issued_by_user_id=issued_by_user_id,
        )
    )
    return token


def recalculate_organization(org: Organization, db: Session) -> None:
    rows = db.execute(
        select(Rating.ces, Rating.trust_weight, Rating.included).where(
            Rating.organization_id == org.id
        )
    ).all()
    org.score = weighted_score(rows)
    org.rating_count = len([row for row in rows if row.included])
    db.add(org)
    db.add(
        ScoreHistory(organization_id=org.id, score=org.score)
    )


SESSION_COOKIE = "relyqo_session"
SESSION_HOURS = 8
MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCK_MINUTES = 15
OWNER_ROLE = "FREGAT_OWNER"
STAFF_ROLE = "FREGAT_STAFF"
REVIEWER_ROLE = "RELYQO_REVIEWER"
_DUMMY_PASSWORD_HASH = password_hash("dummy-password-used-for-timing-only")
AI_CACHE_MINUTES = 10
AI_COOLDOWN_SECONDS = 60
_ai_cache: dict[str, dict] = {}
_ai_last_request: dict[str, datetime] = {}
_ai_lock = Lock()


def bootstrap_user(username: str, password: str, db: Session) -> User | None:
    """Create the two initial accounts from legacy Render secrets once."""
    if username == "fregat-owner":
        expected = settings.owner_password
        role = OWNER_ROLE
        org, _ = ensure_fregat(db)
        organization_id = org.id
    elif username == "relyqo-reviewer":
        expected = settings.review_password
        role = REVIEWER_ROLE
        organization_id = None
    else:
        return None
    if not expected or not hmac.compare_digest(
        password.encode("utf-8"), expected.encode("utf-8")
    ):
        return None
    user = User(
        username=username,
        password_hash=password_hash(password),
        role=role,
        organization_id=organization_id,
    )
    db.add(user)
    db.flush()
    return user


def authenticate(username: str, password: str, db: Session) -> User | None:
    user = db.scalar(select(User).where(User.username == username))
    if not user:
        user = bootstrap_user(username, password, db)
    if not user:
        verify_password(password, _DUMMY_PASSWORD_HASH)
        return None
    now = datetime.utcnow()
    if user.locked_until and user.locked_until > now:
        raise HTTPException(
            429,
            "Слишком много попыток входа. Повторите через 15 минут",
        )
    if not user.active or not verify_password(password, user.password_hash):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= MAX_LOGIN_ATTEMPTS:
            user.locked_until = now + timedelta(minutes=LOGIN_LOCK_MINUTES)
        locked = user.failed_login_attempts >= MAX_LOGIN_ATTEMPTS
        db.add_all(
            [
                user,
                AuditLog(
                    actor_type=user.role,
                    action="AUTH_LOGIN_LOCKED" if locked else "AUTH_LOGIN_FAILED",
                    entity_type="USER",
                    entity_id=user.id,
                ),
            ]
        )
        db.commit()
        if locked:
            raise HTTPException(
                429,
                "Слишком много попыток входа. Повторите через 15 минут",
            )
        return None
    user.failed_login_attempts = 0
    user.locked_until = None
    db.add(user)
    return user


def revoke_user_sessions(user_id: str, db: Session) -> None:
    db.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id == user_id,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.utcnow())
    )


def session_user(
    token: str | None,
    db: Session,
    roles: str | set[str] | None = None,
) -> User:
    if not token:
        raise HTTPException(401, "Войдите в аккаунт")
    session = db.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == token_hash(token),
            AuthSession.revoked_at.is_(None),
        )
    )
    if not session or session.expires_at < datetime.utcnow():
        raise HTTPException(401, "Сессия истекла. Войдите снова")
    user = db.get(User, session.user_id)
    if not user or not user.active:
        raise HTTPException(401, "Аккаунт отключён")
    allowed_roles = {roles} if isinstance(roles, str) else roles
    if allowed_roles and user.role not in allowed_roles:
        raise HTTPException(403, "У этого аккаунта нет доступа")
    return user


@app.get("/", include_in_schema=False)
def web():
    return FileResponse(static / "index.html")


@app.get("/owner", include_in_schema=False)
def owner_web():
    return FileResponse(
        static / "owner.html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/business", include_in_schema=False)
def business_web():
    return FileResponse(
        static / "business.html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/review", include_in_schema=False)
def review_web():
    return FileResponse(
        static / "review.html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/staff", include_in_schema=False)
def staff_web():
    return FileResponse(
        static / "staff.html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/recover", include_in_schema=False)
def recover_web():
    return FileResponse(
        static / "recover.html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.post("/v1/auth/login")
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    user = authenticate(body.username.strip().lower(), body.password, db)
    if not user:
        raise HTTPException(401, "Неверное имя пользователя или пароль")
    response.headers["Cache-Control"] = "no-store, max-age=0"
    raw_token = secrets.token_urlsafe(32)
    session = AuthSession(
        user_id=user.id,
        token_hash=token_hash(raw_token),
        expires_at=datetime.utcnow() + timedelta(hours=SESSION_HOURS),
    )
    db.add_all(
        [
            session,
            AuditLog(
                actor_type=user.role,
                action="AUTH_LOGIN",
                entity_type="USER",
                entity_id=user.id,
            ),
        ]
    )
    db.commit()
    response.set_cookie(
        SESSION_COOKIE,
        raw_token,
        max_age=SESSION_HOURS * 3600,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        path="/",
    )
    return {"username": user.username, "role": user.role}


@app.get("/v1/auth/me")
def me(
    response: Response,
    relyqo_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    user = session_user(relyqo_session, db)
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return {"username": user.username, "role": user.role}


@app.post("/v1/auth/logout")
def logout(
    response: Response,
    relyqo_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    user = session_user(relyqo_session, db)
    response.headers["Cache-Control"] = "no-store, max-age=0"
    session = db.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == token_hash(relyqo_session),
            AuthSession.revoked_at.is_(None),
        )
    )
    session.revoked_at = datetime.utcnow()
    db.add_all(
        [
            session,
            AuditLog(
                actor_type=user.role,
                action="AUTH_LOGOUT",
                entity_type="USER",
                entity_id=user.id,
            ),
        ]
    )
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"status": "SIGNED_OUT"}


@app.post("/v1/auth/change-password")
def change_password(
    body: PasswordChange,
    response: Response,
    relyqo_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    user = session_user(relyqo_session, db)
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(401, "Текущий пароль указан неверно")
    if verify_password(body.new_password, user.password_hash):
        raise HTTPException(422, "Новый пароль должен отличаться от текущего")
    user.password_hash = password_hash(body.new_password)
    user.failed_login_attempts = 0
    user.locked_until = None
    revoke_user_sessions(user.id, db)
    db.add_all(
        [
            user,
            AuditLog(
                actor_type=user.role,
                action="AUTH_PASSWORD_CHANGED",
                entity_type="USER",
                entity_id=user.id,
            ),
        ]
    )
    db.commit()
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"status": "PASSWORD_CHANGED", "login_required": True}


@app.post("/v1/auth/recovery-code")
def create_recovery_code(
    body: RecoveryCodeCreate,
    response: Response,
    relyqo_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    user = session_user(relyqo_session, db, {OWNER_ROLE, REVIEWER_ROLE})
    if not verify_password(body.current_password, user.password_hash):
        db.add(
            AuditLog(
                actor_type=user.role,
                action="AUTH_RECOVERY_CODE_FAILED",
                entity_type="USER",
                entity_id=user.id,
            )
        )
        db.commit()
        raise HTTPException(401, "Текущий пароль указан неверно")
    raw_code = f"relyqo-{secrets.token_urlsafe(32)}"
    user.recovery_code_hash = token_hash(raw_code)
    user.recovery_code_created_at = datetime.utcnow()
    db.add_all(
        [
            user,
            AuditLog(
                actor_type=user.role,
                action="AUTH_RECOVERY_CODE_CREATED",
                entity_type="USER",
                entity_id=user.id,
            ),
        ]
    )
    db.commit()
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return {
        "recovery_code": raw_code,
        "created_at": user.recovery_code_created_at,
        "warning": "SAVE_NOW_SHOWN_ONCE",
    }


@app.post("/v1/auth/recover")
def recover_account(body: AccountRecovery, response: Response, db: Session = Depends(get_db)):
    username = body.username.strip().lower()
    user = db.scalar(select(User).where(User.username == username))
    supplied_hash = token_hash(body.recovery_code.strip())
    valid_role = bool(user and user.role in {OWNER_ROLE, REVIEWER_ROLE})
    valid_code = bool(
        valid_role
        and user.recovery_code_hash
        and hmac.compare_digest(supplied_hash, user.recovery_code_hash)
    )
    if not valid_code:
        if valid_role:
            db.add(
                AuditLog(
                    actor_type=user.role,
                    action="AUTH_RECOVERY_FAILED",
                    entity_type="USER",
                    entity_id=user.id,
                )
            )
            db.commit()
        raise HTTPException(401, "Неверное имя пользователя или код восстановления")
    if verify_password(body.new_password, user.password_hash):
        raise HTTPException(422, "Новый пароль должен отличаться от прежнего")
    user.password_hash = password_hash(body.new_password)
    user.recovery_code_hash = None
    user.recovery_code_created_at = None
    user.failed_login_attempts = 0
    user.locked_until = None
    revoke_user_sessions(user.id, db)
    db.add_all(
        [
            user,
            AuditLog(
                actor_type=user.role,
                action="AUTH_ACCOUNT_RECOVERED",
                entity_type="USER",
                entity_id=user.id,
            ),
        ]
    )
    db.commit()
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"status": "ACCOUNT_RECOVERED", "login_required": True}


@app.post("/v1/owner/staff")
def create_staff_account(
    body: StaffCreate,
    relyqo_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    owner = session_user(relyqo_session, db, OWNER_ROLE)
    username = body.username.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,79}", username):
        raise HTTPException(
            422,
            "Имя: латинские буквы, цифры, точка, дефис или подчёркивание",
        )
    if db.scalar(select(User).where(User.username == username)):
        raise HTTPException(409, "Это имя пользователя уже занято")
    staff = User(
        username=username,
        password_hash=password_hash(body.password),
        role=STAFF_ROLE,
        organization_id=owner.organization_id,
    )
    db.add(staff)
    db.flush()
    db.add(
        AuditLog(
            actor_type=owner.role,
            action="STAFF_ACCOUNT_CREATED",
            entity_type="USER",
            entity_id=staff.id,
        )
    )
    db.commit()
    return {
        "id": staff.id,
        "username": staff.username,
        "role": staff.role,
        "active": staff.active,
    }


@app.get("/v1/owner/staff")
def list_staff_accounts(
    relyqo_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    owner = session_user(relyqo_session, db, OWNER_ROLE)
    staff = db.scalars(
        select(User)
        .where(
            User.organization_id == owner.organization_id,
            User.role == STAFF_ROLE,
        )
        .order_by(User.username)
    ).all()
    return {
        "items": [
            {
                "id": user.id,
                "username": user.username,
                "active": user.active,
                "created_at": user.created_at,
            }
            for user in staff
        ]
    }


@app.post("/v1/owner/staff/{user_id}/status")
def set_staff_status(
    user_id: str,
    body: StaffStatus,
    relyqo_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    owner = session_user(relyqo_session, db, OWNER_ROLE)
    staff = db.get(User, user_id)
    if (
        not staff
        or staff.role != STAFF_ROLE
        or staff.organization_id != owner.organization_id
    ):
        raise HTTPException(404, "Сотрудник не найден")
    staff.active = body.active
    if not body.active:
        revoke_user_sessions(staff.id, db)
    db.add_all(
        [
            staff,
            AuditLog(
                actor_type=owner.role,
                action="STAFF_ACCOUNT_ENABLED" if body.active else "STAFF_ACCOUNT_DISABLED",
                entity_type="USER",
                entity_id=staff.id,
            ),
        ]
    )
    db.commit()
    return {"id": staff.id, "username": staff.username, "active": staff.active}


@app.post("/v1/owner/staff/{user_id}/reset-password")
def reset_staff_password(
    user_id: str,
    body: StaffPasswordReset,
    relyqo_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    owner = session_user(relyqo_session, db, OWNER_ROLE)
    staff = db.get(User, user_id)
    if (
        not staff
        or staff.role != STAFF_ROLE
        or staff.organization_id != owner.organization_id
    ):
        raise HTTPException(404, "Сотрудник не найден")
    if verify_password(body.new_password, staff.password_hash):
        raise HTTPException(422, "Новый пароль должен отличаться от прежнего")
    staff.password_hash = password_hash(body.new_password)
    staff.failed_login_attempts = 0
    staff.locked_until = None
    revoke_user_sessions(staff.id, db)
    db.add_all(
        [
            staff,
            AuditLog(
                actor_type=owner.role,
                action="STAFF_PASSWORD_RESET",
                entity_type="USER",
                entity_id=staff.id,
            ),
        ]
    )
    db.commit()
    return {
        "id": staff.id,
        "username": staff.username,
        "status": "PASSWORD_RESET",
    }


@app.get("/v1/owner/qr-log")
def owner_qr_log(
    relyqo_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    owner = session_user(relyqo_session, db, OWNER_ROLE)
    rows = db.execute(
        select(VisitToken, Branch)
        .join(Branch, VisitToken.branch_id == Branch.id)
        .where(Branch.organization_id == owner.organization_id)
        .order_by(VisitToken.created_at.desc())
        .limit(100)
    ).all()
    items = []
    for token, branch in rows:
        issuer = db.get(User, token.issued_by_user_id) if token.issued_by_user_id else None
        status = (
            "USED"
            if token.used_at
            else "EXPIRED"
            if token.expires_at < datetime.utcnow()
            else "ACTIVE"
        )
        items.append(
            {
                "id": token.id,
                "transaction_reference": token.transaction_reference,
                "branch": branch.name,
                "issued_by": issuer.username if issuer else "legacy/system",
                "created_at": token.created_at,
                "expires_at": token.expires_at,
                "used_at": token.used_at,
                "status": status,
            }
        )
    return {"items": items, "count": len(items)}


@app.get("/fregat", include_in_schema=False)
def fregat_visit(db: Session = Depends(get_db)):
    """Pilot QR entry: each scan receives a fresh one-time visit token."""
    if not settings.demo_mode:
        raise HTTPException(404)
    _, branch = ensure_fregat(db)
    token = issue_visit_token(branch, db)
    db.commit()
    return RedirectResponse(url=f"/?token={token}", status_code=303)


@app.get("/fregat/qr.png", include_in_schema=False)
def fregat_qr(request: Request):
    import io
    import qrcode

    target = f"{str(request.base_url).rstrip('/')}/fregat"
    image = qrcode.make(target)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return Response(output.getvalue(), media_type="image/png")


@app.post("/v1/owner/visit-token")
def owner_visit_token(
    body: OwnerTokenCreate,
    request: Request,
    relyqo_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    user = session_user(relyqo_session, db, {OWNER_ROLE, STAFF_ROLE})
    existing = db.scalar(
        select(VisitToken).where(
            VisitToken.transaction_reference == body.transaction_reference
        )
    )
    if existing:
        raise HTTPException(409, "Для этого чека QR уже выпускался")
    _, branch = ensure_fregat(db)
    if user.organization_id != branch.organization_id:
        raise HTTPException(403, "Нет доступа к этому ресторану")
    token = issue_visit_token(branch, db, user.id)
    record = db.scalar(
        select(VisitToken).where(VisitToken.token_hash == token_hash(token))
    )
    record.transaction_reference = body.transaction_reference
    db.add(
        AuditLog(
            actor_type=user.role,
            action="VISIT_TOKEN_ISSUED",
            entity_type="VISIT_TOKEN",
            entity_id=record.id,
        )
    )
    db.commit()
    base_url = str(request.base_url).rstrip("/")
    return {
        "expires_in": 10800,
        "visit_url": f"{base_url}/?token={token}",
        "qr_url": f"{base_url}/v1/qr.png?token={token}",
    }


@app.get("/v1/qr.png", include_in_schema=False)
def token_qr(token: str, request: Request, db: Session = Depends(get_db)):
    import io
    import qrcode

    try:
        verify_signature(token)
    except Exception as exc:
        raise HTTPException(400, "Недействительный QR") from exc
    record = db.scalar(
        select(VisitToken).where(VisitToken.token_hash == token_hash(token))
    )
    if not record or record.used_at or record.expires_at < datetime.utcnow():
        raise HTTPException(410, "QR недоступен")
    target = f"{str(request.base_url).rstrip('/')}/?token={token}"
    image = qrcode.make(target)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return Response(output.getvalue(), media_type="image/png")


@app.get("/fregat/qr", response_class=HTMLResponse, include_in_schema=False)
def fregat_qr_page():
    return """<!doctype html><html lang='ru'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Fregat — RELYQO QR</title><style>body{font-family:Arial,sans-serif;text-align:center;padding:36px;color:#082c27}img{width:min(72vw,420px)}h1{font-size:42px;margin-bottom:4px}p{font-size:20px}.brand{letter-spacing:.18em;color:#16715f;font-weight:700}@media print{button{display:none}}</style></head><body><div class='brand'>RELYQO · VERIFIED VISIT</div><h1>Fregat</h1><p>Shota Rustaveli 69 · Tashkent</p><img src='/fregat/qr.png' alt='QR для оценки Fregat'><p>Отсканируйте QR после посещения<br>и оставьте честную оценку.</p><button onclick='print()'>Печать</button></body></html>"""


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    return FileResponse(
        static / "manifest.webmanifest", media_type="application/manifest+json"
    )


@app.get("/sw.js", include_in_schema=False)
def sw():
    return FileResponse(static / "sw.js", media_type="application/javascript")


@app.get("/v1/health")
def health(db: Session = Depends(get_db)):
    db.execute(select(1))
    return {"status": "ok", "version": "1.1.0"}


@app.post("/v1/demo/visit")
def demo_visit(request: Request, db: Session = Depends(get_db)):
    """Create a short-lived demo visit URL. Disabled when DEMO_MODE=false."""
    if not settings.demo_mode:
        raise HTTPException(404)
    org = db.scalar(select(Organization).where(Organization.name == "Saffron Table"))
    if not org:
        org = Organization(name="Saffron Table", city="Tashkent")
        db.add(org)
        db.flush()
    branch = db.scalar(select(Branch).where(Branch.organization_id == org.id))
    if not branch:
        branch = Branch(organization_id=org.id, name="Tashkent City")
        db.add(branch)
        db.flush()
    token, _ = create_token(branch.id)
    db.add(
        VisitToken(
            branch_id=branch.id,
            token_hash=token_hash(token),
            expires_at=datetime.utcnow() + timedelta(hours=3),
        )
    )
    db.commit()
    base_url = str(request.base_url).rstrip("/")
    return {
        "organization_id": org.id,
        "expires_in": 10800,
        "visit_url": f"{base_url}/?token={token}",
    }


@app.post("/v1/visits/verify-token")
def verify_visit(body: VerifyVisit, db: Session = Depends(get_db)):
    try:
        data = verify_signature(body.token)
    except Exception as exc:
        raise HTTPException(400, str(exc))
    record = db.scalar(
        select(VisitToken)
        .where(VisitToken.token_hash == token_hash(body.token))
        .with_for_update()
    )
    if not record or record.used_at:
        raise HTTPException(409, "QR уже использован или не существует")
    if record.expires_at < datetime.utcnow():
        raise HTTPException(410, "QR истёк")
    branch = db.get(Branch, record.branch_id)
    org = db.get(Organization, branch.organization_id)
    if data["branch_id"] != branch.id:
        raise HTTPException(400, "QR не соответствует филиалу")
    visit = Visit(branch_id=branch.id)
    record.used_at = datetime.utcnow()
    db.add(visit)
    db.flush()
    db.add(
        AuditLog(
            actor_type="CUSTOMER",
            action="VISIT_VERIFIED",
            entity_type="VISIT",
            entity_id=visit.id,
        )
    )
    db.commit()
    return {
        "status": "VERIFIED",
        "visit_id": visit.id,
        "organization": {"id": org.id, "name": org.name},
        "branch": {"id": branch.id, "name": branch.name},
        "verification_score": visit.verification_score,
    }


@app.post("/v1/ratings")
def rate(body: RatingCreate, db: Session = Depends(get_db)):
    visit = db.get(Visit, body.visit_id)
    if not visit:
        raise HTTPException(404, "Посещение не найдено")
    branch = db.get(Branch, visit.branch_id)
    org = db.get(Organization, branch.organization_id)
    ces = calculate_ces(
        body.overall, body.food, body.service, body.cleanliness, body.value
    )
    pending_reason = review_reason(
        body.overall, body.food, body.service, body.cleanliness, body.value
    )
    rating = Rating(
        **body.model_dump(),
        organization_id=org.id,
        ces=ces,
        trust_weight=visit.verification_score,
        included=pending_reason is None,
        status="PENDING_REVIEW" if pending_reason else "ACCEPTED",
    )
    db.add(rating)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Для этого посещения оценка уже поставлена")
    if pending_reason:
        db.add_all(
            [
                OwnerReview(
                    entity_type="RATING",
                    entity_id=rating.id,
                    reason=pending_reason,
                ),
                AuditLog(
                    actor_type="SCORE_ENGINE",
                    action="RATING_QUEUED_FOR_REVIEW",
                    entity_type="RATING",
                    entity_id=rating.id,
                ),
            ]
        )
    else:
        recalculate_organization(org, db)
        db.add(
            AuditLog(
                actor_type="SCORE_ENGINE",
                action="SCORE_RECALCULATED",
                entity_type="ORGANIZATION",
                entity_id=org.id,
            )
        )
    db.commit()
    return {
        "rating_id": rating.id,
        "status": rating.status,
        "ces_score": ces,
        "included_in_rating": rating.included,
        "relyqo_score": org.score,
        "rating_count": org.rating_count,
    }


@app.get("/v1/organizations/{organization_id}/score")
def score(organization_id: str, db: Session = Depends(get_db)):
    org = db.get(Organization, organization_id)
    if not org:
        raise HTTPException(404, "Организация не найдена")
    return {
        "organization_id": org.id,
        "name": org.name,
        "relyqo_score": org.score,
        "rating_count": org.rating_count,
        "calculation": "deterministic_weighted_ces_v1",
    }


@app.get("/v1/business/organizations/{organization_id}")
def business_read(
    organization_id: str,
    x_role: str = Header(default="BUSINESS_VIEWER"),
    db: Session = Depends(get_db),
):
    if x_role != "BUSINESS_VIEWER":
        raise HTTPException(403)
    return score(organization_id, db)


@app.get("/v1/review/ratings")
def pending_rating_reviews(
    relyqo_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    session_user(relyqo_session, db, REVIEWER_ROLE)
    reviews = db.scalars(
        select(OwnerReview)
        .where(
            OwnerReview.entity_type == "RATING",
            OwnerReview.status == "PENDING",
        )
        .order_by(OwnerReview.id)
    ).all()
    result = []
    for review in reviews:
        rating = db.get(Rating, review.entity_id)
        if not rating:
            continue
        org = db.get(Organization, rating.organization_id)
        result.append(
            {
                "review_id": review.id,
                "rating_id": rating.id,
                "organization": org.name if org else "Неизвестная организация",
                "reason": review.reason,
                "status": review.status,
                "created_at": rating.created_at,
                "scores": {
                    "overall": rating.overall,
                    "food": rating.food,
                    "service": rating.service,
                    "cleanliness": rating.cleanliness,
                    "value": rating.value,
                    "ces": rating.ces,
                },
            }
        )
    return {"items": result, "count": len(result)}


@app.post("/v1/review/ratings/{review_id}/decision")
def decide_rating_review(
    review_id: str,
    body: ReviewDecision,
    relyqo_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    user = session_user(relyqo_session, db, REVIEWER_ROLE)
    review = db.get(OwnerReview, review_id)
    if not review or review.entity_type != "RATING":
        raise HTTPException(404, "Спорная оценка не найдена")
    if review.status != "PENDING":
        raise HTTPException(409, "Решение уже принято")
    rating = db.get(Rating, review.entity_id)
    if not rating:
        raise HTTPException(404, "Оценка не найдена")
    approved = body.decision == "APPROVE"
    review.status = "APPROVED" if approved else "REJECTED"
    rating.included = approved
    rating.status = "ACCEPTED" if approved else "REJECTED"
    org = db.get(Organization, rating.organization_id)
    recalculate_organization(org, db)
    db.add_all(
        [
            review,
            rating,
            AuditLog(
                actor_type=user.role,
                action=f"RATING_REVIEW_{review.status}",
                entity_type="RATING",
                entity_id=rating.id,
            ),
        ]
    )
    db.commit()
    return {
        "review_id": review.id,
        "status": review.status,
        "rating_status": rating.status,
        "included_in_rating": rating.included,
        "relyqo_score": org.score,
        "rating_count": org.rating_count,
    }


@app.get("/v1/business/fregat")
def fregat_business_dashboard(response: Response, db: Session = Depends(get_db)):
    """Read-only aggregate view. No Business mutation endpoints exist."""
    response.headers["Cache-Control"] = "no-store, max-age=0"
    org = db.scalar(select(Organization).where(Organization.name == "Fregat"))
    if not org:
        raise HTTPException(404, "Fregat ещё не создан")
    branch = db.scalar(select(Branch).where(Branch.organization_id == org.id).limit(1))
    averages = db.execute(
        select(
            func.avg(Rating.overall),
            func.avg(Rating.food),
            func.avg(Rating.service),
            func.avg(Rating.cleanliness),
            func.avg(Rating.value),
        ).where(Rating.organization_id == org.id, Rating.included.is_(True))
    ).one()
    verified_visits = db.scalar(
        select(func.count(Visit.id))
        .join(Branch, Visit.branch_id == Branch.id)
        .where(Branch.organization_id == org.id)
    )
    submitted_ratings = db.scalar(
        select(func.count(Rating.id)).where(Rating.organization_id == org.id)
    )
    pending_review = db.scalar(
        select(func.count(Rating.id)).where(
            Rating.organization_id == org.id,
            Rating.status == "PENDING_REVIEW",
        )
    )
    history = db.scalars(
        select(ScoreHistory)
        .where(ScoreHistory.organization_id == org.id)
        .order_by(ScoreHistory.calculated_at.desc())
        .limit(12)
    ).all()

    def metric(value):
        return round(float(value) * 10, 1) if value is not None else 0.0

    metrics = {
        "overall": metric(averages[0]),
        "food": metric(averages[1]),
        "service": metric(averages[2]),
        "cleanliness": metric(averages[3]),
        "value": metric(averages[4]),
    }
    category_labels = {
        "food": "Качество еды",
        "service": "Обслуживание",
        "cleanliness": "Чистота",
        "value": "Цена и качество",
    }
    category_metrics = {key: metrics[key] for key in category_labels}
    strongest = max(category_metrics, key=category_metrics.get)
    weakest = min(category_metrics, key=category_metrics.get)
    visit_count = verified_visits or 0
    submitted_count = submitted_ratings or 0
    sample_target = 20

    return {
        "organization": {
            "id": org.id,
            "name": org.name,
            "city": org.city,
            "branch": branch.name if branch else None,
        },
        "relyqo_score": org.score,
        "rating_count": org.rating_count,
        "verified_visits": visit_count,
        "metrics": metrics,
        "pilot": {
            "sample_status": "EARLY" if org.rating_count < sample_target else "READY",
            "sample_target": sample_target,
            "remaining_to_target": max(0, sample_target - org.rating_count),
            "submitted_ratings": submitted_count,
            "completion_rate": (
                round(submitted_count / visit_count * 100, 1) if visit_count else 0.0
            ),
            "incomplete_visits": max(0, visit_count - submitted_count),
            "pending_review": pending_review or 0,
            "strongest_category": {
                "key": strongest,
                "label": category_labels[strongest],
                "score": category_metrics[strongest],
            },
            "weakest_category": {
                "key": weakest,
                "label": category_labels[weakest],
                "score": category_metrics[weakest],
            },
        },
        "history": [
            {"score": item.score, "calculated_at": item.calculated_at.isoformat() + "Z"}
            for item in reversed(history)
        ],
        "permissions": {
            "ratings_create": False,
            "ratings_update": False,
            "ratings_delete": False,
            "score_update": False,
        },
        "ai": {
            "configured": bool(settings.openai_api_key),
            "model": settings.openai_model if settings.openai_api_key else None,
            "affects_score": False,
            "can_change_ratings": False,
            "can_decide_reviews": False,
        },
        "calculation": "deterministic_weighted_ces_v1",
    }


@app.get("/v1/business/fregat/ai-insights")
def fregat_ai_insights(
    response: Response,
    relyqo_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    user = session_user(relyqo_session, db, OWNER_ROLE)
    response.headers["Cache-Control"] = "no-store, max-age=0"
    if not settings.openai_api_key:
        raise HTTPException(
            503,
            "AI-аналитик ещё не подключён: добавьте OPENAI_API_KEY в Render",
        )
    dashboard = fregat_business_dashboard(Response(), db)
    payload = {
        "restaurant": dashboard["organization"]["name"],
        "city": dashboard["organization"]["city"],
        "relyqo_score": dashboard["relyqo_score"],
        "score_source": dashboard["calculation"],
        "included_rating_count": dashboard["rating_count"],
        "verified_visit_count": dashboard["verified_visits"],
        "category_scores": dashboard["metrics"],
        "pilot": dashboard["pilot"],
    }
    signature = token_hash(json.dumps(payload, sort_keys=True))
    now = datetime.utcnow()
    with _ai_lock:
        cached = _ai_cache.get(signature)
        if cached and cached["expires_at"] > now:
            return {
                **cached["response"],
                "cached": True,
            }
        last_request = _ai_last_request.get(user.id)
        if last_request:
            seconds_left = AI_COOLDOWN_SECONDS - int(
                (now - last_request).total_seconds()
            )
            if seconds_left > 0:
                raise HTTPException(
                    429,
                    f"Повторный AI-анализ будет доступен через {seconds_left} сек.",
                )
        _ai_last_request[user.id] = now
    try:
        analysis = generate_business_insight(payload)
    except AIUnavailableError as exc:
        raise HTTPException(503, "AI-аналитик ещё не подключён") from exc
    except AIServiceError as exc:
        with _ai_lock:
            _ai_last_request.pop(user.id, None)
        raise HTTPException(
            502,
            "AI-сервис временно недоступен. Попробуйте позже",
        ) from exc
    result = {
        "analysis": analysis,
        "model": settings.openai_model,
        "generated_at": now.isoformat() + "Z",
        "cached": False,
        "disclaimer": (
            "AI даёт справочные рекомендации и не влияет на Score, оценки "
            "или решения Owner Review."
        ),
    }
    with _ai_lock:
        _ai_cache.clear()
        _ai_cache[signature] = {
            "expires_at": now + timedelta(minutes=AI_CACHE_MINUTES),
            "response": result,
        }
    return result
