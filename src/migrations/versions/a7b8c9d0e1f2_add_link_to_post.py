"""add link column to post for episode page url

Revision ID: a7b8c9d0e1f2
Revises: f4e5f6a7b8c9
Create Date: 2026-04-10 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a7b8c9d0e1f2"
down_revision = "f4e5f6a7b8c9"
branch_labels = None
depends_on = None


def column_exists(table_name: str, column_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(sa.text(f"PRAGMA table_info({table_name})"))
    columns = [row[1] for row in result.fetchall()]
    return column_name in columns


def upgrade():
    if not column_exists("post", "link"):
        with op.batch_alter_table("post", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "link",
                    sa.Text(),
                    nullable=True,
                )
            )


def downgrade():
    with op.batch_alter_table("post", schema=None) as batch_op:
        batch_op.drop_column("link")
