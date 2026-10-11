"""Private mail brief isolation, encrypted caching and usage gates; synthetic data only."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import sqlite3
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, inspect, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models.private_workspace import (
    PrivateConnection, PrivateItem, PrivateMailBrief, PrivateMailBriefUsage,
    PrivateWorkspaceBase, utcnow,
)
from services import private_mail_brief as provider
from services import private_mail_brief_service as service
from services.private_workspace import encrypt_credentials


@pytest_asyncio.fixture
async def workspace(monkeypatch, tmp_path):
    for key in (
        'PRIVATE_MAIL_BRIEF_ENABLED', 'PRIVATE_MAIL_BRIEF_EXTERNAL_CONSENT', 'PRIVATE_MAIL_BRIEF_HOSTING_VERIFIED',
        'PRIVATE_MAIL_BRIEF_PROVIDER', 'PRIVATE_MAIL_BRIEF_OPENAI_API_KEY',
        'PRIVATE_MAIL_BRIEF_MODEL', 'PRIVATE_MAIL_BRIEF_MONTHLY_CHAR_LIMIT',
        'PRIVATE_MAIL_BRIEF_MONTHLY_REQUEST_LIMIT', 'PRIVATE_MAIL_BRIEF_MONTHLY_BUDGET_MICRO_USD', 'PRIVATE_WORKSPACE_GMAIL_EXPECTED_ACCOUNT',
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in {
        'PRIVATE_WORKSPACE_ENCRYPTION_KEY': 'synthetic-encryption-key-for-private-brief-tests',
        'PRIVATE_MAIL_BRIEF_ENABLED': 'true',
        'PRIVATE_MAIL_BRIEF_EXTERNAL_CONSENT': 'true',
        'PRIVATE_MAIL_BRIEF_HOSTING_VERIFIED': 'true',
        'PRIVATE_MAIL_BRIEF_PROVIDER': 'openai',
        'PRIVATE_MAIL_BRIEF_OPENAI_API_KEY': 'synthetic_private_brief_key_12345',
        'PRIVATE_MAIL_BRIEF_MODEL': 'gpt-4.1-mini-2025-04-14',
        'PRIVATE_MAIL_BRIEF_MONTHLY_CHAR_LIMIT': '100000',
        'PRIVATE_MAIL_BRIEF_MONTHLY_REQUEST_LIMIT': '100',
        'PRIVATE_MAIL_BRIEF_MONTHLY_BUDGET_MICRO_USD': '5000000',
    }.items():
        monkeypatch.setenv(key, value)
    engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "brief.db"}')
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(PrivateWorkspaceBase.metadata.create_all)
    ids = {name: str(uuid4()) for name in ('mail', 'second', 'foreign', 'manual', 'ads')}
    seeds = [
        ('mail', '4', 'gmail', 'message1', 'Original private subject', 'Your payout was $700.'),
        ('second', '4', 'gmail', 'message2', 'Another private subject', 'Another private snippet'),
        ('foreign', '5', 'gmail', 'message3', 'Foreign private subject', 'Foreign private snippet'),
        ('manual', '4', 'manual', 'manual1', 'Private manual task', 'Private manual note'),
        ('ads', '4', 'google_ads', 'campaign1', 'Private campaign', 'Private campaign note'),
    ]
    connection_id = str(uuid4())
    async with sessions() as db:
        db.add(PrivateConnection(
            id=connection_id, owner_id='4', source_id='gmail', status='connected', generation=2,
            encrypted_credentials=encrypt_credentials({'access_token': 'synthetic-private-token'}),
            metadata_json={'account_label': 'owner@example.com', 'read_only_adapter': True},
        ))
        for name, owner, source, external, title, summary in seeds:
            db.add(PrivateItem(
                id=ids[name], owner_id=owner, source_id=source, external_id=external,
                kind='email' if source == 'gmail' else 'task', title=title, summary=summary,
                status='read', priority='normal', amount_minor=123456 if name == 'mail' else None,
                currency='USD' if name == 'mail' else None,
                due_at=utcnow() if name == 'mail' else None,
                action_status='done' if name == 'mail' else 'open',
                local_title='My local override' if name == 'mail' else None,
                local_summary='My local note' if name == 'mail' else None,
                evidence={'from': 'Sender <sender@example.com>', 'accounting_effect': 'none'},
            ))
        await db.commit()
    calls = []; content_calls = []; failures = []; hooks = []; content_hooks = []; billings = []

    async def fake_brief(plan, **arguments):
        assert arguments == {'reserved_micro_usd': 421911, 'price_policy': provider.PRICE_POLICY}
        calls.append(plan)
        if hooks:
            await hooks.pop(0)()
        if failures:
            raise failures.pop(0)
        return {
            'status': 'ready', 'provider': 'openai', 'version': provider.BRIEF_VERSION,
            'language': 'zh-CN', 'model': provider.model_identifier(),
            'title_zh': '私人邮件整理', 'summary_zh': '合成邮件说明款项，并要求本人核对。',
            'key_points': [{'text_zh': '核对邮件说明的款项', 'evidence': 'Your payout was $700.'}],
            'why_it_matters': '这封邮件可能与款项有关，发件人尚未核验。',
            'action_hint': '在原始邮件中核对回复要求。',
            'action_evidence': 'Please reply before October 15, 2026.',
            'deadline_text': 'October 15, 2026',
            'deadline_evidence': 'Please reply before October 15, 2026.',
            'amount_mentions': [{'text': '$700', 'evidence': 'Your payout was $700.'}],
            'needs_action': True, 'category': 'finance',
            'source_evidence': ['Your payout was $700.'], 'evidence_limited': plan.partial,
            'partial': plan.partial, 'read_only': True, 'source_hash': plan.source_hash,
            'generated_at': utcnow().isoformat(), 'characters': plan.character_count,
            'billing': billings.pop(0) if billings else None,
        }

    async def fake_content(credentials, metadata, message_id, **arguments):
        content_calls.append((metadata['account_label'], message_id))
        assert credentials == {'access_token': 'synthetic-private-token'}
        item = next(seed for seed in seeds if seed[3] == message_id)
        if content_hooks:
            await content_hooks.pop(0)()
        return {
            'title': item[4], 'summary': item[5],
            'body': 'PRIVATE FULL MAIL BODY. Your payout was $700. Please reply before October 15, 2026.',
            'has_body': True, 'truncated': False,
        }

    monkeypatch.setattr(provider, 'brief_mail', fake_brief)
    monkeypatch.setattr(service.gmail, 'fetch_mail_content', fake_content)
    try:
        yield SimpleNamespace(
            engine=engine, sessions=sessions, ids=ids, connection_id=connection_id,
            calls=calls, content_calls=content_calls, failures=failures, hooks=hooks,
            content_hooks=content_hooks,
            billings=billings,
        )
    finally:
        await engine.dispose()


async def usage(workspace, owner='4'):
    async with workspace.sessions() as db:
        result = (await db.execute(select(
            func.coalesce(func.sum(PrivateMailBriefUsage.characters), 0),
            func.coalesce(func.sum(PrivateMailBriefUsage.requests), 0),
        ).where(PrivateMailBriefUsage.owner_id == owner))).one()
        return tuple(result)


async def count_entries(workspace):
    async with workspace.sessions() as db:
        return await db.scalar(select(func.count()).select_from(PrivateMailBrief))


async def money_usage(workspace, owner='4', month=None):
    async with workspace.sessions() as db:
        statement = select(func.coalesce(func.sum(PrivateMailBriefUsage.reserved_usd_micros), 0)).where(
            PrivateMailBriefUsage.owner_id == owner)
        if month is not None: statement = statement.where(PrivateMailBriefUsage.month == month)
        return await db.scalar(statement)


def verified_billing(*, input_tokens=501, output_tokens=400):
    return {'price_policy': provider.PRICE_POLICY, 'reservation_micro_usd': 421911,
            'settlement_micro_usd': provider._price_micro_usd(input_tokens, output_tokens, provider.model_identifier()),
            'usage_verified': True, 'input_tokens': input_tokens, 'output_tokens': output_tokens}


async def alter_connection(workspace, **changes):
    async with workspace.sessions() as db:
        await db.execute(update(PrivateConnection).where(
            PrivateConnection.id == workspace.connection_id,
        ).values(**changes))
        await db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize('item_name,status', [
    ('foreign', 404), ('manual', 409), ('ads', 409), ('missing', 404),
])
async def test_owner_and_gmail_source_checked_before_body_cache_usage_or_provider(workspace, item_name, status):
    async with workspace.sessions() as db:
        with pytest.raises(HTTPException) as error:
            await service.brief_item(db, '4', workspace.ids.get(item_name, str(uuid4())))
    assert error.value.status_code == status
    assert workspace.calls == workspace.content_calls == []
    assert await usage(workspace) == (0, 0) and await count_entries(workspace) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('disabled_key', ['PRIVATE_MAIL_BRIEF_ENABLED', 'PRIVATE_MAIL_BRIEF_EXTERNAL_CONSENT'])
async def test_default_off_or_missing_external_consent_never_reads_or_sends_mail(workspace, monkeypatch, disabled_key):
    monkeypatch.delenv(disabled_key)
    monkeypatch.setenv('APP_AI_KEY', 'synthetic_crm_key_cannot_enable_private_mail')
    monkeypatch.setenv('OPENAI_API_KEY', 'synthetic_shared_key_cannot_enable_private_mail')
    async with workspace.sessions() as db:
        result = await service.brief_item(db, '4', workspace.ids['mail'], mode='body')
    assert result['configured'] is False and result['code'] == 'not_configured'
    assert result['brief']['state'] == 'unavailable'
    assert workspace.calls == workspace.content_calls == []
    assert await usage(workspace) == (0, 0) and await count_entries(workspace) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('changes', [
    {'status': 'disconnected'}, {'encrypted_credentials': None},
    {'metadata_json': {'account_label': 'owner@example.com'}},
    {'metadata_json': {'read_only_adapter': True}},
    {'metadata_json': {'account_label': 'owner@example.com', 'read_only_adapter': 'true'}},
])
async def test_unconnected_or_unverified_context_cannot_disclose_mail(workspace, changes):
    await alter_connection(workspace, **changes)
    async with workspace.sessions() as db:
        result = await service.brief_item(db, '4', workspace.ids['mail'])
    assert result['code'] == 'authorization_expired'
    assert workspace.calls == workspace.content_calls == []
    assert await usage(workspace) == (0, 0) and await count_entries(workspace) == 0


@pytest.mark.asyncio
async def test_expected_mailbox_mismatch_blocks_body_and_ai_before_cache(workspace, monkeypatch):
    monkeypatch.setenv('PRIVATE_WORKSPACE_GMAIL_EXPECTED_ACCOUNT', 'another@example.com')
    async with workspace.sessions() as db:
        result = await service.brief_item(db, '4', workspace.ids['mail'])
    assert result['code'] == 'authorization_expired'
    assert workspace.calls == workspace.content_calls == []
    assert await usage(workspace) == (0, 0) and await count_entries(workspace) == 0


@pytest.mark.asyncio
async def test_full_body_ready_result_cached_encrypted_and_preserves_private_item(workspace):
    fields = ('title', 'summary', 'local_title', 'local_summary', 'status', 'priority', 'amount_minor',
              'currency', 'due_at', 'action_status', 'evidence')
    async with workspace.sessions() as db:
        item = await db.get(PrivateItem, workspace.ids['mail'])
        before = {name: deepcopy(getattr(item, name)) for name in fields}
        first = await service.brief_item(db, '4', workspace.ids['mail'])
        second = await service.brief_item(db, '4', workspace.ids['mail'])
        entry = (await db.execute(select(PrivateMailBrief))).scalar_one()
        await db.refresh(item)
        after = {name: deepcopy(getattr(item, name)) for name in fields}
    assert first['configured'] is True and first['item_id'] == workspace.ids['mail']
    assert first['brief'] == second['brief'] and first['brief']['state'] == 'ready'
    assert first['brief']['title_zh'] == '私人邮件整理' and first['brief']['truncated'] is False
    assert first['brief']['source_scope'] == 'body'
    assert len(workspace.calls) == len(workspace.content_calls) == 1
    assert workspace.calls[0].title == 'Original private subject'
    assert workspace.calls[0].body.startswith('PRIVATE FULL MAIL BODY')
    assert before == after
    assert await usage(workspace) == (workspace.calls[0].character_count, 1)
    assert entry.input_hash == workspace.calls[0].source_hash
    assert entry.source_hash != entry.input_hash
    assert all(text not in entry.encrypted_content for text in (
        'PRIVATE FULL MAIL BODY', 'Original private subject', '私人邮件整理', '$700',
    ))
    assert all(key not in first['brief'] for key in (
        'body_original', 'body_zh', 'encrypted_content', 'lease_token',
    ))
    assert first['brief']['original_body'] == workspace.calls[0].body


@pytest.mark.asyncio
async def test_mail_without_readable_body_is_marked_as_preview_and_incomplete(workspace, monkeypatch):
    fetch = service.gmail.fetch_mail_content
    async def empty_body(*arguments, **keywords):
        content = await fetch(*arguments, **keywords)
        return {**content, 'body': '', 'has_body': False}
    monkeypatch.setattr(service.gmail, 'fetch_mail_content', empty_body)
    async with workspace.sessions() as db:
        result = await service.brief_item(db, '4', workspace.ids['mail'])
    assert result['brief']['state'] == 'ready' and result['brief']['truncated'] is True
    assert result['brief']['source_scope'] == 'preview'
    assert len(workspace.calls) == len(workspace.content_calls) == 1
    assert workspace.calls[0].body is None


@pytest.mark.asyncio
@pytest.mark.parametrize('limiting_key,limit', [
    ('PRIVATE_MAIL_BRIEF_MONTHLY_CHAR_LIMIT', '30'),
    ('PRIVATE_MAIL_BRIEF_MONTHLY_REQUEST_LIMIT', '1'),
])
async def test_character_and_request_reservations_are_atomic_and_owner_isolated(workspace, monkeypatch, limiting_key, limit):
    monkeypatch.setenv(limiting_key, limit)
    async def reserve():
        async with workspace.sessions() as db:
            return await service.reserve_usage(db, '4', 20, reservation_micro_usd=421911, price_policy=provider.PRICE_POLICY)
    results = await asyncio.gather(reserve(), reserve(), reserve())
    assert results.count(True) == 1 and results.count(False) == 2
    assert await usage(workspace) == (20, 1)
    async with workspace.sessions() as db:
        assert await service.reserve_usage(db, '5', 20, reservation_micro_usd=421911, price_policy=provider.PRICE_POLICY) is True
    assert await usage(workspace, '5') == (20, 1)


@pytest.mark.asyncio
async def test_usage_cap_blocks_provider_and_cache_still_readable_at_limit(workspace, monkeypatch):
    async with workspace.sessions() as db:
        first = await service.brief_item(db, '4', workspace.ids['mail'])
        reserved = await usage(workspace)
        monkeypatch.setenv('PRIVATE_MAIL_BRIEF_MONTHLY_CHAR_LIMIT', str(reserved[0]))
        monkeypatch.setenv('PRIVATE_MAIL_BRIEF_MONTHLY_REQUEST_LIMIT', '1')
        cached = await service.brief_item(db, '4', workspace.ids['mail'])
        blocked = await service.brief_item(db, '4', workspace.ids['second'])
    assert cached['brief'] == first['brief'] and cached['brief']['state'] == 'ready'
    assert blocked['code'] == 'limit_reached' and len(workspace.calls) == 1
    assert await usage(workspace) == reserved and len(workspace.content_calls) == 2


@pytest.mark.asyncio
async def test_one_inflight_duplicate_item_claims_one_ai_call_and_usage(workspace):
    started = asyncio.Event(); release = asyncio.Event()
    async def pause():
        started.set()
        await release.wait()
    workspace.hooks.append(pause)
    async def first_request():
        async with workspace.sessions() as db:
            return await service.brief_item(db, '4', workspace.ids['mail'])
    first = asyncio.create_task(first_request())
    try:
        await asyncio.wait_for(started.wait(), timeout=3)
        async with workspace.sessions() as db:
            pending = await service.brief_item(db, '4', workspace.ids['mail'])
        assert pending['brief']['state'] == 'pending'
    finally:
        release.set()
    ready = await first
    assert ready['brief']['state'] == 'ready' and len(workspace.calls) == 1
    assert await usage(workspace) == (workspace.calls[0].character_count, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize('changes', [
    {'status': 'disconnected', 'generation': 3},
    {'generation': 3, 'metadata_json': {'account_label': 'new-owner@example.com', 'read_only_adapter': True}},
])
async def test_disconnect_or_reconnect_during_body_read_stops_ai_disclosure_and_usage(workspace, changes):
    async def change_context():
        await alter_connection(workspace, **changes)
    workspace.content_hooks.append(change_context)
    async with workspace.sessions() as db:
        result = await service.brief_item(db, '4', workspace.ids['mail'])
    assert result['code'] == 'authorization_expired'
    assert len(workspace.content_calls) == 1 and workspace.calls == []
    assert await usage(workspace) == (0, 0)
    async with workspace.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(PrivateMailBrief).where(
            PrivateMailBrief.state == 'ready',
        )) == 0


@pytest.mark.asyncio
async def test_changed_original_during_body_read_stops_ai_disclosure(workspace):
    async def change_original():
        async with workspace.sessions() as db:
            await db.execute(update(PrivateItem).where(PrivateItem.id == workspace.ids['mail']).values(
                summary='A changed original snippet after read began',
            ))
            await db.commit()
    workspace.content_hooks.append(change_original)
    async with workspace.sessions() as db:
        result = await service.brief_item(db, '4', workspace.ids['mail'])
    assert result['code'] == 'authorization_expired'
    assert workspace.calls == [] and await usage(workspace) == (0, 0)


@pytest.mark.asyncio
async def test_consent_revoked_during_body_read_stops_ai_disclosure_and_usage(workspace, monkeypatch):
    async def revoke():
        monkeypatch.setenv('PRIVATE_MAIL_BRIEF_EXTERNAL_CONSENT', 'false')
    workspace.content_hooks.append(revoke)
    async with workspace.sessions() as db:
        result = await service.brief_item(db, '4', workspace.ids['mail'])
    assert result['code'] == 'not_configured'
    assert len(workspace.content_calls) == 1 and workspace.calls == []
    assert await usage(workspace) == (0, 0)


@pytest.mark.asyncio
async def test_disconnect_committed_after_reservation_before_final_guard_stops_ai_send(workspace):
    async with workspace.sessions() as db:
        original_commit = db.commit
        commits = 0
        async def commit_then_disconnect():
            nonlocal commits
            commits += 1
            await original_commit()
            # Claim and usage have committed. Revocation wins before any
            # external AI request, even though its allowance was reserved.
            if commits == 3:
                await alter_connection(workspace, status='disconnected', generation=3)
        db.commit = commit_then_disconnect
        result = await service.brief_item(db, '4', workspace.ids['mail'])
    assert result['code'] == 'authorization_expired' and result['brief']['state'] != 'ready'
    assert len(workspace.content_calls) == 1 and workspace.calls == []
    assert (await usage(workspace))[1] == 1  # Conservative reservations are never refunded.
    async with workspace.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(PrivateMailBrief).where(
            PrivateMailBrief.state == 'ready',
        )) == 0


@pytest.mark.asyncio
async def test_evidence_limitation_survives_detail_cache_and_compact_list(workspace, monkeypatch):
    fake_brief = provider.brief_mail
    async def limited_brief(plan, **arguments):
        result = await fake_brief(plan, **arguments)
        return {**result, 'evidence_limited': True}
    monkeypatch.setattr(provider, 'brief_mail', limited_brief)
    async with workspace.sessions() as db:
        first = await service.brief_item(db, '4', workspace.ids['mail'])
        cached = await service.brief_item(db, '4', workspace.ids['mail'])
        listed = await service.attach_cached_previews(db, '4', [
            {'id': workspace.ids['mail'], 'source_id': 'gmail'},
        ])
    assert first['brief']['evidence_limited'] is True
    assert cached['brief']['evidence_limited'] is True
    assert listed[0]['mail_brief']['evidence_limited'] is True
    assert first['brief']['truncated'] is False  # Evidence quality differs from incomplete reading.
    assert 'original_body' not in listed[0]['mail_brief']
    assert len(workspace.calls) == len(workspace.content_calls) == 1


@pytest.mark.asyncio
async def test_connection_changes_during_ai_call_prevent_result_return_and_ready_cache(workspace):
    async def disconnect():
        await alter_connection(workspace, status='disconnected', generation=3)
    workspace.hooks.append(disconnect)
    async with workspace.sessions() as db:
        result = await service.brief_item(db, '4', workspace.ids['mail'])
    assert result['code'] == 'authorization_expired' and result['brief']['state'] != 'ready'
    assert not result['brief'].get('title_zh')
    assert await usage(workspace) == (workspace.calls[0].character_count, 1)
    async with workspace.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(PrivateMailBrief).where(
            PrivateMailBrief.state == 'ready',
        )) == 0


@pytest.mark.asyncio
async def test_ambiguous_provider_failure_retains_usage_and_does_not_repeat_during_cooldown(workspace):
    workspace.failures.append(provider.MailBriefError('upstream_timeout'))
    async with workspace.sessions() as db:
        first = await service.brief_item(db, '4', workspace.ids['mail'])
        second = await service.brief_item(db, '4', workspace.ids['mail'])
    assert first['brief']['state'] == second['brief']['state'] == 'failed'
    assert first['code'] == second['code'] == 'upstream_unavailable'
    assert len(workspace.calls) == len(workspace.content_calls) == 1
    assert await usage(workspace) == (workspace.calls[0].character_count, 1)


@pytest.mark.asyncio
async def test_cached_list_briefs_expose_no_raw_body_or_cross_owner_data(workspace):
    async with workspace.sessions() as db:
        await service.brief_item(db, '4', workspace.ids['mail'])
        items = [
            {'id': workspace.ids['mail'], 'source_id': 'gmail'},
            {'id': workspace.ids['foreign'], 'source_id': 'gmail'},
            {'id': workspace.ids['manual'], 'source_id': 'manual'},
        ]
        attached = await service.attach_cached_previews(db, '4', items)
    assert attached[0]['mail_brief']['state'] == 'ready'
    assert all(key not in attached[0]['mail_brief'] for key in (
        'body_original', 'original_body', 'body', 'encrypted_content', 'lease_token', 'input_hash',
    ))
    assert 'PRIVATE FULL MAIL BODY' not in str(attached)
    assert 'mail_brief' not in attached[1] and 'mail_brief' not in attached[2]
    assert len(workspace.calls) == len(workspace.content_calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('changes', [
    {'status': 'disconnected', 'generation': 3},
    {'metadata_json': {'account_label': 'changed@example.com', 'read_only_adapter': True}},
])
async def test_cache_read_rechecks_connection_after_context_before_return(workspace, monkeypatch, changes):
    async with workspace.sessions() as db:
        await service.brief_item(db, '4', workspace.ids['mail'])
    claim = service._claim
    async def racing_claim(db, context):
        await alter_connection(workspace, **changes)
        return await claim(db, context)
    monkeypatch.setattr(service, '_claim', racing_claim)
    async with workspace.sessions() as db:
        result = await service.brief_item(db, '4', workspace.ids['mail'])
    assert result['code'] == 'authorization_expired' and not result['brief'].get('title_zh')
    assert len(workspace.calls) == len(workspace.content_calls) == 1


@pytest.mark.asyncio
async def test_cache_hash_mismatch_is_not_returned_as_current_body_brief(workspace):
    async with workspace.sessions() as db:
        await service.brief_item(db, '4', workspace.ids['mail'])
        await db.execute(update(PrivateMailBrief).values(input_hash='f' * 64))
        await db.commit()
        listed = await service.attach_cached_previews(db, '4', [
            {'id': workspace.ids['mail'], 'source_id': 'gmail'},
        ])
        assert 'mail_brief' not in listed[0]
        refreshed = await service.brief_item(db, '4', workspace.ids['mail'])
        entry = (await db.execute(select(PrivateMailBrief))).scalar_one()
    assert refreshed['brief']['state'] == 'ready' and len(workspace.calls) == 2
    assert entry.input_hash == workspace.calls[-1].source_hash


@pytest.mark.asyncio
async def test_disabled_service_does_not_return_existing_private_cache(workspace, monkeypatch):
    async with workspace.sessions() as db:
        await service.brief_item(db, '4', workspace.ids['mail'])
        monkeypatch.setenv('PRIVATE_MAIL_BRIEF_EXTERNAL_CONSENT', 'false')
        disabled = await service.brief_item(db, '4', workspace.ids['mail'])
        attached = await service.attach_cached_previews(db, '4', [
            {'id': workspace.ids['mail'], 'source_id': 'gmail'},
        ])
    assert disabled['code'] == 'not_configured' and disabled['brief']['state'] == 'unavailable'
    assert not disabled['brief'].get('title_zh') and 'mail_brief' not in attached[0]
    assert len(workspace.calls) == 1


@pytest.mark.asyncio
async def test_usd_budget_atomic_under_concurrent_requests_and_owner_isolation(workspace):
    async def reserve(owner='4'):
        async with workspace.sessions() as db:
            return await service.reserve_usage(db, owner, 20, reservation_micro_usd=421911,
                                               price_policy=provider.PRICE_POLICY)
    results = await asyncio.gather(*(reserve() for _ in range(16)))
    assert results.count(True) == 11 and results.count(False) == 5
    assert await usage(workspace) == (220, 11)
    assert await money_usage(workspace) == 421911 * 11
    assert await reserve('5') is True
    assert await usage(workspace, '5') == (20, 1) and await money_usage(workspace, '5') == 421911


@pytest.mark.asyncio
async def test_money_cap_blocks_ai_and_cache_does_not_charge_twice(workspace, monkeypatch):
    monkeypatch.setenv('PRIVATE_MAIL_BRIEF_MONTHLY_BUDGET_MICRO_USD', '421911')
    async with workspace.sessions() as db:
        ready = await service.brief_item(db, '4', workspace.ids['mail'])
        cached = await service.brief_item(db, '4', workspace.ids['mail'])
        blocked = await service.brief_item(db, '4', workspace.ids['second'])
        snapshot = await service.budget_snapshot(db, '4')
    assert ready['brief'] == cached['brief'] and ready['brief']['state'] == 'ready'
    assert blocked['code'] == 'budget_exhausted' and len(workspace.calls) == 1
    assert await money_usage(workspace) == 421911
    assert snapshot == {'configured': True, 'month': service.utcnow().strftime('%Y-%m'),
                        'limit_usd': '0.42', 'reserved_usd': '0.43', 'remaining_usd': '0.00'}
    assert all(key not in ready['brief'] for key in ('billing', 'price_policy', 'reservation_micro_usd'))


@pytest.mark.asyncio
async def test_verified_success_settles_once_atomically_with_ready_cache(workspace):
    workspace.billings.append(verified_billing())
    finish = service._finish
    captured = {}
    async def capturing_finish(db, context, token, **arguments):
        if arguments.get('result'):
            captured.update(context=context, token=token, arguments=arguments)
        return await finish(db, context, token, **arguments)
    # A duplicate completion with the old lease must neither refund twice nor
    # erase an already accepted cache result.
    from unittest.mock import patch
    with patch.object(service, '_finish', capturing_finish):
        async with workspace.sessions() as db:
            result = await service.brief_item(db, '4', workspace.ids['mail'])
    assert result['brief']['state'] == 'ready'
    assert await money_usage(workspace) == 841
    async with workspace.sessions() as db:
        entry = (await db.execute(select(PrivateMailBrief))).scalar_one()
        assert entry.reservation_state == 'settled' and entry.reservation_micro_usd == 421911
        assert entry.reservation_price_policy == provider.PRICE_POLICY
        assert await finish(db, captured['context'], captured['token'], **captured['arguments']) is False
        cached = await service.brief_item(db, '4', workspace.ids['mail'])
    assert cached['brief'] == result['brief'] and await money_usage(workspace) == 841
    assert len(workspace.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('change', [
    {'usage_verified': False}, {'settlement_micro_usd': 0}, {'settlement_micro_usd': -1},
    {'reservation_micro_usd': 421910}, {'price_policy': 'unapproved-price-policy'},
    {'input_tokens': 1047577}, {'output_tokens': 1801}, {'input_tokens': True},
])
async def test_unknown_or_forged_usage_cannot_release_reserved_usd(workspace, change):
    billing = verified_billing(); billing.update(change)
    workspace.billings.append(billing)
    async with workspace.sessions() as db:
        result = await service.brief_item(db, '4', workspace.ids['mail'])
        entry = (await db.execute(select(PrivateMailBrief))).scalar_one()
    assert result['brief']['state'] == 'ready' and entry.reservation_state == 'held'
    assert await money_usage(workspace) == 421911


@pytest.mark.asyncio
async def test_failures_missing_usage_and_final_auth_rejection_keep_full_reservation(workspace):
    workspace.failures.append(provider.MailBriefError('upstream_timeout'))
    async with workspace.sessions() as db:
        failed = await service.brief_item(db, '4', workspace.ids['mail'])
        unknown = await service.brief_item(db, '4', workspace.ids['second'])
    assert failed['brief']['state'] == 'failed' and unknown['brief']['state'] == 'ready'
    assert await money_usage(workspace) == 421911 * 2


@pytest.mark.asyncio
async def test_success_after_connection_revocation_cannot_settle_or_return_mail(workspace):
    workspace.billings.append(verified_billing())
    async def revoke():
        await alter_connection(workspace, status='disconnected', generation=3)
    workspace.hooks.append(revoke)
    async with workspace.sessions() as db:
        result = await service.brief_item(db, '4', workspace.ids['mail'])
    assert result['code'] == 'authorization_expired' and result['brief']['state'] != 'ready'
    assert await money_usage(workspace) == 421911


@pytest.mark.asyncio
async def test_month_boundary_settles_original_reservation_month_and_cache_is_free(workspace, monkeypatch):
    october = datetime(2026, 10, 31, 23, 59, 59, tzinfo=timezone.utc)
    november = datetime(2026, 11, 1, 0, 0, 1, tzinfo=timezone.utc)
    clock = [october]
    monkeypatch.setattr(service, 'utcnow', lambda: clock[0])
    workspace.billings.append(verified_billing())
    async def next_month(): clock[0] = november
    workspace.hooks.append(next_month)
    async with workspace.sessions() as db:
        result = await service.brief_item(db, '4', workspace.ids['mail'])
        cached = await service.brief_item(db, '4', workspace.ids['mail'])
        november_result = await service.brief_item(db, '4', workspace.ids['second'])
    assert result['brief'] == cached['brief'] and november_result['brief']['state'] == 'ready'
    assert await money_usage(workspace, month='2026-10') == 841
    assert await money_usage(workspace, month='2026-11') == 421911
    assert len(workspace.calls) == 2


@pytest.mark.asyncio
async def test_month_changes_after_reservation_before_send_pause_without_ai(workspace, monkeypatch):
    october = datetime(2026, 10, 31, 23, 59, 59, tzinfo=timezone.utc)
    november = datetime(2026, 11, 1, 0, 0, 1, tzinfo=timezone.utc)
    clock = [october]
    monkeypatch.setattr(service, 'utcnow', lambda: clock[0])
    async with workspace.sessions() as db:
        original_commit = db.commit
        commits = 0
        async def change_month_after_commit():
            nonlocal commits
            commits += 1
            await original_commit()
            if commits == 3:
                clock[0] = november
        db.commit = change_month_after_commit
        result = await service.brief_item(db, '4', workspace.ids['mail'])
    assert result['code'] == 'budget_month_changed' and workspace.calls == []
    assert await money_usage(workspace, month='2026-10') == 421911
    assert await money_usage(workspace, month='2026-11') == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['token', 'expired', 'receipt'])
async def test_final_guard_rejects_changed_lease_or_receipt_without_ai(workspace, change):
    async with workspace.sessions() as db:
        original_commit = db.commit
        commits = 0
        async def replace_after_commit():
            nonlocal commits
            commits += 1
            await original_commit()
            if commits == 3:
                values = {'lease_token': 'replacement-token'} if change == 'token' else (
                    {'lease_until': service.utcnow()} if change == 'expired' else {'reservation_micro_usd': 1})
                async with workspace.sessions() as other:
                    await other.execute(update(PrivateMailBrief).values(**values))
                    await other.commit()
        db.commit = replace_after_commit
        result = await service.brief_item(db, '4', workspace.ids['mail'])
    assert result['code'] == 'authorization_expired' and workspace.calls == []
    assert await money_usage(workspace) == 421911


@pytest.mark.asyncio
async def test_expired_lease_cannot_reserve_or_call_ai(workspace, monkeypatch):
    original_time = service.utcnow()
    clock = [original_time]
    monkeypatch.setattr(service, 'utcnow', lambda: clock[0])
    async def expire_lease():
        from datetime import timedelta
        clock[0] = original_time + timedelta(seconds=121)
    workspace.content_hooks.append(expire_lease)
    async with workspace.sessions() as db:
        result = await service.brief_item(db, '4', workspace.ids['mail'])
    assert result['brief']['state'] != 'ready' and workspace.calls == []
    assert await money_usage(workspace) == 0 and await usage(workspace) == (0, 0)


@pytest.mark.asyncio
async def test_budget_dto_rounds_reservation_up_and_remaining_down(workspace):
    async with workspace.sessions() as db:
        db.add(PrivateMailBriefUsage(owner_id='4', month=service.utcnow().strftime('%Y-%m'),
                                     characters=100, requests=1, reserved_usd_micros=841))
        await db.commit()
        snapshot = await service.budget_snapshot(db, '4')
        another_owner = await service.budget_snapshot(db, '5')
    assert snapshot['limit_usd'] == '5.00' and snapshot['reserved_usd'] == '0.01'
    assert snapshot['remaining_usd'] == '4.99' and snapshot['configured'] is True
    assert another_owner['reserved_usd'] == '0.00' and another_owner['remaining_usd'] == '5.00'


@pytest.mark.asyncio
async def test_legacy_nonzero_counts_are_not_a_fresh_free_usd_allowance(workspace):
    async with workspace.sessions() as db:
        db.add(PrivateMailBriefUsage(owner_id='4', month=service.utcnow().strftime('%Y-%m'),
                                     characters=500, requests=1, reserved_usd_micros=0))
        await db.commit()
        snapshot = await service.budget_snapshot(db, '4')
        allowed = await service.reserve_usage(db, '4', 20, reservation_micro_usd=421911,
                                              price_policy=provider.PRICE_POLICY)
    assert snapshot['reserved_usd'] == '5.00' and snapshot['remaining_usd'] == '0.00'
    assert allowed is False and await money_usage(workspace) == 5000000
    assert await usage(workspace) == (500, 1)


@pytest.mark.asyncio
async def test_private_budget_migration_preserves_legacy_rows_indexes_and_business_sentinel(tmp_path):
    business_path = tmp_path / 'crm-sentinel.db'
    with sqlite3.connect(business_path) as db:
        db.execute('CREATE TABLE receipts (id INTEGER PRIMARY KEY, amount INTEGER)')
        db.execute('INSERT INTO receipts VALUES (1,70000)')
    fingerprint = hashlib.sha256(business_path.read_bytes()).hexdigest()
    engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "old-private.db"}')
    try:
        async with engine.begin() as connection:
            await connection.execute(text('CREATE TABLE private_mail_brief_usage (owner_id VARCHAR(64) NOT NULL, '
                'month VARCHAR(7) NOT NULL, characters INTEGER NOT NULL DEFAULT 0, requests INTEGER NOT NULL DEFAULT 0, '
                'updated_at DATETIME, PRIMARY KEY(owner_id,month))'))
            await connection.execute(text("CREATE TABLE private_mail_briefs (cache_key VARCHAR(64) PRIMARY KEY, "
                "owner_id VARCHAR(64), state VARCHAR(16), encrypted_content TEXT)"))
            await connection.execute(text('CREATE INDEX legacy_brief_owner ON private_mail_briefs(owner_id)'))
            await connection.execute(text("INSERT INTO private_mail_brief_usage VALUES ('4','2026-10',500,1,'2026-10-11')"))
            await connection.execute(text("INSERT INTO private_mail_brief_usage VALUES ('5','2026-10',0,0,'2026-10-11')"))
            await connection.execute(text("INSERT INTO private_mail_briefs VALUES ('synthetic-key','4','ready','synthetic-encrypted-data')"))
            before_index = (await connection.execute(text("SELECT sql FROM sqlite_master WHERE name='legacy_brief_owner'"))).scalar_one()
            await service.migrate_private_mail_brief_budget(connection)
            await service.migrate_private_mail_brief_budget(connection)
            rows = (await connection.execute(text('SELECT owner_id,characters,requests,reserved_usd_micros FROM private_mail_brief_usage ORDER BY owner_id'))).all()
            cache = (await connection.execute(text('SELECT state,encrypted_content,reservation_month,reservation_micro_usd,reservation_price_policy,reservation_state FROM private_mail_briefs'))).one()
            after_index = (await connection.execute(text("SELECT sql FROM sqlite_master WHERE name='legacy_brief_owner'"))).scalar_one()
            assert rows == [('4', 500, 1, 5000000), ('5', 0, 0, 0)]
            assert cache == ('ready', 'synthetic-encrypted-data', None, 0, None, 'none')
            assert before_index == after_index
            await connection.execute(text("UPDATE private_mail_brief_usage SET reserved_usd_micros=841 WHERE owner_id='4'"))
            await service.migrate_private_mail_brief_budget(connection)
            assert (await connection.execute(text("SELECT reserved_usd_micros FROM private_mail_brief_usage WHERE owner_id='4'"))).scalar_one() == 841
        assert hashlib.sha256(business_path.read_bytes()).hexdigest() == fingerprint
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_budget_migration_rejects_business_or_mixed_schema_before_any_alter(tmp_path):
    engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "mixed.db"}')
    try:
        async with engine.begin() as connection:
            await connection.execute(text('CREATE TABLE customers (id INTEGER PRIMARY KEY)'))
            await connection.execute(text('CREATE TABLE private_mail_brief_usage (owner_id TEXT,month TEXT,characters INTEGER,requests INTEGER)'))
            with pytest.raises(RuntimeError, match='private_budget_schema_mismatch'):
                await service.migrate_private_mail_brief_budget(connection)
            columns = await connection.run_sync(lambda db: {column['name'] for column in inspect(db).get_columns('private_mail_brief_usage')})
            assert 'reserved_usd_micros' not in columns
    finally:
        await engine.dispose()
