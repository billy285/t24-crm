"""Bounded Plaid reads for the owner's Bank of America source only.

No payment, transfer, balance-refresh, email/SMS delivery or arbitrary endpoint
is available. Link/exchange authorizes reads; all provider tokens stay server-side.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
import os
import re
import time
from urllib.parse import urlsplit, urlencode
from uuid import UUID, uuid4

import httpx

from services.private_workspace_providers import ProviderError


ERRORS = {
    'bank_not_configured': '银行只读连接尚未完成服务器配置',
    'bank_authorization_expired': '银行授权已失效，请重新连接',
    'bank_identity_changed': '银行机构、账户来源或环境与原授权不一致，请重新连接',
    'bank_access_denied': '银行只读授权未获批准，请检查连接权限',
    'bank_invalid_response': '银行来源返回的数据无法安全读取',
    'bank_rate_limited': '银行请求过于频繁，请稍后重试',
    'bank_upstream_unavailable': '银行来源暂时不可用，请稍后重试',
    'bank_upstream_timeout': '银行来源响应超时，请稍后重试',
    'bank_pagination_changed': '银行流水同步期间发生变化，请重新同步完整批次',
    'bank_sync_limit': '银行流水批次超过安全上限，本轮未保存，请核对后重试',
    'bank_request_not_allowed': '不允许此银行操作',
}
PATHS = frozenset({'/link/token/create', '/link/token/get', '/item/public_token/exchange',
                   '/item/get', '/institutions/get_by_id', '/accounts/get', '/transactions/sync'})
HOSTS = {'production': 'production.plaid.com', 'sandbox': 'sandbox.plaid.com'}
MAX_BYTES = 4 * 1024 * 1024
MAX_PAGES = 25
MAX_TRANSACTIONS = 10000
MAX_ACCOUNTS = 50
MAX_SECONDS = 65
UPDATE_STATES = {'UNKNOWN', 'NOT_READY', 'INITIAL_UPDATE_COMPLETE', 'HISTORICAL_UPDATE_COMPLETE'}
ID = re.compile(r'[A-Za-z0-9_-]{1,128}')
# ISO 4217 List One, SIX maintenance agency, published 2026-09-17 and
# verified 2026-10-11. Plaid decimal amounts use ISO units, unlike Stripe's
# provider-specific exceptions. Unspecified/new codes have no inferred scale.
# https://www.six-group.com/dam/download/financial-information/data-center/iso-currrency/lists/list-one.xml
ISO_MINOR_UNITS = {
    **dict.fromkeys('BIF CLP DJF GNF ISK JPY KMF KRW PYG RWF UGX UYI VND VUV XAF XOF XPF'.split(), 0),
    **dict.fromkeys(('AED AFN ALL AMD AOA ARS AUD AWG AZN BAM BBD BDT BMD BND BOB BOV BRL BSD BTN BWP BYN BZD '
        'CAD CDF CHE CHF CHW CNY COP COU CRC CUP CVE CZK DKK DOP DZD EGP ERN ETB EUR FJD FKP GBP GEL GHS GIP '
        'GMD GTQ GYD HKD HNL HTG HUF IDR ILS INR IRR JMD KES KGS KHR KPW KYD KZT LAK LBP LKR LRD LSL MAD MDL '
        'MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN MXV MYR MZN NAD NGN NIO NOK NPR NZD PAB PEN PGK PHP PKR PLN '
        'QAR RON RSD RUB SAR SBD SCR SDG SEK SGD SHP SLE SOS SRD SSP STN SVC SYP SZL THB TJS TMT TOP TRY TTD '
        'TWD TZS UAH USD USN UYU UZS VED VES WST XAD XCD XCG YER ZAR ZMW ZWG').split(), 2),
    **dict.fromkeys('BHD IQD JOD KWD LYD OMR TND'.split(), 3),
    **dict.fromkeys('CLF UYW'.split(), 4),
}


class BankProviderError(ProviderError):
    def __init__(self, code):
        self.code = code if code in ERRORS else 'bank_upstream_unavailable'
        self.public_message = ERRORS[self.code]
        self.retryable = self.code in {'bank_rate_limited', 'bank_upstream_unavailable', 'bank_upstream_timeout', 'bank_pagination_changed'}
        RuntimeError.__init__(self, self.public_message)


def _need(condition, code='bank_invalid_response'):
    if not condition:
        raise BankProviderError(code)


def _id(value):
    _need(isinstance(value, str) and ID.fullmatch(value))
    return value


def _opaque(value, maximum=8192):
    _need(isinstance(value, str) and 1 <= len(value) <= maximum and not re.search(r'[\x00-\x20\x7f]', value))
    return value


def bank_missing_configuration():
    missing = []
    if os.getenv('PRIVATE_WORKSPACE_PLAID_ENABLED', '').lower() != 'true':
        missing.append('PRIVATE_WORKSPACE_PLAID_ENABLED')
    for key in ('PRIVATE_WORKSPACE_PLAID_CLIENT_ID', 'PRIVATE_WORKSPACE_PLAID_SECRET'):
        value = os.getenv(key, '')
        if not re.fullmatch(r'[A-Za-z0-9_-]{8,256}', value):
            missing.append(key)
    if os.getenv('PRIVATE_WORKSPACE_PLAID_ENV', 'production') not in HOSTS:
        missing.append('PRIVATE_WORKSPACE_PLAID_ENV')
    try:
        _public_origin()
    except BankProviderError:
        missing.append('PRIVATE_WORKSPACE_PUBLIC_URL')
    institution = os.getenv('PRIVATE_WORKSPACE_BOFA_INSTITUTION_ID', '')
    if institution and not re.fullmatch(r'ins_[A-Za-z0-9_-]{1,100}', institution):
        missing.append('PRIVATE_WORKSPACE_BOFA_INSTITUTION_ID')
    return missing


# Source registry integration imports this exact public name lazily.
missing_configuration = bank_missing_configuration


def _public_origin():
    value = os.getenv('PRIVATE_WORKSPACE_PUBLIC_URL', '').rstrip('/')
    try:
        p = urlsplit(value)
        _need(p.scheme == 'https' and p.hostname and not p.username and not p.password
              and p.port in (None, 443) and not p.path and not p.query and not p.fragment, 'bank_not_configured')
    except ValueError:
        raise BankProviderError('bank_not_configured') from None
    return value


def bank_settings():
    _need(not bank_missing_configuration(), 'bank_not_configured')
    client = os.environ['PRIVATE_WORKSPACE_PLAID_CLIENT_ID']
    return {'client_id': client, 'secret': os.environ['PRIVATE_WORKSPACE_PLAID_SECRET'],
            'environment': os.getenv('PRIVATE_WORKSPACE_PLAID_ENV', 'production'),
            'client_fingerprint': hashlib.sha256(client.encode()).hexdigest(),
            'institution_id': os.getenv('PRIVATE_WORKSPACE_BOFA_INSTITUTION_ID') or None}


def checked_credentials(credentials, *, owner_id='4'):
    settings = bank_settings()
    _need(isinstance(credentials, dict) and credentials.get('owner_id') == owner_id
          and credentials.get('environment') == settings['environment']
          and credentials.get('client_fingerprint') == settings['client_fingerprint'], 'bank_identity_changed')
    _id(credentials.get('item_id'))
    institution = _id(credentials.get('institution_id'))
    _need(institution.startswith('ins_') and (not settings['institution_id'] or institution == settings['institution_id']),
          'bank_identity_changed')
    _need(_opaque(credentials.get('access_token')).startswith('access-' + settings['environment'] + '-'),
          'bank_identity_changed')
    cursor = credentials.get('transaction_cursor', '')
    _need(isinstance(cursor, str) and len(cursor) <= 4096 and not re.search(r'[\x00-\x20\x7f]', cursor))
    return settings


def _aware(value, *, optional=False):
    if value is None and optional:
        return None
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
        _need(isinstance(dt, datetime) and dt.tzinfo is not None)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        raise BankProviderError('bank_invalid_response') from None


class BankClient:
    def __init__(self, settings, transport=None):
        self.settings = settings
        self.http = httpx.AsyncClient(transport=transport, trust_env=False, follow_redirects=False,
                                     timeout=httpx.Timeout(12, connect=5))
        self.deadline = time.monotonic() + MAX_SECONDS
        self.requests = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *unused):
        await self.http.aclose()

    async def request(self, path, payload):
        _need(path in PATHS and isinstance(payload, dict) and not {'client_id', 'secret'} & set(payload),
              'bank_request_not_allowed')
        self.requests += 1
        _need(self.requests <= MAX_PAGES + 7, 'bank_sync_limit')
        remaining = self.deadline - time.monotonic()
        _need(remaining > 0, 'bank_upstream_timeout')

        async def operation():
            async with self.http.stream('POST', 'https://' + HOSTS[self.settings['environment']] + path,
                                        json={**payload, 'client_id': self.settings['client_id'], 'secret': self.settings['secret']},
                                        headers={'Plaid-Version': '2020-09-14', 'Content-Type': 'application/json'}) as response:
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    _need(len(body) <= MAX_BYTES)
                _need(not 300 <= response.status_code < 400, 'bank_request_not_allowed')
                try:
                    value = json.loads(body, parse_float=Decimal,
                                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                except (ValueError, UnicodeError):
                    raise BankProviderError('bank_invalid_response') from None
                _need(isinstance(value, dict))
                error = value.get('error_code')
                if error or response.status_code != 200:
                    code = ('bank_pagination_changed' if error == 'TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION'
                            else 'bank_authorization_expired' if error in {'ITEM_LOGIN_REQUIRED', 'ITEM_NOT_FOUND', 'INVALID_ACCESS_TOKEN'}
                            else 'bank_rate_limited' if response.status_code == 429 or error == 'RATE_LIMIT_EXCEEDED'
                            else 'bank_access_denied' if response.status_code in (401, 403) or error in {'INVALID_API_KEYS', 'PRODUCT_NOT_READY', 'ACCESS_NOT_GRANTED'}
                            else 'bank_upstream_unavailable')
                    raise BankProviderError(code)
                return value

        try:
            return await asyncio.wait_for(operation(), timeout=remaining)
        except (asyncio.TimeoutError, TimeoutError, httpx.TimeoutException):
            raise BankProviderError('bank_upstream_timeout') from None
        except httpx.HTTPError:
            raise BankProviderError('bank_upstream_unavailable') from None


def hosted_url(value):
    try:
        p = urlsplit(value)
        _need(p.scheme == 'https' and p.hostname == 'secure.plaid.com' and p.port in (None, 443)
              and not p.username and not p.password and not p.query and not p.fragment
              and re.fullmatch(r'/hl/[A-Za-z0-9_-]{8,256}', p.path), 'bank_invalid_response')
    except (ValueError, TypeError):
        raise BankProviderError('bank_invalid_response') from None
    return value


async def create_hosted_link(owner_id, session_id, *, transport=None):
    _need(owner_id == '4', 'bank_access_denied')
    _need(str(UUID(session_id)) == session_id)
    settings = bank_settings()
    redirect = _public_origin() + '/private-workspace?' + urlencode({'view': 'bofa_bank', 'bank_session': session_id})
    async with BankClient(settings, transport) as client:
        response = await client.request('/link/token/create', {
            'client_name': 'T24 Private Workspace', 'country_codes': ['US'], 'language': 'en',
            'user': {'client_user_id': 't24-private-owner-' + owner_id}, 'products': ['transactions'],
            'hosted_link': {'completion_redirect_uri': redirect, 'is_mobile_app': False, 'url_lifetime_seconds': 900},
        })
    token = _opaque(response.get('link_token'))
    _need(token.startswith('link-' + settings['environment'] + '-'), 'bank_identity_changed')
    expiration = _aware(response.get('expiration'))
    now = datetime.now(timezone.utc)
    _need(expiration > now)
    return {'link_token': token, 'authorization_url': hosted_url(response.get('hosted_link_url')),
            'expires_at': min(expiration, now + timedelta(seconds=900)).isoformat(),
            'environment': settings['environment'], 'client_fingerprint': settings['client_fingerprint']}


def _institution_identity(value, expected_id=None):
    _need(isinstance(value, dict))
    institution_id = _id(value.get('institution_id'))
    name = value.get('name')
    _need(isinstance(name, str) and len(name) <= 200)
    canonical = re.sub('[^a-z]', '', name.lower())
    _need(canonical in {'bankofamerica', 'bankofamericanationalassociation', 'bankofamericabusiness',
                        'bankofamericabusinessadvantage', 'bankofamericacommercial'}
          and (not expected_id or institution_id == expected_id), 'bank_identity_changed')
    _need('US' in value.get('country_codes', []) and 'transactions' in value.get('products', []), 'bank_access_denied')
    return {'institution_id': institution_id, 'institution_name': name}


async def verify_item(client, credentials):
    response = await client.request('/item/get', {'access_token': credentials['access_token']})
    item = response.get('item')
    _need(isinstance(item, dict) and item.get('item_id') == credentials['item_id']
          and item.get('institution_id') == credentials['institution_id'], 'bank_identity_changed')
    _need(not item.get('error'), 'bank_authorization_expired')
    institution = await client.request('/institutions/get_by_id', {'institution_id': credentials['institution_id'], 'country_codes': ['US']})
    identity = _institution_identity(institution.get('institution'), credentials['institution_id'])
    updated = ((item.get('status') or {}).get('transactions') or {}).get('last_successful_update')
    return {**identity, 'bank_updated_at': _aware(updated, optional=True).isoformat() if updated else None}


async def exchange_completed_link(context, *, owner_id='4', transport=None, on_exchanged=None):
    settings = bank_settings()
    _need(isinstance(context, dict) and context.get('environment') == settings['environment']
          and context.get('client_fingerprint') == settings['client_fingerprint'], 'bank_identity_changed')
    link_token = _opaque(context.get('link_token'))
    _need(link_token.startswith('link-' + settings['environment'] + '-'), 'bank_identity_changed')
    async with BankClient(settings, transport) as client:
        if context.get('access_token'):
            credentials = {key: context[key] for key in ('access_token', 'item_id', 'institution_id', 'environment', 'client_fingerprint')}
            credentials.update(owner_id=owner_id, transaction_cursor='')
        else:
            result = await client.request('/link/token/get', {'link_token': link_token})
            _need(result.get('link_token') == link_token, 'bank_identity_changed')
            sessions = result.get('link_sessions') or []
            _need(isinstance(sessions, list) and len(sessions) <= 20)
            successes = []
            for session in sessions:
                _need(isinstance(session, dict))
                values = (session.get('results') or {}).get('item_add_results') or []
                _need(isinstance(values, list) and len(values) <= 2)
                successes.extend(values)
            if not successes:
                return None
            _need(len(successes) == 1 and isinstance(successes[0], dict), 'bank_identity_changed')
            success = successes[0]
            institution = success.get('institution') or {}
            institution_id = _id(institution.get('institution_id'))
            _need(not settings['institution_id'] or institution_id == settings['institution_id'], 'bank_identity_changed')
            public_token = _opaque(success.get('public_token'))
            _need(public_token.startswith('public-' + settings['environment'] + '-'), 'bank_identity_changed')
            exchanged = await client.request('/item/public_token/exchange', {'public_token': public_token})
            credentials = {'access_token': _opaque(exchanged.get('access_token')), 'item_id': _id(exchanged.get('item_id')),
                           'institution_id': institution_id, 'environment': settings['environment'],
                           'client_fingerprint': settings['client_fingerprint'], 'owner_id': owner_id, 'transaction_cursor': ''}
        checked_credentials(credentials, owner_id=owner_id)
        if on_exchanged:
            # The one-time public token is never persisted. Save only the
            # encrypted access-token stage before later verification can fail.
            await on_exchanged(credentials)
        identity = await verify_item(client, credentials)
        checked_credentials(credentials, owner_id=owner_id)
    return {'credentials': credentials, 'metadata': {'bank_item_id': credentials['item_id'],
            'bank_environment': settings['environment'], 'bank_institution_id': credentials['institution_id'],
            'bank_client_fingerprint': settings['client_fingerprint'],
            'bank_institution_name': identity['institution_name'], 'account_label': 'Bank of America',
            'mode': 'live' if settings['environment'] == 'production' else 'test',
            'connection_mode': 'plaid_hosted_link', 'read_only_adapter': True}}


def _decimal(value):
    _need(not isinstance(value, bool) and isinstance(value, (str, int, float, Decimal)))
    try:
        result = Decimal(str(value))
        _need(result.is_finite() and abs(result) <= Decimal('90000000000000'))
        return result
    except InvalidOperation:
        raise BankProviderError('bank_invalid_response') from None


def _currency(row):
    iso, unofficial = row.get('iso_currency_code'), row.get('unofficial_currency_code')
    _need(not (iso and unofficial))
    if iso is not None:
        _need(isinstance(iso, str) and re.fullmatch(r'[A-Z]{3}', iso))
    if unofficial is not None:
        _need(isinstance(unofficial, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,24}', unofficial))
    return iso, unofficial


def _minor(value, currency):
    if value is None or currency not in ISO_MINOR_UNITS:
        return None
    value = int((_decimal(value) * (10 ** ISO_MINOR_UNITS[currency])).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    _need(abs(value) <= 9000000000000000)
    return value


def _text(value, limit=240):
    return re.sub(r'[\x00-\x1f\x7f]', ' ', str(value or '')).strip()[:limit]


def _accounts(response, credentials):
    item = response.get('item')
    _need(isinstance(item, dict) and item.get('item_id') == credentials['item_id']
          and item.get('institution_id') == credentials['institution_id'], 'bank_identity_changed')
    values = response.get('accounts')
    _need(isinstance(values, list) and 0 < len(values) <= MAX_ACCOUNTS)
    accounts = []
    seen = set()
    for row in values:
        _need(isinstance(row, dict))
        account = _id(row.get('account_id'))
        _need(account not in seen)
        seen.add(account)
        balances = row.get('balances')
        _need(isinstance(balances, dict))
        currency, unofficial = _currency(balances)
        kind = row.get('type')
        _need(kind in {'depository', 'credit', 'loan', 'investment', 'other'})
        mask = row.get('mask')
        _need(mask is None or isinstance(mask, str) and re.fullmatch(r'[0-9]{1,4}', mask))
        updated = _aware(balances.get('last_updated_datetime'), optional=True)
        accounts.append({'account_id': account, 'name': _text(row.get('name') or 'Bank of America', 120),
            'mask': mask, 'type': kind, 'subtype': _text(row.get('subtype'), 60) or None,
            'currency': currency, 'unofficial_currency': unofficial,
            **{label + '_minor': _minor(balances.get(label), currency) for label in ('current', 'available', 'limit')},
            'current_decimal': str(_decimal(balances['current'])) if balances.get('current') is not None else None,
            'balance_kind': 'owed' if kind in {'credit', 'loan'} else 'funds' if kind == 'depository' else 'other',
            'balance_source': 'cached_accounts_get', 'balance_updated_at': updated.isoformat() if updated else None})
    return accounts


def _transaction(row, credentials, accounts, snapshot):
    _need(isinstance(row, dict))
    transaction = _id(row.get('transaction_id'))
    account_id = _id(row.get('account_id'))
    _need(account_id in accounts, 'bank_identity_changed')
    amount = _decimal(row.get('amount'))
    currency, unofficial = _currency(row)
    _need(type(row.get('pending')) is bool)
    try:
        day = date.fromisoformat(row.get('date'))
    except (TypeError, ValueError):
        raise BankProviderError('bank_invalid_response') from None
    precise = _aware(row.get('datetime'), optional=True)
    pending_id = row.get('pending_transaction_id')
    if pending_id is not None:
        _id(pending_id)
        _need(not row['pending'] and pending_id != transaction)
    direction = 'outflow' if amount > 0 else 'inflow' if amount < 0 else 'neutral'
    account = accounts[account_id]
    evidence = {'bank_item_id': credentials['item_id'], 'bank_environment': credentials['environment'],
        'bank_institution_id': credentials['institution_id'], 'bank_account_id': account_id,
        'bank_account_mask': account['mask'], 'bank_transaction_id': transaction, 'pending': row['pending'],
        'pending_transaction_id': pending_id, 'bank_snapshot_id': snapshot['id'],
        'bank_observed_at': snapshot['observed_at'], 'accounting_effect': 'none',
        'transaction_date': day.isoformat(), 'amount_direction': direction,
        'amount_decimal': str(-amount), 'unofficial_currency': unofficial,
        'balance_kind': account['balance_kind'], 'date_timezone': 'institution_not_supplied'}
    return {'external_id': credentials['item_id'] + ':' + transaction, 'kind': 'bank_transaction',
        'title': _text(row.get('merchant_name') or row.get('name') or '银行交易'),
        'summary': ('待入账' if row['pending'] else '已入账') + ' · ' + account['name'],
        'status': 'pending' if row['pending'] else 'posted', 'priority': 'low',
        'amount_minor': _minor(-amount, currency), 'currency': currency,
        'occurred_at': precise.isoformat() if precise else None,
        'source_url': 'https://secure.bankofamerica.com/', 'evidence': evidence}


async def fetch_bofa_bank(credentials, *, transport=None):
    settings = checked_credentials(credentials)
    async with BankClient(settings, transport) as client:
        identity = await verify_item(client, credentials)
        account_values = _accounts(await client.request('/accounts/get', {'access_token': credentials['access_token']}), credentials)
        accounts = {row['account_id']: row for row in account_values}
        snapshot = {'id': uuid4().hex, 'observed_at': datetime.now(timezone.utc).isoformat(),
            'item_id': credentials['item_id'], 'environment': credentials['environment'],
            'institution_id': credentials['institution_id'], 'accounts_complete': True,
            'balance_realtime': False, 'bank_updated_at': identity['bank_updated_at']}
        cursor = credentials.get('transaction_cursor', '')
        items, removed, replaced = {}, set(), set()
        seen_cursors = {cursor}
        total = 0
        for page in range(MAX_PAGES):
            payload = {'access_token': credentials['access_token'], 'count': 500}
            if cursor:
                payload['cursor'] = cursor
            result = await client.request('/transactions/sync', payload)
            _need(type(result.get('has_more')) is bool)
            next_cursor = result.get('next_cursor')
            _need(isinstance(next_cursor, str) and len(next_cursor) <= 4096 and not re.search(r'[\x00-\x20\x7f]', next_cursor))
            for field in ('added', 'modified', 'removed'):
                values = result.get(field)
                _need(isinstance(values, list) and len(values) <= 500)
                total += len(values)
                _need(total <= MAX_TRANSACTIONS, 'bank_sync_limit')
                for row in values:
                    if field == 'removed':
                        _need(isinstance(row, dict))
                        transaction = _id(row.get('transaction_id'))
                        account_id = row.get('account_id')
                        if account_id is not None:
                            _need(_id(account_id) in accounts, 'bank_identity_changed')
                        external_id = credentials['item_id'] + ':' + transaction
                        removed.add(external_id)
                        items.pop(external_id, None)
                    else:
                        value = _transaction(row, credentials, accounts, snapshot)
                        items[value['external_id']] = value
                        removed.discard(value['external_id'])
                        pending_id = value['evidence']['pending_transaction_id']
                        if pending_id:
                            replaced.add(credentials['item_id'] + ':' + pending_id)
            cursor = next_cursor
            if not result['has_more']:
                state = result.get('transactions_update_status', 'UNKNOWN')
                _need(state in UPDATE_STATES)
                snapshot.update(transaction_update_status=state, pagination_complete=True,
                                transactions_complete=state == 'HISTORICAL_UPDATE_COMPLETE')
                break
            _need(cursor and cursor not in seen_cursors, 'bank_invalid_response')
            seen_cursors.add(cursor)
        else:
            raise BankProviderError('bank_sync_limit')
        for external_id in replaced:
            items.pop(external_id, None)
        # Recheck server configuration after all external waits. The core must
        # additionally recheck live connection generation before atomic commit.
        checked_credentials(credentials)
        return {'items': list(items.values()), 'balances': [],
            'removed_external_ids': sorted(removed), 'replaced_pending_external_ids': sorted(replaced),
            'credentials': {**credentials, 'transaction_cursor': cursor},
            'metadata': {'bank_item_id': credentials['item_id'], 'bank_environment': settings['environment'],
                'bank_client_fingerprint': settings['client_fingerprint'],
                'bank_institution_id': credentials['institution_id'], 'bank_institution_name': identity['institution_name'],
                'bank_accounts': account_values, 'bank_snapshot': snapshot, 'account_label': 'Bank of America',
                'coverage': 'plaid_transactions_sync', 'partial': not snapshot['transactions_complete'],
                'sync_window': 'cursor_changes', 'aggregated_totals': False, 'accounting_effect': 'none',
                'mode': 'live' if settings['environment'] == 'production' else 'test', 'read_only_adapter': True}}
