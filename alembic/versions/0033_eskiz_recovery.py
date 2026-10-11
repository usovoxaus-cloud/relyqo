"""Add provider identity and keyed OTP digest to existing phone challenges."""

from alembic import op
import sqlalchemy as sa

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade():
    columns = {
        c["name"] for c in sa.inspect(op.get_bind()).get_columns("phone_challenges")
    }
    if "provider" not in columns:
        op.add_column(
            "phone_challenges",
            sa.Column(
                "provider", sa.String(16), nullable=False, server_default="twilio"
            ),
        )
    if "code_digest" not in columns:
        op.add_column(
            "phone_challenges", sa.Column("code_digest", sa.String(64), nullable=True)
        )


def downgrade():
    op.drop_column("phone_challenges", "code_digest")
    op.drop_column("phone_challenges", "provider")
