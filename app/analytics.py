"""Read-only administrator analytics; all numbers are computed by SQL."""

from datetime import date, datetime, time, timedelta
import json
from pathlib import Path
from threading import Lock
from typing import Literal

from fastapi import Cookie, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse
from sqlalchemy import and_, case, distinct, func, literal, select, union_all
from sqlalchemy.orm import Session

from .ai import AIServiceError, AIUnavailableError, generate_admin_analytics
from .categories import category_catalog
from .config import settings
from .db import get_db
from .models import Branch, CommunityRating, ManualPlace, Organization, Rating, Visit
from .security import token_hash

_lock = Lock()
_cache = {}
_last_request = {}
_busy = set()


class AnalyticsFilter:
    def __init__(
        self,
        start: date | None = None,
        end: date | None = None,
        source: Literal["verified", "community"] = "verified",
        category: str | None = Query(default=None, max_length=40),
        entity: str | None = Query(default=None, max_length=80),
    ):
        self.end = end or datetime.utcnow().date()
        self.start = start or self.end - timedelta(days=29)
        if not 0 <= (self.end - self.start).days < 366:
            raise HTTPException(422, "Выберите период от 1 до 366 дней")
        self.source, self.category, self.entity = source, category, entity

    @property
    def bounds(self):
        return datetime.combine(self.start, time.min), datetime.combine(
            self.end + timedelta(days=1), time.min
        )


def entities():
    return union_all(
        select(
            (literal("org:") + Organization.id).label("key"),
            Organization.name.label("name"),
            Organization.category.label("category"),
            literal("organization").label("kind"),
        ),
        select(
            (literal("manual:") + ManualPlace.id).label("key"),
            ManualPlace.name,
            ManualPlace.category,
            literal("manual"),
        ),
    ).subquery()


def feedback(source):
    if source == "verified":
        return select(
            Rating.id,
            (literal("org:") + Rating.organization_id).label("entity"),
            Rating.consumer_user_id.label("consumer"),
            Rating.created_at,
            Rating.overall,
            Rating.food.label("quality"),
            Rating.service,
            Rating.cleanliness,
            Rating.value,
            and_(Rating.included.is_(True), Rating.trust_weight > 0).label("eligible"),
        ).subquery()
    # Partner community keys identify branches, while reports group all branches of an organization.
    return (
        select(
            CommunityRating.id,
            case(
                (Branch.id.is_not(None), literal("org:") + Branch.organization_id),
                else_=CommunityRating.object_key,
            ).label("entity"),
            CommunityRating.consumer_user_id.label("consumer"),
            CommunityRating.created_at,
            CommunityRating.overall,
            CommunityRating.quality,
            CommunityRating.service,
            CommunityRating.cleanliness,
            CommunityRating.value,
            literal(True).label("eligible"),
        )
        .outerjoin(Branch, CommunityRating.object_key == literal("relyqo:") + Branch.id)
        .subquery()
    )


def aggregate_columns(f):
    valid = f.c.eligible.is_(True)

    def count_if(condition, name):
        return func.coalesce(func.sum(case((condition, 1), else_=0)), 0).label(name)

    return [
        func.count(f.c.id).label("submitted"),
        count_if(valid, "included"),
        func.count(distinct(case((valid, f.c.consumer)))).label("respondents"),
        count_if(and_(valid, f.c.consumer.is_(None)), "anonymous"),
        count_if(and_(valid, f.c.overall >= 8), "satisfied"),
        count_if(and_(valid, f.c.overall.between(5, 7)), "neutral"),
        count_if(and_(valid, f.c.overall <= 4), "dissatisfied"),
        *[
            func.avg(case((valid, getattr(f.c, key)))).label(key)
            for key in ["overall", "quality", "service", "cleanliness", "value"]
        ],
    ]


def metric_payload(row):
    row = dict(row or {})
    counts = {
        key: int(row.get(key) or 0)
        for key in [
            "submitted",
            "included",
            "respondents",
            "anonymous",
            "satisfied",
            "neutral",
            "dissatisfied",
        ]
    }
    counts["excluded"] = counts["submitted"] - counts["included"]
    counts["satisfied_percent"] = (
        round(100 * counts["satisfied"] / counts["included"], 1)
        if counts["included"]
        else None
    )
    counts["dimensions"] = {
        key: round(float(row[key]), 2) if row.get(key) is not None else None
        for key in ["overall", "quality", "service", "cleanliness", "value"]
    }
    return counts


def build_report(db, filters):
    catalog = category_catalog(db)
    labels = {item["code"]: item["label"] for item in catalog}
    if filters.category and filters.category not in labels:
        raise HTTPException(422, "Неизвестная категория")
    e, f = entities(), feedback(filters.source)
    conditions = []
    if filters.category:
        conditions.append(e.c.category == filters.category)
    if filters.entity:
        conditions.append(e.c.key == filters.entity)
    directory = (
        db.execute(select(e).where(*conditions).order_by(e.c.name, e.c.key))
        .mappings()
        .all()
    )
    if filters.entity and not directory:
        raise HTTPException(404, "Организация не найдена в выбранной категории")
    start, stop = filters.bounds
    conditions += [f.c.created_at >= start, f.c.created_at < stop]
    joined = f.join(e, f.c.entity == e.c.key)
    columns = aggregate_columns(f)
    summary = metric_payload(
        db.execute(select(*columns).select_from(joined).where(*conditions))
        .mappings()
        .one()
    )
    grouped = (
        db.execute(
            select(e.c.key, *columns)
            .select_from(joined)
            .where(*conditions)
            .group_by(e.c.key)
        )
        .mappings()
        .all()
    )
    by_entity = {row["key"]: metric_payload(row) for row in grouped}
    sectors = (
        db.execute(
            select(e.c.category, *columns)
            .select_from(joined)
            .where(*conditions)
            .group_by(e.c.category)
        )
        .mappings()
        .all()
    )
    daily = (
        db.execute(
            select(func.date(f.c.created_at).label("day"), *columns)
            .select_from(joined)
            .where(*conditions)
            .group_by(func.date(f.c.created_at))
        )
        .mappings()
        .all()
    )
    by_day = {str(row["day"]): metric_payload(row) for row in daily}
    visit_counts, visit_days = {}, {}
    if filters.source == "verified":
        visit_base = (
            select(
                Visit.id,
                Visit.verified_at,
                (literal("org:") + Branch.organization_id).label("entity"),
            )
            .join(Branch, Visit.branch_id == Branch.id)
            .subquery()
        )
        visits_joined = visit_base.join(e, visit_base.c.entity == e.c.key)
        where = [visit_base.c.verified_at >= start, visit_base.c.verified_at < stop]
        if filters.category:
            where.append(e.c.category == filters.category)
        if filters.entity:
            where.append(e.c.key == filters.entity)
        visit_counts = dict(
            db.execute(
                select(e.c.key, func.count())
                .select_from(visits_joined)
                .where(*where)
                .group_by(e.c.key)
            ).all()
        )
        visit_days = {
            str(day): count
            for day, count in db.execute(
                select(func.date(visit_base.c.verified_at), func.count())
                .select_from(visits_joined)
                .where(*where)
                .group_by(func.date(visit_base.c.verified_at))
            )
        }
    summary["verified_visits"] = (
        sum(visit_counts.values()) if filters.source == "verified" else None
    )
    organizations = [
        {
            **dict(row),
            "category_label": labels.get(row["category"], row["category"]),
            **by_entity.get(row["key"], metric_payload(None)),
            "verified_visits": visit_counts.get(row["key"], 0)
            if filters.source == "verified"
            else None,
        }
        for row in directory
    ]
    organizations.sort(
        key=lambda row: (
            -row["included"],
            -int(row["verified_visits"] or 0),
            row["name"],
            row["key"],
        )
    )
    summary["organizations_with_feedback"] = sum(
        row["included"] > 0 for row in organizations
    )
    trend = []
    for n in range((filters.end - filters.start).days + 1):
        day = (filters.start + timedelta(days=n)).isoformat()
        trend.append(
            {
                "date": day,
                **by_day.get(day, metric_payload(None)),
                "verified_visits": visit_days.get(day, 0)
                if filters.source == "verified"
                else None,
            }
        )
    return {
        "period": {
            "start": str(filters.start),
            "end": str(filters.end),
            "timezone": "UTC",
        },
        "filters": {
            "source": filters.source,
            "category": filters.category,
            "entity": filters.entity,
        },
        "summary": summary,
        "organizations": organizations,
        "categories": [
            {
                "code": row["category"],
                "label": labels.get(row["category"], row["category"]),
                **metric_payload(row),
            }
            for row in sectors
        ],
        "trend": trend,
        "methodology": {
            "satisfied": "8–10 из 10",
            "neutral": "5–7 из 10",
            "dissatisfied": "1–4 из 10",
            "basis": "Общая оценка потребителя; доли считаются по учтённым оценкам, а не по всем посетителям.",
            "respondents": "Уникальные аккаунты, оставившие учтённые оценки в выбранном периоде. Безымянные оценки не превращаются в уникальных людей.",
            "visits": "Только посещения, подтверждённые через RELYQO. Это не весь поток клиентов организации.",
            "sources": "Подтверждённые и Community-оценки показаны раздельно. Оценки на проверке и исключённые оценки не входят в удовлетворённость.",
        },
        "ai": {"configured": bool(settings.openai_api_key), "affects_ratings": False},
    }


def ai_context(report):
    # No consumer identifiers, email, phone, passwords, photos, or raw activity history.
    def public_metrics(row):
        return {
            key: value
            for key, value in row.items()
            if key not in {"key", "code", "kind", "category"}
        }

    weeks = {}
    for day in report["trend"]:
        value = date.fromisoformat(day["date"])
        key = (value - timedelta(days=value.weekday())).isoformat()
        week = weeks.setdefault(
            key,
            {
                "week_start": key,
                "observed_days": 0,
                "included": 0,
                "satisfied": 0,
                "verified_visits": 0 if day["verified_visits"] is not None else None,
            },
        )
        week["observed_days"] += 1
        week["included"] += day["included"]
        week["satisfied"] += day["satisfied"]
        if week["verified_visits"] is not None:
            week["verified_visits"] += day["verified_visits"]
    return {
        "period": report["period"],
        "source": report["filters"]["source"],
        "weekly_trend": list(weeks.values()),
        "summary": report["summary"],
        "methodology": report["methodology"],
        "categories": [public_metrics(row) for row in report["categories"][:30]],
        "organizations": [
            public_metrics(row) for row in report["organizations"] if row["included"]
        ][:20],
        "organization_details_limit": 20,
        "organization_count": len(report["organizations"]),
    }


def register_analytics_routes(app, session_user):
    @app.get("/admin/analytics", include_in_schema=False)
    def page():
        # The shell contains no statistics. Every data/AI endpoint below authenticates the administrator.
        return FileResponse(
            Path(__file__).parent / "static" / "admin-analytics.html",
            headers={
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Frame-Options": "DENY",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'",
            },
        )

    @app.get("/v1/admin/analytics")
    def report(
        response: Response,
        filters: AnalyticsFilter = Depends(),
        relyqo_session: str | None = Cookie(default=None),
        db: Session = Depends(get_db),
    ):
        session_user(relyqo_session, db, "RELYQO_ADMIN")
        response.headers["Cache-Control"] = "no-store, max-age=0"
        return build_report(db, filters)

    @app.post("/v1/admin/analytics/insights")
    def insights(
        response: Response,
        filters: AnalyticsFilter = Depends(),
        relyqo_session: str | None = Cookie(default=None),
        db: Session = Depends(get_db),
    ):
        user = session_user(relyqo_session, db, "RELYQO_ADMIN")
        response.headers["Cache-Control"] = "no-store, max-age=0"
        if not settings.openai_api_key:
            raise HTTPException(
                503, "ИИ-анализ пока не подключён. Статистика доступна."
            )
        report = build_report(db, filters)
        if not report["summary"]["included"]:
            raise HTTPException(422, "Для анализа нужны оценки за выбранный период")
        payload = ai_context(report)
        signature = token_hash(
            settings.openai_model
            + json.dumps(payload, ensure_ascii=False, sort_keys=True)
        )
        now = datetime.utcnow()
        with _lock:
            cached = _cache.get(signature)
            if cached and cached["until"] > now:
                return {**cached["result"], "cached": True}
            if signature in _busy or _last_request.get(
                user.id, datetime.min
            ) > now - timedelta(seconds=60):
                raise HTTPException(
                    429,
                    "Следующий ИИ-анализ доступен через минуту",
                    headers={"Retry-After": "60"},
                )
            _last_request[user.id] = now
            _busy.add(signature)
        try:
            analysis = generate_admin_analytics(payload)
        except (AIServiceError, AIUnavailableError) as exc:
            raise HTTPException(
                502,
                "ИИ временно недоступен. Все расчёты статистики продолжают работать.",
            ) from exc
        finally:
            with _lock:
                _busy.discard(signature)
        result = {
            "analysis": analysis,
            "generated_at": now.isoformat() + "Z",
            "cached": False,
        }
        with _lock:
            if len(_cache) >= 64:
                _cache.clear()
            _cache[signature] = {"result": result, "until": now + timedelta(minutes=15)}
        return result
