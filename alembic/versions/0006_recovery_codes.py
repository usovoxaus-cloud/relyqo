"""Add one-time recovery codes for privileged accounts."""

from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {
        column["name"] for column in sa.inspect(bind).get_columns("users")
    }
    with op.batch_alter_table("users") as batch:
        if "recovery_code_hash" not in columns:
            batch.add_column(
                sa.Column("recovery_code_hash", sa.String(length=64), nullable=True)
            )
        if "recovery_code_created_at" not in columns:
            batch.add_column(
                sa.Column("recovery_code_created_at", sa.DateTime(), nullable=True)
            )


def downgrade():
    with op.batch_alter_table("users") as batch:
        batch.drop_column("recovery_code_created_at")
        batch.drop_column("recovery_code_hash")
