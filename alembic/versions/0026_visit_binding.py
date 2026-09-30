"""Bind newly verified visits; support list-only places without invented GPS."""
from alembic import op
import sqlalchemy as sa

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "rater_hash" not in {column["name"] for column in inspector.get_columns("visits")}:
        op.add_column("visits", sa.Column("rater_hash", sa.String(64), nullable=True))
    if "rating_cooldowns" not in inspector.get_table_names():
        op.create_table("rating_cooldowns",
                    sa.Column("key", sa.String(64), primary_key=True),
                    sa.Column("expires_at", sa.DateTime(), nullable=False))
        op.create_index("ix_rating_cooldowns_expires_at", "rating_cooldowns", ["expires_at"])
    columns = {column["name"] for column in inspector.get_columns("manual_places")}
    if "source_url" not in columns:
        op.add_column("manual_places", sa.Column("source_url", sa.String(500), nullable=True))
    if "source_checked_at" not in columns:
        op.add_column("manual_places", sa.Column("source_checked_at", sa.DateTime(), nullable=True))
    with op.batch_alter_table("manual_places") as batch:
        batch.alter_column("latitude", existing_type=sa.Float(), nullable=True)
        batch.alter_column("longitude", existing_type=sa.Float(), nullable=True)


def downgrade():
    # Restoring NOT NULL would destroy list-only records. Keep the wider columns.
    op.drop_table("rating_cooldowns")
    op.drop_column("visits", "rater_hash")
    op.drop_column("manual_places", "source_url")
    op.drop_column("manual_places", "source_checked_at")
