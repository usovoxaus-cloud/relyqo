"""Add public community ratings kept separate from verified RELYQO Score."""

from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("community_ratings"):
        op.create_table(
            "community_ratings",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("object_key", sa.String(length=320), nullable=False),
            sa.Column("source", sa.String(length=30), nullable=False),
            sa.Column("rater_hash", sa.String(length=64), nullable=False),
            sa.Column("overall", sa.Integer(), nullable=False),
            sa.Column("quality", sa.Integer(), nullable=False),
            sa.Column("service", sa.Integer(), nullable=False),
            sa.Column("cleanliness", sa.Integer(), nullable=False),
            sa.Column("value", sa.Integer(), nullable=False),
            sa.Column("community_score", sa.Float(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "object_key",
                "rater_hash",
                name="uq_community_object_rater",
            ),
        )
    indexes = {
        index["name"]
        for index in sa.inspect(bind).get_indexes("community_ratings")
    }
    if "ix_community_ratings_object_key" not in indexes:
        op.create_index(
            "ix_community_ratings_object_key",
            "community_ratings",
            ["object_key"],
        )
    if "ix_community_ratings_rater_hash" not in indexes:
        op.create_index(
            "ix_community_ratings_rater_hash",
            "community_ratings",
            ["rater_hash"],
        )


def downgrade():
    if sa.inspect(op.get_bind()).has_table("community_ratings"):
        op.drop_table("community_ratings")
