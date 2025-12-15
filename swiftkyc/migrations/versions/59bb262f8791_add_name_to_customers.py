"""add name column to customers (non-null with default empty string)

Revision ID: add_customer_name_20251210
Revises: 39b6f913defe
Create Date: 2025-12-10 00:00:00
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "add_customer_name_20251210"
down_revision = "39b6f913defe"
branch_labels = None
depends_on = None


def upgrade():
    # Add column with default='' and NOT NULL
    op.add_column(
        "customers",
        sa.Column(
            "name",
            sa.String(length=200),
            nullable=False,
            server_default="",
        ),
    )

    # Important: remove the server default *after* existing rows are filled
    op.alter_column(
        "customers",
        "name",
        server_default=None
    )


def downgrade():
    op.drop_column("customers", "name")
