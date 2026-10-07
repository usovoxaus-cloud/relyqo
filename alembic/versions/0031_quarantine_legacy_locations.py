"""Quarantine three audited coordinates that contradict their Tashkent addresses.

This is an exact-record repair, not geocoding or duplicate merging. Original
coordinates are retained in the existing, backed-up audit log. Any record edited
since the audit is skipped. New locations must be verified before being assigned.
"""
from datetime import datetime
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None

# Public organization records audited on 2026-10-07. Preserve the exact values so
# a deliberate, reviewed recovery remains possible without transferring ratings.
REPAIRS = (
    ("manual_places", "bf8cf764-6352-4c45-a99a-5bef9d810153", "SCOPUS MCHJ",
     "шахрисабз 38", "Tashkent", 41.03027708951169, 28.811502591353836),
    ("branches", "2e02ac12-9122-46ff-a011-9573bdb5873b", "scopus mchj",
     "shaxrisabz 38", "tashkent", 41.030349, 28.811625),
    ("branches", "d864bc29-fd03-4b55-b66b-842042e22895", "Scopus Publication Mchj",
     "shaxrisabz 38", "Tashkent", 1.0, 1.0),
)


def upgrade():
    connection = op.get_bind()
    for table, record_id, name, address, city, latitude, longitude in REPAIRS:
        # Table names come exclusively from the fixed migration constants.
        name_guard = "name = :name" if table == "manual_places" else (
            "organization_id IN (SELECT id FROM organizations WHERE name = :name)"
        )
        changed = connection.execute(sa.text(
            f"UPDATE {table} SET latitude = NULL, longitude = NULL "
            f"WHERE id = :id AND {name_guard} AND address = :address "
            "AND city = :city AND country_code = 'UZ' AND google_place_id IS NULL "
            "AND latitude = :latitude AND longitude = :longitude"
        ), dict(id=record_id, name=name, address=address, city=city,
                latitude=latitude, longitude=longitude))
        if changed.rowcount:
            connection.execute(sa.text(
                "INSERT INTO audit_log (id, actor_type, action, entity_type, entity_id, created_at) "
                "VALUES (:id, 'SYSTEM', :action, :entity_type, :entity_id, :created_at)"
            ), dict(id=str(uuid4()),
                    action=f"LOCATION_QUARANTINED_0031:{latitude},{longitude}",
                    entity_type="MANUAL_PLACE" if table == "manual_places" else "BRANCH",
                    entity_id=record_id, created_at=datetime.utcnow()))


def downgrade():
    # A schema rollback must not put known-wrong points back onto the map.
    # The exact originals remain in audit_log and REPAIRS for reviewed recovery.
    pass
