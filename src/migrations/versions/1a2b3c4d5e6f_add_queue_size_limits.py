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
    inspector = sa.inspect(op.get_bind())
    return column_name in {col["name"] for col in inspector.get_columns(table_name)}


def upgrade() -> None:
    cols_to_add = {
        "max_queue_size": sa.Column("max_queue_size", sa.Integer(), nullable=True),
        "max_queue_size_per_feed": sa.Column("max_queue_size_per_feed", sa.Integer(), nullable=True),
    }
    missing = [col for name, col in cols_to_add.items() if not column_exists("app_settings", name)]
    if missing:
        with op.batch_alter_table("app_settings", schema=None) as batch_op:
            for col in missing:
                batch_op.add_column(col)


def downgrade() -> None:
    cols_to_drop = [
        col for col in ("max_queue_size_per_feed", "max_queue_size")
        if column_exists("app_settings", col)
    ]
    if cols_to_drop:
        with op.batch_alter_table("app_settings", schema=None) as batch_op:
            for col in cols_to_drop:
                batch_op.drop_column(col)
