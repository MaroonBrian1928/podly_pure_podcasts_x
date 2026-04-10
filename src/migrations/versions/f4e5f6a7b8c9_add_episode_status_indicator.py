"""add episode status indicator settings

Revision ID: f4e5f6a7b8c9
Revises: e3f4a5b6c7d8
Create Date: 2026-04-10 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f4e5f6a7b8c9"
down_revision = "e3f4a5b6c7d8"
branch_labels = None
depends_on = None


def column_exists(table_name: str, column_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(sa.text(f"PRAGMA table_info({table_name})"))
    columns = [row[1] for row in result.fetchall()]
    return column_name in columns


def upgrade():
    if not column_exists("app_settings", "episode_status_indicator_enabled"):
        with op.batch_alter_table("app_settings", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "episode_status_indicator_enabled",
                    sa.Boolean(),
                    nullable=False,
                    server_default="0",
                )
            )

    if not column_exists("app_settings", "episode_status_processed_symbol"):
        with op.batch_alter_table("app_settings", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "episode_status_processed_symbol",
                    sa.Text(),
                    nullable=False,
                    server_default="✓",
                )
            )

    if not column_exists("app_settings", "episode_status_error_symbol"):
        with op.batch_alter_table("app_settings", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "episode_status_error_symbol",
                    sa.Text(),
                    nullable=False,
                    server_default="⚠",
                )
            )


def downgrade():
    with op.batch_alter_table("app_settings", schema=None) as batch_op:
        batch_op.drop_column("episode_status_error_symbol")
        batch_op.drop_column("episode_status_processed_symbol")
        batch_op.drop_column("episode_status_indicator_enabled")
