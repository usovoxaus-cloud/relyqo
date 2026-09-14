"""Verified consumer email, one-use recovery tokens and shared rate limits."""

from alembic import op
import sqlalchemy as sa

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "consumer_emails" not in existing:
        op.create_table(
            "consumer_emails",
            sa.Column(
                "user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True
            ),
            sa.Column("email", sa.String(254), nullable=False),
            sa.Column("verified_at", sa.DateTime(), nullable=False),
        )
        op.create_index(
            "ix_consumer_emails_email", "consumer_emails", ["email"], unique=True
        )
    if "password_recovery_tokens" not in existing:
        op.create_table(
            "password_recovery_tokens",
            sa.Column("token_hash", sa.String(64), primary_key=True),
            sa.Column(
                "user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False
            ),
            sa.Column("purpose", sa.String(20), nullable=False),
            sa.Column("email", sa.String(254), nullable=False),
            sa.Column("password_fingerprint", sa.String(64), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("consumed_at", sa.DateTime(), nullable=True),
        )
        op.create_index(
            "ix_password_recovery_tokens_user_id",
            "password_recovery_tokens",
            ["user_id"],
        )
        op.create_index(
            "ix_password_recovery_tokens_expires_at",
            "password_recovery_tokens",
            ["expires_at"],
        )
    if "recovery_rate_limits" not in existing:
        op.create_table(
            "recovery_rate_limits",
            sa.Column("key", sa.String(64), primary_key=True),
            sa.Column("count", sa.Integer(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
        )
        op.create_index(
            "ix_recovery_rate_limits_expires_at", "recovery_rate_limits", ["expires_at"]
        )


def downgrade():
    op.drop_table("recovery_rate_limits")
    op.drop_table("password_recovery_tokens")
    op.drop_table("consumer_emails")
