"""Owner isolation, private encrypted caches and spending gates; no live HTTP."""
import asyncio
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models.private_workspace import PrivateConnection, PrivateItem, PrivateMailTranslation, PrivateTranslationUsage, PrivateWorkspaceBase, utcnow
from services import private_mail_translation as translator
from services import private_mail_translation_service as service
from services.private_workspace import encrypt_credentials


@pytest_asyncio.fixture
async def workspace(monkeypatch, tmp_path):
    monkeypatch.setenv('PRIVATE_WORKSPACE_ENCRYPTION_KEY', 'synthetic-encryption-key-for-private-translation-tests')
    monkeypatch.setenv('PRIVATE_GOOGLE_TRANSLATE_API_KEY', 'synthetic_private_translation_key_12345')
    monkeypatch.setenv('PRIVATE_MAIL_TRANSLATION_ENABLED', 'true')
    monkeypatch.setenv('PRIVATE_MAIL_TRANSLATION_MONTHLY_CHAR_LIMIT', '100000')
    monkeypatch.delenv('PRIVATE_WORKSPACE_GMAIL_EXPECTED_ACCOUNT', raising=False)
    engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "translation.db"}')
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(PrivateWorkspaceBase.metadata.create_all)
    ids = {name: str(uuid4()) for name in ('mail', 'second', 'foreign', 'manual')}
    seeds = [('mail', '4', 'gmail', 'message1', 'Original private subject', 'Original private snippet'),
             ('second', '4', 'gmail', 'message2', 'Another private subject', 'Another private snippet'),
             ('foreign', '5', 'gmail', 'message3', 'Foreign private subject', 'Foreign private snippet'),
             ('manual', '4', 'manual', 'manual1', 'Private manual task', 'Private manual note')]
    connection_id = str(uuid4())
    async with sessions() as db:
        db.add(PrivateConnection(id=connection_id, owner_id='4', source_id='gmail', status='connected', generation=2,
            encrypted_credentials=encrypt_credentials({'access_token': 'synthetic-private-token'}),
            metadata_json={'account_label': 'owner@example.com', 'read_only_adapter': True}))
        for name, owner, source, external, title, summary in seeds:
            db.add(PrivateItem(id=ids[name], owner_id=owner, source_id=source, external_id=external, kind='email' if source == 'gmail' else 'task',
                               title=title, summary=summary, status='read', evidence={}, local_title='My local override' if name == 'mail' else None))
        await db.commit()
    calls = []; content_calls = []; failures = []; hooks = []

    async def fake_translate(plan, **arguments):
        calls.append(plan)
        if hooks: await hooks.pop(0)()
        if failures: raise failures.pop(0)
        return {'title': '译文：' + plan.title, 'summary': '译文：' + plan.summary,
                'body': '中文正文：' + plan.body if plan.body is not None else None,
                'body_truncated': plan.body_truncated, 'translated_at': utcnow().isoformat(),
                'characters': plan.character_count, 'source_hash': plan.source_hash}

    async def fake_content(credentials, metadata, message_id, **arguments):
        content_calls.append((metadata['account_label'], message_id))
        assert credentials == {'access_token': 'synthetic-private-token'}
        item = next(seed for seed in seeds if seed[3] == message_id)
        return {'title': item[4], 'summary': item[5], 'body': 'PRIVATE FULL MAIL BODY',
                'has_body': True, 'truncated': False}

    monkeypatch.setattr(translator, 'translate_mail', fake_translate)
    monkeypatch.setattr(service.gmail, 'fetch_mail_content', fake_content)
    try:
        yield SimpleNamespace(engine=engine, sessions=sessions, ids=ids, connection_id=connection_id,
                              calls=calls, content_calls=content_calls, failures=failures, hooks=hooks)
    finally:
        await engine.dispose()


async def usage(workspace, owner='4'):
    async with workspace.sessions() as db:
        return await db.scalar(select(func.coalesce(func.sum(PrivateTranslationUsage.characters), 0))
                               .where(PrivateTranslationUsage.owner_id == owner))


async def count_entries(workspace):
    async with workspace.sessions() as db:
        return await db.scalar(select(func.count()).select_from(PrivateMailTranslation))


