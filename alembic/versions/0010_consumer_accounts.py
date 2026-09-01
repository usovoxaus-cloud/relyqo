"""Add consumer accounts, synced favorites, and rating history.

Revision ID: 0010
Revises: 0009
"""

from alembic import op
import sqlalchemy as sa


revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("consumer_favorites"):
        op.create_table(
            "consumer_favorites",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("object_key", sa.String(length=320), nullable=False),
            sa.Column("source", sa.String(length=30), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "user_id", "object_key", name="uq_consumer_favorite_user_object"
            ),
        )
        op.create_index(
            "ix_consumer_favorites_user_id",
            "consumer_favorites",
            ["user_id"],
        )
        op.create_index(
            "ix_consumer_favorites_object_key",
            "consumer_favorites",
            ["object_key"],
        )
    inspector = sa.inspect(bind)
    community_columns = {
        column["name"] for column in inspector.get_columns("community_ratings")
    }
    if "consumer_user_id" not in community_columns:
        with op.batch_alter_table("community_ratings") as batch:
            batch.add_column(
                sa.Column("consumer_user_id", sa.String(length=36), nullable=True)
            )
            batch.create_foreign_key(
                "fk_community_rating_consumer",
                "users",
                ["consumer_user_id"],
                ["id"],
            )
            batch.create_unique_constraint(
                "uq_community_object_consumer",
                ["object_key", "consumer_user_id"],
            )
            batch.create_index(
                "ix_community_ratings_consumer_user_id",
                ["consumer_user_id"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("consumer_favorites"):
        op.drop_table("consumer_favorites")
    community_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("community_ratings")
    }
    if "consumer_user_id" in community_columns:
        with op.batch_alter_table("community_ratings") as batch:
            batch.drop_index("ix_community_ratings_consumer_user_id")
            batch.drop_constraint("uq_community_object_consumer", type_="unique")
            batch.drop_constraint("fk_community_rating_consumer", type_="foreignkey")
            batch.drop_column("consumer_user_id")
