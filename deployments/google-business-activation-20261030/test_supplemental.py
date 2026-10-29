import copy
import json
import stat
import subprocess
import sys
import types
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import core as c
import diagnostics as d
import supplemental as s
import make_supplemental_command as generator


def test_forwarder_filter_only_names_and_redacts_unit_instances():
    values = ['rsyslog.service', 'filebeat@billy.personal.example.service', 'nginx.service', 'datadog-agent.service',
        'unrelated.service', 'ilogtail.service', 'filebeat.service SECRET_VALUE']
    result = s.matched_names(values, s.FORWARDER_MARKERS, unit=True)
    assert result == ['datadog-agent.service', 'filebeat@INSTANCE_REDACTED.service', 'ilogtail.service', 'rsyslog.service']
    assert 'personal' not in json.dumps(result) and 'SECRET_VALUE' not in json.dumps(result)


def test_process_comm_filter_includes_linux_truncated_names():
    result = s.matched_names(['systemd-journal', 'ilogtail', 'AliYunDun', 'python3', 'otelcol-contrib'], s.FORWARDER_MARKERS)
    assert result == ['AliYunDun', 'ilogtail', 'otelcol-contrib', 'systemd-journal']


def test_worker_identity_resolves_explicit_or_default_group(monkeypatch):
    monkeypatch.setattr(s.pwd, 'getpwnam', lambda name: types.SimpleNamespace(pw_uid=33, pw_gid=33) if name == 'www-data' else pytest.fail('unexpected user'))
    monkeypatch.setattr(s.grp, 'getgrnam', lambda name: types.SimpleNamespace(gr_gid=4) if name == 'adm' else pytest.fail('unexpected group'))
    default = s.worker_identity(b'user www-data;\nhttp {}\n')
    assert default['uid'] == 33 and default['effective_gid'] == 33 and default['explicit_group_configured'] is False
    explicit = s.worker_identity(b'user www-data adm;\nhttp {}\n')
    assert explicit['effective_gid'] == 4 and explicit['configured_group'] == 'adm'


@pytest.mark.parametrize('blob', [b'http {}', b'user root;\nuser www-data;', b'user "not-a-literal";'])
def test_ambiguous_worker_configuration_fails_closed(blob):
    with pytest.raises(c.GuardError, match='EXACT_CONFIGURED_NGINX_WORKER_USER_REQUIRED'):
        s.worker_identity(blob)


def test_process_snapshot_reads_comm_only(tmp_path):
    for pid, name in [('1', 'python3'), ('2', 'ilogtail'), ('3', 'bad name SECRET'), ('not-a-pid', 'SECRET')]:
        path = tmp_path / pid
        path.mkdir()
        (path / 'comm').write_text(name + '\n')
        (path / 'cmdline').write_text('SECRET_ARGV')
        (path / 'environ').write_text('SECRET_ENV')
    assert s.process_names(tmp_path) == ['ilogtail', 'python3']


def test_log_metadata_is_lstat_only_with_exact_permissions_and_no_contents(monkeypatch):
    original_lstat, original_resolve, original_open = Path.lstat, Path.resolve, Path.open

    def lstat(path):
        if str(path) == '/var/log/nginx':
            return types.SimpleNamespace(st_uid=0, st_gid=4, st_mode=stat.S_IFDIR | 0o755, st_nlink=2)
        if str(path) == '/var/log/nginx/access.log':
            return types.SimpleNamespace(st_uid=33, st_gid=4, st_mode=stat.S_IFREG | 0o640, st_nlink=1)
        if str(path) == '/var/log/nginx/error.log':
            return types.SimpleNamespace(st_uid=0, st_gid=0, st_mode=stat.S_IFLNK | 0o777, st_nlink=1)
        if str(path) == '/var/log/nginx/missing.log':
            raise FileNotFoundError()
        return original_lstat(path)

    def resolve(path, **kwargs):
        if str(path) == '/var/log/nginx/error.log':
            return Path('/dev/stdout')
        if str(path).startswith('/var/log/nginx'):
            return path
        return original_resolve(path, **kwargs)

    def open_no_log_contents(path, *args, **kwargs):
        assert not str(path).startswith('/var/log/nginx'), 'log content must never be opened'
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'lstat', lstat)
    monkeypatch.setattr(Path, 'resolve', resolve)
    monkeypatch.setattr(Path, 'open', open_no_log_contents)
    rows = [{'destination_type': 'local-nginx-log', 'destination': '/var/log/nginx/' + name} for name in ('access.log', 'error.log', 'missing.log')]
    result = s.stat_logs(rows)
    assert result[0]['uid'] == 33 and result[0]['gid'] == 4 and result[0]['mode'] == '0640' and result[0]['nlink'] == 1
    assert result[0]['parent']['uid'] == 0 and result[0]['parent']['mode'] == '0755'
    assert result[1]['is_symlink'] is True and result[1]['resolved_path'] == '/dev/stdout'
    assert result[2]['exists'] is False


def test_crm_probe_uses_metadata_not_importing_plugins_and_never_reads_sensitive_process_files():
    source = s.crm_probe_source()
    compile(source, 'readonly-crm-metadata-probe', 'exec')
    assert 'metadata.distributions(path=distribution_paths)' in source
    assert "sysconfig.get_path(name) for name in ('purelib','platlib')" in source
    assert "p/'comm'" in source and 'cmdline' not in source and 'environ' not in source
    assert 'import ddtrace' not in source and 'import sentry_sdk' not in source
    assert 'file_url' not in source and 'os.environ' not in source


