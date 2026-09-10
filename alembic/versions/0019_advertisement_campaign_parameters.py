"""Add scheduling and display parameters to advertisements.

Revision ID: 0019
Revises: 0018
"""

from alembic import op
import sqlalchemy as sa


revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


COLUMNS = {
    "campaign_name": sa.Column(
        "campaign_name", sa.String(length=80), nullable=False, server_default="Кампания"
    ),
    "cta_text": sa.Column(
        "cta_text", sa.String(length=32), nullable=False, server_default="Подробнее"
    ),
    "page_scope": sa.Column(
        "page_scope", sa.String(length=30), nullable=False, server_default="ALL"
    ),
    "starts_at": sa.Column("starts_at", sa.DateTime(), nullable=True),
    "ends_at": sa.Column("ends_at", sa.DateTime(), nullable=True),
    "max_impressions": sa.Column("max_impressions", sa.Integer(), nullable=True),
}


def advertisement_columns() -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("advertisements")
    }


def advertisement_indexes() -> set[str]:
    return {
        index["name"]
        for index in sa.inspect(op.get_bind()).get_indexes("advertisements")
    }


def upgrade() -> None:
    existing_columns = advertisement_columns()
    with op.batch_alter_table("advertisements") as batch:
        for name, column in COLUMNS.items():
            if name not in existing_columns:
                batch.add_column(column)
    if "ix_advertisements_page_scope" not in advertisement_indexes():
        op.create_index(
            "ix_advertisements_page_scope", "advertisements", ["page_scope"]
        )


def downgrade() -> None:
    if "ix_advertisements_page_scope" in advertisement_indexes():
        op.drop_index("ix_advertisements_page_scope", table_name="advertisements")
    existing_columns = advertisement_columns()
    with op.batch_alter_table("advertisements") as batch:
        for name in COLUMNS:
            if name in existing_columns:
                batch.drop_column(name)
