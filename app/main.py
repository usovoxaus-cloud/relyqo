from datetime import datetime, timedelta, timezone
import base64
import binascii
import hmac
import json
import math
from pathlib import Path
import re
import secrets
from threading import Lock
from urllib.parse import unquote, urlencode, urlparse
from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .config import settings
from .ai import (
    AIServiceError,
    AIUnavailableError,
    analyze_service_photo,
    generate_business_insight,
    generate_consumer_assistance,
    generate_public_advice,
)
from .db import get_db
from .models import (
    Advertisement,
    AdvertisementMedia,
    AuditLog,
    AuthSession,
    Branch,
    CommunityRating,
    ConsumerFavorite,
    GooglePlaceReference,
    ManualPlace,
    Organization,
    OwnerReview,
    Rating,
    RatingPhoto,
    ScoreHistory,
    Visit,
    VisitToken,
    User,
)
from .schemas import (
    AccountRecovery,
    AdvertisementCreate,
    AdvertisementStatus,
    BusinessApplicationDecision,
    BusinessOwnerRegister,
    BusinessProfileUpdate,
    CommunityRatingCreate,
    ConsumerAssistantRequest,
    ConsumerFavoriteChange,
    ConsumerRegister,
    LoginRequest,
    ManualPlaceCreate,
    NearbySearch,
    OwnerTokenCreate,
    PasswordChange,
    PublicAdvisorRequest,
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
SERVICE_CATEGORIES = {
    "RESTAURANT",
    "CAFE",
    "COFFEE_SHOP",
    "BAKERY",
    "BAR",
    "FOOD_COURT",
    "HOTEL",
    "BEAUTY",
    "HEALTH",
    "ENTERTAINMENT",
    "RETAIL",
    "AUTO_SERVICE",
    "PROFESSIONAL_SERVICE",
    "EDUCATION",
    "OTHER",
}
ADVERTISEMENT_PLACEMENTS = {"TOP_BANNER", "CORNER"}
ADVERTISEMENT_PAGE_SCOPES = {"ALL", "HOME", "MAP", "RANKINGS", "PROFILE"}
ADVERTISEMENT_MEDIA_TYPES = {
    "image/jpeg": ("IMAGE", 5 * 1024 * 1024),
    "image/png": ("IMAGE", 5 * 1024 * 1024),
    "image/webp": ("IMAGE", 5 * 1024 * 1024),
    "video/mp4": ("VIDEO", 25 * 1024 * 1024),
    "video/webm": ("VIDEO", 25 * 1024 * 1024),
    "application/pdf": ("PRESENTATION", 15 * 1024 * 1024),
    "application/vnd.ms-powerpoint": ("PRESENTATION", 15 * 1024 * 1024),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": (
        "PRESENTATION",
        15 * 1024 * 1024,
    ),
}
SERVICE_CATEGORY_GROUPS = {
    "FOOD": {"RESTAURANT", "CAFE", "COFFEE_SHOP", "BAKERY", "BAR", "FOOD_COURT", "FOOD"},
    "HOTEL": {"HOTEL"},
    "BEAUTY": {"BEAUTY"},
    "HEALTH": {"HEALTH"},
    "ENTERTAINMENT": {"ENTERTAINMENT"},
    "RETAIL": {"RETAIL"},
    "AUTO_SERVICE": {"AUTO_SERVICE"},
    "PROFESSIONAL_SERVICE": {"PROFESSIONAL_SERVICE"},
    "EDUCATION": {"EDUCATION"},
    "OTHER": {"OTHER"},
}
SERVICE_CATEGORY_ALIASES = {
    "РЕСТОРАН": "FOOD",
    "КАФЕ": "FOOD",
    "КОФЕЙНЯ": "FOOD",
    "ГОСТИНИЦА": "HOTEL",
    "ОБРАЗОВАНИЕ": "EDUCATION",
}
CITY_NAME_ALIASES = {
    "tashkent": "Tashkent",
    "toshkent": "Tashkent",
    "ташкент": "Tashkent",
    "тоshkent": "Tashkent",
}
TOP_ORGANIZATION_LIMIT = 3
TOP_ORGANIZATION_MIN_RATINGS = 3


def service_category_group(value: str | None) -> str:
    normalized = (value or "OTHER").strip().upper()
    if normalized in SERVICE_CATEGORY_ALIASES:
        return SERVICE_CATEGORY_ALIASES[normalized]
    for group, categories in SERVICE_CATEGORY_GROUPS.items():
        if normalized in categories:
            return group
    return "OTHER"


def normalize_city_name(value: str | None) -> str:
    cleaned = " ".join((value or "").split())
    return CITY_NAME_ALIASES.get(cleaned.casefold(), cleaned)


