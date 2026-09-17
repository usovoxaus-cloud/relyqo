"""Private feedback details, explainable risk signals and administrator review."""

from datetime import datetime, timedelta
import hashlib
import hmac
import json
from pathlib import Path
from typing import Literal

from fastapi import Cookie, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, distinct, func, select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import (
    AuditLog,
    Branch,
    CommunityRating,
    FeedbackSignal,
    ManualPlace,
    ModerationCase,
    Organization,
    OwnerReview,
    Rating,
    RatingPhoto,
    User,
)
from .password_recovery import limited

REASONS = {
    "FAST_SERVICE": ("Быстрое обслуживание", "Tez xizmat"),
    "FRIENDLY_STAFF": ("Вежливый персонал", "Xushmuomala xodimlar"),
    "GOOD_QUALITY": ("Хорошее качество", "Yaxshi sifat"),
    "CLEAN_PLACE": ("Чистота и порядок", "Tozalik va tartib"),
    "FAIR_PRICE": ("Понятная и справедливая цена", "Tushunarli va adolatli narx"),
    "LONG_WAIT": ("Долго ждал", "Uzoq kutdim"),
    "RUDE_SERVICE": ("Грубое обслуживание", "Qo‘pol muomala"),
    "POOR_QUALITY": ("Проблема с качеством", "Sifat bilan muammo"),
    "UNCLEAN": ("Недостаточно чисто", "Tozalik yetarli emas"),
    "UNCLEAR_PRICE": ("Непрозрачная цена", "Narx aniq emas"),
    "NOT_AS_DESCRIBED": ("Не соответствует описанию", "Tavsifga mos emas"),
    "OTHER": ("Другая причина", "Boshqa sabab"),
}
SIGNALS = {
    "DUPLICATE_PHOTO": "Одинаковое изображение уже прикреплено к другой оценке.",
    "RATING_BURST": "Не менее 8 оценок одного объекта за 10 минут.",
    "SHARED_BROWSER": "Не менее 3 аккаунтов оценивают один объект из одного браузера за сутки.",
    "RAPID_ACCOUNT": "Один аккаунт отправил не менее 10 оценок за час.",
}


def feedback_payload(rating):
    return {
        "comment": rating.comment,
        "reasons": json.loads(rating.reasons_json or "[]"),
        "status": rating.status,
        "included": rating.included,
    }


def photo_digest(raw):
    # Decode when possible so metadata/re-encoding of identical pixels does not evade exact matching.
    from io import BytesIO
    from PIL import Image, ImageOps

    try:
        with Image.open(BytesIO(raw)) as im:
            if im.width * im.height > 25_000_000:
                return hashlib.sha256(raw).hexdigest()
            im = ImageOps.exif_transpose(im).convert("RGB")
            return hashlib.sha256(
                f"{im.width}x{im.height}:".encode() + im.tobytes()
            ).hexdigest()
    except Exception:
        return hashlib.sha256(raw).hexdigest()


