"""Synthetic Gmail body reads: no credentials, real emails or external requests."""
import base64
import copy
import json

import httpx
import pytest

from services import private_workspace_providers as providers


ACCOUNT = 'synthetic-owner@example.com'
CREDENTIALS = {'access_token': 'synthetic-access', 'refresh_token': 'synthetic-refresh', 'expires_at': 2000000000,
               'scope': providers.GMAIL_SCOPE, 'token_type': 'Bearer'}
METADATA = {'account_label': ACCOUNT}


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setenv('GOOGLE_WORKSPACE_CLIENT_ID', 'synthetic-client.apps.googleusercontent.com')
    monkeypatch.setenv('GOOGLE_WORKSPACE_CLIENT_SECRET', 'synthetic-client-secret')
    monkeypatch.setenv('PRIVATE_WORKSPACE_PUBLIC_URL', 'https://t24-crm.com')
    monkeypatch.setenv('PRIVATE_WORKSPACE_GMAIL_EXPECTED_ACCOUNT', ACCOUNT)


def text_part(value, mime='text/plain', *, charset='utf-8', filename='', disposition=None):
    value = value.encode(charset) if isinstance(value, str) else value
    result = {'mimeType': mime, 'filename': filename,
              'headers': [{'name': 'Content-Type', 'value': f'{mime}; charset={charset}'}],
              'body': {'data': base64.urlsafe_b64encode(value).decode().rstrip('='), 'size': len(value)}}
    if disposition: result['headers'].append({'name': 'Content-Disposition', 'value': disposition})
    return result


def multipart(*parts, mime='multipart/alternative'):
    return {'mimeType': mime, 'headers': [], 'parts': list(parts)}


def message(payload):
    payload = copy.deepcopy(payload)
    payload['headers'] = [{'name': 'Subject', 'value': 'Synthetic subject'}, *payload.get('headers', [])]
    return {'id': 'synthetic-message', 'snippet': 'Synthetic snippet', 'payload': payload}


def transport_for(payload, *, account=ACCOUNT, message_id='synthetic-message'):
    calls = []

    def reply(request):
        calls.append(request)
        assert request.headers['Authorization'] == 'Bearer synthetic-access'
        if request.url.path.endswith('/profile'):
            assert request.method == 'GET' and dict(request.url.params) == {}
            return httpx.Response(200, json={'emailAddress': account})
        assert request.method == 'GET' and request.url.path == '/gmail/v1/users/me/messages/synthetic-message'
        assert dict(request.url.params) == {'format': 'full'}
        data = message(payload); data['id'] = message_id
        return httpx.Response(200, json=data)

    return httpx.MockTransport(reply), calls


async def fetch(payload, **kwargs):
    transport, calls = transport_for(payload, **kwargs)
    result = await providers.fetch_mail_content(CREDENTIALS, METADATA, 'synthetic-message', transport=transport)
    return result, calls


@pytest.mark.asyncio
async def test_explicit_full_read_validates_profile_then_returns_plain_body():
    result, calls = await fetch(text_part('Hello\r\n\r\nNext line\x00\tvalue'))
    assert result == {'title': 'Synthetic subject', 'summary': 'Synthetic snippet', 'body': 'Hello\n\nNext line\tvalue',
                      'has_body': True, 'truncated': False}
    assert len(calls) == 2
    assert calls[0].url.path.endswith('/profile')


@pytest.mark.asyncio
async def test_plain_preferred_over_html_without_decoding_or_loading_duplicate():
    result, calls = await fetch(multipart(text_part('<p>HTML duplicate</p>', 'text/html'), text_part('Plain original')))
    assert result['body'] == 'Plain original' and not result['truncated']
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_html_fallback_only_visible_text_no_script_attributes_or_remote_content():
    html = ('<html><head><title>Hidden title</title><style>BAD CSS</style></head><body><p>Hello &amp; welcome</p>'
            '<script>SECRET SCRIPT</script><div hidden>HIDDEN</div><div aria-hidden="true">ARIA</div>'
            '<div style="display: none">STYLE</div><iframe src="https://example.invalid">IFRAME</iframe>'
            '<a href="https://example.invalid/private">Visible link</a><img src="https://example.invalid/track">'
            '<br>Next line</body></html>')
    result, calls = await fetch(text_part(html, 'text/html'))
    assert result['body'] == 'Hello & welcome\nVisible link\nNext line'
    assert not result['truncated'] and len(calls) == 2
    assert 'https:' not in result['body'] and 'SECRET' not in result['body']


