"""Private actionable notifications and administrator-owned improvement experiments."""

from datetime import date, datetime, timedelta
import json
from typing import Literal
from fastapi import Cookie, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session
from .analytics import AnalyticsFilter, build_report, entities, feedback
from .db import get_db
from .models import (
    AdminNotificationRead,
    AuditLog,
    ImprovementAction,
    ModerationCase,
    Organization,
    User,
)


def today():
    return datetime.utcnow().date()


def notification_feed(db):
    items = []
    for row in db.scalars(
        select(ModerationCase)
        .where(ModerationCase.status == "PENDING")
        .order_by(ModerationCase.created_at.desc())
        .limit(100)
    ):
        label = {
            "COMPLAINT": "Новая жалоба",
            "APPEAL": "Новая апелляция",
            "SIGNAL": "Нужна проверка активности",
            "REVIEW": "Спорная оценка",
        }.get(row.kind, "Новое обращение")
        items.append(
            {
                "key": "case:" + row.id,
                "title": label,
                "kind": row.kind,
                "created_at": row.created_at.isoformat(),
                "href": "/admin/control#cases",
            }
        )
    for row in db.scalars(
        select(Organization)
        .where(Organization.profile_status == "SELF_REGISTERED")
        .order_by(Organization.created_at.desc())
        .limit(100)
    ):
        items.append(
            {
                "key": "application:" + row.id,
                "title": "Новая заявка организации",
                "organization": row.name,
                "kind": "APPLICATION",
                "created_at": row.created_at.isoformat(),
                "href": "/admin/control#applications",
            }
        )
    # Only completed UTC days, equal 7-day windows, separate rating sources.
    stop = datetime.combine(today(), datetime.min.time())
    split, start = stop - timedelta(days=7), stop - timedelta(days=14)
    for source in ("verified", "community"):
        e, f = entities(), feedback(source)
        rows = db.execute(
            select(
                e.c.key,
                e.c.name,
                func.sum(case((f.c.created_at >= split, 1), else_=0)).label(
                    "current_n"
                ),
                func.sum(case((f.c.created_at < split, 1), else_=0)).label(
                    "previous_n"
                ),
                func.sum(
                    case(((f.c.created_at >= split) & (f.c.overall <= 4), 1), else_=0)
                ).label("current_bad"),
                func.sum(
                    case(((f.c.created_at < split) & (f.c.overall <= 4), 1), else_=0)
                ).label("previous_bad"),
            )
            .select_from(f.join(e, f.c.entity == e.c.key))
            .where(
                f.c.eligible.is_(True), f.c.created_at >= start, f.c.created_at < stop
            )
            .group_by(e.c.key, e.c.name)
        ).mappings()
        for r in rows:
            if r["current_n"] < 10 or r["previous_n"] < 10 or r["current_bad"] < 3:
                continue
            before, after = (
                100 * r["previous_bad"] / r["previous_n"],
                100 * r["current_bad"] / r["current_n"],
            )
            if after - before < 20:
                continue
            from urllib.parse import urlencode

            query = urlencode(
                {
                    "source": source,
                    "entity": r["key"],
                    "start": split.date().isoformat(),
                    "end": (stop.date() - timedelta(days=1)).isoformat(),
                }
            )
            items.append(
                {
                    "key": f"risk:{today()}:{source}:{r['key']}",
                    "title": "Рост доли недовольных",
                    "organization": r["name"],
                    "kind": "SATISFACTION",
                    "created_at": stop.isoformat(),
                    "source": source,
                    "current_percent": round(after, 1),
                    "previous_percent": round(before, 1),
                    "current_count": r["current_n"],
                    "previous_count": r["previous_n"],
                    "href": "/admin/analytics?" + query,
                }
            )
    items.sort(key=lambda r: (r["created_at"], r["key"]), reverse=True)
    return items


class MarkRead(BaseModel):
    keys: list[str] = Field(max_length=100)


