"""Opt-in, verified-address notifications. Queue contains no message text or location."""
from datetime import datetime, timedelta
import logging
from threading import Event, Thread
from urllib.error import HTTPError

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel, StrictBool
from sqlalchemy import select, update

from .db import SessionLocal, get_db
from .models import (ConsumerEmail, MailDelivery, RequestEmailJob, RequestEmailPreference,
                     ServiceRepresentative, ServiceRequest, ServiceRequestRead, User)
from .password_recovery import require_mail_configuration, recovery_origin, send_email
from .security import token_hash
from .web_ui import consumer_html
from .consumer_entry import require_account_page

log = logging.getLogger(__name__)
wake = Event()


def configured():
    try:
        require_mail_configuration()
        return True
    except HTTPException:
        return False


def queue_request_notifications(db, item, actor_id):
    """Call in the same transaction as the event; never subscribe anyone implicitly."""
    from .service_requests import OWNERS, scope
    if item.status == "WITHDRAWN":
        return
    recipients = {item.consumer_user_id: "consumer"}
    representatives = db.scalars(select(ServiceRepresentative.user_id).where(
        ServiceRepresentative.object_key == item.object_key))
    for user_id in representatives:
        if user_id != item.consumer_user_id:
            recipients[user_id] = "business"
    if item.organization_id:
        for user_id in db.scalars(select(User.id).where(User.organization_id == item.organization_id, User.role.in_(OWNERS))):
            if user_id != item.consumer_user_id:
                recipients[user_id] = "business"
    if db.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    for user_id, view in recipients.items():
        user, pref, email = db.get(User, user_id), db.get(RequestEmailPreference, user_id), db.get(ConsumerEmail, user_id)
        if user_id == actor_id or not user or not user.active or not pref or not pref.enabled or not email:
            continue
        if pref.email_hash != token_hash(email.email):
            continue
        try:
            allowed = db.scalar(scope(select(ServiceRequest.id), user, db, view).where(ServiceRequest.id == item.id))
        except HTTPException:
            continue
        if not allowed:
            continue
        try:
            origin = recovery_origin()
        except ValueError:
            log.error("Request notification origin is not configured")
            continue
        db.execute(insert(RequestEmailJob).values(user_id=user_id, request_id=item.id,
            version=item.version, view=view, email_hash=pref.email_hash, language=user.language,
            origin=origin).on_conflict_do_nothing(index_elements=["user_id", "request_id", "version"]))


def eligible_recipient(db, job):
    from .service_requests import scope
    user, pref, email = db.get(User, job.user_id), db.get(RequestEmailPreference, job.user_id), db.get(ConsumerEmail, job.user_id)
    if not user or not user.active or not pref or not pref.enabled or not email:
        return None
    if token_hash(email.email) != job.email_hash or pref.email_hash != job.email_hash:
        return None
    read = db.get(ServiceRequestRead, (job.user_id, job.request_id))
    if read and read.version >= job.version:
        return None
    try:
        item = db.scalar(scope(select(ServiceRequest), user, db, job.view).where(ServiceRequest.id == job.request_id))
    except HTTPException:
        return None
    if not item or item.status == "WITHDRAWN":
        return None
    return email.email


def email_content(job):
    # Freeze these fields when queuing: every retry with the same key has the same payload.
    prefix = "/me" if job.view == "consumer" else "/business"
    link = f"{job.origin}{prefix}/requests?id={job.request_id}&lang={job.language}"
    settings_link = f"{job.origin}/notifications?lang={job.language}"
    if job.language == "uz":
        return ("RELYQO: murojaatda yangilik bor",
            f"Murojaatingizda yangi xabar yoki holat o‘zgarishi bor. Hisobingizga kirib ko‘ring:\n{link}\n\n"
            f"Siz email bildirishnomalarini yoqqansiz. O‘chirish yoki sozlash:\n{settings_link}")
    return ("RELYQO: обновление обращения",
        f"В обращении появилось сообщение или изменился статус. Войдите в свой аккаунт, чтобы посмотреть:\n{link}\n\n"
        f"Вы включили уведомления по email. Отключить или изменить настройки:\n{settings_link}")


