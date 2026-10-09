"""Opt-in consumer/business conversations. Never mutate ratings or moderation cases."""

from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import Request, APIRouter, Cookie, Depends, HTTPException, Query, Response
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel, Field, StrictBool
from sqlalchemy import false, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import get_db
from .models import (AuditLog, Branch, CommunityRating, ManualPlace, Organization,
                     Rating, ServiceMessage, ServiceRequest, User, Visit)
from .password_recovery import limited
from .request_notifications import queue_request_notifications, wake
from .consumer_entry import require_consumer_page
from .request_engagement import (active_representative, decorate_rows, mark_read, overdue_condition,
                                 represented_keys, statistics, unread_condition)

OWNERS = {"BUSINESS_OWNER", "FREGAT_OWNER"}
ROLES = OWNERS | {"CONSUMER", "RELYQO_ADMIN"}


class NewRequest(BaseModel):
    rating_id: str = Field(min_length=1, max_length=36)
    message: str = Field(min_length=10, max_length=2000)
    consent: StrictBool


class RequestAction(BaseModel):
    version: int = Field(ge=1)
    action: Literal["reply", "start", "resolve", "reopen", "withdraw"]
    message: str = Field(default="", max_length=2000)


class Assignment(BaseModel):
    version: int = Field(ge=1)
    branch_id: str = Field(min_length=1, max_length=36)
    confirmed: StrictBool
    note: str = Field(min_length=10, max_length=1000)


def usable_organization(db, organization_id):
    org = db.get(Organization, organization_id) if organization_id else None
    if not org or org.profile_status != "VERIFIED_PARTNER":
        return False
    return bool(db.scalar(select(User.id).where(
        User.organization_id == org.id, User.active.is_(True), User.role.in_(OWNERS)
    ).limit(1)))


def own_rating(db, user, rating_id):
    rating = db.get(Rating, rating_id)
    if rating and rating.consumer_user_id == user.id:
        visit = db.get(Visit, rating.visit_id)
        branch = db.get(Branch, visit.branch_id) if visit else None
        if branch:
            return rating, "VERIFIED", "relyqo:" + branch.id, branch
    rating = db.get(CommunityRating, rating_id)
    if rating and rating.consumer_user_id == user.id:
        key = rating.object_key
        if key.startswith("relyqo:"):
            branch = db.get(Branch, key.split(":", 1)[1])
            if branch:
                return rating, "COMMUNITY", key, branch
        if key.startswith("manual:") and db.get(ManualPlace, key.split(":", 1)[1]):
            # A name or imported map ID is not proof of business ownership.
            return rating, "COMMUNITY", key, None
    raise HTTPException(404, "Оценка недоступна для обращения")


def object_info(db, key):
    prefix, _, identifier = key.partition(":")
    if prefix == "manual":
        place = db.get(ManualPlace, identifier)
        if place:
            return {"name": place.name, "address": place.address}
    if prefix == "relyqo":
        branch = db.get(Branch, identifier)
        org = db.get(Organization, branch.organization_id) if branch else None
        if org:
            return {"name": org.name, "address": branch.address or branch.name}
    return {"name": "Организация", "address": ""}


def effective_view(db, user, view="auto"):
    if view == "auto":
        view = "admin" if user.role == "RELYQO_ADMIN" else "business" if user.role in OWNERS else "consumer"
    if view not in {"consumer", "business", "admin"}:
        raise HTTPException(422, "Неизвестный раздел обращений")
    if (view == "admin" and user.role != "RELYQO_ADMIN") or (view == "consumer" and user.role != "CONSUMER"):
        raise HTTPException(403, "У этого аккаунта нет доступа")
    if view == "business" and user.role not in OWNERS | {"CONSUMER"}:
        raise HTTPException(403, "У этого аккаунта нет доступа")
    return view


def scope(query, user, db, view="auto"):
    view = effective_view(db, user, view)
    if view == "consumer":
        return query.where(ServiceRequest.consumer_user_id == user.id)
    if view == "business":
        keys = represented_keys(db, user)
        owner = user.role in OWNERS and usable_organization(db, user.organization_id)
        if not owner and not keys:
            raise HTTPException(403, "Ответы доступны после подтверждения организации администратором RELYQO")
        return query.where(or_(ServiceRequest.organization_id == user.organization_id if owner else false(),
                               ServiceRequest.object_key.in_(keys)),
                           ServiceRequest.consumer_user_id != user.id,
                           ServiceRequest.status.not_in(["WITHDRAWN", "WAITING_ORGANIZATION"]))
    return query


