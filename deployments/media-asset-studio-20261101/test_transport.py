import ast
import base64
import hashlib
import importlib.util
from pathlib import Path
import re
import zlib

import pytest

HERE = Path(__file__).resolve().parent


def module():
    spec = importlib.util.spec_from_file_location('asset_transport', HERE / 'make_toolchain_transport.py')
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def python_body(command):
    return command.split("<<'ASSET_TOOLCHAIN_PROTECTED_TRANSPORT'\n", 1)[1].rsplit('\nASSET_TOOLCHAIN_PROTECTED_TRANSPORT\n', 1)[0]


def test_all_fragments_below_console_limit_and_reconstruct_exact_reviewed_command():
    m = module(); source = (HERE / 'toolchain-command.sh').read_bytes(); commands, pins = m.generate(source)
    assert len(commands) == len(pins['chunks']) + 1 and all(len(body.encode()) < 14000 for body in commands.values())
    packed = []
    for index, (name, size, sha) in enumerate(pins['chunks']):
        command = commands[f'stage-{index:02d}-command.sh']; ast.parse(python_body(command))
        match = re.search(r'body=base64.b64decode\(([^,]+),validate=True\)', command)
        body = base64.b64decode(ast.literal_eval(match[1]), validate=True)
        assert len(body) == size and hashlib.sha256(body).hexdigest() == sha
        packed.append(body)
    body = b''.join(packed)
    assert hashlib.sha256(body).hexdigest() == pins['packed_sha256'] and zlib.decompress(body) == source
    assert hashlib.sha256(source).hexdigest() == pins['source_command_sha256'] == 'c1b0cbbeaa3305379cc634ae7d37b45627a32d35d129b750ad261863a0f27075'
    ast.parse(python_body(commands['execute-command.sh']))


def test_stage_scripts_only_store_exact_ordered_chunks_and_never_run_toolchain():
    m = module(); commands, _ = m.generate((HERE / 'toolchain-command.sh').read_bytes())
    for name, command in commands.items():
        tree = ast.parse(python_body(command))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
        if name.startswith('stage-'):
            assert not any(isinstance(c.func, ast.Attribute) and c.func.attr in {'execve', 'system', 'Popen', 'run'} for c in calls)
            assert 'ORDERED_APPEND_ONLY_TRANSPORT_REQUIRED' in command and "'toolchain_executed':False" in command
        else:
            assert "EXACT_REVIEWED_TOOLCHAIN_COMMAND_REQUIRED" in command and "execution-started.json" in command
            assert "os.execve('/bin/bash'" in command and "FRESH_COMPLETE_TRANSPORT_REQUIRED" in command


def test_transport_is_deterministic_and_rejects_changed_reviewed_source():
    m = module(); source = (HERE / 'toolchain-command.sh').read_bytes()
    assert m.generate(source) == m.generate(source)
    with pytest.raises(RuntimeError, match='EXACT_REVIEWED_TOOLCHAIN_COMMAND_REQUIRED'): m.generate(source + b'changed')


def test_root_private_nofollow_exclusive_hash_and_fsync_guards_are_embedded():
    m = module(); commands, _ = m.generate((HERE / 'toolchain-command.sh').read_bytes())
    for command in commands.values():
        assert 'EXACT_ROOT_SERVER_REQUIRED' in command and 'O_NOFOLLOW' in command and 'O_EXCL' in command
        assert '0o600' in command and '0o700' in command and 'os.fsync' in command
        assert 'TRANSPORT_HASH_OR_IDENTITY_DRIFT' in command