def drain_notifications(factory=None, limit=10):
    """Durable retry with an atomic lease. Retries finish before Resend's 24-hour key expiry."""
    if not configured():
        return
    factory = factory or SessionLocal
    for _ in range(limit):
        now = datetime.utcnow()
        with factory() as db:
            due = (RequestEmailJob.status.in_(["PENDING", "PROCESSING"])) & (RequestEmailJob.next_attempt_at <= now)
            job = db.scalar(select(RequestEmailJob).where(due).order_by(RequestEmailJob.created_at, RequestEmailJob.id).limit(1))
            if not job:
                return
            job_id, attempts = job.id, job.attempts + 1
            claimed = db.execute(update(RequestEmailJob).where(RequestEmailJob.id == job_id, due).values(
                status="PROCESSING", attempts=attempts, first_attempt_at=job.first_attempt_at or now,
                next_attempt_at=now + timedelta(minutes=2)),
                execution_options={"synchronize_session": False})
            db.commit()
            if claimed.rowcount != 1:
                continue
            db.refresh(job)
            address = eligible_recipient(db, job)
            if not address or job.first_attempt_at <= now - timedelta(hours=22) or attempts > 5:
                job.status = "CANCELLED" if not address else "FAILED"
                db.commit()
                continue
            subject, body = email_content(job)
            try:
                provider = send_email(address, subject, body, idempotency_key="request-event/" + job.id)
                values = {"status": "ACCEPTED", "provider_id": str(provider)[:100]}
            except Exception as error:
                permanent = isinstance(error, HTTPError) and 400 <= error.code < 500 and error.code != 429
                values = {"status": "FAILED" if permanent or attempts >= 5 else "PENDING",
                          "next_attempt_at": now + timedelta(seconds=60 * 2 ** (attempts - 1))}
                log.warning("Request notification attempt failed; retryable=%s", values["status"] == "PENDING")
            saved = db.execute(update(RequestEmailJob).where(RequestEmailJob.id == job_id,
                RequestEmailJob.status == "PROCESSING", RequestEmailJob.attempts == attempts).values(**values))
            if saved.rowcount == 1 and values["status"] in {"ACCEPTED", "FAILED"}:
                db.add(MailDelivery(user_id=job.user_id, purpose="REQUEST_UPDATE",
                    status=values["status"], provider_id=values.get("provider_id")))
            db.commit()


class PreferenceChange(BaseModel):
    enabled: StrictBool
    consent: StrictBool = False


def register_request_notifications(app, session_user):
    stop = Event()
    def run_worker():
        while not stop.is_set():
            try:
                drain_notifications()
            except Exception:
                log.error("Request notification queue temporarily unavailable")
            wake.wait(30)
            wake.clear()

    @app.on_event("startup")
    def start():
        stop.clear()
        app.state.request_email_worker = Thread(target=run_worker, name="request-email", daemon=True)
        app.state.request_email_worker.start()

    @app.on_event("shutdown")
    def shutdown():
        stop.set()
        wake.set()
        app.state.request_email_worker.join(timeout=1)

    def private(response: Response):
        response.headers["Cache-Control"] = "private, no-store"
    router = APIRouter(dependencies=[Depends(private)])

    def state(db, user):
        email, pref = db.get(ConsumerEmail, user.id), db.get(RequestEmailPreference, user.id)
        enabled = bool(email and pref and pref.enabled and pref.email_hash == token_hash(email.email))
        return {"enabled": enabled, "verified": bool(email), "email": email.email if email else None,
                "available": configured()}

    @router.get("/v1/notifications/preferences")
    def preferences(db=Depends(get_db), relyqo_session: str | None = Cookie(default=None)):
        user = session_user(relyqo_session, db, {"CONSUMER", "BUSINESS_OWNER", "FREGAT_OWNER"})
        return state(db, user)

    @router.post("/v1/notifications/preferences")
    def change(body: PreferenceChange, db=Depends(get_db), relyqo_session: str | None = Cookie(default=None)):
        user = session_user(relyqo_session, db, {"CONSUMER", "BUSINESS_OWNER", "FREGAT_OWNER"})
        email = db.get(ConsumerEmail, user.id)
        if body.enabled:
            if not body.consent:
                raise HTTPException(422, "Подтвердите согласие на уведомления по email")
            if not email:
                raise HTTPException(422, "Сначала подтвердите email в настройках аккаунта")
            require_mail_configuration()
        if db.bind.dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        values = {"enabled": body.enabled, "email_hash": token_hash(email.email) if body.enabled else None,
                  "updated_at": datetime.utcnow()}
        db.execute(insert(RequestEmailPreference).values(user_id=user.id, **values)
            .on_conflict_do_update(index_elements=["user_id"], set_=values))
        if not body.enabled:
            db.execute(update(RequestEmailJob).where(RequestEmailJob.user_id == user.id,
                RequestEmailJob.status.in_(["PENDING", "PROCESSING"])).values(status="CANCELLED"))
        db.commit()
        return state(db, user)

    @app.get("/notifications", include_in_schema=False, dependencies=[Depends(require_account_page)])
    def page():
        return consumer_html("notifications.html")

    app.include_router(router)