def record_signals(db, rating, rating_type, object_key, raw_device=None, photo=None):
    """Signals never change a score or establish that an account committed fraud."""
    now = datetime.utcnow()
    device = (
        hmac.new(
            settings.qr_secret.encode(), ("feedback:" + raw_device).encode(), "sha256"
        ).hexdigest()
        if raw_device
        else None
    )
    event = FeedbackSignal(
        rating_id=rating.id,
        rating_type=rating_type,
        object_key=object_key,
        user_id=rating.consumer_user_id,
        device_hash=device,
    )
    db.add(event)
    db.flush()
    signals = []
    if photo and photo.content_hash:
        duplicate = db.scalar(
            select(RatingPhoto.id)
            .where(
                RatingPhoto.content_hash == photo.content_hash,
                RatingPhoto.id != photo.id,
            )
            .limit(1)
        )
        if duplicate:
            signals.append("DUPLICATE_PHOTO")
    if (
        db.scalar(
            select(func.count())
            .select_from(FeedbackSignal)
            .where(
                FeedbackSignal.object_key == object_key,
                FeedbackSignal.created_at >= now - timedelta(minutes=10),
            )
        )
        >= 8
    ):
        signals.append("RATING_BURST")
    if (
        device
        and db.scalar(
            select(func.count(distinct(FeedbackSignal.user_id))).where(
                FeedbackSignal.device_hash == device,
                FeedbackSignal.object_key == object_key,
                FeedbackSignal.created_at >= now - timedelta(days=1),
            )
        )
        >= 3
    ):
        signals.append("SHARED_BROWSER")
    if (
        rating.consumer_user_id
        and db.scalar(
            select(func.count())
            .select_from(FeedbackSignal)
            .where(
                FeedbackSignal.user_id == rating.consumer_user_id,
                FeedbackSignal.created_at >= now - timedelta(hours=1),
            )
        )
        >= 10
    ):
        signals.append("RAPID_ACCOUNT")
    if signals:
        db.add(
            ModerationCase(
                case_key="signal:" + rating.id,
                kind="SIGNAL",
                object_key=object_key,
                rating_id=rating.id,
                rating_type=rating_type,
                details=json.dumps({"signals": signals}, ensure_ascii=False),
            )
        )
        db.add(
            AuditLog(
                actor_type="TRUST_RULES",
                action="FEEDBACK_FLAGGED",
                entity_type=rating_type,
                entity_id=rating.id,
            )
        )
    # No raw IP, fingerprinting or cross-site tracking. Correlation events expire after 30 days.
    db.execute(
        delete(FeedbackSignal).where(
            FeedbackSignal.created_at < now - timedelta(days=30)
        )
    )
    return signals


def object_name(db, key):
    prefix, _, identifier = key.partition(":")
    if prefix == "org":
        obj = db.get(Organization, identifier)
    elif prefix == "relyqo":
        branch = db.get(Branch, identifier)
        obj = db.get(Organization, branch.organization_id) if branch else None
    elif prefix == "manual":
        obj = db.get(ManualPlace, identifier)
    else:
        obj = None
    return obj.name if obj else key


class ComplaintRequest(BaseModel):
    object_key: str = Field(min_length=8, max_length=320)
    message: str = Field(min_length=10, max_length=1200)
    rating_id: str | None = Field(default=None, max_length=36)


class CaseDecision(BaseModel):
    decision: Literal["APPROVE", "REJECT", "DISMISS"]
    note: str = Field(min_length=10, max_length=1200)


