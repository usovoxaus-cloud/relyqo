from datetime import datetime
from pathlib import Path
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .config import settings
from .db import get_db
from .models import (
    AuditLog,
    Branch,
    Organization,
    Rating,
    ScoreHistory,
    Visit,
    VisitToken,
)
from .schemas import RatingCreate, VerifyVisit
from .score import calculate_ces, weighted_score
from .security import token_hash, verify_signature

app = FastAPI(title="RELYQO API", version="1.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
static = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static), name="static")


@app.get("/", include_in_schema=False)
def web():
    return FileResponse(static / "index.html")


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    return FileResponse(
        static / "manifest.webmanifest", media_type="application/manifest+json"
    )


@app.get("/sw.js", include_in_schema=False)
def sw():
    return FileResponse(static / "sw.js", media_type="application/javascript")


@app.get("/v1/health")
def health(db: Session = Depends(get_db)):
    db.execute(select(1))
    return {"status": "ok", "version": "1.1.0"}


@app.post("/v1/visits/verify-token")
def verify_visit(body: VerifyVisit, db: Session = Depends(get_db)):
    try:
        data = verify_signature(body.token)
    except Exception as exc:
        raise HTTPException(400, str(exc))
    record = db.scalar(
        select(VisitToken)
        .where(VisitToken.token_hash == token_hash(body.token))
        .with_for_update()
    )
    if not record or record.used_at:
        raise HTTPException(409, "QR уже использован или не существует")
    if record.expires_at < datetime.utcnow():
        raise HTTPException(410, "QR истёк")
    branch = db.get(Branch, record.branch_id)
    org = db.get(Organization, branch.organization_id)
    if data["branch_id"] != branch.id:
        raise HTTPException(400, "QR не соответствует филиалу")
    visit = Visit(branch_id=branch.id)
    record.used_at = datetime.utcnow()
    db.add(visit)
    db.flush()
    db.add(
        AuditLog(
            actor_type="CUSTOMER",
            action="VISIT_VERIFIED",
            entity_type="VISIT",
            entity_id=visit.id,
        )
    )
    db.commit()
    return {
        "status": "VERIFIED",
        "visit_id": visit.id,
        "organization": {"id": org.id, "name": org.name},
        "branch": {"id": branch.id, "name": branch.name},
        "verification_score": visit.verification_score,
    }


@app.post("/v1/ratings")
def rate(body: RatingCreate, db: Session = Depends(get_db)):
    visit = db.get(Visit, body.visit_id)
    if not visit:
        raise HTTPException(404, "Посещение не найдено")
    branch = db.get(Branch, visit.branch_id)
    org = db.get(Organization, branch.organization_id)
    ces = calculate_ces(
        body.overall, body.food, body.service, body.cleanliness, body.value
    )
    rating = Rating(
        **body.model_dump(),
        organization_id=org.id,
        ces=ces,
        trust_weight=visit.verification_score,
    )
    db.add(rating)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Для этого посещения оценка уже поставлена")
    rows = db.execute(
        select(Rating.ces, Rating.trust_weight, Rating.included).where(
            Rating.organization_id == org.id
        )
    ).all()
    org.score = weighted_score(rows)
    org.rating_count = len([r for r in rows if r.included])
    db.add_all(
        [
            ScoreHistory(organization_id=org.id, score=org.score),
            AuditLog(
                actor_type="SCORE_ENGINE",
                action="SCORE_RECALCULATED",
                entity_type="ORGANIZATION",
                entity_id=org.id,
            ),
        ]
    )
    db.commit()
    return {
        "rating_id": rating.id,
        "status": rating.status,
        "ces_score": ces,
        "included_in_rating": rating.included,
        "relyqo_score": org.score,
        "rating_count": org.rating_count,
    }


@app.get("/v1/organizations/{organization_id}/score")
def score(organization_id: str, db: Session = Depends(get_db)):
    org = db.get(Organization, organization_id)
    if not org:
        raise HTTPException(404, "Организация не найдена")
    return {
        "organization_id": org.id,
        "name": org.name,
        "relyqo_score": org.score,
        "rating_count": org.rating_count,
        "calculation": "deterministic_weighted_ces_v1",
    }


@app.get("/v1/business/organizations/{organization_id}")
def business_read(
    organization_id: str,
    x_role: str = Header(default="BUSINESS_VIEWER"),
    db: Session = Depends(get_db),
):
    if x_role != "BUSINESS_VIEWER":
        raise HTTPException(403)
    return score(organization_id, db)
