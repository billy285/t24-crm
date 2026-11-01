"""Pinned public identities match the actual reviewed OFF-deployment receipts."""
import importlib.util
import json
from pathlib import Path
import re

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, file); value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value


def test_runtime_pins_match_the_actual_canonical_off_deployment():
    c = load('publisher_actual_runtime_pins', HERE/'core.py'); c.pins_ready()
    body = (ROOT/'outputs/meta-operations-20261101/deployed.json').read_bytes()
    assert c.H(body) == c.DEPLOYED_SHA
    value = json.loads(body)
    assert value['stage'] == 'META_OPERATIONS_DEPLOYED_OFF_VERIFIED'
    assert (value['source_sha'], value['frontend_version'], value['schema_revision']) == (c.SOURCE_SHA, c.FRONTEND, c.SCHEMA_REVISION)
    assert value['crm']['id'] == c.ORIGINAL_ID and value['crm']['image'] == c.IMAGE and value['crm']['restart'] == 0
    assert value['operations_environment_absent'] is True and value['operations_execution_enabled'] is value['operations_scheduler_enabled'] is False
    assert c.H((ROOT/'deployments/meta-operations-20261101/release.py').read_bytes()) == c.RELEASE_TOOL_SHA


def test_publisher_config_pins_match_reviewed_exact_eight_scopes_and_callback():
    c = load('publisher_actual_configuration_pins', HERE/'core.py')
    body = (ROOT/'outputs/meta-operations-20261101/publisher-configuration-freeze.json').read_bytes()
    assert c.H(body) == c.CONFIG_FREEZE_SHA; value = json.loads(body)
    assert (value['app_id'], value['config_id'], value['business_id']) == (c.APP_ID, c.CONFIG_ID, c.BUSINESS_ID)
    assert value['requested_scopes'] == list(c.SCOPES) and value['redirect_uris'] == [c.CALLBACK]
    assert value['token_type'] == 'USER' and value['mode'] == 'Development'
    assert value['callback_persisted_after_navigation'] is value['strict_redirect_mode'] is value['https_enforced'] is True
    assert value['credential_values_exported'] is value['public_post_or_reply_performed'] is False


def test_browser_encryptor_has_same_public_identity_pins_as_receiver():
    c = load('publisher_actual_browser_pins', HERE/'core.py'); script = (HERE/'encrypt-in-browser.js').read_text()
    expected = {'APP_ID':c.APP_ID, 'BUSINESS_ID':c.BUSINESS_ID, 'CONFIG_ID':c.CONFIG_ID,
        'GRAPH_VERSION':c.GRAPH_VERSION, 'CONFIG_FREEZE_SHA':c.CONFIG_FREEZE_SHA, 'SOURCE_SHA':c.SOURCE_SHA}
    for key, value in expected.items():
        assert re.search(r"const APPROVED_"+key+r" = '([^']+)';", script).group(1) == value


def test_real_identity_pins_do_not_bypass_pending_fresh_baseline():
    g = load('publisher_actual_pending_baseline', HERE/'make_commands.py')
    c, b = g.identities(runtime_only=True)
    assert b.BASELINE_SHA is None and c.APP_ID == '3037236509957803'
    with pytest.raises(RuntimeError, match='ACTUAL_REVIEWED_BASELINE_REQUIRED'): g.identities()
