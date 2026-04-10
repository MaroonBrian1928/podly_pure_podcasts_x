"""add feed tag settings

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-04-09 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d2e3f4a5b6c7"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def column_exists(table_name: str, column_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(sa.text(f"PRAGMA table_info({table_name})"))
    columns = [row[1] for row in result.fetchall()]
    return column_name in columns


def upgrade():
    if not column_exists("app_settings", "feed_tag_label"):
        with op.batch_alter_table("app_settings", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "feed_tag_label",
                    sa.Text(),
                    nullable=False,
                    server_default="",
                )
            )

    if not column_exists("app_settings", "feed_tag_position"):
        with op.batch_alter_table("app_settings", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "feed_tag_position",
                    sa.Text(),
                    nullable=False,
                    server_default="prefix",
                )
            )


def downgrade():
    if column_exists("app_settings", "feed_tag_position"):
        with op.batch_alter_table("app_settings", schema=None) as batch_op:
            batch_op.drop_column("feed_tag_position")
    if column_exists("app_settings", "feed_tag_label"):
        with op.batch_alter_table("app_settings", schema=None) as batch_op:
            batch_op.drop_column("feed_tag_label")
