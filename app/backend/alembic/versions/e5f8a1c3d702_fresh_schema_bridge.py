"""Create legacy tables required by the explicit migration chain.

Revision ID: e5f8a1c3d702
Revises: e4c7a1b9d305
Create Date: 2026-08-16

The application historically relied on ``Base.metadata.create_all`` and a few
request-time ``CREATE TABLE IF NOT EXISTS`` statements for these tables.  A
fresh database managed only by Alembic therefore could not reach the next
revision.  Keep every definition explicit here so the migration remains stable
when ORM models change in the future.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "e5f8a1c3d702"
down_revision = "e4c7a1b9d305"
branch_labels = None
depends_on = None


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _ensure_table(table: str, *elements: object, **kwargs: object) -> None:
    """Create a table, or validate a table previously created at runtime.

    Some pre-bridge databases can legitimately be stamped at e4 while already
    containing a subset of these tables from the old runtime bootstrap.  Never
    overwrite those tables or their data.  Existing tables must contain every
    bridge-baseline column and the expected primary key before we continue.
    """

    inspector = _inspector()
    if not inspector.has_table(table):
        op.create_table(table, *elements, **kwargs)
        return

    actual_columns = {column["name"] for column in inspector.get_columns(table)}
    expected_columns = {
        element.name for element in elements if isinstance(element, sa.Column)
    }
    missing_columns = sorted(expected_columns - actual_columns)
    if missing_columns:
        raise RuntimeError(
            f"Existing table {table!r} is incomplete; missing columns: "
            f"{', '.join(missing_columns)}"
        )

    expected_primary_key: list[str] = []
    for element in elements:
        if isinstance(element, sa.PrimaryKeyConstraint):
            pending = getattr(element, "_pending_colargs", ())
            expected_primary_key = [
                column if isinstance(column, str) else column.name for column in pending
            ]
            break
    actual_primary_key = list(inspector.get_pk_constraint(table).get("constrained_columns") or [])
    if expected_primary_key and actual_primary_key != expected_primary_key:
        raise RuntimeError(
            f"Existing table {table!r} has primary key {actual_primary_key!r}; "
            f"expected {expected_primary_key!r}"
        )


def _ensure_index(table: str, columns: tuple[str, ...], *, unique: bool = False, name: str | None = None) -> None:
    index_name = name or f"ix_{table}_{'_'.join(columns)}"
    existing = {index["name"]: index for index in _inspector().get_indexes(table)}
    if index_name in existing:
        index = existing[index_name]
        actual_columns = tuple(index.get("column_names") or ())
        actual_unique = bool(index.get("unique"))
        if actual_columns != columns or actual_unique != unique:
            raise RuntimeError(
                f"Existing index {index_name!r} on {table!r} has columns "
                f"{actual_columns!r}, unique={actual_unique}; expected "
                f"{columns!r}, unique={unique}"
            )
        return
    op.create_index(index_name, table, list(columns), unique=unique)


def _indexes(table: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        _ensure_index(table, (column,))


def _require_unique(table: str, columns: tuple[str, ...], name: str) -> None:
    inspector = _inspector()
    candidates = [
        (constraint.get("name"), tuple(constraint.get("column_names") or ()))
        for constraint in inspector.get_unique_constraints(table)
    ]
    candidates.extend(
        (index.get("name"), tuple(index.get("column_names") or ()))
        for index in inspector.get_indexes(table)
        if index.get("unique")
    )
    if not any(actual_columns == columns for _, actual_columns in candidates):
        raise RuntimeError(
            f"Existing table {table!r} is missing unique key {name!r} on {columns!r}"
        )


def _ensure_columns(table: str, columns: tuple[sa.Column, ...]) -> None:
    existing = {column["name"] for column in _inspector().get_columns(table)}
    missing = [column for column in columns if column.name not in existing]
    if not missing:
        return

    required = [column.name for column in missing if not column.nullable and column.server_default is None]
    if required:
        has_rows = op.get_bind().execute(sa.text(f'SELECT 1 FROM "{table}" LIMIT 1')).first() is not None
        if has_rows:
            raise RuntimeError(
                f"Cannot safely add required columns {required!r} to non-empty table {table!r}"
            )

    with op.batch_alter_table(table) as batch_op:
        for column in missing:
            batch_op.add_column(column)


def _ensure_nullable(table: str, column_name: str, column_type: sa.types.TypeEngine) -> None:
    current = next(
        column for column in _inspector().get_columns(table) if column["name"] == column_name
    )
    if current.get("nullable"):
        return
    with op.batch_alter_table(table) as batch_op:
        batch_op.alter_column(column_name, existing_type=column_type, nullable=True)


def _bridge_runtime_repair_columns() -> None:
    """Make a fresh migrated schema match columns previously supplied by repair."""

    _ensure_columns(
        "customers",
        (
            sa.Column("sales_lead_id", sa.Integer(), nullable=True),
            sa.Column("country", sa.String(), nullable=True),
            sa.Column("tiktok_link", sa.String(), nullable=True),
            sa.Column("selected_platforms", sa.String(), nullable=True),
            sa.Column("interested_packages", sa.String(), nullable=True),
            sa.Column("interested_packages_snapshot", sa.String(), nullable=True),
        ),
    )
    _ensure_index("customers", ("sales_lead_id",))

    _ensure_columns(
        "deals",
        (
            sa.Column("source_payment_id", sa.Integer(), nullable=True),
            sa.Column("package_platforms", sa.String(), nullable=True),
        ),
    )

    _ensure_columns(
        "employees",
        (
            sa.Column("password", sa.String(), nullable=True),
            sa.Column("employee_code", sa.String(), nullable=True),
            sa.Column("department", sa.String(), nullable=True),
            sa.Column("position", sa.String(), nullable=True),
            sa.Column("login_username", sa.String(), nullable=True),
            sa.Column("hire_date", sa.String(), nullable=True),
            sa.Column("supervisor", sa.String(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        ),
    )

    _ensure_columns(
        "expenses",
        (
            sa.Column("expense_category", sa.String(), nullable=True),
            sa.Column("currency", sa.String(), nullable=True),
            sa.Column("expense_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("recorded_by", sa.String(), nullable=True),
            sa.Column("user_id", sa.String(), nullable=False),
        ),
    )
    _ensure_nullable("expenses", "customer_id", sa.Integer())

    _ensure_columns(
        "payments",
        (
            sa.Column("source_deal_id", sa.Integer(), nullable=True),
            sa.Column("income_type", sa.String(), nullable=True),
            sa.Column("management_amount", sa.Float(), nullable=True),
            sa.Column("ads_recharge_amount", sa.Float(), nullable=True),
            sa.Column("stripe_fee_amount", sa.Float(), nullable=True),
            sa.Column("net_amount", sa.Float(), nullable=True),
            sa.Column("currency", sa.String(), nullable=True),
            sa.Column("payment_mode", sa.String(), nullable=True),
            sa.Column("transaction_reference", sa.String(), nullable=True),
            sa.Column("expense_month", sa.String(), nullable=True),
            sa.Column("recorded_by", sa.String(), nullable=True),
            sa.Column("user_id", sa.String(), nullable=False),
        ),
    )

    _ensure_columns(
        "service_progresses",
        (sa.Column("package_platforms", sa.String(), nullable=True),),
    )
    _ensure_columns(
        "service_tasks",
        (
            sa.Column("platform", sa.String(), nullable=True),
            sa.Column("completed_at", sa.String(), nullable=True),
            sa.Column("completed_by", sa.String(), nullable=True),
            sa.Column("selected_copy_id", sa.Integer(), nullable=True),
            sa.Column("selected_copy_title", sa.String(), nullable=True),
            sa.Column("selected_material_id", sa.Integer(), nullable=True),
            sa.Column("selected_material_title", sa.String(), nullable=True),
            sa.Column("completion_quality", sa.String(), nullable=True),
            sa.Column("completion_note", sa.String(), nullable=True),
        ),
    )

    # Several older migrations omitted the BaseModel primary-key indexes.
    for table in (
        "ad_fund_settlements",
        "customer_lifecycle_cycles",
        "customer_lifecycle_events",
        "finance_refunds",
        "opportunities",
    ):
        _ensure_index(table, ("id",))

    # The historical migrations and production database represent these keys
    # as a named UNIQUE constraint plus a non-unique lookup index. Preserve
    # that safe representation instead of rebuilding SQLite tables merely to
    # move uniqueness onto the named index itself.
    _require_unique("deals", ("opportunity_id",), "uq_deals_opportunity_id")
    _ensure_index("deals", ("opportunity_id",))
    _require_unique(
        "opportunities",
        ("opportunity_code",),
        "uq_opportunities_code",
    )
    _ensure_index("opportunities", ("opportunity_code",))


def upgrade() -> None:
    _ensure_table(
        "users",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("last_login", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    _indexes("users", ("id",))

    _ensure_table(
        "oidc_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=255), nullable=False),
        sa.Column("nonce", sa.String(length=255), nullable=False),
        sa.Column("code_verifier", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    _indexes("oidc_states", ("id",))
    _ensure_index("oidc_states", ("state",), unique=True)

    _ensure_table(
        "customer_ai_copies",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("customer_name", sa.String(), nullable=True),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("language", sa.String(), nullable=True),
        sa.Column("tone", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("extra_requirements", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("generated_by", sa.String(), nullable=True),
        sa.Column("ai_model", sa.String(), nullable=True),
        sa.Column("is_ai_generated", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    _indexes("customer_ai_copies", ("id",))

    _ensure_table(
        "customer_callbacks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=True),
        sa.Column("employee_name", sa.String(), nullable=True),
        sa.Column("created_by_employee_id", sa.Integer(), nullable=True),
        sa.Column("created_by_employee_name", sa.String(), nullable=True),
        sa.Column("completed_by_employee_id", sa.Integer(), nullable=True),
        sa.Column("completed_by_employee_name", sa.String(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("callback_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("callback_type", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("content", sa.String(), nullable=True),
        sa.Column("result", sa.String(), nullable=True),
        sa.Column("next_callback_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    _indexes("customer_callbacks", ("id",))

    _ensure_table(
        "customer_materials",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("material_type", sa.String(), nullable=False),
        sa.Column("platform", sa.String(), nullable=True),
        sa.Column("source_type", sa.String(), nullable=True),
        sa.Column("file_name", sa.String(), nullable=True),
        sa.Column("file_path", sa.String(), nullable=True),
        sa.Column("file_url", sa.Text(), nullable=True),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        sa.Column("content_type", sa.String(), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("linked_item_id", sa.Integer(), nullable=True),
        sa.Column("linked_item_snapshot", sa.String(), nullable=True),
        sa.Column("usage_status", sa.String(), nullable=True),
        sa.Column("approval_status", sa.String(), nullable=True),
        sa.Column("copyright_status", sa.String(), nullable=True),
        sa.Column("is_favorite", sa.Boolean(), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    _indexes("customer_materials", ("id",))

    _ensure_table(
        "customer_menu_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("item_type", sa.String(), nullable=True),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("price", sa.String(), nullable=True),
        sa.Column("selling_points", sa.Text(), nullable=True),
        sa.Column("suitable_platforms", sa.Text(), nullable=True),
        sa.Column("is_featured", sa.Boolean(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    _indexes("customer_menu_items", ("id",))

    _ensure_table(
        "merchant_ai_analyses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("merchant_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("analysis_json", sa.Text(), nullable=False),
        sa.Column("source_snapshot", sa.Text(), nullable=False),
        sa.Column("ai_used", sa.Boolean(), nullable=False),
        sa.Column("ai_model", sa.String(), nullable=True),
        sa.Column("generated_by_id", sa.Integer(), nullable=True),
        sa.Column("generated_by_name", sa.String(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    _indexes("merchant_ai_analyses", ("id", "merchant_id", "generated_at"))

    _ensure_table(
        "merchant_pool",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("business_name", sa.String(), nullable=False),
        sa.Column("contact_name", sa.String(), nullable=True),
        sa.Column("phone", sa.String(), nullable=True),
        sa.Column("industry", sa.String(), nullable=True),
        sa.Column("country", sa.String(), nullable=True),
        sa.Column("state", sa.String(), nullable=True),
        sa.Column("city", sa.String(), nullable=True),
        sa.Column("address", sa.String(), nullable=True),
        sa.Column("website", sa.String(), nullable=True),
        sa.Column("rating", sa.Float(), nullable=True),
        sa.Column("google_business_url", sa.String(), nullable=True),
        sa.Column("google_rating", sa.Float(), nullable=True),
        sa.Column("google_review_count", sa.Integer(), nullable=True),
        sa.Column("yelp_url", sa.String(), nullable=True),
        sa.Column("yelp_rating", sa.Float(), nullable=True),
        sa.Column("yelp_review_count", sa.Integer(), nullable=True),
        sa.Column("social_profiles", sa.Text(), nullable=True),
        sa.Column("recent_negative_reviews", sa.Text(), nullable=True),
        sa.Column("content_update_summary", sa.Text(), nullable=True),
        sa.Column("content_last_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("data_source", sa.String(), nullable=False),
        sa.Column("source_record_id", sa.String(), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("business_status", sa.String(), nullable=True),
        sa.Column("pool_status", sa.String(), nullable=False),
        sa.Column("isolation_reason", sa.String(), nullable=True),
        sa.Column("duplicate_of_id", sa.Integer(), nullable=True),
        sa.Column("existing_customer_id", sa.Integer(), nullable=True),
        sa.Column("converted_lead_id", sa.Integer(), nullable=True),
        sa.Column("raw_payload", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("created_by_name", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    _indexes(
        "merchant_pool",
        ("id", "business_name", "phone", "industry", "city", "website", "rating", "data_source", "collected_at", "pool_status"),
    )

    _ensure_table(
        "ringcentral_connections",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("employee_name", sa.String(), nullable=True),
        sa.Column("ringcentral_account_id", sa.String(), nullable=True),
        sa.Column("ringcentral_extension_id", sa.String(), nullable=True),
        sa.Column("extension_number", sa.String(), nullable=True),
        sa.Column("access_token_encrypted", sa.Text(), nullable=False),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    _indexes("ringcentral_connections", ("id", "ringcentral_account_id", "ringcentral_extension_id", "is_active"))
    _ensure_index("ringcentral_connections", ("employee_id",), unique=True)

    _ensure_table(
        "sales_call_activities",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("sales_employee_id", sa.Integer(), nullable=False),
        sa.Column("sales_employee_name", sa.String(), nullable=True),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("next_follow_up_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("call_duration_seconds", sa.Integer(), nullable=True),
        sa.Column("ringcentral_call_id", sa.String(), nullable=True),
        sa.Column("ringcentral_session_id", sa.String(), nullable=True),
        sa.Column("recording_uri", sa.Text(), nullable=True),
        sa.Column("sync_status", sa.String(), nullable=False),
        sa.Column("called_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    _indexes(
        "sales_call_activities",
        ("id", "lead_id", "sales_employee_id", "outcome", "next_follow_up_at", "ringcentral_call_id", "ringcentral_session_id", "sync_status", "called_at"),
    )

    _ensure_table(
        "sales_call_ai_analyses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("call_activity_id", sa.Integer(), nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("transcript", sa.Text(), nullable=False),
        sa.Column("transcript_source", sa.String(), nullable=False),
        sa.Column("original_analysis_json", sa.Text(), nullable=False),
        sa.Column("reviewed_analysis_json", sa.Text(), nullable=True),
        sa.Column("ai_provider", sa.String(), nullable=True),
        sa.Column("ai_model", sa.String(), nullable=True),
        sa.Column("needs_manager_intervention", sa.Boolean(), nullable=False),
        sa.Column("reviewed_by_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_by_name", sa.String(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    _indexes("sales_call_ai_analyses", ("id", "call_activity_id", "lead_id", "needs_manager_intervention"))

    _ensure_table(
        "sales_daily_dial_tasks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("sales_employee_id", sa.Integer(), nullable=False),
        sa.Column("task_date", sa.Date(), nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("dial_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_activity_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sales_employee_id", "task_date", "lead_id", name="uq_sales_daily_dial_task"),
    )
    _indexes("sales_daily_dial_tasks", ("id", "sales_employee_id", "task_date", "lead_id", "status"))
    _require_unique(
        "sales_daily_dial_tasks",
        ("sales_employee_id", "task_date", "lead_id"),
        "uq_sales_daily_dial_task",
    )

    _ensure_table(
        "sales_daily_quotas",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("sales_employee_id", sa.Integer(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("target_count", sa.Integer(), nullable=False),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_name", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sales_employee_id", "target_date", name="uq_sales_daily_quota"),
    )
    _indexes("sales_daily_quotas", ("id", "sales_employee_id", "target_date"))
    _require_unique(
        "sales_daily_quotas",
        ("sales_employee_id", "target_date"),
        "uq_sales_daily_quota",
    )

    # f6b2d8a1c904 adds product scope and billing_cycle to this base table.
    _ensure_table(
        "sales_quote_requests",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("package_name", sa.String(), nullable=False),
        sa.Column("selected_platforms", sa.Text(), nullable=True),
        sa.Column("billing_mode", sa.String(), nullable=False),
        sa.Column("payment_method", sa.String(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("list_amount", sa.Float(), nullable=False),
        sa.Column("discount_amount", sa.Float(), nullable=False),
        sa.Column("final_amount", sa.Float(), nullable=False),
        sa.Column("service_start_date", sa.String(), nullable=True),
        sa.Column("service_end_date", sa.String(), nullable=True),
        sa.Column("special_terms", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("submitted_by_id", sa.Integer(), nullable=False),
        sa.Column("submitted_by_name", sa.String(), nullable=True),
        sa.Column("reviewed_by_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_by_name", sa.String(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    _indexes("sales_quote_requests", ("id", "lead_id", "status", "submitted_by_id"))

    # f6b2d8a1c904 adds employee ownership and collaborators to this base table.
    _ensure_table(
        "sales_handoff_checklists",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("quote_id", sa.Integer(), nullable=True),
        sa.Column("customer_goal", sa.Text(), nullable=True),
        sa.Column("key_contacts", sa.Text(), nullable=True),
        sa.Column("service_start_date", sa.String(), nullable=True),
        sa.Column("service_end_date", sa.String(), nullable=True),
        sa.Column("special_commitments", sa.Text(), nullable=True),
        sa.Column("operations_owner", sa.String(), nullable=True),
        sa.Column("operations_group_created", sa.Boolean(), nullable=False),
        sa.Column("finance_payment_confirmed", sa.Boolean(), nullable=False),
        sa.Column("payment_status", sa.String(), nullable=False),
        sa.Column("amount_received", sa.Float(), nullable=False),
        sa.Column("payment_date", sa.String(), nullable=True),
        sa.Column("payment_reference", sa.String(), nullable=True),
        sa.Column("payment_confirmed_by_id", sa.Integer(), nullable=True),
        sa.Column("payment_confirmed_by_name", sa.String(), nullable=True),
        sa.Column("payment_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("generated_deal_id", sa.Integer(), nullable=True),
        sa.Column("generate_service_board", sa.Boolean(), nullable=False),
        sa.Column("handoff_notes", sa.Text(), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_name", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    _ensure_index("sales_handoff_checklists", ("lead_id",), unique=True)
    _indexes("sales_handoff_checklists", ("id", "quote_id", "generated_deal_id"))

    _ensure_table(
        "sales_knowledge_articles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("customer_question", sa.Text(), nullable=True),
        sa.Column("standard_answer", sa.Text(), nullable=False),
        sa.Column("action_steps", sa.Text(), nullable=True),
        sa.Column("related_links", sa.Text(), nullable=True),
        sa.Column("escalation_rule", sa.Text(), nullable=True),
        sa.Column("tags", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("is_sensitive", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("created_by_name", sa.String(), nullable=True),
        sa.Column("published_by_id", sa.Integer(), nullable=True),
        sa.Column("published_by_name", sa.String(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    _indexes("sales_knowledge_articles", ("id", "category", "title", "status"))

    _ensure_table(
        "sales_knowledge_questions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("submitted_by_id", sa.Integer(), nullable=True),
        sa.Column("submitted_by_name", sa.String(), nullable=True),
        sa.Column("resolved_article_id", sa.Integer(), nullable=True),
        sa.Column("resolved_by_id", sa.Integer(), nullable=True),
        sa.Column("resolved_by_name", sa.String(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    _indexes("sales_knowledge_questions", ("id", "status", "submitted_by_id", "resolved_article_id"))

    _ensure_table(
        "sales_lead_assignment_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("from_sales_employee_id", sa.Integer(), nullable=True),
        sa.Column("from_sales_employee_name", sa.String(), nullable=True),
        sa.Column("to_sales_employee_id", sa.Integer(), nullable=True),
        sa.Column("to_sales_employee_name", sa.String(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("effective_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("operated_by_id", sa.Integer(), nullable=True),
        sa.Column("operated_by_name", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    _indexes(
        "sales_lead_assignment_logs",
        ("id", "lead_id", "action", "from_sales_employee_id", "to_sales_employee_id", "effective_until", "created_at"),
    )

    _ensure_table(
        "sales_lead_conversion_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("generated_customer_code", sa.String(), nullable=False),
        sa.Column("duplicate_check_json", sa.Text(), nullable=False),
        sa.Column("lead_snapshot_json", sa.Text(), nullable=False),
        sa.Column("generate_service_board", sa.Boolean(), nullable=False),
        sa.Column("service_progress_id", sa.Integer(), nullable=True),
        sa.Column("converted_by_id", sa.Integer(), nullable=False),
        sa.Column("converted_by_name", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    _indexes("sales_lead_conversion_logs", ("id", "lead_id", "customer_id", "generated_customer_code"))

    # a7c5e9f2b104 adds automation-cycle fields and their indexes.
    _ensure_table(
        "sales_leads",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("business_name", sa.String(), nullable=False),
        sa.Column("contact_name", sa.String(), nullable=True),
        sa.Column("phone", sa.String(), nullable=False),
        sa.Column("industry", sa.String(), nullable=True),
        sa.Column("country", sa.String(), nullable=True),
        sa.Column("state", sa.String(), nullable=True),
        sa.Column("city", sa.String(), nullable=True),
        sa.Column("address", sa.String(), nullable=True),
        sa.Column("website", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("merchant_pool_id", sa.Integer(), nullable=True),
        sa.Column("analysis_snapshot", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("assigned_sales_id", sa.Integer(), nullable=True),
        sa.Column("assigned_sales_name", sa.String(), nullable=True),
        sa.Column("team_manager_id", sa.Integer(), nullable=True),
        sa.Column("is_blacklisted", sa.Boolean(), nullable=False),
        sa.Column("do_not_contact", sa.Boolean(), nullable=False),
        sa.Column("do_not_contact_reason", sa.String(), nullable=True),
        sa.Column("converted_customer_id", sa.Integer(), nullable=True),
        sa.Column("converted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("converted_by_id", sa.Integer(), nullable=True),
        sa.Column("converted_by_name", sa.String(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("next_follow_up_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_contact_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("created_by_name", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    _indexes(
        "sales_leads",
        ("id", "business_name", "phone", "merchant_pool_id", "status", "assigned_sales_id", "team_manager_id", "is_blacklisted", "do_not_contact", "converted_customer_id"),
    )

    # These four tables previously existed only through request-time DDL.
    _ensure_table(
        "app_settings",
        sa.Column("config_key", sa.Text(), nullable=False),
        sa.Column("value_json", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=False), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("config_key"),
    )
    _ensure_table(
        "monthly_deduction_rates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("year_month", sa.Date(), nullable=False),
        sa.Column("rate", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("year_month", name="uq_monthly_deduction_rates_year_month"),
        sqlite_autoincrement=True,
    )
    _require_unique(
        "monthly_deduction_rates",
        ("year_month",),
        "uq_monthly_deduction_rates_year_month",
    )
    _ensure_table(
        "monthly_deduction_defaults",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("rate", sa.Numeric(precision=5, scale=4), server_default=sa.text("0.15"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sqlite_autoincrement=True,
    )
    audit_json_type = sa.Text().with_variant(postgresql.JSONB(), "postgresql")
    _ensure_table(
        "monthly_deduction_audits",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.BigInteger(), nullable=True),
        sa.Column("before_json", audit_json_type, nullable=True),
        sa.Column("after_json", audit_json_type, nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sqlite_autoincrement=True,
    )

    _bridge_runtime_repair_columns()


def downgrade() -> None:
    raise RuntimeError(
        "e5f8a1c3d702 is intentionally irreversible: these tables and columns may "
        "contain data created before Alembic owned them. Roll back the application "
        "with a verified database backup; do not run alembic downgrade."
    )
