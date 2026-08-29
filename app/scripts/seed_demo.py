from datetime import datetime, timedelta
from app.db import Base, SessionLocal, engine
from app.models import Branch, Organization, VisitToken
from app.security import create_token, token_hash
from app.config import settings


def main():
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        org = Organization(name="Saffron Table", city="Tashkent")
        db.add(org)
        db.flush()
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
        print(
            f"ORGANIZATION_ID={org.id}\nVISIT_URL={settings.public_base_url}/?token={token}\nVISIT_TOKEN={token}"
        )


if __name__ == "__main__":
    main()
