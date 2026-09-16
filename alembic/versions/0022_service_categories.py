"""Allow administrators to add service categories."""

from alembic import op
import sqlalchemy as sa

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade():
    if "service_categories" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "service_categories",
            sa.Column("code", sa.String(40), primary_key=True),
            sa.Column("label", sa.String(80), nullable=False),
            sa.Column("label_key", sa.String(80), nullable=False, unique=True),
            sa.Column("group_code", sa.String(40), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    for table, column in [
        ("ratings", "created_at"),
        ("community_ratings", "created_at"),
        ("visits", "verified_at"),
    ]:
        name = f"ix_{table}_{column}"
        if name not in {
            index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)
        }:
            op.create_index(name, table, [column])


def downgrade():
    for table, column in [
        ("ratings", "created_at"),
        ("community_ratings", "created_at"),
        ("visits", "verified_at"),
    ]:
        op.drop_index(f"ix_{table}_{column}", table_name=table)
    op.drop_table("service_categories")
