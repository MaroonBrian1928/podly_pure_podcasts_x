"""add actual_model_name to model_call for fallback tracking

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-15 00:00:00.000000

When the LLM fallback model handles a call, actual_model_name records the
model that actually answered. NULL means the primary model (model_name) was
used, preserving backwards compatibility.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def column_exists(table_name: str, column_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(sa.text(f"PRAGMA table_info({table_name})"))
    columns = [row[1] for row in result.fetchall()]
    return column_name in columns


def upgrade() -> None:
    if not column_exists("model_call", "actual_model_name"):
        with op.batch_alter_table("model_call", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column("actual_model_name", sa.String(), nullable=True)
            )


def downgrade() -> None:
    if column_exists("model_call", "actual_model_name"):
        with op.batch_alter_table("model_call", schema=None) as batch_op:
            batch_op.drop_column("actual_model_name")
