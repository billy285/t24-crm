"""Add daily automation scans, data quality issues and task links.

Revision ID: c9f4d2a7e615
Revises: b7e3a1d5f804
Create Date: 2026-08-03
"""

from alembic import op
import sqlalchemy as sa


revision = "c9f4d2a7e615"
down_revision = "b7e3a1d5f804"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "data_quality_issues",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("issue_key", sa.String(length=192), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("customer_name", sa.String(length=255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("suggested_action", sa.Text(), nullable=True),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("first_detected_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("last_detected_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["customer_engagements.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("issue_key", name="uq_data_quality_issues_key"),
    )
    for column in ("issue_key", "code", "category", "severity", "status", "customer_id", "project_id", "first_detected_at", "last_detected_at", "resolved_at"):
        op.create_index(f"ix_data_quality_issues_{column}", "data_quality_issues", [column], unique=False)

    op.create_table(
        "automation_scan_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_key", sa.String(length=96), nullable=False),
        sa.Column("scan_date", sa.Date(), nullable=False),
        sa.Column("trigger", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("detected_count", sa.Integer(), nullable=False),
        sa.Column("opened_count", sa.Integer(), nullable=False),
        sa.Column("resolved_count", sa.Integer(), nullable=False),
        sa.Column("task_created_count", sa.Integer(), nullable=False),
        sa.Column("task_updated_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_key", name="uq_automation_scan_runs_key"),
    )
    for column in ("run_key", "scan_date", "trigger", "status", "started_at", "completed_at"):
        op.create_index(f"ix_automation_scan_runs_{column}", "automation_scan_runs", [column], unique=False)

    with op.batch_alter_table("tasks") as batch_op:
        batch_op.add_column(sa.Column("source_type", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("automation_issue_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("completion_result", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_foreign_key(
            "fk_tasks_automation_issue_id",
            "data_quality_issues",
            ["automation_issue_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_unique_constraint("uq_tasks_automation_issue_id", ["automation_issue_id"])
        batch_op.create_index("ix_tasks_source_type", ["source_type"], unique=False)
        batch_op.create_index("ix_tasks_automation_issue_id", ["automation_issue_id"], unique=False)
        batch_op.create_index("ix_tasks_completed_at", ["completed_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.drop_index("ix_tasks_completed_at")
        batch_op.drop_index("ix_tasks_automation_issue_id")
        batch_op.drop_index("ix_tasks_source_type")
        batch_op.drop_constraint("uq_tasks_automation_issue_id", type_="unique")
        batch_op.drop_constraint("fk_tasks_automation_issue_id", type_="foreignkey")
        batch_op.drop_column("completed_at")
        batch_op.drop_column("completion_result")
        batch_op.drop_column("automation_issue_id")
        batch_op.drop_column("source_type")

    for column in ("completed_at", "started_at", "status", "trigger", "scan_date", "run_key"):
        op.drop_index(f"ix_automation_scan_runs_{column}", table_name="automation_scan_runs")
    op.drop_table("automation_scan_runs")

    for column in ("resolved_at", "last_detected_at", "first_detected_at", "project_id", "customer_id", "status", "severity", "category", "code", "issue_key"):
        op.drop_index(f"ix_data_quality_issues_{column}", table_name="data_quality_issues")
    op.drop_table("data_quality_issues")
