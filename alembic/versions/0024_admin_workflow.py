"""Private admin workflow and scoped backup clients; additive schema only."""

from alembic import op
import sqlalchemy as sa

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())

    def create(name, *columns):
        # The initial historical migration creates current Base.metadata on fresh installs.
        if name not in existing:
            op.create_table(name, *columns)

    create(
        "admin_notification_reads",
        sa.Column(
            "user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True
        ),
        sa.Column("event_key", sa.String(180), primary_key=True),
        sa.Column("read_at", sa.DateTime(), nullable=False),
    )
    create(
        "improvement_actions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=False),
        sa.Column("filters_json", sa.Text(), nullable=False),
        sa.Column("baseline_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, index=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column(
            "created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    create(
        "improvement_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "action_id",
            sa.String(36),
            sa.ForeignKey("improvement_actions.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    create(
        "backup_agents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("password_fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("last_export_at", sa.DateTime(), nullable=True),
        sa.Column("last_saved_at", sa.DateTime(), nullable=True),
        sa.Column("latest_digest", sa.String(64), nullable=True),
    )


def downgrade():
    op.drop_table("backup_agents")
    op.drop_table("improvement_events")
    op.drop_table("improvement_actions")
    op.drop_table("admin_notification_reads")
