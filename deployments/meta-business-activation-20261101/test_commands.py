"""Immutable local carrier simulation; generated commands are never executed."""
import ast
import base64
import importlib.util
import json
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('meta_activation_command_test', HERE/'make_commands.py')
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)


def summary(): return json.loads((HERE.parents[1]/'outputs/meta-business-activation-20261101/baseline-summary.json').read_bytes())


@pytest.fixture
def carrier(monkeypatch):
    def git(argv):
        assert argv[0] == 'git'
        if argv[1] == 'rev-parse': return b'exact-application-tree\n'
        assert argv[1] == 'show'; name = argv[2].split(':', 1)[1].removeprefix(g.DIRECTORY+'/')
        return (HERE/name).read_bytes()
    monkeypatch.setattr(g.subprocess, 'check_output', git)
    return 'a'*40


def python_body(command): return command.split("<<'META_ACTIVATION'\n", 1)[1].rsplit('\nMETA_ACTIVATION', 1)[0]


def test_exact_carrier_generates_separate_small_activation_namespace_commands(carrier):
    commands, report = g.generate(carrier, summary())
    assert set(commands) == {'stage-command.sh', 'prepare-command.sh', 'activate-command.sh', 'recover-command.sh'}
    for name, command in commands.items():
        assert len(command.encode()) < 11000; ast.parse(python_body(command))
        assert 'tools-activation-v1' in command and "sys.modules['core']=module" in command
        assert report['commands'][name] == g.H(command.encode())
    stage = commands['stage-command.sh']
    assert 'ProxyHandler({})' in stage and 'NoRedirect' in stage and "verify('tool-staging-before')" in stage
    assert 'baseline.json' not in stage.split('c.write(', 1)[1] and 'ENV_FILE' not in stage
    assert report['members'] == {name: {'sha256': g.H((HERE/name).read_bytes()), 'bytes': (HERE/name).stat().st_size} for name in g.MEMBERS}


def test_carrier_tree_or_member_drift_rejected(carrier, monkeypatch):
    real = g.subprocess.check_output
    def altered(argv):
        if argv[1] == 'show': return real(argv)+b'changed'
        return real(argv)
    monkeypatch.setattr(g.subprocess, 'check_output', altered)
    with pytest.raises(RuntimeError, match='EXACT_COMMITTED_TOOL_REQUIRED'): g.generate(carrier, summary())


@pytest.mark.parametrize('key,value', [('sha256', 'b'*64), ('table_count', 140), ('meta_environment_keys_absent', False), ('source_sha', 'b'*40)])
def test_wrong_actual_baseline_cannot_generate_command(carrier, key, value):
    row = summary(); row[key] = value
    with pytest.raises(RuntimeError, match='EXACT_ACTUAL_BASELINE_SUMMARY_REQUIRED'): g.generate(carrier, row)


def test_receive_wrapper_accepts_only_exact_encrypted_payload(carrier):
    _, report = g.generate(carrier, summary()); cipher = base64.b64encode(bytes(384)).decode()
    command = g.entry_command(report['members'], 'receive', transfer_id='a'*32, ciphertext=cipher)
    ast.parse(python_body(command)); assert len(command.encode()) < 11000 and cipher in command
    assert 'APP_SECRET=' not in command and 'TOKEN_KEY=' not in command
    for value in ('not-ciphertext', base64.b64encode(bytes(383)).decode(), cipher+'\n'):
        with pytest.raises(RuntimeError): g.entry_command(report['members'], 'receive', transfer_id='a'*32, ciphertext=value)
    with pytest.raises(RuntimeError): g.entry_command(report['members'], 'receive', transfer_id='wrong', ciphertext=cipher)


def test_stage_pin_dictionary_cannot_be_retargeted(carrier):
    _, report = g.generate(carrier, summary()); report['members']['baseline.py']['sha256'] = 'b'*64
    with pytest.raises(RuntimeError, match='EXACT_CURRENT_FOUR_TOOL_PINS_REQUIRED'): g.entry_command(report['members'], 'activate')
