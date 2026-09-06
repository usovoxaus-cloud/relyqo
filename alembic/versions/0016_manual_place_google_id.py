"""Link consumer-confirmed places to a Google Place ID.

Revision ID: 0016
Revises: 0015
"""

from alembic import op
import sqlalchemy as sa


revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def columns() -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("manual_places")
    }


def indexes() -> set[str]:
    return {
        index["name"]
        for index in sa.inspect(op.get_bind()).get_indexes("manual_places")
        if index.get("name")
    }


def upgrade() -> None:
    if "google_place_id" not in columns():
        with op.batch_alter_table("manual_places") as batch:
            batch.add_column(
                sa.Column("google_place_id", sa.String(length=255), nullable=True)
            )
    if "ux_manual_places_google_place_id" not in indexes():
        op.create_index(
            "ux_manual_places_google_place_id",
            "manual_places",
            ["google_place_id"],
            unique=True,
        )


def downgrade() -> None:
    if "ux_manual_places_google_place_id" in indexes():
        op.drop_index(
            "ux_manual_places_google_place_id",
            table_name="manual_places",
        )
    if "google_place_id" in columns():
        with op.batch_alter_table("manual_places") as batch:
            batch.drop_column("google_place_id")
