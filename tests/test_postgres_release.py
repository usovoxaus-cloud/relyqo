"""Opt-in integration against the disposable PostgreSQL 18 service in CI."""

from datetime import datetime
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from app.config import settings
from app.models import User, Organization, Branch, Visit, Rating, RatingPhoto, AppContent
from app.analytics import AnalyticsFilter, build_report
from app.backups import create_snapshot, restore_snapshot


def test_postgres_additive_migration_and_independent_restore(monkeypatch):
    dsn = os.environ.get("RELYQO_TEST_PG_DSN")
    if not dsn:
        pytest.skip("Requires a disposable PostgreSQL CI database")
    url = make_url(dsn)
    assert url.host in ("127.0.0.1", "localhost") and url.database == "relyqo_ci"
    engine = create_engine(dsn)
    assert inspect(engine).get_table_names() == [], "CI source must start empty"
    monkeypatch.setattr(settings, "database_url", dsn)
    cfg = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    command.upgrade(cfg, "0023")
    # The legacy initial migration creates current metadata on a fresh installation.
    # Remove only the new, empty tables to reproduce an actual pre-0024 schema.
    with engine.begin() as c:
        for table in (
            "app_content",
            "backup_agents",
            "improvement_events",
            "improvement_actions",
            "admin_notification_reads",
        ):
            c.execute(text("DROP TABLE " + table))
    with Session(engine) as db:
        user = User(
            username="ci-fixture",
            role="CONSUMER",
            password_hash="fixture-not-a-real-login",
        )
        org = Organization(name="CI restaurant", category="RESTAURANT")
        db.add_all([user, org])
        db.flush()
        branch = Branch(organization_id=org.id, name="CI branch")
        db.add(branch)
        db.flush()
        visit = Visit(branch_id=branch.id, verified_at=datetime(2026, 9, 1))
        db.add(visit)
        db.flush()
        rating = Rating(
            visit_id=visit.id,
            organization_id=org.id,
            consumer_user_id=user.id,
            overall=9,
            food=9,
            service=9,
            cleanliness=9,
            value=9,
            ces=90,
            trust_weight=1,
            comment="Restore fixture",
            created_at=datetime(2026, 9, 1),
        )
        db.add(rating)
        db.flush()
        # The snapshot must preserve binary evidence as well as relational references.
        db.add(
            RatingPhoto(
                rating_id=rating.id,
                image_data=b"fixture-photo-bytes",
                content_type="image/png",
                content_hash="fixture-digest",
                analysis_status="SKIPPED",
            )
        )
        db.commit()
        rating_id = rating.id
    command.upgrade(cfg, "head")
    with Session(engine) as db:
        assert db.get(Rating, rating_id).comment == "Restore fixture"
        report = build_report(
            db,
            AnalyticsFilter(
                start=datetime(2026, 9, 1).date(),
                end=datetime(2026, 9, 2).date(),
                category=None,
                entity=None,
            ),
        )
        assert report["summary"]["new_respondents"] == 1
        assert report["comparison"]["summary"]["included"] == 0
    with Session(engine) as db:
        db.add(AppContent(key="home", content_json='{"ru":{"title":"Проверка","hint":"Сохранено"},"uz":{"title":"Sinov","hint":"Saqlandi"}}', previous_json=None, version=1, updated_by=db.scalar(select(User.id))))
        db.commit()
    phrase = "ci-only-backup-encryption-passphrase"
    archive = create_snapshot(engine, phrase)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text("CREATE DATABASE relyqo_ci_restore"))
    target = create_engine(url.set(database="relyqo_ci_restore"))
    restore_snapshot(target, archive, phrase)
    with Session(target) as db:
        assert db.get(Rating, rating_id).comment == "Restore fixture"
        assert db.get(AppContent, "home").version == 1
        assert "Sinov" in db.get(AppContent, "home").content_json
        assert db.scalar(select(RatingPhoto.image_data)) == b"fixture-photo-bytes"
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == "0025"
    with pytest.raises(ValueError):
        restore_snapshot(target, archive, phrase)
    target.dispose()
    engine.dispose()
    admin.dispose()
