"""add queue size limit settings

Revision ID: a1b2c3d4e5f6
Revises: f4e5f6a7b8c9
Create Date: 2026-05-04 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "f4e5f6a7b8c9"
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
