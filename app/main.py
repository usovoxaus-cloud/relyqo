from datetime import datetime, timedelta
import hmac
from pathlib import Path
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
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
from .schemas import OwnerTokenCreate, RatingCreate, VerifyVisit
from .score import calculate_ces, weighted_score
from .security import create_token, token_hash, verify_signature

app = FastAPI(title="RELYQO API", version="1.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
static = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static), name="static")


def ensure_fregat(db: Session) -> tuple[Organization, Branch]:
    org = db.scalar(select(Organization).where(Organization.name == "Fregat"))
    if not org:
        org = Organization(name="Fregat", city="Tashkent")
        db.add(org)
        db.flush()
    branch = db.scalar(
        select(Branch).where(
            Branch.organization_id == org.id,
            Branch.name == "Shota Rustaveli 69",
        )
    )
    if not branch:
        branch = Branch(organization_id=org.id, name="Shota Rustaveli 69")
        db.add(branch)
        db.flush()
    return org, branch


def issue_visit_token(branch: Branch, db: Session) -> str:
    token, _ = create_token(branch.id)
    db.add(
        VisitToken(
            branch_id=branch.id,
            token_hash=token_hash(token),
            expires_at=datetime.utcnow() + timedelta(hours=3),
        )
    )
    return token


@app.get("/", include_in_schema=False)
def web():
    return FileResponse(static / "index.html")


@app.get("/owner", include_in_schema=False)
def owner_web():
    return FileResponse(static / "owner.html")


@app.get("/fregat", include_in_schema=False)
def fregat_visit(db: Session = Depends(get_db)):
    """Pilot QR entry: each scan receives a fresh one-time visit token."""
    if not settings.demo_mode:
        raise HTTPException(404)
    _, branch = ensure_fregat(db)
    token = issue_visit_token(branch, db)
    db.commit()
    return RedirectResponse(url=f"/?token={token}", status_code=303)


@app.get("/fregat/qr.png", include_in_schema=False)
def fregat_qr(request: Request):
    import io
    import qrcode

    target = f"{str(request.base_url).rstrip('/')}/fregat"
    image = qrcode.make(target)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return Response(output.getvalue(), media_type="image/png")


@app.post("/v1/owner/visit-token")
def owner_visit_token(
    body: OwnerTokenCreate, request: Request, db: Session = Depends(get_db)
):
    if not settings.owner_password or not hmac.compare_digest(
        body.password.encode("utf-8"), settings.owner_password.encode("utf-8")
    ):
        raise HTTPException(401, "Неверный пароль владельца")
    existing = db.scalar(
        select(VisitToken).where(
            VisitToken.transaction_reference == body.transaction_reference
        )
    )
    if existing:
        raise HTTPException(409, "Для этого чека QR уже выпускался")
    _, branch = ensure_fregat(db)
    token = issue_visit_token(branch, db)
    record = db.scalar(
        select(VisitToken).where(VisitToken.token_hash == token_hash(token))
    )
    record.transaction_reference = body.transaction_reference
    db.add(
        AuditLog(
            actor_type="OWNER",
            action="VISIT_TOKEN_ISSUED",
            entity_type="VISIT_TOKEN",
            entity_id=record.id,
        )
    )
    db.commit()
    base_url = str(request.base_url).rstrip("/")
    return {
        "expires_in": 10800,
        "visit_url": f"{base_url}/?token={token}",
        "qr_url": f"{base_url}/v1/qr.png?token={token}",
    }


@app.get("/v1/qr.png", include_in_schema=False)
def token_qr(token: str, request: Request, db: Session = Depends(get_db)):
    import io
    import qrcode

    try:
        verify_signature(token)
    except Exception as exc:
        raise HTTPException(400, "Недействительный QR") from exc
    record = db.scalar(
        select(VisitToken).where(VisitToken.token_hash == token_hash(token))
    )
    if not record or record.used_at or record.expires_at < datetime.utcnow():
        raise HTTPException(410, "QR недоступен")
    target = f"{str(request.base_url).rstrip('/')}/?token={token}"
    image = qrcode.make(target)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return Response(output.getvalue(), media_type="image/png")


@app.get("/fregat/qr", response_class=HTMLResponse, include_in_schema=False)
def fregat_qr_page():
    return """<!doctype html><html lang='ru'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Fregat — RELYQO QR</title><style>body{font-family:Arial,sans-serif;text-align:center;padding:36px;color:#082c27}img{width:min(72vw,420px)}h1{font-size:42px;margin-bottom:4px}p{font-size:20px}.brand{letter-spacing:.18em;color:#16715f;font-weight:700}@media print{button{display:none}}</style></head><body><div class='brand'>RELYQO · VERIFIED VISIT</div><h1>Fregat</h1><p>Shota Rustaveli 69 · Tashkent</p><img src='/fregat/qr.png' alt='QR для оценки Fregat'><p>Отсканируйте QR после посещения<br>и оставьте честную оценку.</p><button onclick='print()'>Печать</button></body></html>"""


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


@app.post("/v1/demo/visit")
def demo_visit(request: Request, db: Session = Depends(get_db)):
    """Create a short-lived demo visit URL. Disabled when DEMO_MODE=false."""
    if not settings.demo_mode:
        raise HTTPException(404)
    org = db.scalar(select(Organization).where(Organization.name == "Saffron Table"))
    if not org:
        org = Organization(name="Saffron Table", city="Tashkent")
        db.add(org)
        db.flush()
    branch = db.scalar(select(Branch).where(Branch.organization_id == org.id))
    if not branch:
        branch = Branch(organization_id=org.id, name="Tashkent City")
        db.add(branch)
        db.flush()
    token, _ = create_token(branch.id)
    db.add(
        VisitToken(
            branch_id=branch.id,
            token_hash=token_hash(token),
            expires_at=datetime.utcnow() + timedelta(hours=3),
        )
    )
    db.commit()
    base_url = str(request.base_url).rstrip("/")
    return {
        "organization_id": org.id,
        "expires_in": 10800,
        "visit_url": f"{base_url}/?token={token}",
    }


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
