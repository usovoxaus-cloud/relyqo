"""Revocable export-only clients for daily backups on the owner's Windows computer."""

from datetime import datetime, timedelta
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import secrets
from zipfile import ZIP_DEFLATED, ZipFile
from fastapi import Cookie, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from .backups import create_snapshot
from .config import settings
from .db import get_db
from .models import BackupAgent, OperationsEvent, User
from .password_recovery import limited
from .security import token_hash, verify_password


class SetupRequest(BaseModel):
    current_password: str = Field(min_length=8, max_length=200)


class ExportRequest(BaseModel):
    passphrase: str = Field(min_length=16, max_length=200)


class ReceiptRequest(BaseModel):
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def valid_agent(agent, user):
    return bool(
        agent
        and user
        and user.active
        and user.role == "RELYQO_ADMIN"
        and agent.revoked_at is None
        and agent.expires_at > datetime.utcnow()
        and secrets.compare_digest(
            agent.password_fingerprint, token_hash(user.password_hash)
        )
    )


def backup_client_status(db, user):
    agent = db.scalar(
        select(BackupAgent)
        .where(BackupAgent.user_id == user.id)
        .order_by(BackupAgent.created_at.desc())
        .limit(1)
    )
    status = "not_configured"
    if agent:
        status = "disabled" if not valid_agent(agent, user) else "awaiting_first_backup"
        if valid_agent(agent, user) and agent.last_saved_at:
            status = (
                "recent"
                if agent.last_saved_at >= datetime.utcnow() - timedelta(hours=36)
                else "overdue"
            )
    return {
        "status": status,
        "last_saved_at": agent.last_saved_at if agent else None,
        "expires_at": agent.expires_at if agent else None,
        "note": "Копирование работает, когда компьютер включён и выполнен вход в Windows. Сохранение подтверждает программа на компьютере; восстановление проверяется отдельно.",
    }


def authenticate(db, authorization):
    prefix, _, raw = (authorization or "").partition(" ")
    if prefix != "Bearer" or not raw.startswith("rqbackup_") or len(raw) > 160:
        raise HTTPException(401, "Ключ резервного копирования недействителен")
    agent = db.scalar(
        select(BackupAgent).where(BackupAgent.token_hash == token_hash(raw))
    )
    user = db.get(User, agent.user_id) if agent else None
    if not valid_agent(agent, user):
        raise HTTPException(401, "Ключ резервного копирования недействителен")
    return agent, user


def register_scheduled_backups(app, session_user):
    @app.post("/v1/admin/backups/client", status_code=201)
    def setup(
        body: SetupRequest,
        response: Response,
        relyqo_session: str | None = Cookie(default=None),
        db: Session = Depends(get_db),
    ):
        user = session_user(relyqo_session, db, "RELYQO_ADMIN")
        if limited(db, "backup-client-setup", user.id, 3):
            raise HTTPException(429, "Не более трёх попыток в час")
        if not verify_password(body.current_password, user.password_hash):
            raise HTTPException(401, "Текущий пароль указан неверно")
        db.scalar(select(User).where(User.id == user.id).with_for_update())
        now = datetime.utcnow()
        for previous in db.scalars(
            select(BackupAgent).where(
                BackupAgent.user_id == user.id, BackupAgent.revoked_at.is_(None)
            )
        ):
            previous.revoked_at = now
        raw = "rqbackup_" + secrets.token_urlsafe(40)
        agent = BackupAgent(
            user_id=user.id,
            token_hash=token_hash(raw),
            password_fingerprint=token_hash(user.password_hash),
            expires_at=now + timedelta(days=180),
        )
        db.add(agent)
        db.add(
            OperationsEvent(
                kind="BACKUP_CLIENT",
                status="CREATED",
                details="Export-only key issued. Waiting for a saved-file receipt.",
            )
        )
        db.commit()
        response.headers["Cache-Control"] = "no-store"
        return {
            "token": raw,
            "expires_at": agent.expires_at,
            "status": "awaiting_first_backup",
        }

    @app.post("/v1/admin/backups/client/revoke")
    def revoke(
        response: Response,
        relyqo_session: str | None = Cookie(default=None),
        db: Session = Depends(get_db),
    ):
        user = session_user(relyqo_session, db, "RELYQO_ADMIN")
        db.scalar(select(User).where(User.id == user.id).with_for_update())
        for agent in db.scalars(
            select(BackupAgent).where(
                BackupAgent.user_id == user.id, BackupAgent.revoked_at.is_(None)
            )
        ):
            agent.revoked_at = datetime.utcnow()
        db.add(
            OperationsEvent(
                kind="BACKUP_CLIENT",
                status="REVOKED",
                details="Export-only keys revoked.",
            )
        )
        db.commit()
        response.headers["Cache-Control"] = "no-store"
        return {"ok": True}

    @app.get("/v1/admin/backups/windows.zip")
    def client(
        relyqo_session: str | None = Cookie(default=None), db: Session = Depends(get_db)
    ):
        session_user(relyqo_session, db, "RELYQO_ADMIN")
        output = BytesIO()
        with ZipFile(output, "w", ZIP_DEFLATED) as archive:
            for path in sorted((Path(__file__).parent / "backup-client").iterdir()):
                archive.write(path, path.name)
            archive.writestr(
                "server.json",
                json.dumps({"base_url": settings.public_base_url}, ensure_ascii=False),
            )
        return Response(
            output.getvalue(),
            media_type="application/zip",
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": 'attachment; filename="RELYQO-Windows-backup.zip"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.post("/v1/backup-client/export")
    def export(
        body: ExportRequest,
        authorization: str | None = Header(default=None),
        db: Session = Depends(get_db),
    ):
        agent, user = authenticate(db, authorization)
        if limited(db, "backup-user", user.id, 3):
            raise HTTPException(429, "Не более трёх копий в час")
        # Recheck after the rate-limit commit, and serialize exports/receipts for this key.
        agent = db.scalar(
            select(BackupAgent)
            .where(BackupAgent.id == agent.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if not valid_agent(agent, user):
            raise HTTPException(401, "Ключ резервного копирования недействителен")
        try:
            raw = create_snapshot(db.get_bind(), body.passphrase)
        except ValueError:
            raise HTTPException(
                413, "Для базы этого размера используйте резервную копию через pg_dump"
            )
        agent.last_export_at, agent.latest_digest = (
            datetime.utcnow(),
            sha256(raw).hexdigest(),
        )
        db.commit()
        return Response(
            raw,
            media_type="application/octet-stream",
            headers={
                "Cache-Control": "no-store",
                "X-Backup-SHA256": agent.latest_digest,
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.post("/v1/backup-client/receipt")
    def receipt(
        body: ReceiptRequest,
        response: Response,
        authorization: str | None = Header(default=None),
        db: Session = Depends(get_db),
    ):
        agent, _ = authenticate(db, authorization)
        agent = db.scalar(
            select(BackupAgent)
            .where(BackupAgent.id == agent.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if not agent.latest_digest or not secrets.compare_digest(
            agent.latest_digest, body.sha256
        ):
            raise HTTPException(409, "Подтверждение не соответствует последней копии")
        if agent.last_saved_at != agent.last_export_at:
            agent.last_saved_at = agent.last_export_at
            db.add(
                OperationsEvent(
                    kind="LOCAL_BACKUP",
                    status="SAVED",
                    details="Windows client confirmed an atomic local write and matching SHA-256. Restore drill is separate.",
                )
            )
            db.commit()
        response.headers["Cache-Control"] = "no-store"
        return {"ok": True, "last_saved_at": agent.last_saved_at}
