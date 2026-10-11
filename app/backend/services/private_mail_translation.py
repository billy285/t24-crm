"""Bounded Google Basic NMT translation for the owner's private mail only.

This module does not fetch mail, access databases, accept dynamic endpoints,
write CRM data, execute mail instructions, or log text/credentials. The private
core authorizes the owner and atomically reserves ``plan.character_count`` before
calling it. Retrying requires a new reservation: requests are never auto-retried.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import html
import json
import os
import re
import unicodedata

import httpx

TRANSLATION_URL = 'https://translation.googleapis.com/language/translate/v2'
TARGET_LANGUAGE = 'zh-CN'
TRANSLATION_VERSION = 'google-basic-nmt-v1'
MAX_BODY_CHARACTERS = 50_000
MAX_SEGMENT_CHARACTERS = 5_000
MAX_REQUEST_BYTES = 90_000  # Basic's documented maximum is 100K bytes.
MAX_RESPONSE_BYTES = 2_000_000
MAX_REQUESTS = 4
MAX_SECONDS = 45
DEFAULT_MONTHLY_CHARACTER_LIMIT = 100_000
_ERRORS = {
    'not_configured': '邮件中文翻译尚未启用或配置无效',
    'invalid_input': '邮件内容格式无效，暂时无法翻译',
    'request_limit': '这封邮件超出翻译处理范围，请查看原始邮件',
    'access_denied': '翻译服务权限或配置需要检查',
    'quota_exceeded': '翻译服务额度暂不可用，请稍后重试',
    'upstream_timeout': '邮件翻译超时，请稍后重试',
    'upstream_unavailable': '邮件翻译服务暂不可用，请稍后重试',
    'invalid_response': '翻译结果暂不可用，请稍后重试',
}


class TranslationError(Exception):
    def __init__(self, code):
        self.code = code if code in _ERRORS else 'upstream_unavailable'
        super().__init__(_ERRORS[self.code])


def _api_key():
    value = os.getenv('PRIVATE_GOOGLE_TRANSLATE_API_KEY') or ''
    if not re.fullmatch(r'[A-Za-z0-9_-]{20,200}', value): raise TranslationError('not_configured')
    return value


def configured():
    enabled = (os.getenv('PRIVATE_MAIL_TRANSLATION_ENABLED') or '').strip().lower() in {'1', 'true'}
    if not enabled: return False
    try:
        _api_key(); monthly_limit()
    except TranslationError: return False
    return True


def monthly_limit():
    value = os.getenv('PRIVATE_MAIL_TRANSLATION_MONTHLY_CHAR_LIMIT', str(DEFAULT_MONTHLY_CHARACTER_LIMIT))
    if not re.fullmatch(r'[0-9]{1,8}', value): raise TranslationError('not_configured')
    result = int(value)
    if not 1 <= result <= 10_000_000: raise TranslationError('not_configured')
    return result


def _text(value, maximum, *, truncate=False):
    if not isinstance(value, str): raise TranslationError('invalid_input')
    try: value.encode('utf-8')
    except UnicodeError: raise TranslationError('invalid_input') from None
    # Preserve readable line breaks, but remove nonprinting controls that could
    # conceal content or leak terminal instructions if accidentally inspected.
    value = value.replace('\r\n', '\n').replace('\r', '\n')
    value = ''.join(character for character in value if character in '\n\t'
                    or unicodedata.category(character) not in {'Cc', 'Cs'})
    if len(value) > maximum:
        if not truncate: raise TranslationError('invalid_input')
        return value[:maximum], True
    return value, False


def _han(character):
    code = ord(character)
    return (0x3400 <= code <= 0x4DBF or 0x4E00 <= code <= 0x9FFF
            or 0xF900 <= code <= 0xFAFF or 0x20000 <= code <= 0x323AF)


def _needs_translation(text):
    letters = [character for character in text if character.isalpha()]
    if not letters: return False  # Numeric/punctuation-only content is invariant.
    if not all(_han(character) for character in letters): return True
    # Han alone can also be Japanese. Skip only clear Chinese phrases and no
    # Latin, kana or other alphabetic content; mixed mail always gets translated.
    phrases = ('您好', '谢谢', '请您', '已确认', '已收到', '收款', '退款', '账户', '发票', '账单',
               '安全提醒', '邮件', '支付', '验证码', '登录', '预约', '客户', '这是', '中文', '本月')
    return not any(phrase in text for phrase in phrases)


@dataclass(frozen=True, repr=False)
class TranslationPlan:
    title: str = field(repr=False)
    summary: str = field(repr=False)
    body: str | None = field(repr=False)
    body_truncated: bool
    source_hash: str
    character_count: int
    _segments: tuple[tuple[str, str], ...] = field(repr=False)

    def __repr__(self): return '<PrivateMailTranslationPlan>'


def prepare_mail_translation(title, summary, body=None, *, body_truncated=False):
    if type(body_truncated) is not bool: raise TranslationError('invalid_input')
    title, _ = _text(title, 2_000); summary, _ = _text(summary, 1_000)
    clipped = False
    if body is not None: body, clipped = _text(body, MAX_BODY_CHARACTERS, truncate=True)
    body_truncated = body_truncated or clipped
    values = {'title': title, 'summary': summary, 'body': body, 'body_truncated': body_truncated}
    digest = hashlib.sha256(json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    segments = tuple((name, value[offset:offset + MAX_SEGMENT_CHARACTERS])
                     for name, value in (('title', title), ('summary', summary), ('body', body))
                     if value and _needs_translation(value)
                     for offset in range(0, len(value), MAX_SEGMENT_CHARACTERS))
    return TranslationPlan(title, summary, body, body_truncated, digest,
                           sum(len(value) for _, value in segments), segments)


def translation_cache_key(owner_id, mailbox, generation, message_id, source_hash):
    if (not isinstance(owner_id, str) or not owner_id or len(owner_id) > 64
            or not isinstance(mailbox, str) or not re.fullmatch(r'[^\s@]{1,64}@[^\s@]{1,190}', mailbox)
            or type(generation) is not int or generation < 0
            or not isinstance(message_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', message_id)
            or not isinstance(source_hash, str) or not re.fullmatch(r'[a-f0-9]{64}', source_hash)):
        raise TranslationError('invalid_input')
    values = [owner_id, mailbox.casefold(), generation, message_id, source_hash, TARGET_LANGUAGE, TRANSLATION_VERSION]
    return hashlib.sha256(json.dumps(values, separators=(',', ':')).encode()).hexdigest()


def _payload(segments):
    return json.dumps({'q': [text for _, text in segments], 'target': TARGET_LANGUAGE, 'format': 'text', 'model': 'nmt'},
                      ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def _batches(plan):
    batches = []; batch = []
    for segment in plan._segments:
        if len(_payload([*batch, segment])) > MAX_REQUEST_BYTES:
            if not batch: raise TranslationError('request_limit')
            batches.append(tuple(batch)); batch = []
        batch.append(segment)
    if batch: batches.append(tuple(batch))
    if len(batches) > MAX_REQUESTS: raise TranslationError('request_limit')
    return batches


async def _request(client, segments, key):
    try:
        async with client.stream('POST', TRANSLATION_URL, content=_payload(segments), headers={
                'X-Goog-Api-Key': key, 'Content-Type': 'application/json; charset=utf-8', 'Accept': 'application/json'}) as response:
            if response.status_code in (401, 403): raise TranslationError('access_denied')
            if response.status_code == 429: raise TranslationError('quota_exceeded')
            if response.status_code != 200: raise TranslationError('upstream_unavailable')
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                raw.extend(chunk)
                if len(raw) > MAX_RESPONSE_BYTES: raise TranslationError('invalid_response')
            try: data = json.loads(raw)
            except (ValueError, UnicodeError): raise TranslationError('invalid_response') from None
    except httpx.TimeoutException: raise TranslationError('upstream_timeout') from None
    except httpx.HTTPError: raise TranslationError('upstream_unavailable') from None
    translations = (data.get('data') or {}).get('translations') if isinstance(data, dict) and isinstance(data.get('data'), dict) else None
    if not isinstance(translations, list) or len(translations) != len(segments): raise TranslationError('invalid_response')
    results = []
    for translated, (_, source) in zip(translations, segments):
        value = translated.get('translatedText') if isinstance(translated, dict) else None
        if not isinstance(value, str) or not value and source.strip(): raise TranslationError('invalid_response')
        # Google returns HTML entities even for format=text. Decode once;
        # consumers must render this as text, never raw HTML.
        value = html.unescape(value)
        try: value, _ = _text(value, max(10_000, len(source) * 6))
        except TranslationError: raise TranslationError('invalid_response') from None
        results.append(value)
    return results


async def translate_mail(plan, *, transport=None):
    if not isinstance(plan, TranslationPlan): raise TranslationError('invalid_input')
    # Rebuild the plan so callers cannot forge the quota count or segments.
    checked = prepare_mail_translation(plan.title, plan.summary, plan.body, body_truncated=plan.body_truncated)
    if checked != plan: raise TranslationError('invalid_input')
    batches = _batches(plan); translated = {'title': plan.title, 'summary': plan.summary, 'body': plan.body}
    if batches:
        if not configured(): raise TranslationError('not_configured')
        key = _api_key(); assembled = {}
        deadline = asyncio.get_running_loop().time() + MAX_SECONDS
        async with httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(20, connect=5),
                                    follow_redirects=False, trust_env=False) as client:
            for batch in batches:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0: raise TranslationError('upstream_timeout')
                try: values = await asyncio.wait_for(_request(client, batch, key), timeout=remaining)
                except asyncio.TimeoutError: raise TranslationError('upstream_timeout') from None
                for (name, _), value in zip(batch, values): assembled.setdefault(name, []).append(value)
        translated.update({name: ''.join(values) for name, values in assembled.items()})
    return {'status': 'ready', 'provider': 'google_cloud_translation', 'target_language': TARGET_LANGUAGE,
            'version': TRANSLATION_VERSION, **translated, 'body_truncated': plan.body_truncated,
            'source_hash': plan.source_hash, 'translated_at': datetime.now(timezone.utc).isoformat(),
            'characters': plan.character_count}
