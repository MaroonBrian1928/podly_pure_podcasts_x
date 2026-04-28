"""add OIDC support

Revision ID: a1b2c3d4e5f6
Revises: c3d4e5f6a7b8
Create Date: 2026-04-28 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade():
    # Add OIDC columns to users table
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "auth_provider",
                sa.String(length=32),
                nullable=False,
                server_default="local",
            )
        )
        batch_op.add_column(
            sa.Column("oidc_sub", sa.String(length=255), nullable=True)
        )
        batch_op.add_column(
            sa.Column("oidc_email", sa.String(length=255), nullable=True)
        )
        batch_op.create_unique_constraint("uq_users_oidc_sub", ["oidc_sub"])
        batch_op.create_index("ix_users_oidc_sub", ["oidc_sub"])

    # Backfill auth_provider for existing Discord SSO users
    op.execute(
        "UPDATE users SET auth_provider = 'discord' WHERE discord_id IS NOT NULL"
    )

    # Create oidc_settings table
    op.create_table(
        "oidc_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("issuer", sa.Text(), nullable=True),
        sa.Column("client_id", sa.Text(), nullable=True),
        sa.Column("client_secret", sa.Text(), nullable=True),
        sa.Column("redirect_uri", sa.Text(), nullable=True),
        sa.Column("allow_registration", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    op.drop_table("oidc_settings")

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_index("ix_users_oidc_sub")
        batch_op.drop_constraint("uq_users_oidc_sub", type_="unique")
        batch_op.drop_column("oidc_email")
        batch_op.drop_column("oidc_sub")
        batch_op.drop_column("auth_provider")
