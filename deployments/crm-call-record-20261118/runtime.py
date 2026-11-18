"""Clone an existing T24 runtime while preserving its mounts, environment and network."""

import copy

import hashlib

import http.client

import itertools

import json

import os

from pathlib import Path, PurePosixPath

import re

import socket

import sqlite3

import stat

import subprocess

import time

from urllib.parse import quote

INVENTORY_SCRIPT = """import pathlib,hashlib,json
r=pathlib.Path('/app/backend');excluded={'data','logs','__pycache__','.git','.pytest_cache','.venv','node_modules','work'}
print(json.dumps({str(p.relative_to(r)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(r.rglob('*')) if p.is_file() and not p.is_symlink() and not any(x in excluded or x.startswith('.') for x in p.relative_to(r).parts) and p.suffix not in {'.pyc','.db','.log','.pem','.key'}}))
"""

def need(value, code):
    if not value:
        raise RuntimeError(code)

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()

def run(args, code='RUNTIME_COMMAND_FAILED', timeout=90):
    result = subprocess.run(args, capture_output=True, timeout=timeout)
    need(result.returncode == 0 and len(result.stdout) <= 8388608, code)
    return result.stdout

def inspect(name):
    rows = json.loads(run(['docker', 'inspect', name], 'RUNTIME_INSPECT_FAILED'))
    need(isinstance(rows, list) and len(rows) == 1, 'SINGLE_RUNTIME_REQUIRED')
    return rows[0]

def missing_requested(result, name):
    if result.returncode != 1 or result.stdout.strip() != b'[]':
        return False
    pattern = rb'(?i:(?:error: |error response from daemon: )?no such (?:object|container): )' + re.escape(name.encode('utf-8')) + rb'\r?\n?'
    return re.fullmatch(pattern, result.stderr) is not None

def optional(name):
    result = subprocess.run(['docker', 'inspect', name], capture_output=True, timeout=30)
    if result.returncode:
        need(missing_requested(result, name), 'RUNTIME_LOOKUP_FAILED')
        return None
    rows = json.loads(result.stdout)
    need(isinstance(rows, list) and len(rows) == 1, 'SINGLE_OPTIONAL_RUNTIME_REQUIRED')
    return rows[0]

def networks(info):
    result = {}
    for name, value in info.get('NetworkSettings', {}).get('Networks', {}).items():
        need(not value.get('IPAMConfig'), 'STATIC_IP_REQUIRES_SEPARATE_REVIEW')
        result[name] = {key: copy.deepcopy(value[key]) for key in ('Aliases', 'Links', 'DriverOpts', 'GwPriority') if value.get(key) is not None}
        if 'Aliases' in result[name]:
            result[name]['Aliases'] = [v for v in result[name]['Aliases'] if v not in (info['Id'], info['Id'][:12])]
    need(bool(result), 'EXISTING_NETWORK_REQUIRED')
    return result

def sorted_mounts(info):
    return sorted(info['Mounts'], key=canonical)

def validate_writable_layer(info, lines):
    parents = set()
    for row in info['Mounts']:
        path = PurePosixPath(row['Destination'])
        parents.add(str(path))
        parents.update(map(str, path.parents))
    for line in lines:
        need(len(line) > 2 and line[:2] in ('A ', 'C ', 'D '), 'VALID_WRITABLE_LAYER_DIFF_REQUIRED')
        name = line[2:]
        need(name.startswith('/') and '..' not in PurePosixPath(name).parts, 'CANONICAL_WRITABLE_LAYER_PATH_REQUIRED')
        cache = '__pycache__' in PurePosixPath(name).parts and (name.startswith('/app/backend/') or re.match(r'^/usr/(?:local/)?lib/python3\.\d+/', name))
        benign = name in parents or name in {'/tmp', '/run', '/var', '/var/tmp', '/root', '/root/.cache'} or name.startswith(('/tmp/', '/var/tmp/', '/root/.cache/')) or cache
        need(benign, 'UNREVIEWED_WRITABLE_LAYER_STATE')

def inventory(container):
    return json.loads(run(['docker', 'exec', container, 'python', '-I', '-S', '-B', '-c', INVENTORY_SCRIPT], 'LIVE_INVENTORY_FAILED'))

