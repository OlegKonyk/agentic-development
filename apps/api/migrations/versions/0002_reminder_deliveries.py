"""reminder deliveries: append-only health signal for reminder delivery

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-26

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel  # noqa: F401
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reminder_deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reminder_deliveries_task_id", "reminder_deliveries", ["task_id"])
    op.create_index("ix_reminder_deliveries_at", "reminder_deliveries", ["at"])


def downgrade() -> None:
    op.drop_index("ix_reminder_deliveries_at", table_name="reminder_deliveries")
    op.drop_index("ix_reminder_deliveries_task_id", table_name="reminder_deliveries")
    op.drop_table("reminder_deliveries")
