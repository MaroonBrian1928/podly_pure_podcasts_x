"""add processing_job.stage_history

Revision ID: 3b71e9f0a4cd
Revises: d4e7f8a9b2c1
Create Date: 2026-05-15 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "3b71e9f0a4cd"
down_revision = "d4e7f8a9b2c1"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("processing_job", schema=None) as batch_op:
        batch_op.add_column(sa.Column("stage_history", sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table("processing_job", schema=None) as batch_op:
        batch_op.drop_column("stage_history")