def cold_inventory(image):
    need(re.fullmatch(r'sha256:[a-f0-9]{64}', image), 'IMMUTABLE_LOCAL_IMAGE_REQUIRED')
    return json.loads(run(['docker', 'run', '--rm', '--network=none', '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges', '--pids-limit=64', '--memory=256m', '--entrypoint=python', image, '-I', '-S', '-B', '-c', INVENTORY_SCRIPT], 'COLD_IMAGE_INVENTORY_FAILED'))

def clone_payload(original, image, source):
    need(re.fullmatch(r'sha256:[a-f0-9]{64}', image) and image != BASE_IMAGE and re.fullmatch('[a-f0-9]{40}', source), 'EXACT_NEW_IMAGE_AND_SOURCE_REQUIRED')
    need(original['HostConfig'].get('AutoRemove') is False, 'NO_AUTO_REMOVE_FOR_ROLLBACK_REQUIRED')
    config = copy.deepcopy(original['Config'])
    config['Image'] = image
    config['Hostname'] = ''
    config['Labels'] = {**(config.get('Labels') or {}), 't24.release.scope': SCOPE, 't24.release.source': source}
    config['HostConfig'] = copy.deepcopy(original['HostConfig'])
    config['NetworkingConfig'] = {'EndpointsConfig': networks(original)}
    return config

def configuration_equal(current, original, image, source, *, original_runtime=False, retained_name=None):
    expected = copy.deepcopy(original['Config'])
    if not original_runtime:
        expected['Image'] = image
        expected['Hostname'] = current['Id'][:12]
        expected['Labels'] = {**(expected.get('Labels') or {}), 't24.release.scope': SCOPE, 't24.release.source': source}
    need(current['Config'] == expected and current['Image'] == image, 'EXACT_RUNTIME_CONFIG_REQUIRED')
    host = dict(current['HostConfig'])
    # Docker29 serializes candidate OomKillDisable's explicit null default as false.
    if not original_runtime and 'OomKillDisable' in original['HostConfig'] and original['HostConfig']['OomKillDisable'] is None and host.get('OomKillDisable') is False:
        host['OomKillDisable'] = None
    need(host == original['HostConfig'], 'EXACT_HOST_SECURITY_AND_MOUNTS_REQUIRED')
    need(current['Config'].get('Env') == original['Config'].get('Env'), 'EXACT_RUNTIME_ENVIRONMENT_REQUIRED')
    need(sorted_mounts(current) == sorted_mounts(original), 'EXACT_ALL_MOUNT_FIELDS_REQUIRED')
    actual_networks, prior_networks = networks(current), networks(original)
    if original_runtime and retained_name:
        for row in actual_networks.values():
            if 'Aliases' in row:
                row['Aliases'] = ['t24-crm' if value == retained_name else value for value in row['Aliases']]
    need(actual_networks == prior_networks, 'EXACT_RUNTIME_NETWORK_ALIASES_REQUIRED')

class DockerConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect('/var/run/docker.sock')

def create_candidate(original, image, source):
    payload = clone_payload(original, image, source)
    connection = DockerConnection('localhost', timeout=45)
    try:
        connection.request('POST', '/containers/create?name=' + quote('t24-crm'), json.dumps(payload), {'Content-Type': 'application/json'})
        response = connection.getresponse()
        body = response.read(1048577)
        need(response.status == 201 and len(body) <= 1048576, 'CANDIDATE_CREATE_FAILED')
        ident = json.loads(body).get('Id', '')
        need(re.fullmatch('[a-f0-9]{64}', ident), 'EXACT_CANDIDATE_ID_REQUIRED')
        return ident
    finally:
        connection.close()

def ready(ident, timeout=65):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        result = subprocess.run(['docker', 'exec', ident, 'curl', '-q', '-fsS', '--max-time', '3', '--noproxy', '*', 'http://127.0.0.1:8000/ready'], capture_output=True, timeout=6)
        if result.returncode == 0:
            return
        need(inspect(ident)['State']['Running'], 'CANDIDATE_EXITED_BEFORE_READY')
        time.sleep(0.5)
    raise RuntimeError('CANDIDATE_READINESS_TIMEOUT')

SCOPE = "crm-call-record"

# Populated from the pinned manifest before inspecting or cloning a runtime.
BASE_IMAGE = None
