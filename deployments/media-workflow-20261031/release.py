"""Six empty image/planning tables; preserve the already-enabled worker exactly.

Exact reviewed source/version pins bind this release. Retained filesystem,
Docker, offline-environment and migration-container primitives are hash loaded by
the independently reviewed preflight. No private content or provider is accessed.
"""
import argparse
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import secrets
import selectors
import subprocess
from datetime import datetime, timezone
import socket
import sqlite3
import stat
import sys
import time
import types

H = lambda body: hashlib.sha256(body).hexdigest()
HOST = 'iZj6c4cj7edgnhdimts4l7Z'
SOURCE_SHA = 'c114242205af98c33a7c2ad435409e0c84ebd085'
FRONTEND = '33047aa593a2'
BASE_SOURCE = '6a7c0f7ee8d1b5eb9e24a5f0027cce24930d0667'
BASE_FRONTEND = '5af8aec0193c'
BASE_DEPLOYED_SHA = 'c4d66c9cd2ae3fc3cf18543138ce7f28c1764d31e28ed89668960ec8838cf35c'
BASE_ENABLED_SHA = 'b7b1f50e0d5b306bc46ea415f4a160ab8cbeccfae879d6604a6d8607b9f83f29'
ACTIVATION_FROM = '2026-10-30T19:42:04Z'
OLD_REVISION = 'eaf5a7b8c914'
NEW_REVISION = 'acd7c9d0e136'
SCOPE = 'media-workflow'
PREFLIGHT_SHA = 'a776108b6c877d8909fe0e41a5b0fb112d663acc9189e0db7f88883a97c39164'
APPLICATION_FREEZE_SHA = '7baccdca74c1d4abb31dd0bc4c0afc4c9ed8de893d55d2f9b2686e1ff0cea7ef'
MIGRATION = 'alembic/versions/fbc6b8c9d025_media_publication_images.py'
MIGRATIONS = ((MIGRATION, 'fbc6b8c9d025', OLD_REVISION),
    ('alembic/versions/acd7c9d0e136_media_content_plans.py', NEW_REVISION, 'fbc6b8c9d025'))
NEW_TABLES = frozenset({'media_publication_image_policies', 'media_publication_images', 'media_publication_image_selections',
    'media_publication_image_deliveries', 'media_content_plans', 'media_content_plan_tasks'})
NEW_INDEXES = frozenset({'ix_media_publication_images_customer_id', 'ix_media_publication_images_material_id',
    'ix_media_publication_image_selections_image_id', 'ix_media_publication_image_deliveries_image_id',
    'ix_media_content_plans_customer_id', 'ix_media_content_plan_tasks_plan_id'})
BACKEND_FILES = frozenset({'main.py', 'alembic/versions/fbc6b8c9d025_media_publication_images.py',
    'alembic/versions/acd7c9d0e136_media_content_plans.py', 'models/media_publication_images.py', 'models/media_planning.py',
    'routers/media_operations.py', 'routers/media_publication_images.py', 'routers/media_planning.py',
    'services/google_business.py', 'services/google_business_management.py', 'services/media_operations.py',
    'services/media_publication_images.py', 'services/media_planning.py'})
EXISTING_BACKEND_FILES = frozenset({'main.py', 'routers/media_operations.py', 'services/google_business.py',
    'services/google_business_management.py', 'services/media_operations.py'})
FRONTEND_FILES = frozenset('app/frontend/src/' + name for name in (
    'components/GoogleBusinessManagement.tsx', 'components/GoogleBusinessWorkspace.tsx', 'components/MediaTeamMaterials.tsx',
    'components/MediaPublicationImage.tsx', 'components/media-publication-image.css', 'components/media-team-materials.css',
    'lib/google-business-api.ts', 'lib/media-operations-api.ts', 'lib/media-publication-images.ts',
    'pages/MediaOperations.tsx', 'pages/media-operations.css', 'components/MediaPlanningWorkspace.tsx',
    'components/media-planning.css', 'lib/media-planning-api.ts'))
TEST_FILES = frozenset({'app/backend/tests/test_media_publication_images.py', 'app/backend/tests/test_media_publication_images_security.py',
    'app/backend/tests/test_media_planning.py', 'app/backend/tests/test_media_publication_images_middleware.py', 'app/frontend/tests/media-publication-images.test.mjs'})
SOURCE_FILES = frozenset('app/backend/' + name for name in BACKEND_FILES) | FRONTEND_FILES | TEST_FILES
DELIVERY_PREFIX = '/api/v1/media-publication-images/delivery/'
CALLBACK = '/api/v1/google-business/oauth/callback'


def need(ok, code):
    if not ok: raise RuntimeError(code)


def digest(value): return H(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())
def encoded(value): return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def pins_ready():
    need(isinstance(SOURCE_SHA, str) and bool(re.fullmatch('[a-f0-9]{40}', SOURCE_SHA)) and SOURCE_SHA != '0' * 40
         and isinstance(FRONTEND, str) and bool(re.fullmatch('[a-f0-9]{12}', FRONTEND)) and FRONTEND != '0' * 12
         and isinstance(APPLICATION_FREEZE_SHA, str) and bool(re.fullmatch('[a-f0-9]{64}', APPLICATION_FREEZE_SHA)) and APPLICATION_FREEZE_SHA != '0' * 64,
         'ACTUAL_REVIEWED_SOURCE_FRONTEND_AND_FREEZE_REQUIRED')


def protected_read(path, sha):
    row = path.lstat()
    need(path.resolve() == path and stat.S_ISREG(row.st_mode) and row.st_uid == 0 and row.st_nlink == 1 and stat.S_IMODE(row.st_mode) == 0o600, 'PROTECTED_TOOL_REQUIRED')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        opened = os.fstat(stream.fileno()); need((opened.st_dev, opened.st_ino) == (row.st_dev, row.st_ino), 'TOOL_OPEN_DRIFT'); body = stream.read(1048577)
    after = path.lstat()
    need(len(body) <= 1048576 and (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) and H(body) == sha, 'EXACT_REVIEWED_TOOL_BYTES_REQUIRED'); return body


def local_bytes(path, maximum=16 * 1024 ** 2):
    """Authoring inputs are regular canonical files, never linked private data."""
    path = Path(path); row = path.lstat()
    need(path.resolve() == path.absolute() and stat.S_ISREG(row.st_mode) and row.st_nlink == 1, 'REGULAR_CANONICAL_LOCAL_INPUT_REQUIRED')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        opened = os.fstat(stream.fileno()); need((opened.st_dev, opened.st_ino) == (row.st_dev, row.st_ino), 'LOCAL_INPUT_OPEN_DRIFT'); body = stream.read(maximum + 1)
    after = path.lstat()
    need(len(body) <= maximum and (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), 'LOCAL_INPUT_READ_DRIFT'); return body


def validate_summary(summary):
    need(summary['stage'] == 'MEDIA_WORKFLOW_PREFLIGHT_CAPTURED' and summary['source_sha'] == BASE_SOURCE and summary['frontend_version'] == BASE_FRONTEND and summary['schema_revision'] == OLD_REVISION and summary['table_count'] == 130, 'EXACT_ACTUAL_PREFLIGHT_SUMMARY_REQUIRED')
    need(summary['deployed_sha256'] == BASE_DEPLOYED_SHA and summary['scheduler_enabled_receipt_sha256'] == BASE_ENABLED_SHA and summary['scheduler_enabled'] is True and summary['scheduler_activation_from'] == ACTIVATION_FROM and summary['gbp_feature_enabled'] is True and summary['callback_logging_protection_retained'] is True and summary['image_delivery_prefix_absent'] is True, 'EXACT_EXISTING_ON_SUMMARY_REQUIRED')
    need(summary['private_boundary_verified'] is True and summary['host_docker_timestamp_parser_verified'] is True and all(summary[k] is False for k in ('credential_content_read', 'private_content_read', 'executed_business_writes')), 'READONLY_SUMMARY_REQUIRED')
    sha = summary['sha256']; need(re.fullmatch('[a-f0-9]{64}', sha) and summary['path'] == '/opt/t24-crm/releases/media-workflow-preflight-' + sha[:12] + '.json', 'EXACT_SERVER_PROOF_PATH_REQUIRED')


def compare(candidate, original, m):
    need(candidate['Config']['Env'] == original['Config']['Env'], 'EXACT_EXISTING_ENVIRONMENT_REQUIRED')
    need(candidate['Config'].get('Labels') == m.expected_labels(original), 'EXACT_RELEASE_LABELS_REQUIRED')
    for info in (original, candidate):
        need('OomKillDisable' in info['HostConfig'] and (info['HostConfig']['OomKillDisable'] is None or info['HostConfig']['OomKillDisable'] is False), 'EXACT_OOM_DEFAULT_REQUIRED')
        for endpoint in info.get('NetworkSettings', {}).get('Networks', {}).values():
            need(endpoint.get('IPAMConfig') is None or endpoint.get('IPAMConfig') == {}, 'EXPLICIT_IPAM_UNSUPPORTED')
    left, right = original['HostConfig']['OomKillDisable'], candidate['HostConfig']['OomKillDisable']
    need(left is right or left is None and right is False, 'UNPROVEN_OOM_DEFAULT_DIRECTION')
    normalized = copy.deepcopy(candidate)
    for key in ('Image', 'Hostname', 'Labels'): normalized['Config'][key] = copy.deepcopy(original['Config'].get(key))
    normalized['HostConfig']['OomKillDisable'] = left
    need(m.runtime(normalized)['config'] == m.runtime(original)['config'], 'EXACT_RUNTIME_CONFIGURATION_REQUIRED')


