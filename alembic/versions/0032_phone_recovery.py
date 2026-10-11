"""Verified account phones and single-use SMS recovery challenges."""

from alembic import op
import sqlalchemy as sa

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "account_phones" not in existing:
        op.create_table(
            "account_phones",
            sa.Column(
                "user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True
            ),
            sa.Column("phone", sa.String(16), nullable=False, unique=True),
            sa.Column("verified_at", sa.DateTime(), nullable=False),
        )
    if "phone_challenges" not in existing:
        op.create_table(
            "phone_challenges",
            sa.Column("token_hash", sa.String(64), primary_key=True),
            sa.Column(
                "user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False
            ),
            sa.Column("phone", sa.String(16), nullable=False),
            sa.Column("purpose", sa.String(10), nullable=False),
            sa.Column("password_fingerprint", sa.String(64), nullable=False),
            sa.Column("verification_sid", sa.String(34), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("consumed_at", sa.DateTime(), nullable=True),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        )
        op.create_index("ix_phone_challenges_user_id", "phone_challenges", ["user_id"])
        op.create_index(
            "ix_phone_challenges_expires_at", "phone_challenges", ["expires_at"]
        )


def downgrade():
    op.drop_table("phone_challenges")
    op.drop_table("account_phones")
