from sqlalchemy.ext.asyncio import AsyncSession


def is_sqlite(session: AsyncSession) -> bool:
    bind = session.get_bind()
    return bool(bind and bind.dialect.name == "sqlite")


def current_timestamp_sql(session: AsyncSession) -> str:
    return "CURRENT_TIMESTAMP" if is_sqlite(session) else "NOW()"
