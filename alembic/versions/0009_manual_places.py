"""Add manually submitted community places.

Revision ID: 0009
Revises: 0008
"""

from alembic import op
import sqlalchemy as sa


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("manual_places"):
        op.create_table(
            "manual_places",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("identity_hash", sa.String(length=64), nullable=False),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("category", sa.String(length=40), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("address", sa.String(length=255), nullable=False),
            sa.Column("city", sa.String(length=80), nullable=False),
            sa.Column("country_code", sa.String(length=2), nullable=False),
            sa.Column("latitude", sa.Float(), nullable=False),
            sa.Column("longitude", sa.Float(), nullable=False),
            sa.Column("created_by_hash", sa.String(length=64), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_manual_places_identity_hash",
            "manual_places",
            ["identity_hash"],
            unique=True,
        )
        op.create_index(
            "ix_manual_places_created_by_hash",
            "manual_places",
            ["created_by_hash"],
            unique=False,
        )
        op.create_index(
            "ix_manual_places_latitude", "manual_places", ["latitude"], unique=False
        )
        op.create_index(
            "ix_manual_places_longitude",
            "manual_places",
            ["longitude"],
            unique=False,
        )
    if not inspector.has_table("google_place_references"):
        op.create_table(
            "google_place_references",
            sa.Column("place_id", sa.String(length=255), nullable=False),
            sa.Column("first_seen_at", sa.DateTime(), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("place_id"),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("google_place_references"):
        op.drop_table("google_place_references")
    if inspector.has_table("manual_places"):
        op.drop_table("manual_places")