def sequence_boundary(before, current, *, forward=False, recovery=False):
    for value in (before, current):
        need(set(value) == {'pragma_sha256', 'sequence_exists', 'sequence_sha256', 'sequence_values'}, 'EXACT_SEQUENCE_VALUES_REQUIRED')
        rows = value['sequence_values']
        need(type(value['sequence_exists']) is bool and isinstance(rows, dict) and all(isinstance(k, str) and type(v) is int and v >= 0 for k, v in rows.items()), 'EXACT_VALID_SEQUENCE_MAP_REQUIRED')
        need(value['sequence_exists'] or not rows, 'SEQUENCE_EXISTENCE_MAP_CONFLICT')
        need(value['sequence_sha256'] == digest(sorted(rows.items())), 'SEQUENCE_PROOF_HASH_VALUES_CONFLICT')
    need(before['pragma_sha256'] == current['pragma_sha256'] and before['sequence_exists'] is current['sequence_exists'], 'EXACT_SCHEMA_PRAGMA_METADATA_REQUIRED')
    if recovery: return
    if forward:
        need(set(before['sequence_values']) == set(current['sequence_values']) and all(current['sequence_values'][k] >= v for k, v in before['sequence_values'].items()), 'SEQUENCE_COUNTER_REGRESSED_OR_KEYS_CHANGED')
    else: need(before == current, 'EXACT_OWN_SEQUENCE_METADATA_REQUIRED')


def snapshot(m, path): return json.loads(json.dumps(m.sql_snapshot(path)))
def evidence(rows): return {name: {'count': row['count'], 'rows_sha256': row['rows_sha256'], 'shape_sha256': digest({k: row[k] for k in ('columns', 'schema', 'indexes')})} for name, row in rows.items()}


def objects(path):
    con = sqlite3.connect('file:' + str(path) + '?mode=ro', uri=True)
    try:
        con.execute('PRAGMA query_only=ON'); con.execute('BEGIN')
        return {(row[0], row[1], row[2]): row[3] for row in con.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}
    finally: con.close()


def additive_objects(before, after):
    need(all(after.get(key) == value for key, value in before.items()), 'ORIGINAL_SCHEMA_OBJECT_CHANGED')
    need({key[:2] for key in set(after) - set(before)} == {('table', name) for name in NEW_TABLES} | {('index', name) for name in NEW_INDEXES}, 'EXACT_SIX_ADDITIVE_TABLES_AND_INDEXES_REQUIRED')


def compare_original(before, after, *, rows=True, empty=True):
    need(set(after) == set(before) | NEW_TABLES, 'EXACT_SIX_NEW_TABLES_REQUIRED')
    for name, old in before.items():
        current = after[name]
        need(all(current[key] == old[key] for key in ('columns', 'schema', 'indexes')), 'ORIGINAL_TABLE_SHAPE_CHANGED')
        if name == 'alembic_version':
            need(current['count'] == 1 and current['rows_sha256'] == H(json.dumps([NEW_REVISION]).encode()), 'EXACT_NEW_SCHEMA_HEAD_REQUIRED')
        elif rows: need((current['count'], current['rows_sha256']) == (old['count'], old['rows_sha256']), 'ORIGINAL_BUSINESS_ROWS_CHANGED')
    if empty: need(all(after[name]['count'] == 0 for name in NEW_TABLES), 'NEW_WORKFLOW_TABLES_MUST_START_EMPTY')


def migration_script():
    # Both migrations run in one explicit SQLite transaction. No intermediate
    # head is committed; a failure rolls back to the exact original revision.
    return f'''import importlib.util,sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
migrations={MIGRATIONS!r}
e=sa.create_engine('sqlite:///file:/app/backend/data/crm_prod.db?mode=rw&uri=true')
with e.connect() as c:
 c.exec_driver_sql('BEGIN IMMEDIATE')
 assert c.exec_driver_sql('SELECT version_num FROM alembic_version').fetchall()==[({OLD_REVISION!r},)]
 present=c.exec_driver_sql("SELECT 1 FROM sqlite_master WHERE name='sqlite_sequence' AND type='table'").fetchone() is not None
 sequence=c.exec_driver_sql('SELECT name,seq FROM sqlite_sequence ORDER BY name').fetchall() if present else []
 pragma=[c.exec_driver_sql('PRAGMA '+n).fetchone() for n in ('user_version','application_id')]
 head={OLD_REVISION!r}
 for path,revision,down in migrations:
  s=importlib.util.spec_from_file_location('reviewed_workflow_migration','/app/backend/'+path)
  m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
  assert m.revision==revision and m.down_revision==down==head
  with Operations.context(MigrationContext.configure(c)):m.upgrade()
  head=revision
 assert head=={NEW_REVISION!r}
 present_after=c.exec_driver_sql("SELECT 1 FROM sqlite_master WHERE name='sqlite_sequence' AND type='table'").fetchone() is not None
 assert present_after==present
 assert (c.exec_driver_sql('SELECT name,seq FROM sqlite_sequence ORDER BY name').fetchall() if present_after else [])==sequence
 assert [c.exec_driver_sql('PRAGMA '+n).fetchone() for n in ('user_version','application_id')]==pragma
 assert c.exec_driver_sql("UPDATE alembic_version SET version_num='{NEW_REVISION}' WHERE version_num='{OLD_REVISION}'").rowcount==1
 c.commit()
print('EXACT_WORKFLOW_ADDITIVE_MIGRATION_OK')
'''


def _tokens(blob):
    """Small strict Nginx scanner, retaining byte offsets and ignoring comments."""
    text = blob.decode('utf-8')
    token = re.compile(r'''\s+|\#[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[{};]|[^\s{};#"']+''')
    position, tokens = 0, []
    for item in token.finditer(text):
        need(item.start() == position, 'NGINX_SYNTAX_NOT_SUPPORTED')
        position = item.end()
        value = item.group()
        if not value.isspace() and not value.startswith('#'):
            tokens.append((value, item.start(), item.end()))
    need(position == len(text), 'NGINX_SYNTAX_NOT_SUPPORTED')
    return text, tokens


def nginx_blocks(blob):
    text, tokens = _tokens(blob)
    root = {'header': [], 'directives': [], 'parent': None}
    stack, result, directive = [], [root], []
    for value, start, end in tokens:
        if value == '{':
            need(bool(directive), 'NGINX_BLOCK_HEADER_REQUIRED')
            row = {'header': [item[0] for item in directive], 'start': directive[0][1], 'open': end,
                'parent': stack[-1] if stack else None, 'directives': []}
            result.append(row)
            stack.append(row)
            directive = []
        elif value == '}':
            need(bool(stack) and not directive, 'NGINX_BLOCK_STRUCTURE_REJECTED')
            row = stack.pop()
            row['close'], row['end'] = start, end
        elif value == ';':
            need(bool(directive), 'NGINX_EMPTY_DIRECTIVE_REJECTED')
            (stack[-1] if stack else root)['directives'].append([item[0] for item in directive])
            directive = []
        else:
            directive.append((value, start, end))
    need(not stack and not directive, 'NGINX_UNTERMINATED_STRUCTURE')
    return text, result



