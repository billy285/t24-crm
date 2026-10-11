"""Owner authorization, session leases and bank delta commits in an independent fixture DB."""
from copy import deepcopy
from datetime import timedelta
import json
from types import SimpleNamespace

from fastapi import HTTPException
import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models.private_workspace import PrivateBankLink, PrivateConnection, PrivateItem, PrivateWorkspaceBase, utcnow
from services import private_bank_provider as bank, private_bank_service as service, private_workspace as core
from test_private_bank_provider import bank_config, BankMock, credentials, account, transaction, sync_page, ITEM, INSTITUTION, ACCESS, LINK, PUBLIC


@pytest_asyncio.fixture
async def private_bank_db(bank_config, tmp_path):
    engine = create_async_engine('sqlite+aiosqlite:///' + str(tmp_path / 'synthetic_private.db'))
    async with engine.begin() as connection:
        await connection.run_sync(PrivateWorkspaceBase.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as db:
            yield SimpleNamespace(db=db, sessions=sessions)
    finally:
        await engine.dispose()


async def row_for(db):
    return (await db.execute(select(PrivateConnection).where(PrivateConnection.source_id == 'bofa_bank')
                            .execution_options(populate_existing=True))).scalar_one()


async def link_for(db, session_id):
    return (await db.execute(select(PrivateBankLink).where(PrivateBankLink.id == session_id)
                            .execution_options(populate_existing=True))).scalar_one()


async def connected(db, mock):
    begin = await service.begin_bank_link(db, '4', transport=mock.transport)
    result = await service.complete_bank_link(db, '4', begin['session_id'], transport=mock.transport)
    assert result['state'] == 'connected'
    return await row_for(db)


@pytest.mark.asyncio
async def test_owner_hosted_session_is_encrypted_reusable_and_completion_idempotent(private_bank_db):
    db = private_bank_db.db; mock = BankMock()
    first = await service.begin_bank_link(db, '4', transport=mock.transport)
    second = await service.begin_bank_link(db, '4', transport=mock.transport)
    assert first == second and first['mode'] == 'production' and len(mock.calls) == 1
    row = await link_for(db, first['session_id'])
    assert LINK not in row.encrypted_context and PUBLIC not in row.encrypted_context and ACCESS not in row.encrypted_context
    assert 'public_token' not in core.decrypt_credentials(row.encrypted_context)
    assert core.decrypt_credentials(row.encrypted_context)['authorization_url'] == first['authorization_url']
    result = await service.complete_bank_link(db, '4', first['session_id'], transport=mock.transport)
    again = await service.complete_bank_link(db, '4', first['session_id'], transport=mock.transport)
    assert result == again and len(mock.calls) == 5
    row = await link_for(db, first['session_id']); connection = await row_for(db)
    assert row.state == 'completed' and row.encrypted_context is None and row.lease_until is None
    assert connection.status == 'connected' and ACCESS not in connection.encrypted_credentials
    assert core.decrypt_credentials(connection.encrypted_credentials)['access_token'] == ACCESS
    assert service.bank_connection_identity(connection, require_snapshot=False)['item_id'] == ITEM
    assert service.bank_connection_identity(connection) is None  # authorization is not a balance snapshot


@pytest.mark.asyncio
async def test_incomplete_redirect_poll_has_no_exchange_and_retains_reusable_link(private_bank_db):
    db = private_bank_db.db; mock = BankMock(); mock.link_results = []
    start = await service.begin_bank_link(db, '4', transport=mock.transport)
    result = await service.complete_bank_link(db, '4', start['session_id'], transport=mock.transport)
    assert result['state'] == 'pending'
    row = await link_for(db, start['session_id'])
    assert row.state == 'pending' and row.lease_until is None and row.encrypted_context
    assert (await service.begin_bank_link(db, '4', transport=mock.transport))['session_id'] == start['session_id']
    assert [r.url.path for r in mock.calls] == ['/link/token/create', '/link/token/get']


@pytest.mark.asyncio
async def test_expired_session_cannot_complete_and_next_begin_creates_one_new_link(private_bank_db):
    db = private_bank_db.db; mock = BankMock()
    start = await service.begin_bank_link(db, '4', transport=mock.transport)
    await db.execute(update(PrivateBankLink).where(PrivateBankLink.id == start['session_id']).values(expires_at=utcnow() - timedelta(seconds=1)))
    await db.commit()
    with pytest.raises(HTTPException) as error: await service.complete_bank_link(db, '4', start['session_id'], transport=mock.transport)
    assert error.value.status_code == 409
    row = await link_for(db, start['session_id'])
    assert row.state == 'expired' and row.encrypted_context is None and len(mock.calls) == 1
    next_start = await service.begin_bank_link(db, '4', transport=mock.transport)
    assert next_start['session_id'] != start['session_id'] and len(mock.calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['begin', 'complete'])
async def test_other_owners_cannot_connect_or_complete(private_bank_db, operation):
    db = private_bank_db.db; mock = BankMock()
    start = await service.begin_bank_link(db, '4', transport=mock.transport)
    with pytest.raises(HTTPException) as error:
        if operation == 'begin': await service.begin_bank_link(db, '5', transport=mock.transport)
        else: await service.complete_bank_link(db, '5', start['session_id'], transport=mock.transport)
    assert error.value.status_code == 403 and len(mock.calls) == 1


@pytest.mark.asyncio
async def test_revoked_owner_after_begin_network_clears_context_without_connected_write(private_bank_db):
    db = private_bank_db.db; mock = BankMock(); checks = 0
    async def owner():
        nonlocal checks
        checks += 1
        return checks < 2
    with pytest.raises(HTTPException) as error: await service.begin_bank_link(db, '4', transport=mock.transport, owner_validator=owner)
    assert error.value.status_code == 403
    connection = await row_for(db)
    row = (await db.execute(select(PrivateBankLink))).scalar_one()
    assert connection.status == 'disconnected' and connection.encrypted_credentials is None
    assert row.state == 'canceled' and row.encrypted_context is None


@pytest.mark.asyncio
async def test_revoked_owner_after_exchange_clears_staged_access_token(private_bank_db):
    db = private_bank_db.db; mock = BankMock()
    start = await service.begin_bank_link(db, '4', transport=mock.transport)
    checks = 0
    async def owner():
        nonlocal checks
        checks += 1
        return checks < 3  # initial check and stage pass; final verification fails
    with pytest.raises(HTTPException) as error: await service.complete_bank_link(db, '4', start['session_id'], transport=mock.transport, owner_validator=owner)
    assert error.value.status_code == 403
    row = await link_for(db, start['session_id']); connection = await row_for(db)
    assert row.state == 'canceled' and row.encrypted_context is None
    assert connection.status == 'disconnected' and connection.encrypted_credentials is None


@pytest.mark.asyncio
async def test_generation_change_during_external_exchange_cannot_write_connected(private_bank_db):
    db = private_bank_db.db; mock = BankMock()
    start = await service.begin_bank_link(db, '4', transport=mock.transport)
    async def handler(request):
        if request.url.path == '/item/public_token/exchange':
            async with private_bank_db.sessions() as other:
                await other.execute(update(PrivateConnection).values(generation=99, status='disconnected', encrypted_credentials=None))
                await other.commit()
        return await mock(request)
    with pytest.raises(HTTPException) as error:
        await service.complete_bank_link(db, '4', start['session_id'], transport=httpx.MockTransport(handler))
    assert error.value.status_code == 409
    connection = await row_for(db); row = await link_for(db, start['session_id'])
    assert connection.generation == 99 and connection.status == 'disconnected' and connection.encrypted_credentials is None
    assert row.encrypted_context is None


@pytest.mark.asyncio
async def test_active_lease_prevents_duplicate_exchange_or_new_hosted_item(private_bank_db):
    db = private_bank_db.db; mock = BankMock()
    start = await service.begin_bank_link(db, '4', transport=mock.transport)
    await db.execute(update(PrivateBankLink).where(PrivateBankLink.id == start['session_id']).values(
        state='exchanging', lease_until=utcnow() + timedelta(seconds=60)))
    await db.commit()
    assert (await service.complete_bank_link(db, '4', start['session_id'], transport=mock.transport))['state'] == 'pending'
    with pytest.raises(HTTPException) as error: await service.begin_bank_link(db, '4', transport=mock.transport)
    assert error.value.status_code == 409 and len(mock.calls) == 1


@pytest.mark.asyncio
async def test_retryable_verification_resumes_encrypted_stage_without_double_exchange(private_bank_db):
    db = private_bank_db.db; mock = BankMock()
    start = await service.begin_bank_link(db, '4', transport=mock.transport)
    mock.overrides['/item/get'] = httpx.Response(503, json={'error_code': 'INSTITUTION_DOWN', 'error_message': ACCESS})
    with pytest.raises(HTTPException) as error: await service.complete_bank_link(db, '4', start['session_id'], transport=mock.transport)
    assert error.value.status_code == 502 and ACCESS not in str(error.value)
    row = await link_for(db, start['session_id'])
    staged = core.decrypt_credentials(row.encrypted_context)
    assert row.state == 'pending' and staged['access_token'] == ACCESS and 'public_token' not in staged
    mock.overrides.clear()
    assert (await service.complete_bank_link(db, '4', start['session_id'], transport=mock.transport))['state'] == 'connected'
    assert len([r for r in mock.calls if r.url.path == '/item/public_token/exchange']) == 1
    assert len([r for r in mock.calls if r.url.path == '/link/token/get']) == 1


@pytest.mark.asyncio
async def test_current_condition_keeps_incremental_history_hides_removed_and_old_identity(private_bank_db):
    db = private_bank_db.db; mock = BankMock(); connection = await connected(db, mock)
    fetched = await bank.fetch_bofa_bank(core.decrypt_credentials(connection.encrypted_credentials), transport=mock.transport)
    service.validate_bank_batch(connection, fetched, utcnow() - timedelta(seconds=1))
    connection.metadata_json = fetched['metadata']; connection.last_sync = utcnow()
    await db.commit()
    evidence = fetched['items'][0]['evidence']
    for name, state, changes in [
        ('current', 'posted', {}), ('earlier-snapshot', 'pending', {'bank_snapshot_id': 'a' * 32}),
        ('removed', 'removed', {}), ('replaced', 'replaced', {}),
        ('old-item', 'posted', {'bank_item_id': 'different_item'}), ('old-env', 'posted', {'bank_environment': 'sandbox'}),
        ('old-bank', 'posted', {'bank_institution_id': 'ins_different'}),
    ]:
        db.add(PrivateItem(owner_id='4', source_id='bofa_bank', external_id=name, title=name, kind='bank_transaction',
                           summary='', status=state, evidence={**evidence, **changes}))
    await db.commit()
    condition = await service.current_bank_condition(db, '4')
    values = (await db.execute(select(PrivateItem.title).where(condition))).scalars().all()
    assert set(values) == {'current', 'earlier-snapshot'}
    assert not (await db.execute(select(PrivateItem.id).where(await service.current_bank_condition(db, '5')))).all()


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation', ['item', 'env', 'snapshot', 'account', 'removed_scope', 'token', 'owner', 'observed', 'balance', 'direction'])
async def test_batch_binding_validation_prevents_cross_account_and_cursor_credential_overwrite(private_bank_db, mutation):
    db = private_bank_db.db; mock = BankMock(); connection = await connected(db, mock)
    batch = await bank.fetch_bofa_bank(core.decrypt_credentials(connection.encrypted_credentials), transport=mock.transport)
    service.validate_bank_batch(connection, batch, utcnow() - timedelta(seconds=1))
    changed = deepcopy(batch)
    if mutation == 'item': changed['metadata']['bank_item_id'] = 'other_item'
    elif mutation == 'env': changed['metadata']['bank_environment'] = 'sandbox'
    elif mutation == 'snapshot': changed['items'][0]['evidence']['bank_snapshot_id'] = 'f' * 32
    elif mutation == 'account': changed['items'][0]['evidence']['bank_account_id'] = 'other_account'
    elif mutation == 'removed_scope': changed['removed_external_ids'] = ['other_item:transaction']
    elif mutation == 'token': changed['credentials']['access_token'] = 'access-production-other_key'
    elif mutation == 'owner': changed['credentials']['owner_id'] = '5'
    elif mutation == 'observed': changed['metadata']['bank_snapshot']['observed_at'] = '2020-01-01T00:00:00+00:00'
    elif mutation == 'balance': changed['metadata']['bank_accounts'][0]['current_minor'] = True
    elif mutation == 'direction': changed['items'][0]['evidence']['amount_direction'] = 'inflow'
    with pytest.raises((ValueError, bank.BankProviderError)):
        service.validate_bank_batch(connection, changed, utcnow() - timedelta(seconds=1))


@pytest.mark.asyncio
async def test_core_sync_cursor_deltas_soft_removals_and_local_actions_commit_together(private_bank_db, monkeypatch):
    db = private_bank_db.db; mock = BankMock([sync_page(added=[transaction('pending_tx', pending=True), transaction('delete_tx')], cursor='cursor_one')])
    await connected(db, mock)
    registry = core.providers()
    async def fetch(source_id, auth, metadata):
        assert source_id == 'bofa_bank'
        return await bank.fetch_bofa_bank(auth, transport=mock.transport)
    monkeypatch.setattr(core, 'providers', lambda: SimpleNamespace(fetch_source=fetch, describe_sources=registry.describe_sources))
    first = await core.sync_source(db, '4', 'bofa_bank')
    assert first['counts']['created'] == 2
    await db.execute(update(PrivateItem).where(PrivateItem.external_id.in_([ITEM + ':pending_tx', ITEM + ':delete_tx'])).values(
        action_status='done', local_summary='Owner private follow-up'))
    # Older institution history with the same transaction id must remain untouched.
    db.add(PrivateItem(owner_id='4', source_id='bofa_bank', external_id='old_item:delete_tx', kind='bank_transaction',
                       title='Old source', summary='', status='posted', evidence={'bank_item_id': 'old_item',
                       'bank_environment': 'production', 'bank_institution_id': INSTITUTION}))
    await db.commit()
    mock.pages = [sync_page(added=[transaction('posted_tx', pending_transaction_id='pending_tx', amount=-10)],
                            removed=[{'transaction_id': 'delete_tx', 'account_id': 'synthetic_checking'}], cursor='cursor_two')]
    await core.sync_source(db, '4', 'bofa_bank')
    connection = await row_for(db)
    assert core.decrypt_credentials(connection.encrypted_credentials)['transaction_cursor'] == 'cursor_two'
    records = (await db.execute(select(PrivateItem).execution_options(populate_existing=True))).scalars().all()
    mapped = {row.external_id: row for row in records}
    assert mapped[ITEM + ':pending_tx'].status == 'replaced' and mapped[ITEM + ':delete_tx'].status == 'removed'
    assert mapped[ITEM + ':pending_tx'].action_status == 'done' and mapped[ITEM + ':delete_tx'].local_summary == 'Owner private follow-up'
    assert mapped['old_item:delete_tx'].status == 'posted'
    listed = (await db.execute(select(PrivateItem).where(await service.current_bank_condition(db, '4')))).scalars().all()
    assert [row.external_id for row in listed] == [ITEM + ':posted_tx']


@pytest.mark.asyncio
async def test_core_failed_second_page_never_commits_first_page_cursor_or_balances(private_bank_db, monkeypatch):
    db = private_bank_db.db; mock = BankMock([sync_page(added=[transaction('original_tx')], cursor='cursor_one')])
    await connected(db, mock); registry = core.providers()
    async def fetch(source_id, auth, metadata): return await bank.fetch_bofa_bank(auth, transport=mock.transport)
    monkeypatch.setattr(core, 'providers', lambda: SimpleNamespace(fetch_source=fetch, describe_sources=registry.describe_sources))
    await core.sync_source(db, '4', 'bofa_bank')
    connection = await row_for(db); old_meta = deepcopy(connection.metadata_json)
    def changed(request, payload):
        return sync_page(added=[transaction('must_not_save')], cursor='middle', more=True) if payload['cursor'] == 'cursor_one' else httpx.Response(
            400, json={'error_code': 'TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION', 'error_message': ACCESS})
    mock.overrides['/transactions/sync'] = changed
    mock.accounts = [account(balances={'current': 999.99, 'available': 999.99, 'limit': None, 'iso_currency_code': 'USD'})]
    with pytest.raises(HTTPException) as error: await core.sync_source(db, '4', 'bofa_bank')
    assert error.value.status_code == 502 and ACCESS not in str(error.value)
    connection = await row_for(db)
    assert core.decrypt_credentials(connection.encrypted_credentials)['transaction_cursor'] == 'cursor_one'
    assert connection.metadata_json == old_meta
    assert (await db.execute(select(PrivateItem.external_id))).scalars().all() == [ITEM + ':original_tx']


@pytest.mark.asyncio
async def test_core_generation_change_after_complete_batch_rejects_all_new_money_data(private_bank_db, monkeypatch):
    db = private_bank_db.db; mock = BankMock([sync_page(added=[transaction('must_not_save')])])
    connection = await connected(db, mock); registry = core.providers()
    async def fetch(source_id, auth, metadata):
        batch = await bank.fetch_bofa_bank(auth, transport=mock.transport)
        async with private_bank_db.sessions() as other:
            await other.execute(update(PrivateConnection).values(generation=99, status='disconnected', encrypted_credentials=None))
            await other.commit()
        return batch
    monkeypatch.setattr(core, 'providers', lambda: SimpleNamespace(fetch_source=fetch, describe_sources=registry.describe_sources))
    with pytest.raises(HTTPException): await core.sync_source(db, '4', 'bofa_bank')
    connection = await row_for(db)
    assert connection.generation == 99 and connection.encrypted_credentials is None and connection.status == 'disconnected'
    assert not (await db.execute(select(PrivateItem.id))).all()


@pytest.mark.asyncio
async def test_date_only_transactions_sort_before_sql_limit_by_bank_date_not_import_time(private_bank_db, monkeypatch):
    db = private_bank_db.db; mock = BankMock([sync_page(added=[
        transaction('latest', date='2026-10-10'), transaction('old', date='2026-09-01'),
        transaction('middle', date='2026-10-09')])])
    await connected(db, mock); registry = core.providers()
    async def fetch(source_id, auth, metadata): return await bank.fetch_bofa_bank(auth, transport=mock.transport)
    monkeypatch.setattr(core, 'providers', lambda: SimpleNamespace(fetch_source=fetch, describe_sources=registry.describe_sources))
    await core.sync_source(db, '4', 'bofa_bank')
    now = utcnow()
    await db.execute(update(PrivateItem).where(PrivateItem.external_id == ITEM + ':latest').values(created_at=now - timedelta(days=3)))
    await db.execute(update(PrivateItem).where(PrivateItem.external_id == ITEM + ':old').values(created_at=now))
    await db.execute(update(PrivateItem).where(PrivateItem.external_id == ITEM + ':middle').values(created_at=now - timedelta(days=2)))
    await db.commit()
    first = await core.list_items(db, '4', source_id='bofa_bank', limit=1)
    two = await core.list_items(db, '4', source_id='bofa_bank', limit=2)
    assert first['total'] == 3 and [row['evidence']['bank_transaction_id'] for row in first['items']] == ['latest']
    assert [row['evidence']['bank_transaction_id'] for row in two['items']] == ['latest', 'middle']
    assert all(row['occurred_at'] is None for row in two['items'])


@pytest.mark.asyncio
@pytest.mark.parametrize('setting,value', [
    ('PRIVATE_WORKSPACE_PLAID_ENV', 'sandbox'),
    ('PRIVATE_WORKSPACE_PLAID_CLIENT_ID', 'different_synthetic_client'),
])
async def test_public_bank_source_withholds_old_balances_when_server_binding_changes(private_bank_db, monkeypatch, setting, value):
    db = private_bank_db.db; mock = BankMock(); connection = await connected(db, mock)
    batch = await bank.fetch_bofa_bank(core.decrypt_credentials(connection.encrypted_credentials), transport=mock.transport)
    connection.metadata_json = batch['metadata']; connection.last_sync = utcnow()
    await db.commit()
    descriptor = {'id': 'bofa_bank', 'name': 'Bank of America', 'capabilities': [], 'missing_configuration': []}
    before = core.source_response(descriptor, connection)
    assert before['status'] == 'connected' and before['metadata']['bank_accounts']
    assert before['metadata']['bank_snapshot']['id'] == batch['metadata']['bank_snapshot']['id']
    monkeypatch.setenv(setting, value)
    after = core.source_response(descriptor, connection)
    assert after['status'] == 'error' and '重新连接' in after['error']
    assert 'bank_accounts' not in after['metadata'] and 'bank_snapshot' not in after['metadata']
    assert ACCESS not in json.dumps(after, default=str) and 'encrypted_credentials' not in json.dumps(after, default=str)
    # Rejected public output does not destroy the private retained snapshot.
    assert connection.metadata_json == batch['metadata']


@pytest.mark.asyncio
async def test_public_bank_source_retains_bound_cached_balances_after_an_ordinary_sync_failure(private_bank_db, monkeypatch):
    db = private_bank_db.db; mock = BankMock(); await connected(db, mock); registry = core.providers()
    async def fetch(source_id, auth, metadata):
        return await bank.fetch_bofa_bank(auth, transport=mock.transport)
    monkeypatch.setattr(core, 'providers', lambda: SimpleNamespace(fetch_source=fetch, describe_sources=registry.describe_sources))
    await core.sync_source(db, '4', 'bofa_bank')
    connection = await row_for(db); cached = deepcopy(connection.metadata_json)
    previous_sync = connection.last_sync
    mock.overrides['/accounts/get'] = httpx.Response(503, json={'error_code': 'INSTITUTION_DOWN', 'error_message': ACCESS})
    with pytest.raises(HTTPException):
        await core.sync_source(db, '4', 'bofa_bank')
    connection = await row_for(db)
    source = core.source_response({'id': 'bofa_bank', 'name': 'Bank of America', 'capabilities': [], 'missing_configuration': []}, connection)
    assert source['status'] == 'error' and source['error']
    assert source['metadata']['bank_accounts'] == cached['bank_accounts']
    assert source['metadata']['bank_snapshot'] == cached['bank_snapshot']
    assert connection.last_sync == previous_sync and connection.metadata_json == cached
    assert ACCESS not in json.dumps(source, default=str)
