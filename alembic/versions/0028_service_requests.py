"""Consent-based organization replies, separate from private moderation."""
from alembic import op
import sqlalchemy as sa

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade():
    # Legacy 0001 creates current metadata on fresh databases.
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "service_requests" not in existing:
        op.create_table(
            "service_requests",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("rating_id", sa.String(36), nullable=False),
            sa.Column("rating_type", sa.String(20), nullable=False),
            sa.Column("consumer_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("object_key", sa.String(320), nullable=False),
            sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id")),
            sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id")),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("consent_version", sa.String(20), nullable=False),
            sa.Column("consent_at", sa.DateTime(), nullable=False),
            sa.Column("assigned_by", sa.String(36), sa.ForeignKey("users.id")),
            sa.Column("assignment_note", sa.Text()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("rating_type", "rating_id", name="uq_service_request_rating"),
            sa.CheckConstraint("status IN ('WAITING_ORGANIZATION','OPEN','IN_PROGRESS','ANSWERED','RESOLVED','WITHDRAWN')", name="ck_service_request_status"),
            sa.CheckConstraint("rating_type IN ('VERIFIED','COMMUNITY')", name="ck_service_request_rating_type"),
        )
        for column in ("consumer_user_id", "organization_id", "status", "updated_at"):
            op.create_index("ix_service_requests_" + column, "service_requests", [column])
    if "service_messages" not in existing:
        op.create_table(
            "service_messages",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("request_id", sa.String(36), sa.ForeignKey("service_requests.id"), nullable=False),
            sa.Column("author_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("side", sa.String(20), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint("side IN ('CONSUMER','BUSINESS')", name="ck_service_message_side"),
        )
        op.create_index("ix_service_messages_request_id", "service_messages", ["request_id"])


def downgrade():
    op.drop_table("service_messages")
    op.drop_table("service_requests")
