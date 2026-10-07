"""project allowlist/goals, run evaluation counters, bug resolution

Revision ID: 0003_projects_eval_resolution
Revises: 0002_autonomous_loop
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_projects_eval_resolution"
down_revision = "0002_autonomous_loop"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("allowed_domains", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("projects", sa.Column("default_goals", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("test_runs", sa.Column("candidates_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("test_runs", sa.Column("discarded_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("test_runs", sa.Column("first_bug_at", sa.DateTime(), nullable=True))
    op.add_column("bugs", sa.Column("resolution", sa.String(16), nullable=False, server_default="open"))
    op.add_column("bugs", sa.Column("resolved_at", sa.DateTime(), nullable=True))
    # No duplicate states per run; indexes for the common list queries.
    op.create_unique_constraint("uq_ui_states_run_fingerprint", "ui_states", ["test_run_id", "fingerprint"])
    op.create_index("ix_test_runs_created_at", "test_runs", ["created_at"])
    op.create_index("ix_bugs_run_created", "bugs", ["test_run_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_bugs_run_created", "bugs")
    op.drop_index("ix_test_runs_created_at", "test_runs")
    op.drop_constraint("uq_ui_states_run_fingerprint", "ui_states", type_="unique")
    for t, cols in (("bugs", ["resolved_at", "resolution"]), ("test_runs", ["first_bug_at", "discarded_count", "candidates_count"]),
                    ("projects", ["default_goals", "allowed_domains"])):
        for c in cols:
            op.drop_column(t, c)
