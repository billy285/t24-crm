"""Bounded private work without Python 3.11 asyncio APIs; synthetic inputs only."""
import asyncio
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

from models.private_workspace import PrivateMailBrief, PrivateMailTranslation, PrivateWorkspaceBrief
from services import private_bank_provider as bank
from services import private_mail_brief_service as mail
from services import private_mail_translation_service as translation
from test_private_bank_provider import bank_config, BankMock
from test_private_mail_brief_service import workspace, money_usage
from test_private_mail_translation_service import workspace as translation_workspace
from test_private_workspace_brief import boss, get, generate


class LegacyAsyncTimeout(Exception):
    """In Python 3.10 asyncio.TimeoutError differed from builtins.TimeoutError."""


@pytest.fixture
def old_asyncio(monkeypatch):
    original = asyncio.wait_for
    state = SimpleNamespace(original=original, short=False, calls=[])
    monkeypatch.delattr(asyncio, 'timeout', raising=False)
    monkeypatch.setattr(asyncio, 'TimeoutError', LegacyAsyncTimeout)

    async def wait_for(coro, timeout):
        state.calls.append(timeout)
        try:
            return await original(coro, min(timeout, 0.08) if state.short else timeout)
        except TimeoutError:
            raise LegacyAsyncTimeout() from None

    monkeypatch.setattr(asyncio, 'wait_for', wait_for)
    return state


async def blocked(cleanup, entered=None):
    if entered is not None: entered.set()
    try: await asyncio.Future()
    finally: cleanup.append('canceled-and-awaited')


@pytest.mark.asyncio
async def test_translation_success_without_new_asyncio_timeout(translation_workspace, old_asyncio):
    async with translation_workspace.sessions() as db:
        result = await translation.translate_item(db, '4', translation_workspace.ids['mail'], mode='body')
    assert result['translation']['state'] == 'ready' and old_asyncio.calls == [55]


@pytest.mark.asyncio
async def test_mail_brief_success_without_new_asyncio_timeout(workspace, old_asyncio):
    async with workspace.sessions() as db: result = await mail.brief_item(db, '4', workspace.ids['mail'])
    assert result['brief']['state'] == 'ready' and old_asyncio.calls == [55]


@pytest.mark.asyncio
async def test_workspace_brief_success_without_new_asyncio_timeout(boss, old_asyncio, monkeypatch):
    monkeypatch.setenv('PRIVATE_WORKSPACE_BRIEF_EXTERNAL_CONSENT', 'true')
    result = await generate(boss, await get(boss))
    assert result['ai']['state'] == 'ready' and old_asyncio.calls == [55]


@pytest.mark.asyncio
async def test_bank_request_success_without_new_asyncio_timeout(bank_config, old_asyncio):
    provider = BankMock()
    async with bank.BankClient(bank.bank_settings(), provider.transport) as client:
        result = await client.request('/item/get', {'access_token': 'synthetic-access'})
    assert result['item']['item_id'] == 'synthetic_bank_item'
    assert len(old_asyncio.calls) == 1 and 0 < old_asyncio.calls[0] <= bank.MAX_SECONDS


@pytest.mark.asyncio
async def test_translation_legacy_timeout_cancels_work_and_marks_failed(translation_workspace, old_asyncio):
    cleanup = []; translation_workspace.hooks.append(lambda: blocked(cleanup)); old_asyncio.short = True
    async with translation_workspace.sessions() as db:
        result = await translation.translate_item(db, '4', translation_workspace.ids['mail'], mode='preview')
        row = (await db.execute(select(PrivateMailTranslation))).scalar_one()
    assert result['code'] == 'upstream_unavailable' and result['translation']['state'] == 'failed'
    assert cleanup == ['canceled-and-awaited'] and row.state == 'failed' and row.encrypted_content is None


@pytest.mark.asyncio
async def test_mail_brief_legacy_timeout_keeps_uncertain_budget_reserved(workspace, old_asyncio):
    cleanup = []; workspace.hooks.append(lambda: blocked(cleanup)); old_asyncio.short = True
    async with workspace.sessions() as db:
        result = await mail.brief_item(db, '4', workspace.ids['mail'])
        row = (await db.execute(select(PrivateMailBrief))).scalar_one()
    assert result['code'] == 'upstream_unavailable' and result['brief']['state'] == 'failed'
    assert cleanup == ['canceled-and-awaited'] and row.state == 'failed' and row.encrypted_content is None
    assert row.reservation_state == 'held' and await money_usage(workspace) == 421911