def get_request(db, user, request_id, view="auto"):
    item = db.scalar(scope(select(ServiceRequest), user, db, view).where(ServiceRequest.id == request_id))
    if not item:
        raise HTTPException(404, "Обращение не найдено")
    return item


def serialize(db, item, user, detail=False):
    # Never serialize user IDs, usernames, private rating comments/reasons/photos, or scores.
    payload = {"id": item.id, "organization": object_info(db, item.object_key),
               "status": item.status, "version": item.version,
               "created_at": item.created_at.isoformat() + "Z",
               "updated_at": item.updated_at.isoformat() + "Z"}
    if user.role == "CONSUMER" and item.consumer_user_id == user.id:
        payload["rating_id"] = item.rating_id
    if detail:
        payload["messages"] = [{"side": m.side, "body": m.body,
                                "created_at": m.created_at.isoformat() + "Z"}
                               for m in db.scalars(select(ServiceMessage).where(
                                   ServiceMessage.request_id == item.id).order_by(ServiceMessage.created_at, ServiceMessage.id))]
        if user.role == "RELYQO_ADMIN":
            payload["assignment_note"] = item.assignment_note
        if item.organization_id:
            org = db.get(Organization, item.organization_id)
            payload["recipient"] = org.name if org else None
        elif active_representative(db, item.object_key) and item.status != "WAITING_ORGANIZATION":
            payload["recipient"] = object_info(db, item.object_key)["name"]
    return payload


def audit(db, user, item, action):
    db.add(AuditLog(actor_type=user.role, action="SERVICE_REQUEST_" + action,
                    entity_type="SERVICE_REQUEST", entity_id=item.id))


def bump(db, item, version, **values):
    result = db.execute(update(ServiceRequest).where(
        ServiceRequest.id == item.id, ServiceRequest.version == version
    ).values(**values, version=version + 1, updated_at=datetime.utcnow()),
                        execution_options={"synchronize_session": False})
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "Обращение обновилось. Обновите переписку и повторите действие")
    db.flush()
    db.refresh(item)


def throttle(db, user):
    if limited(db, "service-request-write", user.id, 30):
        raise HTTPException(429, "Слишком много сообщений. Попробуйте через час")


