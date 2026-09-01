"""Scope receipt references to a branch.

Revision ID: 0012
Revises: 0011
"""

from alembic import op
import sqlalchemy as sa


revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


OLD_CONSTRAINT = "uq_visit_tokens_transaction_reference"
NEW_CONSTRAINT = "uq_visit_tokens_branch_transaction_reference"


def unique_constraints() -> dict[str, tuple[str, ...]]:
    return {
        constraint["name"]: tuple(constraint["column_names"])
        for constraint in sa.inspect(op.get_bind()).get_unique_constraints(
            "visit_tokens"
        )
        if constraint.get("name")
    }


def upgrade() -> None:
    constraints = unique_constraints()
    with op.batch_alter_table("visit_tokens") as batch:
        for name, columns in constraints.items():
            if columns == ("transaction_reference",):
                batch.drop_constraint(name, type_="unique")
        if NEW_CONSTRAINT not in constraints:
            batch.create_unique_constraint(
                NEW_CONSTRAINT,
                ["branch_id", "transaction_reference"],
            )


def downgrade() -> None:
    constraints = unique_constraints()
    with op.batch_alter_table("visit_tokens") as batch:
        if NEW_CONSTRAINT in constraints:
            batch.drop_constraint(NEW_CONSTRAINT, type_="unique")
        if OLD_CONSTRAINT not in constraints:
            batch.create_unique_constraint(
                OLD_CONSTRAINT,
                ["transaction_reference"],
            )
