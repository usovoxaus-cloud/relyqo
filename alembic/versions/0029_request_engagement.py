"""Scoped read receipts and approved representation of existing cards."""
from alembic import op
import sqlalchemy as sa

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "service_request_reads" not in existing:
        op.create_table("service_request_reads",
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True),
            sa.Column("request_id", sa.String(36), sa.ForeignKey("service_requests.id"), primary_key=True),
            sa.Column("version", sa.Integer(), nullable=False))
    if "representation_claims" not in existing:
        op.create_table("representation_claims",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
            sa.Column("object_key", sa.String(320), nullable=False, index=True),
            sa.Column("contact", sa.String(200), nullable=False),
            sa.Column("evidence", sa.Text(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, index=True),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("applicant_seen_version", sa.Integer(), nullable=False),
            sa.Column("decision_note", sa.Text()),
            sa.Column("decided_by", sa.String(36), sa.ForeignKey("users.id")),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("user_id", "object_key", name="uq_representation_claim_user_object"),
            sa.CheckConstraint("status IN ('PENDING','APPROVED','REJECTED','REVOKED')", name="ck_representation_claim_status"))
    if "service_representatives" not in existing:
        op.create_table("service_representatives",
            sa.Column("object_key", sa.String(320), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
            sa.Column("claim_id", sa.String(36), sa.ForeignKey("representation_claims.id"), nullable=False, unique=True),
            sa.Column("approved_at", sa.DateTime(), nullable=False))


def downgrade():
    op.drop_table("service_representatives")
    op.drop_table("representation_claims")
    op.drop_table("service_request_reads")
