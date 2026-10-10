"""Run private monitoring separately from CRM jobs; the business DB is read-only.

Start with ``python -m services.private_workspace_worker`` from backend/.
No CRM startup, mock data, migrations, or finance services are imported.
"""
import asyncio
import logging
import os
import signal
from contextlib import aclosing
from pathlib import Path

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.config import settings
from services.private_workspace import (
    close_private_workspace_storage, get_private_db, sync_due_sources,
)

logger = logging.getLogger(__name__)


def business_reader_url(raw_url: str) -> str:
    url = make_url(raw_url)
    if url.get_backend_name() == 'sqlite':
        if not url.database or url.database == ':memory:':
            raise ValueError('Monitoring requires an existing business database')
        path = Path(url.database).expanduser().resolve()
        if not path.is_file():
            raise ValueError('Business database was not found; monitoring will not create one')
        url = url.set(drivername='sqlite+aiosqlite', database=f'file:{path}')
        url = url.update_query_dict({'mode': 'ro', 'uri': 'true'})
        return url.render_as_string(hide_password=False)
    if url.get_backend_name() in {'postgresql', 'postgres'}:
        return url.set(drivername='postgresql+asyncpg').render_as_string(hide_password=False)
    raise ValueError('Private monitoring supports read-only SQLite or PostgreSQL identity checks')


def create_business_reader():
    raw = os.environ.get('DATABASE_URL') or settings.database_url
    url = business_reader_url(raw)
    options = {'server_settings': {'default_transaction_read_only': 'on'}} if make_url(url).get_backend_name() == 'postgresql' else {}
    return create_async_engine(url, connect_args=options, echo=False)


async def run_once(sessions):
    async with sessions() as business_db:
        async with aclosing(get_private_db()) as private_sessions:
            async for private_db in private_sessions:
                return await sync_due_sources(business_db, private_db)


async def run():
    engine = create_business_reader()
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in ('SIGINT', 'SIGTERM'):
        try:
            loop.add_signal_handler(getattr(signal, name), stopped.set)
        except (NotImplementedError, RuntimeError):
            pass
    try:
        while not stopped.is_set():
            try:
                counts = await run_once(sessions)
                logger.info('Private monitoring cycle: attempted=%s succeeded=%s failed=%s skipped=%s',
                            counts['attempted'], counts['succeeded'], counts['failed'], counts['skipped'])
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Provider bodies, tokens, owner identities and bank/email data stay out of logs.
                logger.error('Private monitoring cycle failed (%s)', type(exc).__name__)
            try:
                await asyncio.wait_for(stopped.wait(), timeout=60)
            except asyncio.TimeoutError:
                pass
    finally:
        await close_private_workspace_storage()
        await engine.dispose()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
