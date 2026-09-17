"""Private operational status, encrypted manual backups and incident notifications."""

from datetime import datetime, timedelta
import logging
from fastapi import Cookie, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from .backups import create_snapshot
from .config import settings
from .db import get_db, SessionLocal
from .models import ConsumerEmail, MailDelivery, OperationsEvent, User
from .password_recovery import limited, send_email
from .security import verify_password

logger = logging.getLogger(__name__)


def report_incident(kind="APPLICATION_ERROR"):
    """Only a generic incident label is mailed; never include requests, credentials or customer data."""
    try:
        with SessionLocal() as db:
            if limited(db, "incident-notification", kind, 1):
                return
            db.add(
                OperationsEvent(
                    kind=kind,
                    status="FAILED",
                    details="A server error occurred. Inspect protected service logs.",
                )
            )
            db.commit()
            if not settings.resend_api_key or not settings.recovery_email_from:
                return
            recipients = db.scalars(
                select(ConsumerEmail.email)
                .join(User, User.id == ConsumerEmail.user_id)
                .where(User.role == "RELYQO_ADMIN", User.active.is_(True))
            ).all()
            for email in recipients:
                send_email(
                    email,
                    "RELYQO: сбой / nosozlik",
                    "RELYQO: зафиксирована серверная ошибка. Проверьте раздел «Состояние системы» в админке.\n\nRELYQO: server xatosi qayd etildi. Administrator panelidagi tizim holatini tekshiring.",
                )
    except Exception:
        logger.error("Could not persist or deliver operational alert")


class BackupRequest(BaseModel):
    current_password: str = Field(min_length=8, max_length=200)
    passphrase: str = Field(min_length=16, max_length=200)
    confirm_passphrase: str = Field(min_length=16, max_length=200)


def register_operations_routes(app, session_user):
    @app.middleware("http")
    async def incident_monitor(request, call_next):
        try:
            response = await call_next(request)
        except Exception:
            # Do not run email synchronously in an exception path.
            import asyncio

            await asyncio.to_thread(report_incident)
            raise
        if response.status_code >= 500 and request.url.path.startswith("/v1/"):
            # Appending preserves BackgroundTasks installed by the endpoint.
            from starlette.background import BackgroundTasks as Tasks

            tasks = Tasks()
            if response.background:
                tasks.add_task(response.background)
            tasks.add_task(report_incident)
            response.background = tasks
        return response

    @app.get("/v1/admin/operations")
    def status(
        response: Response,
        relyqo_session: str | None = Cookie(default=None),
        db: Session = Depends(get_db),
    ):
        user = session_user(relyqo_session, db, "RELYQO_ADMIN")
        db.execute(text("SELECT 1"))
        latest = db.scalars(
            select(OperationsEvent)
            .order_by(OperationsEvent.created_at.desc())
            .limit(20)
        ).all()
        mail = db.execute(
            select(MailDelivery.status, func.count())
            .where(MailDelivery.created_at >= datetime.utcnow() - timedelta(days=7))
            .group_by(MailDelivery.status)
        ).all()
        recovery = db.get(ConsumerEmail, user.id)
        response.headers["Cache-Control"] = "no-store"
        return {
            "database": "ok",
            "mail_configured": bool(
                settings.resend_api_key and settings.recovery_email_from
            ),
            "admin_email_verified": bool(recovery),
            "mail_last_7_days": dict(mail),
            "mail_status_note": "ACCEPTED означает принятие провайдером, а не подтверждение доставки.",
            "automatic_backups": settings.automatic_backup_status,
            "database_expires_at": settings.database_expires_at or None,
            "monitoring": "Ошибки API: письмо на подтверждённую почту администратора, не чаще раза в час. Недоступность всего сайта: отдельная проверка GitHub Actions.",
            "events": [
                {
                    "kind": r.kind,
                    "status": r.status,
                    "details": r.details,
                    "created_at": r.created_at,
                }
                for r in latest
            ],
        }

    @app.post("/v1/admin/backups/export")
    def export(
        body: BackupRequest,
        relyqo_session: str | None = Cookie(default=None),
        db: Session = Depends(get_db),
    ):
        user = session_user(relyqo_session, db, "RELYQO_ADMIN")
        if limited(db, "backup-user", user.id, 3):
            raise HTTPException(429, "Не более трёх копий в час")
        if not verify_password(body.current_password, user.password_hash):
            raise HTTPException(401, "Текущий пароль указан неверно")
        if body.passphrase != body.confirm_passphrase:
            raise HTTPException(422, "Пароли резервной копии не совпадают")
        try:
            raw = create_snapshot(db.get_bind(), body.passphrase)
        except ValueError:
            raise HTTPException(
                413, "Для базы этого размера используйте резервную копию через pg_dump"
            )
        db.add(
            OperationsEvent(
                kind="MANUAL_BACKUP",
                status="EXPORTED",
                details="Encrypted snapshot created; save the downloaded file outside Render.",
            )
        )
        db.commit()
        name = "relyqo-" + datetime.utcnow().strftime("%Y%m%d-%H%M%S") + ".rqbackup"
        return Response(
            raw,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{name}"',
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )
