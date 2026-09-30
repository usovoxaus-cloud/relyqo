"""Paginated organization registry for the platform administrator."""
from fastapi import Cookie, Depends, Query, Response
from sqlalchemy import func, or_, select

from .db import get_db
from .models import Branch, Organization


def register_admin_directory(app, session_user):
    @app.get("/v1/admin/organizations")
    def organizations(
        response: Response,
        q: str = Query(default="", max_length=160),
        offset: int = Query(default=0, ge=0, le=100000),
        relyqo_session: str | None = Cookie(default=None),
        db=Depends(get_db),
    ):
        session_user(relyqo_session, db, "RELYQO_ADMIN")
        response.headers["Cache-Control"] = "no-store, max-age=0"
        query = select(Organization)
        if q.strip():
            query = query.where(or_(
                Organization.name.contains(q.strip(), autoescape=True),
                Organization.city.contains(q.strip(), autoescape=True),
            ))
        total = db.scalar(select(func.count()).select_from(query.subquery()))
        rows = db.scalars(query.order_by(Organization.name, Organization.id).offset(offset).limit(50)).all()
        branches = {}
        if rows:
            for branch in db.scalars(select(Branch).where(Branch.organization_id.in_([row.id for row in rows])).order_by(Branch.name, Branch.id)):
                branches.setdefault(branch.organization_id, []).append({
                    "id": branch.id, "name": branch.name, "address": branch.address,
                    "city": branch.city, "active": branch.active,
                })
        return {
            "items": [{"id": row.id, "name": row.name, "city": row.city,
                       "category": row.category, "profile_status": row.profile_status,
                       "rating_count": row.rating_count, "score": row.score,
                       "branches": branches.get(row.id, [])} for row in rows],
            "total": total, "next_offset": offset + 50 if offset + 50 < total else None,
        }
