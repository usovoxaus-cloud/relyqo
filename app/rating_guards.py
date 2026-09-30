"""Database-backed rolling limits, shared by every application process."""
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from .models import RatingCooldown
from .security import token_hash


def reserve_rating_window(db, organization_id, browser_id, user_id=None):
    now = datetime.utcnow()
    identities = ["browser:" + browser_id]
    if user_id:
        identities.append("account:" + user_id)
    for identity in sorted(identities):
        key = token_hash(f"verified-rating:{organization_id}:{identity}")
        expires = now + timedelta(hours=24)
        updated = db.execute(update(RatingCooldown).where(
            RatingCooldown.key == key, RatingCooldown.expires_at <= now,
        ).values(expires_at=expires)).rowcount
        if updated:
            continue
        try:
            with db.begin_nested():
                db.add(RatingCooldown(key=key, expires_at=expires))
                db.flush()
        except IntegrityError:
            raise HTTPException(429, "Это заведение можно оценить по QR один раз за 24 часа.") from None
