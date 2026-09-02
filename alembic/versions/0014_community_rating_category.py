"""Remember the service category used for a community rating.

Revision ID: 0014
Revises: 0013
"""

from alembic import op
import sqlalchemy as sa


revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def has_category_column() -> bool:
    return "category" in {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("community_ratings")
    }


def upgrade() -> None:
    if has_category_column():
        return
    with op.batch_alter_table("community_ratings") as batch:
        batch.add_column(
            sa.Column(
                "category",
                sa.String(length=40),
                nullable=False,
                server_default="OTHER",
            )
        )


def downgrade() -> None:
    if not has_category_column():
        return
    with op.batch_alter_table("community_ratings") as batch:
        batch.drop_column("category")
