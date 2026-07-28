"""task urgency index: (owner_id, due_at, id) for board-wide urgency paging

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-28

"""

from collections.abc import Sequence

import sqlmodel  # noqa: F401
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_tasks_owner_due_at_id", "tasks", ["owner_id", "due_at", "id"])


def downgrade() -> None:
    op.drop_index("ix_tasks_owner_due_at_id", table_name="tasks")