@pytest.mark.asyncio
async def test_workspace_legacy_timeout_keeps_shared_budget_reserved(boss, old_asyncio, monkeypatch):
    monkeypatch.setenv('PRIVATE_WORKSPACE_BRIEF_EXTERNAL_CONSENT', 'true')
    cleanup = []; boss.boss_hooks.append(lambda: blocked(cleanup)); old_asyncio.short = True
    result = await generate(boss, await get(boss))
    async with boss.sessions() as db: row = (await db.execute(select(PrivateWorkspaceBrief))).scalar_one()
    assert result['ai']['code'] == 'upstream_unavailable' and result['ai']['state'] == 'failed'
    assert cleanup == ['canceled-and-awaited'] and row.state == 'failed' and row.encrypted_content is None
    assert row.reservation_state == 'held' and await money_usage(boss) == 421911


class BlockingStream(httpx.AsyncByteStream):
    def __init__(self, cleanup, entered=None): self.cleanup = cleanup; self.entered = entered
    async def __aiter__(self):
        await blocked(self.cleanup, self.entered)
        yield b'{}'
    async def aclose(self): self.cleanup.append('stream-closed')


@pytest.mark.asyncio
async def test_bank_legacy_timeout_closes_response_stream(bank_config, old_asyncio):
    cleanup = []; old_asyncio.short = True
    transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=BlockingStream(cleanup)))
    async with bank.BankClient(bank.bank_settings(), transport) as client:
        with pytest.raises(bank.BankProviderError) as error:
            await client.request('/item/get', {'access_token': 'synthetic-access'})
    assert error.value.code == 'bank_upstream_timeout' and cleanup == ['canceled-and-awaited', 'stream-closed']


async def cancel_inflight(call, entered, old_asyncio):
    task = asyncio.create_task(call())
    await old_asyncio.original(entered.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task


@pytest.mark.asyncio
async def test_translation_external_cancellation_propagates_after_child_cleanup(translation_workspace, old_asyncio):
    cleanup = []; entered = asyncio.Event(); translation_workspace.hooks.append(lambda: blocked(cleanup, entered))
    async def call():
        async with translation_workspace.sessions() as db:
            return await translation.translate_item(db, '4', translation_workspace.ids['mail'], mode='preview')
    await cancel_inflight(call, entered, old_asyncio)
    async with translation_workspace.sessions() as db: row = (await db.execute(select(PrivateMailTranslation))).scalar_one()
    assert cleanup == ['canceled-and-awaited'] and row.state == 'pending' and row.encrypted_content is None


@pytest.mark.asyncio
async def test_mail_external_cancellation_cannot_save_success_or_refund_uncertain_usage(workspace, old_asyncio):
    cleanup = []; entered = asyncio.Event(); workspace.hooks.append(lambda: blocked(cleanup, entered))
    async def call():
        async with workspace.sessions() as db: return await mail.brief_item(db, '4', workspace.ids['mail'])
    await cancel_inflight(call, entered, old_asyncio)
    async with workspace.sessions() as db: row = (await db.execute(select(PrivateMailBrief))).scalar_one()
    assert cleanup == ['canceled-and-awaited'] and row.state == 'pending' and row.encrypted_content is None
    assert row.reservation_state == 'held' and await money_usage(workspace) == 421911


@pytest.mark.asyncio
async def test_workspace_external_cancellation_cannot_save_success_or_refund_shared_usage(boss, old_asyncio, monkeypatch):
    monkeypatch.setenv('PRIVATE_WORKSPACE_BRIEF_EXTERNAL_CONSENT', 'true')
    cleanup = []; entered = asyncio.Event(); boss.boss_hooks.append(lambda: blocked(cleanup, entered))
    data = await get(boss); await cancel_inflight(lambda: generate(boss, data), entered, old_asyncio)
    async with boss.sessions() as db: row = (await db.execute(select(PrivateWorkspaceBrief))).scalar_one()
    assert cleanup == ['canceled-and-awaited'] and row.state == 'pending' and row.encrypted_content is None
    assert row.reservation_state == 'held' and await money_usage(boss) == 421911


@pytest.mark.asyncio
async def test_bank_external_cancellation_closes_stream_and_propagates(bank_config, old_asyncio):
    cleanup = []; entered = asyncio.Event()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=BlockingStream(cleanup, entered)))
    async with bank.BankClient(bank.bank_settings(), transport) as client:
        await cancel_inflight(lambda: client.request('/item/get', {'access_token': 'synthetic-access'}), entered, old_asyncio)
    assert cleanup == ['canceled-and-awaited', 'stream-closed']
