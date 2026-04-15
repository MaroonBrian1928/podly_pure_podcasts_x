"""add llm_fallback_model and llm_fallback_api_key to llm_settings

Revision ID: a1b2c3d4e5f6
Revises: f7a4195e0953
Create Date: 2026-04-15 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "f7a4195e0953"
branch_labels = None
depends_on = None


def column_exists(table_name: str, column_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(sa.text(f"PRAGMA table_info({table_name})"))
    columns = [row[1] for row in result.fetchall()]
    return column_name in columns


def upgrade() -> None:
    if not column_exists("llm_settings", "llm_fallback_model"):
        with op.batch_alter_table("llm_settings", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column("llm_fallback_model", sa.Text(), nullable=True)
            )

    if not column_exists("llm_settings", "llm_fallback_api_key"):
        with op.batch_alter_table("llm_settings", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column("llm_fallback_api_key", sa.Text(), nullable=True)
            )


def downgrade() -> None:
    if column_exists("llm_settings", "llm_fallback_api_key"):
        with op.batch_alter_table("llm_settings", schema=None) as batch_op:
            batch_op.drop_column("llm_fallback_api_key")

    if column_exists("llm_settings", "llm_fallback_model"):
        with op.batch_alter_table("llm_settings", schema=None) as batch_op:
            batch_op.drop_column("llm_fallback_model")
