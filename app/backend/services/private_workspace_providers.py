"""Owner-workspace read adapters. No CRM imports, database writes or payment actions.

Credentials returned by this module are for the encrypted core store only. Google
Ads' fixed search RPC uses POST, but no provider mutation endpoint is permitted.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from email.utils import getaddresses
import json
import os
import re
import time
from types import MappingProxyType
from urllib.parse import urlencode, urlsplit

import httpx

GMAIL_SCOPE = 'https://www.googleapis.com/auth/gmail.readonly'
ADS_SCOPE = 'https://www.googleapis.com/auth/adwords'
ADS_VERSION = 'v25'
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_REQUESTS = 90
MAX_SYNC_SECONDS = 45
GMAIL_LIMIT = 80
BOFA_MAIL_LIMIT = 40
STRIPE_LIMIT = 100
ADS_ACCOUNT_QUERY = 'SELECT customer.id, customer.descriptive_name, customer.currency_code, customer.manager FROM customer LIMIT 1'
ADS_CAMPAIGN_QUERY = ('SELECT campaign.id, campaign.name, campaign.status, metrics.impressions, metrics.clicks, metrics.cost_micros '
                      'FROM campaign WHERE segments.date DURING LAST_30_DAYS ORDER BY campaign.id LIMIT 101')

_ERRORS = {
    'not_configured': '此来源尚未完成服务器配置',
    'unknown_source': '不支持的来源',
    'invalid_credentials': '来源凭据无效，请重新连接',
    'authorization_expired': '来源授权已失效，请重新连接',
    'access_denied': '来源拒绝访问，请核对授权权限',
    'rate_limited': '来源请求过于频繁，请稍后重试',
    'upstream_unavailable': '来源暂时不可用，请稍后重试',
    'upstream_timeout': '来源响应超时，请稍后重试',
    'invalid_response': '来源返回的数据无法安全读取',
    'request_not_allowed': '该来源操作不被允许',
    'sync_limit': '同步已达到安全请求上限',
    'ads_project_not_approved': 'Google Cloud 项目尚未获准读取正式广告账户，请在 Google Ads API 概览申请 Explorer 或更高访问级别后重新连接',
    'ads_account_changed': '广告账户配置与已授权账户不一致，请重新连接',
    'ads_manager_account': '请选择具体广告账户，经理账户不能作为广告观察的目标账户',
}


class ProviderError(RuntimeError):
    def __init__(self, code: str):
        self.code = code if code in _ERRORS else 'upstream_unavailable'
        self.public_message = _ERRORS[self.code]
        self.retryable = self.code in {'rate_limited', 'upstream_unavailable', 'upstream_timeout'}
        super().__init__(self.public_message)


@dataclass(frozen=True)
class SourceDefinition:
    id: str
    name: str
    capabilities: tuple[str, ...]
    scope: str | None = None


# Add a definition and a fetch handler together when introducing another source.
REGISTRY = MappingProxyType({source.id: source for source in (
    SourceDefinition('gmail', 'Gmail', ('read_email',), GMAIL_SCOPE),
    SourceDefinition('google_ads', 'Google Ads', ('read_campaign_metrics',), ADS_SCOPE),
    SourceDefinition('bofa', 'Bank of America', ('read_bank_email_alerts',), GMAIL_SCOPE),
    SourceDefinition('stripe', 'Stripe', ('read_payments', 'read_refunds', 'read_disputes', 'read_payouts', 'read_balance')),
    SourceDefinition('manual', '手动事项', ('manual_entry',)),
)})


def _source(source_id: str) -> SourceDefinition:
    try: return REGISTRY[source_id]
    except (KeyError, TypeError): raise ProviderError('unknown_source') from None


def _google_settings() -> tuple[str, str]:
    return (os.getenv('GOOGLE_WORKSPACE_CLIENT_ID') or os.getenv('GOOGLE_CLIENT_ID') or '',
            os.getenv('GOOGLE_WORKSPACE_CLIENT_SECRET') or os.getenv('GOOGLE_CLIENT_SECRET') or '')


def _account_email(value: object) -> str:
    # This identifies the mailbox returned by Google's profile endpoint, not a
    # sender address. Reject malformed values instead of truncating an identity.
    if not isinstance(value, str) or len(value) > 254 or value.count('@') != 1:
        raise ProviderError('invalid_response')
    local, domain = value.rsplit('@', 1)
    labels = domain.split('.')
    if (not local or len(local) > 64 or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+", local)
            or len(labels) < 2 or any(not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label) for label in labels)):
        raise ProviderError('invalid_response')
    return value


def _expected_gmail_account() -> str | None:
    value = os.getenv('PRIVATE_WORKSPACE_GMAIL_EXPECTED_ACCOUNT', '').strip()
    return _account_email(value) if value else None


def _check_gmail_account(account: str | None) -> None:
    expected = _expected_gmail_account()
    if expected and not account:
        # Old snapshots may have lost their profile identity. A configured
        # mailbox restriction must require reauthorization rather than guess.
        raise ProviderError('authorization_expired')
    if expected and account.casefold() != expected.casefold():
        raise ProviderError('access_denied')


def _public_origin() -> str:
    value = os.getenv('PRIVATE_WORKSPACE_PUBLIC_URL', '').rstrip('/')
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.path or parsed.query or parsed.fragment):
        raise ProviderError('not_configured')
    return value


def _customer_id(value: str) -> str:
    value = value.replace('-', '')
    if not re.fullmatch(r'\d{10}', value): raise ProviderError('not_configured')
    return value


def _stripe_key(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'rk_(?:live|test)_[A-Za-z0-9]{8,512}', value):
        raise ProviderError('invalid_credentials')
    return value


def _missing(source: SourceDefinition) -> list[str]:
    result = []
    if source.scope:
        client_id, secret = _google_settings()
        if not client_id: result.append('GOOGLE_WORKSPACE_CLIENT_ID')
        if not secret: result.append('GOOGLE_WORKSPACE_CLIENT_SECRET')
        try: _public_origin()
        except (ProviderError, ValueError): result.append('PRIVATE_WORKSPACE_PUBLIC_URL')
    if source.id == 'gmail':
        try: _expected_gmail_account()
        except ProviderError: result.append('PRIVATE_WORKSPACE_GMAIL_EXPECTED_ACCOUNT')
    if source.id == 'google_ads':
        try: _customer_id(os.getenv('PRIVATE_WORKSPACE_GOOGLE_ADS_CUSTOMER_ID') or os.getenv('GOOGLE_ADS_CUSTOMER_ID') or '')
        except ProviderError: result.append('PRIVATE_WORKSPACE_GOOGLE_ADS_CUSTOMER_ID')
        if os.getenv('GOOGLE_ADS_LOGIN_CUSTOMER_ID'):
            try: _customer_id(os.environ['GOOGLE_ADS_LOGIN_CUSTOMER_ID'])
            except ProviderError: result.append('GOOGLE_ADS_LOGIN_CUSTOMER_ID')
    if source.id == 'stripe':
        try: _stripe_key(os.getenv('PRIVATE_WORKSPACE_STRIPE_KEY'))
        except ProviderError: result.append('PRIVATE_WORKSPACE_STRIPE_KEY')
    return result


def describe_sources() -> list[dict]:
    result = []
    for source in REGISTRY.values():
        missing = _missing(source)
        result.append({'id': source.id, 'name': source.name, 'capabilities': list(source.capabilities),
                       'missing_configuration': missing, 'status': 'not_configured' if missing else 'disconnected'})
    return result


def _configured(source: SourceDefinition) -> None:
    if _missing(source): raise ProviderError('not_configured')


def _opaque(value: object, maximum: int = 8192) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum or re.search(r'[\x00-\x20\x7f]', value):
        raise ProviderError('invalid_credentials')
    return value


def _id(value: object, prefix: str | None = None) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value) or prefix and not value.startswith(prefix):
        raise ProviderError('invalid_response')
    return value


def _text(value: object, limit: int = 300) -> str:
    return re.sub(r'[\x00-\x1f\x7f]+', ' ', str(value or '')).strip()[:limit]


def _integer(value: object, *, negative: bool = False) -> int:
    if isinstance(value, bool) or not (isinstance(value, int) or isinstance(value, str) and re.fullmatch(r'-?\d{1,18}', value)):
        raise ProviderError('invalid_response')
    integer = int(value)
    if abs(integer) > 10**18 or not negative and integer < 0: raise ProviderError('invalid_response')
    return integer


def _currency(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z]{3}', value): raise ProviderError('invalid_response')
    return value.lower()


def _date(value: object, *, milliseconds: bool = False) -> str | None:
    if value is None: return None
    seconds = _integer(value) / (1000 if milliseconds else 1)
    try: return datetime.fromtimestamp(seconds, timezone.utc).isoformat()
    except (ValueError, OverflowError, OSError): raise ProviderError('invalid_response') from None


class _Client:
    def __init__(self, transport: httpx.AsyncBaseTransport | None):
        self.client = httpx.AsyncClient(transport=transport, trust_env=False, follow_redirects=False,
                                       timeout=httpx.Timeout(10, connect=5))
        self.requests = 0
        self.deadline = time.monotonic() + MAX_SYNC_SECONDS

    async def __aenter__(self): return self
    async def __aexit__(self, *unused): await self.client.aclose()

    async def request(self, method: str, url: str, **arguments) -> dict:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0: raise ProviderError('upstream_timeout')
        try: return await asyncio.wait_for(self._request(method, url, **arguments), timeout=remaining)
        except asyncio.TimeoutError: raise ProviderError('upstream_timeout') from None

    async def _request(self, method: str, url: str, **arguments) -> dict:
        parsed = urlsplit(url)
        allowed = (method == 'POST' and parsed.hostname == 'oauth2.googleapis.com' and parsed.path == '/token' or
                   method == 'GET' and parsed.hostname == 'gmail.googleapis.com' and
                   re.fullmatch(r'/gmail/v1/users/me/(?:profile|messages(?:/[A-Za-z0-9_-]{1,128})?)', parsed.path) or
                   method == 'POST' and parsed.hostname == 'googleads.googleapis.com' and
                   re.fullmatch(r'/v25/customers/\d{10}/googleAds:search', parsed.path) or
                   method == 'GET' and parsed.hostname == 'api.stripe.com' and parsed.path in
                   {'/v1/charges', '/v1/refunds', '/v1/disputes', '/v1/payouts', '/v1/balance'})
        if (not allowed or parsed.scheme != 'https' or parsed.port not in (None, 443) or parsed.username or parsed.password
                or parsed.query or parsed.fragment): raise ProviderError('request_not_allowed')
        if parsed.hostname == 'googleads.googleapis.com' and arguments.get('json', {}).get('query') not in (ADS_ACCOUNT_QUERY, ADS_CAMPAIGN_QUERY):
            raise ProviderError('request_not_allowed')
        if any(str(key).lower() in {'token', 'access_token', 'api_key', 'key', 'authorization'} for key in arguments.get('params', {})):
            raise ProviderError('request_not_allowed')
        self.requests += 1
        if self.requests > MAX_REQUESTS: raise ProviderError('sync_limit')
        try:
            async with self.client.stream(method, url, **arguments) as response:
                if parsed.hostname == 'googleads.googleapis.com' and response.status_code in (400, 403):
                    # Only recognize a fixed machine error; never publish Google's
                    # message, request ID, account identifiers or response body.
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_RESPONSE_BYTES: raise ProviderError('invalid_response')
                    try: error_data = json.loads(body)
                    except (ValueError, UnicodeError): error_data = {}
                    if isinstance(error_data, dict):
                        details = (error_data.get('error') or {}).get('details', []) if isinstance(error_data.get('error'), dict) else []
                        if isinstance(details, list):
                            for detail in details:
                                errors = detail.get('errors', []) if isinstance(detail, dict) else []
                                if not isinstance(errors, list): continue
                                for error in errors:
                                    code = error.get('errorCode', {}) if isinstance(error, dict) else {}
                                    if isinstance(code, dict) and code.get('authorizationError') == 'CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION':
                                        raise ProviderError('ads_project_not_approved')
                if response.status_code == 401: raise ProviderError('authorization_expired')
                if response.status_code == 403: raise ProviderError('access_denied')
                if response.status_code == 429: raise ProviderError('rate_limited')
                if response.status_code >= 500: raise ProviderError('upstream_unavailable')
                if response.status_code == 400 and parsed.hostname == 'oauth2.googleapis.com': raise ProviderError('authorization_expired')
                if response.status_code < 200 or response.status_code >= 300: raise ProviderError('invalid_response')
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES: raise ProviderError('invalid_response')
                try: result = json.loads(body)
                except (ValueError, UnicodeError): raise ProviderError('invalid_response') from None
                if not isinstance(result, dict): raise ProviderError('invalid_response')
                return result
        except httpx.TimeoutException: raise ProviderError('upstream_timeout') from None
        except httpx.HTTPError: raise ProviderError('upstream_unavailable') from None


def _token_response(data: dict, scope: str, previous: dict | None = None) -> dict:
    previous = previous or {}
    granted = str(data.get('scope') or previous.get('scope') or scope).split()
    token_type = data.get('token_type', 'Bearer')
    if not isinstance(token_type, str) or scope not in granted or token_type.lower() != 'bearer': raise ProviderError('access_denied')
    expires_in = _integer(data.get('expires_in', 3600))
    if expires_in <= 0: raise ProviderError('invalid_response')
    result = {'access_token': _opaque(data.get('access_token')), 'scope': ' '.join(granted), 'token_type': 'Bearer',
              'expires_at': int(time.time()) + min(expires_in, 86400)}
    refresh = data.get('refresh_token') or previous.get('refresh_token')
    if refresh: result['refresh_token'] = _opaque(refresh)
    return result


async def begin_connect(source_id: str, state: str, *, transport: httpx.AsyncBaseTransport | None = None) -> dict:
    source = _source(source_id); _configured(source)
    if source.id == 'manual': return {'credentials': {}, 'metadata': {'connection_mode': 'manual'}}
    if source.id == 'stripe':
        key = _stripe_key(os.getenv('PRIVATE_WORKSPACE_STRIPE_KEY'))
        async with _Client(transport) as client:
            balance = await client.request('GET', 'https://api.stripe.com/v1/balance', headers={'Authorization': 'Bearer ' + key})
            if balance.get('object') != 'balance' or not isinstance(balance.get('available'), list) or not isinstance(balance.get('pending'), list):
                raise ProviderError('invalid_response')
        return {'credentials': {'api_key': key}, 'metadata': {'connection_mode': 'restricted_api_key', 'read_only_adapter': True}}
    if not isinstance(state, str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,256}', state): raise ProviderError('invalid_credentials')
    client_id, _ = _google_settings()
    parameters = {'client_id': client_id, 'redirect_uri': _public_origin() + '/api/v1/private-workspace/oauth/' + source.id + '/callback',
                  'response_type': 'code', 'scope': source.scope, 'state': state, 'access_type': 'offline', 'prompt': 'consent'}
    return {'authorization_url': 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode(parameters),
            'metadata': {'connection_mode': 'oauth', 'read_only_adapter': True, 'scope': source.scope}}


async def complete_connect(source_id: str, code: str, *, transport: httpx.AsyncBaseTransport | None = None) -> dict:
    source = _source(source_id); _configured(source)
    if not source.scope: raise ProviderError('request_not_allowed')
    client_id, secret = _google_settings()
    async with _Client(transport) as client:
        data = await client.request('POST', 'https://oauth2.googleapis.com/token', data={
            'client_id': client_id, 'client_secret': secret, 'code': _opaque(code, 4096), 'grant_type': 'authorization_code',
            'redirect_uri': _public_origin() + '/api/v1/private-workspace/oauth/' + source.id + '/callback'})
        credentials = _token_response(data, source.scope)
        metadata = {'connection_mode': 'oauth', 'read_only_adapter': True, 'scope': credentials['scope']}
        if source.id in {'gmail', 'bofa'}:
            profile = await client.request('GET', 'https://gmail.googleapis.com/gmail/v1/users/me/profile',
                                           headers={'Authorization': 'Bearer ' + credentials['access_token']})
            account = _account_email(profile.get('emailAddress'))
            if source.id == 'gmail': _check_gmail_account(account)
            metadata['account_label'] = account
        elif source.id == 'google_ads':
            google = _Google(client, source, credentials)
            customer, account_value = await _ads_account(google)
            metadata['ads_customer_id'] = customer
            # This is a verified advertiser name, never a Google user identity.
            metadata['account_label'] = _text(account_value.get('descriptiveName'), 200) or customer
            credentials = google.credentials
    return {'credentials': credentials, 'metadata': metadata}


class _Google:
    def __init__(self, client: _Client, source: SourceDefinition, credentials: dict):
        self.client = client; self.source = source; self.credentials = dict(credentials); self.refreshed = False
        scope = credentials.get('scope')
        if not isinstance(scope, str) or source.scope not in scope.split(): raise ProviderError('access_denied')

    async def refresh(self):
        if self.refreshed or not self.credentials.get('refresh_token'): raise ProviderError('authorization_expired')
        self.refreshed = True
        client_id, secret = _google_settings()
        data = await self.client.request('POST', 'https://oauth2.googleapis.com/token', data={
            'client_id': client_id, 'client_secret': secret, 'refresh_token': _opaque(self.credentials['refresh_token']), 'grant_type': 'refresh_token'})
        self.credentials = _token_response(data, self.source.scope, self.credentials)

    async def request(self, method: str, url: str, **arguments):
        expires = self.credentials.get('expires_at')
        if expires is not None and _integer(expires) <= int(time.time()) + 30 and not self.refreshed: await self.refresh()
        headers = dict(arguments.pop('headers', {}))
        try:
            return await self.client.request(method, url, headers={**headers, 'Authorization': 'Bearer ' + _opaque(self.credentials.get('access_token'))}, **arguments)
        except ProviderError as error:
            if error.code != 'authorization_expired' or self.refreshed: raise
            await self.refresh()
            return await self.client.request(method, url, headers={**headers, 'Authorization': 'Bearer ' + self.credentials['access_token']}, **arguments)


def _list(value: object) -> list:
    if not isinstance(value, list): raise ProviderError('invalid_response')
    return value


async def _gmail(google: _Google, source: SourceDefinition, metadata: dict) -> dict:
    account = _account_email(metadata['account_label']) if metadata.get('account_label') else None
    if source.id == 'gmail': _check_gmail_account(account)
    query = 'newer_than:60d {in:inbox is:important is:starred}' if source.id == 'gmail' else 'newer_than:60d {from:bankofamerica.com from:bofa.com}'
    limit = GMAIL_LIMIT if source.id == 'gmail' else BOFA_MAIL_LIMIT
    items = []; seen = set(); page = None; partial = False
    for _ in range(limit // 20):
        parameters = {'maxResults': 20, 'q': query, 'includeSpamTrash': 'false'}
        if page: parameters['pageToken'] = page
        listing = await google.request('GET', 'https://gmail.googleapis.com/gmail/v1/users/me/messages', params=parameters)
        records = _list(listing.get('messages', []))
        if len(records) > 20: raise ProviderError('invalid_response')
        for record in records:
            message_id = _id(record.get('id'))
            if message_id in seen: continue
            seen.add(message_id)
            message = await google.request('GET', 'https://gmail.googleapis.com/gmail/v1/users/me/messages/' + message_id,
                                           params={'format': 'metadata', 'metadataHeaders': ['Subject', 'From']})
            if message.get('id') != message_id: raise ProviderError('invalid_response')
            payload = message.get('payload') or {}
            headers = {str(header.get('name', '')).lower(): str(header.get('value', '')) for header in _list(payload.get('headers', []))}
            if source.id == 'bofa':
                addresses = getaddresses([headers.get('from', '')])
                if len(addresses) != 1: continue
                domain = addresses[0][1].rsplit('@', 1)[-1].lower()
                if not any(domain == allowed or domain.endswith('.' + allowed) for allowed in ('bankofamerica.com', 'bofa.com')): continue
            thread_id = _id(message.get('threadId') or message_id)
            labels = _list(message.get('labelIds', []))
            evidence = {'provider_message_id': message_id, 'provider_thread_id': thread_id}
            if source.id == 'gmail':
                evidence['labels'] = [str(label)[:80] for label in labels[:50] if isinstance(label, str)]
            if headers.get('from'):
                evidence.update({'from': _text(headers['from']), 'sender_verification': 'unverified'})
            if source.id == 'bofa': evidence.update(type='email_alert', verification='unverified', accounting_effect='none')
            items.append({'external_id': message_id, 'kind': 'email_alert' if source.id == 'bofa' else 'email',
                          'title': _text(headers.get('subject') or ('银行邮件提醒' if source.id == 'bofa' else '邮件'), 200),
                          'summary': _text(message.get('snippet')), 'status': 'unverified' if source.id == 'bofa' else
                          ('unread' if 'UNREAD' in labels else 'read'),
                          # Gmail's importance label is evidence, not personal urgency.
                          'priority': 'normal',
                          'occurred_at': _date(message.get('internalDate'), milliseconds=True),
                          # Mailbox selection is an explicit browser hint. An
                          # unknown identity must not silently open account 0.
                          'source_url': 'https://mail.google.com/mail/u/?' + urlencode({'authuser': account}) + '#all/' + thread_id if account else None,
                          'evidence': evidence})
        page = listing.get('nextPageToken')
        if not page: break
        page = _opaque(page, 2048)
    partial = bool(page)
    return {'items': items, 'balances': [], 'metadata': {'partial': partial, 'sync_window': 'last_60_days',
             'coverage': 'bounded_recent_records', 'fetched_messages': len(seen), 'record_limit': limit,
             'importance_source': 'owner_metadata_rules' if source.id == 'gmail' else None,
             'bank_data_verification': 'unverified' if source.id == 'bofa' else None}}


def _ads_target() -> str:
    return _customer_id(os.getenv('PRIVATE_WORKSPACE_GOOGLE_ADS_CUSTOMER_ID') or os.getenv('GOOGLE_ADS_CUSTOMER_ID') or '')


def _ads_request() -> tuple[str, dict]:
    customer = _ads_target()
    # Since 2026-09-09 access is attached to the OAuth Cloud project; the
    # obsolete developer-token header is neither required nor sent.
    headers = {}
    if os.getenv('GOOGLE_ADS_LOGIN_CUSTOMER_ID'): headers['login-customer-id'] = _customer_id(os.environ['GOOGLE_ADS_LOGIN_CUSTOMER_ID'])
    return 'https://googleads.googleapis.com/' + ADS_VERSION + '/customers/' + customer + '/googleAds:search', headers


async def _ads_account(google: _Google) -> tuple[str, dict]:
    customer = _ads_target()
    endpoint, headers = _ads_request()
    account = await google.request('POST', endpoint, headers=headers, json={'query': ADS_ACCOUNT_QUERY})
    accounts = _list(account.get('results', []))
    if len(accounts) != 1 or not isinstance(accounts[0], dict): raise ProviderError('invalid_response')
    account_value = accounts[0].get('customer', {})
    if not isinstance(account_value, dict): raise ProviderError('invalid_response')
    if str(account_value.get('id')) != customer: raise ProviderError('access_denied')
    if account_value.get('manager', False) is True: raise ProviderError('ads_manager_account')
    if account_value.get('manager', False) is not False: raise ProviderError('invalid_response')
    _currency(account_value.get('currencyCode'))
    return customer, account_value


async def _ads(google: _Google, source: SourceDefinition, metadata: dict) -> dict:
    customer = _customer_id(os.getenv('PRIVATE_WORKSPACE_GOOGLE_ADS_CUSTOMER_ID') or os.getenv('GOOGLE_ADS_CUSTOMER_ID') or '')
    # Existing connections with no confirmed target also require fresh consent.
    if metadata.get('ads_customer_id') != customer: raise ProviderError('ads_account_changed')
    endpoint, headers = _ads_request()
    _, account_value = await _ads_account(google)
    currency = _currency(account_value.get('currencyCode'))
    report = await google.request('POST', endpoint, headers=headers, json={'query': ADS_CAMPAIGN_QUERY})
    rows = _list(report.get('results', []))
    if len(rows) > 101: raise ProviderError('invalid_response')
    items = []
    for row in rows[:100]:
        campaign = row.get('campaign') or {}; metrics = row.get('metrics') or {}
        campaign_id = str(_integer(campaign.get('id')))
        impressions = _integer(metrics.get('impressions', 0)); clicks = _integer(metrics.get('clicks', 0))
        cost = _integer(metrics.get('costMicros', 0))
        items.append({'external_id': customer + ':' + campaign_id + ':last_30_days', 'kind': 'campaign',
                      'title': _text(campaign.get('name') or campaign_id, 200), 'status': _text(campaign.get('status'), 80),
                      'summary': f'近30天（不含今天）· 曝光 {impressions} · 点击 {clicks} · 费用 {Decimal(cost) / Decimal(1000000):f} {currency.upper()}',
                      'priority': 'normal', 'currency': currency, 'source_url': 'https://ads.google.com/aw/overview',
                      'evidence': {'customer_id': customer, 'campaign_id': campaign_id, 'cost_micros': cost,
                                   'impressions': impressions, 'clicks': clicks, 'period': 'LAST_30_DAYS', 'accounting_effect': 'none'}})
    return {'items': items, 'balances': [], 'metadata': {'partial': len(rows) > 100 or bool(report.get('nextPageToken')), 'sync_window': 'last_30_days',
             'coverage': 'bounded_campaign_records', 'record_limit': 100, 'aggregated_totals': False,
             'account_label': _text(account_value.get('descriptiveName'), 200) or customer,
             'ads_customer_id': customer, 'api_version': ADS_VERSION}}


async def _stripe(client: _Client, source: SourceDefinition, credentials: dict) -> dict:
    key = _stripe_key(credentials.get('api_key')); headers = {'Authorization': 'Bearer ' + key}
    balance = await client.request('GET', 'https://api.stripe.com/v1/balance', headers=headers)
    if balance.get('object') != 'balance': raise ProviderError('invalid_response')
    balances = {}
    for field, output in (('available', 'available_minor'), ('pending', 'pending_minor')):
        seen = set()
        for row in _list(balance.get(field)):
            currency = _currency(row.get('currency'))
            if currency in seen: raise ProviderError('invalid_response')
            seen.add(currency)
            balances.setdefault(currency, {'currency': currency, 'available_minor': 0, 'pending_minor': 0})[output] = _integer(row.get('amount'), negative=True)
    items = []; partial = False; resource_coverage = {}
    for resource, kind, prefix in (('charges', 'payment', 'ch_'), ('refunds', 'refund', 're_'), ('disputes', 'dispute', 'dp_'), ('payouts', 'payout', 'po_')):
        cursor = None; seen = set()
        for _ in range(2):
            parameters = {'limit': 50}
            if cursor: parameters['starting_after'] = cursor
            response = await client.request('GET', 'https://api.stripe.com/v1/' + resource, headers=headers, params=parameters)
            rows = _list(response.get('data', []))
            if len(rows) > 50 or response.get('has_more', False) not in (True, False): raise ProviderError('invalid_response')
            for row in rows:
                identity = _id(row.get('id'), prefix)
                if identity in seen: raise ProviderError('invalid_response')
                seen.add(identity)
                status = _text(row.get('status'), 80)
                evidence = {'provider_id': identity, 'provider_status': status, 'accounting_effect': 'none'}
                if kind == 'payout': evidence['funds_movement'] = 'stripe_balance_to_bank'
                due = (row.get('evidence_details') or {}).get('due_by') if kind == 'dispute' else row.get('arrival_date') if kind == 'payout' else None
                dashboard = 'https://dashboard.stripe.com/' + ('test/' if key.startswith('rk_test_') else '')
                detail = ('disputes/' if kind == 'dispute' else 'payouts/' if kind == 'payout' else 'payments/')
                link_id = identity
                if kind == 'refund': link_id = _id(row.get('charge'), 'ch_') if isinstance(row.get('charge'), str) else ''
                items.append({'external_id': resource + ':' + identity, 'kind': kind, 'title': _text(row.get('description') or
                              {'payment': 'Stripe 收款', 'refund': 'Stripe 退款', 'dispute': 'Stripe 争议', 'payout': 'Stripe 提现'}[kind], 200),
                              'summary': _text(row.get('reason') or identity), 'status': status, 'priority': 'high' if kind == 'dispute' and status == 'needs_response' else 'normal',
                              'amount_minor': _integer(row.get('amount')), 'currency': _currency(row.get('currency')),
                              'occurred_at': _date(row.get('created')), 'due_at': _date(due), 'source_url': dashboard + detail + link_id, 'evidence': evidence})
            has_more = response.get('has_more', False)
            if not has_more: break
            if not rows: raise ProviderError('invalid_response')
            cursor = _id(rows[-1].get('id'), prefix)
        partial = partial or bool(has_more)
        resource_coverage[resource] = {'fetched': len(seen), 'partial': bool(has_more)}
    return {'items': items, 'balances': list(balances.values()), 'metadata': {'partial': partial, 'read_only_adapter': True,
             'coverage': 'bounded_recent_records', 'record_limit_per_resource': STRIPE_LIMIT, 'resources': resource_coverage,
             'aggregated_totals': False, 'mode': 'test' if key.startswith('rk_test_') else 'live', 'payouts_are_income': False}}


async def fetch_source(source_id: str, credentials: dict, metadata: dict, *, transport: httpx.AsyncBaseTransport | None = None) -> dict:
    source = _source(source_id); _configured(source)
    if not isinstance(credentials, dict) or not isinstance(metadata, dict): raise ProviderError('invalid_credentials')
    if source.id == 'manual': return {'items': [], 'balances': [], 'metadata': {'connection_mode': 'manual'}}
    async def fetch():
        async with _Client(transport) as client:
            if source.id == 'stripe': return await _stripe(client, source, credentials)
            google = _Google(client, source, credentials)
            result = await (_ads(google, source, metadata) if source.id == 'google_ads' else _gmail(google, source, metadata))
            if google.credentials != credentials: result['credentials'] = google.credentials
            return result
    try: return await asyncio.wait_for(fetch(), timeout=MAX_SYNC_SECONDS)
    except asyncio.TimeoutError: raise ProviderError('upstream_timeout') from None
    except (TypeError, ValueError, KeyError, AttributeError, OverflowError): raise ProviderError('invalid_response') from None
