"""add notification apprise settings

Revision ID: c1d2e3f4a5b6
Revises: 3e5eebc6b3b1
Create Date: 2026-04-09 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c1d2e3f4a5b6"
down_revision = "3e5eebc6b3b1"
branch_labels = None
depends_on = None


def column_exists(table_name: str, column_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(sa.text(f"PRAGMA table_info({table_name})"))
    columns = [row[1] for row in result.fetchall()]
    return column_name in columns


def upgrade():
    if not column_exists("app_settings", "notification_apprise_url"):
        with op.batch_alter_table("app_settings", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "notification_apprise_url",
                    sa.Text(),
                    nullable=False,
                    server_default="",
                )
            )

    if not column_exists("app_settings", "notification_apprise_key"):
        with op.batch_alter_table("app_settings", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "notification_apprise_key",
                    sa.Text(),
                    nullable=False,
                    server_default="",
                )
            )


def downgrade():
    with op.batch_alter_table("app_settings", schema=None) as batch_op:
        batch_op.drop_column("notification_apprise_key")
        batch_op.drop_column("notification_apprise_url")
