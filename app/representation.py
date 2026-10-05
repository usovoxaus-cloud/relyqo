"""Administrator-approved representatives of existing public cards. No rating or role changes."""
from datetime import datetime
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, StrictBool
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from .db import get_db
from .models import (AuditLog, Branch, ManualPlace, Organization, RepresentationClaim,
                     ServiceRepresentative, ServiceRequest, User)
from .password_recovery import limited
from .request_engagement import active_representative
from .service_requests import OWNERS, object_info, usable_organization


class ClaimInput(BaseModel):
    object_key: str = Field(min_length=8, max_length=320)
    contact: str = Field(min_length=5, max_length=200)
    evidence: str = Field(min_length=20, max_length=2000)
    consent: StrictBool
    version: int | None = Field(default=None, ge=1)


class ClaimDecision(BaseModel):
    version: int = Field(ge=1)
    action: Literal["approve", "reject", "revoke"]
    note: str = Field(min_length=20, max_length=2000)
    verified: StrictBool = False


class ClaimRead(BaseModel):
    id: str = Field(max_length=36)
    version: int = Field(ge=1)


class ClaimReads(BaseModel):
    items: list[ClaimRead] = Field(max_length=20)


def valid_card(db, key):
    kind, _, identifier = key.partition(":")
    if kind == "manual":
        place = db.get(ManualPlace, identifier)
        if place and place.active:
            return
    elif kind == "relyqo":
        branch = db.get(Branch, identifier)
        org = db.get(Organization, branch.organization_id) if branch else None
        if branch and branch.active and org and org.profile_status in {"PUBLISHED", "VERIFIED_PARTNER"}:
            return
    raise HTTPException(404, "Карточка организации недоступна")


def claim_data(db, row, admin=False):
    data = {"id": row.id, "object_key": row.object_key, "organization": object_info(db, row.object_key),
            "status": row.status, "version": row.version, "contact": row.contact, "evidence": row.evidence,
            "decision_note": row.decision_note, "created_at": row.created_at.isoformat()+"Z"}
    if admin:
        user = db.get(User, row.user_id)
        data["applicant"] = user.username if user else ""
        data["applicant_active"] = bool(user and user.active)
    return data


