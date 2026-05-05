"""add queue size limit settings

Revision ID: 1a2b3c4d5e6f
Revises: 6f67a7db0fbb
Create Date: 2026-05-04 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "1a2b3c4d5e6f"
down_revision = "6f67a7db0fbb"
branch_labels = None
depends_on = None


def column_exists(table_name: str, column_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(sa.text(f"PRAGMA table_info({table_name})"))
    columns = [row[1] for row in result.fetchall()]
    return column_name in columns


def upgrade() -> None:
    if not column_exists("app_settings", "max_queue_size"):
        with op.batch_alter_table("app_settings", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column("max_queue_size", sa.Integer(), nullable=True)
            )

    if not column_exists("app_settings", "max_queue_size_per_feed"):
        with op.batch_alter_table("app_settings", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column("max_queue_size_per_feed", sa.Integer(), nullable=True)
            )


def downgrade() -> None:
    for col in ("max_queue_size_per_feed", "max_queue_size"):
        if column_exists("app_settings", col):
            with op.batch_alter_table("app_settings", schema=None) as batch_op:
                batch_op.drop_column(col)