def register_service_requests(app, session_user):
    def private_response(response: Response):
        response.headers["Cache-Control"] = "private, no-store, max-age=0"

    api = APIRouter(dependencies=[Depends(private_response)])
    @app.get("/me/requests", include_in_schema=False, dependencies=[Depends(require_consumer_page)])
    @app.get("/business/requests", include_in_schema=False)
    @app.get("/admin/requests", include_in_schema=False)
    def page(request: Request):
        if request.url.path == "/me/requests":
            content = (Path(__file__).parent / "static" / "service-requests.html").read_text(encoding="utf-8")
            return HTMLResponse(content.replace("<body", '<body data-consumer-authenticated="true"', 1), headers={"Cache-Control": "no-store"})
        return FileResponse(Path(__file__).parent / "static" / "service-requests.html", headers={"Cache-Control": "no-store"})

    @api.get("/v1/service-requests/context")
    def context(rating_id: str = Query(max_length=36), db: Session = Depends(get_db),
                relyqo_session: str | None = Cookie(default=None)):
        user = session_user(relyqo_session, db, "CONSUMER")
        _, kind, key, branch = own_rating(db, user, rating_id)
        existing = db.scalar(select(ServiceRequest.id).where(
            ServiceRequest.rating_id == rating_id, ServiceRequest.rating_type == kind))
        ready = bool(branch and branch.active and usable_organization(db, branch.organization_id)) or bool(
            active_representative(db, key) and active_representative(db, key) != user.id)
        return {"organization": object_info(db, key), "ready": ready, "existing_id": existing}

    @api.post("/v1/service-requests", status_code=201)
    def create(body: NewRequest, response: Response, db: Session = Depends(get_db),
               relyqo_session: str | None = Cookie(default=None)):
        user = session_user(relyqo_session, db, "CONSUMER")
        if not body.consent:
            raise HTTPException(422, "Подтвердите согласие на передачу текста организации")
        message = body.message.strip()
        if len(message) < 10:
            raise HTTPException(422, "Опишите обращение: от 10 до 2000 символов")
        _, kind, key, branch = own_rating(db, user, body.rating_id)
        query = select(ServiceRequest).where(ServiceRequest.rating_id == body.rating_id,
                                             ServiceRequest.rating_type == kind)
        existing = db.scalar(query)
        if existing:
            response.status_code = 200
            return serialize(db, existing, user, True)
        throttle(db, user)
        branch_ready = bool(branch and branch.active and usable_organization(db, branch.organization_id))
        representative = active_representative(db, key)
        ready = branch_ready or bool(representative and representative != user.id)
        item = ServiceRequest(rating_id=body.rating_id, rating_type=kind,
                              consumer_user_id=user.id, object_key=key,
                              branch_id=branch.id if branch_ready else None,
                              organization_id=branch.organization_id if branch_ready else None,
                              status="OPEN" if ready else "WAITING_ORGANIZATION")
        try:
            db.add(item)
            db.flush()
            db.add(ServiceMessage(request_id=item.id, author_id=user.id, side="CONSUMER", body=message))
            mark_read(db, user.id, item.id, item.version)
            audit(db, user, item, "CREATED")
            queue_request_notifications(db, item, user.id)
            db.commit()
            wake.set()
        except IntegrityError:
            db.rollback()
            item = db.scalar(query)
            if not item:
                raise
            response.status_code = 200
        return serialize(db, item, user, True)

    @api.get("/v1/service-requests")
    def listing(db: Session = Depends(get_db), relyqo_session: str | None = Cookie(default=None),
                offset: int = Query(default=0, ge=0), limit: int = Query(default=20, ge=1, le=50),
                view: str = "auto", filter: Literal["ALL", "UNREAD", "NEEDS_REPLY", "OVERDUE", "WAITING_ORGANIZATION", "ANSWERED", "RESOLVED", "WITHDRAWN"] = "ALL"):
        user = session_user(relyqo_session, db, ROLES)
        mode = effective_view(db, user, view)
        query = scope(select(ServiceRequest), user, db, mode)
        summary = statistics(db, query)
        if filter == "UNREAD":
            query = query.where(unread_condition(user.id))
        elif filter == "NEEDS_REPLY":
            query = query.where(ServiceRequest.status.in_(["OPEN", "IN_PROGRESS"]))
        elif filter == "OVERDUE":
            query = query.where(overdue_condition())
        elif filter != "ALL":
            query = query.where(ServiceRequest.status == filter)
        items = list(db.scalars(query.order_by(ServiceRequest.updated_at.desc(), ServiceRequest.id).offset(offset).limit(limit + 1)))
        extra = decorate_rows(db, items[:limit], user)
        return {"role": "REPRESENTATIVE" if mode == "business" and user.role == "CONSUMER" else user.role,
                "items": [{**serialize(db, item, user), **extra[item.id]} for item in items[:limit]],
                "has_more": len(items) > limit, "summary": summary}

    @api.get("/v1/service-requests/branches")
    def branches(q: str = Query(min_length=2, max_length=100), db: Session = Depends(get_db),
                 relyqo_session: str | None = Cookie(default=None)):
        session_user(relyqo_session, db, "RELYQO_ADMIN")
        rows = db.execute(select(Branch, Organization).join(Organization, Branch.organization_id == Organization.id)
                          .where(Branch.active.is_(True), Organization.profile_status == "VERIFIED_PARTNER",
                                 Organization.name.contains(q.strip(), autoescape=True)).limit(50))
        return {"items": [{"id": b.id, "name": o.name, "address": b.address or b.name}
                          for b, o in rows if usable_organization(db, o.id)]}

    @api.get("/v1/service-requests/{request_id}")
    def detail(request_id: str, view: str = "auto", db: Session = Depends(get_db), relyqo_session: str | None = Cookie(default=None)):
        user = session_user(relyqo_session, db, ROLES)
        item = get_request(db, user, request_id, view)
        return {**serialize(db, item, user, True), **decorate_rows(db, [item], user)[item.id]}

    @api.post("/v1/service-requests/{request_id}/assign")
    def assign(request_id: str, body: Assignment, db: Session = Depends(get_db),
               relyqo_session: str | None = Cookie(default=None)):
        user = session_user(relyqo_session, db, "RELYQO_ADMIN")
        item = get_request(db, user, request_id)
        if item.status != "WAITING_ORGANIZATION":
            raise HTTPException(409, "Организация уже назначена или обращение закрыто")
        branch = db.get(Branch, body.branch_id)
        if not body.confirmed or len(body.note.strip()) < 10:
            raise HTTPException(422, "Подтвердите совпадение организации и укажите основание проверки")
        if not branch or not branch.active or not usable_organization(db, branch.organization_id):
            raise HTTPException(422, "Выберите подтверждённую организацию с активным владельцем")
        # A verified-visit identity is immutable, even for an administrator.
        if item.object_key.startswith("relyqo:") and item.object_key != "relyqo:" + branch.id:
            raise HTTPException(422, "Филиал не совпадает с оценённой организацией")
        bump(db, item, body.version, branch_id=branch.id, organization_id=branch.organization_id,
             status="OPEN", assigned_by=user.id, assignment_note=body.note.strip())
        audit(db, user, item, "ASSIGNED")
        mark_read(db, user.id, item.id, item.version)
        queue_request_notifications(db, item, user.id)
        db.commit()
        wake.set()
        return serialize(db, item, user, True)

    @api.post("/v1/service-requests/{request_id}/actions")
    def action(request_id: str, body: RequestAction, db: Session = Depends(get_db),
               relyqo_session: str | None = Cookie(default=None), view: str = "auto"):
        user = session_user(relyqo_session, db, OWNERS | {"CONSUMER"})
        throttle(db, user)
        mode = effective_view(db, user, view)
        item = get_request(db, user, request_id, mode)
        if item.version != body.version:
            raise HTTPException(409, "Обращение обновилось. Обновите переписку и повторите действие")
        owner = mode == "business"
        states = ({"start": {"OPEN"}, "reply": {"OPEN", "IN_PROGRESS", "ANSWERED"}} if owner else {
            "reply": {"WAITING_ORGANIZATION", "OPEN", "IN_PROGRESS", "ANSWERED"},
            "resolve": {"ANSWERED"}, "reopen": {"RESOLVED"},
            "withdraw": {"WAITING_ORGANIZATION", "OPEN", "IN_PROGRESS", "ANSWERED", "RESOLVED"},
        })
        if item.status not in states.get(body.action, set()):
            raise HTTPException(409, "Это действие недоступно для текущего статуса обращения")
        message = body.message.strip()
        if body.action in {"reply", "reopen"} and len(message) < 2:
            raise HTTPException(422, "Напишите сообщение: от 2 до 2000 символов")
        if body.action == "reply":
            status = "ANSWERED" if owner else ("WAITING_ORGANIZATION" if item.status == "WAITING_ORGANIZATION" else "IN_PROGRESS")
        else:
            status = {"start": "IN_PROGRESS", "resolve": "RESOLVED", "reopen": "IN_PROGRESS", "withdraw": "WITHDRAWN"}[body.action]
        if not owner and body.action in {"reply", "reopen"}:
            # A revoked or disabled recipient must not leave follow-ups in an unowned queue.
            representative = active_representative(db, item.object_key)
            ready = usable_organization(db, item.organization_id) or bool(
                representative and representative != item.consumer_user_id)
            status = "IN_PROGRESS" if ready else "WAITING_ORGANIZATION"
        bump(db, item, body.version, status=status)
        if body.action in {"reply", "reopen"}:
            db.add(ServiceMessage(request_id=item.id, author_id=user.id,
                                  side="BUSINESS" if owner else "CONSUMER", body=message))
        audit(db, user, item, body.action.upper())
        mark_read(db, user.id, item.id, item.version)
        queue_request_notifications(db, item, user.id)
        db.commit()
        wake.set()
        return serialize(db, item, user, True)

    app.include_router(api)