@pytest.mark.asyncio
@pytest.mark.parametrize('item_name,status', [('foreign', 404), ('manual', 409), ('missing', 404)])
async def test_owner_and_gmail_source_are_checked_before_cache_spend_or_network(workspace, item_name, status):
    async with workspace.sessions() as db:
        with pytest.raises(HTTPException) as error:
            await service.translate_item(db, '4', workspace.ids.get(item_name, str(uuid4())))
    assert error.value.status_code == status
    assert workspace.calls == workspace.content_calls == [] and await usage(workspace) == 0
    assert await count_entries(workspace) == 0


@pytest.mark.asyncio
async def test_disabled_service_has_no_cache_or_body_network_side_effect(workspace, monkeypatch):
    monkeypatch.setenv('PRIVATE_MAIL_TRANSLATION_ENABLED', 'false')
    async with workspace.sessions() as db:
        result = await service.translate_item(db, '4', workspace.ids['mail'], mode='body')
    assert result['configured'] is False and result['code'] == 'not_configured'
    assert workspace.calls == workspace.content_calls == [] and await count_entries(workspace) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('changes', [{'status': 'disconnected'}, {'encrypted_credentials': None},
                                    {'metadata_json': {'account_label': 'owner@example.com'}},
                                    {'metadata_json': {'read_only_adapter': True}}])
async def test_unconnected_or_unverified_context_cannot_disclose_mail(workspace, changes):
    async with workspace.sessions() as db:
        await db.execute(update(PrivateConnection).where(PrivateConnection.id == workspace.connection_id).values(**changes))
        await db.commit()
        result = await service.translate_item(db, '4', workspace.ids['mail'], mode='body')
    assert result['code'] == 'authorization_expired'
    assert workspace.calls == workspace.content_calls == [] and await count_entries(workspace) == 0


@pytest.mark.asyncio
async def test_preview_reuses_encrypted_cache_without_translating_local_override(workspace):
    async with workspace.sessions() as db:
        first = await service.translate_item(db, '4', workspace.ids['mail'], mode='preview')
        second = await service.translate_item(db, '4', workspace.ids['mail'], mode='preview')
    assert first['translation'] == second['translation'] and first['translation']['state'] == 'ready'
    assert first['translation']['title_zh'] == '译文：Original private subject'
    assert len(workspace.calls) == 1 and workspace.content_calls == []
    assert await usage(workspace) == workspace.calls[0].character_count
    async with workspace.sessions() as db:
        entry = (await db.execute(select(PrivateMailTranslation))).scalar_one()
        assert 'Original private' not in entry.encrypted_content and '译文' not in entry.encrypted_content
        assert service._decrypt(entry.encrypted_content)['title_zh'] == first['translation']['title_zh']
        original = await db.get(PrivateItem, workspace.ids['mail'])
        assert original.title == 'Original private subject' and original.local_title == 'My local override'
        assert original.amount_minor is None and original.currency is None


@pytest.mark.asyncio
async def test_cache_identity_changes_after_original_metadata_or_generation_changes(workspace):
    async with workspace.sessions() as db:
        await service.translate_item(db, '4', workspace.ids['mail'], mode='preview')
        await db.execute(update(PrivateItem).where(PrivateItem.id == workspace.ids['mail']).values(summary='Updated original snippet'))
        await db.commit()
        result = await service.translate_item(db, '4', workspace.ids['mail'], mode='preview')
        assert result['translation']['summary_zh'] == '译文：Updated original snippet'
        await db.execute(update(PrivateConnection).where(PrivateConnection.id == workspace.connection_id).values(generation=3))
        await db.commit()
        await service.translate_item(db, '4', workspace.ids['mail'], mode='preview')
    assert len(workspace.calls) == 3 and await count_entries(workspace) == 3


@pytest.mark.asyncio
async def test_corrupt_encrypted_cache_is_not_returned_and_is_refetched(workspace):
    async with workspace.sessions() as db:
        await service.translate_item(db, '4', workspace.ids['mail'], mode='preview')
        await db.execute(update(PrivateMailTranslation).values(encrypted_content='not-encrypted-mail'))
        await db.commit()
        result = await service.translate_item(db, '4', workspace.ids['mail'], mode='preview')
    assert len(workspace.calls) == 2 and result['translation']['state'] == 'ready'


