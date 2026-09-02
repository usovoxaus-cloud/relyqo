"""Optionally link a verified QR rating to a consumer account.

Revision ID: 0015
Revises: 0014
"""

from alembic import op
import sqlalchemy as sa


revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def columns() -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("ratings")
    }


def indexes() -> set[str]:
    return {
        index["name"]
        for index in sa.inspect(op.get_bind()).get_indexes("ratings")
        if index.get("name")
    }


def upgrade() -> None:
    if "consumer_user_id" not in columns():
        with op.batch_alter_table("ratings") as batch:
            batch.add_column(
                sa.Column("consumer_user_id", sa.String(length=36), nullable=True)
            )
            batch.create_foreign_key(
                "fk_ratings_consumer_user_id_users",
                "users",
                ["consumer_user_id"],
                ["id"],
            )
    if "ix_ratings_consumer_user_id" not in indexes():
        op.create_index(
            "ix_ratings_consumer_user_id",
            "ratings",
            ["consumer_user_id"],
        )


def downgrade() -> None:
    if "ix_ratings_consumer_user_id" in indexes():
        op.drop_index("ix_ratings_consumer_user_id", table_name="ratings")
    if "consumer_user_id" in columns():
        with op.batch_alter_table("ratings") as batch:
            batch.drop_column("consumer_user_id")
