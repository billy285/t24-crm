from core.database import Base
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)


class CompanyStrategySettings(Base):
    __tablename__ = "company_strategy_settings"
    __table_args__ = (UniqueConstraint("settings_key", name="uq_company_strategy_settings_key"), {"extend_existing": True})

    id = Column(Integer, primary_key=True, autoincrement=True)
    settings_key = Column(String(32), nullable=False, default="company", index=True)
    target_start_date = Column(Date, nullable=False)
    target_end_date = Column(Date, nullable=False)
    five_year_profit_target_cny = Column(Numeric(18, 2), nullable=False, default=20_000_000)
    monthly_fixed_expense_cny = Column(Numeric(18, 2), nullable=False, default=30_000)
    cash_reserve_months = Column(Integer, nullable=False, default=6)
    default_usd_cny_rate = Column(Numeric(12, 4), nullable=False, default=6.7)
    current_focus = Column(String(240), nullable=True)
    updated_by = Column(String(160), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class CashAccount(Base):
    __tablename__ = "cash_accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(160), nullable=False)
    account_type = Column(String(32), nullable=False, default="bank")
    currency = Column(String(3), nullable=False, default="CNY", index=True)
    masked_identifier = Column(String(80), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    sort_order = Column(Integer, nullable=False, default=0)
    notes = Column(Text, nullable=True)
    created_by = Column(String(160), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        Index(
            "uq_cash_accounts_active_name_currency",
            func.lower(func.trim(name)),
            currency,
            unique=True,
            sqlite_where=is_active.is_(True),
            postgresql_where=is_active.is_(True),
        ),
        {"extend_existing": True},
    )


class CashPeriod(Base):
    __tablename__ = "cash_periods"
    __table_args__ = (UniqueConstraint("year_month", name="uq_cash_period_year_month"), {"extend_existing": True})

    id = Column(Integer, primary_key=True, autoincrement=True)
    year_month = Column(String(7), nullable=False, index=True)
    version = Column(Integer, nullable=False, default=1)
    snapshot_date = Column(Date, nullable=False)
    status = Column(String(24), nullable=False, default="draft", index=True)
    usd_cny_rate = Column(Numeric(12, 4), nullable=False)
    notes = Column(Text, nullable=True)
    locked_at = Column(DateTime(timezone=True), nullable=True)
    locked_by = Column(String(160), nullable=True)
    reopened_at = Column(DateTime(timezone=True), nullable=True)
    reopened_by = Column(String(160), nullable=True)
    reopen_reason = Column(Text, nullable=True)
    created_by = Column(String(160), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class CashAccountBalance(Base):
    __tablename__ = "cash_account_balances"
    __table_args__ = (UniqueConstraint("period_id", "account_id", name="uq_cash_balance_period_account"), {"extend_existing": True})

    id = Column(Integer, primary_key=True, autoincrement=True)
    period_id = Column(Integer, ForeignKey("cash_periods.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("cash_accounts.id", ondelete="RESTRICT"), nullable=False, index=True)
    account_name = Column(String(160), nullable=True)
    account_type = Column(String(32), nullable=True)
    masked_identifier = Column(String(80), nullable=True)
    currency = Column(String(3), nullable=False)
    balance = Column(Numeric(18, 2), nullable=False, default=0)
    confirmed_zero = Column(Boolean, nullable=False, default=False)
    rate_to_cny = Column(Numeric(12, 4), nullable=False, default=1)
    balance_cny = Column(Numeric(18, 2), nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class CashRestriction(Base):
    __tablename__ = "cash_restrictions"
    __table_args__ = (
        UniqueConstraint("period_id", "source_ref", name="uq_cash_restriction_period_source"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    period_id = Column(Integer, ForeignKey("cash_periods.id", ondelete="CASCADE"), nullable=False, index=True)
    category = Column(String(40), nullable=False, index=True)
    description = Column(String(240), nullable=False)
    currency = Column(String(3), nullable=False)
    amount = Column(Numeric(18, 2), nullable=False, default=0)
    rate_to_cny = Column(Numeric(12, 4), nullable=False, default=1)
    amount_cny = Column(Numeric(18, 2), nullable=False, default=0)
    source_ref = Column(String(160), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class CashAuditLog(Base):
    __tablename__ = "cash_audit_logs"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    period_id = Column(Integer, ForeignKey("cash_periods.id", ondelete="CASCADE"), nullable=False, index=True)
    action = Column(String(48), nullable=False, index=True)
    actor_id = Column(String(64), nullable=False)
    actor_name = Column(String(160), nullable=True)
    actor_role = Column(String(32), nullable=False)
    reason = Column(Text, nullable=True)
    snapshot_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class StrategyRecommendationDecision(Base):
    __tablename__ = "strategy_recommendation_decisions"
    __table_args__ = (UniqueConstraint("recommendation_key", name="uq_strategy_recommendation_key"), {"extend_existing": True})

    id = Column(Integer, primary_key=True, autoincrement=True)
    recommendation_key = Column(String(80), nullable=False, index=True)
    title = Column(String(240), nullable=False)
    rationale = Column(Text, nullable=True)
    recommended_action = Column(Text, nullable=True)
    status = Column(String(24), nullable=False, default="accepted", index=True)
    decision_note = Column(Text, nullable=True)
    next_review_date = Column(Date, nullable=True)
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True)
    decided_by_id = Column(String(64), nullable=True)
    decided_by_name = Column(String(160), nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