@pytest.mark.asyncio
async def test_quota_reservation_is_atomic_under_concurrent_private_sessions(workspace, monkeypatch):
    monkeypatch.setenv('PRIVATE_MAIL_TRANSLATION_MONTHLY_CHAR_LIMIT', '30')
    async def reserve():
        async with workspace.sessions() as db: return await service.reserve_characters(db, '4', 20)
    results = await asyncio.gather(reserve(), reserve(), reserve())
    assert results.count(True) == 1 and results.count(False) == 2
    assert await usage(workspace) == 20
    async with workspace.sessions() as db:
        assert await service.reserve_characters(db, '5', 20) is True
    assert await usage(workspace, '5') == 20


@pytest.mark.asyncio
async def test_quota_block_stops_translation_and_does_not_increment_spend(workspace, monkeypatch):
    monkeypatch.setenv('PRIVATE_MAIL_TRANSLATION_MONTHLY_CHAR_LIMIT', '1')
    async with workspace.sessions() as db:
        result = await service.translate_item(db, '4', workspace.ids['mail'], mode='preview')
    assert result['code'] == 'limit_reached' and workspace.calls == []
    assert await usage(workspace) == 0


@pytest.mark.asyncio
async def test_ambiguous_provider_failure_keeps_reserved_characters_and_honors_cooldown(workspace):
    workspace.failures.append(translator.TranslationError('upstream_timeout'))
    async with workspace.sessions() as db:
        first = await service.translate_item(db, '4', workspace.ids['mail'], mode='preview')
        second = await service.translate_item(db, '4', workspace.ids['mail'], mode='preview')
    assert first['translation']['state'] == second['translation']['state'] == 'failed'
    assert first['code'] == second['code'] == 'upstream_unavailable'
    assert len(workspace.calls) == 1 and await usage(workspace) == workspace.calls[0].character_count


@pytest.mark.asyncio
async def test_only_one_same_item_request_claims_translation_and_reserves_spend(workspace):
    started = asyncio.Event(); release = asyncio.Event()
    async def pause(): started.set(); await release.wait()
    workspace.hooks.append(pause)
    async def first_request():
        async with workspace.sessions() as db:
            return await service.translate_item(db, '4', workspace.ids['mail'], mode='preview')
    first = asyncio.create_task(first_request())
    await started.wait()
    async with workspace.sessions() as db:
        pending = await service.translate_item(db, '4', workspace.ids['mail'], mode='preview')
    assert pending['translation']['state'] == 'pending'
    release.set(); ready = await first
    assert ready['translation']['state'] == 'ready' and len(workspace.calls) == 1
    assert await usage(workspace) == workspace.calls[0].character_count


@pytest.mark.asyncio
async def test_changed_connection_during_translation_prevents_result_return_or_cache_ready(workspace):
    async def disconnect():
        async with workspace.sessions() as db:
            await db.execute(update(PrivateConnection).where(PrivateConnection.id == workspace.connection_id)
                             .values(status='disconnected', generation=3)); await db.commit()
    workspace.hooks.append(disconnect)
    async with workspace.sessions() as db:
        result = await service.translate_item(db, '4', workspace.ids['mail'], mode='preview')
    assert result['code'] == 'authorization_expired' and result['translation']['title_zh'] is None
    async with workspace.sessions() as db:
        assert (await db.execute(select(PrivateMailTranslation.state))).scalar_one() != 'ready'
    assert await usage(workspace) == workspace.calls[0].character_count


@pytest.mark.asyncio
async def test_changed_original_mail_during_translation_prevents_stale_result_return(workspace):
    async def change_original():
        async with workspace.sessions() as db:
            await db.execute(update(PrivateItem).where(PrivateItem.id == workspace.ids['mail'])
                             .values(summary='New original snippet')); await db.commit()
    workspace.hooks.append(change_original)
    async with workspace.sessions() as db:
        result = await service.translate_item(db, '4', workspace.ids['mail'], mode='preview')
    assert result['code'] == 'authorization_expired' and result['translation']['title_zh'] is None
    async with workspace.sessions() as db:
        assert (await db.execute(select(PrivateMailTranslation.state))).scalar_one() != 'ready'
    assert await usage(workspace) == workspace.calls[0].character_count