class CreateAction(BaseModel):
    title: str = Field(min_length=5, max_length=160)
    recommendation: str = Field(min_length=10, max_length=6000)
    start: date | None = None
    end: date | None = None
    source: Literal["verified", "community"] = "verified"
    category: str | None = Field(default=None, max_length=40)
    entity: str | None = Field(default=None, max_length=80)


class ChangeAction(BaseModel):
    status: Literal["OPEN", "IN_PROGRESS", "DONE", "DISMISSED"]
    note: str = Field(min_length=5, max_length=1200)
    version: int = Field(ge=1)


def action_payload(row):
    return {
        "id": row.id,
        "title": row.title,
        "recommendation": row.recommendation,
        "status": row.status,
        "note": row.note,
        "version": row.version,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "completed_at": row.completed_at,
        "filters": json.loads(row.filters_json),
        "baseline": json.loads(row.baseline_json),
    }


def register_admin_workflow(app, session_user):
    def admin(response, cookie, db):
        user = session_user(cookie, db, "RELYQO_ADMIN")
        response.headers["Cache-Control"] = "no-store"
        return user

    @app.get("/v1/admin/notifications")
    def notifications(
        response: Response,
        relyqo_session: str | None = Cookie(default=None),
        db: Session = Depends(get_db),
    ):
        user = admin(response, relyqo_session, db)
        items = notification_feed(db)
        keys = [r["key"] for r in items]
        read = (
            set(
                db.scalars(
                    select(AdminNotificationRead.event_key).where(
                        AdminNotificationRead.user_id == user.id,
                        AdminNotificationRead.event_key.in_(keys),
                    )
                )
            )
            if keys
            else set()
        )
        for item in items:
            item["read"] = item["key"] in read
        return {
            "items": items,
            "unread": sum(not r["read"] for r in items),
            "rule": "Сигнал недовольства: два периода по 7 полных дней, минимум 10 оценок в каждом, рост доли на 20 процентных пунктов и минимум 3 низкие оценки. Это повод для проверки, не доказательство ухудшения услуги.",
        }

    @app.post("/v1/admin/notifications/read")
    def read(
        body: MarkRead,
        response: Response,
        relyqo_session: str | None = Cookie(default=None),
        db: Session = Depends(get_db),
    ):
        user = admin(response, relyqo_session, db)
        allowed = {r["key"] for r in notification_feed(db)}
        if set(body.keys) - allowed:
            raise HTTPException(
                422, "Уведомление больше не актуально. Обновите список."
            )
        if db.bind.dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        for key in set(body.keys):
            db.execute(
                insert(AdminNotificationRead)
                .values(user_id=user.id, event_key=key, read_at=datetime.utcnow())
                .on_conflict_do_nothing()
            )
        db.commit()
        return {"ok": True}

    @app.get("/v1/admin/actions")
    def actions(
        response: Response,
        offset: int = Query(0, ge=0),
        relyqo_session: str | None = Cookie(default=None),
        db: Session = Depends(get_db),
    ):
        admin(response, relyqo_session, db)
        rows = db.scalars(
            select(ImprovementAction)
            .order_by(ImprovementAction.created_at.desc(), ImprovementAction.id)
            .offset(offset)
            .limit(25)
        ).all()
        return {
            "items": [action_payload(row) for row in rows],
            "next_offset": offset + 25 if len(rows) == 25 else None,
        }

    @app.post("/v1/admin/actions", status_code=201)
    def create(
        body: CreateAction,
        response: Response,
        relyqo_session: str | None = Cookie(default=None),
        db: Session = Depends(get_db),
    ):
        user = admin(response, relyqo_session, db)
        if len(body.title.strip()) < 5 or len(body.recommendation.strip()) < 10:
            raise HTTPException(422, "Укажите название и проверяемое действие")
        if body.end and body.end >= today():
            raise HTTPException(422, "Для исходного периода выберите завершённые дни")
        filters = AnalyticsFilter(
            start=body.start,
            end=body.end or today() - timedelta(days=1),
            source=body.source,
            category=body.category,
            entity=body.entity,
        )
        report = build_report(db, filters, comparison=False)
        if not report["summary"]["included"]:
            raise HTTPException(422, "Для исходного периода нужны учтённые оценки")
        row = ImprovementAction(
            title=body.title.strip(),
            recommendation=body.recommendation.strip(),
            filters_json=json.dumps({**report["period"], **report["filters"]}),
            baseline_json=json.dumps(report["summary"]),
            created_by=user.id,
            note="",
        )
        db.add(row)
        db.flush()
        db.add(
            AuditLog(
                actor_type=user.role,
                action="IMPROVEMENT_CREATED",
                entity_type="IMPROVEMENT",
                entity_id=row.id,
            )
        )
        db.commit()
        return action_payload(row)

    @app.post("/v1/admin/actions/{identifier}")
    def change(
        identifier: str,
        body: ChangeAction,
        response: Response,
        relyqo_session: str | None = Cookie(default=None),
        db: Session = Depends(get_db),
    ):
        user = admin(response, relyqo_session, db)
        row = db.scalar(
            select(ImprovementAction)
            .where(ImprovementAction.id == identifier)
            .with_for_update()
        )
        if not row:
            raise HTTPException(404, "Задача не найдена")
        if row.version != body.version:
            raise HTTPException(409, "Задача уже изменена. Обновите список.")
        if len(body.note.strip()) < 5:
            raise HTTPException(422, "Опишите выполненное действие")
        if row.status in ("DONE", "DISMISSED"):
            raise HTTPException(
                409, "Задача закрыта. Для нового эксперимента создайте новую задачу."
            )
        row.status, row.note, row.updated_at = (
            body.status,
            body.note.strip(),
            datetime.utcnow(),
        )
        row.version += 1
        if body.status == "DONE":
            row.completed_at = datetime.utcnow()
        from .models import ImprovementEvent

        db.add(
            ImprovementEvent(
                action_id=row.id, actor_id=user.id, status=row.status, note=row.note
            )
        )
        db.add(
            AuditLog(
                actor_type=user.role,
                action="IMPROVEMENT_" + row.status,
                entity_type="IMPROVEMENT",
                entity_id=row.id,
            )
        )
        db.commit()
        return action_payload(row)

    @app.get("/v1/admin/actions/{identifier}/result")
    def result(
        identifier: str,
        response: Response,
        relyqo_session: str | None = Cookie(default=None),
        db: Session = Depends(get_db),
    ):
        admin(response, relyqo_session, db)
        row = db.get(ImprovementAction, identifier)
        if not row:
            raise HTTPException(404, "Задача не найдена")
        from .models import ImprovementEvent

        history = [
            {
                "status": e.status,
                "note": e.note,
                "created_at": e.created_at,
                "actor": db.get(User, e.actor_id).username,
            }
            for e in db.scalars(
                select(ImprovementEvent)
                .where(ImprovementEvent.action_id == row.id)
                .order_by(ImprovementEvent.created_at)
            )
        ]
        payload = {
            "action": action_payload(row),
            "history": history,
            "after": None,
            "note": "Изменения показателей не доказывают эффект действия: состав авторов и условия могли измениться. Сравнивайте размер выборки и полные периоды.",
        }
        if not row.completed_at:
            return payload
        filters = json.loads(row.filters_json)
        days = (
            date.fromisoformat(filters["end"]) - date.fromisoformat(filters["start"])
        ).days + 1
        start = row.completed_at.date() + timedelta(days=1)
        expected_end = start + timedelta(days=days - 1)
        end = min(today() - timedelta(days=1), expected_end)
        payload["measurement"] = {
            "start": str(start),
            "expected_end": str(expected_end),
            "complete": end >= expected_end,
            "observed_days": max(0, (end - start).days + 1),
            "planned_days": days,
        }
        if end >= start:
            report = build_report(
                db,
                AnalyticsFilter(
                    start=start,
                    end=end,
                    source=filters["source"],
                    category=filters["category"],
                    entity=filters["entity"],
                ),
                comparison=False,
            )
            payload["after"] = {
                "period": report["period"],
                "summary": report["summary"],
            }
        return payload
