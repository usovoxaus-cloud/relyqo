"""Add public location metadata for global restaurant discovery."""

from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("branches")}
    with op.batch_alter_table("branches") as batch:
        if "address" not in columns:
            batch.add_column(sa.Column("address", sa.String(length=255), nullable=True))
        if "city" not in columns:
            batch.add_column(sa.Column("city", sa.String(length=80), nullable=True))
        if "country_code" not in columns:
            batch.add_column(
                sa.Column("country_code", sa.String(length=2), nullable=True)
            )
        if "latitude" not in columns:
            batch.add_column(sa.Column("latitude", sa.Float(), nullable=True))
        if "longitude" not in columns:
            batch.add_column(sa.Column("longitude", sa.Float(), nullable=True))
        if "google_place_id" not in columns:
            batch.add_column(
                sa.Column("google_place_id", sa.String(length=255), nullable=True)
            )
        if "active" not in columns:
            batch.add_column(
                sa.Column(
                    "active",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.true(),
                )
            )
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("branches")}
    if "ix_branches_latitude" not in indexes:
        op.create_index("ix_branches_latitude", "branches", ["latitude"])
    if "ix_branches_longitude" not in indexes:
        op.create_index("ix_branches_longitude", "branches", ["longitude"])
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("branches")}
    if "ux_branches_google_place_id" not in indexes:
        op.create_index(
            "ux_branches_google_place_id",
            "branches",
            ["google_place_id"],
            unique=True,
        )
    bind.execute(
        sa.text(
            """
            UPDATE branches
            SET address = COALESCE(address, :address),
                city = COALESCE(city, :city),
                country_code = COALESCE(country_code, :country_code),
                latitude = COALESCE(latitude, :latitude),
                longitude = COALESCE(longitude, :longitude),
                active = :active
            WHERE name = :branch_name
              AND organization_id IN (
                  SELECT id FROM organizations WHERE name = :organization_name
              )
            """
        ),
        {
            "address": "Shota Rustaveli 69",
            "city": "Tashkent",
            "country_code": "UZ",
            "latitude": 41.272878,
            "longitude": 69.240319,
            "active": True,
            "branch_name": "Shota Rustaveli 69",
            "organization_name": "Fregat",
        },
    )


def downgrade():
    op.drop_index("ux_branches_google_place_id", table_name="branches")
    op.drop_index("ix_branches_longitude", table_name="branches")
    op.drop_index("ix_branches_latitude", table_name="branches")
    with op.batch_alter_table("branches") as batch:
        batch.drop_column("active")
        batch.drop_column("google_place_id")
        batch.drop_column("longitude")
        batch.drop_column("latitude")
        batch.drop_column("country_code")
        batch.drop_column("city")
        batch.drop_column("address")
