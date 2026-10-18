"""Private, explicitly saved request drafts; independent of deferred SMS work."""
from alembic import op
import sqlalchemy as sa

revision = "0032_request_drafts"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade():
    # Portable restore creates known model tables before replaying schema revisions.
    if "request_drafts" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "request_drafts",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("kind", sa.String(10), primary_key=True),
        sa.Column("context_id", sa.String(36), primary_key=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("kind IN ('new','reply')", name="ck_request_draft_kind"),
        sa.CheckConstraint("version > 0", name="ck_request_draft_version"),
    )


def downgrade():
    op.drop_table("request_drafts")