@pytest.mark.asyncio
async def test_empty_plain_falls_back_to_html():
    result, _ = await fetch(multipart(text_part('  \n'), text_part('<p>Readable fallback</p>', 'text/html')))
    assert result['body'] == 'Readable fallback'


@pytest.mark.parametrize('attribute', ['filename', 'attachment', 'inline-filename', 'subtree'])
@pytest.mark.asyncio
async def test_attached_files_and_message_subtrees_never_read(attribute):
    attached = text_part('ATTACHMENT CONTENT')
    if attribute == 'filename': attached['filename'] = 'attached.txt'
    elif attribute == 'attachment': attached['headers'].append({'name': 'Content-Disposition', 'value': 'attachment'})
    elif attribute == 'inline-filename': attached['headers'].append({'name': 'Content-Disposition', 'value': 'inline; filename="attached.txt"'})
    else: attached = {'mimeType': 'message/rfc822', 'parts': [attached], 'body': {'attachmentId': 'synthetic-attachment'}}
    result, calls = await fetch(multipart(text_part('Visible original'), attached, mime='multipart/mixed'))
    assert result['body'] == 'Visible original' and not result['truncated'] and len(calls) == 2


@pytest.mark.asyncio
async def test_attachment_subtree_skipped_before_recursing():
    attached = multipart(text_part('HIDDEN'))
    attached['headers'].append({'name': 'Content-Disposition', 'value': 'attachment'})
    result, _ = await fetch(multipart(text_part('Original'), attached))
    assert result['body'] == 'Original'


@pytest.mark.asyncio
async def test_external_body_reports_incomplete_without_attachment_request():
    result, calls = await fetch({'mimeType': 'text/plain', 'body': {'attachmentId': 'synthetic-attachment', 'size': 123}})
    assert result['body'] == '' and not result['has_body'] and result['truncated'] and len(calls) == 2


@pytest.mark.asyncio
async def test_header_only_message_has_no_body_not_truncated():
    result, _ = await fetch({'mimeType': 'text/plain', 'body': {}})
    assert result['body'] == '' and not result['has_body'] and not result['truncated']


@pytest.mark.parametrize('bad_id', ['../profile', 'id/attachments/a', 'id?format=raw', 'https://example.invalid', '', 'x' * 129, None])
@pytest.mark.asyncio
async def test_id_validation_happens_before_any_http_request(bad_id):
    def no_request(request): raise AssertionError('Unexpected HTTP request')
    with pytest.raises(providers.ProviderError, match='无法安全读取') as caught:
        await providers.fetch_mail_content(CREDENTIALS, METADATA, bad_id, transport=httpx.MockTransport(no_request))
    assert caught.value.code == 'invalid_response'


@pytest.mark.parametrize('metadata,expected_code', [({}, 'authorization_expired'), ({'account_label': 'different@example.com'}, 'access_denied')])
@pytest.mark.asyncio
async def test_missing_or_wrong_connected_identity_rejected_before_http(metadata, expected_code):
    def no_request(request): raise AssertionError('Unexpected HTTP request')
    with pytest.raises(providers.ProviderError) as caught:
        await providers.fetch_mail_content(CREDENTIALS, metadata, 'synthetic-message', transport=httpx.MockTransport(no_request))
    assert caught.value.code == expected_code


@pytest.mark.asyncio
async def test_missing_identity_fails_closed_even_without_expected_configuration(monkeypatch):
    monkeypatch.delenv('PRIVATE_WORKSPACE_GMAIL_EXPECTED_ACCOUNT')
    with pytest.raises(providers.ProviderError) as caught:
        await providers.fetch_mail_content(CREDENTIALS, {}, 'synthetic-message')
    assert caught.value.code == 'authorization_expired'


@pytest.mark.asyncio
async def test_realtime_profile_mismatch_rejected_before_message_read():
    transport, calls = transport_for(text_part('Must not read'), account='different@example.com')
    with pytest.raises(providers.ProviderError) as caught:
        await providers.fetch_mail_content(CREDENTIALS, METADATA, 'synthetic-message', transport=transport)
    assert caught.value.code == 'access_denied' and len(calls) == 1


