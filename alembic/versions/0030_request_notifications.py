"""Opt-in email preferences and durable request-event outbox."""
from alembic import op
import sqlalchemy as sa

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "request_email_preferences" not in existing:
        op.create_table("request_email_preferences",
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("email_hash", sa.String(64)),
            sa.Column("updated_at", sa.DateTime(), nullable=False))
    if "request_email_jobs" not in existing:
        op.create_table("request_email_jobs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
            sa.Column("request_id", sa.String(36), sa.ForeignKey("service_requests.id"), nullable=False, index=True),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("view", sa.String(20), nullable=False),
            sa.Column("email_hash", sa.String(64), nullable=False),
            sa.Column("language", sa.String(2), nullable=False),
            sa.Column("origin", sa.String(255), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, index=True),
            sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("first_attempt_at", sa.DateTime()),
            sa.Column("next_attempt_at", sa.DateTime(), nullable=False, index=True),
            sa.Column("provider_id", sa.String(100)),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("user_id", "request_id", "version", name="uq_request_email_event"))


def downgrade():
    op.drop_table("request_email_jobs")
    op.drop_table("request_email_preferences")
