from sqlalchemy.ext.asyncio import AsyncSession


def is_sqlite(session: AsyncSession) -> bool:
    bind = session.get_bind()
    return bool(bind and bind.dialect.name == "sqlite")


def current_timestamp_sql(session: AsyncSession) -> str:
    return "CURRENT_TIMESTAMP" if is_sqlite(session) else "NOW()"


def create_rates_sql(session: AsyncSession) -> str:
    if is_sqlite(session):
        return """
CREATE TABLE IF NOT EXISTS monthly_deduction_rates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  year_month DATE UNIQUE NOT NULL,
  rate NUMERIC(5,4) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

    return """
CREATE TABLE IF NOT EXISTS monthly_deduction_rates (
  id SERIAL PRIMARY KEY,
  year_month DATE UNIQUE NOT NULL,
  rate NUMERIC(5,4) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""


def create_default_sql(session: AsyncSession) -> str:
    if is_sqlite(session):
        return """
CREATE TABLE IF NOT EXISTS monthly_deduction_defaults (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  rate NUMERIC(5,4) NOT NULL DEFAULT 0.15,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

    return """
CREATE TABLE IF NOT EXISTS monthly_deduction_defaults (
  id SERIAL PRIMARY KEY,
  rate NUMERIC(5,4) NOT NULL DEFAULT 0.15,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""


def create_audit_sql(session: AsyncSession) -> str:
    if is_sqlite(session):
        return """
CREATE TABLE IF NOT EXISTS monthly_deduction_audits (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  action TEXT NOT NULL,
  actor_id BIGINT,
  before_json TEXT,
  after_json TEXT,
  at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

    return """
CREATE TABLE IF NOT EXISTS monthly_deduction_audits (
  id SERIAL PRIMARY KEY,
  action TEXT NOT NULL,
  actor_id BIGINT,
  before_json JSONB,
  after_json JSONB,
  at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""