@pytest.mark.asyncio
async def test_profile_binding_case_insensitive_and_unconfigured_expected_compatible(monkeypatch):
    monkeypatch.delenv('PRIVATE_WORKSPACE_GMAIL_EXPECTED_ACCOUNT')
    result, _ = await fetch(text_part('Confirmed account'), account=ACCOUNT.upper())
    assert result['body'] == 'Confirmed account'


@pytest.mark.asyncio
async def test_wrong_returned_message_id_rejected():
    with pytest.raises(providers.ProviderError) as caught:
        await fetch(text_part('Must not read'), message_id='different-message')
    assert caught.value.code == 'invalid_response'


@pytest.mark.parametrize('encoded', ['%%%%', 'abcd+/', 'A', 'abc=extra', '\nYQ', 123, 'abcd==='])
@pytest.mark.asyncio
async def test_malformed_body_encoding_does_not_escape_safe_error(encoded):
    part = text_part('Original'); part['body']['data'] = encoded
    with pytest.raises(providers.ProviderError) as caught:
        await fetch(part)
    assert caught.value.code == 'invalid_response'
    assert 'Original' not in str(caught.value) and str(encoded) not in str(caught.value)


@pytest.mark.asyncio
async def test_declared_charset_decodes_non_utf8():
    result, _ = await fetch(text_part('Café\nGood day', charset='iso-8859-1'))
    assert result['body'] == 'Café\nGood day'


@pytest.mark.asyncio
async def test_unknown_charset_falls_back_without_executing_or_loading_anything():
    part = text_part('你好')
    part['headers'][0]['value'] = 'text/plain; charset="unknown-synthetic-charset"'
    result, _ = await fetch(part)
    assert result['body'] == '你好'


@pytest.mark.parametrize('mime', ['text/plain', 'text/html'])
@pytest.mark.asyncio
async def test_body_character_cap_explicit_truncation(mime):
    value = 'a' * (providers.MAIL_BODY_MAX_CHARS + 1)
    result, _ = await fetch(text_part(value, mime))
    assert len(result['body']) == 50000 and result['truncated'] and result['has_body']


@pytest.mark.asyncio
async def test_aggregate_decoded_byte_budget_bounded(monkeypatch):
    monkeypatch.setattr(providers, 'MAIL_BODY_MAX_BYTES', 12)
    result, _ = await fetch(multipart(text_part('abcdefghij'), text_part('ABCDEFGHIJ'), mime='multipart/mixed'))
    assert result['body'] == 'abcdefghij\n\nAB' and result['truncated']


@pytest.mark.asyncio
async def test_oversize_single_part_decodes_only_bounded_prefix(monkeypatch):
    monkeypatch.setattr(providers, 'MAIL_BODY_MAX_BYTES', 6)
    result, _ = await fetch(text_part('abcdefghijklmnopqrstuvwxyz'))
    assert result['body'] == 'abcdef' and result['truncated']


@pytest.mark.asyncio
async def test_declared_body_larger_than_inline_bytes_marks_truncated():
    part = text_part('Short'); part['body']['size'] = 100
    result, _ = await fetch(part)
    assert result['body'] == 'Short' and result['truncated']


@pytest.mark.asyncio
async def test_mime_part_limit_explicit_not_silent_loss(monkeypatch):
    monkeypatch.setattr(providers, 'MAIL_MIME_MAX_PARTS', 3)
    result, _ = await fetch(multipart(text_part('first'), text_part('second'), text_part('third'), mime='multipart/mixed'))
    assert result['body'] == 'first\n\nsecond' and result['truncated']


@pytest.mark.asyncio
async def test_depth_limit_does_not_recurse_unbounded(monkeypatch):
    monkeypatch.setattr(providers, 'MAIL_MIME_MAX_DEPTH', 2)
    result, _ = await fetch(multipart(text_part('visible'), multipart(multipart(text_part('too deep')))))
    assert result['body'] == 'visible' and result['truncated']


@pytest.mark.asyncio
async def test_unsupported_body_types_not_read_or_decoded():
    result, _ = await fetch({'mimeType': 'image/png', 'body': {'data': 'not valid base64!'}})
    assert not result['has_body'] and not result['truncated']


@pytest.mark.asyncio
async def test_html_nesting_cap_does_not_show_hidden_content_or_break_output():
    value = '<div>' * 140 + 'Bounded nested content' + '</div>' * 140
    result, _ = await fetch(text_part(value, 'text/html'))
    assert result['truncated'] and not result['has_body']


