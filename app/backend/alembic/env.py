#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Desc   :

import asyncio
import importlib
import pkgutil
from logging.config import fileConfig

import models
from alembic import context
from core.config import settings
from core.database import Base
from sqlalchemy import pool
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

# Automatically import all ORM models under Models
for _, module_name, _ in pkgutil.iter_modules(models.__path__):
    importlib.import_module(f"{models.__name__}.{module_name}")

config = context.config


def _async_database_url(raw_url: str) -> str:
    """Use the configured application database with an asyncio driver."""
    url = make_url(raw_url)
    if url.drivername == "sqlite":
        url = url.set(drivername="sqlite+aiosqlite")
    elif url.drivername in ("postgres", "postgresql"):
        url = url.set(drivername="postgresql+asyncpg")
    rendered = url.render_as_string(hide_password=False)
    return rendered.replace("%", "%%")


config.set_main_option("sqlalchemy.url", _async_database_url(settings.database_url))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


# These tables are intentionally owned by explicit SQL contracts rather than
# ORM models.  They are migrated, but must not be interpreted as removals by
# ``alembic check``.
NON_ORM_PERSISTENT_TABLES = {
    "app_settings",
    "monthly_deduction_rates",
    "monthly_deduction_defaults",
    "monthly_deduction_audits",
}

# Preserve the one legacy database-only column instead of letting
# autogenerate suggest a destructive drop.  New reflected-only columns remain
# visible to ``alembic check`` unless deliberately documented here.
LEGACY_DATABASE_ONLY_COLUMNS = {("expense_categories", "user_id")}


def alembic_include_object(object, name, type_, reflected, compare_to):
    if type_ == "table" and name in NON_ORM_PERSISTENT_TABLES:
        return False
    if type_ == "column" and reflected and compare_to is None:
        table_name = getattr(getattr(object, "table", None), "name", None)
        if (table_name, name) in LEGACY_DATABASE_ONLY_COLUMNS:
            return False
    return True


def alembic_compare_server_default(*_args, **_kwargs):
    """Ignore Python-default versus historical server-default noise.

    The legacy models deliberately use application-side defaults while older
    migrations use server defaults for safe backfills.  Column/table/index/FK
    drift remains fully checked.
    """

    return False


def _configure_context(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=alembic_compare_server_default,
        include_object=alembic_include_object,
    )


async def run_migrations_online():
    connectable = create_async_engine(config.get_main_option("sqlalchemy.url"), poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(_configure_context)
        async with connection.begin():
            await connection.run_sync(lambda sync_conn: context.run_migrations())
    await connectable.dispose()


def run_migrations():
    try:
        # If there is no event loop currently, use asyncio.run directly
        loop = asyncio.get_running_loop()
        loop.create_task(run_migrations_online())
    except RuntimeError:
        asyncio.run(run_migrations_online())


run_migrations()
