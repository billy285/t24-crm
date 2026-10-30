import copy
import json
import sys
import types
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import core as c
import callback_headers_probe as h
import make_headers_probe_command as generator


def test_http_and_server_headers_are_distinguished_from_static_siblings():
    config = b'''http { add_header X-Frame-Options SAMEORIGIN always;
server { server_name t24-crm.com;
location ^~ /api/ { proxy_pass http://127.0.0.1:8000; }
location / { add_header Referrer-Policy SECRET_VALUE; }
location /assets/ { add_header X-SECRET-NAME SECRET_VALUE; }
}}
'''
    result = h.header_scopes(config)
    assert sum(not row['is_location_scope'] for row in result) == 1
    assert sum(row['is_api_location'] for row in result) == 0
    assert 'SECRET' not in json.dumps(result)
    assert result[0]['public_security_header_name'] == 'x-frame-options'


def test_api_header_and_unknown_include_top_level_are_not_hidden():
    config = b'http {}\nserver { location ^~ /api/ { add_header X-Frame-Options SAMEORIGIN; } }\nadd_header Referrer-Policy no-referrer;'
    result = h.header_scopes(config)
    assert result[0]['is_api_location'] is True
    assert result[1]['is_location_scope'] is False


@pytest.mark.parametrize('blob', [b'http {', b'http {} garbage', b'}', b'http { add_header X bad }'])
def test_bad_header_context_syntax_fails_closed(blob):
    with pytest.raises(c.GuardError):
        h.header_scopes(blob)


def test_public_policy_facts_do_not_export_cookie_location_or_other_values():
    blob = b'HTTP/1.1 303 See Other\r\nLocation: /media-ops?google=failed\r\nReferrer-Policy: strict-origin-when-cross-origin\r\nCache-Control: private, no-store\r\nSet-Cookie: SUPERSECRET\r\nContent-Security-Policy: SECRET_DOMAIN\r\n\r\n'
    result = h.response_facts(blob)
    assert result['status'] == 303 and result['location_is_fixed_failed_redirect'] is True
    assert result['referrer_policy'] == ['strict-origin-when-cross-origin']
    assert result['cache_control_has_no_store'] is True
    assert 'SECRET' not in json.dumps(result)
    assert 'content-security-policy' in result['public_security_header_names_present']


def test_unexpected_referrer_value_is_redacted():
    result = h.response_facts(b'HTTP/1.1 303\nReferrer-Policy: SECRET\nLocation: https://SECRET/\n\n')
    assert result['referrer_policy'] == ['[UNEXPECTED_VALUE_REDACTED]']
    assert result['location_is_fixed_failed_redirect'] is False
    assert 'SECRET' not in json.dumps(result)


def test_header_wrapper_is_small_and_has_no_mutating_modules():
    text = generator.command()
    assert len(text.encode()) < 15000
    assert "loaded['callback_headers_probe'].main()" in text
    assert "'activation':" not in text and "'transport':" not in text


def test_probe_checks_rollback_and_performs_noquery_loopback_get(monkeypatch):
    prior = json.loads((HERE.parent / 'google-business-20261030/deployed.json').read_bytes())
    info = {'Id': prior['crm']['id'], 'Image': c.IMAGE, 'State': {'Running': True}, 'Config': {'Env': ['KEEP=SECRET_ENV']}}
    site, active = b'synthetic-original-site', b'http {server {location / {add_header Referrer-Policy SECRET;}}}'
    prior['nginx_sha256'] = c.H(site)
    fake = types.SimpleNamespace(read=lambda path, digest: json.dumps(prior).encode(),
        inspect=lambda name: copy.deepcopy(info) if name == 't24-crm' else pytest.fail('private container'),
        runtime=lambda value: copy.deepcopy(prior['crm']), NGINX=types.SimpleNamespace(read_bytes=lambda: site))
    monkeypatch.setattr(c, 'server_guard', lambda: None)
    monkeypatch.setattr(c, 'legacy', lambda: fake)
    monkeypatch.setattr(h, 'OBSERVED_ACTIVE_SHA', c.H(active))
    calls = []

    def run(args, code, **kwargs):
        calls.append(args)
        if args == ['nginx', '-T']: return active
        assert args[:2] == ['curl', '-q'] and args[-1] == 'https://t24-crm.com/api/v1/google-business/oauth/callback'
        assert args[args.index('--noproxy') + 1] == '*'
        assert args[args.index('--resolve') + 1] == 't24-crm.com:443:127.0.0.1'
        assert not any(value in args for value in ('--cookie', '-b', '--header', '-H'))
        return b'HTTP/1.1 303 See Other\r\nLocation: /media-ops?google=failed\r\nReferrer-Policy: strict-origin-when-cross-origin\r\nCache-Control: private, no-store\r\n\r\n'

    monkeypatch.setattr(c, 'run', run)
    result = h.proof()
    assert result['original_site_restored'] is True and result['observed_active_config_restored'] is True
    assert result['potential_inherited_header_directive_count'] == 0
    assert result['query_or_cookie_or_authentication_sent'] is False
    assert result['configuration_changed'] is False and result['business_writes'] is False
    assert 'SECRET' not in json.dumps(result)
    assert len([args for args in calls if args[0] == 'curl']) == 1
