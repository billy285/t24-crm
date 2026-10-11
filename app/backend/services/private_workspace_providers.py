"""Owner-workspace read adapters. No CRM imports, database writes or payment actions.

Credentials returned by this module are for the encrypted core store only. Google
Ads' fixed search RPC uses POST, but no provider mutation endpoint is permitted.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from email.header import decode_header
from email.utils import getaddresses
from email.message import Message
from html.parser import HTMLParser
import json
import os
import re
import time
from types import MappingProxyType
from urllib.parse import urlencode, urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from services.private_ads_health import build_ads_health, metric_row

GMAIL_SCOPE = 'https://www.googleapis.com/auth/gmail.readonly'
ADS_SCOPE = 'https://www.googleapis.com/auth/adwords'
ADS_VERSION = 'v25'
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_REQUESTS = 90
MAX_SYNC_SECONDS = 45
GMAIL_LIMIT = 80
MAIL_BODY_MAX_CHARS = 50000
MAIL_BODY_MAX_BYTES = 200000
MAIL_MIME_MAX_DEPTH = 8
MAIL_MIME_MAX_PARTS = 64
BOFA_MAIL_LIMIT = 40
STRIPE_LIMIT = 100
ADS_ACCOUNT_QUERY = ('SELECT customer.id, customer.descriptive_name, customer.currency_code, customer.manager, customer.time_zone, '
                     'customer.conversion_tracking_setting.conversion_tracking_status FROM customer LIMIT 1')
ADS_INVENTORY_QUERY = ('SELECT campaign.id, campaign.name, campaign.status, campaign.primary_status, campaign.primary_status_reasons, '
                       'campaign.serving_status, campaign.advertising_channel_type, campaign.start_date_time, campaign.end_date_time, '
                       'campaign.bidding_strategy, campaign.bidding_strategy_type, campaign.bidding_strategy_system_status, '
                       'campaign.target_cpa.target_cpa_micros, campaign.maximize_conversions.target_cpa_micros '
                       'FROM campaign ORDER BY campaign.status, campaign.id LIMIT 101')
ADS_CAMPAIGN_QUERY = ('SELECT campaign.id, metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.conversions '
                      'FROM campaign WHERE segments.date DURING LAST_30_DAYS ORDER BY campaign.id LIMIT 101')
ADS_DAILY_QUERY = ('SELECT campaign.id, segments.date, metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.conversions '
                  'FROM campaign WHERE segments.date DURING LAST_14_DAYS ORDER BY campaign.id, segments.date LIMIT 1401')
ADS_QUERIES = (ADS_ACCOUNT_QUERY, ADS_INVENTORY_QUERY, ADS_CAMPAIGN_QUERY, ADS_DAILY_QUERY)

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
    'stripe_account_changed': 'Stripe 账户或模式与私人空间配置不一致，请核对后重新连接',
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
    SourceDefinition('bofa_bank', 'Bank of America 账户', ('read_bank_balances', 'read_bank_transactions')),
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


def stripe_expected_identity() -> tuple[str, str]:
    """The dedicated private account is fixed by server configuration, never a browser hint."""
    account = os.getenv('PRIVATE_WORKSPACE_STRIPE_ACCOUNT_ID', '').strip()
    mode = os.getenv('PRIVATE_WORKSPACE_STRIPE_MODE', 'live').strip()
    if not re.fullmatch(r'acct_[A-Za-z0-9]{8,128}', account) or mode not in {'live', 'test'}:
        raise ProviderError('not_configured')
    return account, mode


def _stripe_mode(key: str) -> str:
    mode = 'test' if key.startswith('rk_test_') else 'live'
    if mode != stripe_expected_identity()[1]: raise ProviderError('stripe_account_changed')
    return mode


def _missing(source: SourceDefinition) -> list[str]:
    result = []
    if source.id == 'bofa_bank':
        from services.private_bank_provider import missing_configuration
        return missing_configuration()
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
        if not re.fullmatch(r'acct_[A-Za-z0-9]{8,128}', os.getenv('PRIVATE_WORKSPACE_STRIPE_ACCOUNT_ID', '').strip()):
            result.append('PRIVATE_WORKSPACE_STRIPE_ACCOUNT_ID')
        if os.getenv('PRIVATE_WORKSPACE_STRIPE_MODE', 'live').strip() not in {'live', 'test'}:
            result.append('PRIVATE_WORKSPACE_STRIPE_MODE')
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
                   {'/v1/account', '/v1/charges', '/v1/refunds', '/v1/disputes', '/v1/payouts', '/v1/balance'})
        if (not allowed or parsed.scheme != 'https' or parsed.port not in (None, 443) or parsed.username or parsed.password
                or parsed.query or parsed.fragment): raise ProviderError('request_not_allowed')
        if parsed.hostname == 'googleads.googleapis.com':
            payload = arguments.get('json', {})
            if (not isinstance(payload, dict) or payload.get('query') not in ADS_QUERIES
                    or set(payload) - {'query', 'pageToken'}): raise ProviderError('request_not_allowed')
            if 'pageToken' in payload: _opaque(payload['pageToken'], 2048)
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
        key = _stripe_key(os.getenv('PRIVATE_WORKSPACE_STRIPE_KEY')); mode = _stripe_mode(key)
        async with _Client(transport) as client:
            headers = {'Authorization': 'Bearer ' + key}
            identity, _ = await _stripe_identity(client, headers, mode)
            # Verify every required read before claiming this source is connected.
            # No write, account mutation, refund or payout endpoint is ever called.
            for resource, kind, prefix in STRIPE_RESOURCES:
                result = await client.request('GET', 'https://api.stripe.com/v1/' + resource, headers=headers, params={'limit': 1})
                rows, _ = _stripe_list(result, mode, 1, kind=kind)
                for row in rows: _stripe_item(row, kind, prefix, identity, mode, 'connect-probe', datetime.now(timezone.utc).isoformat())
        return {'credentials': {'api_key': key, 'stripe_account_id': identity['stripe_account_id'], 'mode': mode},
                'metadata': {**identity, 'mode': mode, 'connection_mode': 'restricted_api_key', 'read_only_adapter': True}}
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


def _mail_headers(part: dict) -> dict[str, str]:
    values = part.get('headers', [])
    if not isinstance(values, list) or len(values) > 100: raise ProviderError('invalid_response')
    headers = {}
    for value in values:
        if (not isinstance(value, dict) or not isinstance(value.get('name'), str)
                or not isinstance(value.get('value'), str) or len(value['name']) > 128 or len(value['value']) > 10000):
            raise ProviderError('invalid_response')
        headers[value['name'].lower()] = value['value']
    return headers


def _mail_plain(value: str) -> str:
    # Keep paragraph structure for reading and translation. Never interpret the
    # result as markup; even a text/plain message can contain literal HTML.
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ud800-\udfff]', '', value.replace('\r\n', '\n').replace('\r', '\n')).strip()


def _mail_subject(value: str) -> str:
    decoded = []
    try:
        for part, charset in decode_header(value):
            if isinstance(part, bytes):
                try: part = part.decode((charset or 'utf-8')[:64], errors='replace')
                except (LookupError, TypeError): part = part.decode('utf-8', errors='replace')
            decoded.append(part)
    except (ValueError, binascii.Error): raise ProviderError('invalid_response') from None
    return _text(_mail_plain(''.join(decoded)) or '邮件', 1000)


class _MailHTMLText(HTMLParser):
    """Visible text only: no attributes, links, embedded media or network I/O."""
    _HIDDEN = {'script', 'style', 'head', 'iframe', 'object', 'embed', 'svg', 'math', 'template', 'noscript'}
    _VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
    _BLOCK = {'address', 'article', 'blockquote', 'div', 'dl', 'dt', 'dd', 'footer', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
              'header', 'li', 'main', 'ol', 'p', 'pre', 'section', 'table', 'tr', 'ul'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.output = []; self.length = 0; self.stack = []; self.overflow = 0; self.truncated = False

    def _append(self, text: str):
        remaining = MAIL_BODY_MAX_CHARS + 1 - self.length
        if len(text) > remaining: self.truncated = True
        if remaining > 0:
            self.output.append(text[:remaining]); self.length += len(text[:remaining])

    def handle_starttag(self, tag, attrs):
        hidden = bool(self.overflow or self.stack and self.stack[-1][1])
        attributes = dict(attrs)
        style = (attributes.get('style') or '').replace(' ', '').lower()
        hidden = hidden or tag in self._HIDDEN or 'hidden' in attributes or attributes.get('aria-hidden') == 'true' or 'display:none' in style or 'visibility:hidden' in style
        if not hidden and (tag in self._BLOCK or tag in {'br', 'hr'}): self._append('\n')
        if tag not in self._VOID:
            if len(self.stack) >= 128 or self.overflow:
                self.overflow += 1; self.truncated = True
            else: self.stack.append((tag, hidden))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self._VOID: self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.overflow:
            if tag not in self._VOID: self.overflow -= 1
            return
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                hidden = self.stack[index][1]; del self.stack[index:]
                if not hidden and tag in self._BLOCK: self._append('\n')
                break

    def handle_data(self, data):
        if not self.overflow and not (self.stack and self.stack[-1][1]): self._append(data)


def _mail_body(payload: dict) -> tuple[str, bool]:
    candidates = {'text/plain': [], 'text/html': []}; visited = 0; truncated = False; remaining_bytes = MAIL_BODY_MAX_BYTES

    def visit(part: object, depth: int):
        nonlocal visited, truncated
        if depth > MAIL_MIME_MAX_DEPTH or visited >= MAIL_MIME_MAX_PARTS:
            truncated = True; return
        visited += 1
        if not isinstance(part, dict): raise ProviderError('invalid_response')
        headers = _mail_headers(part)
        descriptor = Message(); descriptor['Content-Type'] = headers.get('content-type', 'text/plain')
        if headers.get('content-disposition'): descriptor['Content-Disposition'] = headers['content-disposition']
        # Do not parse attached messages, text files or an attachment subtree.
        if part.get('filename') or descriptor.get_content_disposition() == 'attachment' or descriptor.get_filename(): return
        if not isinstance(part.get('mimeType', ''), str): raise ProviderError('invalid_response')
        mime = part.get('mimeType', '').lower()
        if mime in candidates: candidates[mime].append((part, descriptor.get_content_charset() or 'utf-8'))
        elif mime.startswith('multipart/'):
            parts = part.get('parts', [])
            if not isinstance(parts, list): raise ProviderError('invalid_response')
            for child in parts[:MAIL_MIME_MAX_PARTS]: visit(child, depth + 1)
            if len(parts) > MAIL_MIME_MAX_PARTS: truncated = True

    def decode(part: dict, charset: str) -> str:
        nonlocal truncated, remaining_bytes
        body = part.get('body', {})
        if not isinstance(body, dict): raise ProviderError('invalid_response')
        encoded = body.get('data')
        if encoded is None:
            # Gmail may store a body outside this response. That attachment
            # endpoint remains forbidden; report incomplete content instead.
            if body.get('attachmentId') or body.get('size'): truncated = True
            return ''
        if (not isinstance(encoded, str) or not re.fullmatch(r'[A-Za-z0-9_-]*={0,2}', encoded)
                or len(encoded) % 4 == 1): raise ProviderError('invalid_response')
        if not remaining_bytes:
            if encoded: truncated = True
            return ''
        max_encoded = ((remaining_bytes + 2) // 3) * 4
        if len(encoded) > max_encoded:
            encoded = encoded[:max_encoded]; truncated = True
        try: decoded = base64.b64decode(encoded + '=' * (-len(encoded) % 4), altchars=b'-_', validate=True)
        except (ValueError, binascii.Error): raise ProviderError('invalid_response') from None
        if len(decoded) > remaining_bytes: truncated = True
        decoded = decoded[:remaining_bytes]; remaining_bytes -= len(decoded)
        if 'size' in body and _integer(body['size']) > len(decoded): truncated = True
        try: return decoded.decode(charset[:64], errors='replace')
        except (LookupError, TypeError): return decoded.decode('utf-8', errors='replace')

    visit(payload, 0)
    # A multipart alternative contains duplicate content. Prefer actual plain
    # text; use the HTML fallback only when no readable plain body is present.
    plain = '\n\n'.join(_mail_plain(decode(part, charset)) for part, charset in candidates['text/plain']).strip()
    if plain:
        body = plain
    else:
        texts = []
        for part, charset in candidates['text/html']:
            parser = _MailHTMLText()
            try: parser.feed(decode(part, charset)); parser.close()
            except (AssertionError, ValueError): raise ProviderError('invalid_response') from None
            texts.append(_mail_plain(''.join(parser.output))); truncated = truncated or parser.truncated
        body = '\n\n'.join(texts).strip()
    if len(body) > MAIL_BODY_MAX_CHARS: truncated = True
    return body[:MAIL_BODY_MAX_CHARS], truncated


async def fetch_mail_content(credentials: dict, metadata: dict, message_id: str, *, transport: httpx.AsyncBaseTransport | None = None) -> dict:
    """Explicit Gmail body read. Refreshed credentials are for the private core only."""
    source = _source('gmail'); _configured(source)
    if not isinstance(credentials, dict) or not isinstance(metadata, dict): raise ProviderError('invalid_credentials')
    message_id = _id(message_id)
    if not metadata.get('account_label'): raise ProviderError('authorization_expired')
    account = _account_email(metadata['account_label']); _check_gmail_account(account)

    async def fetch():
        async with _Client(transport) as client:
            google = _Google(client, source, credentials)
            profile = await google.request('GET', 'https://gmail.googleapis.com/gmail/v1/users/me/profile')
            actual = _account_email(profile.get('emailAddress')); _check_gmail_account(actual)
            if actual.casefold() != account.casefold(): raise ProviderError('access_denied')
            message = await google.request('GET', 'https://gmail.googleapis.com/gmail/v1/users/me/messages/' + message_id, params={'format': 'full'})
            if message.get('id') != message_id or not isinstance(message.get('payload'), dict): raise ProviderError('invalid_response')
            headers = _mail_headers(message['payload']); body, truncated = _mail_body(message['payload'])
            result = {'title': _mail_subject(headers.get('subject') or '邮件'), 'summary': _text(message.get('snippet'), 1000),
                      'body': body, 'has_body': bool(body), 'truncated': truncated}
            if google.credentials != credentials: result['credentials'] = google.credentials
            return result
    try: return await asyncio.wait_for(fetch(), timeout=MAX_SYNC_SECONDS)
    except asyncio.TimeoutError: raise ProviderError('upstream_timeout') from None
    except (TypeError, ValueError, KeyError, AttributeError, OverflowError): raise ProviderError('invalid_response') from None


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
    account_timezone = account_value.get('timeZone')
    if not isinstance(account_timezone, str) or len(account_timezone) > 100: raise ProviderError('invalid_response')
    try: ZoneInfo(account_timezone)
    except (ZoneInfoNotFoundError, ValueError): raise ProviderError('invalid_response') from None
    return customer, account_value


async def _ads_rows(google: _Google, endpoint: str, headers: dict, query: str, limit: int) -> tuple[list, bool]:
    rows = []; page = None; seen_pages = set()
    for _ in range(2):
        payload = {'query': query}
        if page: payload['pageToken'] = page
        result = await google.request('POST', endpoint, headers=headers, json=payload)
        values = _list(result.get('results', []))
        if any(not isinstance(row, dict) for row in values) or len(rows) + len(values) > limit:
            raise ProviderError('invalid_response')
        rows.extend(values)
        page = result.get('nextPageToken')
        if page is None or page == '': return rows, False
        try: page = _opaque(page, 2048)
        except ProviderError: raise ProviderError('invalid_response') from None
        if page in seen_pages: raise ProviderError('invalid_response')
        seen_pages.add(page)
        if len(rows) >= limit: break
    return rows, True


async def _ads(google: _Google, source: SourceDefinition, metadata: dict) -> dict:
    customer = _customer_id(os.getenv('PRIVATE_WORKSPACE_GOOGLE_ADS_CUSTOMER_ID') or os.getenv('GOOGLE_ADS_CUSTOMER_ID') or '')
    # Existing connections with no confirmed target also require fresh consent.
    if metadata.get('ads_customer_id') != customer: raise ProviderError('ads_account_changed')
    endpoint, headers = _ads_request()
    _, account_value = await _ads_account(google)
    currency = _currency(account_value.get('currencyCode'))
    account_timezone = account_value['timeZone']
    inventory, inventory_paged = await _ads_rows(google, endpoint, headers, ADS_INVENTORY_QUERY, 101)
    monthly, monthly_paged = await _ads_rows(google, endpoint, headers, ADS_CAMPAIGN_QUERY, 101)
    daily, daily_paged = await _ads_rows(google, endpoint, headers, ADS_DAILY_QUERY, 1401)
    inventory_complete = len(inventory) <= 100 and not inventory_paged
    metrics_complete = len(monthly) <= 100 and len(daily) <= 1400 and not monthly_paged and not daily_paged
    snapshot_id = str(uuid4()); observed_at = datetime.now(timezone.utc)
    tracking = (account_value.get('conversionTrackingSetting') or {}).get('conversionTrackingStatus', 'UNKNOWN')
    inventory_ids = set(); monthly_values = {}; daily_values = {}
    for row in inventory:
        campaign_id = str(_integer((row.get('campaign') or {}).get('id')))
        if campaign_id in inventory_ids: raise ProviderError('invalid_response')
        inventory_ids.add(campaign_id)
    for row in monthly:
        campaign_id = str(_integer((row.get('campaign') or {}).get('id')))
        if campaign_id in monthly_values: raise ProviderError('invalid_response')
        monthly_values[campaign_id] = metric_row(row.get('metrics') or {})
    for row in daily:
        campaign_id = str(_integer((row.get('campaign') or {}).get('id')))
        day = (row.get('segments') or {}).get('date')
        if not isinstance(day, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day): raise ProviderError('invalid_response')
        try: parsed_day = date.fromisoformat(day)
        except ValueError: raise ProviderError('invalid_response') from None
        account_today = observed_at.astimezone(ZoneInfo(account_timezone)).date()
        if not account_today - timedelta(days=14) <= parsed_day < account_today: raise ProviderError('invalid_response')
        values = daily_values.setdefault(campaign_id, {})
        if day in values: raise ProviderError('invalid_response')
        values[day] = metric_row(row.get('metrics') or {})
    # A series created/deleted between the fixed inventory and report calls
    # indicates a moving snapshot. Preserve observed platform faults, but do
    # not infer missing metrics are zero or pronounce healthy delivery.
    if inventory_complete and (set(monthly_values) | set(daily_values)) - inventory_ids:
        metrics_complete = False
    items = []
    for row in inventory[:100]:
        campaign = row.get('campaign') or {}
        campaign_id = str(_integer(campaign.get('id')))
        try:
            health = build_ads_health(campaign, monthly_values.get(campaign_id), daily_values.get(campaign_id, {}),
                                      account_timezone=account_timezone, currency=currency.upper(), tracking_status=tracking,
                                      snapshot_id=snapshot_id, observed_at=observed_at,
                                      inventory_complete=inventory_complete, metrics_complete=metrics_complete)
        except ValueError: raise ProviderError('invalid_response') from None
        monthly_metric = health['metrics']['last_30_days']
        summary = health['reason'] if not monthly_metric else (
            f'近30天（不含今天）· 曝光 {monthly_metric["impressions"]} · 点击 {monthly_metric["clicks"]} · '
            f'费用 {Decimal(monthly_metric["cost_micros"]) / Decimal(1000000):f} {currency.upper()}')
        evidence = {'customer_id': customer, 'campaign_id': campaign_id, 'period': 'LAST_30_DAYS', 'accounting_effect': 'none',
                    'ads_snapshot_id': snapshot_id, 'ads_health': health}
        if monthly_metric: evidence.update({key: monthly_metric[key] for key in ('cost_micros', 'impressions', 'clicks', 'conversions')})
        items.append({'external_id': customer + ':' + campaign_id + ':last_30_days', 'kind': 'campaign',
                      'title': _text(campaign.get('name') or campaign_id, 200), 'status': _text(campaign.get('status'), 80),
                      'summary': summary, 'occurred_at': observed_at.isoformat(),
                      'priority': {'problem': 'high', 'attention': 'normal', 'healthy': 'low', 'paused': 'low', 'unknown': 'low'}[health['bucket']],
                      'currency': currency, 'source_url': 'https://ads.google.com/aw/overview', 'evidence': evidence})
    return {'items': items, 'balances': [], 'metadata': {'partial': not inventory_complete or not metrics_complete, 'sync_window': 'last_30_days',
             'coverage': 'bounded_campaign_records', 'record_limit': 100, 'aggregated_totals': False,
             'account_label': _text(account_value.get('descriptiveName'), 200) or customer,
             'ads_customer_id': customer, 'api_version': ADS_VERSION,
             'ads_snapshot': {'id': snapshot_id, 'observed_at': observed_at.isoformat(), 'account_timezone': account_timezone,
                              'inventory_count': len(items), 'inventory_complete': inventory_complete,
                              'metrics_complete': metrics_complete, 'record_limit': 100}}}


STRIPE_RESOURCES = (('charges', 'payment', 'ch_'), ('refunds', 'refund', 're_'), ('disputes', 'dispute', 'dp_'), ('payouts', 'payout', 'po_'))


def _stripe_livemode(row: dict, mode: str) -> None:
    if type(row.get('livemode')) is not bool: raise ProviderError('invalid_response')
    if row['livemode'] != (mode == 'live'): raise ProviderError('stripe_account_changed')


def _stripe_resource_mode(row: dict, mode: str, kind: str | None = None) -> None:
    if kind == 'payment' and row.get('object') != 'charge': raise ProviderError('invalid_response')
    if kind == 'dispute' and row.get('object') != 'dispute': raise ProviderError('invalid_response')
    if kind == 'refund':
        if row.get('object') != 'refund': raise ProviderError('invalid_response')
        # Refund objects omit livemode. Only this verified resource uses the
        # same key/account/balance request context; an explicit field must match.
        # https://docs.stripe.com/api/refunds/object
        if 'livemode' not in row: return
    _stripe_livemode(row, mode)


def _stripe_resource_id(value: object, kind: str, prefix: str) -> str:
    if kind in {'payment', 'dispute'}:
        identity = _id(value)
        # Charges use ch_ or py_; current Disputes use du_, alongside dp_.
        # https://support.stripe.com/questions/getting-started-with-stripe-through-a-third-party-platform
        # https://docs.stripe.com/api/disputes/object
        pattern = r'(?:ch|py)_[A-Za-z0-9]+' if kind == 'payment' else r'(?:dp|du)_[A-Za-z0-9]+'
        if not re.fullmatch(pattern, identity): raise ProviderError('invalid_response')
        return identity
    return _id(value, prefix)


def _stripe_balances(balance: dict, mode: str) -> list[dict]:
    if balance.get('object') != 'balance': raise ProviderError('invalid_response')
    _stripe_livemode(balance, mode)
    balances = {}
    for field, output in (('available', 'available_minor'), ('pending', 'pending_minor')):
        seen = set()
        for row in _list(balance.get(field)):
            currency = _currency(row.get('currency'))
            if currency in seen: raise ProviderError('invalid_response')
            seen.add(currency)
            balances.setdefault(currency, {'currency': currency, 'available_minor': 0, 'pending_minor': 0})[output] = _integer(row.get('amount'), negative=True)
    return list(balances.values())


async def _stripe_identity(client: _Client, headers: dict, mode: str) -> tuple[dict, list[dict]]:
    expected, _ = stripe_expected_identity()
    account = await client.request('GET', 'https://api.stripe.com/v1/account', headers=headers)
    if account.get('object') != 'account': raise ProviderError('invalid_response')
    account_id = _id(account.get('id'), 'acct_')
    if account_id != expected: raise ProviderError('stripe_account_changed')
    # Account objects do not carry livemode. The key and balance establish the
    # environment; resource objects with livemode additionally corroborate it.
    balance = await client.request('GET', 'https://api.stripe.com/v1/balance', headers=headers)
    balances = _stripe_balances(balance, mode)
    profile = account.get('business_profile') or {}; settings = account.get('settings') or {}
    if not isinstance(profile, dict) or not isinstance(settings, dict): raise ProviderError('invalid_response')
    dashboard = settings.get('dashboard') or {}
    if not isinstance(dashboard, dict): raise ProviderError('invalid_response')
    label = _text(profile.get('name') or dashboard.get('display_name') or account_id, 200)
    return {'stripe_account_id': account_id, 'account_label': label}, balances


def _stripe_list(response: dict, mode: str, limit: int, *, kind: str | None = None) -> tuple[list, bool]:
    if response.get('object') != 'list': raise ProviderError('invalid_response')
    rows = _list(response.get('data')); has_more = response.get('has_more')
    if len(rows) > limit or type(has_more) is not bool: raise ProviderError('invalid_response')
    for row in rows:
        if not isinstance(row, dict): raise ProviderError('invalid_response')
        _stripe_resource_mode(row, mode, kind)
    return rows, has_more


def _stripe_item(row: dict, kind: str, prefix: str, identity: dict, mode: str, snapshot_id: str, observed_at: str) -> dict:
    _stripe_resource_mode(row, mode, kind)
    identity_id = _stripe_resource_id(row.get('id'), kind, prefix); status = _text(row.get('status'), 80)
    amount = _integer(row.get('amount')); currency = _currency(row.get('currency'))
    evidence = {'provider_id': identity_id, 'provider_status': status, 'accounting_effect': 'none',
                'stripe_account_id': identity['stripe_account_id'], 'stripe_mode': mode,
                'stripe_snapshot_id': snapshot_id, 'stripe_observed_at': observed_at}
    if kind == 'payment':
        captured, paid, refunded = row.get('captured'), row.get('paid'), row.get('refunded')
        if any(type(value) is not bool for value in (captured, paid, refunded)) or status not in {'succeeded', 'pending', 'failed'}:
            raise ProviderError('invalid_response')
        captured_amount = _integer(row.get('amount_captured')); refunded_amount = _integer(row.get('amount_refunded'))
        uncaptured_refunded = (status == 'succeeded' and paid and not captured and refunded
                               and captured_amount == 0 and 0 < refunded_amount <= amount)
        if refunded_amount > amount or captured_amount > amount or captured_amount and not paid:
            raise ProviderError('invalid_response')
        if refunded_amount > captured_amount and not uncaptured_refunded:
            raise ProviderError('invalid_response')
        # An uncaptured authorization can be marked refunded by Stripe. Keep the
        # original fields, without treating that mark as captured/refunded cash.
        # https://docs.stripe.com/api/payment_intents/cancel
        if uncaptured_refunded: state = 'uncaptured_refunded'
        elif status == 'failed': state = 'failed'
        elif status == 'pending': state = 'pending'
        elif captured_amount and refunded_amount == captured_amount: state = 'refunded'
        elif refunded_amount: state = 'partially_refunded'
        elif captured_amount and (captured_amount < amount or not captured): state = 'partially_captured'
        elif captured: state = 'captured'
        elif paid: state = 'authorized'
        else: raise ProviderError('invalid_response')
        evidence.update(payment_state=state, amount_authorized_minor=amount if paid else 0,
                        amount_captured_minor=captured_amount, amount_refunded_minor=refunded_amount,
                        captured=captured, paid=paid, refunded=refunded)
    if kind == 'payout': evidence['funds_movement'] = 'stripe_balance_to_bank'
    details = row.get('evidence_details') or {}
    if not isinstance(details, dict): raise ProviderError('invalid_response')
    due = details.get('due_by') if kind == 'dispute' else row.get('arrival_date') if kind == 'payout' else None
    dashboard = 'https://dashboard.stripe.com/' + ('test/' if mode == 'test' else '')
    detail = 'disputes/' if kind == 'dispute' else 'payouts/' if kind == 'payout' else 'payments/'
    link_id = identity_id
    if kind == 'refund':
        charge = row.get('charge'); charge = charge.get('id') if isinstance(charge, dict) else charge
        link_id = _stripe_resource_id(charge, 'payment', 'ch_') if isinstance(charge, str) else None
    elif kind == 'payment' and isinstance(row.get('payment_intent'), str):
        link_id = _id(row['payment_intent'], 'pi_')
    resource = {'payment': 'charges', 'refund': 'refunds', 'dispute': 'disputes', 'payout': 'payouts'}[kind]
    return {'external_id': resource + ':' + identity_id, 'kind': kind,
            'title': _text(row.get('description') or {'payment': 'Stripe 支付', 'refund': 'Stripe 退款', 'dispute': 'Stripe 争议', 'payout': 'Stripe 提现'}[kind], 200),
            'summary': _text(row.get('reason') or identity_id), 'status': status,
            'priority': 'high' if kind == 'dispute' and status in {'needs_response', 'warning_needs_response'} else 'normal',
            'amount_minor': amount, 'currency': currency, 'occurred_at': _date(row.get('created')), 'due_at': _date(due),
            'source_url': dashboard + detail + link_id if link_id else None, 'evidence': evidence}


async def _stripe(client: _Client, source: SourceDefinition, credentials: dict, metadata: dict) -> dict:
    key = _stripe_key(credentials.get('api_key')); mode = _stripe_mode(key)
    expected, expected_mode = stripe_expected_identity()
    if (credentials.get('stripe_account_id') != expected or credentials.get('mode') != expected_mode
            or metadata.get('stripe_account_id') != expected or metadata.get('mode') != expected_mode):
        raise ProviderError('stripe_account_changed')
    headers = {'Authorization': 'Bearer ' + key}
    identity, balances = await _stripe_identity(client, headers, mode)
    snapshot_id = str(uuid4()); observed_at = datetime.now(timezone.utc).isoformat()
    items = []; partial = False; resource_coverage = {}
    for resource, kind, prefix in STRIPE_RESOURCES:
        cursor = None; seen = set()
        for _ in range(2):
            parameters = {'limit': 50}
            if cursor: parameters['starting_after'] = cursor
            response = await client.request('GET', 'https://api.stripe.com/v1/' + resource, headers=headers, params=parameters)
            rows, has_more = _stripe_list(response, mode, 50, kind=kind)
            for row in rows:
                row_id = _stripe_resource_id(row.get('id'), kind, prefix)
                if row_id in seen: raise ProviderError('invalid_response')
                seen.add(row_id)
                items.append(_stripe_item(row, kind, prefix, {'stripe_account_id': expected}, mode, snapshot_id, observed_at))
            if not has_more: break
            if not rows: raise ProviderError('invalid_response')
            cursor = _stripe_resource_id(rows[-1].get('id'), kind, prefix)
        partial = partial or bool(has_more)
        resource_coverage[resource] = {'fetched': len(seen), 'partial': bool(has_more)}
    return {'items': items, 'balances': balances, 'metadata': {**identity, 'partial': partial, 'read_only_adapter': True,
             'coverage': 'bounded_recent_records', 'record_limit_per_resource': STRIPE_LIMIT, 'resources': resource_coverage,
             'aggregated_totals': False, 'mode': mode, 'payouts_are_income': False,
             'stripe_snapshot': {'id': snapshot_id, 'observed_at': observed_at, 'account_id': expected, 'mode': mode}}}


async def fetch_source(source_id: str, credentials: dict, metadata: dict, *, transport: httpx.AsyncBaseTransport | None = None) -> dict:
    source = _source(source_id)
    if source.id == 'bofa_bank':
        from services.private_bank_provider import fetch_bofa_bank
        return await fetch_bofa_bank(credentials, transport=transport)
    # A connected Stripe worker receives its key only from encrypted private
    # credentials. The one-time setup environment key is not a runtime dependency.
    if source.id == 'stripe': stripe_expected_identity()
    else: _configured(source)
    if not isinstance(credentials, dict) or not isinstance(metadata, dict): raise ProviderError('invalid_credentials')
    if source.id == 'manual': return {'items': [], 'balances': [], 'metadata': {'connection_mode': 'manual'}}
    async def fetch():
        async with _Client(transport) as client:
            if source.id == 'stripe': return await _stripe(client, source, credentials, metadata)
            google = _Google(client, source, credentials)
            result = await (_ads(google, source, metadata) if source.id == 'google_ads' else _gmail(google, source, metadata))
            if google.credentials != credentials: result['credentials'] = google.credentials
            return result
    try: return await asyncio.wait_for(fetch(), timeout=MAX_SYNC_SECONDS)
    except asyncio.TimeoutError: raise ProviderError('upstream_timeout') from None
    except (TypeError, ValueError, KeyError, AttributeError, OverflowError): raise ProviderError('invalid_response') from None
