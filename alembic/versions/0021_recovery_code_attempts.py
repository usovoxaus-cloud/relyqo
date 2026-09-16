"""Add keyed OTP verification and persistent per-code attempt limits."""

from alembic import op
import sqlalchemy as sa

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade():
    columns = {
        c["name"]
        for c in sa.inspect(op.get_bind()).get_columns("password_recovery_tokens")
    }
    if "code_hash" not in columns:
        op.add_column(
            "password_recovery_tokens",
            sa.Column("code_hash", sa.String(64), nullable=True),
        )
    if "attempts" not in columns:
        op.add_column(
            "password_recovery_tokens",
            sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        )


def downgrade():
    op.drop_column("password_recovery_tokens", "attempts")
    op.drop_column("password_recovery_tokens", "code_hash")
