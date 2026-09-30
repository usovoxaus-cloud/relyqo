"""Public aggregate evidence only; never exposes a customer's identity or visit id."""
from fastapi import Depends, HTTPException, Response
from sqlalchemy import func, select

from .business import metric_labels
from .categories import BUILTINS
from .db import get_db
from .models import Branch, CommunityRating, ManualPlace, Organization, Rating, Visit

MINIMUM_RATINGS = 20


def timestamp(value):
    return value.isoformat() + "Z" if value else None


def organization_evidence(db):
    ratings = db.execute(select(Rating.organization_id, func.count(Rating.id),
                                func.max(Rating.created_at))
                         .where(Rating.included.is_(True)).group_by(Rating.organization_id)).all()
    visits = dict(db.execute(select(Branch.organization_id, func.count(Visit.id))
                            .join(Visit, Visit.branch_id == Branch.id)
                            .group_by(Branch.organization_id)).all())
    evidence = {key: {"verified_visit_count": count} for key, count in visits.items()}
    for key, count, latest in ratings:
        evidence.setdefault(key, {}).update(verified_rating_count=count,
                                            verified_last_rating_at=timestamp(latest))
    return evidence


def rating_confidence(count):
    return "ENOUGH_FOR_RANKING" if count >= MINIMUM_RATINGS else "EARLY" if count else "NO_RATINGS"


def register_public_profiles(app):
    @app.get("/v1/public/place")
    def public_profile(object_key: str, response: Response, db=Depends(get_db)):
        kind, _, identifier = object_key.partition(":")
        if kind == "relyqo":
            branch = db.get(Branch, identifier)
            org = db.get(Organization, branch.organization_id) if branch and branch.active else None
            if not org or org.profile_status not in {"PUBLISHED", "VERIFIED_PARTNER"}:
                raise HTTPException(404, "Организация не найдена")
            profile = {"name": org.name, "address": branch.address or branch.name,
                       "description": org.description, "category": org.category,
                       "source": "RELYQO_PARTNER", "profile_status": org.profile_status,
                       "relyqo_score": round(org.score, 1), "score_scope": "ORGANIZATION",
                       **organization_evidence(db).get(org.id, {})}
            fields = [Rating.food, Rating.service, Rating.cleanliness, Rating.value]
            averages = db.execute(select(*(func.avg(field) for field in fields)).where(
                Rating.organization_id == org.id, Rating.included.is_(True))).one()
            profile["verified_metrics"] = dict(zip(("quality", "service", "cleanliness", "value"),
                (round(float(v) * 10, 1) if v is not None else 0 for v in averages)))
            google_reference = branch
        elif kind == "manual":
            place = db.get(ManualPlace, identifier)
            if not place or not place.active:
                raise HTTPException(404, "Организация не найдена")
            profile = {"name": place.name, "address": place.address, "description": place.description,
                       "category": place.category, "source": "MANUAL", "profile_status": "COMMUNITY",
                       "relyqo_score": 0, "score_scope": "PLACE", "verified_metrics": {},
                       "source_url": place.source_url, "source_checked_at": timestamp(place.source_checked_at)}
            google_reference = place
        else:
            raise HTTPException(404, "Организация не найдена")
        count, score, latest, *metrics = db.execute(select(func.count(CommunityRating.id),
            func.avg(CommunityRating.community_score), func.max(CommunityRating.created_at),
            *(func.avg(field) for field in (CommunityRating.quality, CommunityRating.service,
                                         CommunityRating.cleanliness, CommunityRating.value)))
            .where(CommunityRating.object_key == object_key, CommunityRating.included.is_(True))).one()
        profile.update(object_key=object_key, community_rating_count=count,
                       community_score=round(float(score), 1) if score is not None else 0,
                       community_last_rating_at=timestamp(latest),
                       community_metrics=dict(zip(("quality", "service", "cleanliness", "value"),
                           (round(float(v) * 10, 1) if v is not None else 0 for v in metrics))))
        for field in ("verified_rating_count", "verified_visit_count"):
            profile.setdefault(field, 0)
        profile.setdefault("verified_last_rating_at", None)
        profile["category_label"] = BUILTINS.get(profile["category"], (profile["category"],))[0]
        labels = metric_labels(profile["category"], db)
        profile["metric_labels"] = {"quality": labels["food"], **{k: labels[k] for k in ("service", "cleanliness", "value")}}
        profile["minimum_ratings"] = MINIMUM_RATINGS
        # Only identity is persisted; Google scores are fetched live by the browser.
        profile["google_reference"] = {
            "google_place_id": google_reference.google_place_id,
            "name": profile["name"], "address": profile["address"],
            "latitude": google_reference.latitude, "longitude": google_reference.longitude,
            "city": google_reference.city,
            "country_code": google_reference.country_code or "UZ",
        }
        response.headers["Cache-Control"] = "no-store, max-age=0"
        return profile
