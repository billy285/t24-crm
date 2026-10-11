"""Private mail brief isolation, encrypted caching and usage gates; synthetic data only."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select, update
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
        'PRIVATE_MAIL_BRIEF_ENABLED', 'PRIVATE_MAIL_BRIEF_EXTERNAL_CONSENT',
        'PRIVATE_MAIL_BRIEF_PROVIDER', 'PRIVATE_MAIL_BRIEF_OPENAI_API_KEY',
        'PRIVATE_MAIL_BRIEF_MODEL', 'PRIVATE_MAIL_BRIEF_MONTHLY_CHAR_LIMIT',
        'PRIVATE_MAIL_BRIEF_MONTHLY_REQUEST_LIMIT', 'PRIVATE_WORKSPACE_GMAIL_EXPECTED_ACCOUNT',
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in {
        'PRIVATE_WORKSPACE_ENCRYPTION_KEY': 'synthetic-encryption-key-for-private-brief-tests',
        'PRIVATE_MAIL_BRIEF_ENABLED': 'true',
        'PRIVATE_MAIL_BRIEF_EXTERNAL_CONSENT': 'true',
        'PRIVATE_MAIL_BRIEF_PROVIDER': 'openai',
        'PRIVATE_MAIL_BRIEF_OPENAI_API_KEY': 'synthetic_private_brief_key_12345',
        'PRIVATE_MAIL_BRIEF_MODEL': 'synthetic-approved-model',
        'PRIVATE_MAIL_BRIEF_MONTHLY_CHAR_LIMIT': '100000',
        'PRIVATE_MAIL_BRIEF_MONTHLY_REQUEST_LIMIT': '100',
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
    calls = []; content_calls = []; failures = []; hooks = []; content_hooks = []

    async def fake_brief(plan, **arguments):
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
            return await service.reserve_usage(db, '4', 20)
    results = await asyncio.gather(reserve(), reserve(), reserve())
    assert results.count(True) == 1 and results.count(False) == 2
    assert await usage(workspace) == (20, 1)
    async with workspace.sessions() as db:
        assert await service.reserve_usage(db, '5', 20) is True
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
