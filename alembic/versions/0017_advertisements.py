"""Add clearly separated advertising campaigns.

Revision ID: 0017
Revises: 0016
"""

from alembic import op
import sqlalchemy as sa


revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "advertisements" in inspector.get_table_names():
        return
    op.create_table(
        "advertisements",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("sponsor_name", sa.String(length=120), nullable=False),
        sa.Column("headline", sa.String(length=120), nullable=False),
        sa.Column("message", sa.String(length=280), nullable=False),
        sa.Column("target_url", sa.String(length=500), nullable=True),
        sa.Column("placement", sa.String(length=30), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("impressions", sa.Integer(), nullable=False),
        sa.Column("clicks", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_advertisements_placement", "advertisements", ["placement"])
    op.create_index("ix_advertisements_active", "advertisements", ["active"])
    op.create_index(
        "ix_advertisements_created_by_user_id",
        "advertisements",
        ["created_by_user_id"],
    )


def downgrade() -> None:
    if "advertisements" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("advertisements")