@pytest.mark.asyncio
async def test_title_summary_controls_and_length_are_bounded():
    def reply(request):
        if request.url.path.endswith('/profile'): return httpx.Response(200, json={'emailAddress': ACCOUNT})
        data = message(text_part('Body')); data['snippet'] = 's' * 1100 + '\x00'
        data['payload']['headers'][0]['value'] = 't' * 1100 + '\x00'
        return httpx.Response(200, json=data)
    result = await providers.fetch_mail_content(CREDENTIALS, METADATA, 'synthetic-message', transport=httpx.MockTransport(reply))
    assert len(result['title']) == len(result['summary']) == 1000 and '\x00' not in result['title']


@pytest.mark.parametrize('subject,expected', [('=?UTF-8?B?5pyI5bqm6LSm5Y2V?=', '月度账单'), ('=?iso-8859-1?Q?Caf=E9_payment?=', 'Café payment')])
def test_encoded_subject_is_readable_plain_text(subject, expected):
    assert providers._mail_subject(subject) == expected


@pytest.mark.asyncio
async def test_html_parser_failure_never_contains_mail_content(monkeypatch):
    def parser_failure(parser, text): raise AssertionError('synthetic-sensitive parser content')
    monkeypatch.setattr(providers._MailHTMLText, 'feed', parser_failure)
    with pytest.raises(providers.ProviderError) as caught:
        await fetch(text_part('<![synthetic-sensitive]>', 'text/html'))
    assert caught.value.code == 'invalid_response' and 'synthetic-sensitive' not in str(caught.value)


def test_mail_plain_removes_unpaired_surrogates_from_unusual_charset():
    assert providers._mail_plain('Readable\ud800text') == 'Readabletext'


@pytest.mark.asyncio
async def test_refresh_returned_only_to_core_and_input_not_mutated():
    credentials = copy.deepcopy(CREDENTIALS); credentials['expires_at'] = 1; before = copy.deepcopy(credentials); calls = []
    def reply(request):
        calls.append(request)
        if request.url.host == 'oauth2.googleapis.com':
            assert request.method == 'POST' and request.url.path == '/token'
            return httpx.Response(200, json={'access_token': 'synthetic-new-access', 'expires_in': 3600, 'token_type': 'Bearer'})
        assert request.headers['Authorization'] == 'Bearer synthetic-new-access'
        if request.url.path.endswith('/profile'): return httpx.Response(200, json={'emailAddress': ACCOUNT})
        return httpx.Response(200, json=message(text_part('Body')))
    result = await providers.fetch_mail_content(credentials, METADATA, 'synthetic-message', transport=httpx.MockTransport(reply))
    assert result['credentials']['access_token'] == 'synthetic-new-access'
    assert result['credentials']['refresh_token'] == 'synthetic-refresh' and credentials == before
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_metadata_only_scope_cannot_access_full_body():
    credentials = {**CREDENTIALS, 'scope': 'https://www.googleapis.com/auth/gmail.metadata'}
    def no_request(request): raise AssertionError('Unexpected HTTP request')
    with pytest.raises(providers.ProviderError) as caught:
        await providers.fetch_mail_content(credentials, METADATA, 'synthetic-message', transport=httpx.MockTransport(no_request))
    assert caught.value.code == 'access_denied'


@pytest.mark.asyncio
async def test_attachment_endpoint_stays_outside_provider_allowlist():
    async with providers._Client(httpx.MockTransport(lambda request: (_ for _ in ()).throw(AssertionError('Unexpected request')))) as client:
        with pytest.raises(providers.ProviderError) as caught:
            await client.request('GET', 'https://gmail.googleapis.com/gmail/v1/users/me/messages/synthetic-message/attachments/attached')
    assert caught.value.code == 'request_not_allowed'


@pytest.mark.asyncio
async def test_whole_response_byte_limit_remains_enforced():
    def reply(request):
        if request.url.path.endswith('/profile'): return httpx.Response(200, json={'emailAddress': ACCOUNT})
        return httpx.Response(200, content=json.dumps({'id': 'synthetic-message', 'padding': 'a' * providers.MAX_RESPONSE_BYTES}))
    with pytest.raises(providers.ProviderError) as caught:
        await providers.fetch_mail_content(CREDENTIALS, METADATA, 'synthetic-message', transport=httpx.MockTransport(reply))
    assert caught.value.code == 'invalid_response'
