"""Add persistent login attempt protection to user accounts."""

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {
        column["name"] for column in sa.inspect(bind).get_columns("users")
    }
    with op.batch_alter_table("users") as batch:
        if "failed_login_attempts" not in columns:
            batch.add_column(
                sa.Column(
                    "failed_login_attempts",
                    sa.Integer(),
                    nullable=False,
                    server_default="0",
                )
            )
        if "locked_until" not in columns:
            batch.add_column(sa.Column("locked_until", sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table("users") as batch:
        batch.drop_column("locked_until")
        batch.drop_column("failed_login_attempts")
