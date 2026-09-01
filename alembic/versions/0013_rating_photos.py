"""Store optional consumer photos with ratings.

Revision ID: 0013
Revises: 0012
"""

from alembic import op
import sqlalchemy as sa


revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "rating_photos" in inspector.get_table_names():
        return
    op.create_table(
        "rating_photos",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("rating_id", sa.String(length=36), nullable=True),
        sa.Column("community_rating_id", sa.String(length=36), nullable=True),
        sa.Column("object_key", sa.String(length=320), nullable=True),
        sa.Column("content_type", sa.String(length=40), nullable=False),
        sa.Column("image_data", sa.LargeBinary(), nullable=False),
        sa.Column("ai_analysis", sa.Text(), nullable=True),
        sa.Column("analysis_status", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["rating_id"], ["ratings.id"]),
        sa.ForeignKeyConstraint(
            ["community_rating_id"], ["community_ratings.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rating_id"),
        sa.UniqueConstraint("community_rating_id"),
    )
    op.create_index("ix_rating_photos_rating_id", "rating_photos", ["rating_id"])
    op.create_index(
        "ix_rating_photos_community_rating_id",
        "rating_photos",
        ["community_rating_id"],
    )
    op.create_index("ix_rating_photos_object_key", "rating_photos", ["object_key"])


def downgrade() -> None:
    if "rating_photos" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("rating_photos")
