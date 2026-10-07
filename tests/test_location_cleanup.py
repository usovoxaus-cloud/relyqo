"""Audited data repair must preserve cards, feedback and later corrections."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db import Base
from app.models import AuditLog, Branch, CommunityRating, ManualPlace, Organization


def cleanup_migration():
    path = Path(__file__).parents[1] / "alembic/versions/0031_quarantine_legacy_locations.py"
    spec = importlib.util.spec_from_file_location("location_cleanup", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def seed_bad_locations(db):
    records = []
    for table, record_id, name, address, city, lat, lng in cleanup_migration().REPAIRS:
        data = dict(id=record_id, address=address, city=city, country_code="UZ",
                    latitude=lat, longitude=lng)
        if table == "manual_places":
            record = ManualPlace(**data, name=name, category="PROFESSIONAL_SERVICE",
                                 description="", identity_hash=record_id, created_by_hash="fixture")
        else:
            org = Organization(name=name, city=city, category="PROFESSIONAL_SERVICE")
            db.add(org)
            db.flush()
            record = Branch(**data, name="Fixture branch", organization_id=org.id)
        db.add(record)
        records.append(record)
    db.flush()
    return records


@pytest.fixture
def catalog(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'catalog.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        records = seed_bad_locations(db)
        db.add(CommunityRating(object_key="manual:" + records[0].id, source="MANUAL",
            rater_hash="fixture", overall=8, quality=8, service=8, cleanliness=8,
            value=8, community_score=80, comment="Preserve this private fixture"))
        db.commit()
    yield engine
    engine.dispose()


def apply_cleanup(engine, monkeypatch):
    migration = cleanup_migration()
    with engine.begin() as connection:
        monkeypatch.setattr(migration, "op", SimpleNamespace(get_bind=lambda: connection))
        migration.upgrade()


def test_cleanup_preserves_cards_ratings_and_archives_exact_original_points(catalog, monkeypatch):
    apply_cleanup(catalog, monkeypatch)
    apply_cleanup(catalog, monkeypatch)
    with Session(catalog) as db:
        for table, record_id, _, address, _, lat, lng in cleanup_migration().REPAIRS:
            record = db.get(ManualPlace if table == "manual_places" else Branch, record_id)
            assert record.active and record.address == address
            assert record.latitude is None and record.longitude is None
            audit = db.scalar(select(AuditLog).where(AuditLog.entity_id == record_id))
            assert audit.action == f"LOCATION_QUARANTINED_0031:{lat},{lng}"
        assert db.scalar(select(func.count()).select_from(AuditLog)) == 3
        rating = db.scalar(select(CommunityRating))
        assert rating.object_key == "manual:bf8cf764-6352-4c45-a99a-5bef9d810153"
        assert rating.comment == "Preserve this private fixture" and rating.included


@pytest.mark.parametrize("change", ["coordinates", "address", "provider"])
def test_cleanup_never_overwrites_records_corrected_since_audit(catalog, monkeypatch, change):
    with Session(catalog) as db:
        record = db.get(ManualPlace, "bf8cf764-6352-4c45-a99a-5bef9d810153")
        if change == "coordinates":
            record.latitude, record.longitude = 41.3035, 69.2811
        elif change == "address":
            record.address = "Corrected address"
        else:
            record.google_place_id = "verified-provider-fixture"
        db.commit()
        old_point = record.latitude, record.longitude
    apply_cleanup(catalog, monkeypatch)
    with Session(catalog) as db:
        record = db.get(ManualPlace, "bf8cf764-6352-4c45-a99a-5bef9d810153")
        assert (record.latitude, record.longitude) == old_point
        assert db.scalar(select(func.count()).select_from(AuditLog)) == 2
