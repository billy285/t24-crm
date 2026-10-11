"""Owner-bound Hosted Link sessions and bank batch validation; private DB only."""
from datetime import datetime, timedelta, timezone
import re
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import and_, false, or_, select, update

from models.private_workspace import PrivateBankLink, PrivateConnection, PrivateItem, utcnow
from services import private_bank_provider as provider


def _core():
    # The core integrates these functions lazily too; never import CRM app/jobs.
    from services import private_workspace
    return private_workspace


def _owner(owner_id):
    owner_id = str(owner_id)
    if owner_id != '4':
        raise HTTPException(status_code=403, detail='仅老板本人可以连接私人银行')
    return owner_id


async def _owner_still_valid(callback):
    if callback and not await callback():
        raise HTTPException(status_code=403, detail='私人空间访问权限已失效')


def _aware(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


async def _connection(db, owner_id, *, create=False):
    return await _core().connection_for(db, owner_id, 'bofa_bank', create=create)


async def _cancel_session(db, row, state='canceled'):
    await db.execute(update(PrivateBankLink).where(PrivateBankLink.id == row.id, PrivateBankLink.owner_id == row.owner_id).values(
        state=state, encrypted_context=None, lease_until=None, updated_at=utcnow()))
    await db.execute(update(PrivateConnection).where(PrivateConnection.id == row.connection_id,
        PrivateConnection.owner_id == row.owner_id, PrivateConnection.generation == row.generation,
        PrivateConnection.source_id == 'bofa_bank', PrivateConnection.status == 'connecting').values(
        status='disconnected', encrypted_credentials=None, sync_lease_until=None))
    await db.commit()


async def begin_bank_link(db, owner_id, *, transport=None, owner_validator=None):
    owner_id = _owner(owner_id)
    settings = provider.bank_settings()
    await _owner_still_valid(owner_validator)
    connection = await _connection(db, owner_id, create=True)
    connection_id, generation = connection.id, connection.generation
    now, session_id = utcnow(), str(uuid4())
    if connection.status == 'connecting':
        existing = (await db.execute(select(PrivateBankLink).where(
            PrivateBankLink.owner_id == owner_id, PrivateBankLink.connection_id == connection_id,
            PrivateBankLink.generation == generation, PrivateBankLink.state.in_(['pending', 'exchanging']),
            PrivateBankLink.expires_at > now).order_by(PrivateBankLink.created_at.desc()))).scalars().first()
        if existing:
            if existing.lease_until and _aware(existing.lease_until) > now:
                raise HTTPException(status_code=409, detail='银行授权正在确认，请稍后查看')
            if not existing.encrypted_context:
                raise HTTPException(status_code=409, detail='银行授权页面正在准备，请稍后重试')
            context = _core().decrypt_credentials(existing.encrypted_context)
            if (context.get('environment') != settings['environment']
                    or context.get('client_fingerprint') != settings['client_fingerprint']):
                raise HTTPException(status_code=409, detail='银行服务器配置已改变，请取消后重新连接')
            await _owner_still_valid(owner_validator)
            return {'session_id': existing.id, 'authorization_url': provider.hosted_url(context.get('authorization_url')),
                    'expires_at': _aware(existing.expires_at).isoformat(), 'mode': settings['environment']}
    claimed = await db.execute(update(PrivateConnection).where(PrivateConnection.id == connection_id,
        PrivateConnection.owner_id == owner_id, PrivateConnection.generation == generation).values(
        generation=generation + 1, status='connecting', encrypted_credentials=None,
        metadata_json={}, error=None, last_sync=None, sync_lease_until=None))
    if claimed.rowcount != 1:
        await db.rollback()
        raise HTTPException(status_code=409, detail='银行连接状态已改变，请重新打开')
    await db.execute(update(PrivateBankLink).where(PrivateBankLink.owner_id == owner_id,
        PrivateBankLink.connection_id == connection_id, PrivateBankLink.state.in_(['pending', 'exchanging'])).values(
        state='canceled', encrypted_context=None, lease_until=None))
    row = PrivateBankLink(id=session_id, owner_id=owner_id, connection_id=connection_id,
        generation=generation + 1, state='pending', expires_at=now + timedelta(seconds=900))
    db.add(row)
    await db.commit()
    # Rollback expires ORM attributes even with expire_on_commit=False. Keep
    # immutable session identity across provider waits and cleanup paths.
    row = SimpleNamespace(id=session_id, owner_id=owner_id, connection_id=connection_id, generation=generation + 1)
    try:
        result = await provider.create_hosted_link(owner_id, session_id, transport=transport)
        await _owner_still_valid(owner_validator)
        now = utcnow()
        expires = provider._aware(result['expires_at'])
        identity = await db.execute(update(PrivateConnection).where(PrivateConnection.id == connection_id,
            PrivateConnection.owner_id == owner_id, PrivateConnection.generation == generation + 1,
            PrivateConnection.status == 'connecting').values(error=None))
        if identity.rowcount != 1 or expires <= now:
            raise HTTPException(status_code=409, detail='银行连接已取消或超时，请重新连接')
        context = {key: result[key] for key in ('link_token', 'environment', 'client_fingerprint', 'authorization_url')}
        saved = await db.execute(update(PrivateBankLink).where(PrivateBankLink.id == session_id,
            PrivateBankLink.owner_id == owner_id, PrivateBankLink.state == 'pending',
            PrivateBankLink.generation == generation + 1).values(
            encrypted_context=_core().encrypt_credentials(context), expires_at=expires))
        if saved.rowcount != 1:
            raise HTTPException(status_code=409, detail='银行连接状态已改变，请重新连接')
        await db.commit()
        return {'session_id': session_id, 'authorization_url': result['authorization_url'],
                'expires_at': expires.isoformat(), 'mode': settings['environment']}
    except Exception as error:
        await db.rollback()
        await _cancel_session(db, row, 'canceled' if isinstance(error, HTTPException) else 'failed')
        if isinstance(error, HTTPException):
            raise
        detail = error.public_message if isinstance(error, provider.BankProviderError) else '银行连接暂不可用，请稍后重试'
        raise HTTPException(status_code=502, detail=detail) from None


async def complete_bank_link(db, owner_id, session_id, *, transport=None, owner_validator=None):
    owner_id = _owner(owner_id)
    await _owner_still_valid(owner_validator)
    try:
        if str(UUID(session_id)) != session_id:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(status_code=422, detail='银行连接请求格式无效') from None
    row = (await db.execute(select(PrivateBankLink).where(PrivateBankLink.id == session_id,
        PrivateBankLink.owner_id == owner_id).execution_options(populate_existing=True))).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail='银行连接请求不存在')
    row = SimpleNamespace(**{key: getattr(row, key) for key in (
        'id', 'owner_id', 'connection_id', 'generation', 'state', 'expires_at', 'encrypted_context', 'lease_until')})
    connection = await _connection(db, owner_id)
    current = (connection and connection.id == row.connection_id and connection.generation == row.generation)
    if current and row.state == 'completed' and bank_connection_identity(connection, require_snapshot=False):
        await _owner_still_valid(owner_validator)
        return {'state': 'connected', 'session_id': session_id, 'source_id': 'bofa_bank'}
    if not current or connection.status != 'connecting' or row.state not in {'pending', 'exchanging'}:
        await _cancel_session(db, row)
        raise HTTPException(status_code=409, detail='银行连接已取消，请重新连接')
    now = utcnow()
    if _aware(row.expires_at) <= now:
        await _cancel_session(db, row, 'expired')
        raise HTTPException(status_code=409, detail='银行连接请求已过期，请重新连接')
    if not row.encrypted_context:
        return {'state': 'pending', 'session_id': session_id, 'source_id': 'bofa_bank'}
    # Verify local encryption before obtaining a lease. A temporarily unavailable
    # cipher must not block retries or lose a recoverable short-lived grant.
    context = _core().decrypt_credentials(row.encrypted_context)
    lease = now + timedelta(seconds=provider.MAX_SECONDS + 15)
    claimed = await db.execute(update(PrivateBankLink).where(PrivateBankLink.id == session_id,
        PrivateBankLink.owner_id == owner_id, PrivateBankLink.generation == row.generation,
        PrivateBankLink.state.in_(['pending', 'exchanging']), PrivateBankLink.expires_at > now,
        or_(PrivateBankLink.lease_until.is_(None), PrivateBankLink.lease_until < now)).values(
        state='exchanging', lease_until=lease).execution_options(synchronize_session=False))
    if claimed.rowcount != 1:
        await db.rollback()
        return {'state': 'pending', 'session_id': session_id, 'source_id': 'bofa_bank'}
    await db.commit()

    async def save_exchanged(credentials):
        await _owner_still_valid(owner_validator)
        binding = await db.execute(update(PrivateConnection).where(PrivateConnection.id == row.connection_id,
            PrivateConnection.owner_id == owner_id, PrivateConnection.generation == row.generation,
            PrivateConnection.status == 'connecting').values(error=None))
        if binding.rowcount != 1:
            raise HTTPException(status_code=409, detail='银行连接状态已改变，请重新连接')
        saved = await db.execute(update(PrivateBankLink).where(PrivateBankLink.id == session_id,
            PrivateBankLink.owner_id == owner_id, PrivateBankLink.generation == row.generation,
            PrivateBankLink.state == 'exchanging', PrivateBankLink.lease_until == lease,
            PrivateBankLink.expires_at > utcnow()).values(
            encrypted_context=_core().encrypt_credentials({**context, **credentials})))
        if saved.rowcount != 1:
            raise HTTPException(status_code=409, detail='银行连接请求已改变或超时')
        await db.commit()

    try:
        result = await provider.exchange_completed_link(context, owner_id=owner_id, transport=transport, on_exchanged=save_exchanged)
        await _owner_still_valid(owner_validator)
        if result is None:
            await db.execute(update(PrivateBankLink).where(PrivateBankLink.id == session_id,
                PrivateBankLink.owner_id == owner_id, PrivateBankLink.state == 'exchanging',
                PrivateBankLink.lease_until == lease).values(state='pending', lease_until=None))
            await db.commit()
            return {'state': 'pending', 'session_id': session_id, 'source_id': 'bofa_bank'}
        provider.checked_credentials(result['credentials'], owner_id=owner_id)
        saved = await db.execute(update(PrivateBankLink).where(PrivateBankLink.id == session_id,
            PrivateBankLink.owner_id == owner_id, PrivateBankLink.generation == row.generation,
            PrivateBankLink.state == 'exchanging', PrivateBankLink.lease_until == lease,
            PrivateBankLink.expires_at > utcnow()).values(state='completed', completed_at=utcnow(),
                lease_until=None, encrypted_context=None))
        if saved.rowcount != 1:
            raise HTTPException(status_code=409, detail='银行连接请求已改变或超时')
        changed = await db.execute(update(PrivateConnection).where(PrivateConnection.id == row.connection_id,
            PrivateConnection.owner_id == owner_id, PrivateConnection.source_id == 'bofa_bank',
            PrivateConnection.generation == row.generation, PrivateConnection.status == 'connecting').values(
            status='connected', encrypted_credentials=_core().encrypt_credentials(result['credentials']),
            metadata_json=result['metadata'], error=None, last_sync=None, sync_lease_until=None))
        if changed.rowcount != 1:
            raise HTTPException(status_code=409, detail='银行授权已改变，请重新连接')
        await db.commit()
        return {'state': 'connected', 'session_id': session_id, 'source_id': 'bofa_bank'}
    except Exception as error:
        await db.rollback()
        if isinstance(error, provider.BankProviderError) and error.retryable:
            await db.execute(update(PrivateBankLink).where(PrivateBankLink.id == session_id,
                PrivateBankLink.owner_id == owner_id, PrivateBankLink.state == 'exchanging',
                PrivateBankLink.lease_until == lease).values(state='pending', lease_until=None))
            await db.commit()
        else:
            await _cancel_session(db, row, 'canceled' if isinstance(error, HTTPException) else 'failed')
        if isinstance(error, HTTPException):
            raise
        detail = error.public_message if isinstance(error, provider.BankProviderError) else '银行授权未完成，请重新连接'
        raise HTTPException(status_code=502, detail=detail) from None