def register_representation(app, session_user):
    def private(response: Response):
        response.headers["Cache-Control"] = "private, no-store"
    router = APIRouter(dependencies=[Depends(private)])

    @app.get("/representative", include_in_schema=False)
    @app.get("/admin/representatives", include_in_schema=False)
    def page():
        return FileResponse(Path(__file__).parent/"static"/"representative.html", headers={"Cache-Control":"no-store"})

    @router.get("/v1/representation/context")
    def context(object_key: str = Query(max_length=320), db=Depends(get_db), relyqo_session: str | None = Cookie(default=None)):
        user = session_user(relyqo_session, db, OWNERS | {"CONSUMER"})
        valid_card(db, object_key)
        existing = db.scalar(select(RepresentationClaim).where(RepresentationClaim.user_id == user.id,
                                                               RepresentationClaim.object_key == object_key))
        return {"organization": object_info(db, object_key), "claim": claim_data(db, existing) if existing else None,
                "represented": bool(active_representative(db, object_key))}

    @router.post("/v1/representation/claims")
    def submit(body: ClaimInput, db=Depends(get_db), relyqo_session: str | None = Cookie(default=None)):
        user = session_user(relyqo_session, db, OWNERS | {"CONSUMER"})
        valid_card(db, body.object_key)
        if not body.consent or len(body.contact.strip()) < 5 or len(body.evidence.strip()) < 20:
            raise HTTPException(422, "Укажите рабочий контакт, основание полномочий и согласие на проверку")
        if limited(db, "representation-claim", user.id, 5):
            raise HTTPException(429, "Слишком много заявок. Попробуйте через час")
        query = select(RepresentationClaim).where(RepresentationClaim.user_id == user.id,
                                                  RepresentationClaim.object_key == body.object_key)
        row = db.scalar(query)
        if row and row.status in {"PENDING", "APPROVED"}:
            return claim_data(db, row)
        if row:
            result = db.execute(update(RepresentationClaim).where(RepresentationClaim.id == row.id,
                RepresentationClaim.version == body.version, RepresentationClaim.status.in_(["REJECTED", "REVOKED"]))
                .values(contact=body.contact.strip(), evidence=body.evidence.strip(), status="PENDING",
                        decision_note=None, decided_by=None, version=RepresentationClaim.version+1,
                        applicant_seen_version=RepresentationClaim.version+1, updated_at=datetime.utcnow()))
            if result.rowcount != 1:
                db.rollback()
                raise HTTPException(409, "Заявка обновилась. Обновите страницу")
            db.refresh(row)
        else:
            row = RepresentationClaim(user_id=user.id, object_key=body.object_key,
                                      contact=body.contact.strip(), evidence=body.evidence.strip())
            db.add(row)
        try:
            db.flush()
            db.add(AuditLog(actor_type=user.role, action="REPRESENTATION_REQUESTED", entity_type="REPRESENTATION", entity_id=row.id))
            db.commit()
        except IntegrityError:
            db.rollback()
            row = db.scalar(query)
            if not row:
                raise
        return claim_data(db, row)

    @router.get("/v1/representation/claims")
    def listing(db=Depends(get_db), relyqo_session: str | None = Cookie(default=None),
                status: Literal["ALL", "PENDING", "APPROVED", "REJECTED", "REVOKED"] = "ALL",
                offset: int = Query(default=0, ge=0)):
        user = session_user(relyqo_session, db, OWNERS | {"CONSUMER", "RELYQO_ADMIN"})
        query = select(RepresentationClaim)
        admin = user.role == "RELYQO_ADMIN"
        if not admin:
            query = query.where(RepresentationClaim.user_id == user.id)
        if status != "ALL":
            query = query.where(RepresentationClaim.status == status)
        rows = list(db.scalars(query.order_by(RepresentationClaim.updated_at.desc(), RepresentationClaim.id).offset(offset).limit(21)))
        return {"admin": admin, "items": [claim_data(db, r, admin) for r in rows[:20]], "has_more": len(rows)>20}

    @router.post("/v1/representation/claims/{claim_id}/decision")
    def decide(claim_id: str, body: ClaimDecision, db=Depends(get_db), relyqo_session: str | None = Cookie(default=None)):
        admin = session_user(relyqo_session, db, "RELYQO_ADMIN")
        row = db.get(RepresentationClaim, claim_id)
        if not row:
            raise HTTPException(404, "Заявка не найдена")
        required_status = "APPROVED" if body.action == "revoke" else "PENDING"
        if row.status != required_status or row.version != body.version:
            raise HTTPException(409, "Заявка обновилась. Обновите страницу")
        if len(body.note.strip()) < 20:
            raise HTTPException(422, "Запишите основание решения: не менее 20 символов")
        if body.action == "approve":
            valid_card(db, row.object_key)
            applicant = db.get(User, row.user_id)
            if not body.verified or not applicant or not applicant.active or applicant.role not in OWNERS | {"CONSUMER"}:
                raise HTTPException(422, "Подтвердите проверку полномочий активного заявителя")
            existing = db.get(ServiceRepresentative, row.object_key)
            if existing and existing.user_id != row.user_id:
                raise HTTPException(409, "У карточки уже есть представитель. Сначала проверьте и отзовите прежний доступ")
        target = {"approve":"APPROVED", "reject":"REJECTED", "revoke":"REVOKED"}[body.action]
        changed = db.execute(update(RepresentationClaim).where(RepresentationClaim.id == row.id,
            RepresentationClaim.version == body.version, RepresentationClaim.status == required_status).values(
                status=target, version=body.version+1, decision_note=body.note.strip(), decided_by=admin.id,
                updated_at=datetime.utcnow()), execution_options={"synchronize_session":False})
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, "Заявка обновилась. Обновите страницу")
        try:
            if body.action == "approve":
                if not db.get(ServiceRepresentative, row.object_key):
                    db.add(ServiceRepresentative(object_key=row.object_key, user_id=row.user_id, claim_id=row.id))
                    db.flush()
                # Consent is for this exact card. Never transfer ratings or private feedback.
                db.execute(update(ServiceRequest).where(ServiceRequest.object_key == row.object_key,
                    ServiceRequest.consumer_user_id != row.user_id, ServiceRequest.status == "WAITING_ORGANIZATION")
                    .values(status="OPEN", version=ServiceRequest.version+1, updated_at=datetime.utcnow()))
            elif body.action == "revoke":
                db.execute(delete(ServiceRepresentative).where(ServiceRepresentative.object_key == row.object_key,
                                                               ServiceRepresentative.claim_id == row.id))
                for request in db.scalars(select(ServiceRequest).where(ServiceRequest.object_key == row.object_key,
                                                         ServiceRequest.status != "WITHDRAWN").with_for_update()):
                    state = request.status
                    if state in {"OPEN", "IN_PROGRESS"} and not usable_organization(db, request.organization_id):
                        state = "WAITING_ORGANIZATION"
                    db.execute(update(ServiceRequest).where(ServiceRequest.id == request.id).values(status=state,
                               version=ServiceRequest.version+1, updated_at=datetime.utcnow()))
            db.add(AuditLog(actor_type=admin.role, action="REPRESENTATION_"+target, entity_type="REPRESENTATION", entity_id=row.id))
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "У карточки уже есть представитель. Сначала проверьте и отзовите прежний доступ")
        db.refresh(row)
        return claim_data(db, row, True)

    @router.post("/v1/representation/read")
    def read(body: ClaimReads, db=Depends(get_db), relyqo_session: str | None = Cookie(default=None)):
        user = session_user(relyqo_session, db, OWNERS | {"CONSUMER"})
        for item in body.items:
            row = db.get(RepresentationClaim, item.id)
            if not row or row.user_id != user.id:
                raise HTTPException(404, "Заявка не найдена")
            if item.version > row.version:
                raise HTTPException(409, "Заявка обновилась. Обновите страницу")
            db.execute(update(RepresentationClaim).where(RepresentationClaim.id == row.id,
                RepresentationClaim.applicant_seen_version < item.version).values(applicant_seen_version=item.version))
        db.commit()
        return {"read": True}

    app.include_router(router)
