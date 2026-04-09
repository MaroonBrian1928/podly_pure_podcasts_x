"""add per-feed tag settings and global override flag

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-04-09 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "e3f4a5b6c7d8"
down_revision = "d2e3f4a5b6c7"
branch_labels = None
depends_on = None


def column_exists(table_name: str, column_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(sa.text(f"PRAGMA table_info({table_name})"))
    columns = [row[1] for row in result.fetchall()]
    return column_name in columns


def upgrade():
    # Per-feed tag overrides on the feed table (nullable = inherit global)
    if not column_exists("feed", "feed_tag_label"):
        with op.batch_alter_table("feed", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column("feed_tag_label", sa.Text(), nullable=True)
            )

    if not column_exists("feed", "feed_tag_position"):
        with op.batch_alter_table("feed", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column("feed_tag_position", sa.Text(), nullable=True)
            )

    # Global override flag on app_settings (False = per-feed wins when set)
    if not column_exists("app_settings", "feed_tag_override"):
        with op.batch_alter_table("app_settings", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "feed_tag_override",
                    sa.Boolean(),
                    nullable=False,
                    server_default="0",
                )
            )


def downgrade():
    with op.batch_alter_table("app_settings", schema=None) as batch_op:
        batch_op.drop_column("feed_tag_override")

    with op.batch_alter_table("feed", schema=None) as batch_op:
        batch_op.drop_column("feed_tag_position")
        batch_op.drop_column("feed_tag_label")