def image_delivery_nginx(blob):
    """Copy only a reviewed local API upstream; retain every original byte."""
    text, blocks = nginx_blocks(blob)
    need(DELIVERY_PREFIX not in text, 'EXISTING_DELIVERY_LOCATION_REQUIRES_REVIEW')
    servers = [row for row in blocks if row['header'] == ['server'] and
        any(item[0] == 'server_name' and 't24-crm.com' in item[1:] for item in row['directives']) and
        any(item[0] == 'listen' and any('443' == v or v.endswith(':443') for v in item[1:]) for item in row['directives'])]
    need(len(servers) == 1, 'EXACT_CRM_HTTPS_SERVER_REQUIRED'); server = servers[0]
    callbacks = [row for row in blocks if row['parent'] is server and row['header'] == ['location', '=', CALLBACK]]
    need(len(callbacks) == 1 and ['access_log', 'off'] in callbacks[0]['directives'] and
         ['error_log', '/dev/null', 'crit'] in callbacks[0]['directives'], 'EXISTING_CALLBACK_LOG_PROTECTION_REQUIRED')
    def prefix(row):
        h = row['header']
        if len(h) == 2 and h[0] == 'location' and h[1].startswith('/'): return h[1]
        if len(h) == 3 and h[:2] == ['location', '^~'] and h[2].startswith('/'): return h[2]
        return None
    candidates = [row for row in blocks if row['parent'] is server and prefix(row) and
        DELIVERY_PREFIX.startswith(prefix(row)) and any(d[0] == 'proxy_pass' for d in row['directives'])]
    need(bool(candidates), 'DIRECT_API_PROXY_LOCATION_REQUIRED')
    location = max(candidates, key=lambda row: len(prefix(row)))
    need(not any(row['parent'] is location for row in blocks), 'NESTED_PROXY_LOCATION_REQUIRES_REVIEW')
    allowed = {'proxy_pass', 'proxy_http_version', 'proxy_set_header', 'proxy_read_timeout', 'proxy_send_timeout',
        'proxy_connect_timeout', 'proxy_buffering', 'proxy_request_buffering'}
    copied = []
    for item in location['directives']:
        need(item[0] in allowed, 'NONSTANDARD_API_PROXY_REQUIRES_REVIEW')
        if item[0] == 'proxy_pass':
            need(len(item) == 2 and bool(re.fullmatch(r'http://127\.0\.0\.1:[0-9]{2,5}', item[1])), 'EXACT_LOOPBACK_UPSTREAM_REQUIRED')
        elif item[0] == 'proxy_set_header':
            need(len(item) == 3 and item[1] in {'Host','X-Real-IP','X-Forwarded-For','X-Forwarded-Proto','Upgrade','Connection'} and
                bool(re.fullmatch(r'\$[a-z_]+|"upgrade"|upgrade|""', item[2])), 'PROXY_HEADER_REQUIRES_REVIEW')
        elif item[0] == 'proxy_http_version': need(item == ['proxy_http_version','1.1'], 'EXACT_PROXY_HTTP_VERSION_REQUIRED')
        elif item[0] in {'proxy_buffering','proxy_request_buffering'}: need(len(item) == 2 and item[1] in {'on','off'}, 'PROXY_BUFFER_SETTING_REJECTED')
        else: need(len(item) == 2 and bool(re.fullmatch('[0-9]{1,5}[sm]?',item[1])), 'PROXY_TIMEOUT_REQUIRES_REVIEW')
        copied.append('        ' + ' '.join(item) + ';\n')
    need(sum(d[0] == 'proxy_pass' for d in location['directives']) == 1, 'EXACT_ONE_UPSTREAM_REQUIRED')
    added = ('    # T24 CRM leased image delivery: never log capability-token paths.\n'
        '    location ^~ ' + DELIVERY_PREFIX + ' {\n' + ''.join(copied) +
        '        access_log off;\n        error_log /dev/null crit;\n    }\n\n')
    position = text.rfind('\n', 0, location['start']) + 1
    need(not text[position:location['start']].strip(), 'INLINE_API_LOCATION_REQUIRES_REVIEW')
    updated = text[:position] + added + text[position:]
    need(updated.count(added) == 1 and updated.replace(added,'',1) == text, 'NONDELIVERY_NGINX_BYTES_CHANGED')
    return updated.encode(), added.encode()


def table_shape(con, name):
    need(name in NEW_TABLES, 'EXACT_NEW_TABLE_NAME_REQUIRED')
    return digest([con.execute('PRAGMA table_info(' + name + ')').fetchall(),
        con.execute('PRAGMA index_list(' + name + ')').fetchall(),
        con.execute('PRAGMA foreign_key_list(' + name + ')').fetchall(),
        con.execute('SELECT type,name,tbl_name,sql FROM sqlite_master WHERE tbl_name=? ORDER BY type,name',(name,)).fetchall()])


IMAGE_ROUTES = {( '/api/v1/media-publication-images' + path, method) for path,method in (
    ('/delivery-policy','GET'),('/delivery-policy','POST'),('','GET'),('/prepare','POST'),
    ('/requests/{request_id}','GET'),('/delivery/{token}.png','GET'),('/delivery/{token}.png','HEAD'),
    ('/{image_id}/preview','GET'),('/{image_id}/revoke','POST'))}
PLANNING_ROUTES = {('/api/v1/media-planning' + path, method) for path,method in (
    ('/calendar','GET'),('/summary','GET'),('/plans','GET'),('/plans','POST'),('/requests/{request_id}','GET'))}


NEW_TABLE_SHAPES = {'media_content_plan_tasks': 'f3f68ae79353ec3221e23fe86766ab68c98d32b72483095c0bafbd0dc3e0f347', 'media_content_plans': '0a913ff5cac7a6968c03556607c9dbb7e2372a4684e8be55b76f3e509c6a1745', 'media_publication_image_deliveries': 'f6ffdfb3abf7b1df4bf39fdfe0a433d9eb24c8eec93d8812c5bccdc1a0aaabfa', 'media_publication_image_policies': '95b167073f96afc5aacd770378a496731f709b858c80ad39113394da561c0ed3', 'media_publication_image_selections': '9896ff28282ab4feb3ab8dfb4967c8f01d3a6165237d2e57d2970cb6d7d2564f', 'media_publication_images': 'f7f33e87c01bccc8d0f76d196c897aa3d2d78e886c0495341de119e8583c241a'}


NGINX_LOG_METADATA = {
    '/var/log/nginx/access.log': (33,4,0o640),
    '/var/log/nginx/error.log': (33,4,0o640),
    '/var/log/nginx/t24-private-error.log': (33,0,0o600)}


def delivery_log_paths(active):
    _, blocks = nginx_blocks(active); paths = set(); target = []
    for row in blocks:
        if row['header'] == ['location','^~',DELIVERY_PREFIX]: target.append(row)
        for item in row['directives']:
            need(item[0] != 'debug_connection' and not (item[0] == 'error_log' and 'debug' in item[1:]), 'DEBUG_LOGGING_REQUIRES_REVIEW')
            if item[0] not in {'access_log','error_log'}: continue
            need(len(item) >= 2, 'EXPLICIT_LOG_DESTINATION_REQUIRED')
            if item[1] not in {'off','/dev/null'}:
                need(item[1] in NGINX_LOG_METADATA, 'UNKNOWN_LOG_DESTINATION_REQUIRES_REVIEW'); paths.add(item[1])
    need(len(target) == 1 and ['access_log','off'] in target[0]['directives'] and
        ['error_log','/dev/null','crit'] in target[0]['directives'], 'EXACT_DELIVERY_LOG_SUPPRESSION_REQUIRED')
    need(paths == set(NGINX_LOG_METADATA), 'EXACT_OBSERVED_LOG_PATH_SET_REQUIRED'); return sorted(paths)


def open_nginx_log(raw):
    path = Path(raw); need(raw in NGINX_LOG_METADATA and path.resolve() == path and path.parent == Path('/var/log/nginx'), 'EXACT_NGINX_LOG_PATH_REQUIRED')
    parent = path.parent.lstat(); need(stat.S_ISDIR(parent.st_mode) and parent.st_uid == 0 and parent.st_gid == 4 and stat.S_IMODE(parent.st_mode) == 0o755, 'NGINX_LOG_DIRECTORY_METADATA_REQUIRED')
    before = path.lstat(); uid,gid,mode = NGINX_LOG_METADATA[raw]
    need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and (before.st_uid,before.st_gid,stat.S_IMODE(before.st_mode)) == (uid,gid,mode), 'NGINX_LOG_METADATA_REQUIRED')
    fd = os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        opened = os.fstat(fd); need((before.st_dev,before.st_ino,before.st_uid,before.st_gid,before.st_mode,before.st_nlink) ==
            (opened.st_dev,opened.st_ino,opened.st_uid,opened.st_gid,opened.st_mode,opened.st_nlink), 'NGINX_LOG_OPEN_DRIFT')
        os.lseek(fd,opened.st_size,os.SEEK_SET); return fd,opened
    except BaseException: os.close(fd); raise


def bounded_output(argv, *, timeout=15, maximum=4*1024**2):
    # Bound the actual pipe read, not only a completed communicate() buffer.
    child = subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,close_fds=True)
    selector = selectors.DefaultSelector(); body = bytearray(); deadline=time.monotonic()+timeout
    try:
        selector.register(child.stdout,selectors.EVENT_READ)
        while selector.get_map():
            left=deadline-time.monotonic(); need(left>0,'BOUNDED_LOG_COMMAND_TIMEOUT')
            for key,_ in selector.select(left):
                chunk=os.read(key.fileobj.fileno(),min(65536,maximum+1-len(body)))
                if not chunk: selector.unregister(key.fileobj); continue
                body.extend(chunk); need(len(body)<=maximum,'BOUNDED_LOG_OUTPUT_REQUIRED')
        need(child.wait(timeout=max(.01,deadline-time.monotonic()))==0,'BOUNDED_LOG_COMMAND_FAILED'); return bytes(body)
    finally:
        selector.close()
        if child.poll() is None: child.kill(); child.wait(timeout=5)
        child.stdout.close()


def sentinel_headers(blob):
    need(isinstance(blob,bytes) and len(blob)<=65536,'BOUNDED_SENTINEL_HEADERS_REQUIRED')
    blocks=[b for b in re.split(rb'\r?\n\r?\n',blob) if b.lower().startswith(b'http/')]
    need(len(blocks)==1 and re.fullmatch(rb'HTTP/1\.[01] 404[^\r\n]*',blocks[0].splitlines()[0]), 'NONCAPABILITY_SENTINEL_MUST_BE_404')
    headers={}
    for line in blocks[0].splitlines()[1:]:
        need(b':' in line,'SENTINEL_HEADER_FORMAT_REQUIRED');key,value=line.split(b':',1);headers.setdefault(key.strip().lower(),[]).append(value.strip().lower())
    need(headers.get(b'referrer-policy')==[b'no-referrer'] and headers.get(b'x-content-type-options')==[b'nosniff'], 'SENTINEL_PRIVACY_HEADERS_REQUIRED')
    need(any(b'no-store' in {part.strip() for part in value.split(b',')} for value in headers.get(b'cache-control',[])) and bool(headers.get(b'strict-transport-security')) and bool(headers.get(b'content-security-policy')), 'SENTINEL_SECURITY_HEADERS_REQUIRED')
    return True


