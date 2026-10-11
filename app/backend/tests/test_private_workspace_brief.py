"""Synthetic owner snapshots, provider isolation and one shared USD budget."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select, update

from models.private_workspace import PrivateConnection, PrivateItem, PrivateWorkspaceBrief, PrivateMailBriefUsage
from services import private_mail_brief as shared
from services import private_mail_brief_service as mail
from services import private_workspace_brief_service as boss_service
from services import private_workspace_brief_provider as boss_provider
from test_private_mail_brief_service import workspace, usage, money_usage, verified_billing
from test_private_workspace_app import private_app

STRIPE_ACCOUNT = 'acct_synthetic12345678'
STRIPE_SNAPSHOT = 'syntheticstripebriefsnapshot'


def stripe_metadata(now):
    return {'stripe_account_id': STRIPE_ACCOUNT, 'mode': 'test', 'stripe_snapshot': {
        'id': STRIPE_SNAPSHOT, 'account_id': STRIPE_ACCOUNT, 'mode': 'test', 'observed_at': now.isoformat()},
        'balances': [{'currency': 'USD', 'available_minor': 99999999, 'pending_minor': 11111111}]}


def stripe_evidence(now):
    return {'stripe_account_id': STRIPE_ACCOUNT, 'stripe_mode': 'test',
            'stripe_snapshot_id': STRIPE_SNAPSHOT, 'stripe_observed_at': now.isoformat()}


async def seed_bank(boss, monkeypatch, *, complete=True):
    """A local synthetic connection only; no provider request or real token."""
    monkeypatch.setenv('PRIVATE_WORKSPACE_PLAID_ENABLED', 'true')
    monkeypatch.setenv('PRIVATE_WORKSPACE_PLAID_CLIENT_ID', 'synthetic-plaid-client')
    monkeypatch.setenv('PRIVATE_WORKSPACE_PLAID_SECRET', 'synthetic-plaid-fixture')
    monkeypatch.setenv('PRIVATE_WORKSPACE_PLAID_ENV', 'sandbox')
    monkeypatch.setenv('PRIVATE_WORKSPACE_PUBLIC_URL', 'https://private.example.test')
    monkeypatch.setenv('PRIVATE_WORKSPACE_BOFA_INSTITUTION_ID', 'ins_synthetic_bank')
    metadata = {'bank_item_id': 'synthetic-bank-item', 'bank_environment': 'sandbox',
        'bank_institution_id': 'ins_synthetic_bank', 'bank_institution_name': 'Synthetic bank name',
        'bank_client_fingerprint': hashlib.sha256(b'synthetic-plaid-client').hexdigest(),
        'bank_accounts': [{'account_id': 'private-bank-account', 'name': 'PRIVATE BANK ACCOUNT NAME', 'mask': '1234',
            'currency': 'USD', 'current_minor': 88888888, 'available_minor': None, 'limit_minor': None,
            'type': 'depository', 'subtype': 'checking', 'balance_kind': 'funds', 'balance_source': 'cached_accounts_get'}],
        'bank_snapshot': {'id': 'd' * 32, 'observed_at': boss.now.isoformat(), 'item_id': 'synthetic-bank-item',
            'environment': 'sandbox', 'institution_id': 'ins_synthetic_bank', 'accounts_complete': True,
            'pagination_complete': True, 'transactions_complete': complete, 'balance_realtime': False,
            'transaction_update_status': 'HISTORICAL_UPDATE_COMPLETE' if complete else 'INITIAL_UPDATE_COMPLETE'}}
    async with boss.sessions() as db:
        db.add(PrivateConnection(owner_id='4', source_id='bofa_bank', status='connected', generation=1,
            last_sync=boss.now, encrypted_credentials='synthetic-encrypted', metadata_json=metadata))
        for name, status, owner, item, env, institution in (
            ('posted', 'posted', '4', 'synthetic-bank-item', 'sandbox', 'ins_synthetic_bank'),
            ('pending', 'pending', '4', 'synthetic-bank-item', 'sandbox', 'ins_synthetic_bank'),
            ('old-snapshot', 'posted', '4', 'synthetic-bank-item', 'sandbox', 'ins_synthetic_bank'),
            ('removed', 'removed', '4', 'synthetic-bank-item', 'sandbox', 'ins_synthetic_bank'),
            ('replaced', 'replaced', '4', 'synthetic-bank-item', 'sandbox', 'ins_synthetic_bank'),
            ('foreign', 'posted', '5', 'synthetic-bank-item', 'sandbox', 'ins_synthetic_bank'),
            ('old-item', 'posted', '4', 'other-bank-item', 'sandbox', 'ins_synthetic_bank'),
            ('wrong-env', 'posted', '4', 'synthetic-bank-item', 'production', 'ins_synthetic_bank'),
            ('wrong-institution', 'posted', '4', 'synthetic-bank-item', 'sandbox', 'ins_other_bank'),
        ):
            db.add(PrivateItem(owner_id=owner, source_id='bofa_bank', external_id='synthetic-bank:' + name,
                kind='bank_transaction', title='PRIVATE BANK TRANSACTION ' + name, summary='PRIVATE BANK DESCRIPTION',
                status=status, priority='normal', amount_minor=55555555, currency='USD', occurred_at=None, evidence={
                    'bank_item_id': item, 'bank_environment': env, 'bank_institution_id': institution,
                    'bank_account_id': 'private-bank-account', 'bank_account_mask': '1234',
                    'bank_snapshot_id': 'c' * 32 if name == 'old-snapshot' else 'd' * 32,
                    'bank_observed_at': boss.now.isoformat(), 'pending': status == 'pending',
                    'transaction_date': boss.now.date().isoformat(), 'amount_decimal': '555555.55'}))
        await db.commit()


@pytest_asyncio.fixture
async def boss(workspace, monkeypatch):
    now = datetime(2026, 10, 11, 4, 0, tzinfo=timezone.utc)
    workspace.now = now; workspace.boss_calls = []; workspace.boss_hooks = []; workspace.boss_failures = []
    monkeypatch.setattr(boss_service, 'utcnow', lambda: workspace.now)
    monkeypatch.setattr(mail, 'utcnow', lambda: workspace.now)
    monkeypatch.delenv('PRIVATE_WORKSPACE_BRIEF_EXTERNAL_CONSENT', raising=False)
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_ACCOUNT_ID', STRIPE_ACCOUNT)
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_MODE', 'test')
    workspace.special = {name: str(uuid4()) for name in ('dispute', 'problem', 'failure', 'attention', 'bofa', 'overdue', 'old_ads')}
    metadata = {'ads_customer_id': '1234567890', 'ads_snapshot': {'id': 'fresh', 'observed_at': now.isoformat(),
                'inventory_complete': True, 'metrics_complete': True}}
    async with workspace.sessions() as db:
        await db.execute(update(PrivateConnection).values(last_sync=now))
        for source in ('google_ads', 'stripe', 'bofa'):
            db.add(PrivateConnection(owner_id='4', source_id=source, status='connected', generation=1,
                last_sync=now, encrypted_credentials='synthetic-encrypted',
                metadata_json=metadata if source == 'google_ads' else stripe_metadata(now) if source == 'stripe' else {}))
        await db.execute(update(PrivateItem).where(PrivateItem.id == workspace.ids['mail']).values(occurred_at=now))
        for name, source, kind, status, due, currency in (
            ('dispute', 'stripe', 'dispute', 'needs_response', now + timedelta(days=1), 'USD'),
            ('failure', 'stripe', 'payout', 'failed', now - timedelta(days=1), 'CNY'),
            ('bofa', 'bofa', 'email_alert', 'unverified', None, None),
            ('overdue', 'manual', 'task', 'manual', now - timedelta(days=2), None),
        ):
            db.add(PrivateItem(id=workspace.special[name], owner_id='4', source_id=source, external_id='synthetic-' + name,
                kind=kind, title='Synthetic ' + name, summary='PRIVATE RAW DETAILS must not enter AI payload', status=status,
                priority='normal', amount_minor=777777 if currency else None, currency=currency,
                occurred_at=now, due_at=due, action_status='done' if source == 'stripe' else 'open',
                evidence=stripe_evidence(now) if source == 'stripe' else {}))
        for name, bucket, snapshot_id in (('problem', 'problem', 'fresh'), ('attention', 'attention', 'fresh'), ('old_ads', 'problem', 'old')):
            db.add(PrivateItem(id=workspace.special[name], owner_id='4', source_id='google_ads', external_id='synthetic-' + name,
                kind='campaign', title='Synthetic ' + name, summary='Raw campaign name and details', status='ENABLED',
                priority='normal', occurred_at=now, action_status='done', evidence={
                    'customer_id': '1234567890', 'ads_snapshot_id': snapshot_id,
                    'ads_health': {'snapshot_id': snapshot_id, 'bucket': bucket, 'currency': 'USD',
                        'account_timezone': 'America/Los_Angeles', 'coverage': {'metrics_complete': True},
                        'metrics': {'yesterday': {'clicks': 10, 'cost_micros': 2000000},
                                    'last_7_days': {'clicks': 70, 'cost_micros': 14000000}},
                        'periods': {'yesterday': {'start': '2026-10-10', 'end': '2026-10-10'},
                                    'last_7_days': {'start': '2026-10-04', 'end': '2026-10-10'}}}}))
        await db.commit()
    async def fake_explain(data, **arguments):
        assert arguments == {'reserved_micro_usd': 421911, 'price_policy': shared.PRICE_POLICY}
        workspace.boss_calls.append(deepcopy(data))
        if workspace.boss_hooks: await workspace.boss_hooks.pop(0)()
        if workspace.boss_failures: raise workspace.boss_failures.pop(0)
        return {**boss_provider.validate({'summary': '先核对平台提示与争议要求，再处理其他待办；缺失数据仍待确认。',
            'source_refs': ['stripe', 'google_ads'], 'issue_notes': [
                {'issue_id': issue['id'], 'explanation': '先查看原始来源，确认要求后再手动处理。'} for issue in data['issues']]}, data),
            'billing': workspace.billings.pop(0) if workspace.billings else None}
    monkeypatch.setattr(boss_provider, 'explain', fake_explain)
    return workspace


async def get(boss, owner='4', period='today'):
    async with boss.sessions() as db: return await boss_service.snapshot(db, owner, period)


async def generate(boss, data):
    async with boss.sessions() as db: return await boss_service.explain(db, '4', data['period'], data['snapshot_id'])


@pytest.mark.asyncio
async def test_local_snapshot_stable_owner_only_no_body_or_ai_and_honest_sources(boss):
    first = await get(boss); second = await get(boss)
    assert first['snapshot_id'] == second['snapshot_id']
    assert [issue['item_id'] for issue in first['issues']] == [boss.special['dispute'], boss.special['problem'], boss.special['failure']]
    assert boss.special['old_ads'] not in json.dumps(first)
    assert first['window']['timezone'] == 'Asia/Shanghai' and first['window']['end'] == '2026-10-11'
    assert first['capabilities'] == {'configured': False, 'code': 'not_configured'}
    stripe = next(source for source in first['sources'] if source['source_id'] == 'stripe')
    assert stripe['data_state'] == 'partial' and any('USD 事件 1 条' == fact for fact in stripe['facts'])
    raw = json.dumps(first, ensure_ascii=False)
    assert '777777' not in raw and '99999999' not in raw and 'Foreign private' not in raw
    assert '提现不等于银行到账' in raw and '最后记录状态' in raw and '资金变动与实际入账均未核验' in raw
    foreign = await get(boss, '5')
    assert all(issue.get('item_id') not in boss.special.values() for issue in foreign['issues'])
    assert boss.boss_calls == boss.calls == boss.content_calls == [] and await usage(boss) == (0, 0)


@pytest.mark.asyncio
async def test_last7days_uses_source_windows_and_not_combined_financial_totals(boss):
    data = await get(boss, period='last7days')
    assert data['window']['start'].startswith('2026-10-05')
    ads = next(source for source in data['sources'] if source['source_id'] == 'google_ads')
    assert any('2026-10-04 至 2026-10-10' in fact for fact in ads['facts'])
    assert '已覆盖系列点击 140 次，广告费用 28.00 USD' in ads['facts']
    assert 'America/Los_Angeles' in json.dumps(ads)
    assert data['snapshot_id'] != (await get(boss))['snapshot_id']


@pytest.mark.asyncio
async def test_stale_missing_and_disconnected_sources_never_become_healthy(boss):
    boss.now += timedelta(days=2)
    data = await get(boss)
    assert all(source['data_state'] == 'stale' for source in data['sources'] if source['source_id'] not in {'manual', 'bofa_bank'})
    assert next(source for source in data['sources'] if source['source_id'] == 'bofa_bank')['data_state'] == 'missing'
    assert all(issue['source_id'] not in {'google_ads', 'stripe'} for issue in data['issues'])
    missing = await get(boss, 'no-imported-source')
    assert all(source['data_state'] == 'missing' for source in missing['sources'] if source['source_id'] != 'manual')
    assert all('缺失数据视为零' in source['facts'][0] for source in missing['sources'] if source['source_id'] != 'manual')


@pytest.mark.asyncio
async def test_workspace_consent_and_host_gates_deny_without_any_charge(boss, monkeypatch):
    data = await get(boss)
    denied = await generate(boss, data)
    assert denied['ai']['code'] == 'not_configured'
    monkeypatch.setenv('PRIVATE_WORKSPACE_BRIEF_EXTERNAL_CONSENT', 'true')
    monkeypatch.setenv('PRIVATE_MAIL_BRIEF_HOSTING_VERIFIED', 'false')
    denied = await generate(boss, await get(boss))
    assert denied['ai']['code'] == 'not_configured' and boss.boss_calls == []
    assert await money_usage(boss) == 0


@pytest.mark.asyncio
async def test_explicit_explanation_encrypted_cache_settles_once_and_keeps_facts(boss, monkeypatch):
    monkeypatch.setenv('PRIVATE_WORKSPACE_BRIEF_EXTERNAL_CONSENT', 'true')
    boss.billings.append(verified_billing())
    original = await get(boss); result = await generate(boss, original); cached = await generate(boss, original)
    assert result['ai']['state'] == cached['ai']['state'] == 'ready' and len(boss.boss_calls) == 1
    assert result['sources'] == original['sources'] and result['issues'] == original['issues']
    assert await money_usage(boss) == 841
    async with boss.sessions() as db:
        row = (await db.execute(select(PrivateWorkspaceBrief))).scalar_one()
        assert row.reservation_state == 'settled' and '先核对' not in row.encrypted_content
    assert (await get(boss))['ai']['state'] == 'ready'


@pytest.mark.asyncio
async def test_duplicate_success_completion_cannot_refund_twice(boss, monkeypatch):
    monkeypatch.setenv('PRIVATE_WORKSPACE_BRIEF_EXTERNAL_CONSENT', 'true')
    boss.billings.append(verified_billing()); finish = boss_service._finish; captured = {}
    async def capture(db, context, token, **arguments):
        if arguments.get('ai'): captured.update(context=context, token=token, arguments=arguments)
        return await finish(db, context, token, **arguments)
    monkeypatch.setattr(boss_service, '_finish', capture)
    assert (await generate(boss, await get(boss)))['ai']['state'] == 'ready'
    async with boss.sessions() as db:
        assert await finish(db, captured['context'], captured['token'], **captured['arguments']) is False
    assert await money_usage(boss) == 841


@pytest.mark.asyncio
async def test_updated_source_rejects_old_snapshot_before_charge(boss, monkeypatch):
    monkeypatch.setenv('PRIVATE_WORKSPACE_BRIEF_EXTERNAL_CONSENT', 'true')
    data = await get(boss)
    async with boss.sessions() as db:
        await db.execute(update(PrivateConnection).where(PrivateConnection.source_id == 'google_ads').values(generation=9))
        await db.commit()
    rejected = await generate(boss, data)
    assert rejected['ai']['code'] == 'snapshot_changed' and boss.boss_calls == []
    assert await money_usage(boss) == 0


@pytest.mark.asyncio
async def test_source_changes_during_ai_reject_result_and_keep_full_shared_reservation(boss, monkeypatch):
    monkeypatch.setenv('PRIVATE_WORKSPACE_BRIEF_EXTERNAL_CONSENT', 'true')
    boss.billings.append(verified_billing())
    async def disconnect():
        async with boss.sessions() as db:
            await db.execute(update(PrivateConnection).where(PrivateConnection.source_id == 'stripe').values(status='disconnected'))
            await db.commit()
    boss.boss_hooks.append(disconnect)
    result = await generate(boss, await get(boss))
    assert result['ai']['code'] == 'snapshot_changed' and result['ai']['state'] != 'ready'
    assert await money_usage(boss) == 421911


@pytest.mark.asyncio
async def test_failure_and_unknown_usage_never_refund_shared_budget(boss, monkeypatch):
    monkeypatch.setenv('PRIVATE_WORKSPACE_BRIEF_EXTERNAL_CONSENT', 'true')
    boss.boss_failures.append(shared.MailBriefError('upstream_timeout'))
    first = await generate(boss, await get(boss))
    assert first['ai']['code'] == 'upstream_unavailable' and await money_usage(boss) == 421911
    second = await generate(boss, await get(boss, period='last7days'))
    assert second['ai']['state'] == 'ready' and await money_usage(boss) == 421911 * 2


@pytest.mark.asyncio
async def test_concurrent_mail_and_workspace_share_one_dollar_budget(boss, monkeypatch):
    monkeypatch.setenv('PRIVATE_WORKSPACE_BRIEF_EXTERNAL_CONSENT', 'true')
    monkeypatch.setenv('PRIVATE_MAIL_BRIEF_MONTHLY_BUDGET_MICRO_USD', '421911')
    data = await get(boss)
    async def mail_request():
        async with boss.sessions() as db: return await mail.brief_item(db, '4', boss.ids['mail'])
    mail_result, workspace_result = await asyncio.gather(mail_request(), generate(boss, data))
    assert len(boss.calls) + len(boss.boss_calls) == 1
    assert await money_usage(boss) == 421911 and (await usage(boss))[1] == 1
    codes = [mail_result.get('code'), workspace_result.get('ai', {}).get('code')]
    assert 'budget_exhausted' in codes


@pytest.mark.asyncio
async def test_duplicate_generation_claims_one_call(boss, monkeypatch):
    monkeypatch.setenv('PRIVATE_WORKSPACE_BRIEF_EXTERNAL_CONSENT', 'true')
    began = asyncio.Event(); release = asyncio.Event()
    async def pause(): began.set(); await release.wait()
    boss.boss_hooks.append(pause)
    data = await get(boss)
    running = asyncio.create_task(generate(boss, data)); await began.wait()
    duplicate = await generate(boss, data)
    assert duplicate['ai']['state'] == 'pending'
    release.set(); assert (await running)['ai']['state'] == 'ready'
    assert len(boss.boss_calls) == 1 and await money_usage(boss) == 421911


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['source', 'lease', 'month', 'business_day'])
async def test_final_send_guard_holds_reserved_budget_when_snapshot_or_lease_changes(boss, monkeypatch, change):
    monkeypatch.setenv('PRIVATE_WORKSPACE_BRIEF_EXTERNAL_CONSENT', 'true')
    if change == 'month': boss.now = datetime(2026, 10, 31, 23, 59, 59, tzinfo=timezone.utc)
    if change == 'business_day': boss.now = datetime(2026, 10, 11, 15, 59, 59, tzinfo=timezone.utc)
    data = await get(boss)
    async with boss.sessions() as db:
        original_commit = db.commit; commits = 0
        async def change_after_commit():
            nonlocal commits
            commits += 1; await original_commit()
            if commits == 3:
                if change in {'month', 'business_day'}: boss.now += timedelta(seconds=2)
                else:
                    async with boss.sessions() as other:
                        if change == 'source':
                            await other.execute(update(PrivateConnection).where(PrivateConnection.source_id == 'gmail').values(generation=8))
                        else: await other.execute(update(PrivateWorkspaceBrief).values(lease_token='replaced'))
                        await other.commit()
        db.commit = change_after_commit
        result = await boss_service.explain(db, '4', data['period'], data['snapshot_id'])
    assert result['ai']['code'] == ('budget_month_changed' if change == 'month' else 'snapshot_changed')
    assert boss.boss_calls == [] and await money_usage(boss) == 421911


@pytest.mark.asyncio
async def test_success_across_utc_month_settles_original_receipt_month(boss, monkeypatch):
    monkeypatch.setenv('PRIVATE_WORKSPACE_BRIEF_EXTERNAL_CONSENT', 'true')
    boss.now = datetime(2026, 10, 31, 23, 59, 59, tzinfo=timezone.utc)
    boss.billings.append(verified_billing())
    async def next_month(): boss.now += timedelta(seconds=2)
    boss.boss_hooks.append(next_month)
    result = await generate(boss, await get(boss))
    assert result['ai']['state'] == 'ready'
    assert await money_usage(boss, month='2026-10') == 841
    assert await money_usage(boss, month='2026-11') == 0


@pytest.mark.asyncio
async def test_authenticated_routes_deny_other_accounts_and_preserve_crm_finance(private_app, monkeypatch):
    import hashlib
    value = private_app
    monkeypatch.delenv('PRIVATE_WORKSPACE_BRIEF_EXTERNAL_CONSENT', raising=False)
    before = hashlib.sha256(value.business_path.read_bytes()).hexdigest()
    route = '/api/v1/private-workspace/brief'
    data = await value.client.get(route + '?period=last7days', headers=value.headers())
    assert data.status_code == 200 and data.headers['cache-control'] == 'no-store'
    body = data.json()
    assert body['period'] == 'last7days' and len(body['sources']) == 6 and body['issues'] == []
    assert body['capabilities'] == {'configured': False, 'code': 'not_configured'}
    denied_ai = await value.client.post(route + '/explain', headers=value.headers(),
        json={'period': 'last7days', 'snapshot_id': body['snapshot_id']})
    assert denied_ai.status_code == 200 and denied_ai.json()['ai']['code'] == 'not_configured'
    for identity in (2, 3, 4):
        assert (await value.client.get(route, headers=value.headers(identity))).status_code == 403
        assert (await value.client.post(route + '/explain', headers=value.headers(identity),
                json={'period': 'last7days', 'snapshot_id': body['snapshot_id']})).status_code == 403
    assert (await value.client.get(route + '?period=all', headers=value.headers())).status_code == 422
    assert (await value.client.post(route + '/explain', headers=value.headers(),
        json={'period': 'today', 'snapshot_id': body['snapshot_id'], 'enabled': True, 'owner_id': '4'})).status_code == 422
    assert hashlib.sha256(value.business_path.read_bytes()).hexdigest() == before


@pytest.mark.asyncio
async def test_minimized_provider_payload_and_strict_number_free_evidence(boss, monkeypatch):
    data = await get(boss)
    raw = json.loads(boss_provider.payload(data, shared.model_identifier()))
    text = raw['input'][0]['content'][0]['text']
    assert 'owner@example.com' not in text and 'PRIVATE RAW DETAILS' not in text and '777777' not in text
    assert raw['tools'] == [] and raw['tool_choice'] == 'none' and raw['store'] is False
    assert raw['text']['format']['strict'] is True and raw['service_tier'] == 'default'
    safe = {'summary': '请先核对来源状态，再处理重要事项。', 'source_refs': ['stripe'], 'issue_notes': []}
    for change in ({'summary': '收入为 $700'}, {'summary': '收到三笔收入'}, {'summary': '收到三笔款项'},
                   {'summary': '款项已到账'}, {'summary': '款项已经到账'}, {'summary': '资金到帐正常'},
                   {'summary': '一切正常，没有风险'}, {'source_refs': ['foreign_source']},
                   {'issue_notes': [{'issue_id': 'foreign-item', 'explanation': '核对要求。'}]}):
        value = deepcopy(safe); value.update(change)
        with pytest.raises(shared.MailBriefError): boss_provider.validate(value, data)


@pytest.mark.asyncio
@pytest.mark.parametrize('crossing', ['beijing_day', 'source_freshness'])
async def test_snapshot_expires_during_ai_never_returns_ready_or_settles(boss, monkeypatch, crossing):
    monkeypatch.setenv('PRIVATE_WORKSPACE_BRIEF_EXTERNAL_CONSENT', 'true')
    if crossing == 'beijing_day': boss.now = datetime(2026, 10, 11, 15, 59, 50, tzinfo=timezone.utc)
    else:
        async with boss.sessions() as db:
            stamp = boss.now - timedelta(hours=24) + timedelta(seconds=10)
            await db.execute(update(PrivateConnection).where(PrivateConnection.source_id == 'stripe')
                .values(last_sync=stamp, metadata_json=stripe_metadata(stamp)))
            await db.commit()
    boss.billings.append(verified_billing())
    async def expire(): boss.now += timedelta(seconds=20)
    boss.boss_hooks.append(expire)
    result = await generate(boss, await get(boss))
    assert result['ai']['state'] != 'ready' and result['ai']['code'] == 'snapshot_changed'
    assert await money_usage(boss) == 421911


@pytest.mark.asyncio
async def test_connection_identity_changes_even_with_same_timestamp_reject_result(boss, monkeypatch):
    monkeypatch.setenv('PRIVATE_WORKSPACE_BRIEF_EXTERNAL_CONSENT', 'true')
    boss.billings.append(verified_billing())
    async def change_without_timestamp():
        async with boss.sessions() as db:
            stamp = (await db.execute(select(PrivateConnection.updated_at).where(PrivateConnection.source_id == 'stripe'))).scalar_one()
            await db.execute(update(PrivateConnection).where(PrivateConnection.source_id == 'stripe')
                .values(generation=9, status='disconnected', updated_at=stamp))
            await db.commit()
    boss.boss_hooks.append(change_without_timestamp)
    result = await generate(boss, await get(boss))
    assert result['ai']['code'] == 'snapshot_changed' and await money_usage(boss) == 421911


@pytest.mark.asyncio
async def test_partial_ads_are_data_review_and_not_confirmed_platform_errors(boss):
    async with boss.sessions() as db:
        connection = (await db.execute(select(PrivateConnection).where(PrivateConnection.source_id == 'google_ads'))).scalar_one()
        metadata = deepcopy(connection.metadata_json); metadata['ads_snapshot']['metrics_complete'] = False
        connection.metadata_json = metadata; await db.commit()
    data = await get(boss)
    ads = next(source for source in data['sources'] if source['source_id'] == 'google_ads')
    assert ads['data_state'] == 'partial'
    assert all(issue.get('item_id') not in {boss.special['problem'], boss.special['attention']} for issue in data['issues'])
    assert not any('广告费用' in fact for fact in ads['facts'])


@pytest.mark.asyncio
async def test_source_caps_cannot_let_many_mails_displace_platform_issues(boss, monkeypatch):
    monkeypatch.setattr(boss_service, 'MAX_ROWS', 2)
    async with boss.sessions() as db:
        for index in range(6):
            db.add(PrivateItem(owner_id='4', source_id='gmail', external_id='extra-mail-' + str(index),
                kind='email', title='Routine message', summary='Routine update', status='read',
                priority='normal', occurred_at=boss.now + timedelta(microseconds=index), evidence={}))
        await db.commit()
    data = await get(boss)
    assert [issue['item_id'] for issue in data['issues']] == [boss.special['dispute'], boss.special['problem'], boss.special['failure']]
    gmail = next(source for source in data['sources'] if source['source_id'] == 'gmail')
    assert any('最多 2 条' in fact for fact in gmail['facts'])
    assert next(source for source in data['sources'] if source['source_id'] == 'google_ads')['data_state'] == 'ready'


@pytest.mark.asyncio
async def test_ads_loading_cap_marks_partial_before_platform_candidates_and_metrics(boss, monkeypatch):
    monkeypatch.setattr(boss_service, 'MAX_ROWS', 1)
    data = await get(boss)
    ads = next(source for source in data['sources'] if source['source_id'] == 'google_ads')
    assert ads['data_state'] == 'partial' and not any('广告费用' in fact for fact in ads['facts'])
    assert all(issue.get('item_id') not in {boss.special['problem'], boss.special['attention']} for issue in data['issues'])


@pytest.mark.asyncio
async def test_stripe_retained_rows_without_first_successful_sync_do_not_make_platform_issues(boss):
    async with boss.sessions() as db:
        await db.execute(update(PrivateConnection).where(PrivateConnection.source_id == 'stripe').values(last_sync=None))
        await db.commit()
    data = await get(boss)
    assert next(source for source in data['sources'] if source['source_id'] == 'stripe')['data_state'] == 'missing'
    assert all(issue['source_id'] != 'stripe' for issue in data['issues'])


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['account', 'mode', 'snapshot', 'missing_binding'])
async def test_stripe_unverified_identity_is_unsupported_without_history_counts_or_issues(boss, change):
    async with boss.sessions() as db:
        connection = (await db.execute(select(PrivateConnection).where(PrivateConnection.source_id == 'stripe'))).scalar_one()
        metadata = deepcopy(connection.metadata_json)
        if change == 'account': metadata['stripe_account_id'] = 'acct_other12345678'
        elif change == 'mode': metadata['mode'] = 'live'
        elif change == 'snapshot': metadata['stripe_snapshot']['account_id'] = 'acct_other12345678'
        else: metadata.pop('stripe_account_id')
        connection.metadata_json = metadata
        await db.commit()
    data = await get(boss)
    stripe = next(source for source in data['sources'] if source['source_id'] == 'stripe')
    assert stripe['data_state'] == 'unsupported' and stripe['facts'] == ['Stripe 账户、环境或同步快照身份无法核实；历史事件不参与简报。']
    assert all(issue['source_id'] != 'stripe' for issue in data['issues'])


@pytest.mark.asyncio
async def test_stripe_brief_filters_old_account_mode_and_snapshot_before_counts_and_ranking(boss):
    async with boss.sessions() as db:
        for change in ('account', 'mode', 'snapshot'):
            evidence = stripe_evidence(boss.now)
            evidence[{'account': 'stripe_account_id', 'mode': 'stripe_mode', 'snapshot': 'stripe_snapshot_id'}[change]] = {
                'account': 'acct_other12345678', 'mode': 'live', 'snapshot': 'oldstripebriefsnapshot'}[change]
            db.add(PrivateItem(owner_id='4', source_id='stripe', external_id='historical-' + change,
                kind='dispute', title='Historical Stripe item ' + change, summary='Private historic details',
                status='needs_response', priority='urgent', occurred_at=boss.now, due_at=boss.now, evidence=evidence))
        await db.commit()
    data = await get(boss)
    stripe = next(source for source in data['sources'] if source['source_id'] == 'stripe')
    assert stripe['facts'][0] == '同期已同步事件 2 条'
    assert [issue['item_id'] for issue in data['issues']] == [boss.special['dispute'], boss.special['problem'], boss.special['failure']]
    assert 'Historical Stripe item' not in json.dumps(data)


@pytest.mark.asyncio
@pytest.mark.parametrize('complete', [True, False])
async def test_real_bank_brief_counts_bound_local_posted_and_pending_only_without_financial_details(boss, monkeypatch, complete):
    await seed_bank(boss, monkeypatch, complete=complete)
    data = await get(boss)
    bank = next(source for source in data['sources'] if source['source_id'] == 'bofa_bank')
    assert bank['status'] == 'connected' and bank['last_sync'] == boss.now.isoformat()
    assert bank['data_state'] == ('ready' if complete else 'partial')
    assert bank['facts'][0] == '当前本地已入账 2 条，待入账 1 条'
    # Incremental bank history remains valid, even without a precise datetime.
    assert 'PRIVATE BANK' not in json.dumps(data) and '88888888' not in json.dumps(data) and '55555555' not in json.dumps(data)
    assert all(issue['source_id'] != 'bofa_bank' for issue in data['issues'])
    if not complete: assert any('未加载记录不视为零' in fact for fact in bank['facts'])
    ai_source = next(source for source in json.loads(boss_provider._source(data))['sources'] if source['source_id'] == 'bofa_bank')
    assert ai_source == boss_provider.BANK_GAP and ai_source['facts'] == [] and ai_source['last_sync'] is None


@pytest.mark.asyncio
@pytest.mark.parametrize('change,expected', [('item', 'unsupported'), ('environment', 'unsupported'),
    ('institution', 'unsupported'), ('client', 'unsupported'), ('snapshot', 'unsupported'),
    ('age', 'stale'), ('error', 'stale')])
async def test_real_bank_invalid_or_stale_snapshot_never_becomes_current_or_healthy(boss, monkeypatch, change, expected):
    await seed_bank(boss, monkeypatch)
    async with boss.sessions() as db:
        connection = (await db.execute(select(PrivateConnection).where(PrivateConnection.source_id == 'bofa_bank'))).scalar_one()
        metadata = deepcopy(connection.metadata_json)
        if change == 'item': metadata['bank_item_id'] = 'new-bank-item'
        elif change == 'environment': metadata['bank_environment'] = 'production'
        elif change == 'institution': metadata['bank_institution_id'] = 'ins_other_bank'
        elif change == 'client': metadata['bank_client_fingerprint'] = 'e' * 64
        elif change == 'snapshot': metadata['bank_snapshot']['id'] = 'invalid'
        elif change == 'age': metadata['bank_snapshot']['observed_at'] = (boss.now - timedelta(days=2)).isoformat()
        else: connection.error = 'Synthetic sync failure'
        connection.metadata_json = metadata
        await db.commit()
    data = await get(boss)
    bank = next(source for source in data['sources'] if source['source_id'] == 'bofa_bank')
    assert bank['data_state'] == expected
    if expected == 'unsupported': assert bank['facts'] == ['银行连接或同步快照身份无法核实；历史流水不参与简报。']
    else: assert any('重新核实' in fact for fact in bank['facts'])
    assert next(source for source in json.loads(boss_provider._source(data))['sources'] if source['source_id'] == 'bofa_bank') == boss_provider.BANK_GAP


@pytest.mark.asyncio
async def test_real_bank_snapshot_freshness_sets_local_brief_expiration(boss, monkeypatch):
    await seed_bank(boss, monkeypatch)
    observed = boss.now - timedelta(hours=24) + timedelta(seconds=10)
    async with boss.sessions() as db:
        connection = (await db.execute(select(PrivateConnection).where(PrivateConnection.source_id == 'bofa_bank'))).scalar_one()
        metadata = deepcopy(connection.metadata_json); metadata['bank_snapshot']['observed_at'] = observed.isoformat()
        connection.metadata_json = metadata
        await db.commit()
    async with boss.sessions() as db:
        _, revision = await boss_service._snapshot(db, '4', 'today')
    assert revision['valid_until'] == boss.now + timedelta(seconds=10)


@pytest.mark.asyncio
async def test_final_ai_boundary_discards_all_bank_details_and_rejects_bank_issue_notes(boss, monkeypatch):
    await seed_bank(boss, monkeypatch)
    data = await get(boss)
    bank = next(source for source in data['sources'] if source['source_id'] == 'bofa_bank')
    bank.update(summary='PRIVATE BANK SUMMARY', facts=['PRIVATE BANK AMOUNT 987654321 USD'],
                last_sync='PRIVATE BANK SYNC TIME', metadata={'account': 'PRIVATE BANK ACCOUNT'})
    data['issues'].insert(0, {'id': 'PRIVATE BANK ISSUE ID', 'source_id': 'bofa_bank',
        'title': 'PRIVATE BANK TITLE', 'summary': 'PRIVATE BANK TRANSACTION SUMMARY',
        'next_action': 'PRIVATE BANK AMOUNT INSTRUCTION', 'priority': 'urgent'})
    raw = json.loads(boss_provider.payload(data, shared.model_identifier()))
    body = json.dumps(raw, ensure_ascii=False)
    assert 'PRIVATE BANK' not in body and '987654321' not in body
    safe = {'summary': '真实银行信息仅供本人在本地核对，未纳入本次整理。', 'source_refs': ['bofa_bank'], 'issue_notes': []}
    assert boss_provider.validate(safe, data)['state'] == 'ready'
    safe['issue_notes'] = [{'issue_id': 'PRIVATE BANK ISSUE ID', 'explanation': '核对银行记录。'}]
    with pytest.raises(shared.MailBriefError): boss_provider.validate(safe, data)


@pytest.mark.asyncio
async def test_actual_workspace_provider_fixed_endpoint_gate_and_usage(boss, monkeypatch):
    # Undo the fixture fake only for a mocked HTTP transport; no real request.
    monkeypatch.setenv('PRIVATE_WORKSPACE_BRIEF_EXTERNAL_CONSENT', 'true')
    data = await get(boss); calls = []
    original = __import__('services.private_workspace_brief_provider', fromlist=['explain'])
    # The function is patched by the fixture, so retrieve a separately saved
    # implementation via importlib reload before this transport-only probe.
    import importlib
    module = importlib.reload(original)
    def handle(request):
        calls.append(request)
        assert str(request.url) == 'https://api.openai.com/v1/responses'
        return httpx.Response(200, json={'status': 'completed', 'model': shared.model_identifier(), 'service_tier': 'default',
            'usage': {'input_tokens': 501, 'output_tokens': 400, 'total_tokens': 901},
            'output': [{'type': 'message', 'role': 'assistant', 'status': 'completed', 'content': [{'type': 'output_text',
                'text': json.dumps({'summary': '先查看来源提示，再核对待处理要求。', 'source_refs': ['stripe'], 'issue_notes': []})}]}]})
    result = await module.explain(data, reserved_micro_usd=421911, price_policy=shared.PRICE_POLICY, transport=httpx.MockTransport(handle))
    assert result['billing']['settlement_micro_usd'] == 841 and len(calls) == 1
    monkeypatch.setenv('PRIVATE_WORKSPACE_BRIEF_EXTERNAL_CONSENT', 'false')
    with pytest.raises(shared.MailBriefError) as denied:
        await module.explain(data, reserved_micro_usd=421911, price_policy=shared.PRICE_POLICY, transport=httpx.MockTransport(handle))
    assert denied.value.code == 'not_configured' and len(calls) == 1