@pytest.mark.parametrize('value', [
    {'process_comm_names': ['python3'], 'matching_installed_package_names': ['ddtrace'], 'argv': 'SECRET'},
    {'process_comm_names': ['SECRET ARG'], 'matching_installed_package_names': []},
    {'process_comm_names': ['python3'], 'matching_installed_package_names': ['unrelated-package']},
    {'process_comm_names': ['python3', 'python3'], 'matching_installed_package_names': []},
    {'process_comm_names': [None], 'matching_installed_package_names': []},
])
def test_unapproved_crm_probe_output_is_rejected(value):
    with pytest.raises((c.GuardError, TypeError)):
        s.validate_crm_probe(json.dumps(value).encode())


def test_supplemental_wrapper_embeds_only_readonly_dependencies():
    source = generator.command()
    assert "loaded['supplemental'].main()" in source
    assert "'activation':" not in source and "'transport':" not in source
    assert 'hashlib.sha256(blob).hexdigest()!=member' in source


def test_full_supplemental_probe_only_reads_exact_crm_identity(monkeypatch):
    prior = json.loads((HERE.parent / 'google-business-20261030/deployed.json').read_bytes())
    info = {'Id': prior['crm']['id'], 'Image': c.IMAGE, 'State': {'Running': True}}
    calls = []
    active = b'user www-data;\nerror_log /var/log/nginx/error.log warn;\nhttp {}\n'
    monkeypatch.setattr(c, 'server_guard', lambda: None)
    monkeypatch.setattr(d, 'ACTIVE_NGINX_SHA', c.H(active))
    diagnostics = {'nginx_logging_directives': [], 'environment_values_exported': False,
        'manual_external_logging_review_still_required': True, 'public_dns_ips': ['1.1.1.1']}
    monkeypatch.setattr(d, 'proof', lambda: copy.deepcopy(diagnostics))
    fake = types.SimpleNamespace(read=lambda path, digest: json.dumps(prior).encode(),
        inspect=lambda name: copy.deepcopy(info) if name == 't24-crm' else pytest.fail('private/arbitrary container access'),
        runtime=lambda row: copy.deepcopy(prior['crm']))
    monkeypatch.setattr(c, 'legacy', lambda: fake)
    monkeypatch.setattr(s.pwd, 'getpwnam', lambda name: types.SimpleNamespace(pw_uid=33, pw_gid=33))
    monkeypatch.setattr(s, 'process_names', lambda: ['python3', 'ilogtail'])

    def run(args, code, **kwargs):
        calls.append(args)
        if args == ['nginx', '-T']:
            return active
        if args[0] == 'systemctl':
            assert args == ['systemctl', 'list-units', '--type=service', '--state=running', '--no-legend', '--no-pager', '--plain']
            return b'rsyslog.service loaded active running SECRET_DESCRIPTION\nnginx.service loaded active running WEB\n'
        assert args[:8] == ['docker', 'exec', prior['crm']['id'], 'python', '-I', '-S', '-B', '-c']
        return b'{"process_comm_names":["python3"],"matching_installed_package_names":["opentelemetry-api"]}'

    monkeypatch.setattr(c, 'run', run)
    result = s.proof()
    assert result['host_matching_active_service_names'] == ['rsyslog.service']
    assert result['host_matching_process_comm_names'] == ['ilogtail']
    assert result['crm_readonly_name_probe']['matching_installed_package_names'] == ['opentelemetry-api']
    assert 'SECRET_DESCRIPTION' not in json.dumps(result)
    assert result['private_containers_accessed'] is False and result['log_contents_read'] is False
    assert result['manual_external_logging_review_still_required'] is True
    assert result['business_writes'] is False and result['configuration_changed'] is False
    assert len([args for args in calls if args[0] == 'docker']) == 1


def test_isolated_no_site_probe_does_not_execute_synthetic_startup_hooks(tmp_path):
    marker = tmp_path / 'startup-side-effect'
    pythonpath = tmp_path / 'telemetry-site'
    pythonpath.mkdir()
    action = 'from pathlib import Path;Path(' + repr(str(marker)) + ').write_text("UNSAFE_STARTUP")\n'
    (pythonpath / 'sitecustomize.py').write_text(action)
    (pythonpath / 'telemetry.pth').write_text('import pathlib;pathlib.Path(' + repr(str(marker)) + ').write_text("UNSAFE_PTH")\n')
    env = dict(__import__('os').environ, PYTHONPATH=str(pythonpath))
    # Demonstrate the synthetic hook is effective under ordinary site startup.
    control = subprocess.run([sys.executable, '-B', '-c', 'import site;site.addsitedir(' + repr(str(pythonpath)) + ')'], env=env, capture_output=True)
    assert control.returncode == 0 and marker.read_text() == 'UNSAFE_PTH'
    marker.unlink()
    proc = tmp_path / 'proc'
    (proc / '1').mkdir(parents=True)
    (proc / '1/comm').write_text('python3\n')
    # The production probe is Linux-only; substitute its comm directory for
    # this macOS subprocess fixture while executing all metadata/startup code.
    code = s.crm_probe_source().replace("Path('/proc')", 'Path(' + repr(str(proc)) + ')')
    result = subprocess.run([sys.executable, '-I', '-S', '-B', '-c', code], env=env, capture_output=True)
    assert result.returncode == 0, result.stderr.decode()
    value = s.validate_crm_probe(result.stdout)
    assert 'process_comm_names' in value and not marker.exists()