class Release:
    def __init__(self, args):
        pins_ready(); self.args = args
        body = protected_read(args.release / 'preflight.py', PREFLIGHT_SHA)
        self.pf = types.ModuleType('_publication_preflight'); self.pf.__file__ = str(args.release / 'preflight.py')
        exec(compile(body, self.pf.__file__, 'exec'), self.pf.__dict__)
        self.helper, self.m, self.base, self.safe = self.pf.dependencies(); m = self.m
        self.manifest = json.loads(m.read(args.release / 'manifest.json', args.manifest_sha256)); m.read(args.release / 'payload.tar.gz', args.payload_sha256)
        self.proof = json.loads(m.read(args.preflight, args.preflight_sha256)); self.validate()
        self.pins = json.loads(m.read(self.base.PRIVATE_PINS, self.base.PRIVATE_PINS_SHA))
        self.source, self.version = SOURCE_SHA, FRONTEND
        self.public = Path('/var/www/t24-crm-public/' + SCOPE + '-' + SOURCE_SHA[:12] + '-20261031')
        need(args.release == Path('/opt/t24-crm/releases/' + SCOPE + '-' + SOURCE_SHA[:12] + '-20261031'), 'EXACT_RELEASE_PATH_REQUIRED')
        m.SOURCE, m.SCOPE, m.BACKEND = SOURCE_SHA, SCOPE, set(BACKEND_FILES)
        m.BASELINE_FRONTEND, m.FRONTEND_VERSION = BASE_FRONTEND, FRONTEND
        m.PUBLIC, m.NGINX_SHA, m.STATIC_SHA = Path(self.proof['public_root']), self.proof['nginx_sha256'], self.proof['public_inventory_sha256']
        m.OLD_ID, m.BASE_IMAGE, m.OLD_CONFIG = (self.proof['crm'][k] for k in ('id', 'image', 'config'))
        m.public_root = lambda: self.public
        root_only = m.next_nginx
        m.next_nginx = lambda original: image_delivery_nginx(root_only(original))[0]
        self.old_name = 't24-crm-before-' + SCOPE + '-' + SOURCE_SHA[:12]
        self.candidate_name = 't24-crm-candidate-' + SCOPE + '-' + SOURCE_SHA[:12]
        self.offline_name = 't24-' + SCOPE + '-probe-' + SOURCE_SHA[:12]
        # Only in-memory parameters of the hash-reviewed retained migration
        # functions change; no helper source or server file is rewritten.
        self.base.OLD_REVISION, self.base.NEW_REVISION, self.base.MIGRATION = OLD_REVISION, NEW_REVISION, MIGRATION
        self.base.migration_script = migration_script

    def validate(self):
        p, v, a = self.proof, self.manifest, self.args
        need(p['stage'] == 'MEDIA_WORKFLOW_READONLY_PREFLIGHT' and p['host'] == HOST and p['source_sha'] == BASE_SOURCE and p['frontend_version'] == BASE_FRONTEND and p['schema_revision'] == OLD_REVISION, 'EXACT_ENABLED_BASELINE_REQUIRED')
        need(p['deployed_sha256'] == self.pf.DEPLOYED_SHA and p['scheduler_enabled_receipt_sha256'] == self.pf.ENABLED_SHA and p['crm']['id'] == self.pf.ORIGINAL_ID and p['crm']['image'] == self.pf.IMAGE, 'EXACT_ON_CONTAINER_RECEIPTS_REQUIRED')
        need(p['scheduler_enabled'] is True and p['scheduler_activation_from'] == self.pf.ACTIVATION_FROM and p['host_docker_timestamp_parser_verified'] is True and p['callback_logging_protection_retained'] is True and len(p['rows']) == 130 and p['image_delivery_prefix_absent'] is True, 'EXACT_ON_PREFLIGHT_BOUNDARIES_REQUIRED')
        need(all(p[k] is False for k in ('provider_requests', 'business_writes', 'private_content_read', 'credential_content_read', 'container_or_configuration_changed')), 'READONLY_PREFLIGHT_REQUIRED')
        need(v['source_sha'] == SOURCE_SHA and v['frontend_version'] == FRONTEND and v['baseline_source_sha'] == BASE_SOURCE and v['baseline_frontend_version'] == BASE_FRONTEND, 'EXACT_SOURCE_REQUIRED')
        need(v['schema_revision'] == NEW_REVISION and v['old_schema_revision'] == OLD_REVISION and v['additive_tables'] == sorted(NEW_TABLES) and v['database_migration'] is True and v['production_seed_rows'] is False and v['credentials_included'] is False and v['image_delivery_policy_enabled'] is False and v['runtime_environment_changed'] is False, 'EXACT_EMPTY_ADDITIVE_SCOPE_REQUIRED')
        need(set(v['changed_source_files']) == SOURCE_FILES and len(v['changed_source_files']) == len(SOURCE_FILES) and v['application_freeze_sha256'] == APPLICATION_FREEZE_SHA, 'EXACT_APPLICATION_DELTA_REQUIRED')
        need(v['preflight_sha256'] == a.preflight_sha256 and v['payload_sha256'] == a.payload_sha256, 'EXACT_PAYLOAD_PROOF_REQUIRED')
        need(set(v['backend_before']) == set(v['backend_after']) == BACKEND_FILES and v['backend_before'] == p['backend_changed_before'], 'EXACT_RUNTIME_BACKEND_SCOPE_REQUIRED')
        need(all(bool(re.fullmatch('[a-f0-9]{64}', value or '')) if name in EXISTING_BACKEND_FILES else value is None for name, value in v['backend_before'].items()), 'EXACT_EXISTING_BACKEND_HASHES_REQUIRED')
        need({n[8:] for n in v['files'] if n.startswith('backend/')} == BACKEND_FILES and all(v['files']['backend/' + n] == v['backend_after'][n] for n in BACKEND_FILES), 'EXACT_RUNTIME_PATCHES_REQUIRED')
        need(all(re.fullmatch('[a-f0-9]{64}', value) for value in [*v['files'].values(), *v['backend_after'].values()]), 'EXACT_MEMBER_HASHES_REQUIRED')
        need({'static/index.html', 'static/app-version.json'} <= set(v['files']) and all(n in {'backend/' + name for name in BACKEND_FILES} or n.startswith('static/') and self.m.static_path(n[7:]) for n in v['files']), 'EXACT_STATIC_PAYLOAD_REQUIRED')

    def record(self, name, value):
        sha = self.m.write(self.args.release / name, value)
        fd = os.open(self.args.release, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try: os.fsync(fd)
        finally: os.close(fd)
        return sha

    def private_boundary(self):
        need(self.safe.safe_private_boundary(self.m, self.pins) == self.proof['private_boundary'], 'PRIVATE_RUNTIME_METADATA_DRIFT')

    def nginx(self, updated=False):
        body = self.m.NGINX.read_bytes(); active = self.m.run(['nginx', '-T'], 'ACTIVE_NGINX_PARSE_FAILED'); observed_active_sha=H(active)
        old = os.fsencode(self.proof['public_root']); new = os.fsencode(str(self.public))
        if updated:
            original = self.m.read(self.args.release / 'nginx-before.conf', self.proof['nginx_sha256'])
            _, added = image_delivery_nginx(original)
            need(body.count(added) == active.count(added) == 1 and body.count(new) == active.count(new) == 1, 'EXACT_DELIVERY_PREFIX_AND_ROOT_REQUIRED')
            body = body.replace(added, b'', 1).replace(new, old, 1)
            active = active.replace(added, b'', 1).replace(new, old, 1)
        need(H(body) == self.proof['nginx_sha256'] and H(active) == self.proof['active_nginx_config_sha256'], 'CALLBACK_OR_OTHER_NGINX_CONFIGURATION_DRIFT')
        return observed_active_sha

    def metadata(self, path): return self.helper.db_metadata(path)
    def rows(self, path=None): return snapshot(self.m, path or self.m.BUSINESS)
    def source_boundary(self, info, inventory): return self.base.Release.source_overlay_boundary(self, info, inventory)

    def revision(self):
        con = sqlite3.connect('file:' + str(self.m.BUSINESS) + '?mode=ro', uri=True)
        try:
            con.execute('PRAGMA query_only=ON'); rows = con.execute('SELECT version_num FROM alembic_version').fetchall()
            need(len(rows) == 1 and rows[0][0] in {OLD_REVISION, NEW_REVISION}, 'EXACT_KNOWN_SCHEMA_REQUIRED'); return rows[0][0]
        finally: con.close()

    def protections(self, *, updated=False, head=OLD_REVISION, recovery=False, schema=None):
        m, p = self.m, self.proof
        self.private_boundary()
        need(m.credential_boundary() == p['credential_boundary'] and self.safe.protected_metadata(self.safe.GBP_ENV) == p['google_credential_metadata'], 'CREDENTIAL_METADATA_DRIFT')
        row = m.BUSINESS.stat(); need([row.st_dev, row.st_ino] == p['database_identity'], 'DATABASE_INODE_DRIFT')
        sequence_boundary(p['database_metadata'], self.metadata(m.BUSINESS), forward=not recovery, recovery=recovery)
        need(m.schema_signature(m.BUSINESS, head) == (p['schema_sha256'] if head == OLD_REVISION else schema), 'EXACT_SCHEMA_STRUCTURE_DRIFT')
        need(digest(m.tree(m.PUBLIC)) == p['public_inventory_sha256'], 'ORIGINAL_STATIC_DRIFT'); self.nginx(updated)

    def current(self):
        m, p = self.m, self.proof; self.protections(); old = m.inspect('t24-crm')
        need(old['State']['Running'] is True and m.runtime(old) == p['crm'], 'CURRENT_RUNTIME_DRIFT')
        self.pf.google_environment(old); m.verify_secret_mount(old); m.verify_production_worker_enabled(old); m.retained().require_safe_original_restart(old)
        inventory = m.inventory(old['Id']); need(digest(inventory) == p['backend_inventory_sha256'] and len(inventory) == p['backend_file_count'], 'CURRENT_SOURCE_DRIFT')
        need(digest(sorted(old['Config']['Env'])) == p['environment_sha256'] and evidence(self.rows()) == p['rows'], 'CURRENT_ENVIRONMENT_OR_ROWS_DRIFT')
        m.ready(old['Id']); return old, inventory

    def image(self):
        m = self.m; need(m.image_id(m.BASE_IMAGE) == m.BASE_IMAGE, 'EXACT_LOCAL_BASE_IMAGE_REQUIRED')
        base = 't24-crm:' + SCOPE + '-base-' + SOURCE_SHA[:12]; prior = m.image_id(base)
        need(prior is None or prior == m.BASE_IMAGE, 'BASE_TAG_DRIFT')
        if prior is None: m.run(['docker', 'image', 'tag', m.BASE_IMAGE, base], 'BASE_TAG_FAILED')
        m.write(self.args.release / 'Dockerfile', ('FROM ' + base + '\n' + ''.join('COPY backend/' + n + ' /app/backend/' + n + '\n' for n in sorted(BACKEND_FILES))).encode())
        m.write(self.args.release / '.dockerignore', m.dockerignore()); tag = 't24-crm:' + SCOPE + '-' + SOURCE_SHA[:12]
        m.run(['docker', 'build', '--network=none', '--pull=false', '-t', tag, str(self.args.release)], 'PATCH_BUILD_FAILED', 300)
        image = m.image_id(tag); need(m.image_id(base) == m.BASE_IMAGE and re.fullmatch('sha256:[a-f0-9]{64}', image or ''), 'EXACT_BUILT_IMAGE_REQUIRED'); return image

    def offline_args(self, data, image):
        command = self.base.Release.offline_args(self, data, image)
        # The live cutoff remains byte-exact in the production clone. The
        # isolated worker has no inherited activation timestamp at all.
        command[-1:-1] = ['-e', 'T24_GBP_SCHEDULER_ACTIVATION_FROM=']
        return command
    def migration_identity(self, data): return self.base.Release.migration_identity(self, data)
    def settle_migration(self, data, *, required=False): return self.base.Release.settle_migration(self, data, required=required)
    def run_migration(self, data, image, *, retry=False):
        # The retained writer fsyncs file bytes. Add the directory barrier only
        # for this exact migration identity, before the retained helper can
        # start the created container. No frozen helper file is changed.
        _, identity_path = self.migration_identity(data); original_write = self.m.write
        def durable_identity_write(path, value):
            sha = original_write(path, value)
            if path == identity_path:
                fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try: os.fsync(fd)
                finally: os.close(fd)
            return sha
        self.m.write = durable_identity_write
        try: return self.base.Release.run_migration(self, data, image, retry=retry)
        finally: self.m.write = original_write

    def new_schema(self, path, *, empty=True):
        con = sqlite3.connect('file:' + str(path) + '?mode=ro', uri=True)
        try:
            con.execute('PRAGMA query_only=ON'); con.execute('BEGIN')
            need(con.execute('SELECT version_num FROM alembic_version').fetchall() == [(NEW_REVISION,)] and con.execute('PRAGMA quick_check').fetchall() == [('ok',)], 'EXACT_NEW_HEAD_AND_INTEGRITY_REQUIRED')
            need({name: table_shape(con, name) for name in NEW_TABLES} == NEW_TABLE_SHAPES, 'EXACT_NEW_TABLE_SHAPES_REQUIRED')
            if empty: need(all(con.execute('SELECT COUNT(*) FROM ' + name).fetchone()[0] == 0 for name in NEW_TABLES), 'NEW_WORKFLOW_TABLES_MUST_START_EMPTY')
        finally: con.close()
        return self.m.schema_signature(path, NEW_REVISION)

    def route_probe(self):
        expected = {'/api/v1/google-business': ('routers.google_business', self.base.GBP_ROUTES | {('/api/v1/google-business/bindings/{binding_id}/review', 'GET')}),
            '/api/v1/media-operations': ('routers.media_operations', self.base.MEDIA_ROUTES),
            '/api/v1/media-publication-images': ('routers.media_publication_images', IMAGE_ROUTES),
            '/api/v1/media-planning': ('routers.media_planning', PLANNING_ROUTES)}
        return ("import socket\ndef blocked(*a,**k):raise AssertionError('NO_PROVIDER_NETWORK')\nsocket.socket.connect=blocked\nfrom main import app\nimport fastapi.routing\nexpected=" + repr(expected) + "\nschema=app.openapi()\ncontexts=list(fastapi.routing.iter_route_contexts(app.routes)) if hasattr(fastapi.routing,'iter_route_contexts') else app.routes\nfor prefix,(module,methods) in expected.items():\n hidden={(prefix+'/delivery/{token}.png',m) for m in ('GET','HEAD')} if prefix=='/api/v1/media-publication-images' else set()\n actual={(p,m.upper()) for p,v in schema['paths'].items() if p.startswith(prefix) for m in v if m.lower() in {'get','post','put','patch','delete','head','options','trace'}}\n assert actual==methods-hidden\n registered=[(x.path,m,getattr(getattr(x,'endpoint',None),'__module__',''),getattr(x,'include_in_schema',True)) for x in contexts if getattr(x,'path','').startswith(prefix) for m in (getattr(x,'methods',set()) or set())]\n assert len(registered)==len(methods) and {(p,m) for p,m,_,_ in registered}==methods and all(mod==module for _,_,mod,_ in registered)\n assert all(visible is False for p,m,_,visible in registered if (p,m) in hidden)\nprint('EXACT_WORKFLOW_MEDIA_GOOGLE_ROUTES')\n")

    def active_probe(self):
        return ("import socket\ndef blocked(*a,**k):raise AssertionError('NO_PROVIDER_NETWORK')\nsocket.socket.connect=blocked\nfrom services.google_business_provider import enabled,settings\nfrom services.google_business_scheduler import enabled as worker,activation_from\nassert enabled() is True and not settings()[1] and worker() is True\nassert activation_from().isoformat()==" + repr(self.pf.ACTIVATION_FROM.replace('Z', '+00:00')) + "\nprint('EXACT_EXISTING_ON_WORKER_CUTOFF_NO_NETWORK')\n")

    def prepare(self):
        self.helper.docker_timestamp_probe(); m, a = self.m, self.args; old, before = self.current()
        need({p.name for p in a.release.iterdir()} == {'release.py', 'preflight.py', 'manifest.json', 'payload.tar.gz'}, 'FRESH_STAGING_REQUIRED')
        m.extract(a.release, self.manifest); expected = {**before, **self.manifest['backend_after']}
        original_sha = self.record('original-container.json', old); before_sha = self.record('backend-original-inventory.json', before); after_sha = self.record('backend-candidate-inventory.json', expected)
        image = self.image(); data = a.release / 'probe-data'; data.mkdir(mode=0o700); (a.release / 'probe-logs').mkdir(mode=0o700)
        m.backup(m.BUSINESS, data / 'crm_prod.db'); rows = self.rows(data / 'crm_prod.db'); metadata = self.metadata(data / 'crm_prod.db')
        need(evidence(rows) == self.proof['rows'] and m.schema_signature(data / 'crm_prod.db', OLD_REVISION) == self.proof['schema_sha256'], 'ISOLATED_COPY_DRIFT')
        sequence_boundary(self.proof['database_metadata'], metadata, forward=True); before_objects = objects(data / 'crm_prod.db')
        self.run_migration(data, image); schema = self.new_schema(data / 'crm_prod.db'); migrated = self.rows(data / 'crm_prod.db')
        additive_objects(before_objects, objects(data / 'crm_prod.db')); compare_original(rows, migrated); sequence_boundary(metadata, self.metadata(data / 'crm_prod.db'))
        need(not m.inspect_optional(self.offline_name), 'FRESH_OFFLINE_PROBE_NAME_REQUIRED')
        command = self.offline_args(data, image); command[2:2] = ['--name', self.offline_name, '-d']; m.run(command, 'OFFLINE_START_FAILED')
        try:
            m.ready(self.offline_name); self.base.verify_disabled_environment(m.inspect(self.offline_name)); need(m.inventory(self.offline_name) == expected, 'OFFLINE_SOURCE_DRIFT')
            checks = [("import sys;assert sys.version_info[:2]==(3,10);print('EXACT_PYTHON310')", b'EXACT_PYTHON310'), (self.route_probe(), b'EXACT_WORKFLOW_MEDIA_GOOGLE_ROUTES'), (self.base.gbp_disabled_probe(), b'EXACT_GBP_DISABLED_UNCONFIGURED_NO_NETWORK')]
            for code, marker in checks: need(marker in m.run(['docker', 'exec', self.offline_name, 'python', '-B', '-c', code], 'OFFLINE_PROBE_FAILED'), 'EXACT_OFFLINE_PROBE_MARKER_REQUIRED')
        finally: m.run(['docker', 'stop', '--time', '20', self.offline_name], 'OFFLINE_STOP_FAILED', 45)
        need(self.rows(data / 'crm_prod.db') == migrated and self.new_schema(data / 'crm_prod.db') == schema and self.metadata(data / 'crm_prod.db') == metadata, 'OFFLINE_STARTUP_CHANGED_DATABASE')
        root, static = m.stage_public(a.release, self.manifest); next_sha = H(m.next_nginx(m.NGINX.read_bytes())); self.current()
        result = {'stage': 'MEDIA_WORKFLOW_PREPARED_OFFLINE_VERIFIED', 'source_sha': SOURCE_SHA, 'frontend_version': FRONTEND, 'old_schema_revision': OLD_REVISION, 'schema_revision': NEW_REVISION, 'schema_after_sha256': schema, 'old_crm': m.runtime(old), 'candidate_image': image, 'preflight_sha256': a.preflight_sha256, 'manifest_sha256': a.manifest_sha256, 'payload_sha256': a.payload_sha256, 'original_container_sha256': original_sha, 'original_inventory_sha256': before_sha, 'candidate_inventory_sha256': after_sha, 'public_root': str(root), 'public_inventory_sha256': static, 'nginx_next_sha256': next_sha, 'original_table_count': 130, 'new_table_count': 136, 'additive_tables': sorted(NEW_TABLES), 'image_delivery_policy_off_empty': True, 'delivery_prefix_logging_protection_prepared': True, 'offline_additive_only': True, 'offline_original_rows_unchanged': True, 'offline_new_table_empty': True, 'offline_own_metadata_exact': True, 'actual_python310_verified': True, 'exact_media_google_routes': True, 'offline_network_none': True, 'offline_credentials_absent': True, 'offline_workers_off': True, 'scheduler_on_and_cutoff_preserved': True, 'host_docker_timestamp_parser_verified': True, 'provider_requests': False, 'production_database_migrated': False, 'sequence_written_by_tool': False}
        sha = self.record('prepared.json', result); return {**result, 'receipt_sha256': sha}

    def reviewed(self):
        m, a = self.m, self.args; need(re.fullmatch('[a-f0-9]{64}', a.review_sha256 or ''), 'PREPARED_INDEPENDENT_REVIEW_REQUIRED')
        r = json.loads(m.read(a.release / 'prepared.json', a.review_sha256))
        need(r['stage'] == 'MEDIA_WORKFLOW_PREPARED_OFFLINE_VERIFIED' and r['source_sha'] == SOURCE_SHA and r['frontend_version'] == FRONTEND and r['schema_revision'] == NEW_REVISION and r['old_schema_revision'] == OLD_REVISION, 'EXACT_PREPARED_SCOPE_REQUIRED')
        need(r['manifest_sha256'] == a.manifest_sha256 and r['payload_sha256'] == a.payload_sha256 and r['preflight_sha256'] == a.preflight_sha256 and r['original_table_count'] == 130 and r['new_table_count'] == 136, 'EXACT_PREPARED_IDENTITIES_REQUIRED')
        need(r['additive_tables'] == sorted(NEW_TABLES) and r['image_delivery_policy_off_empty'] is True and r['delivery_prefix_logging_protection_prepared'] is True, 'EXACT_IMAGE_POLICY_AND_DELIVERY_PREFIX_REVIEW_REQUIRED')
        need(all(r[k] is True for k in ('offline_additive_only', 'offline_original_rows_unchanged', 'offline_new_table_empty', 'offline_own_metadata_exact', 'actual_python310_verified', 'exact_media_google_routes', 'offline_network_none', 'offline_credentials_absent', 'offline_workers_off', 'scheduler_on_and_cutoff_preserved', 'host_docker_timestamp_parser_verified')) and all(r[k] is False for k in ('provider_requests', 'production_database_migrated', 'sequence_written_by_tool')), 'EXACT_OFFLINE_ACCEPTANCE_REQUIRED')
        old = json.loads(m.read(a.release / 'original-container.json', r['original_container_sha256'])); before = json.loads(m.read(a.release / 'backend-original-inventory.json', r['original_inventory_sha256'])); expected = json.loads(m.read(a.release / 'backend-candidate-inventory.json', r['candidate_inventory_sha256']))
        need(m.runtime(old) == r['old_crm'] == self.proof['crm'] and digest(before) == self.proof['backend_inventory_sha256'] and expected == {**before, **self.manifest['backend_after']}, 'PREPARED_BASELINE_DRIFT')
        need(m.image_id(r['candidate_image']) == r['candidate_image'] and m.verify_public(self.public, self.manifest) == r['public_inventory_sha256'], 'PREPARED_IMAGE_STATIC_DRIFT')
        return r, old, before, expected

    def state(self, r, old):
        value = json.loads(self.m.read(self.args.release / 'candidate-created.json'))
        need(value == {'source_sha': SOURCE_SHA, 'candidate_id': value['candidate_id'], 'candidate_image': r['candidate_image'], 'original_id': old['Id'], 'review_sha256': self.args.review_sha256} and re.fullmatch('[a-f0-9]{64}', value['candidate_id']) and value['candidate_id'] != old['Id'], 'EXACT_DURABLE_CANDIDATE_ID_REQUIRED'); return value

    def identities(self, state, old):
        m = self.m; retained = m.inspect(old['Id']); candidate = m.inspect(state['candidate_id'])
        need(retained['Image'] == old['Image'] and m.runtime(retained)['config'] == m.runtime(old)['config'] and retained['Name'] in {'/t24-crm', '/' + self.old_name}, 'RETAINED_ORIGINAL_DRIFT')
        need(candidate['Id'] == state['candidate_id'] and candidate['Image'] == state['candidate_image'] and candidate['Name'] in {'/t24-crm', '/' + self.candidate_name}, 'OWNED_CANDIDATE_ID_IMAGE_ROLE_REQUIRED')
        active = m.inspect_optional('t24-crm'); need(not active or active['Id'] in {old['Id'], candidate['Id']}, 'UNKNOWN_PRIMARY_CONTAINER')
        for name, identity in ((self.old_name, old['Id']), (self.candidate_name, candidate['Id'])):
            found = m.inspect_optional(name); need(not found or found['Id'] == identity, 'UNKNOWN_RESERVED_CONTAINER')
        return retained, candidate

    def fresh(self, r, old, before, expected, state, *, migrated=False, updated=False, live=False, baseline=None, recovery=False):
        head = NEW_REVISION if migrated else OLD_REVISION
        self.protections(updated=updated, head=head, recovery=recovery, schema=r['schema_after_sha256'])
        retained, candidate = self.identities(state, old); compare(candidate, old, self.m); self.pf.google_environment(candidate)
        if not recovery: need(self.m.runtime(retained) == self.m.runtime(old), 'ORIGINAL_RESTART_PROVENANCE_DRIFT')
        if migrated: need(retained['State']['Running'] is False, 'OLD_WORKER_MUST_REMAIN_STOPPED_AFTER_MIGRATION')
        self.m.verify_secret_mount(candidate); self.m.verify_production_worker_enabled(candidate)
        self.source_boundary(retained, before); self.source_boundary(candidate, expected)
        if live:
            need(candidate['State']['Running'] is True and retained['State']['Running'] is False and self.m.inspect('t24-crm')['Id'] == candidate['Id'], 'EXACT_SINGLE_LIVE_CANDIDATE_REQUIRED'); self.helper.validation_window(candidate)
        else: need(candidate['State']['Running'] is False, 'PRESTART_CANDIDATE_STOPPED_REQUIRED')
        need(type(candidate['RestartCount']) is int and candidate['RestartCount'] == 0, 'CANDIDATE_RESTARTED')
        if migrated:
            need(self.new_schema(self.m.BUSINESS, empty=not recovery) == r['schema_after_sha256'], 'NEW_SCHEMA_DRIFT')
            if baseline is not None: compare_original(baseline, self.rows(), rows=not recovery, empty=not recovery)
        elif not recovery: need(evidence(self.rows()) == self.proof['rows'], 'OLD_ROWS_CHANGED_BEFORE_MIGRATION')
        return retained, candidate

    def delivery_sentinel(self, candidate_id):
        # This token has no lease/image/policy and is never returned as a URL.
        # Only a single pass/fail over appended logs leaves this process.
        need(bool(re.fullmatch('[a-f0-9]{64}',candidate_id)), 'EXACT_SENTINEL_CANDIDATE_REQUIRED')
        known=self.m.inspect(candidate_id)
        need(known['Id']==candidate_id and known['State']['Running'] is True and self.m.inspect('t24-crm')['Id']==candidate_id, 'SENTINEL_KNOWN_LIVE_CANDIDATE_REQUIRED')
        expected_active=self.nginx(updated=True); active=self.m.run(['nginx','-T'],'ACTIVE_NGINX_PARSE_FAILED')
        need(H(active)==expected_active,'SENTINEL_EFFECTIVE_NGINX_CHANGED')
        paths=delivery_log_paths(active)
        token='t24_noncapability_probe_'+secrets.token_hex(16); need(len(token)!=43,'NONCAPABILITY_MARKER_FORMAT_REQUIRED')
        since=datetime.now(timezone.utc).isoformat(); opened={}
        try:
            for raw in paths: opened[raw]=open_nginx_log(raw)
            for method in ('GET','HEAD'):
                args=['curl','-q','--silent','--show-error','--noproxy','*','--http1.1','--header','Connection: close',
                    '--max-time','10','--max-redirs','0','--resolve','t24-crm.com:443:127.0.0.1','-D','-','-o','/dev/null']
                if method=='HEAD':args.append('--head')
                args.append('https://t24-crm.com'+DELIVERY_PREFIX+token+'.png')
                sentinel_headers(self.m.run(args,'NONCAPABILITY_SENTINEL_REQUEST_FAILED',15))
            time.sleep(.25)
            for raw,(fd,before) in opened.items():
                after=os.stat(raw,follow_symlinks=False)
                need((before.st_dev,before.st_ino,before.st_uid,before.st_gid,before.st_mode,before.st_nlink)==
                    (after.st_dev,after.st_ino,after.st_uid,after.st_gid,after.st_mode,after.st_nlink) and after.st_size>=before.st_size,'SENTINEL_LOG_ROTATION_OR_METADATA_DRIFT')
                delta=os.read(fd,4*1024**2+1)
                need(len(delta)<=4*1024**2 and token.encode() not in delta,'SENTINEL_PATH_PRESENT_IN_NGINX_LOG')
            logs=bounded_output(['docker','logs','--since',since,candidate_id])
            need(token.encode() not in logs,'SENTINEL_PATH_PRESENT_IN_CONTAINER_LOG')
            need(self.nginx(updated=True)==expected_active,'SENTINEL_EFFECTIVE_NGINX_CHANGED')
            return {'delivery_prefix_logging_protected':True,'noncapability_get_and_head_404_verified':True,
                'effective_nginx_log_paths_checked':True,'bounded_nginx_append_scan_verified':True,
                'bounded_candidate_stdout_stderr_scan_verified':True,'no_raw_logs_exported':True,
                'sentinel_loopback_https_only':True,'sentinel_created_image_or_lease':False,
                'sentinel_google_or_provider_request':False,'sentinel_active_nginx_sha256':H(active)}
        finally:
            for fd,_ in opened.values():os.close(fd)

    def public_check(self, candidate_id):
        prefix = ['curl', '-q', '--silent', '--show-error', '--fail', '--noproxy', '*', '--resolve', 't24-crm.com:443:127.0.0.1', '--max-time', '3']
        value = json.loads(self.m.run([*prefix, 'https://t24-crm.com/app-version.json'], 'PUBLIC_VERSION_FAILED', 5)); need(value.get('version') == FRONTEND, 'PUBLIC_VERSION_DRIFT')
        value = json.loads(self.m.run([*prefix, 'https://t24-crm.com/ready'], 'PUBLIC_READY_FAILED', 5)); need(value.get('status') == 'ready', 'PUBLIC_READY_DRIFT')
        return self.delivery_sentinel(candidate_id)

    def activate(self):
        m, a = self.m, self.args; r, old, before, expected = self.reviewed(); self.current()
        need(not (a.release / 'activation-started.json').exists() and not m.inspect_optional(self.old_name) and not m.inspect_optional(self.candidate_name), 'FRESH_SWITCH_REQUIRED')
        original_nginx = m.NGINX.read_bytes(); need(H(m.next_nginx(original_nginx)) == r['nginx_next_sha256'], 'REVIEWED_NGINX_REQUIRED')
        self.record('nginx-before.conf', original_nginx); self.record('activation-started.json', {'source_sha': SOURCE_SHA, 'review_sha256': a.review_sha256, 'original_id': old['Id'], 'candidate_image': r['candidate_image']})
        status, body = m.retained().docker_request('POST', '/containers/create?name=' + self.candidate_name, m.clone_config(r['candidate_image'], old)); need(status == 201, 'CANDIDATE_CREATE_FAILED')
        identity = json.loads(body)['Id']; need(re.fullmatch('[a-f0-9]{64}', identity), 'EXACT_CREATED_ID_REQUIRED')
        self.record('candidate-created.json', {'source_sha': SOURCE_SHA, 'candidate_id': identity, 'candidate_image': r['candidate_image'], 'original_id': old['Id'], 'review_sha256': a.review_sha256}); state = self.state(r, old)
        try:
            _, candidate = self.fresh(r, old, before, expected, state)
            need(candidate['State']['Status'] == 'created' and candidate['State'].get('StartedAt') in {'', '0001-01-01T00:00:00Z', '0001-01-01T00:00:00.000000000Z'}, 'NEVER_STARTED_CANDIDATE_REQUIRED')
            m.run(['docker', 'stop', '--time', '30', old['Id']], 'ORIGINAL_STOP_FAILED', 60)
            retained, _ = self.fresh(r, old, before, expected, state); need(retained['State']['Running'] is False, 'ORIGINAL_STOPPED_REQUIRED')
            baseline = self.rows(); need(evidence(baseline) == self.proof['rows'], 'STOPPED_ORIGINAL_ROWS_DRIFT')
            baseline_sha = self.record('production-before-rows.json', baseline)
            self.record('production-baseline-identity.json', {'source_sha': SOURCE_SHA, 'original_id': old['Id'], 'candidate_id': identity, 'review_sha256': a.review_sha256, 'rows_sha256': baseline_sha})
            self.run_migration(m.BUSINESS.parent, r['candidate_image'])
            compare_original(baseline, self.rows()); need(self.new_schema(m.BUSINESS) == r['schema_after_sha256'], 'PRODUCTION_ADDITIVE_SCHEMA_DRIFT')
            self.fresh(r, old, before, expected, state, migrated=True, baseline=baseline)
            m.run(['docker', 'rename', old['Id'], self.old_name], 'ORIGINAL_RENAME_FAILED'); m.run(['docker', 'rename', identity, 't24-crm'], 'CANDIDATE_RENAME_FAILED')
            self.fresh(r, old, before, expected, state, migrated=True, baseline=baseline)
            m.run(['docker', 'start', identity], 'CANDIDATE_START_FAILED'); m.ready(identity)
            self.accept(r, old, before, expected, state, baseline, updated=False)
            m.replace_nginx(original_nginx, m.next_nginx(original_nginx)); m.retained().reload_nginx()
            candidate = self.accept(r, old, before, expected, state, baseline, updated=True); sentinel = self.public_check(state['candidate_id'])
            candidate = self.accept(r, old, before, expected, state, baseline, updated=True)
            result = {'stage': 'MEDIA_WORKFLOW_DEPLOYED_VERIFIED', 'deployed': True, 'source_sha': SOURCE_SHA, 'frontend_version': FRONTEND, 'schema_revision': NEW_REVISION, 'schema_sha256': r['schema_after_sha256'], 'crm': m.runtime(candidate), 'original_id': old['Id'], 'preflight_sha256': a.preflight_sha256, 'prepared_sha256': a.review_sha256, 'candidate_inventory_sha256': r['candidate_inventory_sha256'], 'public_root': str(self.public), 'public_inventory_sha256': r['public_inventory_sha256'], 'nginx_sha256': H(m.NGINX.read_bytes()), 'original_business_rows_unchanged': True, 'original_130_tables_preserved_except_reviewed_schema_head': True, 'six_new_workflow_tables_empty': True, 'scheduler_enabled': True, 'scheduler_activation_from': self.pf.ACTIVATION_FROM, 'existing_google_environment_preserved': True, 'original_env_mounts_network_unchanged': True, 'private_runtime_unchanged': True, 'database_restored': False, 'production_containers_deleted': False, 'no_new_policy_task_schedule_or_post': True, 'image_delivery_policy_off_empty': True, **sentinel, 'provider_requests_by_deployment': False, 'sequence_written_by_tool': False, 'live_kernel_oom_behavior_verified': False}
            sha = self.record('deployed.json', result); return {**result, 'receipt_sha256': sha}
        except BaseException:
            self.recover_internal(r, old, before, expected); raise

    def accept(self, r, old, before, expected, state, baseline, *, updated, recovery=False):
        _, candidate = self.fresh(r, old, before, expected, state, migrated=True, updated=updated, live=True, baseline=baseline, recovery=recovery)
        output = self.m.run(['docker', 'exec', candidate['Id'], 'python', '-B', '-c', self.active_probe()], 'ACTIVE_GOOGLE_ENVIRONMENT_FAILED')
        need(output.strip() == b'EXACT_EXISTING_ON_WORKER_CUTOFF_NO_NETWORK', 'EXACT_ON_CUTOFF_MARKER_REQUIRED')
        need(self.m.verify_public(self.public, self.manifest) == r['public_inventory_sha256'], 'FINAL_PUBLIC_INVENTORY_DRIFT')
        _, candidate = self.fresh(r, old, before, expected, state, migrated=True, updated=updated, live=True, baseline=baseline, recovery=recovery); return candidate

    def recover_internal(self, r, old, before, expected):
        m, a = self.m, self.args; state = self.state(r, old); candidate = m.inspect(state['candidate_id'])
        need(candidate['Id'] == state['candidate_id'] and candidate['Image'] == r['candidate_image'] and candidate['Name'] in {'/t24-crm', '/' + self.candidate_name}, 'OWNED_RECOVERY_CANDIDATE_REQUIRED')
        if candidate['State']['Running']: m.run(['docker', 'stop', '--time', '30', candidate['Id']], 'RECOVERY_CONTAINMENT_FAILED', 60)
        need(m.inspect(candidate['Id'])['State']['Running'] is False, 'RECOVERY_CANDIDATE_STOPPED_REQUIRED')
        # Settle a possibly interrupted, durably identified migration before
        # deciding whether retained code is still compatible with the head.
        known = self.settle_migration(m.BUSINESS.parent)
        head = self.revision(); body = m.NGINX.read_bytes(); updated = H(body) == r['nginx_next_sha256']
        self.protections(updated=updated, head=head, recovery=True, schema=r['schema_after_sha256'])
        retained, candidate = self.identities(state, old); self.source_boundary(retained, before); self.source_boundary(candidate, expected)
        if head == OLD_REVISION:
            # No migration committed. Restore exact old runtime only against
            # its exact old schema; never copy a database or counters back.
            if updated:
                original = m.read(a.release / 'nginx-before.conf', self.proof['nginx_sha256']); m.replace_nginx(body, original)
            m.retained().reload_nginx()
            if candidate['Name'] == '/t24-crm': m.run(['docker', 'rename', candidate['Id'], self.candidate_name], 'RETAIN_CANDIDATE_FAILED')
            if retained['Name'] != '/t24-crm': m.run(['docker', 'rename', retained['Id'], 't24-crm'], 'RESTORE_OLD_NAME_FAILED')
            if not retained['State']['Running']: m.run(['docker', 'start', retained['Id']], 'PRE_MIGRATION_RESUME_FAILED')
            m.ready(retained['Id']); restored = m.inspect('t24-crm'); self.pf.google_environment(restored)
            need(restored['Id'] == old['Id'] and restored['State']['Running'] is True and m.runtime(restored)['config'] == m.runtime(old)['config'], 'PRE_MIGRATION_ORIGINAL_NOT_RESTORED')
            self.source_boundary(restored, before); self.protections(recovery=True)
            kept = m.inspect(state['candidate_id']); need(kept['State']['Running'] is False and kept['Name'] == '/' + self.candidate_name, 'PRE_MIGRATION_CANDIDATE_NOT_RETAINED_STOPPED')
            result = {'stage': 'MEDIA_WORKFLOW_PRE_MIGRATION_ORIGINAL_RESUMED', 'source_sha': BASE_SOURCE, 'schema_revision': OLD_REVISION, 'candidate_retained_stopped': True, 'database_restored': False, 'provider_requests_by_tool': False}
        else:
            # New schema is forward-only. Preserve any legitimate independent
            # rows created after a partial switch; never start old code here.
            need(known is not None and known['Image'] == r['candidate_image'] and known['State']['Running'] is False, 'SETTLED_KNOWN_MIGRATION_REQUIRED')
            if retained['State']['Running']: m.run(['docker', 'stop', '--time', '30', retained['Id']], 'FORWARD_STOP_OLD_FAILED', 60)
            saved = json.loads(m.read(a.release / 'production-baseline-identity.json'))
            need(saved == {'source_sha': SOURCE_SHA, 'original_id': old['Id'], 'candidate_id': state['candidate_id'], 'review_sha256': a.review_sha256, 'rows_sha256': saved['rows_sha256']} and re.fullmatch('[a-f0-9]{64}', saved['rows_sha256']), 'EXACT_PRODUCTION_BASELINE_IDENTITY_REQUIRED')
            baseline = json.loads(m.read(a.release / 'production-before-rows.json', saved['rows_sha256']))
            need(evidence(baseline) == self.proof['rows'], 'PRODUCTION_BASELINE_PROOF_DRIFT')
            compare_original(baseline, self.rows(), rows=False, empty=False)
            need(self.new_schema(m.BUSINESS, empty=False) == r['schema_after_sha256'], 'FORWARD_SCHEMA_DRIFT')
            compare(candidate, old, m); self.pf.google_environment(candidate); m.verify_secret_mount(candidate)
            if retained['Name'] == '/t24-crm': m.run(['docker', 'rename', retained['Id'], self.old_name], 'FORWARD_RETAIN_OLD_FAILED')
            if candidate['Name'] != '/t24-crm': m.run(['docker', 'rename', candidate['Id'], 't24-crm'], 'FORWARD_CANDIDATE_ROLE_FAILED')
            try:
                m.run(['docker', 'start', candidate['Id']], 'FORWARD_START_FAILED'); m.ready(candidate['Id'])
                if not updated: m.replace_nginx(body, m.next_nginx(body))
                m.retained().reload_nginx(); active = self.accept(r, old, before, expected, state, baseline, updated=True, recovery=True); sentinel = self.public_check(state['candidate_id'])
                active = self.accept(r, old, before, expected, state, baseline, updated=True, recovery=True)
            except BaseException:
                live=m.inspect(candidate['Id'])
                need(live['Id']==state['candidate_id'] and live['Image']==r['candidate_image'], 'KNOWN_FORWARD_CANDIDATE_REQUIRED')
                if live['State']['Running']:m.run(['docker','stop','--time','30',live['Id']], 'FORWARD_ACCEPTANCE_CONTAINMENT_FAILED',60)
                need(m.inspect(live['Id'])['State']['Running'] is False,'FORWARD_CANDIDATE_CONTAINED_REQUIRED')
                raise
            result = {'stage': 'MEDIA_WORKFLOW_FORWARD_RECOVERED', 'source_sha': SOURCE_SHA, 'schema_revision': NEW_REVISION, 'crm': m.runtime(active), 'old_application_started_after_migration': False, 'independent_rows_preserved': True, 'scheduler_enabled': True, 'scheduler_activation_from': self.pf.ACTIVATION_FROM, 'database_restored': False, 'containers_deleted': False, 'provider_requests_by_tool': False, **sentinel}
        self.record('recovery-' + str(time.time_ns()) + '.json', result); return result

    def recover(self):
        r, old, before, expected = self.reviewed(); a = self.args
        need(not (a.release / 'deployed.json').exists(), 'SUCCESSFUL_DEPLOYMENT_REQUIRES_SEPARATE_RECOVERY_REVIEW')
        started = json.loads(self.m.read(a.release / 'activation-started.json'))
        need(started == {'source_sha': SOURCE_SHA, 'review_sha256': a.review_sha256, 'original_id': old['Id'], 'candidate_image': r['candidate_image']}, 'EXACT_RECOVERY_INTENT_REQUIRED')
        if not (a.release / 'candidate-created.json').exists():
            self.current(); return {'stage': 'MEDIA_WORKFLOW_ABORTED_BEFORE_SWITCH', 'original_unchanged': True, 'candidate_not_touched': True, 'manual_orphan_review_required': True, 'database_restored': False}
        return self.recover_internal(r, old, before, expected)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--phase', choices=['prepare', 'activate', 'recover'], required=True)
    parser.add_argument('--release', type=Path, required=True); parser.add_argument('--manifest-sha256', required=True); parser.add_argument('--payload-sha256', required=True)
    parser.add_argument('--preflight', type=Path, required=True); parser.add_argument('--preflight-sha256', required=True); parser.add_argument('--review-sha256'); args = parser.parse_args()
    pins_ready(); need(os.geteuid() == 0 and socket.gethostname() == HOST, 'EXACT_ROOT_SERVER_REQUIRED'); resource.setrlimit(resource.RLIMIT_CORE, (0, 0)); os.umask(0o077); sys.dont_write_bytecode = True
    need(args.release.resolve() == args.release and args.release.parent == Path('/opt/t24-crm/releases'), 'EXACT_RELEASE_PARENT_REQUIRED')
    for parent in args.release.parents:
        row = parent.lstat(); need(parent.resolve() == parent and stat.S_ISDIR(row.st_mode) and row.st_uid == 0 and not row.st_mode & 0o022, 'PROTECTED_RELEASE_PARENT_REQUIRED')
    row = args.release.lstat(); need(stat.S_ISDIR(row.st_mode) and row.st_uid == 0 and stat.S_IMODE(row.st_mode) == 0o700, 'PROTECTED_RELEASE_REQUIRED')
    need(all(re.fullmatch('[a-f0-9]{64}', s) for s in (args.manifest_sha256, args.payload_sha256, args.preflight_sha256)), 'EXACT_PUBLIC_PINS_REQUIRED')
    need(args.preflight == Path('/opt/t24-crm/releases/media-workflow-preflight-' + args.preflight_sha256[:12] + '.json'), 'EXACT_SERVER_PREFLIGHT_PATH_REQUIRED')
    need(args.phase != 'prepare' or args.review_sha256 is None, 'PREPARE_HAS_NO_SWITCH_REVIEW_ARGUMENT')
    lock = os.open('/opt/t24-crm/releases/.media-workflow-release.lock', os.O_RDWR | os.O_NONBLOCK | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        row = os.fstat(lock); need(stat.S_ISREG(row.st_mode) and row.st_uid == 0 and row.st_nlink == 1 and stat.S_IMODE(row.st_mode) == 0o600, 'PROTECTED_LOCK_REQUIRED'); fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        print(json.dumps(getattr(Release(args), args.phase)(), sort_keys=True))
    finally: os.close(lock)


if __name__ == '__main__':
    try: main()
    except BaseException as error:
        value = str(error); code = value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}', value) else 'PUBLICATION_RELEASE_REJECTED'
        print(json.dumps({'stage': 'MEDIA_WORKFLOW_RELEASE_REJECTED', 'code': code, 'database_restored': False})); sys.exit(1)
