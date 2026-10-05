"""Read receipts, scoped reminders and response statistics for opt-in conversations."""
from datetime import datetime, timedelta
from urllib.parse import quote
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import case, func, or_, select

from .db import get_db
from .models import (RepresentationClaim, ServiceMessage, ServiceRepresentative,
                     ServiceRequest, ServiceRequestRead, User)

OVERDUE_HOURS = 48


def represented_keys(db, user):
    return list(db.scalars(select(ServiceRepresentative.object_key).where(ServiceRepresentative.user_id == user.id)))


def active_representative(db, object_key):
    return db.scalar(select(ServiceRepresentative.user_id).join(User, User.id == ServiceRepresentative.user_id)
                     .where(ServiceRepresentative.object_key == object_key, User.active.is_(True)))


def mark_read(db, user_id, request_id, version):
    # A delayed tab must never mark a newer response as read or move the receipt backwards.
    if db.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    insert_row = insert(ServiceRequestRead).values(user_id=user_id, request_id=request_id, version=version)
    db.execute(insert_row.on_conflict_do_update(index_elements=["user_id", "request_id"],
               set_={"version": version}, where=ServiceRequestRead.version < version))


def unread_condition(user_id):
    seen = select(ServiceRequestRead.version).where(ServiceRequestRead.user_id == user_id,
            ServiceRequestRead.request_id == ServiceRequest.id).scalar_subquery()
    return func.coalesce(seen, 0) < ServiceRequest.version


def waiting_since():
    return func.coalesce(select(func.max(ServiceMessage.created_at)).where(
        ServiceMessage.request_id == ServiceRequest.id, ServiceMessage.side == "CONSUMER"
    ).scalar_subquery(), ServiceRequest.created_at)


def overdue_condition():
    return (ServiceRequest.status.in_(["OPEN", "IN_PROGRESS"])) & (waiting_since() <= datetime.utcnow() - timedelta(hours=OVERDUE_HOURS))


def decorate_rows(db, rows, user):
    ids = [r.id for r in rows]
    if not ids:
        return {}
    reads = dict(db.execute(select(ServiceRequestRead.request_id, ServiceRequestRead.version).where(
        ServiceRequestRead.user_id == user.id, ServiceRequestRead.request_id.in_(ids))).all())
    waiting = dict(db.execute(select(ServiceMessage.request_id, func.max(ServiceMessage.created_at)).where(
        ServiceMessage.request_id.in_(ids), ServiceMessage.side == "CONSUMER").group_by(ServiceMessage.request_id)).all())
    now = datetime.utcnow()
    result = {}
    for item in rows:
        since = waiting.get(item.id, item.created_at)
        needs_reply = item.status in {"OPEN", "IN_PROGRESS"}
        result[item.id] = {"unread": reads.get(item.id, 0) < item.version,
            "waiting_hours": round(max(0, (now - since).total_seconds() / 3600), 1) if needs_reply else None,
            "overdue": needs_reply and since <= now - timedelta(hours=OVERDUE_HOURS)}
    return result


def statistics(db, query):
    scoped = query.subquery()
    counts = dict(db.execute(select(scoped.c.status, func.count()).group_by(scoped.c.status)).all())
    total = sum(counts.values())
    eligible = total - counts.get("WITHDRAWN", 0)
    first = select(ServiceMessage.request_id, func.min(ServiceMessage.created_at).label("first_at")).where(
        ServiceMessage.side == "BUSINESS").group_by(ServiceMessage.request_id).subquery()
    if db.bind.dialect.name == "postgresql":
        seconds = func.extract("epoch", first.c.first_at - scoped.c.created_at)
    else:
        seconds = (func.julianday(first.c.first_at) - func.julianday(scoped.c.created_at)) * 86400
    avg, answered = db.execute(select(func.avg(seconds), func.count()).select_from(
        scoped.join(first, first.c.request_id == scoped.c.id)).where(scoped.c.status != "WITHDRAWN")).one()
    overdue = db.scalar(select(func.count()).select_from(query.where(overdue_condition()).subquery()))
    return {"total": total, "waiting_organization": counts.get("WAITING_ORGANIZATION", 0),
            "needs_reply": counts.get("OPEN", 0) + counts.get("IN_PROGRESS", 0), "overdue": overdue,
            "answered": counts.get("ANSWERED", 0), "resolved": counts.get("RESOLVED", 0),
            "resolution_percent": round(100 * counts.get("RESOLVED", 0) / eligible, 1) if eligible else None,
            "first_response_hours": round(max(0, avg) / 3600, 1) if avg is not None else None,
            "response_sample": answered, "overdue_hours": OVERDUE_HOURS}