def register_feedback_routes(app, session_user, recalculate):
    @app.get("/v1/public/feedback-reasons")
    def reason_catalog():
        return {
            "items": [
                {"code": code, "label": labels[0], "label_uz": labels[1]}
                for code, labels in REASONS.items()
            ]
        }

    @app.get("/admin/control", include_in_schema=False)
    def control_page():
        return FileResponse(
            Path(__file__).parent / "static" / "admin-control.html",
            headers={
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'",
            },
        )

    @app.post("/v1/consumer/complaints", status_code=201)
    def complaint(
        body: ComplaintRequest,
        response: Response,
        relyqo_session: str | None = Cookie(default=None),
        db: Session = Depends(get_db),
    ):
        user = session_user(relyqo_session, db, "CONSUMER")
        if len(body.message.strip()) < 10:
            raise HTTPException(422, "Опишите ситуацию подробнее")
        if limited(db, "complaint-user", user.id, 3):
            raise HTTPException(429, "Слишком много обращений. Попробуйте через час.")
        prefix, _, identifier = body.object_key.partition(":")
        model = {"relyqo": Branch, "manual": ManualPlace}.get(prefix)
        if model is None or not db.get(model, identifier):
            raise HTTPException(404, "Организация не найдена")
        kind, rating_type, rating_id = "COMPLAINT", None, None
        if body.rating_id:
            rating = db.scalar(
                select(Rating).where(Rating.id == body.rating_id).with_for_update()
            )
            rating_type = "VERIFIED"
            if not rating:
                rating = db.scalar(
                    select(CommunityRating)
                    .where(CommunityRating.id == body.rating_id)
                    .with_for_update()
                )
                rating_type = "COMMUNITY"
            if not rating or rating.consumer_user_id != user.id:
                raise HTTPException(404, "Оценка не найдена")
            if rating_type == "VERIFIED":
                from .models import Visit

                visit = db.get(Visit, rating.visit_id)
                expected_key = "relyqo:" + visit.branch_id
            else:
                expected_key = rating.object_key
            if body.object_key != expected_key or rating.included:
                raise HTTPException(
                    422, "Апелляция доступна для своей исключённой оценки"
                )
            kind, rating_id = "APPEAL", rating.id
            if db.scalar(
                select(ModerationCase.id).where(
                    ModerationCase.rating_id == rating.id,
                    ModerationCase.kind == "APPEAL",
                    ModerationCase.status == "PENDING",
                )
            ):
                raise HTTPException(409, "Апелляция уже ожидает проверки")
        import uuid

        case = ModerationCase(
            case_key=str(uuid.uuid4()),
            kind=kind,
            object_key=body.object_key,
            reporter_id=user.id,
            rating_id=rating_id,
            rating_type=rating_type,
            details=body.message.strip(),
        )
        db.add(case)
        db.flush()
        db.add(
            AuditLog(
                actor_type=user.role,
                action="COMPLAINT_CREATED",
                entity_type="MODERATION_CASE",
                entity_id=case.id,
            )
        )
        db.commit()
        response.headers["Cache-Control"] = "no-store"
        return {
            "id": case.id,
            "status": case.status,
            "message": "Обращение принято. Ответ появится в вашем кабинете.",
        }

    @app.get("/v1/consumer/complaints")
    def own_complaints(
        response: Response,
        relyqo_session: str | None = Cookie(default=None),
        db: Session = Depends(get_db),
    ):
        user = session_user(relyqo_session, db, "CONSUMER")
        rows = db.scalars(
            select(ModerationCase)
            .where(ModerationCase.reporter_id == user.id)
            .order_by(ModerationCase.created_at.desc())
            .limit(100)
        ).all()
        response.headers["Cache-Control"] = "no-store"
        return {
            "items": [
                {
                    "id": r.id,
                    "kind": r.kind,
                    "organization": object_name(db, r.object_key),
                    "message": r.details,
                    "status": r.status,
                    "answer": r.decision_note,
                    "created_at": r.created_at,
                }
                for r in rows
            ]
        }

    @app.get("/v1/admin/control/cases")
    def cases(
        response: Response,
        status: Literal["PENDING", "CLOSED"] = "PENDING",
        offset: int = Query(0, ge=0),
        relyqo_session: str | None = Cookie(default=None),
        db: Session = Depends(get_db),
    ):
        session_user(relyqo_session, db, "RELYQO_ADMIN")
        query = select(ModerationCase).where(
            ModerationCase.status == "PENDING"
            if status == "PENDING"
            else ModerationCase.status != "PENDING"
        )
        rows = db.scalars(
            query.order_by(ModerationCase.created_at.desc()).offset(offset).limit(50)
        ).all()
        items = []
        for r in rows:
            rating = (
                db.get(
                    Rating if r.rating_type == "VERIFIED" else CommunityRating,
                    r.rating_id,
                )
                if r.rating_id
                else None
            )
            photo = (
                db.scalar(
                    select(RatingPhoto).where(
                        (RatingPhoto.rating_id == r.rating_id)
                        if r.rating_type == "VERIFIED"
                        else (RatingPhoto.community_rating_id == r.rating_id)
                    )
                )
                if rating
                else None
            )
            signals = (
                json.loads(r.details).get("signals", []) if r.kind == "SIGNAL" else []
            )
            items.append(
                {
                    "id": r.id,
                    "kind": r.kind,
                    "organization": object_name(db, r.object_key),
                    "details": "\n".join(SIGNALS.get(s, s) for s in signals)
                    if signals
                    else r.details,
                    "status": r.status,
                    "decision_note": r.decision_note,
                    "created_at": r.created_at,
                    "decided_at": r.decided_at,
                    "decided_by": db.get(User, r.decided_by).username
                    if r.decided_by
                    else None,
                    "rating": {"overall": rating.overall, **feedback_payload(rating)}
                    if rating
                    else None,
                    "photo_url": f"/v1/admin/control/photos/{photo.id}"
                    if photo
                    else None,
                    "ai_analysis": photo.ai_analysis if photo else None,
                }
            )
        legacy = []
        if offset == 0:
            old = db.scalars(
                select(OwnerReview)
                .where(
                    OwnerReview.entity_type == "RATING",
                    OwnerReview.status == "PENDING"
                    if status == "PENDING"
                    else OwnerReview.status != "PENDING",
                )
                .limit(100)
            ).all()
            for r in old:
                if db.scalar(
                    select(ModerationCase.id).where(
                        ModerationCase.case_key == "legacy:" + r.id
                    )
                ):
                    continue
                rating = db.get(Rating, r.entity_id)
                if rating:
                    photo = db.scalar(
                        select(RatingPhoto).where(RatingPhoto.rating_id == rating.id)
                    )
                    legacy.append(
                        {
                            "id": "review:" + r.id,
                            "kind": "REVIEW",
                            "organization": object_name(
                                db, "org:" + rating.organization_id
                            ),
                            "details": r.reason,
                            "status": r.status,
                            "photo_url": f"/v1/admin/control/photos/{photo.id}"
                            if photo
                            else None,
                            "ai_analysis": photo.ai_analysis if photo else None,
                            "rating": {
                                "overall": rating.overall,
                                **feedback_payload(rating),
                            },
                        }
                    )
        application_history = []
        if status == "CLOSED" and offset == 0:
            for event in db.scalars(
                select(AuditLog)
                .where(
                    AuditLog.action.in_(
                        [
                            "BUSINESS_PROFILE_PUBLISHED",
                            "BUSINESS_PROFILE_VERIFIED_PARTNER",
                            "BUSINESS_PROFILE_REJECTED",
                        ]
                    )
                )
                .order_by(AuditLog.created_at.desc())
                .limit(100)
            ).all():
                application_history.append(
                    {
                        "id": event.id,
                        "kind": "APPLICATION",
                        "organization": object_name(db, "org:" + event.entity_id),
                        "details": "",
                        "status": event.action.removeprefix("BUSINESS_PROFILE_"),
                        "created_at": event.created_at,
                    }
                )
        response.headers["Cache-Control"] = "no-store"
        return {
            "application_history": application_history,
            "items": items,
            "legacy": legacy,
            "next_offset": offset + 50 if len(rows) == 50 else None,
        }

    @app.get("/v1/admin/control/feedback")
    def feedback_list(
        response: Response,
        source: Literal["VERIFIED", "COMMUNITY"] = "COMMUNITY",
        offset: int = Query(0, ge=0),
        relyqo_session: str | None = Cookie(default=None),
        db: Session = Depends(get_db),
    ):
        session_user(relyqo_session, db, "RELYQO_ADMIN")
        model = Rating if source == "VERIFIED" else CommunityRating
        rows = db.scalars(
            select(model)
            .order_by(model.created_at.desc(), model.id)
            .offset(offset)
            .limit(50)
        ).all()
        items = []
        for r in rows:
            photo = db.scalar(
                select(RatingPhoto).where(
                    RatingPhoto.rating_id == r.id
                    if source == "VERIFIED"
                    else RatingPhoto.community_rating_id == r.id
                )
            )
            items.append(
                {
                    "id": r.id,
                    "kind": source,
                    "status": r.status,
                    "organization": object_name(
                        db,
                        "org:" + r.organization_id
                        if source == "VERIFIED"
                        else r.object_key,
                    ),
                    "details": "",
                    "created_at": r.created_at,
                    "rating": {"overall": r.overall, **feedback_payload(r)},
                    "photo_url": f"/v1/admin/control/photos/{photo.id}"
                    if photo
                    else None,
                    "ai_analysis": photo.ai_analysis if photo else None,
                }
            )
        response.headers["Cache-Control"] = "no-store"
        return {"items": items, "next_offset": offset + 50 if len(rows) == 50 else None}

    @app.get("/v1/admin/control/photos/{photo_id}")
    def admin_photo(
        photo_id: str,
        relyqo_session: str | None = Cookie(default=None),
        db: Session = Depends(get_db),
    ):
        session_user(relyqo_session, db, "RELYQO_ADMIN")
        photo = db.get(RatingPhoto, photo_id)
        if not photo:
            raise HTTPException(404, "Фото не найдено")
        return Response(
            photo.image_data,
            media_type=photo.content_type,
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    @app.post("/v1/admin/control/cases/{case_id}/decision")
    def decision(
        case_id: str,
        body: CaseDecision,
        response: Response,
        relyqo_session: str | None = Cookie(default=None),
        db: Session = Depends(get_db),
    ):
        user = session_user(relyqo_session, db, "RELYQO_ADMIN")
        if len(body.note.strip()) < 10:
            raise HTTPException(422, "Укажите причину решения")
        legacy = case_id.startswith("review:")
        model = OwnerReview if legacy else ModerationCase
        identifier = case_id.removeprefix("review:") if legacy else case_id
        case = db.get(model, identifier)
        if not case or (legacy and case.entity_type != "RATING"):
            raise HTTPException(404, "Обращение не найдено")
        if case.status != "PENDING":
            raise HTTPException(409, "Решение уже принято")
        rating_type = "VERIFIED" if legacy else case.rating_type
        rating_id = case.entity_id if legacy else case.rating_id
        rating = (
            db.scalar(
                select(Rating if rating_type == "VERIFIED" else CommunityRating)
                .where(
                    (Rating.id if rating_type == "VERIFIED" else CommunityRating.id)
                    == rating_id
                )
                .with_for_update()
            )
            if rating_id
            else None
        )
        case = db.scalar(
            select(model)
            .where(model.id == identifier)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if case.status != "PENDING":
            raise HTTPException(409, "Решение уже принято")
        if (legacy and body.decision == "DISMISS") or (
            not rating and body.decision != "DISMISS"
        ):
            raise HTTPException(
                422, "Для обращения без оценки выберите «Закрыть с ответом»"
            )
        if rating and body.decision != "DISMISS":
            rating.included = body.decision == "APPROVE"
            rating.status = "ACCEPTED" if rating.included else "REJECTED"
            db.flush()
            if rating_type == "VERIFIED":
                recalculate(db.get(Organization, rating.organization_id), db)
                # Close the legacy contradiction review as well, preventing a stale second decision.
                for related in db.scalars(
                    select(OwnerReview).where(
                        OwnerReview.entity_type == "RATING",
                        OwnerReview.entity_id == rating.id,
                        OwnerReview.status == "PENDING",
                    )
                ).all():
                    related.status = "APPROVED" if rating.included else "REJECTED"
            for related in db.scalars(
                select(ModerationCase).where(
                    ModerationCase.rating_id == rating.id,
                    ModerationCase.status == "PENDING",
                    ModerationCase.id != identifier,
                )
            ).all():
                related.status = "APPROVED" if rating.included else "REJECTED"
                related.decided_by = user.id
                related.decided_at = datetime.utcnow()
                related.decision_note = body.note.strip()
        case.status = {
            "APPROVE": "APPROVED",
            "REJECT": "REJECTED",
            "DISMISS": "DISMISSED",
        }[body.decision]
        if legacy:
            db.add(
                ModerationCase(
                    case_key="legacy:" + case.id,
                    kind="REVIEW",
                    object_key="org:" + rating.organization_id,
                    rating_id=rating.id,
                    rating_type="VERIFIED",
                    details=case.reason,
                    status=case.status,
                    decision_note=body.note.strip(),
                    decided_by=user.id,
                    decided_at=datetime.utcnow(),
                )
            )
        else:
            case.decision_note, case.decided_by, case.decided_at = (
                body.note.strip(),
                user.id,
                datetime.utcnow(),
            )
        db.add(
            AuditLog(
                actor_type=user.role,
                action="ADMIN_CASE_" + case.status,
                entity_type="MODERATION_CASE",
                entity_id=identifier,
            )
        )
        db.commit()
        response.headers["Cache-Control"] = "no-store"
        return {"id": case_id, "status": case.status}