def bank_connection_identity(connection, *, require_snapshot=True):
    if not connection or str(connection.owner_id) != '4' or connection.source_id != 'bofa_bank' or connection.status != 'connected':
        return None
    try:
        settings = provider.bank_settings()
        meta = connection.metadata_json or {}
        item_id, institution = provider._id(meta.get('bank_item_id')), provider._id(meta.get('bank_institution_id'))
        if (meta.get('bank_environment') != settings['environment'] or meta.get('bank_client_fingerprint') != settings['client_fingerprint']
                or not institution.startswith('ins_') or settings['institution_id'] and institution != settings['institution_id']):
            return None
        identity = {'item_id': item_id, 'institution_id': institution, 'environment': settings['environment'],
                    'client_fingerprint': settings['client_fingerprint']}
        if not require_snapshot:
            return identity
        snapshot = meta.get('bank_snapshot')
        if (not isinstance(snapshot, dict) or not re.fullmatch(r'[a-f0-9]{32}', snapshot.get('id', ''))
                or any(snapshot.get(key) != identity[key] for key in ('item_id', 'institution_id', 'environment'))
                or snapshot.get('accounts_complete') is not True or snapshot.get('pagination_complete') is not True
                or snapshot.get('balance_realtime') is not False
                or snapshot.get('transaction_update_status') not in provider.UPDATE_STATES
                or type(snapshot.get('transactions_complete')) is not bool
                or snapshot['transactions_complete'] != (snapshot['transaction_update_status'] == 'HISTORICAL_UPDATE_COMPLETE')):
            return None
        observed, synced = provider._aware(snapshot.get('observed_at')), _aware(connection.last_sync)
        if not synced or observed > synced:
            return None
        accounts = meta.get('bank_accounts')
        if not isinstance(accounts, list) or not 0 < len(accounts) <= provider.MAX_ACCOUNTS:
            return None
        account_ids = [provider._id(row.get('account_id')) for row in accounts
                       if isinstance(row, dict) and row.get('balance_source') == 'cached_accounts_get']
        if len(account_ids) != len(accounts) or len(set(account_ids)) != len(account_ids):
            return None
        return {**identity, 'snapshot_id': snapshot['id'], 'observed_at': observed, 'account_ids': account_ids}
    except (provider.BankProviderError, TypeError, ValueError, AttributeError):
        return None


