"""Add transaction reference to one-time visit tokens."""

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("visit_tokens")}
    if "transaction_reference" not in columns:
        with op.batch_alter_table("visit_tokens") as batch:
            batch.add_column(
                sa.Column(
                    "transaction_reference", sa.String(length=120), nullable=True
                )
            )
    unique_columns = {
        tuple(constraint["column_names"])
        for constraint in sa.inspect(bind).get_unique_constraints("visit_tokens")
    }
    if ("transaction_reference",) not in unique_columns:
        with op.batch_alter_table("visit_tokens") as batch:
            batch.create_unique_constraint(
                "uq_visit_tokens_transaction_reference", ["transaction_reference"]
            )


def downgrade():
    op.drop_constraint(
        "uq_visit_tokens_transaction_reference", "visit_tokens", type_="unique"
    )
    op.drop_column("visit_tokens", "transaction_reference")
