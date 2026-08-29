"""Add transaction reference to one-time visit tokens."""

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "visit_tokens",
        sa.Column("transaction_reference", sa.String(length=120), nullable=True),
    )
    op.create_unique_constraint(
        "uq_visit_tokens_transaction_reference",
        "visit_tokens",
        ["transaction_reference"],
    )


def downgrade():
    op.drop_constraint(
        "uq_visit_tokens_transaction_reference", "visit_tokens", type_="unique"
    )
    op.drop_column("visit_tokens", "transaction_reference")