@pytest.mark.asyncio
async def test_reconnect_during_body_fetch_stops_translation_disclosure_and_reservation(workspace, monkeypatch):
    fetch = service.gmail.fetch_mail_content
    async def reconnect_while_reading(credentials, metadata, message_id):
        content = await fetch(credentials, metadata, message_id)
        async with workspace.sessions() as db:
            await db.execute(update(PrivateConnection).where(PrivateConnection.id == workspace.connection_id)
                             .values(generation=3, metadata_json={'account_label': 'new-owner@example.com', 'read_only_adapter': True}))
            await db.commit()
        return content
    monkeypatch.setattr(service.gmail, 'fetch_mail_content', reconnect_while_reading)
    async with workspace.sessions() as db:
        result = await service.translate_item(db, '4', workspace.ids['mail'], mode='body')
    assert result['code'] == 'authorization_expired' and result['translation']['state'] == 'failed'
    assert len(workspace.content_calls) == 1 and workspace.calls == []
    assert await usage(workspace) == 0
    async with workspace.sessions() as db:
        assert (await db.execute(select(PrivateMailTranslation.state))).scalar_one() != 'ready'


@pytest.mark.asyncio
async def test_body_provider_rejection_does_not_reserve_or_disclose_to_translator(workspace, monkeypatch):
    async def reject_body(*arguments, **keywords):
        raise service.gmail.ProviderError('access_denied')
    monkeypatch.setattr(service.gmail, 'fetch_mail_content', reject_body)
    async with workspace.sessions() as db:
        result = await service.translate_item(db, '4', workspace.ids['mail'], mode='body')
    assert result['code'] == 'authorization_expired'
    assert workspace.calls == [] and await usage(workspace) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('changes', [
    {'status': 'disconnected', 'generation': 3},
    {'metadata_json': {'account_label': 'different@example.com', 'read_only_adapter': True}},
])
async def test_cached_result_is_rechecked_if_connection_changes_between_context_and_claim(workspace, monkeypatch, changes):
    async with workspace.sessions() as db:
        await service.translate_item(db, '4', workspace.ids['mail'], mode='preview')
    claim = service._claim
    async def racing_claim(db, row, context, mode):
        async with workspace.sessions() as other:
            await other.execute(update(PrivateConnection).where(PrivateConnection.id == workspace.connection_id)
                                .values(**changes)); await other.commit()
        return await claim(db, row, context, mode)
    monkeypatch.setattr(service, '_claim', racing_claim)
    async with workspace.sessions() as db:
        result = await service.translate_item(db, '4', workspace.ids['mail'], mode='preview')
    assert result.get('code') == 'authorization_expired' and result['translation']['title_zh'] is None
    assert len(workspace.calls) == 1


