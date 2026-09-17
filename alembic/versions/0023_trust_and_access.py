"""Feedback reasons, private moderation and operational records."""

from alembic import op
import sqlalchemy as sa

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    def add(table, column):
        if column.name not in {c["name"] for c in sa.inspect(bind).get_columns(table)}:
            op.add_column(table, column)

    for table in ["ratings", "community_ratings"]:
        add(table, sa.Column("comment", sa.Text(), nullable=True))
        add(
            table,
            sa.Column("reasons_json", sa.Text(), nullable=False, server_default="[]"),
        )
    add(
        "community_ratings",
        sa.Column("included", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    add(
        "community_ratings",
        sa.Column("status", sa.String(30), nullable=False, server_default="ACCEPTED"),
    )
    add(
        "users",
        sa.Column("language", sa.String(2), nullable=False, server_default="ru"),
    )
    add("rating_photos", sa.Column("content_hash", sa.String(64), nullable=True))
    if "ix_rating_photos_content_hash" not in {
        i["name"] for i in sa.inspect(bind).get_indexes("rating_photos")
    }:
        op.create_index(
            "ix_rating_photos_content_hash", "rating_photos", ["content_hash"]
        )
    tables = set(sa.inspect(bind).get_table_names())
    if "feedback_signals" not in tables:
        op.create_table(
            "feedback_signals",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("rating_id", sa.String(36), nullable=False, unique=True),
            sa.Column("rating_type", sa.String(20), nullable=False),
            sa.Column("object_key", sa.String(320), nullable=False, index=True),
            sa.Column(
                "user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True
            ),
            sa.Column("device_hash", sa.String(64), nullable=True, index=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
        )
    if "moderation_cases" not in tables:
        op.create_table(
            "moderation_cases",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("case_key", sa.String(100), nullable=False, unique=True),
            sa.Column("kind", sa.String(20), nullable=False, index=True),
            sa.Column("object_key", sa.String(320), nullable=False, index=True),
            sa.Column("rating_id", sa.String(36), nullable=True, index=True),
            sa.Column("rating_type", sa.String(20), nullable=True),
            sa.Column(
                "reporter_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True
            ),
            sa.Column("details", sa.Text(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, index=True),
            sa.Column("decision_note", sa.Text(), nullable=True),
            sa.Column(
                "decided_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
            sa.Column("decided_at", sa.DateTime(), nullable=True),
        )
    if "mail_deliveries" not in tables:
        op.create_table(
            "mail_deliveries",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True
            ),
            sa.Column("purpose", sa.String(20), nullable=False),
            sa.Column("provider_id", sa.String(100), nullable=True),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
        )
    if "operations_events" not in tables:
        op.create_table(
            "operations_events",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("kind", sa.String(30), nullable=False, index=True),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("details", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
        )


def downgrade():
    for table in [
        "operations_events",
        "mail_deliveries",
        "moderation_cases",
        "feedback_signals",
    ]:
        op.drop_table(table)
    op.drop_index("ix_rating_photos_content_hash", table_name="rating_photos")
    op.drop_column("rating_photos", "content_hash")
    op.drop_column("users", "language")
    for column in ["included", "status"]:
        op.drop_column("community_ratings", column)
    for table in ["ratings", "community_ratings"]:
        for column in ["comment", "reasons_json"]:
            op.drop_column(table, column)
