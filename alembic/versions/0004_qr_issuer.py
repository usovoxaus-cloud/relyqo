"""Track the account and time that issued each visit QR."""

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("visit_tokens")}
    with op.batch_alter_table("visit_tokens") as batch:
        if "issued_by_user_id" not in columns:
            batch.add_column(
                sa.Column("issued_by_user_id", sa.String(length=36), nullable=True)
            )
            batch.create_foreign_key(
                "fk_visit_tokens_issued_by_user",
                "users",
                ["issued_by_user_id"],
                ["id"],
            )
        if "created_at" not in columns:
            batch.add_column(sa.Column("created_at", sa.DateTime(), nullable=True))
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("visit_tokens")}
    if "ix_visit_tokens_issued_by_user_id" not in indexes:
        op.create_index(
            "ix_visit_tokens_issued_by_user_id",
            "visit_tokens",
            ["issued_by_user_id"],
        )


def downgrade():
    op.drop_index("ix_visit_tokens_issued_by_user_id", table_name="visit_tokens")
    with op.batch_alter_table("visit_tokens") as batch:
        batch.drop_constraint("fk_visit_tokens_issued_by_user", type_="foreignkey")
        batch.drop_column("created_at")
        batch.drop_column("issued_by_user_id")
