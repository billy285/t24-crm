"""The monitor must never create or mutate the CRM database."""
import sqlite3

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from services.private_workspace_worker import business_reader_url


def test_missing_business_database_does_not_get_created(tmp_path):
    file = tmp_path / 'missing.db'
    with pytest.raises(ValueError, match='not found'):
        business_reader_url(f'sqlite:///{file}')
    assert not file.exists()


@pytest.mark.asyncio
async def test_sqlite_identity_connection_is_physically_read_only(tmp_path):
    file = tmp_path / 'business.db'
    with sqlite3.connect(file) as db:
        db.execute('CREATE TABLE financial_sentinel (amount INTEGER)')
        db.execute('INSERT INTO financial_sentinel VALUES (70000)')
    engine = create_async_engine(business_reader_url(f'sqlite:///{file}'))
    try:
        async with engine.connect() as db:
            assert (await db.execute(text('SELECT amount FROM financial_sentinel'))).scalar_one() == 70000
            with pytest.raises(Exception, match='readonly'):
                await db.execute(text('UPDATE financial_sentinel SET amount = 0'))
    finally:
        await engine.dispose()
    with sqlite3.connect(file) as db:
        assert db.execute('SELECT amount FROM financial_sentinel').fetchone()[0] == 70000


def test_postgresql_reader_uses_async_driver():
    assert business_reader_url('postgresql://fixture:synthetic@localhost/private_test').startswith('postgresql+asyncpg://')