@pytest.mark.asyncio
async def test_cached_result_is_rechecked_if_original_mail_changes_between_context_and_claim(workspace, monkeypatch):
    async with workspace.sessions() as db:
        await service.translate_item(db, '4', workspace.ids['mail'], mode='preview')
    claim = service._claim
    async def racing_claim(db, row, context, mode):
        async with workspace.sessions() as other:
            await other.execute(update(PrivateItem).where(PrivateItem.id == workspace.ids['mail'])
                                .values(summary='Changed original after context')); await other.commit()
        return await claim(db, row, context, mode)
    monkeypatch.setattr(service, '_claim', racing_claim)
    async with workspace.sessions() as db:
        result = await service.translate_item(db, '4', workspace.ids['mail'], mode='preview')
    assert result['code'] == 'authorization_expired' and result['translation']['title_zh'] is None
    assert len(workspace.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('ids', [[], list(range(11))])
async def test_batch_bounds_are_checked_before_side_effects(workspace, ids):
    async with workspace.sessions() as db:
        with pytest.raises(HTTPException) as error: await service.translate_batch(db, '4', ids)
    assert error.value.status_code == 422 and workspace.calls == []
    assert await count_entries(workspace) == 0 and await usage(workspace) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('unauthorized', ['foreign', 'manual'])
async def test_batch_authorizes_every_requested_item_before_any_spending_or_cache_claim(workspace, unauthorized):
    async with workspace.sessions() as db:
        with pytest.raises(HTTPException):
            await service.translate_batch(db, '4', [workspace.ids['mail'], workspace.ids[unauthorized]])
    assert workspace.calls == workspace.content_calls == []
    assert await count_entries(workspace) == 0 and await usage(workspace) == 0


@pytest.mark.asyncio
async def test_batch_deduplicates_authorized_ids_and_never_fetches_full_bodies(workspace):
    async with workspace.sessions() as db:
        result = await service.translate_batch(db, '4', [workspace.ids['mail'], workspace.ids['second'], workspace.ids['mail']])
    assert len(result['items']) == len(workspace.calls) == 2 and workspace.content_calls == []
    assert {entry['item_id'] for entry in result['items']} == {workspace.ids['mail'], workspace.ids['second']}
    assert all('body_original' not in entry['translation'] and 'body_zh' not in entry['translation'] for entry in result['items'])


@pytest.mark.asyncio
async def test_full_body_is_encrypted_and_only_returned_to_the_requested_owner_body_view(workspace):
    async with workspace.sessions() as db:
        body = await service.translate_item(db, '4', workspace.ids['mail'], mode='body')
        cached = await service.translate_item(db, '4', workspace.ids['mail'], mode='body')
        items = [{'id': workspace.ids['mail'], 'source_id': 'gmail'}]
        listed = await service.attach_cached_previews(db, '4', items)
    assert body['translation'] == cached['translation']
    assert body['translation']['body_original'] == 'PRIVATE FULL MAIL BODY'
    assert body['translation']['body_zh'] == '中文正文：PRIVATE FULL MAIL BODY'
    assert body['translation']['body_available'] is True
    assert len(workspace.calls) == len(workspace.content_calls) == 1
    assert 'mail_translation' not in listed[0]  # A body cache never fills the preview slot.
    async with workspace.sessions() as db:
        entry = (await db.execute(select(PrivateMailTranslation))).scalar_one()
        assert entry.mode == 'body' and 'PRIVATE FULL MAIL BODY' not in entry.encrypted_content
        assert 'body_original' not in service._decrypt(entry.encrypted_content)
        with pytest.raises(HTTPException) as error:
            await service.translate_item(db, '5', workspace.ids['mail'], mode='body')
        assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_maximum_body_is_preserved_in_encrypted_cache_and_readable_at_spending_limit(workspace, monkeypatch):
    original = 'Private original mail.\n' * 2500
    original = original[:50000]
    assert len(original) == 50000
    fetch = service.gmail.fetch_mail_content
    async def large_body(credentials, metadata, message_id):
        content = await fetch(credentials, metadata, message_id)
        return {**content, 'body': original, 'truncated': True}
    monkeypatch.setattr(service.gmail, 'fetch_mail_content', large_body)
    async with workspace.sessions() as db:
        first = await service.translate_item(db, '4', workspace.ids['mail'], mode='body')
        reserved = await usage(workspace)
        monkeypatch.setenv('PRIVATE_MAIL_TRANSLATION_MONTHLY_CHAR_LIMIT', str(reserved))
        second = await service.translate_item(db, '4', workspace.ids['mail'], mode='body')
        entry = (await db.execute(select(PrivateMailTranslation))).scalar_one()
        assert original not in entry.encrypted_content
        assert service._decrypt(entry.encrypted_content, body=True)['body_original'] == original
    assert second['translation'] == first['translation']
    assert first['translation']['body_original'] == original
    assert first['translation']['body_zh'] == '中文正文：' + original
    assert first['translation']['truncated'] is True
    assert len(workspace.calls) == len(workspace.content_calls) == 1 and await usage(workspace) == reserved


@pytest.mark.asyncio
async def test_disabled_translation_does_not_return_existing_body_cache(workspace, monkeypatch):
    async with workspace.sessions() as db:
        first = await service.translate_item(db, '4', workspace.ids['mail'], mode='body')
        assert first['translation']['state'] == 'ready'
        monkeypatch.setenv('PRIVATE_MAIL_TRANSLATION_ENABLED', 'false')
        disabled = await service.translate_item(db, '4', workspace.ids['mail'], mode='body')
    assert disabled['code'] == 'not_configured' and disabled['translation']['state'] == 'unavailable'
    assert disabled['translation'].get('body_original') is None and disabled['translation'].get('body_zh') is None
    assert len(workspace.calls) == len(workspace.content_calls) == 1


@pytest.mark.asyncio
async def test_list_preview_does_not_expose_ciphertext_body_or_cross_owner_cache(workspace):
    async with workspace.sessions() as db:
        await service.translate_item(db, '4', workspace.ids['mail'], mode='preview')
        items = [{'id': workspace.ids['mail'], 'source_id': 'gmail'}, {'id': workspace.ids['foreign'], 'source_id': 'gmail'}]
        attached = await service.attach_cached_previews(db, '4', items)
    assert attached[0]['mail_translation']['state'] == 'ready'
    assert all(key not in attached[0]['mail_translation'] for key in ('body_original', 'body_zh', 'encrypted_content', 'lease_token'))
    assert 'mail_translation' not in attached[1]
