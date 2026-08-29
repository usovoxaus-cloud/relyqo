"""Initial RELYQO v1.1 schema."""
from alembic import op
from app.db import Base
from app import models
revision="0001"; down_revision=None; branch_labels=None; depends_on=None
def upgrade(): Base.metadata.create_all(op.get_bind())
def downgrade(): Base.metadata.drop_all(op.get_bind())

