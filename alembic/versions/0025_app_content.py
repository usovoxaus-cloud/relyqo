"""Owner-editable public copy; additive migration."""

from alembic import op
import sqlalchemy as sa

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade():
    if "app_content" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "app_content",
            sa.Column("key", sa.String(40), primary_key=True),
            sa.Column("content_json", sa.Text(), nullable=False),
            sa.Column("previous_json", sa.Text(), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column(
                "updated_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False
            ),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )


def downgrade():
    op.drop_table("app_content")
