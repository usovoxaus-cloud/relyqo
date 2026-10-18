"""Drafts belong to one account; saving never sends a message or notification."""
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Cookie, Depends, HTTPException, Path, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import get_db
from .models import RequestDraft, ServiceRequest, User
from .password_recovery import limited

Kind = Literal["new", "reply"]
CONFLICT = "Черновик изменён в другом окне. Загрузите сохранённую версию перед изменением."


class DraftWrite(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    version: int = Field(ge=0)


class DraftDelete(BaseModel):
    version: int = Field(ge=1)


def draft_key(user_id, kind, context_id):
    return (RequestDraft.user_id == user_id, RequestDraft.kind == kind,
            RequestDraft.context_id == context_id)


def clear_sent_draft(db, user_id, kind, context_id, message):
    # A newer draft from another device must not be deleted by an older send.
    db.execute(delete(RequestDraft).where(*draft_key(user_id, kind, context_id),
                                         RequestDraft.body == message))


def register_request_drafts(app, session_user):
    from .service_requests import effective_view, get_request, own_rating, OWNERS

    def private(response: Response):
        response.headers["Cache-Control"] = "private, no-store, max-age=0"

    api = APIRouter(prefix="/v1/request-drafts", dependencies=[Depends(private)])

    def authorize(db, token, kind, context_id, view):
        user = session_user(token, db, OWNERS | {"CONSUMER"})
        if kind == "new":
            if user.role != "CONSUMER" or view not in {"auto", "consumer"}:
                raise HTTPException(403, "У этого аккаунта нет доступа")
            _, rating_kind, _, _ = own_rating(db, user, context_id)
            if db.scalar(select(ServiceRequest.id).where(
                ServiceRequest.rating_id == context_id, ServiceRequest.rating_type == rating_kind
            )):
                raise HTTPException(409, "Обращение уже отправлено. Откройте переписку.")
        else:
            mode = effective_view(db, user, view)
            item = get_request(db, user, context_id, mode)
            if item.status == "WITHDRAWN" or (mode == "business" and item.status == "RESOLVED"):
                raise HTTPException(409, "Это действие недоступно для текущего статуса обращения")
        return user

    def payload(item):
        return {"draft": {"message": item.body, "version": item.version,
                          "updated_at": item.updated_at.isoformat() + "Z"} if item else None}

    @api.get("/{kind}/{context_id}")
    def read(kind: Kind, context_id: str = Path(min_length=1, max_length=36),
             view: str = "auto", db: Session = Depends(get_db),
             relyqo_session: str | None = Cookie(default=None)):
        user = authorize(db, relyqo_session, kind, context_id, view)
        return payload(db.get(RequestDraft, (user.id, kind, context_id)))

    @api.post("/{kind}/{context_id}")
    def save(body: DraftWrite, kind: Kind, context_id: str = Path(min_length=1, max_length=36),
             view: str = "auto", db: Session = Depends(get_db),
             relyqo_session: str | None = Cookie(default=None)):
        user = authorize(db, relyqo_session, kind, context_id, view)
        message = body.message.strip()
        if not message:
            raise HTTPException(422, "Введите текст черновика")
        if limited(db, "request-draft-write", user.id, 120):
            raise HTTPException(429, "Слишком много изменений. Попробуйте позже.")
        # Recheck access after the limiter's transaction and serialize per-account quota.
        db.scalar(select(User).where(User.id == user.id).with_for_update())
        user = authorize(db, relyqo_session, kind, context_id, view)
        key = draft_key(user.id, kind, context_id)
        if body.version == 0:
            if db.get(RequestDraft, (user.id, kind, context_id)):
                raise HTTPException(409, CONFLICT)
            if db.scalar(select(func.count()).select_from(RequestDraft).where(RequestDraft.user_id == user.id)) >= 20:
                raise HTTPException(409, "Сохранено 20 черновиков. Удалите ненужный черновик.")
            db.add(RequestDraft(user_id=user.id, kind=kind, context_id=context_id,
                                body=message, version=1))
        else:
            changed = db.execute(update(RequestDraft).where(*key, RequestDraft.version == body.version)
                                 .values(body=message, version=body.version + 1, updated_at=datetime.utcnow()))
            if changed.rowcount != 1:
                db.rollback()
                raise HTTPException(409, CONFLICT)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, CONFLICT)
        db.expire_all()
        return payload(db.get(RequestDraft, (user.id, kind, context_id)))

    @api.post("/{kind}/{context_id}/remove")
    def remove(body: DraftDelete, kind: Kind, context_id: str = Path(min_length=1, max_length=36),
               view: str = "auto", db: Session = Depends(get_db),
               relyqo_session: str | None = Cookie(default=None)):
        user = authorize(db, relyqo_session, kind, context_id, view)
        changed = db.execute(delete(RequestDraft).where(*draft_key(user.id, kind, context_id),
                                                       RequestDraft.version == body.version))
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, CONFLICT)
        db.commit()
        return {"draft": None}

    app.include_router(api)
