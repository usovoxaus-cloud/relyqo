"""Add self-service business profiles.

Revision ID: 0011
Revises: 0010
"""

from alembic import op
import sqlalchemy as sa


revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("organizations")}
    with op.batch_alter_table("organizations") as batch:
        if "category" not in columns:
            batch.add_column(
                sa.Column(
                    "category",
                    sa.String(length=40),
                    nullable=False,
                    server_default="RESTAURANT",
                )
            )
        if "description" not in columns:
            batch.add_column(sa.Column("description", sa.Text(), nullable=True))
        if "phone" not in columns:
            batch.add_column(sa.Column("phone", sa.String(length=40), nullable=True))
        if "website" not in columns:
            batch.add_column(sa.Column("website", sa.String(length=255), nullable=True))
        if "profile_status" not in columns:
            batch.add_column(
                sa.Column(
                    "profile_status",
                    sa.String(length=30),
                    nullable=False,
                    server_default="VERIFIED_PARTNER",
                )
            )
        if "created_at" not in columns:
            batch.add_column(
                sa.Column(
                    "created_at",
                    sa.DateTime(),
                    nullable=False,
                    server_default=sa.func.now(),
                )
            )
    indexes = {
        index["name"] for index in sa.inspect(bind).get_indexes("organizations")
    }
    if "ix_organizations_category" not in indexes:
        op.create_index("ix_organizations_category", "organizations", ["category"])
    if "ix_organizations_profile_status" not in indexes:
        op.create_index(
            "ix_organizations_profile_status",
            "organizations",
            ["profile_status"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {
        column["name"] for column in sa.inspect(bind).get_columns("organizations")
    }
    indexes = {
        index["name"] for index in sa.inspect(bind).get_indexes("organizations")
    }
    if "ix_organizations_profile_status" in indexes:
        op.drop_index("ix_organizations_profile_status", table_name="organizations")
    if "ix_organizations_category" in indexes:
        op.drop_index("ix_organizations_category", table_name="organizations")
    with op.batch_alter_table("organizations") as batch:
        for column in (
            "created_at",
            "profile_status",
            "website",
            "phone",
            "description",
            "category",
        ):
            if column in columns:
                batch.drop_column(column)
