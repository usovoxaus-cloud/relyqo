"""Add photo, video, and presentation media to advertisements.

Revision ID: 0018
Revises: 0017
"""

from alembic import op
import sqlalchemy as sa


revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


MEDIA_COLUMNS = {
    "media_kind": sa.Column("media_kind", sa.String(length=30), nullable=True),
    "media_content_type": sa.Column(
        "media_content_type", sa.String(length=120), nullable=True
    ),
    "media_filename": sa.Column(
        "media_filename", sa.String(length=180), nullable=True
    ),
    "media_size_bytes": sa.Column("media_size_bytes", sa.Integer(), nullable=True),
}


def advertisement_columns() -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("advertisements")
    }


def upgrade() -> None:
    existing_columns = advertisement_columns()
    with op.batch_alter_table("advertisements") as batch:
        for name, column in MEDIA_COLUMNS.items():
            if name not in existing_columns:
                batch.add_column(column)
    if "advertisement_media" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "advertisement_media",
            sa.Column("advertisement_id", sa.String(length=36), nullable=False),
            sa.Column("media_data", sa.LargeBinary(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["advertisement_id"],
                ["advertisements.id"],
            ),
            sa.PrimaryKeyConstraint("advertisement_id"),
        )


def downgrade() -> None:
    if "advertisement_media" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("advertisement_media")
    existing_columns = advertisement_columns()
    with op.batch_alter_table("advertisements") as batch:
        for name in MEDIA_COLUMNS:
            if name in existing_columns:
                batch.drop_column(name)