def normalize_rating_photo(data_url: str | None) -> tuple[bytes, str, str] | None:
    if not data_url:
        return None
    match = re.fullmatch(
        r"data:image/(jpeg|jpg|png|webp);base64,([A-Za-z0-9+/=\r\n]+)",
        data_url,
    )
    if not match:
        raise HTTPException(422, "Фото должно быть JPEG, PNG или WebP")
    try:
        raw = base64.b64decode(match.group(2), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(422, "Файл фотографии повреждён") from exc
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(413, "Фото должно быть не больше 5 МБ")
    requested = "jpeg" if match.group(1) in {"jpeg", "jpg"} else match.group(1)
    valid_magic = (
        requested == "jpeg" and raw.startswith(b"\xff\xd8\xff")
        or requested == "png" and raw.startswith(b"\x89PNG\r\n\x1a\n")
        or requested == "webp"
        and raw.startswith(b"RIFF")
        and raw[8:12] == b"WEBP"
    )
    if not valid_magic:
        raise HTTPException(422, "Содержимое файла не соответствует формату фото")
    encoded = base64.b64encode(raw).decode("ascii")
    content_type = f"image/{requested}"
    return raw, f"data:{content_type};base64,{encoded}", content_type


def rating_photo_payload(photo: RatingPhoto | None) -> dict | None:
    if not photo:
        return None
    return {
        "id": photo.id,
        "url": f"/v1/consumer/rating-photos/{photo.id}",
        "analysis_status": photo.analysis_status,
        "ai_analysis": photo.ai_analysis,
        "created_at": photo.created_at,
    }


def analyze_rating_photo(
    photo: RatingPhoto,
    image_data_url: str,
    context: dict,
    db: Session,
) -> str | None:
    try:
        analysis = analyze_service_photo(image_data_url, context)
        photo.ai_analysis = analysis
        photo.analysis_status = "COMPLETED"
        db.add(photo)
        db.commit()
        return analysis
    except AIUnavailableError:
        photo.analysis_status = "SAVED_NO_AI"
    except AIServiceError:
        photo.analysis_status = "AI_TEMPORARILY_UNAVAILABLE"
    db.add(photo)
    db.commit()
    return None


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
        branch = Branch(
            organization_id=org.id,
            name="Shota Rustaveli 69",
            address="Shota Rustaveli 69",
            city="Tashkent",
            country_code="UZ",
            latitude=41.272878,
            longitude=69.240319,
        )
        db.add(branch)
        db.flush()
    else:
        branch.address = branch.address or "Shota Rustaveli 69"
        branch.city = branch.city or "Tashkent"
        branch.country_code = branch.country_code or "UZ"
        branch.latitude = branch.latitude or 41.272878
        branch.longitude = branch.longitude or 69.240319
        branch.active = True
        db.add(branch)
    return org, branch


def haversine_km(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    earth_radius_km = 6371.0088
    lat_a = math.radians(latitude_a)
    lat_b = math.radians(latitude_b)
    lat_delta = math.radians(latitude_b - latitude_a)
    lng_delta = math.radians(longitude_b - longitude_a)
    value = (
        math.sin(lat_delta / 2) ** 2
        + math.cos(lat_a) * math.cos(lat_b) * math.sin(lng_delta / 2) ** 2
    )
    return earth_radius_km * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


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
COMMUNITY_COOKIE = "relyqo_community_rater"
SESSION_HOURS = 8
MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCK_MINUTES = 15
OWNER_ROLE = "FREGAT_OWNER"
STAFF_ROLE = "FREGAT_STAFF"
REVIEWER_ROLE = "RELYQO_REVIEWER"
CONSUMER_ROLE = "CONSUMER"
BUSINESS_OWNER_ROLE = "BUSINESS_OWNER"
ADMIN_ROLE = "RELYQO_ADMIN"
_DUMMY_PASSWORD_HASH = password_hash("dummy-password-used-for-timing-only")
AI_CACHE_MINUTES = 10
AI_COOLDOWN_SECONDS = 60
_ai_cache: dict[str, dict] = {}
_ai_last_request: dict[str, datetime] = {}
_ai_lock = Lock()
_consumer_ai_last_request: dict[str, datetime] = {}
PUBLIC_AI_COOLDOWN_SECONDS = 20
_public_ai_cache: dict[str, dict] = {}
_public_ai_last_request: dict[str, datetime] = {}


def new_community_rater() -> tuple[str, str]:
    raw_rater = secrets.token_urlsafe(32)
    signature = hmac.new(
        settings.qr_secret.encode(),
        raw_rater.encode(),
        digestmod="sha256",
    ).hexdigest()
    return raw_rater, f"{raw_rater}.{signature}"


def verified_community_rater(cookie_value: str | None) -> str | None:
    if not cookie_value or len(cookie_value) > 200 or "." not in cookie_value:
        return None
    raw_rater, signature = cookie_value.rsplit(".", 1)
    expected = hmac.new(
        settings.qr_secret.encode(),
        raw_rater.encode(),
        digestmod="sha256",
    ).hexdigest()
    if len(raw_rater) < 32 or not hmac.compare_digest(signature, expected):
        return None
    return raw_rater


def bootstrap_user(username: str, password: str, db: Session) -> User | None:
    """Create initial protected accounts from Render secrets once."""
    if username == "fregat-owner":
        expected = settings.owner_password
        role = OWNER_ROLE
        org, _ = ensure_fregat(db)
        organization_id = org.id
    elif username == "relyqo-reviewer":
        expected = settings.review_password
        role = REVIEWER_ROLE
        organization_id = None
    elif username == "relyqo-admin":
        expected = settings.admin_password
        role = ADMIN_ROLE
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
    password_matches = verify_password(password, user.password_hash)
    admin_secret_matches = bool(
        user.active
        and user.username == "relyqo-admin"
        and user.role == ADMIN_ROLE
        and settings.admin_password
        and hmac.compare_digest(
            password.encode("utf-8"), settings.admin_password.encode("utf-8")
        )
    )
    admin_needs_recovery = bool(
        admin_secret_matches
        and (
            not password_matches
            or (user.locked_until is not None and user.locked_until > now)
        )
    )
    if admin_needs_recovery:
        user.password_hash = password_hash(password)
        user.failed_login_attempts = 0
        user.locked_until = None
        revoke_user_sessions(user.id, db)
        db.add_all(
            [
                user,
                AuditLog(
                    actor_type=ADMIN_ROLE,
                    action="AUTH_ADMIN_RECOVERED_FROM_ENV",
                    entity_type="USER",
                    entity_id=user.id,
                ),
            ]
        )
        password_matches = True
    if user.locked_until and user.locked_until > now:
        raise HTTPException(
            429,
            "Слишком много попыток входа. Повторите через 15 минут",
        )
    if not user.active or not password_matches:
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


def validate_public_object(object_key: str, source: str) -> None:
    expected_prefix = {
        "GOOGLE": "google:",
        "RELYQO_PARTNER": "relyqo:",
        "MANUAL": "manual:",
    }[source]
    if not object_key.startswith(expected_prefix):
        raise HTTPException(422, "Источник и идентификатор объекта не совпадают")


def consumer_object_info(object_key: str, source: str, db: Session) -> dict:
    item = {
        "object_key": object_key,
        "source": source,
        "name": "Архивный объект" if source == "GOOGLE" else "Организация",
        "category": "OTHER",
        "description": "Историческая запись. Новые внешние объекты больше не импортируются.",
        "href": "/nearby",
    }
    identifier = object_key.split(":", 1)[1]
    if source == "MANUAL":
        place = db.get(ManualPlace, identifier)
        if place:
            item.update(
                name=place.name,
                category=place.category,
                description=place.description,
                href=f"/place?object_key={object_key}&source=MANUAL",
            )
    elif source == "RELYQO_PARTNER":
        branch = db.get(Branch, identifier)
        organization = db.get(Organization, branch.organization_id) if branch else None
        if branch and organization:
            item.update(
                name=organization.name,
                category=organization.category,
                description=f"{branch.address or branch.name} · Verified RELYQO Score {organization.score:.1f}/100",
                href=f"/place?object_key={object_key}&source=RELYQO_PARTNER",
            )
    return item


PUBLIC_ADVISOR_PRIORITIES = (
    ("cleanliness", "чистота и состояние", ("чист", "поряд", "санитар")),
    ("service", "сервис", ("сервис", "обслуж", "персонал")),
    ("value", "цена и ценность", ("цен", "дешев", "бюдж", "выгод")),
    ("quality", "качество", ("качеств", "вкус", "еда", "результат")),
    ("distance", "близость", ("рядом", "близк", "недалеко")),
)


def public_advisor_priority(question: str) -> tuple[str, str]:
    normalized = question.casefold()
    for key, label, words in PUBLIC_ADVISOR_PRIORITIES:
        if any(word in normalized for word in words):
            return key, label
    return "overall", "общая оценка"


def public_advisor_fallback(priority_label: str, sections: list[dict]) -> str:
    leaders = [section["items"][0] for section in sections if section["items"]]
    if not leaders:
        return "Пока недостаточно оценок RELYQO для уверенного совета."
    parts = []
    for item in leaders:
        parts.append(
            f'{item["name"]}: {item["score"]:.1f}/100, '
            f'{item["rating_count"]} оценок ({item["confidence_label"]})'
        )
    return (
        f'По критерию «{priority_label}» лидируют: ' + "; ".join(parts) + ". "
        "Перед посещением проверьте адрес, профиль и актуальные условия услуги."
    )


def public_advisor_items(body: PublicAdvisorRequest, db: Session) -> tuple[dict, list[dict]]:
    priority_key, priority_label = public_advisor_priority(body.question)
    distances: dict[str, float | None] = {}
    for candidate in body.candidates:
        current = distances.get(candidate.object_key)
        if current is None or (
            candidate.distance_km is not None and candidate.distance_km < current
        ):
            distances[candidate.object_key] = candidate.distance_km
    partner_ids = [
        key.removeprefix("relyqo:")
        for key in distances
        if key.startswith("relyqo:")
    ]
    manual_ids = [
        key.removeprefix("manual:")
        for key in distances
        if key.startswith("manual:")
    ]
    partner_rows = (
        db.execute(
            select(Branch, Organization)
            .join(Organization, Organization.id == Branch.organization_id)
            .where(
                Branch.id.in_(partner_ids),
                Branch.active.is_(True),
                Organization.profile_status.in_({"PUBLISHED", "VERIFIED_PARTNER"}),
            )
        ).all()
        if partner_ids
        else []
    )
    manual_places = (
        db.scalars(
            select(ManualPlace).where(
                ManualPlace.id.in_(manual_ids), ManualPlace.active.is_(True)
            )
        ).all()
        if manual_ids
        else []
    )
    accepted_keys = {
        *(f"relyqo:{branch.id}" for branch, _ in partner_rows),
        *(f"manual:{place.id}" for place in manual_places),
    }
    community_rows = (
        db.execute(
            select(
                CommunityRating.object_key,
                func.avg(CommunityRating.community_score),
                func.avg(CommunityRating.overall),
                func.avg(CommunityRating.quality),
                func.avg(CommunityRating.service),
                func.avg(CommunityRating.cleanliness),
                func.avg(CommunityRating.value),
                func.count(CommunityRating.id),
            )
            .where(CommunityRating.object_key.in_(accepted_keys))
            .group_by(CommunityRating.object_key)
        ).all()
        if accepted_keys
        else []
    )
    community_stats = {
        row[0]: {
            "score": round(float(row[1]), 1),
            "metrics": {
                "overall": round(float(row[2]) * 10, 1),
                "quality": round(float(row[3]) * 10, 1),
                "service": round(float(row[4]) * 10, 1),
                "cleanliness": round(float(row[5]) * 10, 1),
                "value": round(float(row[6]) * 10, 1),
            },
            "count": int(row[7]),
        }
        for row in community_rows
    }
    organization_ids = {organization.id for _, organization in partner_rows}
    verified_rows = (
        db.execute(
            select(
                Rating.organization_id,
                func.avg(Rating.overall),
                func.avg(Rating.food),
                func.avg(Rating.service),
                func.avg(Rating.cleanliness),
                func.avg(Rating.value),
                func.count(Rating.id),
            )
            .where(
                Rating.organization_id.in_(organization_ids),
                Rating.included.is_(True),
            )
            .group_by(Rating.organization_id)
        ).all()
        if organization_ids
        else []
    )
    verified_stats = {
        row[0]: {
            "metrics": {
                "overall": round(float(row[1]) * 10, 1),
                "quality": round(float(row[2]) * 10, 1),
                "service": round(float(row[3]) * 10, 1),
                "cleanliness": round(float(row[4]) * 10, 1),
                "value": round(float(row[5]) * 10, 1),
            },
            "count": int(row[6]),
        }
        for row in verified_rows
    }

    def base_item(
        *, object_key: str, source: str, name: str, category: str,
        address: str, description: str | None, distance_km: float | None,
        profile_status: str = "", verified_score: float = 0,
        verified_count: int = 0, verified_metrics: dict | None = None,
    ) -> dict:
        rate_query = urlencode(
            {
                "object_key": object_key,
                "source": source,
                "name": name,
                "address": address,
                "category": category,
            }
        )
        profile_query = {
            "object_key": object_key,
            "source": source,
            "name": name,
            "address": address,
            "category": category,
            "category_code": category,
            "description": description or "Профиль организации в RELYQO.",
            "profile_status": profile_status,
            "verified_score": verified_score,
            "verified_count": verified_count,
        }
        for key, value in (verified_metrics or {}).items():
            profile_query[f"verified_{key}"] = value
        return {
            "object_key": object_key,
            "source": source,
            "name": name,
            "category": category,
            "address": address,
            "description": description or "Профиль организации в RELYQO.",
            "distance_km": round(distance_km, 2) if distance_km is not None else None,
            "href": f"/place?{urlencode(profile_query)}",
            "rate_href": f"/community-rate?{rate_query}",
        }

    verified_items: list[dict] = []
    community_items: list[dict] = []
    for branch, organization in partner_rows:
        object_key = f"relyqo:{branch.id}"
        verified = verified_stats.get(organization.id)
        base = base_item(
            object_key=object_key,
            source="RELYQO_PARTNER",
            name=organization.name,
            category=organization.category,
            address=branch.address or branch.name,
            description=organization.description,
            distance_km=distances[object_key],
            profile_status=organization.profile_status,
            verified_score=round(float(organization.score), 1),
            verified_count=verified["count"] if verified else 0,
            verified_metrics=verified["metrics"] if verified else None,
        )
        if verified:
            metric_key = "overall" if priority_key == "distance" else priority_key
            verified_items.append(
                {
                    **base,
                    "score_type": "VERIFIED",
                    "score": round(float(organization.score), 1),
                    "metric_score": verified["metrics"].get(metric_key),
                    "rating_count": verified["count"],
                }
            )
        community = community_stats.get(object_key)
        if community:
            metric_key = "overall" if priority_key == "distance" else priority_key
            community_items.append(
                {
                    **base,
                    "score_type": "COMMUNITY",
                    "score": community["score"],
                    "metric_score": community["metrics"].get(metric_key),
                    "rating_count": community["count"],
                }
            )
    for place in manual_places:
        object_key = f"manual:{place.id}"
        community = community_stats.get(object_key)
        if not community:
            continue
        metric_key = "overall" if priority_key == "distance" else priority_key
        community_items.append(
            {
                **base_item(
                    object_key=object_key,
                    source="MANUAL",
                    name=place.name,
                    category=place.category,
                    address=place.address,
                    description=place.description,
                    distance_km=distances[object_key],
                ),
                "score_type": "COMMUNITY",
                "score": community["score"],
                "metric_score": community["metrics"].get(metric_key),
                "rating_count": community["count"],
            }
        )

    def ranking_key(item: dict):
        distance = item["distance_km"]
        if priority_key == "distance":
            return (
                distance is None,
                distance if distance is not None else math.inf,
                -item["score"],
                -item["rating_count"],
                item["name"].casefold(),
            )
        return (
            -float(item["metric_score"] or item["score"]),
            -item["rating_count"],
            distance is None,
            distance if distance is not None else math.inf,
            item["name"].casefold(),
        )

    sections = []
    for score_type, label, items in (
        ("VERIFIED", "Verified — посещение подтверждено QR", verified_items),
        ("COMMUNITY", "Community — оценки потребителей", community_items),
    ):
        selected = sorted(items, key=ranking_key)[:3]
        for position, item in enumerate(selected, 1):
            item["position"] = position
            item["confidence_label"] = (
                "достаточно подтверждений"
                if item["rating_count"] >= 20
                else "ранний сигнал — данных пока мало"
            )
        if selected:
            sections.append(
                {"score_type": score_type, "label": label, "items": selected}
            )
    return {"key": priority_key, "label": priority_label}, sections


def normalize_business_profile(body: BusinessOwnerRegister | BusinessProfileUpdate) -> dict:
    website = (body.website or "").strip() or None
    if website and not re.match(r"^https?://", website, flags=re.IGNORECASE):
        raise HTTPException(422, "Сайт должен начинаться с http:// или https://")
    return {
        "organization_name": " ".join(body.organization_name.split()),
        "category": body.category,
        "description": " ".join(body.description.split()),
        "address": " ".join(body.address.split()),
        "city": normalize_city_name(body.city),
        "country_code": body.country_code.strip().upper(),
        "phone": " ".join((body.phone or "").split()) or None,
        "website": website,
        "latitude": body.latitude,
        "longitude": body.longitude,
    }


def business_profile_payload(user: User, db: Session) -> dict:
    organization = db.get(Organization, user.organization_id)
    branch = db.scalar(
        select(Branch)
        .where(Branch.organization_id == user.organization_id)
        .order_by(Branch.id)
    )
    if not organization or not branch:
        raise HTTPException(404, "Профиль организации не найден")
    return {
        "username": user.username,
        "role": user.role,
        "organization_id": organization.id,
        "branch_id": branch.id,
        "organization_name": organization.name,
        "category": organization.category,
        "description": organization.description or "",
        "phone": organization.phone,
        "website": organization.website,
        "profile_status": organization.profile_status,
        "address": branch.address or branch.name,
        "city": normalize_city_name(branch.city or organization.city),
        "country_code": branch.country_code,
        "latitude": branch.latitude,
        "longitude": branch.longitude,
        "verified_score": round(organization.score, 1),
        "verified_rating_count": organization.rating_count,
        "permissions": {
            "edit_profile": True,
            "create_rating": False,
            "edit_rating": False,
            "edit_score": False,
            "decide_review": False,
        },
    }


def consumer_html(filename: str) -> HTMLResponse:
    """Add the shared ad surface only to consumer-facing pages."""
    content = (static / filename).read_text(encoding="utf-8")
    if filename == "index.html" and not settings.demo_mode:
        content = content.replace(
            'id="demo" class="secondary"',
            'id="demo" class="secondary hidden" disabled aria-hidden="true"',
            1,
        )
    content = content.replace(
        "</head>",
        '<link rel="stylesheet" href="/static/ads.css?v=ads-3"></head>',
        1,
    )
    content = content.replace(
        "</body>",
        '<script src="/static/ads.js?v=ads-3"></script></body>',
        1,
    )
    return HTMLResponse(
        content=content,
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/", include_in_schema=False)
def web():
    return consumer_html("index.html")


@app.get("/consumer", include_in_schema=False)
def consumer_entry_web():
    """Explicit consumer entrance, separate from protected workspaces."""
    return consumer_html("index.html")


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


@app.get("/nearby", include_in_schema=False)
def nearby_web():
    return consumer_html("nearby.html")


@app.get("/terms", include_in_schema=False)
@app.get("/privacy", include_in_schema=False)
def legal_web():
    return FileResponse(
        static / "legal.html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/community-rate", include_in_schema=False)
def community_rate_web():
    return consumer_html("community-rate.html")


@app.get("/place", include_in_schema=False)
def place_web():
    return consumer_html("place.html")


@app.get("/rankings", include_in_schema=False)
def rankings_web():
    return consumer_html("rankings.html")


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


@app.get("/me", include_in_schema=False)
def consumer_web():
    return consumer_html("me.html")


@app.get("/me/rating", include_in_schema=False)
def consumer_rating_web():
    return consumer_html("rating-detail.html")


@app.get("/business-owner", include_in_schema=False)
def business_owner_web():
    return FileResponse(
        static / "business-owner.html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/admin", include_in_schema=False)
def admin_web():
    return FileResponse(
        static / "admin.html",
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


@app.post("/v1/consumer/register")
def register_consumer(
    body: ConsumerRegister,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    username = body.username.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,79}", username):
        raise HTTPException(
            422,
            "Имя: латинские буквы, цифры, точка, дефис или подчёркивание",
        )
    if db.scalar(select(User).where(User.username == username)):
        raise HTTPException(409, "Это имя пользователя уже занято")
    user = User(
        username=username,
        password_hash=password_hash(body.password),
        role=CONSUMER_ROLE,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Это имя пользователя уже занято")
    raw_token = secrets.token_urlsafe(32)
    db.add_all(
        [
            AuthSession(
                user_id=user.id,
                token_hash=token_hash(raw_token),
                expires_at=datetime.utcnow() + timedelta(hours=SESSION_HOURS),
            ),
            AuditLog(
                actor_type=CONSUMER_ROLE,
                action="CONSUMER_REGISTERED",
                entity_type="USER",
                entity_id=user.id,
            ),
        ]
    )
    db.commit()
    response.headers["Cache-Control"] = "no-store, max-age=0"
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


@app.post("/v1/business-owner/register")
def register_business_owner(
    body: BusinessOwnerRegister,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    username = body.username.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,79}", username):
        raise HTTPException(
            422,
            "Имя: латинские буквы, цифры, точка, дефис или подчёркивание",
        )
    if db.scalar(select(User).where(User.username == username)):
        raise HTTPException(409, "Это имя пользователя уже занято")
    profile = normalize_business_profile(body)
    organization = Organization(
        name=profile["organization_name"],
        city=profile["city"],
        category=profile["category"],
        description=profile["description"],
        phone=profile["phone"],
        website=profile["website"],
        profile_status="SELF_REGISTERED",
    )
    db.add(organization)
    db.flush()
    branch = Branch(
        organization_id=organization.id,
        name=profile["address"],
        address=profile["address"],
        city=profile["city"],
        country_code=profile["country_code"],
        latitude=profile["latitude"],
        longitude=profile["longitude"],
        active=True,
    )
    user = User(
        username=username,
        password_hash=password_hash(body.password),
        role=BUSINESS_OWNER_ROLE,
        organization_id=organization.id,
    )
    db.add_all([branch, user])
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Не удалось создать аккаунт с этими данными")
    raw_token = secrets.token_urlsafe(32)
    db.add_all(
        [
            AuthSession(
                user_id=user.id,
                token_hash=token_hash(raw_token),
                expires_at=datetime.utcnow() + timedelta(hours=SESSION_HOURS),
            ),
            AuditLog(
                actor_type=BUSINESS_OWNER_ROLE,
                action="BUSINESS_SELF_REGISTERED",
                entity_type="ORGANIZATION",
                entity_id=organization.id,
            ),
        ]
    )
    db.commit()
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.set_cookie(
        SESSION_COOKIE,
        raw_token,
        max_age=SESSION_HOURS * 3600,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        path="/",
    )
    return business_profile_payload(user, db)


@app.get("/v1/business-owner/profile")
def get_business_owner_profile(
    response: Response,
    relyqo_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    user = session_user(
        relyqo_session,
        db,
        {BUSINESS_OWNER_ROLE, OWNER_ROLE},
    )
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return business_profile_payload(user, db)


@app.post("/v1/business-owner/profile")
def update_business_owner_profile(
    body: BusinessProfileUpdate,
    response: Response,
    relyqo_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    user = session_user(
        relyqo_session,
        db,
        {BUSINESS_OWNER_ROLE, OWNER_ROLE},
    )
    organization = db.get(Organization, user.organization_id)
    branch = db.scalar(
        select(Branch)
        .where(Branch.organization_id == user.organization_id)
        .order_by(Branch.id)
    )
    if not organization or not branch:
        raise HTTPException(404, "Профиль организации не найден")
    profile = normalize_business_profile(body)
    organization.name = profile["organization_name"]
    organization.city = profile["city"]
    organization.category = profile["category"]
    organization.description = profile["description"]
    organization.phone = profile["phone"]
    organization.website = profile["website"]
    if (
        user.role == BUSINESS_OWNER_ROLE
        and organization.profile_status
        in {"PUBLISHED", "VERIFIED_PARTNER", "REJECTED"}
    ):
        organization.profile_status = "SELF_REGISTERED"
    branch.name = profile["address"]
    branch.address = profile["address"]
    branch.city = profile["city"]
    branch.country_code = profile["country_code"]
    branch.latitude = profile["latitude"]
    branch.longitude = profile["longitude"]
    db.add_all(
        [
            organization,
            branch,
            AuditLog(
                actor_type=user.role,
                action="BUSINESS_PROFILE_UPDATED",
                entity_type="ORGANIZATION",
                entity_id=organization.id,
            ),
        ]
    )
    db.commit()
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return business_profile_payload(user, db)


@app.get("/v1/admin/business-applications")
def business_applications(
    response: Response,
    relyqo_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    session_user(relyqo_session, db, ADMIN_ROLE)
    rows = db.execute(
        select(Organization, Branch, User)
        .join(Branch, Branch.organization_id == Organization.id)
        .join(User, User.organization_id == Organization.id)
        .where(
            Organization.profile_status.in_({"SELF_REGISTERED", "PUBLISHED"}),
            User.role == BUSINESS_OWNER_ROLE,
        )
        .order_by(Organization.created_at, Organization.id)
    ).all()
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return {
        "items": [
            {
                "organization_id": organization.id,
                "username": user.username,
                "organization_name": organization.name,
                "category": organization.category,
                "description": organization.description or "",
                "phone": organization.phone,
                "website": organization.website,
                "address": branch.address or branch.name,
                "city": normalize_city_name(branch.city or organization.city),
                "country_code": branch.country_code,
                "latitude": branch.latitude,
                "longitude": branch.longitude,
                "created_at": organization.created_at,
                "profile_status": organization.profile_status,
                "verified_score": round(organization.score, 1),
                "verified_rating_count": organization.rating_count,
            }
            for organization, branch, user in rows
        ],
        "count": len(rows),
        "permissions": {
            "edit_profile": False,
            "create_rating": False,
            "edit_rating": False,
            "edit_score": False,
            "decide_rating_review": False,
            "publish_profile": True,
        },
    }


@app.get("/v1/admin/dashboard")
def admin_dashboard(
    response: Response,
    relyqo_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    """Read-only operational overview for the isolated administrator role."""
    admin = session_user(relyqo_session, db, ADMIN_ROLE)

    def count_rows(model, *conditions) -> int:
        statement = select(func.count()).select_from(model)
        if conditions:
            statement = statement.where(*conditions)
        return int(db.scalar(statement) or 0)

    recent_events = db.scalars(
        select(AuditLog)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(12)
    ).all()
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return {
        "admin": {"username": admin.username, "role": admin.role},
        "overview": {
            "pending_profiles": count_rows(
                Organization, Organization.profile_status == "SELF_REGISTERED"
            ),
            "published_waiting_qr": count_rows(
                Organization, Organization.profile_status == "PUBLISHED"
            ),
            "verified_partners": count_rows(
                Organization, Organization.profile_status == "VERIFIED_PARTNER"
            ),
            "consumers": count_rows(
                User, User.role == CONSUMER_ROLE, User.active.is_(True)
            ),
            "business_accounts": count_rows(
                User, User.role == BUSINESS_OWNER_ROLE, User.active.is_(True)
            ),
            "verified_ratings": count_rows(Rating),
            "community_ratings": count_rows(CommunityRating),
            "consumer_places": count_rows(ManualPlace, ManualPlace.active.is_(True)),
            "open_owner_reviews": count_rows(
                OwnerReview, OwnerReview.status == "PENDING"
            ),
            "active_advertisements": count_rows(
                Advertisement, Advertisement.active.is_(True)
            ),
        },
        "recent_audit": [
            {
                "actor_type": event.actor_type,
                "action": event.action,
                "entity_type": event.entity_type,
                "entity_id": event.entity_id,
                "created_at": event.created_at,
            }
            for event in recent_events
        ],
        "boundaries": {
            "consumer_portal": "/consumer",
            "admin_portal": "/admin",
            "owner_review_portal": "/review",
            "admin_can_create_ratings": False,
            "admin_can_edit_ratings": False,
            "admin_can_edit_score": False,
            "admin_can_decide_owner_review": False,
            "score_engine": "deterministic_weighted_ces_v1",
        },
    }


def advertisement_payload(advertisement: Advertisement, *, public: bool) -> dict:
    payload = {
        "id": advertisement.id,
        "campaign_name": advertisement.campaign_name if not public else None,
        "sponsor_name": advertisement.sponsor_name,
        "headline": advertisement.headline,
        "message": advertisement.message,
        "cta_text": advertisement.cta_text,
        "placement": advertisement.placement,
        "page_scope": advertisement.page_scope,
        "starts_at": advertisement.starts_at,
        "ends_at": advertisement.ends_at,
        "active": advertisement.active,
        "created_at": advertisement.created_at,
        "updated_at": advertisement.updated_at,
        "media": (
            {
                "kind": advertisement.media_kind,
                "content_type": advertisement.media_content_type,
                "filename": advertisement.media_filename,
                "size_bytes": advertisement.media_size_bytes,
                "url": f"/v1/public/advertisements/{advertisement.id}/media",
            }
            if advertisement.media_kind
            else None
        ),
    }
    if public:
        payload.pop("campaign_name")
        payload["has_link"] = bool(advertisement.target_url)
        payload["click_url"] = (
            f"/v1/public/advertisements/{advertisement.id}/open"
            if advertisement.target_url
            else None
        )
    else:
        payload.update(
            target_url=advertisement.target_url,
            impressions=advertisement.impressions,
            clicks=advertisement.clicks,
            max_impressions=advertisement.max_impressions,
        )
    return payload


def utc_naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def advertisement_is_available(advertisement: Advertisement) -> bool:
    now = datetime.utcnow()
    return bool(
        advertisement.active
        and (advertisement.starts_at is None or advertisement.starts_at <= now)
        and (advertisement.ends_at is None or advertisement.ends_at >= now)
    )


def normalized_advertisement_values(body: AdvertisementCreate) -> dict:
    campaign_name = body.campaign_name.strip()
    sponsor_name = body.sponsor_name.strip()
    headline = body.headline.strip()
    message = body.message.strip()
    cta_text = body.cta_text.strip()
    starts_at = utc_naive(body.starts_at)
    ends_at = utc_naive(body.ends_at)
    if not campaign_name or not sponsor_name or not headline or not message or not cta_text:
        raise HTTPException(
            422,
            "Заполните название кампании, рекламодателя, заголовок, текст и кнопку",
        )
    if body.placement == "TOP_BANNER" and (
        len(headline) > 55 or len(message) > 160
    ):
        raise HTTPException(
            422,
            "Для верхней панели: заголовок до 55, текст до 160 символов",
        )
    if body.placement == "CORNER" and (len(headline) > 80 or len(message) > 240):
        raise HTTPException(
            422,
            "Для углового блока: заголовок до 80, текст до 240 символов",
        )
    if starts_at and ends_at and ends_at <= starts_at:
        raise HTTPException(422, "Дата окончания должна быть позже даты начала")
    return {
        "campaign_name": campaign_name,
        "sponsor_name": sponsor_name,
        "headline": headline,
        "message": message,
        "cta_text": cta_text,
        "target_url": str(body.target_url) if body.target_url else None,
        "placement": body.placement,
        "page_scope": body.page_scope,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "max_impressions": body.max_impressions,
    }


def validate_advertisement_media(content_type: str, raw: bytes) -> tuple[str, int]:
    specification = ADVERTISEMENT_MEDIA_TYPES.get(content_type)
    if not specification:
        raise HTTPException(
            415,
            "Разрешены JPEG, PNG, WebP, MP4, WebM, PDF, PPT и PPTX",
        )
    media_kind, maximum_size = specification
    if not raw:
        raise HTTPException(422, "Медиафайл пуст")
    if len(raw) > maximum_size:
        limits = {"IMAGE": "5 МБ", "VIDEO": "25 МБ", "PRESENTATION": "15 МБ"}
        raise HTTPException(413, f"Максимальный размер: {limits[media_kind]}")
    valid_magic = {
        "image/jpeg": raw.startswith(b"\xff\xd8\xff"),
        "image/png": raw.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/webp": raw.startswith(b"RIFF") and raw[8:12] == b"WEBP",
        "video/mp4": len(raw) >= 12 and raw[4:8] == b"ftyp",
        "video/webm": raw.startswith(b"\x1aE\xdf\xa3"),
        "application/pdf": raw.startswith(b"%PDF-"),
        "application/vnd.ms-powerpoint": raw.startswith(b"\xd0\xcf\x11\xe0"),
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": raw.startswith(
            b"PK\x03\x04"
        ),
    }[content_type]
    if not valid_magic:
        raise HTTPException(422, "Содержимое файла не соответствует его формату")
    return media_kind, maximum_size


@app.get("/v1/admin/advertisements")
def admin_advertisements(
    response: Response,
    relyqo_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    session_user(relyqo_session, db, ADMIN_ROLE)
    rows = db.scalars(
        select(Advertisement).order_by(
            Advertisement.created_at.desc(), Advertisement.id.desc()
        )
    ).all()
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return {
        "items": [advertisement_payload(row, public=False) for row in rows],
        "count": len(rows),
        "score_policy": "Advertising never changes RELYQO Score or ranking position",
    }


@app.post("/v1/admin/advertisements")
def create_advertisement(
    body: AdvertisementCreate,
    relyqo_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    admin = session_user(relyqo_session, db, ADMIN_ROLE)
    advertisement = Advertisement(
        **normalized_advertisement_values(body),
        active=body.active,
        created_by_user_id=admin.id,
    )
    db.add(advertisement)
    db.flush()
    db.add(
        AuditLog(
            actor_type=admin.role,
            action="ADVERTISEMENT_CREATED",
            entity_type="ADVERTISEMENT",
            entity_id=advertisement.id,
        )
    )
    db.commit()
    return advertisement_payload(advertisement, public=False)


@app.post("/v1/admin/advertisements/{advertisement_id}")
def update_advertisement(
    advertisement_id: str,
    body: AdvertisementCreate,
    relyqo_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    admin = session_user(relyqo_session, db, ADMIN_ROLE)
    advertisement = db.get(Advertisement, advertisement_id)
    if not advertisement:
        raise HTTPException(404, "Рекламная кампания не найдена")
    for field, value in normalized_advertisement_values(body).items():
        setattr(advertisement, field, value)
    advertisement.updated_at = datetime.utcnow()
    db.add_all(
        [
            advertisement,
            AuditLog(
                actor_type=admin.role,
                action="ADVERTISEMENT_UPDATED",
                entity_type="ADVERTISEMENT",
                entity_id=advertisement.id,
            ),
        ]
    )
    db.commit()
    return advertisement_payload(advertisement, public=False)


@app.post("/v1/admin/advertisements/{advertisement_id}/media")
async def upload_advertisement_media(
    advertisement_id: str,
    request: Request,
    relyqo_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    admin = session_user(relyqo_session, db, ADMIN_ROLE)
    advertisement = db.get(Advertisement, advertisement_id)
    if not advertisement:
        raise HTTPException(404, "Рекламная кампания не найдена")
    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    specification = ADVERTISEMENT_MEDIA_TYPES.get(content_type)
    if not specification:
        raise HTTPException(
            415,
            "Разрешены JPEG, PNG, WebP, MP4, WebM, PDF, PPT и PPTX",
        )
    maximum_size = specification[1]
    advertised_length = request.headers.get("content-length")
    try:
        if advertised_length and int(advertised_length) > maximum_size:
            raise HTTPException(413, "Медиафайл слишком большой")
    except ValueError as exc:
        raise HTTPException(400, "Некорректный размер медиафайла") from exc
    chunks: list[bytes] = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > maximum_size:
            raise HTTPException(413, "Медиафайл слишком большой")
        chunks.append(chunk)
    raw = b"".join(chunks)
    media_kind, _ = validate_advertisement_media(content_type, raw)
    supplied_filename = unquote(request.headers.get("x-relyqo-filename", "media"))
    filename = Path(supplied_filename).name.strip()[:180] or "media"
    stored_media = db.get(AdvertisementMedia, advertisement.id)
    if stored_media:
        stored_media.media_data = raw
        stored_media.created_at = datetime.utcnow()
    else:
        stored_media = AdvertisementMedia(
            advertisement_id=advertisement.id,
            media_data=raw,
        )
    advertisement.media_kind = media_kind
    advertisement.media_content_type = content_type
    advertisement.media_filename = filename
    advertisement.media_size_bytes = len(raw)
    advertisement.updated_at = datetime.utcnow()
    db.add_all(
        [
            advertisement,
            stored_media,
            AuditLog(
                actor_type=admin.role,
                action="ADVERTISEMENT_MEDIA_UPLOADED",
                entity_type="ADVERTISEMENT",
                entity_id=advertisement.id,
            ),
        ]
    )
    db.commit()
    return advertisement_payload(advertisement, public=False)


@app.post("/v1/admin/advertisements/{advertisement_id}/media/remove")
def remove_advertisement_media(
    advertisement_id: str,
    relyqo_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    admin = session_user(relyqo_session, db, ADMIN_ROLE)
    advertisement = db.get(Advertisement, advertisement_id)
    if not advertisement:
        raise HTTPException(404, "Рекламная кампания не найдена")
    stored_media = db.get(AdvertisementMedia, advertisement.id)
    if stored_media:
        db.delete(stored_media)
    advertisement.media_kind = None
    advertisement.media_content_type = None
    advertisement.media_filename = None
    advertisement.media_size_bytes = None
    advertisement.updated_at = datetime.utcnow()
    db.add_all(
        [
            advertisement,
            AuditLog(
                actor_type=admin.role,
                action="ADVERTISEMENT_MEDIA_REMOVED",
                entity_type="ADVERTISEMENT",
                entity_id=advertisement.id,
            ),
        ]
    )
    db.commit()
    return advertisement_payload(advertisement, public=False)


@app.post("/v1/admin/advertisements/{advertisement_id}/status")
def change_advertisement_status(
    advertisement_id: str,
    body: AdvertisementStatus,
    relyqo_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    admin = session_user(relyqo_session, db, ADMIN_ROLE)
    advertisement = db.get(Advertisement, advertisement_id)
    if not advertisement:
        raise HTTPException(404, "Рекламная кампания не найдена")
    advertisement.active = body.active
    advertisement.updated_at = datetime.utcnow()
    db.add_all(
        [
            advertisement,
            AuditLog(
                actor_type=admin.role,
                action=(
                    "ADVERTISEMENT_ACTIVATED"
                    if body.active
                    else "ADVERTISEMENT_PAUSED"
                ),
                entity_type="ADVERTISEMENT",
                entity_id=advertisement.id,
            ),
        ]
    )
    db.commit()
    return advertisement_payload(advertisement, public=False)


@app.get("/v1/public/advertisements")
def public_advertisements(
    response: Response,
    placement: str | None = None,
    page: str | None = None,
    preview_id: str | None = None,
    db: Session = Depends(get_db),
):
    normalized_placement = placement.strip().upper() if placement else None
    if normalized_placement and normalized_placement not in ADVERTISEMENT_PLACEMENTS:
        raise HTTPException(422, "Неизвестное место рекламного блока")
    normalized_page = page.strip().upper() if page else None
    if normalized_page and normalized_page not in ADVERTISEMENT_PAGE_SCOPES - {"ALL"}:
        raise HTTPException(422, "Неизвестная страница показа рекламы")
    now = datetime.utcnow()
    statement = select(Advertisement).where(
        Advertisement.active.is_(True),
        or_(Advertisement.starts_at.is_(None), Advertisement.starts_at <= now),
        or_(Advertisement.ends_at.is_(None), Advertisement.ends_at >= now),
        or_(
            Advertisement.max_impressions.is_(None),
            Advertisement.impressions < Advertisement.max_impressions,
        ),
    )
    if preview_id:
        statement = statement.where(Advertisement.id == preview_id)
    if normalized_placement:
        statement = statement.where(Advertisement.placement == normalized_placement)
    if normalized_page and not preview_id:
        statement = statement.where(
            Advertisement.page_scope.in_({"ALL", normalized_page})
        )
    rows = db.scalars(
        statement.order_by(Advertisement.updated_at.desc(), Advertisement.id.desc())
        .limit(20)
    ).all()
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return {
        "items": [advertisement_payload(row, public=True) for row in rows],
        "count": len(rows),
        "personal_tracking": False,
        "affects_score_or_ranking": False,
    }


@app.post("/v1/public/advertisements/{advertisement_id}/impression", status_code=204)
def record_advertisement_impression(
    advertisement_id: str,
    db: Session = Depends(get_db),
):
    now = datetime.utcnow()
    result = db.execute(
        update(Advertisement)
        .where(
            Advertisement.id == advertisement_id,
            Advertisement.active.is_(True),
            or_(Advertisement.starts_at.is_(None), Advertisement.starts_at <= now),
            or_(Advertisement.ends_at.is_(None), Advertisement.ends_at >= now),
            or_(
                Advertisement.max_impressions.is_(None),
                Advertisement.impressions < Advertisement.max_impressions,
            ),
        )
        .values(impressions=Advertisement.impressions + 1)
    )
    if not result.rowcount:
        raise HTTPException(404, "Активная реклама не найдена")
    db.commit()
    return Response(status_code=204)


@app.get("/v1/public/advertisements/{advertisement_id}/media")
def advertisement_media(
    advertisement_id: str,
    db: Session = Depends(get_db),
):
    advertisement = db.get(Advertisement, advertisement_id)
    if (
        not advertisement
        or not advertisement_is_available(advertisement)
        or not advertisement.media_kind
    ):
        raise HTTPException(404, "Активный медиафайл рекламы не найден")
    stored_media = db.get(AdvertisementMedia, advertisement.id)
    if not stored_media:
        raise HTTPException(404, "Медиафайл рекламы не найден")
    presentation_extensions = {
        "application/pdf": "pdf",
        "application/vnd.ms-powerpoint": "ppt",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    }
    extension = presentation_extensions.get(advertisement.media_content_type, "file")
    disposition = (
        f'attachment; filename="relyqo-presentation.{extension}"'
        if advertisement.media_kind == "PRESENTATION"
        else "inline"
    )
    return Response(
        content=stored_media.media_data,
        media_type=advertisement.media_content_type,
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Content-Disposition": disposition,
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/v1/public/advertisements/{advertisement_id}/open")
def open_advertisement(
    advertisement_id: str,
    db: Session = Depends(get_db),
):
    advertisement = db.get(Advertisement, advertisement_id)
    if (
        not advertisement
        or not advertisement_is_available(advertisement)
        or not advertisement.target_url
    ):
        raise HTTPException(404, "Активная ссылка рекламы не найдена")
    target = urlparse(advertisement.target_url)
    if target.scheme not in {"http", "https"} or not target.netloc:
        raise HTTPException(409, "Ссылка рекламной кампании недоступна")
    db.execute(
        update(Advertisement)
        .where(
            Advertisement.id == advertisement.id,
            Advertisement.active.is_(True),
        )
        .values(clicks=Advertisement.clicks + 1)
    )
    db.commit()
    return RedirectResponse(advertisement.target_url, status_code=302)


@app.post("/v1/admin/business-applications/{organization_id}/decision")
def decide_business_application(
    organization_id: str,
    body: BusinessApplicationDecision,
    relyqo_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    admin = session_user(relyqo_session, db, ADMIN_ROLE)
    organization = db.get(Organization, organization_id)
    if not organization:
        raise HTTPException(404, "Заявка организации не найдена")
    if organization.profile_status == "SELF_REGISTERED":
        if body.decision not in {"PUBLISH", "REJECT"}:
            raise HTTPException(409, "Сначала опубликуйте профиль организации")
        organization.profile_status = (
            "PUBLISHED" if body.decision == "PUBLISH" else "REJECTED"
        )
    elif organization.profile_status == "PUBLISHED":
        if body.decision != "ENABLE_QR":
            raise HTTPException(409, "Профиль уже опубликован")
        organization.profile_status = "VERIFIED_PARTNER"
    else:
        raise HTTPException(409, "Решение по этой заявке уже принято")
    db.add_all(
        [
            organization,
            AuditLog(
                actor_type=admin.role,
                action=f"BUSINESS_PROFILE_{organization.profile_status}",
                entity_type="ORGANIZATION",
                entity_id=organization.id,
            ),
        ]
    )
    db.commit()
    return {
        "organization_id": organization.id,
        "profile_status": organization.profile_status,
        "verified_score": round(organization.score, 1),
        "verified_rating_count": organization.rating_count,
        "score_changed": False,
        "ratings_changed": False,
    }


@app.post("/v1/business-owner/visit-token")
def business_owner_visit_token(
    body: OwnerTokenCreate,
    request: Request,
    relyqo_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    user = session_user(
        relyqo_session,
        db,
        {BUSINESS_OWNER_ROLE, OWNER_ROLE},
    )
    organization = db.get(Organization, user.organization_id)
    if not organization or organization.profile_status != "VERIFIED_PARTNER":
        raise HTTPException(403, "Выдача QR ещё не подключена администратором RELYQO")
    branch = db.scalar(
        select(Branch)
        .where(
            Branch.organization_id == organization.id,
            Branch.active.is_(True),
        )
        .order_by(Branch.id)
    )
    if not branch:
        raise HTTPException(404, "Активный филиал не найден")
    existing = db.scalar(
        select(VisitToken).where(
            VisitToken.branch_id == branch.id,
            VisitToken.transaction_reference == body.transaction_reference,
        )
    )
    if existing:
        raise HTTPException(409, "Для этого чека QR уже выпускался")
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
        "organization_id": organization.id,
        "branch_id": branch.id,
        "expires_in": 10800,
        "visit_url": f"{base_url}/?token={token}",
        "qr_url": f"{base_url}/v1/qr.png?token={token}",
    }


@app.get("/v1/consumer/dashboard")
def consumer_dashboard(
    response: Response,
    relyqo_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    user = session_user(relyqo_session, db, CONSUMER_ROLE)
    favorites = db.scalars(
        select(ConsumerFavorite)
        .where(ConsumerFavorite.user_id == user.id)
        .order_by(ConsumerFavorite.created_at.desc())
    ).all()
    community_ratings = db.scalars(
        select(CommunityRating)
        .where(CommunityRating.consumer_user_id == user.id)
        .order_by(CommunityRating.created_at.desc())
        .limit(100)
    ).all()
    verified_ratings = db.scalars(
        select(Rating)
        .where(Rating.consumer_user_id == user.id)
        .order_by(Rating.created_at.desc())
        .limit(100)
    ).all()
    community_rating_ids = [rating.id for rating in community_ratings]
    verified_rating_ids = [rating.id for rating in verified_ratings]
    community_photos = (
        db.scalars(
            select(RatingPhoto)
            .where(RatingPhoto.community_rating_id.in_(community_rating_ids))
            .order_by(RatingPhoto.created_at.desc())
        ).all()
        if community_rating_ids
        else []
    )
    verified_photos = (
        db.scalars(
            select(RatingPhoto)
            .where(RatingPhoto.rating_id.in_(verified_rating_ids))
            .order_by(RatingPhoto.created_at.desc())
        ).all()
        if verified_rating_ids
        else []
    )
    community_photos_by_rating = {
        photo.community_rating_id: photo for photo in community_photos
    }
    verified_photos_by_rating = {
        photo.rating_id: photo for photo in verified_photos
    }
    favorite_items = []
    for favorite in favorites:
        item = consumer_object_info(favorite.object_key, favorite.source, db)
        item["saved_at"] = favorite.created_at
        favorite_items.append(item)
    rating_items = []
    for rating in community_ratings:
        item = consumer_object_info(rating.object_key, rating.source, db)
        photo = community_photos_by_rating.get(rating.id)
        item.update(
            rating_id=rating.id,
            rating_type="COMMUNITY",
            rating_type_label="Community",
            category=rating.category,
            display_score=round(rating.community_score, 1),
            score_label="Community Score",
            community_score=round(rating.community_score, 1),
            rated_at=rating.created_at,
            status="PUBLISHED",
            photo=(
                {
                    "id": photo.id,
                    "url": f"/v1/consumer/rating-photos/{photo.id}",
                    "analysis_status": photo.analysis_status,
                    "ai_analysis": photo.ai_analysis,
                    "created_at": photo.created_at,
                }
                if photo
                else None
            ),
        )
        rating_items.append(item)
    for rating in verified_ratings:
        visit = db.get(Visit, rating.visit_id)
        branch = db.get(Branch, visit.branch_id) if visit else None
        org = db.get(Organization, rating.organization_id)
        object_key = f"relyqo:{branch.id}" if branch else "relyqo:unavailable"
        item = consumer_object_info(object_key, "RELYQO_PARTNER", db)
        if org and not branch:
            item.update(name=org.name, description="Подтверждённая QR-оценка")
        photo = verified_photos_by_rating.get(rating.id)
        item.update(
            rating_id=rating.id,
            rating_type="VERIFIED",
            rating_type_label="Verified · QR",
            display_score=round(rating.ces, 1),
            score_label="Verified CES",
            rated_at=rating.created_at,
            status=rating.status,
            included_in_verified_relyqo_score=rating.included,
            photo=(
                {
                    "id": photo.id,
                    "url": f"/v1/consumer/rating-photos/{photo.id}",
                    "analysis_status": photo.analysis_status,
                    "ai_analysis": photo.ai_analysis,
                    "created_at": photo.created_at,
                }
                if photo
                else None
            ),
        )
        rating_items.append(item)
    rating_items.sort(key=lambda item: item["rated_at"], reverse=True)
    photo_items = []
    community_ratings_by_id = {
        rating.id: rating for rating in community_ratings
    }
    for photo in community_photos:
        rating = community_ratings_by_id.get(photo.community_rating_id)
        if not rating:
            continue
        item = consumer_object_info(rating.object_key, rating.source, db)
        item.update(
            photo_id=photo.id,
            photo_url=f"/v1/consumer/rating-photos/{photo.id}",
            rating_id=rating.id,
            rating_type="COMMUNITY",
            rating_type_label="Community",
            category=rating.category,
            display_score=round(rating.community_score, 1),
            community_score=round(rating.community_score, 1),
            analysis_status=photo.analysis_status,
            ai_analysis=photo.ai_analysis,
            photographed_at=photo.created_at,
        )
        photo_items.append(item)
    verified_ratings_by_id = {rating.id: rating for rating in verified_ratings}
    for photo in verified_photos:
        rating = verified_ratings_by_id.get(photo.rating_id)
        if not rating:
            continue
        visit = db.get(Visit, rating.visit_id)
        branch = db.get(Branch, visit.branch_id) if visit else None
        org = db.get(Organization, rating.organization_id)
        object_key = f"relyqo:{branch.id}" if branch else "relyqo:unavailable"
        item = consumer_object_info(object_key, "RELYQO_PARTNER", db)
        if org and not branch:
            item.update(name=org.name, description="Подтверждённая QR-оценка")
        item.update(
            photo_id=photo.id,
            photo_url=f"/v1/consumer/rating-photos/{photo.id}",
            rating_id=rating.id,
            rating_type="VERIFIED",
            rating_type_label="Verified · QR",
            display_score=round(rating.ces, 1),
            analysis_status=photo.analysis_status,
            ai_analysis=photo.ai_analysis,
            photographed_at=photo.created_at,
        )
        photo_items.append(item)
    photo_items.sort(key=lambda item: item["photographed_at"], reverse=True)
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return {
        "username": user.username,
        "role": user.role,
        "favorites": favorite_items,
        "ratings": rating_items,
        "photos": photo_items,
        "principles": {
            "verified_score_is_deterministic": True,
            "community_score_is_separate": True,
            "external_catalogs_are_disabled": True,
        },
    }


@app.get("/v1/consumer/rating-photos/{photo_id}", include_in_schema=False)
def consumer_rating_photo(
    photo_id: str,
    relyqo_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    user = session_user(relyqo_session, db, CONSUMER_ROLE)
    photo = db.get(RatingPhoto, photo_id)
    if not photo:
        raise HTTPException(404, "Фотография не найдена")
    allowed = False
    if photo.community_rating_id:
        community_rating = db.get(CommunityRating, photo.community_rating_id)
        allowed = bool(
            community_rating and community_rating.consumer_user_id == user.id
        )
    elif photo.rating_id:
        verified_rating = db.get(Rating, photo.rating_id)
        allowed = bool(
            verified_rating and verified_rating.consumer_user_id == user.id
        )
    if not allowed:
        raise HTTPException(404, "Фотография не найдена")
    return Response(
        content=photo.image_data,
        media_type=photo.content_type,
        headers={
            "Cache-Control": "private, no-store, max-age=0",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/v1/consumer/ratings/{rating_id}")
def consumer_rating_detail(
    rating_id: str,
    response: Response,
    relyqo_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    user = session_user(relyqo_session, db, CONSUMER_ROLE)
    response.headers["Cache-Control"] = "no-store, max-age=0"
    community_rating = db.get(CommunityRating, rating_id)
    if community_rating and community_rating.consumer_user_id == user.id:
        item = consumer_object_info(
            community_rating.object_key, community_rating.source, db
        )
        photo = db.scalar(
            select(RatingPhoto).where(
                RatingPhoto.community_rating_id == community_rating.id
            )
        )
        return {
            **item,
            "rating_id": community_rating.id,
            "rating_type": "COMMUNITY",
            "rating_type_label": "Community — мнение потребителя",
            "category": community_rating.category,
            "display_score": round(community_rating.community_score, 1),
            "score_label": "Community Score из 100",
            "community_score": round(community_rating.community_score, 1),
            "metrics": {
                "overall": community_rating.overall,
                "quality": community_rating.quality,
                "service": community_rating.service,
                "cleanliness": community_rating.cleanliness,
                "value": community_rating.value,
            },
            "rated_at": community_rating.created_at,
            "status": "PUBLISHED",
            "photo": rating_photo_payload(photo),
            "included_in_verified_relyqo_score": False,
            "consumer_is_only_rating_author": True,
            "ai_can_change_rating": False,
        }
    verified_rating = db.get(Rating, rating_id)
    if not verified_rating or verified_rating.consumer_user_id != user.id:
        raise HTTPException(404, "Оценка не найдена")
    visit = db.get(Visit, verified_rating.visit_id)
    branch = db.get(Branch, visit.branch_id) if visit else None
    organization = db.get(Organization, verified_rating.organization_id)
    object_key = f"relyqo:{branch.id}" if branch else "relyqo:unavailable"
    item = consumer_object_info(object_key, "RELYQO_PARTNER", db)
    if organization and not branch:
        item.update(name=organization.name, description="Подтверждённая QR-оценка")
    photo = db.scalar(
        select(RatingPhoto).where(RatingPhoto.rating_id == verified_rating.id)
    )
    return {
        **item,
        "rating_id": verified_rating.id,
        "rating_type": "VERIFIED",
        "rating_type_label": (
            "Verified — ожидает независимой проверки"
            if verified_rating.status == "PENDING_REVIEW"
            else "Verified — подтверждено одноразовым QR"
        ),
        "category": organization.category if organization else "OTHER",
        "display_score": round(verified_rating.ces, 1),
        "score_label": "Verified CES из 100",
        "metrics": {
            "overall": verified_rating.overall,
            "quality": verified_rating.food,
            "service": verified_rating.service,
            "cleanliness": verified_rating.cleanliness,
            "value": verified_rating.value,
        },
        "rated_at": verified_rating.created_at,
        "status": verified_rating.status,
        "photo": rating_photo_payload(photo),
        "included_in_verified_relyqo_score": verified_rating.included,
        "consumer_is_only_rating_author": True,
        "ai_can_change_rating": False,
    }


@app.post("/v1/consumer/assistant")
def consumer_assistant(
    body: ConsumerAssistantRequest,
    response: Response,
    relyqo_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    user = session_user(relyqo_session, db, CONSUMER_ROLE)
    now = datetime.utcnow()
    with _ai_lock:
        last_request = _consumer_ai_last_request.get(user.id)
        if last_request and (now - last_request).total_seconds() < AI_COOLDOWN_SECONDS:
            raise HTTPException(429, "Подождите минуту перед следующим вопросом")
        _consumer_ai_last_request[user.id] = now
    favorites = db.scalars(
        select(ConsumerFavorite)
        .where(ConsumerFavorite.user_id == user.id)
        .order_by(ConsumerFavorite.created_at.desc())
        .limit(30)
    ).all()
    community_ratings = db.scalars(
        select(CommunityRating)
        .where(CommunityRating.consumer_user_id == user.id)
        .order_by(CommunityRating.created_at.desc())
        .limit(30)
    ).all()
    verified_ratings = db.scalars(
        select(Rating)
        .where(Rating.consumer_user_id == user.id)
        .order_by(Rating.created_at.desc())
        .limit(30)
    ).all()
    category_stats: dict[str, dict] = {}
    for rating in community_ratings:
        stats = category_stats.setdefault(
            rating.category,
            {"rating_count": 0, "score_total": 0.0},
        )
        stats["rating_count"] += 1
        stats["score_total"] += rating.community_score
    verified_items = []
    for rating in verified_ratings:
        organization = db.get(Organization, rating.organization_id)
        category = organization.category if organization else "OTHER"
        stats = category_stats.setdefault(
            category,
            {"rating_count": 0, "score_total": 0.0},
        )
        stats["rating_count"] += 1
        stats["score_total"] += rating.ces
        verified_items.append(
            {
                "name": organization.name if organization else "Организация",
                "category": category,
                "verified_ces_given": round(rating.ces, 1),
                "status": rating.status,
            }
        )
    top_categories = sorted(
        (
            {
                "category": category,
                "rating_count": stats["rating_count"],
                "average_score_given": round(
                    stats["score_total"] / stats["rating_count"], 1
                ),
            }
            for category, stats in category_stats.items()
        ),
        key=lambda item: (-item["rating_count"], -item["average_score_given"]),
    )
    skills = [
        "compare_favorites",
        "analyze_personal_rating_history",
        "explain_score_sources",
        "prepare_service_checklist",
    ]
    context = {
        "question": body.question.strip(),
        "favorites": [
            consumer_object_info(item.object_key, item.source, db)
            for item in favorites
        ],
        "own_community_ratings": [
            {
                **consumer_object_info(item.object_key, item.source, db),
                "category": item.category,
                "community_score_given": round(item.community_score, 1),
            }
            for item in community_ratings
        ],
        "own_verified_ratings": verified_items,
        "preference_profile": {
            "basis": "derived for this request from the consumer's own ratings",
            "favorite_count": len(favorites),
            "community_rating_count": len(community_ratings),
            "verified_rating_count": len(verified_ratings),
            "top_categories": top_categories[:5],
            "persistent_model_training": False,
        },
        "available_skills": skills,
        "score_policy": {
            "verified": "deterministic QR-confirmed score",
            "community": "separate user opinion score",
            "catalog": "RELYQO partners and consumer-added places only",
            "advertising_changes_scores": False,
        },
    }
    try:
        answer = generate_consumer_assistance(context)
    except AIUnavailableError as exc:
        raise HTTPException(503, "AI-помощник ещё не подключён") from exc
    except AIServiceError as exc:
        raise HTTPException(502, "AI-помощник временно недоступен") from exc
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return {
        "answer": answer,
        "model": settings.openai_model,
        "skills": skills,
        "personalized_from_account": bool(
            favorites or community_ratings or verified_ratings
        ),
        "read_only": True,
        "disclaimer": "AI объясняет данные, но не меняет Score и решения Review.",
    }


@app.post("/v1/consumer/favorites")
def change_consumer_favorite(
    body: ConsumerFavoriteChange,
    response: Response,
    relyqo_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    user = session_user(relyqo_session, db, CONSUMER_ROLE)
    validate_public_object(body.object_key, body.source)
    favorite = db.scalar(
        select(ConsumerFavorite).where(
            ConsumerFavorite.user_id == user.id,
            ConsumerFavorite.object_key == body.object_key,
        )
    )
    if body.saved and not favorite:
        favorite = ConsumerFavorite(
            user_id=user.id,
            object_key=body.object_key,
            source=body.source,
        )
        db.add(favorite)
    elif not body.saved and favorite:
        db.delete(favorite)
    db.add(
        AuditLog(
            actor_type=CONSUMER_ROLE,
            action="FAVORITE_SAVED" if body.saved else "FAVORITE_REMOVED",
            entity_type="PUBLIC_OBJECT",
            entity_id=body.object_key[:36],
        )
    )
    db.commit()
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return {"object_key": body.object_key, "saved": body.saved}


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
    _, branch = ensure_fregat(db)
    existing = db.scalar(
        select(VisitToken).where(
            VisitToken.branch_id == branch.id,
            VisitToken.transaction_reference == body.transaction_reference
        )
    )
    if existing:
        raise HTTPException(409, "Для этого чека QR уже выпускался")
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


@app.get("/v1/public/maps-config")
def public_maps_config(response: Response):
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return {
        "configured": bool(settings.google_maps_browser_key),
        "browser_key": settings.google_maps_browser_key,
        "provider": "GOOGLE_MAPS_DISCOVERY",
        "external_place_sources": True,
        "external_place_storage": "none",
        "external_ratings_used": False,
        "search_radius_km": 50,
        "result_limit": 200,
        "location_storage": "none",
    }


@app.post("/v1/public/google-place-ids/sync", deprecated=True)
def sync_external_place_ids():
    raise HTTPException(
        410,
        "Импорт внешних каталогов отключён. Используйте собственный каталог RELYQO.",
    )


@app.get("/v1/public/catalog/stats")
def public_catalog_stats(response: Response, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store, max-age=0"
    partners = db.scalar(select(func.count()).select_from(Branch)) or 0
    consumer_places = db.scalar(select(func.count()).select_from(ManualPlace)) or 0
    return {
        "catalog_source": "RELYQO_ONLY",
        "external_place_sources": False,
        "partners": int(partners),
        "consumer_places": int(consumer_places),
        "total_places": int(partners + consumer_places),
    }


@app.post("/v1/public/branches/nearby")
def public_nearby_branches(
    search: NearbySearch,
    response: Response,
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store, max-age=0"
    latitude = search.latitude
    longitude = search.longitude
    radius_km = search.radius_km
    limit = search.limit
    lat_delta = radius_km / 110.574
    longitude_scale = max(0.01, 111.320 * math.cos(math.radians(latitude)))
    lng_delta = radius_km / longitude_scale
    rows = db.execute(
        select(Branch, Organization)
        .join(Organization, Organization.id == Branch.organization_id)
        .where(
            Branch.active.is_(True),
            Organization.profile_status.in_({"PUBLISHED", "VERIFIED_PARTNER"}),
            Branch.latitude.is_not(None),
            Branch.longitude.is_not(None),
            Branch.latitude.between(latitude - lat_delta, latitude + lat_delta),
            Branch.longitude.between(longitude - lng_delta, longitude + lng_delta),
        )
        .limit(limit * 3)
    ).all()
    organization_ids = [organization.id for _, organization in rows]
    community_keys = [f"relyqo:{branch.id}" for branch, _ in rows]
    community_rows = (
        db.execute(
            select(
                CommunityRating.object_key,
                func.avg(CommunityRating.community_score),
                func.count(CommunityRating.id),
            )
            .where(CommunityRating.object_key.in_(community_keys))
            .group_by(CommunityRating.object_key)
        ).all()
        if community_keys
        else []
    )
    community_stats = {
        row[0]: {
            "community_score": round(float(row[1]), 1),
            "community_rating_count": int(row[2]),
        }
        for row in community_rows
    }
    metric_rows = (
        db.execute(
            select(
                Rating.organization_id,
                func.avg(Rating.overall),
                func.avg(Rating.food),
                func.avg(Rating.service),
                func.avg(Rating.cleanliness),
                func.avg(Rating.value),
            )
            .where(
                Rating.organization_id.in_(organization_ids),
                Rating.included.is_(True),
            )
            .group_by(Rating.organization_id)
        ).all()
        if organization_ids
        else []
    )
    verified_metrics = {
        row[0]: {
            "overall": round(float(row[1]) * 10, 1),
            "quality": round(float(row[2]) * 10, 1),
            "service": round(float(row[3]) * 10, 1),
            "cleanliness": round(float(row[4]) * 10, 1),
            "value": round(float(row[5]) * 10, 1),
        }
        for row in metric_rows
        if all(value is not None for value in row[1:])
    }
    items = []
    for branch, organization in rows:
        distance = haversine_km(
            latitude,
            longitude,
            branch.latitude,
            branch.longitude,
        )
        if distance > radius_km:
            continue
        item = {
                "organization_id": organization.id,
                "branch_id": branch.id,
                "organization": organization.name,
                "category": organization.category,
                "description": organization.description,
                "profile_status": organization.profile_status,
                "verified_partner": organization.profile_status == "VERIFIED_PARTNER",
                "branch": branch.name,
                "address": branch.address or branch.name,
                "city": branch.city or organization.city,
                "country_code": branch.country_code,
                "latitude": branch.latitude,
                "longitude": branch.longitude,
                "distance_km": round(distance, 2),
                "relyqo_score": round(organization.score, 1),
                "verified_rating_count": organization.rating_count,
                "verified_metrics": verified_metrics.get(organization.id),
                "rating_requires_verified_visit": True,
            }
        item.update(
            community_stats.get(
                f"relyqo:{branch.id}",
                {"community_score": 0.0, "community_rating_count": 0},
            )
        )
        items.append(item)
    items.sort(key=lambda item: item["distance_km"])
    return {
        "items": items[:limit],
        "radius_km": radius_km,
        "location_stored": False,
        "rating_policy": "QR_VERIFIED_VISIT_ONLY",
    }


def manual_place_item(
    place: ManualPlace,
    distance_km: float | None = None,
    community_stats: dict | None = None,
) -> dict:
    item = {
        "id": place.id,
        "object_key": f"manual:{place.id}",
        "name": place.name,
        "category": place.category,
        "description": place.description,
        "address": place.address,
        "city": normalize_city_name(place.city),
        "country_code": place.country_code,
        "latitude": place.latitude,
        "longitude": place.longitude,
        "google_place_id": place.google_place_id,
        "distance_km": round(distance_km, 2) if distance_km is not None else None,
        "source": "MANUAL",
        "verified": False,
    }
    item.update(
        community_stats
        or {"community_score": 0.0, "community_rating_count": 0}
    )
    return item


@app.post("/v1/public/manual-places")
def create_manual_place(
    body: ManualPlaceCreate,
    request: Request,
    response: Response,
    rater_cookie: str | None = Cookie(default=None, alias=COMMUNITY_COOKIE),
    db: Session = Depends(get_db),
):
    name = " ".join(body.name.split())
    address = " ".join(body.address.split())
    city = normalize_city_name(body.city)
    description = " ".join(body.description.split())
    country_code = body.country_code.strip().upper()
    google_place_id = (
        body.google_place_id.strip() if body.google_place_id else None
    )
    if len(name) < 2 or len(address) < 3 or len(city) < 2 or len(description) < 10:
        raise HTTPException(422, "Заполните название, описание, адрес и город")
    raw_rater = verified_community_rater(rater_cookie)
    cookie_value = rater_cookie
    if raw_rater is None:
        raw_rater, cookie_value = new_community_rater()
    identity = "|".join(
        (
            name.casefold(),
            address.casefold(),
            city.casefold(),
            country_code,
            f"{body.latitude:.4f}",
            f"{body.longitude:.4f}",
        )
    )
    identity_hash = token_hash(identity)
    existing = None
    if google_place_id:
        existing = db.scalar(
            select(ManualPlace).where(
                ManualPlace.google_place_id == google_place_id,
                ManualPlace.active.is_(True),
            )
        )
    if existing is None:
        existing = db.scalar(
            select(ManualPlace).where(
                ManualPlace.identity_hash == identity_hash,
                ManualPlace.active.is_(True),
            )
        )
    if existing:
        if google_place_id and existing.google_place_id is None:
            existing.google_place_id = google_place_id
            reference = db.get(GooglePlaceReference, google_place_id)
            if reference:
                reference.last_seen_at = datetime.utcnow()
            else:
                db.add(GooglePlaceReference(place_id=google_place_id))
            db.commit()
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.set_cookie(
            COMMUNITY_COOKIE,
            cookie_value,
            max_age=365 * 24 * 3600,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="strict",
            path="/",
        )
        return {
            "status": "COMMUNITY_PLACE_EXISTS",
            "item": manual_place_item(existing),
        }
    place = ManualPlace(
        identity_hash=identity_hash,
        name=name,
        category=body.category,
        description=description,
        address=address,
        city=city,
        country_code=country_code,
        latitude=body.latitude,
        longitude=body.longitude,
        google_place_id=google_place_id,
        created_by_hash=token_hash(raw_rater),
    )
    db.add(place)
    if google_place_id:
        reference = db.get(GooglePlaceReference, google_place_id)
        if reference:
            reference.last_seen_at = datetime.utcnow()
        else:
            db.add(GooglePlaceReference(place_id=google_place_id))
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Это место уже добавлено")
    db.add(
        AuditLog(
            actor_type="COMMUNITY",
            action="MANUAL_PLACE_CREATED",
            entity_type="MANUAL_PLACE",
            entity_id=place.id,
        )
    )
    db.commit()
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.set_cookie(
        COMMUNITY_COOKIE,
        cookie_value,
        max_age=365 * 24 * 3600,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        path="/",
    )
    return {"status": "COMMUNITY_PLACE_CREATED", "item": manual_place_item(place)}


@app.post("/v1/public/manual-places/nearby")
def public_manual_places_nearby(
    search: NearbySearch,
    response: Response,
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store, max-age=0"
    lat_delta = search.radius_km / 110.574
    longitude_scale = max(
        0.01, 111.320 * math.cos(math.radians(search.latitude))
    )
    lng_delta = search.radius_km / longitude_scale
    rows = db.scalars(
        select(ManualPlace)
        .where(
            ManualPlace.active.is_(True),
            ManualPlace.latitude.between(
                search.latitude - lat_delta, search.latitude + lat_delta
            ),
            ManualPlace.longitude.between(
                search.longitude - lng_delta, search.longitude + lng_delta
            ),
        )
        .limit(search.limit * 3)
    ).all()
    community_keys = [f"manual:{place.id}" for place in rows]
    community_rows = (
        db.execute(
            select(
                CommunityRating.object_key,
                func.avg(CommunityRating.community_score),
                func.count(CommunityRating.id),
            )
            .where(CommunityRating.object_key.in_(community_keys))
            .group_by(CommunityRating.object_key)
        ).all()
        if community_keys
        else []
    )
    community_stats = {
        row[0]: {
            "community_score": round(float(row[1]), 1),
            "community_rating_count": int(row[2]),
        }
        for row in community_rows
    }
    items = []
    for place in rows:
        distance = haversine_km(
            search.latitude,
            search.longitude,
            place.latitude,
            place.longitude,
        )
        if distance <= search.radius_km:
            items.append(
                manual_place_item(
                    place,
                    distance,
                    community_stats.get(f"manual:{place.id}"),
                )
            )
    items.sort(key=lambda item: item["distance_km"])
    return {
        "items": items[: search.limit],
        "radius_km": search.radius_km,
        "location_stored": False,
        "place_coordinates_user_submitted": True,
    }


@app.get("/v1/public/rated-organizations")
def public_rated_organizations(
    response: Response,
    offset: int = 0,
    limit: int = 50,
    q: str = "",
    country_code: str = "",
    city: str = "",
    category: str = "ALL",
    score_type: str = "ALL",
    min_score: float = 0,
    sort: str = "rating",
    db: Session = Depends(get_db),
):
    if offset < 0:
        raise HTTPException(422, "Смещение не может быть отрицательным")
    if not 1 <= limit <= 100:
        raise HTTPException(422, "Количество должно быть от 1 до 100")
    if len(q) > 120:
        raise HTTPException(422, "Поисковый запрос слишком длинный")
    if category not in {"ALL", *SERVICE_CATEGORY_GROUPS}:
        raise HTTPException(422, "Неизвестная сфера услуг")
    if score_type not in {"ALL", "VERIFIED", "COMMUNITY"}:
        raise HTTPException(422, "Неизвестный тип оценки")
    if not 0 <= min_score <= 100:
        raise HTTPException(422, "Минимальный рейтинг должен быть от 0 до 100")
    if sort not in {"rating", "reviews", "name"}:
        raise HTTPException(422, "Неизвестная сортировка")
    community_rows = db.execute(
        select(
            CommunityRating.object_key,
            func.avg(CommunityRating.community_score),
            func.count(CommunityRating.id),
        ).group_by(CommunityRating.object_key)
    ).all()
    community_stats = {
        row[0]: {
            "community_score": round(float(row[1]), 1),
            "community_rating_count": int(row[2]),
        }
        for row in community_rows
    }
    items = []
    seen_organizations = set()
    partner_rows = db.execute(
        select(Organization, Branch)
        .join(Branch, Branch.organization_id == Organization.id)
        .where(
            Branch.active.is_(True),
            Organization.profile_status.in_({"PUBLISHED", "VERIFIED_PARTNER"}),
        )
        .order_by(Organization.name, Branch.name)
    ).all()
    for organization, branch in partner_rows:
        object_key = f"relyqo:{branch.id}"
        community = community_stats.get(
            object_key,
            {"community_score": 0.0, "community_rating_count": 0},
        )
        if organization.rating_count <= 0 and community["community_rating_count"] <= 0:
            continue
        if organization.id in seen_organizations:
            continue
        seen_organizations.add(organization.id)
        verified_count = int(organization.rating_count)
        items.append(
            {
                "kind": "partner",
                "object_key": object_key,
                "organization_id": organization.id,
                "branch_id": branch.id,
                "organization": organization.name,
                "name": organization.name,
                "category": organization.category,
                "description": organization.description,
                "profile_status": organization.profile_status,
                "verified_partner": organization.profile_status
                == "VERIFIED_PARTNER",
                "address": branch.address or branch.name,
                "city": normalize_city_name(branch.city or organization.city),
                "country_code": (branch.country_code or "").upper(),
                "latitude": branch.latitude,
                "longitude": branch.longitude,
                "relyqo_score": round(organization.score, 1),
                "verified_rating_count": verified_count,
                **community,
                "score_type": "VERIFIED" if verified_count else "COMMUNITY",
                "display_score": round(organization.score, 1)
                if verified_count
                else community["community_score"],
            }
        )
    manual_ids = [
        object_key.removeprefix("manual:")
        for object_key in community_stats
        if object_key.startswith("manual:")
    ]
    manual_places = (
        db.scalars(
            select(ManualPlace).where(
                ManualPlace.id.in_(manual_ids),
                ManualPlace.active.is_(True),
            )
        ).all()
        if manual_ids
        else []
    )
    for place in manual_places:
        community = community_stats[f"manual:{place.id}"]
        items.append(
            {
                "kind": "manual",
                **manual_place_item(place, community_stats=community),
                "verified_rating_count": 0,
                "score_type": "COMMUNITY",
                "display_score": community["community_score"],
            }
        )
    facets = {
        "countries": sorted(
            {item["country_code"] for item in items if item.get("country_code")}
        ),
        "cities": sorted(
            [
                {"city": city_name, "country_code": country}
                for city_name, country in {
                    (item.get("city") or "", item.get("country_code") or "")
                    for item in items
                    if item.get("city")
                }
            ],
            key=lambda value: (value["country_code"], value["city"].casefold()),
        ),
    }
    query = q.strip().casefold()
    selected_country = country_code.strip().upper()
    selected_city = normalize_city_name(city).casefold()

    def selected_score(item: dict) -> float:
        if score_type == "VERIFIED":
            return float(item["relyqo_score"])
        if score_type == "COMMUNITY":
            return float(item["community_score"])
        return float(item["display_score"])

    def selected_reviews(item: dict) -> int:
        if score_type == "VERIFIED":
            return int(item["verified_rating_count"])
        if score_type == "COMMUNITY":
            return int(item["community_rating_count"])
        return int(item["verified_rating_count"] + item["community_rating_count"])

    def matches(item: dict) -> bool:
        if selected_country and item.get("country_code") != selected_country:
            return False
        if selected_city and (item.get("city") or "").casefold() != selected_city:
            return False
        if category != "ALL" and service_category_group(item.get("category")) != category:
            return False
        if score_type == "VERIFIED" and item["verified_rating_count"] <= 0:
            return False
        if score_type == "COMMUNITY" and item["community_rating_count"] <= 0:
            return False
        if selected_score(item) < min_score:
            return False
        if query:
            searchable = " ".join(
                str(item.get(field) or "")
                for field in ("name", "address", "city", "country_code", "category", "description")
            ).casefold()
            if query not in searchable:
                return False
        return True

    filtered_items = [item for item in items if matches(item)]
    top_candidates = [
        item
        for item in filtered_items
        if selected_reviews(item) >= TOP_ORGANIZATION_MIN_RATINGS
    ]
    top_candidates.sort(
        key=lambda item: (
            -selected_score(item),
            -selected_reviews(item),
            item["name"].casefold(),
        )
    )
    for top_rank, item in enumerate(
        top_candidates[:TOP_ORGANIZATION_LIMIT],
        start=1,
    ):
        item["top_rank"] = top_rank
        item["top_score_type"] = (
            score_type
            if score_type != "ALL"
            else "VERIFIED"
            if item["verified_rating_count"] > 0
            else "COMMUNITY"
        )
    if sort == "name":
        filtered_items.sort(key=lambda item: item["name"].casefold())
    elif sort == "reviews":
        filtered_items.sort(
            key=lambda item: (
                -selected_reviews(item),
                -selected_score(item),
                item["name"].casefold(),
            )
        )
    else:
        filtered_items.sort(
            key=lambda item: (
                -selected_score(item),
                -int(item["verified_rating_count"]),
                -int(item["community_rating_count"]),
                item["name"].casefold(),
            )
        )
    total = len(filtered_items)
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return {
        "items": filtered_items[offset : offset + limit],
        "offset": offset,
        "limit": limit,
        "total": total,
        "has_more": offset + limit < total,
        "facets": facets,
        "score_policy": "VERIFIED_AND_COMMUNITY_SEPARATE",
        "top_policy": {
            "calculation": "deterministic_score_then_rating_count_v1",
            "limit": TOP_ORGANIZATION_LIMIT,
            "minimum_ratings": TOP_ORGANIZATION_MIN_RATINGS,
            "paid_placement": False,
            "business_can_edit": False,
        },
        "external_ratings_used": False,
    }


def community_summary(object_key: str, db: Session) -> dict:
    score, count, overall, quality, service, cleanliness, value = db.execute(
        select(
            func.avg(CommunityRating.community_score),
            func.count(CommunityRating.id),
            func.avg(CommunityRating.overall),
            func.avg(CommunityRating.quality),
            func.avg(CommunityRating.service),
            func.avg(CommunityRating.cleanliness),
            func.avg(CommunityRating.value),
        ).where(CommunityRating.object_key == object_key)
    ).one()
    aggregated = (
        select(
            CommunityRating.object_key.label("object_key"),
            func.avg(CommunityRating.community_score).label("score"),
            func.count(CommunityRating.id).label("rating_count"),
        )
        .group_by(CommunityRating.object_key)
        .subquery()
    )
    ranked = select(
        aggregated.c.object_key,
        func.row_number()
        .over(
            order_by=(
                aggregated.c.score.desc(),
                aggregated.c.rating_count.desc(),
                aggregated.c.object_key.asc(),
            )
        )
        .label("position"),
    ).subquery()
    position = db.scalar(
        select(ranked.c.position).where(ranked.c.object_key == object_key)
    )
    rated_objects = db.scalar(select(func.count()).select_from(aggregated)) or 0
    return {
        "object_key": object_key,
        "community_score": round(float(score), 1) if score is not None else 0.0,
        "rating_count": int(count),
        "community_global_position": int(position) if position is not None else None,
        "community_rated_objects": int(rated_objects),
        "metrics": {
            "overall": round(float(overall) * 10, 1) if overall is not None else 0.0,
            "quality": round(float(quality) * 10, 1) if quality is not None else 0.0,
            "service": round(float(service) * 10, 1) if service is not None else 0.0,
            "cleanliness": round(float(cleanliness) * 10, 1)
            if cleanliness is not None
            else 0.0,
            "value": round(float(value) * 10, 1) if value is not None else 0.0,
        },
        "verified_relyqo_score": None,
        "included_in_relyqo_score": False,
    }


@app.get("/v1/community-ratings/summary")
def get_community_summary(
    object_key: str,
    response: Response,
    db: Session = Depends(get_db),
):
    if not 8 <= len(object_key) <= 320:
        raise HTTPException(422, "Некорректный идентификатор объекта")
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return community_summary(object_key, db)


@app.post("/v1/community-ratings")
def create_community_rating(
    body: CommunityRatingCreate,
    request: Request,
    response: Response,
    rater_cookie: str | None = Cookie(default=None, alias=COMMUNITY_COOKIE),
    relyqo_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    consumer = session_user(relyqo_session, db, CONSUMER_ROLE)
    validate_public_object(body.object_key, body.source)
    normalized_photo = normalize_rating_photo(body.photo_data_url)
    raw_rater = verified_community_rater(rater_cookie)
    cookie_value = rater_cookie
    if raw_rater is None:
        raw_rater, cookie_value = new_community_rater()
    rater_hash = token_hash(raw_rater)
    score = calculate_ces(
        body.overall,
        body.quality,
        body.service,
        body.cleanliness,
        body.value,
    )
    rating = CommunityRating(
        **body.model_dump(exclude={"photo_data_url"}),
        rater_hash=rater_hash,
        consumer_user_id=consumer.id,
        community_score=score,
    )
    db.add(rating)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Вы уже оценили этот объект")
    photo = None
    if normalized_photo:
        photo = RatingPhoto(
            community_rating_id=rating.id,
            object_key=body.object_key,
            content_type=normalized_photo[2],
            image_data=normalized_photo[0],
        )
        db.add(photo)
    db.add(
        AuditLog(
            actor_type="COMMUNITY",
            action="COMMUNITY_RATING_CREATED",
            entity_type="COMMUNITY_RATING",
            entity_id=rating.id,
        )
    )
    db.commit()
    photo_analysis = None
    if photo and normalized_photo:
        photo_analysis = analyze_rating_photo(
            photo,
            normalized_photo[1],
            {
                "source": body.source,
                "consumer_scores": {
                    "overall": body.overall,
                    "quality": body.quality,
                    "service": body.service,
                    "cleanliness": body.cleanliness,
                    "value": body.value,
                },
                "policy": "AI describes visible evidence only and never changes scores",
            },
            db,
        )
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.set_cookie(
        COMMUNITY_COOKIE,
        cookie_value,
        max_age=365 * 24 * 3600,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        path="/",
    )
    return {
        "rating_id": rating.id,
        "status": "COMMUNITY_PUBLISHED",
        "photo_attached": photo is not None,
        "photo_analysis": photo_analysis,
        **community_summary(body.object_key, db),
    }


@app.post("/v1/public/advisor")
def public_advisor(
    body: PublicAdvisorRequest,
    request: Request,
    response: Response,
    rater_cookie: str | None = Cookie(default=None, alias=COMMUNITY_COOKIE),
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store, max-age=0"
    priority, sections = public_advisor_items(body, db)
    if not sections:
        raise HTTPException(
            404,
            "Пока нет организаций с оценками RELYQO для такого выбора",
        )
    raw_rater = verified_community_rater(rater_cookie)
    cookie_value = rater_cookie
    if raw_rater is None:
        raw_rater, cookie_value = new_community_rater()
        response.set_cookie(
            COMMUNITY_COOKIE,
            cookie_value,
            max_age=365 * 24 * 3600,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="strict",
            path="/",
        )
    ai_context = {
        "question": body.question.strip(),
        "priority": priority,
        "recommendations": [
            {
                "score_type": section["score_type"],
                "items": [
                    {
                        "position": item["position"],
                        "name": item["name"],
                        "score": item["score"],
                        "selected_metric_score": item["metric_score"],
                        "rating_count": item["rating_count"],
                        "confidence": item["confidence_label"],
                        "distance_km": item["distance_km"],
                    }
                    for item in section["items"]
                ],
            }
            for section in sections
        ],
        "policy": {
            "consumer_is_only_rating_author": True,
            "ai_cannot_change_score": True,
            "verified_and_community_are_separate": True,
            "external_ratings_used": False,
        },
    }
    signature = token_hash(json.dumps(ai_context, ensure_ascii=False, sort_keys=True))
    now = datetime.utcnow()
    with _ai_lock:
        cached = _public_ai_cache.get(signature)
        if cached and cached["expires_at"] > now:
            return {**cached["response"], "cached": True}
        rater_key = token_hash(raw_rater)
        last_request = _public_ai_last_request.get(rater_key)
        if last_request:
            seconds_left = PUBLIC_AI_COOLDOWN_SECONDS - int(
                (now - last_request).total_seconds()
            )
            if seconds_left > 0:
                raise HTTPException(
                    429,
                    f"Новый совет будет доступен через {seconds_left} сек.",
                )
        _public_ai_last_request[rater_key] = now
    ai_generated = False
    answer = public_advisor_fallback(priority["label"], sections)
    if settings.openai_api_key:
        try:
            answer = generate_public_advice(ai_context)
            ai_generated = True
        except (AIUnavailableError, AIServiceError):
            pass
    result = {
        "answer": answer,
        "ai_generated": ai_generated,
        "priority": priority,
        "sections": sections,
        "generated_at": now.isoformat() + "Z",
        "cached": False,
        "read_only": True,
        "consumer_is_only_rating_author": True,
        "score_changed": False,
        "disclaimer": (
            "ИИ объясняет реальные оценки RELYQO, но не выставляет и не меняет их. "
            "Verified и Community не смешиваются."
        ),
    }
    with _ai_lock:
        if len(_public_ai_cache) >= 200:
            _public_ai_cache.clear()
        _public_ai_cache[signature] = {
            "expires_at": now + timedelta(minutes=AI_CACHE_MINUTES),
            "response": result,
        }
    return result


@app.get("/v1/public/rankings")
def public_rankings(
    response: Response,
    scope: str = "world",
    country_code: str | None = None,
    city: str | None = None,
    category: str | None = None,
    db: Session = Depends(get_db),
):
    if scope not in {"world", "country", "city"}:
        raise HTTPException(422, "Scope должен быть world, country или city")
    normalized_country = country_code.strip().upper() if country_code else None
    normalized_city = city.strip() if city else None
    normalized_category = category.strip().upper() if category else None
    if normalized_country and len(normalized_country) != 2:
        raise HTTPException(422, "Код страны должен содержать две буквы")
    if scope == "country" and not normalized_country:
        raise HTTPException(422, "Для рейтинга страны укажите country_code")
    if scope == "city" and not normalized_city:
        raise HTTPException(422, "Для рейтинга города укажите city")
    if normalized_category and normalized_category not in SERVICE_CATEGORIES:
        raise HTTPException(422, "Неизвестная сфера услуг")
    rows = db.execute(
        select(Organization, Branch)
        .join(Branch, Branch.organization_id == Organization.id)
        .where(
            Branch.active.is_(True),
            Organization.profile_status == "VERIFIED_PARTNER",
        )
        .order_by(Organization.name, Branch.name)
    ).all()
    organizations: dict[str, dict] = {}
    for organization, branch in rows:
        branch_country = (branch.country_code or "").upper() or None
        branch_city = branch.city or organization.city
        if normalized_category and organization.category != normalized_category:
            continue
        if normalized_country and branch_country != normalized_country:
            continue
        if normalized_city and (branch_city or "").casefold() != normalized_city.casefold():
            continue
        if organization.id in organizations:
            continue
        organizations[organization.id] = {
            "organization_id": organization.id,
            "branch_id": branch.id,
            "name": organization.name,
            "category": organization.category,
            "branch": branch.name,
            "address": branch.address or branch.name,
            "city": branch_city,
            "country_code": branch_country,
            "verified_score": round(organization.score, 1),
            "verified_rating_count": organization.rating_count,
            "eligible": organization.rating_count >= 20,
            "position": None,
        }
    items = list(organizations.values())
    eligible = sorted(
        (item for item in items if item["eligible"]),
        key=lambda item: (
            -item["verified_score"],
            -item["verified_rating_count"],
            item["name"].casefold(),
        ),
    )
    for position, item in enumerate(eligible, start=1):
        item["position"] = position
    provisional = sorted(
        (item for item in items if not item["eligible"]),
        key=lambda item: (
            -item["verified_rating_count"],
            -item["verified_score"],
            item["name"].casefold(),
        ),
    )
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return {
        "scope": scope,
        "country_code": normalized_country,
        "city": normalized_city,
        "category": normalized_category,
        "minimum_verified_ratings": 20,
        "ranked_count": len(eligible),
        "provisional_count": len(provisional),
        "items": eligible + provisional,
        "calculation": "deterministic_verified_score_rank_v1",
    }


@app.get("/v1/public/ranking-locations")
def public_ranking_locations(
    response: Response,
    category: str | None = None,
    db: Session = Depends(get_db),
):
    normalized_category = category.strip().upper() if category else None
    if normalized_category and normalized_category not in SERVICE_CATEGORIES:
        raise HTTPException(422, "Неизвестная сфера услуг")
    rows = db.execute(
        select(Organization, Branch)
        .join(Branch, Branch.organization_id == Organization.id)
        .where(
            Branch.active.is_(True),
            Organization.profile_status == "VERIFIED_PARTNER",
        )
    ).all()
    locations: dict[str, dict] = {}
    for organization, branch in rows:
        if normalized_category and organization.category != normalized_category:
            continue
        country_code = (branch.country_code or "").strip().upper()
        city = (branch.city or organization.city or "").strip()
        if len(country_code) != 2 or not city:
            continue
        country = locations.setdefault(
            country_code,
            {"organization_ids": set(), "cities": {}},
        )
        country["organization_ids"].add(organization.id)
        city_ids = country["cities"].setdefault(city, set())
        city_ids.add(organization.id)
    countries = []
    for country_code, data in sorted(locations.items()):
        cities = [
            {"name": city, "organization_count": len(organization_ids)}
            for city, organization_ids in sorted(
                data["cities"].items(), key=lambda item: item[0].casefold()
            )
        ]
        countries.append(
            {
                "country_code": country_code,
                "organization_count": len(data["organization_ids"]),
                "city_count": len(cities),
                "cities": cities,
            }
        )
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return {
        "category": normalized_category,
        "country_count": len(countries),
        "city_count": sum(item["city_count"] for item in countries),
        "countries": countries,
    }


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
        "organization": {"id": org.id, "name": org.name, "category": org.category},
        "branch": {"id": branch.id, "name": branch.name},
        "verification_score": visit.verification_score,
    }


@app.post("/v1/ratings")
def rate(
    body: RatingCreate,
    relyqo_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    normalized_photo = normalize_rating_photo(body.photo_data_url)
    consumer = None
    if relyqo_session:
        signed_in_user = session_user(relyqo_session, db)
        if signed_in_user.role != CONSUMER_ROLE:
            raise HTTPException(
                403,
                "Оценку может отправить только потребитель RELYQO",
            )
        consumer = signed_in_user
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
        **body.model_dump(exclude={"photo_data_url"}),
        organization_id=org.id,
        consumer_user_id=consumer.id if consumer else None,
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
    photo = None
    if normalized_photo:
        photo = RatingPhoto(
            rating_id=rating.id,
            content_type=normalized_photo[2],
            image_data=normalized_photo[0],
        )
        db.add(photo)
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
    photo_analysis = None
    if photo and normalized_photo:
        photo_analysis = analyze_rating_photo(
            photo,
            normalized_photo[1],
            {
                "organization_category": org.category,
                "consumer_scores": {
                    "overall": body.overall,
                    "quality": body.food,
                    "service": body.service,
                    "cleanliness": body.cleanliness,
                    "value": body.value,
                },
                "verified_visit": True,
                "policy": "AI describes visible evidence only and never changes scores",
            },
            db,
        )
    return {
        "rating_id": rating.id,
        "status": rating.status,
        "ces_score": ces,
        "included_in_rating": rating.included,
        "relyqo_score": org.score,
        "rating_count": org.rating_count,
        "saved_to_consumer_history": consumer is not None,
        "photo_attached": photo is not None,
        "photo_analysis": photo_analysis,
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
        photo = db.scalar(
            select(RatingPhoto).where(RatingPhoto.rating_id == rating.id)
        )
        result.append(
            {
                "review_id": review.id,
                "rating_id": rating.id,
                "organization": org.name if org else "Неизвестная организация",
                "reason": review.reason,
                "status": review.status,
                "created_at": rating.created_at,
                "photo": (
                    {
                        "id": photo.id,
                        "analysis_status": photo.analysis_status,
                        "ai_analysis": photo.ai_analysis,
                    }
                    if photo
                    else None
                ),
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


@app.get("/v1/review/rating-photos/{photo_id}", include_in_schema=False)
def review_rating_photo(
    photo_id: str,
    relyqo_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    session_user(relyqo_session, db, REVIEWER_ROLE)
    photo = db.get(RatingPhoto, photo_id)
    if not photo:
        raise HTTPException(404, "Фото оценки не найдено")
    return Response(
        content=photo.image_data,
        media_type=photo.content_type,
        headers={"Cache-Control": "private, no-store, max-age=0"},
    )


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