async def current_bank_condition(db, owner_id, *, require_snapshot=True):
    owner_id = str(owner_id)
    connection = await _connection(db, owner_id)
    identity = bank_connection_identity(connection, require_snapshot=require_snapshot)
    if not identity:
        return false()
    condition = and_(PrivateItem.owner_id == owner_id, PrivateItem.source_id == 'bofa_bank',
        PrivateItem.status.notin_(['removed', 'replaced']),
        PrivateItem.evidence['bank_item_id'].as_string() == identity['item_id'],
        PrivateItem.evidence['bank_environment'].as_string() == identity['environment'],
        PrivateItem.evidence['bank_institution_id'].as_string() == identity['institution_id'])
    if require_snapshot:
        condition = and_(condition, PrivateItem.evidence['bank_account_id'].as_string().in_(identity['account_ids']))
    return condition


def validate_bank_batch(connection, batch, started_at):
    def check(condition):
        if not condition:
            raise ValueError('invalid current bank batch')
    identity = bank_connection_identity(connection, require_snapshot=False)
    check(identity and isinstance(batch, dict) and batch.get('balances') == [])
    meta = batch.get('metadata')
    check(isinstance(meta, dict) and meta.get('bank_item_id') == identity['item_id']
          and meta.get('bank_environment') == identity['environment'] and meta.get('bank_institution_id') == identity['institution_id']
          and meta.get('bank_client_fingerprint') == identity['client_fingerprint'])
    snapshot = meta.get('bank_snapshot')
    check(isinstance(snapshot, dict) and isinstance(snapshot.get('id'), str) and re.fullmatch(r'[a-f0-9]{32}', snapshot['id'])
          and all(snapshot.get(key) == identity[key] for key in ('item_id', 'institution_id', 'environment'))
          and snapshot.get('accounts_complete') is True and snapshot.get('pagination_complete') is True
          and snapshot.get('balance_realtime') is False and snapshot.get('transaction_update_status') in provider.UPDATE_STATES
          and type(snapshot.get('transactions_complete')) is bool
          and snapshot['transactions_complete'] == (snapshot['transaction_update_status'] == 'HISTORICAL_UPDATE_COMPLETE'))
    observed = provider._aware(snapshot.get('observed_at'))
    check(_aware(started_at) - timedelta(seconds=5) <= observed <= utcnow() + timedelta(seconds=5))
    accounts = meta.get('bank_accounts')
    check(isinstance(accounts, list) and 0 < len(accounts) <= provider.MAX_ACCOUNTS)
    account_ids = set()
    for account in accounts:
        check(isinstance(account, dict))
        account_id = provider._id(account.get('account_id'))
        check(account_id not in account_ids and account.get('balance_source') == 'cached_accounts_get'
              and isinstance(account.get('name'), str) and 0 < len(account['name']) <= 120
              and account.get('type') in {'depository', 'credit', 'loan', 'investment', 'other'}
              and account.get('balance_kind') == ('owed' if account['type'] in {'credit', 'loan'} else 'funds' if account['type'] == 'depository' else 'other')
              and (account.get('mask') is None or isinstance(account['mask'], str) and re.fullmatch(r'[0-9]{1,4}', account['mask'])))
        account_ids.add(account_id)
        currency = account.get('currency')
        check(currency is None or isinstance(currency, str) and re.fullmatch(r'[A-Z]{3}', currency))
        for key in ('current_minor', 'available_minor', 'limit_minor'):
            amount = account.get(key)
            check(amount is None or type(amount) is int and abs(amount) <= 9000000000000000 and currency)
    items = batch.get('items')
    check(isinstance(items, list) and len(items) <= provider.MAX_TRANSACTIONS)
    present = set()
    for item in items:
        evidence = item.get('evidence') if isinstance(item, dict) else None
        check(isinstance(evidence, dict) and item.get('kind') == 'bank_transaction'
              and item.get('status') in {'pending', 'posted'} and type(evidence.get('pending')) is bool
              and evidence['pending'] == (item['status'] == 'pending')
              and evidence.get('bank_item_id') == identity['item_id'] and evidence.get('bank_environment') == identity['environment']
              and evidence.get('bank_institution_id') == identity['institution_id'] and evidence.get('bank_account_id') in account_ids
              and evidence.get('bank_snapshot_id') == snapshot['id'] and evidence.get('bank_observed_at') == snapshot['observed_at']
              and evidence.get('accounting_effect') == 'none')
        transaction = provider._id(evidence.get('bank_transaction_id'))
        check(item.get('external_id') == identity['item_id'] + ':' + transaction and item['external_id'] not in present)
        currency = item.get('currency')
        check(currency is None or isinstance(currency, str) and re.fullmatch(r'[A-Z]{3}', currency))
        signed = provider._decimal(evidence.get('amount_decimal'))
        check(evidence.get('amount_direction') == ('inflow' if signed > 0 else 'outflow' if signed < 0 else 'neutral')
              and item.get('amount_minor') == provider._minor(signed, currency)
              and (item.get('amount_minor') is None or type(item['amount_minor']) is int)
              and item.get('source_url') == 'https://secure.bankofamerica.com/')
        present.add(item['external_id'])
    for key in ('removed_external_ids', 'replaced_pending_external_ids'):
        values = batch.get(key)
        check(isinstance(values, list) and len(values) <= provider.MAX_TRANSACTIONS and len(values) == len(set(values)))
        for value in values:
            check(isinstance(value, str) and value.startswith(identity['item_id'] + ':') and value not in present)
            provider._id(value[len(identity['item_id']) + 1:])
    credentials = batch.get('credentials')
    provider.checked_credentials(credentials)
    original = _core().decrypt_credentials(connection.encrypted_credentials)
    check({key: value for key, value in credentials.items() if key != 'transaction_cursor'} ==
          {key: value for key, value in original.items() if key != 'transaction_cursor'})
    return identity
