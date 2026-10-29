import copy
import json
import sys
import types
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import core as c
import diagnostics as d
import collector_policy as p
import make_policy_command as generator


def test_rsyslog_policy_only_returns_module_types_and_local_log_inputs():
    blob = b'''module(load="imuxsock")
module(load="imfile")
input(type="imfile" File="/var/log/nginx/access.log" Tag="SECRET_TAG")
action(type="omfwd" target="SECRET_REMOTE" port="12345" token="SUPERSECRET")
$InputFileName /var/log/nginx/error.log
# input(type="pcap" File="/secret/config")
'''
    result = p.summary(blob)
    assert {'imfile', 'imuxsock', 'omfwd'} <= set(result['module_or_input_type_markers'])
    assert result['local_log_input_pathnames'] == ['/var/log/nginx/access.log', '/var/log/nginx/error.log']
    assert result['network_output_marker_present'] is True
    assert result['http_or_packet_capture_marker_present'] is False
    text = json.dumps(result)
    assert 'SECRET' not in text and '12345' not in text and 'Tag' not in text
    assert result['semantics_not_fully_evaluated'] is True


def test_json_policy_paths_are_allowlisted_and_values_never_exported():
    value = {'module': 'metrics', 'token': 'SUPERSECRET', 'endpoint': 'https://SECRET_REMOTE',
        'inputs': [{'FilePath': '/var/log/nginx/access.log'}, {'File': '/opt/t24-crm/secrets/secret.env'}],
        'capture_request': False}
    result = p.summary(json.dumps(value).encode())
    assert result['local_log_input_pathnames'] == ['/var/log/nginx/access.log']
    assert result['nonlog_path_values_redacted'] is True
    assert result['http_or_packet_capture_marker_present'] is True  # Conservative presence, never assumes enabled/disabled.
    assert 'SECRET' not in json.dumps(result) and 'secret.env' not in json.dumps(result)


@pytest.mark.parametrize('value', ['https://remote/secret', '/etc/../secret', '/var/log/evil\nsecret', 'relative/path', None])
def test_policy_path_rejects_nonpath_or_traversal(value):
    assert p.safe_path(value) is False


def test_candidate_roots_are_fixed_not_business_data_or_private_space():
    assert p.UNITS == ('rsyslog.service', 'cloudmonitor.service', 'aliyun.service')
    assert not any(root.startswith(('/home/', '/root/', '/proc/', '/opt/t24-crm/')) for _, root, _ in p.POLICY_GLOBS)
    assert all('**' not in pattern for _, _, pattern in p.POLICY_GLOBS)


def test_policy_symlink_cannot_reach_unrelated_credentials(monkeypatch):
    original = Path.resolve
    monkeypatch.setattr(Path, 'resolve', lambda path, **kw: Path('/usr/local/secret/credentials.conf') if str(path) == '/etc/rsyslog.d/normal.conf' else original(path, **kw))
    with pytest.raises(c.GuardError, match='POLICY_CONFIG_SYMLINK_REJECTED'):
        p.protected_policy(Path('/etc/rsyslog.d/normal.conf'))


def test_aggregate_never_returns_argv_environment_policy_values(monkeypatch):
    prior = json.loads((HERE.parent / 'google-business-20261030/deployed.json').read_bytes())
    info = {'Id': prior['crm']['id'], 'Image': c.IMAGE, 'State': {'Running': True}, 'Config': {'Env': ['KEEP=SUPERSECRET_ENV']}}
    fake = types.SimpleNamespace(read=lambda path, digest: json.dumps(prior).encode(),
        inspect=lambda name: copy.deepcopy(info) if name == 't24-crm' else pytest.fail('private container access'),
        runtime=lambda row: copy.deepcopy(prior['crm']))
    monkeypatch.setattr(c, 'server_guard', lambda: None)
    monkeypatch.setattr(c, 'legacy', lambda: fake)
    active = b'user www-data;http {}'
    monkeypatch.setattr(d, 'ACTIVE_NGINX_SHA', c.H(active))
    commands = []

    def run(args, code, **kwargs):
        commands.append(args)
        if args == ['nginx', '-T']: return active
        assert args[:4] == ['systemctl', 'show', '--property=FragmentPath', '--value'] and args[4] in p.UNITS
        return ('/lib/systemd/system/' + args[4] + '\n').encode()

    monkeypatch.setattr(c, 'run', run)
    monkeypatch.setattr(p, 'candidates', lambda: [('/etc/rsyslog.d/50-default.conf', 'rsyslog')])

    def read_policy(path):
        if str(path).endswith('.service'):
            return b'ExecStart=/usr/sbin/rsyslogd -n --token SUPERSECRET_ARG\nEnvironment=SUPERSECRET_DSN\n'
        return b'input(type="imfile" File="/var/log/nginx/access.log" auth="SUPERSECRET_POLICY")\n'

    monkeypatch.setattr(p, 'protected_policy', read_policy)
    result = p.proof()
    text = json.dumps(result)
    assert 'SUPERSECRET' not in text and '--token' not in text and 'Environment' not in text
    assert result['unit_pathnames_only'][0]['executable_pathnames_only'] == ['/usr/sbin/rsyslogd']
    assert result['policy_type_and_pathname_facts'][0]['local_log_input_pathnames'] == ['/var/log/nginx/access.log']
    assert result['manual_external_logging_review_still_required'] is True
    assert result['configuration_changed'] is False and result['private_containers_accessed'] is False
    assert not any(args[0] == 'docker' for args in commands)


def test_readonly_policy_wrapper_has_only_pinned_read_dependencies():
    command = generator.command()
    assert "loaded['collector_policy'].main()" in command
    assert "'activation':" not in command and "'transport':" not in command
    assert 'hashlib.sha256(blob).hexdigest()!=member' in command
