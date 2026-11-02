"""Opt-in private draft worker, independent of Google/Meta publication workers."""
import asyncio
import contextlib
from services import media_monthly_automation as service


async def run_worker():
    while service.enabled():
        try: await service.run_tick()
        except asyncio.CancelledError: raise
        except Exception: pass  # no provider response or merchant data in logs
        await asyncio.sleep(60)


def start_worker(): return asyncio.create_task(run_worker()) if service.enabled() else None


async def stop_worker(task):
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError): await task
