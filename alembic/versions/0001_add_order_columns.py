"""add order_type and table_number to orders

Revision ID: 0001_add_order_columns
Revises:
Create Date: 2025-08-16 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0001_add_order_columns"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Add order_type with default 'takeaway' (nullable False)
    op.add_column(
        "orders",
        sa.Column("order_type", sa.String(), nullable=False, server_default="takeaway"),
    )
    # Add table_number as nullable string
    op.add_column("orders", sa.Column("table_number", sa.String(), nullable=True))

    # If you want to remove the server_default afterwards:
    op.alter_column("orders", "order_type", server_default=None)


def downgrade():
    # Drop columns in reverse order
    op.drop_column("orders", "table_number")
    op.drop_column("orders", "order_type")
