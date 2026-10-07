"""autonomous loop: run limits/metrics, richer states/edges/bugs, run_events, memory_records

Revision ID: 0002_autonomous_loop
Revises: 0001_initial
Create Date: 2026-09-30
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_autonomous_loop"
down_revision: str | None = "0001_initial"
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def _add(table: str, *cols: sa.Column) -> None:
    for c in cols:
        op.add_column(table, c)


def upgrade() -> None:
    _add(
        "test_runs",
        sa.Column("max_runtime_seconds", sa.Integer(), nullable=False, server_default="600"),
        sa.Column("max_depth", sa.Integer(), nullable=False, server_default="6"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("termination_reason", sa.String(64), nullable=True),
        sa.Column("termination_detail", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("states_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("actions_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bugs_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("errors_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("coverage", sa.Float(), nullable=False, server_default="0"),
        sa.Column("last_screenshot", sa.String(2048), nullable=True),
    )
    op.execute("UPDATE test_runs SET status = 'queued' WHERE status = 'pending'")

    _add(
        "ui_states",
        sa.Column("visit_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("depth", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("screenshot_path", sa.String(2048), nullable=True),
        sa.Column("visible_text_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("interactive_elements", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    _add(
        "ui_transitions",
        sa.Column("action_label", sa.String(512), nullable=False, server_default=""),
        sa.Column("action_parameters", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("expected_result", sa.Text(), nullable=False, server_default=""),
        sa.Column("actual_result", sa.Text(), nullable=False, server_default=""),
        sa.Column("verdict", sa.String(32), nullable=True),
    )
    _add(
        "bugs",
        sa.Column("project_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=True),
        sa.Column("category", sa.String(64), nullable=False, server_default="functional"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("status", sa.String(16), nullable=False, server_default="unverified"),
        sa.Column("url", sa.String(2048), nullable=False, server_default=""),
        sa.Column("state_key", sa.String(64), nullable=False, server_default=""),
        sa.Column("fingerprint", sa.String(64), nullable=False, server_default=""),
        sa.Column("screenshot_path", sa.String(2048), nullable=True),
        sa.Column("console_errors", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("network_errors", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("severity_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("verification", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("seen_before_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_bugs_project_id", "bugs", ["project_id"])
    op.create_index("ix_bugs_fingerprint", "bugs", ["fingerprint"])

    op.create_table(
        "run_events",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("test_run_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("test_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(48), nullable=False),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("data", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_run_events_run_seq", "run_events", ["test_run_id", "seq"])

    op.create_table(
        "memory_records",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("key", sa.String(600), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("project_id", "kind", "key", name="uq_memory_project_kind_key"),
    )
    op.create_index("ix_memory_records_project_id", "memory_records", ["project_id"])


def downgrade() -> None:
    op.drop_table("memory_records")
    op.drop_table("run_events")
    for col in ("seen_before_count", "verification", "severity_reason", "evidence", "network_errors", "console_errors",
                "screenshot_path", "fingerprint", "state_key", "url", "status", "confidence", "category", "project_id"):
        op.drop_column("bugs", col)
    for col in ("verdict", "actual_result", "expected_result", "action_parameters", "action_label"):
        op.drop_column("ui_transitions", col)
    for col in ("last_seen_at", "interactive_elements", "visible_text_summary", "screenshot_path", "depth", "visit_count"):
        op.drop_column("ui_states", col)
    for col in ("last_screenshot", "coverage", "errors_count", "bugs_count", "actions_count", "states_count", "finished_at",
                "started_at", "termination_detail", "termination_reason", "max_retries", "max_depth", "max_runtime_seconds"):
        op.drop_column("test_runs", col)
    op.execute("UPDATE test_runs SET status = 'pending' WHERE status = 'queued'")