class ReadReceipt(BaseModel):
    version: int = Field(ge=1)


def register_engagement(app, session_user):
    from .service_requests import OWNERS, ROLES, effective_view, get_request, object_info, scope
    def private(response: Response):
        response.headers["Cache-Control"] = "private, no-store"
    router = APIRouter(dependencies=[Depends(private)])

    @router.post("/v1/service-requests/{request_id}/read")
    def read(request_id: str, body: ReadReceipt, view: str = "auto", db=Depends(get_db), relyqo_session: str | None = Cookie(default=None)):
        user = session_user(relyqo_session, db, ROLES)
        mode = effective_view(db, user, view)
        item = get_request(db, user, request_id, mode)
        if body.version > item.version:
            raise HTTPException(409, "Обновите обращение перед отметкой прочтения")
        mark_read(db, user.id, item.id, body.version)
        db.commit()
        return {"read": True}

    @router.get("/v1/engagement/inbox")
    def inbox(db=Depends(get_db), relyqo_session: str | None = Cookie(default=None)):
        user = session_user(relyqo_session, db, ROLES)
        modes = ["admin"] if user.role == "RELYQO_ADMIN" else (["consumer"] if user.role == "CONSUMER" else [])
        # Unverified owners can still be approved representatives of an existing map card.
        from .service_requests import usable_organization
        business = bool(represented_keys(db, user)) or (user.role in OWNERS and usable_organization(db, user.organization_id))
        if business:
            modes.append("business")
        total, overdue, items = 0, 0, []
        for mode in modes:
            query = scope(select(ServiceRequest), user, db, mode)
            new = query.where(unread_condition(user.id))
            total += db.scalar(select(func.count()).select_from(new.subquery()))
            if mode in {"business", "admin"}:
                overdue += db.scalar(select(func.count()).select_from(query.where(overdue_condition()).subquery()))
            for row in db.scalars(new.order_by(ServiceRequest.updated_at.desc(), ServiceRequest.id).limit(5)):
                prefix = {"consumer": "/me", "business": "/business", "admin": "/admin"}[mode]
                items.append({"id": row.id, "name": object_info(db, row.object_key)["name"],
                              "status": row.status, "href": prefix + "/requests?id=" + row.id})
        pending_claims = db.scalar(select(func.count()).select_from(RepresentationClaim).where(
            RepresentationClaim.status == "PENDING")) if user.role == "RELYQO_ADMIN" else 0
        own_claims = select(RepresentationClaim).where(RepresentationClaim.user_id == user.id,
            RepresentationClaim.applicant_seen_version < RepresentationClaim.version,
            RepresentationClaim.status != "PENDING")
        total += db.scalar(select(func.count()).select_from(own_claims.subquery()))
        decisions = [{"id":r.id, "name":object_info(db,r.object_key)["name"], "status":"CLAIM_"+r.status,
                      "href":"/representative?object_key="+quote(r.object_key,safe="")}
                     for r in db.scalars(own_claims.order_by(RepresentationClaim.updated_at.desc()).limit(3))]
        return {"unread": total, "overdue": overdue, "pending_claims": pending_claims,
                "items": (decisions+items)[:8], "business": business, "admin": user.role == "RELYQO_ADMIN"}

    app.include_router(router)
