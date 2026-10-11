#!/usr/bin/env python3
"""Prepare a private Stripe-report image and a data-preserving rollback image.

Only isolated images, synthetic fixtures and a new protected release directory
are written. This helper never loads live configuration, mounts live databases,
starts production services, publishes static assets or applies production DDL.
The historical deployment helpers are intentionally not imported or modified.
"""
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import stat
import subprocess
import tarfile
from uuid import uuid4
import xml.etree.ElementTree as ET

BASE_SOURCE = '3c5b8c1d63b8f078e162e228750b508715699479'
SOURCE_SHA = 'c1ae19b38fec8f62f044d4b0789f31662da12fbf'
BASE_IMAGE = 'sha256:322968e1935a6f7bb2e6d366a9f1cdb98aefab392af28c7269660ff46262a886'
BASE_MODEL_SHA = 'f28e051ef04dc23e0b1e15755eb71e3881879cd203e0698f3a6e239549ca158d'
MODEL_SHA = '142efa791f93be218fab81add24f21231397bce62d60aa77d6d91abc3d1f57b1'
BASE_MODEL_BYTES = 9825
BASE_PYTHON_VERSION = '3.10.22'
BASE_PACKAGE_VERSIONS = {'packaging': '26.3', 'tomli': '2.5.0', 'exceptiongroup': '1.3.1'}
WHEEL_VERSIONS = {'pytest': '8.4.2', 'pytest-asyncio': '1.2.0', 'iniconfig': '2.3.1', 'pluggy': '1.6.0',
                  'pygments': '2.21.0', 'backports-asyncio-runner': '1.2.0'}
BASE_WHEEL_MANIFEST_SHA = '4ad12c82c5d9c50727d6342965d49b2401f3b5b04d7f5f3f4705b8f40fc661f8'
BASE_TEST_ROOT = Path('/opt/t24-crm/releases/private-workspace-1a4c952-20261011-retry2')
HASH = re.compile(r'[a-f0-9]{64}')
IMAGE = re.compile(r'sha256:[a-f0-9]{64}')
PRIVATE_NAME = re.compile(r'private_[a-z][a-z0-9_]{0,79}')
BASE_TABLES = frozenset({'private_connections', 'private_items', 'private_preferences', 'private_sync_runs',
    'private_mail_translations', 'private_translation_usage', 'private_mail_briefs', 'private_mail_brief_usage',
    'private_workspace_briefs', 'private_bank_links'})
TARGET_TABLES = BASE_TABLES | {'private_stripe_reports'}
BACKEND_CHANGES = frozenset('app/backend/' + name for name in (
    'models/private_workspace.py', 'routers/private_workspace.py', 'schemas/private_workspace.py',
    'services/private_stripe_report_provider.py', 'services/private_stripe_report_service.py',
    'services/private_workspace_providers.py', 'tests/test_private_stripe_report_provider.py',
    'tests/test_private_stripe_report_service.py', 'tests/test_private_workspace_core.py'))
PRIVATE_TESTS = frozenset('app/backend/tests/' + name + '.py' for name in (
    'test_private_ads_health', 'test_private_bank_auth', 'test_private_bank_provider', 'test_private_bank_service',
    'test_private_mail_brief', 'test_private_mail_brief_service', 'test_private_mail_content', 'test_private_mail_relevance',
    'test_private_mail_translation', 'test_private_mail_translation_service', 'test_private_python310_compat',
    'test_private_stripe_auth', 'test_private_stripe_connection', 'test_private_stripe_report_provider',
    'test_private_stripe_report_service', 'test_private_workspace_app', 'test_private_workspace_brief',
    'test_private_workspace_core', 'test_private_workspace_providers', 'test_private_workspace_worker')) | {'app/backend/tests/conftest.py'}

SYNTHETIC_ENV = {
    'APP_ENV': 'test', 'ENVIRONMENT': 'test', 'ENV': 'test', 'TZ': 'UTC',
    'DATABASE_URL': 'sqlite+aiosqlite:////tmp/synthetic-business.db', 'DATABASE_SCHEMA_MODE': 'verify_only',
    'PRIVATE_WORKSPACE_DATABASE_URL': 'sqlite+aiosqlite:////tmp/synthetic-private/workspace.db',
    'PRIVATE_WORKSPACE_OWNER_IDS': '4', 'PRIVATE_WORKSPACE_ENCRYPTION_KEY': 'synthetic_report_candidate_encryption_key_never_production',
    'JWT_SECRET_KEY': 'synthetic_report_candidate_employee_signing_key_never_production',
    'AUTOMATION_SCAN_ENABLED': 'false', 'ENABLE_DEFAULT_EMPLOYEE_ADMIN': 'false',
    'PRIVATE_MAIL_BRIEF_ENABLED': 'false', 'PRIVATE_MAIL_BRIEF_EXTERNAL_CONSENT': 'false',
    'PRIVATE_MAIL_BRIEF_HOSTING_VERIFIED': 'false', 'PRIVATE_WORKSPACE_BRIEF_EXTERNAL_CONSENT': 'false',
    'PRIVATE_WORKSPACE_PLAID_ENABLED': 'false', 'ENFORCE_EMPLOYEE_STATUS': 'false',
    'ENFORCE_EMPLOYEE_SESSIONS': 'false', 'PYTHONDONTWRITEBYTECODE': '1',
}

SCAN_BACKEND = """import hashlib,json,pathlib
r=pathlib.Path('/app/backend');out={}
for p in sorted(r.rglob('*')):
 rel=p.relative_to(r)
 if {'data','logs','private-data','__pycache__'}.intersection(rel.parts) or p.suffix in ('.pyc','.pyo'):continue
 assert not p.is_symlink()
 if p.is_file():out[rel.as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
assert out
print(json.dumps(out,sort_keys=True))
"""
SCAN_STATIC = SCAN_BACKEND.replace("'/app/backend'", "'/app/frontend/dist'")
SCAN_PACKAGES = """import hashlib,json,pathlib,sysconfig
h=hashlib.sha256();count=0
for label in ('purelib','scripts'):
 r=pathlib.Path(sysconfig.get_path(label))
 for p in sorted(r.rglob('*')):
  if p.is_file():
   b=p.read_bytes();h.update(json.dumps([label+'/'+p.relative_to(r).as_posix(),len(b),hashlib.sha256(b).hexdigest()],separators=(',',':')).encode());count+=1
assert count>100
print(json.dumps({'files':count,'sha256':h.hexdigest()},sort_keys=True))
"""
SCAN_RUNTIME = """import importlib.metadata,json,platform
out={}
for name in NAMES:
 try:out[name]=importlib.metadata.version(name)
 except importlib.metadata.PackageNotFoundError:out[name]=None
print(json.dumps({'python':platform.python_version(),'packages':out},sort_keys=True))
""".replace('NAMES', repr(sorted(set(BASE_PACKAGE_VERSIONS) | set(WHEEL_VERSIONS))))
VERIFY_TOOLS = """import importlib.metadata,platform
assert platform.python_version()==PYTHON
assert {n:importlib.metadata.version(n) for n in EXPECTED}==EXPECTED
""".replace('PYTHON', repr(BASE_PYTHON_VERSION)).replace('EXPECTED', repr({**BASE_PACKAGE_VERSIONS, **WHEEL_VERSIONS}))

FIXTURE_BASE = """import os,pathlib,sqlite3,time
from datetime import datetime,timezone,timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from models.private_workspace import (PrivateWorkspaceBase,PrivateConnection,PrivateItem,PrivatePreferences,PrivateSyncRun,
 PrivateMailTranslation,PrivateTranslationUsage,PrivateMailBrief,PrivateMailBriefUsage,PrivateWorkspaceBrief,PrivateBankLink)
from services.private_workspace import encrypt_credentials
from services.employee_sessions import _credential_fingerprint
r=pathlib.Path('/synthetic/private');p=r/'original.db';b=pathlib.Path('/synthetic/business/business.db')
e=create_engine('sqlite:///'+str(p));PrivateWorkspaceBase.metadata.create_all(e)
d=datetime(2026,10,12,tzinfo=timezone.utc);token=encrypt_credentials({'synthetic':'fixture-only-never-live'})
with Session(e) as s:
 s.add_all([
  PrivateConnection(id='synthetic',owner_id='4',source_id='gmail',status='connected',encrypted_credentials=token,metadata_json={},generation=1,created_at=d,updated_at=d),
  PrivateItem(id='synthetic-item',owner_id='4',source_id='gmail',external_id='fixture-message',kind='mail',title='Synthetic fixture',summary='No real mail',local_title='Preserved override',status='unread',priority='normal',evidence={},action_status='done',created_at=d,updated_at=d),
  PrivatePreferences(owner_id='4',preferences_json={'synthetic':True},updated_at=d),
  PrivateSyncRun(id='synthetic-run',owner_id='4',source_id='gmail',status='succeeded',started_at=d,completed_at=d,created_count=1,updated_count=0),
  PrivateMailTranslation(cache_key='1'*64,owner_id='4',connection_id='synthetic',generation=1,item_id='synthetic-item',source_hash='2'*64,mode='zh',state='ready',encrypted_content=token,created_at=d,updated_at=d),
  PrivateTranslationUsage(owner_id='4',month='2026-10',characters=11,updated_at=d),
  PrivateMailBrief(cache_key='3'*64,owner_id='4',connection_id='synthetic',generation=1,item_id='synthetic-item',source_hash='4'*64,model='synthetic',state='ready',encrypted_content=token,created_at=d,updated_at=d),
  PrivateMailBriefUsage(owner_id='4',month='2026-10',characters=12,requests=1,reserved_usd_micros=123,updated_at=d),
  PrivateWorkspaceBrief(cache_key='5'*64,owner_id='4',snapshot_id='6'*64,model='synthetic',state='ready',encrypted_content=token,created_at=d,updated_at=d),
  PrivateBankLink(id='synthetic-bank',owner_id='4',connection_id='synthetic',generation=1,state='pending',encrypted_context=token,expires_at=d+timedelta(days=1),created_at=d,updated_at=d),
 ]);s.commit()
e.dispose()
with sqlite3.connect(b) as c:
 c.execute('CREATE TABLE finance_sentinel(id INTEGER PRIMARY KEY,amount INTEGER NOT NULL)');c.execute('INSERT INTO finance_sentinel VALUES (1,70000)')
 c.execute('CREATE TABLE employees(id INTEGER PRIMARY KEY,user_id TEXT,name TEXT,role TEXT,phone TEXT,email TEXT,status TEXT,password TEXT,updated_at TEXT)')
 c.execute('CREATE TABLE employee_auth_sessions(id TEXT PRIMARY KEY,employee_id INTEGER,credential_fingerprint TEXT,created_at INTEGER,expires_at INTEGER,revoked_at INTEGER)')
 password='synthetic-owner-password-hash';now=int(time.time())
 c.execute(\"INSERT INTO employees VALUES (4,'synthetic-owner','Synthetic owner','super_admin',NULL,'owner@invalid.test','active',?,NULL)\",(password,))
 c.execute('INSERT INTO employee_auth_sessions VALUES (?,?,?, ?,?,NULL)',('synthetic-session',4,_credential_fingerprint({'id':4,'password':password}),now,now+3600))
for f in (p,b):os.chmod(f,0o600)
print('{"synthetic_only":true,"original_ten_tables_seeded":true}')
"""
EMPTY_SCHEMA = """import os
from sqlalchemy import create_engine
from models.private_workspace import PrivateWorkspaceBase
p='/synthetic/private/empty.db';e=create_engine('sqlite:///'+p);PrivateWorkspaceBase.metadata.create_all(e);e.dispose();os.chmod(p,0o600)
print('{"independent_empty_candidate_schema":true}')
"""
INIT_MIGRATION = """import os,asyncio
os.environ['DATABASE_URL']='sqlite+aiosqlite:////synthetic/business/business.db'
os.environ['PRIVATE_WORKSPACE_DATABASE_URL']='sqlite+aiosqlite:////synthetic/private/migrated/workspace.db'
from services.private_workspace import private_session_factory,close_private_workspace_storage
async def run():
 await private_session_factory();await close_private_workspace_storage()
asyncio.run(run());print('{"synthetic_initializer_completed":true}')
"""
SEED_REPORT_CACHE = """import os,sqlite3
from services.private_workspace import encrypt_credentials
token=encrypt_credentials({'synthetic':'report-cache-only-never-live'})
with sqlite3.connect('/synthetic/private/migrated/workspace.db') as c:
 c.execute(\"INSERT INTO private_stripe_reports(cache_key,owner_id,connection_id,generation,encrypted_report,expires_at,created_at) VALUES (?,'4','synthetic',1,?,'2027-01-01','2026-10-12')\",('7'*64,token))
print('{"synthetic_report_cache_seeded":true}')
"""
ROLLBACK_READ = """import os,asyncio,sys
os.environ['DATABASE_URL']='sqlite+aiosqlite:////synthetic/business/business.db'
os.environ['PRIVATE_WORKSPACE_DATABASE_URL']='sqlite+aiosqlite:////synthetic/private/migrated/workspace.db'
os.environ['ENFORCE_EMPLOYEE_STATUS']='true';os.environ['ENFORCE_EMPLOYEE_SESSIONS']='true'
from sqlalchemy import select
from models.private_workspace import PrivateConnection,PrivateStripeReport
from services.private_workspace import private_session_factory,close_private_workspace_storage,decrypt_credentials
from services.private_workspace_app import create_private_workspace_app
from services.emp_auth import create_access_token
from httpx import AsyncClient,ASGITransport
async def run():
 sessions=await private_session_factory()
 async with sessions() as db:
  row=(await db.execute(select(PrivateConnection))).scalar_one()
  assert row.owner_id=='4' and decrypt_credentials(row.encrypted_credentials)=={'synthetic':'fixture-only-never-live'}
  cache=(await db.execute(select(PrivateStripeReport))).scalar_one()
  assert cache.owner_id=='4' and decrypt_credentials(cache.encrypted_report)=={'synthetic':'report-cache-only-never-live'}
 await close_private_workspace_storage()
 app=create_private_workspace_app()
 async with app.router.lifespan_context(app):
  async with AsyncClient(transport=ASGITransport(app,raise_app_exceptions=True),base_url='http://synthetic.invalid') as client:
   assert (await client.get('/ready')).status_code==200
   denied=await client.get('/api/v1/private-workspace');assert denied.status_code in (401,403) and denied.headers.get('cache-control')=='no-store'
   token=create_access_token({'emp_id':4,'role':'super_admin','sid':'synthetic-session'})
   response=await client.get('/api/v1/private-workspace',headers={'Authorization':'Bearer '+token})
   assert response.status_code==200 and response.headers.get('cache-control')=='no-store'
 forbidden={'main','services.database','services.deal_payment_sync','services.customer_lifecycle','services.automation_monitor'}
 assert not (forbidden & set(sys.modules))
asyncio.run(run());print('{"compatible_old_api_startup_and_owner_read":true,"new_cache_decrypted_and_preserved":true}')
"""


class PrepareError(RuntimeError): pass


def need(condition, code):
    if not condition: raise PrepareError(code)


def sha(data): return hashlib.sha256(data).hexdigest()


def digest(value): return sha(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode())


def protected(path, *, directory=False):
    path = Path(path)
    need(path.is_absolute() and path.resolve() == path, 'CANONICAL_PROTECTED_PATH_REQUIRED')
    for item in (path, *path.parents): need(not item.is_symlink(), 'PROTECTED_PATH_SYMLINK_REJECTED')
    value = path.lstat()
    need(value.st_uid == os.geteuid() and not stat.S_IMODE(value.st_mode) & 0o077 and
         (stat.S_ISDIR(value.st_mode) if directory else stat.S_ISREG(value.st_mode) and value.st_nlink == 1), 'PROTECTED_OWNER_MODE_REQUIRED')
    return value


def write_new(path, data):
    protected(path.parent, directory=True)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())


def save(path, value): write_new(path, (json.dumps(value, sort_keys=True, indent=2) + '\n').encode())


def frozen_file(path, expected, maximum=64 * 1024**2):
    before = protected(path)
    need(HASH.fullmatch(expected or '') and 0 < before.st_size <= maximum, 'FROZEN_FILE_REQUIRED')
    data = path.read_bytes()
    need(sha(data) == expected and protected(path) == before, 'FROZEN_FILE_HASH_OR_IDENTITY_DRIFT')
    return data


def _file_identity(path, *, private):
    path = Path(path)
    need(path.is_absolute() and path.resolve() == path, 'CANONICAL_DATABASE_PATH_REQUIRED')
    for item in (path, *path.parents): need(not item.is_symlink(), 'DATABASE_PATH_SYMLINK_REJECTED')
    info = protected(path) if private else path.lstat()
    need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'REGULAR_SINGLE_LINK_DATABASE_REQUIRED')
    if private: protected(path.parent, directory=True)
    return {'device': info.st_dev, 'inode': info.st_ino, 'path_sha256': digest(str(path)), 'uid': info.st_uid, 'mode': stat.S_IMODE(info.st_mode)}


def database_snapshot(path, *, private, owner_id='4'):
    """Read-only hash evidence; no record values or SQL text enter receipts."""
    identity = _file_identity(path, private=private)
    with sqlite3.connect(Path(path).as_uri() + '?mode=ro', uri=True, timeout=15) as db:
        db.execute('PRAGMA query_only=ON'); db.execute('BEGIN')
        need(db.execute('PRAGMA integrity_check').fetchall() == [('ok',)], 'DATABASE_INTEGRITY_FAILED')
        objects = {}; tables = {}
        rows = db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name').fetchall()
        for kind, name, table, sql in rows:
            need(kind in {'table', 'index'}, 'TRIGGER_OR_VIEW_REQUIRES_SEPARATE_REVIEW')
            objects[name] = {'type': kind, 'table': table, 'sql_sha256': digest(sql)}
        names = sorted(name for name, value in objects.items() if value['type'] == 'table')
        need(names and all(bool(PRIVATE_NAME.fullmatch(name)) == private for name in names), 'PRIVATE_BUSINESS_SCHEMA_BOUNDARY_REJECTED')
        for name in names:
            quoted = '"' + name.replace('"', '""') + '"'
            columns = db.execute('PRAGMA table_info(' + quoted + ')').fetchall()
            need(columns, 'TABLE_WITHOUT_COLUMNS_REJECTED')
            if private:
                need('owner_id' in {column[1] for column in columns}, 'PRIVATE_OWNER_COLUMN_REQUIRED')
                need(db.execute('SELECT 1 FROM ' + quoted + ' WHERE owner_id IS NULL OR owner_id <> ? LIMIT 1', (owner_id,)).fetchone() is None, 'PRIVATE_OWNER_SCOPE_DRIFT')
            order = ','.join('"' + column[1].replace('"', '""') + '"' for column in columns)
            fingerprint = hashlib.sha256(); count = 0
            for row in db.execute('SELECT * FROM ' + quoted + ' ORDER BY ' + order):
                encoded = json.dumps(list(row), ensure_ascii=False, separators=(',', ':'), default=lambda item: {'bytes_hex': bytes(item).hex()}).encode()
                fingerprint.update(len(encoded).to_bytes(8, 'big')); fingerprint.update(encoded); count += 1
            tables[name] = {'columns_sha256': digest(columns), 'rows': count, 'rows_sha256': fingerprint.hexdigest()}
    need(_file_identity(path, private=private) == identity, 'DATABASE_FILE_IDENTITY_CHANGED')
    return {'identity': identity, 'tables': tables, 'schema_objects': objects, 'schema_sha256': digest(objects), 'data_sha256': digest(tables)}


def release_snapshot(private_path, business_path, *, owner_id='4'):
    need(owner_id == '4' and not os.path.samefile(private_path, business_path), 'PRIVATE_BUSINESS_OR_OWNER_BOUNDARY_REJECTED')
    return {'format_version': 1, 'stage': 'STRIPE_REPORT_READONLY_SCHEMA_SNAPSHOT', 'mutation_performed': False,
            'owner_id': owner_id, 'private': database_snapshot(private_path, private=True, owner_id=owner_id),
            'business': database_snapshot(business_path, private=False)}


def compare_schema_snapshots(before, after, target_schema_objects, *, source_sha=SOURCE_SHA, mode='clone'):
    """Only the reviewed ten-to-eleven additive change is accepted."""
    need(source_sha == SOURCE_SHA and mode in {'clone', 'in_place'}, 'REVIEWED_SOURCE_AND_MODE_REQUIRED')
    for snapshot in (before, after):
        need(snapshot.get('format_version') == 1 and snapshot.get('stage') == 'STRIPE_REPORT_READONLY_SCHEMA_SNAPSHOT'
             and snapshot.get('mutation_performed') is False and snapshot.get('owner_id') == '4', 'OWNER_READONLY_SNAPSHOT_REQUIRED')
    old, new = before['private'], after['private']
    need(set(old['tables']) == BASE_TABLES and set(new['tables']) == TARGET_TABLES, 'EXACT_TEN_TO_ELEVEN_PRIVATE_TABLES_REQUIRED')
    need(isinstance(target_schema_objects, dict) and target_schema_objects == new['schema_objects'], 'INDEPENDENT_TARGET_DDL_REQUIRED')
    need({name for name, value in target_schema_objects.items() if value.get('type') == 'table'} == TARGET_TABLES, 'INDEPENDENT_ELEVEN_TABLE_SCHEMA_REQUIRED')
    for name, value in target_schema_objects.items():
        need(isinstance(name, str) and set(value) == {'type', 'table', 'sql_sha256'} and value['type'] in {'table', 'index'}
             and value['table'] in TARGET_TABLES and HASH.fullmatch(value['sql_sha256']), 'TARGET_SCHEMA_OBJECT_REJECTED')
    if mode == 'in_place': need(old['identity'] == new['identity'], 'PRIVATE_DATABASE_FILE_REPLACED')
    else:
        need((old['identity']['device'], old['identity']['inode']) != (new['identity']['device'], new['identity']['inode']), 'CLONE_MUST_HAVE_DISTINCT_IDENTITY')
    need(all(old['tables'][name] == new['tables'][name] for name in BASE_TABLES), 'ORIGINAL_PRIVATE_ROWS_OR_COLUMNS_CHANGED')
    need(old['schema_objects'] == {name: value for name, value in new['schema_objects'].items() if value['table'] in BASE_TABLES}, 'ORIGINAL_PRIVATE_DDL_OR_INDEX_CHANGED')
    need(new['tables']['private_stripe_reports']['rows'] == 0, 'NEW_REPORT_CACHE_MUST_START_EMPTY')
    need(before['business'] == after['business'], 'BUSINESS_DATABASE_CHANGED')
    return {'stage': 'STRIPE_REPORT_TEN_TO_ELEVEN_SCHEMA_VERIFIED', 'format_version': 1, 'source_sha': source_sha,
            'mode': mode, 'original_rows_columns_indexes_preserved': True, 'new_cache_empty': True, 'business_unchanged': True,
            'original_tables': sorted(BASE_TABLES), 'target_tables': sorted(TARGET_TABLES), 'before_sha256': digest(before),
            'after_sha256': digest(after), 'target_schema_sha256': digest(target_schema_objects), 'validator_wrote_databases': False}


def checked_payload(manifest, frozen_source, payload_sha256):
    need(manifest.get('format_version') == 1 and manifest.get('stage') == 'STRIPE_REPORT_BACKEND_PAYLOAD_PREPARED', 'NEW_REPORT_PAYLOAD_REQUIRED')
    for value in (manifest, frozen_source):
        need(value.get('source_sha') == SOURCE_SHA and value.get('baseline_private_source_sha') == BASE_SOURCE and value.get('base_private_image') == BASE_IMAGE, 'ACCEPTED_BASE_AND_EXACT_SOURCE_REQUIRED')
    need(manifest.get('payload_sha256') == payload_sha256 and HASH.fullmatch(payload_sha256 or ''), 'FROZEN_PAYLOAD_HASH_REQUIRED')
    inventory = manifest.get('payload_files'); hashes = manifest.get('source_file_sha256'); tests = manifest.get('private_tests')
    need(isinstance(inventory, dict) and inventory and all(isinstance(name, str) and HASH.fullmatch(value) for name, value in inventory.items()), 'EXACT_PAYLOAD_INVENTORY_REQUIRED')
    need(set(manifest.get('backend_changes', [])) == BACKEND_CHANGES and set(frozen_source.get('backend_delta_sha256', {})) == BACKEND_CHANGES, 'COMPLETE_REVIEWED_BACKEND_DELTA_REQUIRED')
    need(isinstance(tests, list) and len(tests) == len(set(tests)) and set(tests) == PRIVATE_TESTS, 'ALL_PRIVATE_REGRESSIONS_REQUIRED')
    need(isinstance(hashes, dict) and set(hashes) == BACKEND_CHANGES | PRIVATE_TESTS and all(HASH.fullmatch(value) for value in hashes.values()), 'COMPLETE_PRIVATE_SOURCE_HASHES_REQUIRED')
    need(all(hashes[name] == value for name, value in frozen_source['backend_delta_sha256'].items()), 'FROZEN_DELTA_HASH_DRIFT')
    expected = {name.removeprefix('app/'): value for name, value in hashes.items()}
    static = frozen_source.get('frontend_dist_sha256') or {}
    need(isinstance(static, dict) and static and all(HASH.fullmatch(value) for value in static.values()), 'FROZEN_STATIC_INVENTORY_REQUIRED')
    expected.update({'frontend/dist/' + name: value for name, value in static.items()})
    need(inventory == expected and hashes['app/backend/models/private_workspace.py'] == MODEL_SHA, 'COMPLETE_FROZEN_PAYLOAD_DRIFT')
    dependencies = frozen_source.get('dependency_file_sha256')
    need(isinstance(dependencies, dict) and dependencies and manifest.get('runtime_dependency_file_sha256') == dependencies,
         'UNCHANGED_DEPENDENCY_PROOF_REQUIRED')
    minimum = frozen_source.get('backend_regression_tests_minimum')
    need(type(minimum) is int and minimum >= 845 and manifest.get('backend_regression_tests_expected_minimum') == minimum, 'COMPLETE_PRIVATE_TEST_MINIMUM_REQUIRED')
    need(manifest.get('runtime_dependency_changes') is False and manifest.get('credentials_included') is False
         and manifest.get('production_access') is False and manifest.get('deployed') is False, 'LOCAL_READONLY_PAYLOAD_REQUIRED')
    return manifest


def extract(payload, manifest, root):
    need(not root.exists() and not root.is_symlink(), 'NEW_PAYLOAD_DIRECTORY_REQUIRED'); root.mkdir(mode=0o700)
    found = {}; total = 0
    with tarfile.open(fileobj=io.BytesIO(payload), mode='r:gz') as archive:
        for member in archive:
            name = member.name.removeprefix('payload/'); path = PurePosixPath(name)
            need(member.isfile() and member.name.startswith('payload/') and path.as_posix() == name and not path.is_absolute()
                 and '..' not in path.parts and not any(part.startswith('.') for part in path.parts) and name not in found
                 and name in manifest['payload_files'] and 0 <= member.size <= 16 * 1024**2, 'REGULAR_ALLOWLISTED_ARCHIVE_ONLY')
            total += member.size; need(total <= 64 * 1024**2, 'PAYLOAD_EXPANSION_LIMIT')
            data = archive.extractfile(member).read(member.size + 1)
            need(len(data) == member.size and sha(data) == manifest['payload_files'][name], 'PAYLOAD_MEMBER_HASH_DRIFT')
            destination = root / name; destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True); write_new(destination, data)
            found[name] = sha(data)
    need(found == manifest['payload_files'], 'PAYLOAD_INCOMPLETE')


def checked_base_runtime(value):
    need(value == {'python': BASE_PYTHON_VERSION, 'packages': {**BASE_PACKAGE_VERSIONS, **{name: None for name in WHEEL_VERSIONS}}}, 'ACTUAL_RETAINED_PYTHON_OR_TOOLS_DRIFT')


def wheel_tools(wheels, manifest):
    protected(wheels, directory=True); actual = {}; tools = []
    for path in wheels.iterdir():
        value = path.lstat()
        need(not path.is_symlink() and stat.S_ISREG(value.st_mode) and value.st_nlink == 1 and value.st_uid == os.geteuid()
             and not stat.S_IMODE(value.st_mode) & 0o022, 'IMMUTABLE_RETAINED_WHEEL_REQUIRED')
        pieces = path.name.split('-'); name = re.sub('[-_.]+', '-', pieces[0]).lower()
        need(path.name.endswith('.whl') and len(pieces) >= 5 and WHEEL_VERSIONS.get(name) == pieces[1], 'ONLY_PINNED_TEST_TOOLS_ALLOWED')
        actual[path.name] = sha(path.read_bytes()); tools.append(name + '==' + pieces[1])
    need(actual == manifest and len(tools) == len(WHEEL_VERSIONS) and {tool.split('==')[0] for tool in tools} == set(WHEEL_VERSIONS), 'RETAINED_TEST_WHEEL_INVENTORY_DRIFT')
    return sorted(tools)


def test_report(xml, minimum):
    root = ET.fromstring(xml); suites = list(root.iter('testsuite')); cases = list(root.iter('testcase'))
    total = sum(int(suite.get('tests', '0')) for suite in suites)
    need(suites and total >= minimum and total == len(cases) and all(int(suite.get(key, '0')) == 0 for suite in suites for key in ('errors', 'failures', 'skipped'))
         and not any(list(root.iter(name)) for name in ('failure', 'error', 'skipped')), 'ALL_PRIVATE_TESTS_MUST_PASS_WITHOUT_SKIPS')
    return total


def expected_backend(base, manifest, *, rollback=False):
    expected = dict(base)
    for name, value in manifest['payload_files'].items():
        if name.startswith('backend/') and (not rollback or name == 'backend/models/private_workspace.py'):
            expected[name.removeprefix('backend/')] = value
    return expected


def recipe(manifest, base_tag, *, rollback=False):
    need(re.fullmatch('t24-private-stripe-report-base:' + SOURCE_SHA[:12] + '-[a-f0-9]{12}', base_tag or ''), 'EXCLUSIVE_RETAINED_BASE_TAG_REQUIRED')
    names = ['backend/models/private_workspace.py'] if rollback else sorted(name for name in manifest['payload_files'] if name.startswith('backend/'))
    label = 't24.private.rollback.schema-compatible' if rollback else 't24.private.source.sha'
    value = SOURCE_SHA if not rollback else 'ten-to-eleven-cache'
    return ('FROM ' + base_tag + '\n' + ''.join('COPY ' + name + ' /app/' + name + '\n' for name in names)
            + 'LABEL ' + label + '="' + value + '"\n').encode()


def verify_candidate_base(base, candidate):
    layers = base.get('RootFS', {}).get('Layers'); actual = candidate.get('RootFS', {}).get('Layers')
    need(isinstance(layers, list) and layers and isinstance(actual, list) and len(actual) > len(layers) and actual[:len(layers)] == layers, 'EXACT_RETAINED_BASE_LAYERS_REQUIRED')


def inspect_image(image):
    result = subprocess.run(['docker', 'image', 'inspect', image], capture_output=True, timeout=30, check=False)
    need(result.returncode == 0, 'RETAINED_IMAGE_REQUIRED'); rows = json.loads(result.stdout)
    need(len(rows) == 1 and rows[0]['Id'] == image, 'IMMUTABLE_IMAGE_ID_REQUIRED')
    environment = dict(value.split('=', 1) for value in rows[0]['Config'].get('Env', []))
    need(not any(value and re.search('SECRET|TOKEN|PASSWORD|PRIVATE_.*KEY|OPENAI|PLAID', name) for name, value in environment.items()), 'BAKED_CREDENTIALS_REJECTED')
    return rows[0]


class Runner:
    def __init__(self, release): self.release = release

    def run(self, stage, command, *, timeout=180, cwd=None):
        result = subprocess.run(command, cwd=cwd, capture_output=True, timeout=timeout, check=False)
        write_new(self.release / (stage + '.log'), result.stdout + b'\n' + result.stderr)
        need(result.returncode == 0, 'ISOLATED_' + stage.upper().replace('-', '_') + '_FAILED')
        return result.stdout

    def isolated(self, stage, image, code, *, mounts=(), timeout=180):
        need(IMAGE.fullmatch(image or ''), 'IMMUTABLE_ISOLATED_IMAGE_REQUIRED')
        token = uuid4().hex; name = 't24-private-report-check-' + token[:12]
        command = ['docker', 'run', '--rm', '--name', name, '--label', 't24.private.report.check=' + token,
                   '--network', 'none', '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                   '--no-healthcheck', '--workdir', '/app/backend', '--pids-limit', '128', '--memory', '1g', '--cpus', '2',
                   '--tmpfs', '/tmp:rw,nosuid,size=512m', '--tmpfs', '/app/backend/logs:rw,nosuid,noexec,size=16m']
        for key, value in sorted(SYNTHETIC_ENV.items()): command += ['--env', key + '=' + value]
        allowed_destinations = {'/synthetic/private', '/synthetic/business', '/test-results', '/test-wheels'}
        for source, destination, readonly in mounts:
            protected(source, directory=True)
            need((source.is_relative_to(self.release) or source == BASE_TEST_ROOT / 'test-wheels') and destination in allowed_destinations,
                 'ONLY_SYNTHETIC_AND_TEST_MOUNTS_ALLOWED')
            need(destination != '/test-wheels' or readonly, 'RETAINED_WHEELS_MUST_BE_READONLY')
            command += ['--mount', 'type=bind,src=' + str(source) + ',dst=' + destination + (',readonly' if readonly else '')]
        command += ['--entrypoint', 'python', image, '-c', code]
        try: return self.run(stage, command, timeout=timeout)
        finally:
            found = subprocess.run(['docker', 'inspect', name], capture_output=True, timeout=30, check=False)
            if found.returncode == 0:
                rows = json.loads(found.stdout)
                need(len(rows) == 1 and rows[0]['Image'] == image and rows[0]['Config'].get('Labels', {}).get('t24.private.report.check') == token,
                     'OWN_ISOLATED_CONTAINER_CLEANUP_IDENTITY_REQUIRED')
                result = subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=30, check=False)
                need(result.returncode == 0, 'OWN_ISOLATED_CONTAINER_CLEANUP_FAILED')

    def scan(self, stage, image, code): return json.loads(self.isolated(stage, image, code))


def schema_rehearsal(runner, image, rollback_image, manifest):
    synthetic = runner.release / 'synthetic'; synthetic.mkdir(mode=0o700)
    private = synthetic / 'private'; business_dir = synthetic / 'business'
    private.mkdir(mode=0o700); business_dir.mkdir(mode=0o700)
    writable = [(private, '/synthetic/private', False), (business_dir, '/synthetic/business', False)]
    private_only = [(private, '/synthetic/private', False), (business_dir, '/synthetic/business', True)]
    runner.isolated('schema-original-ten-fixture', BASE_IMAGE, FIXTURE_BASE, mounts=writable)
    original, business = private / 'original.db', business_dir / 'business.db'
    before = release_snapshot(original, business)
    need(set(before['private']['tables']) == BASE_TABLES and all(row['rows'] > 0 for row in before['private']['tables'].values()), 'ACTUAL_SEEDED_TEN_TABLE_BASE_REQUIRED')
    runner.isolated('schema-independent-empty-eleven', image, EMPTY_SCHEMA, mounts=private_only)
    empty = database_snapshot(private / 'empty.db', private=True)
    need(set(empty['tables']) == TARGET_TABLES and all(row['rows'] == 0 for row in empty['tables'].values()), 'INDEPENDENT_EMPTY_ELEVEN_SCHEMA_REQUIRED')
    save(runner.release / 'synthetic-target-schema.json', empty['schema_objects']); save(runner.release / 'synthetic-before.json', before)
    migrated = private / 'migrated'; migrated.mkdir(mode=0o700)
    with sqlite3.connect(original.as_uri() + '?mode=ro', uri=True) as old, sqlite3.connect(migrated / 'workspace.db') as new: old.backup(new)
    (migrated / 'workspace.db').chmod(0o600)
    runner.isolated('schema-ten-to-eleven-candidate-init', image, INIT_MIGRATION, mounts=private_only)
    after = release_snapshot(migrated / 'workspace.db', business)
    proof = compare_schema_snapshots(before, after, empty['schema_objects'])
    save(runner.release / 'synthetic-after.json', after); save(runner.release / 'synthetic-schema-validation.json', proof)
    runner.isolated('schema-populated-encrypted-cache', image, SEED_REPORT_CACHE, mounts=private_only)
    populated = release_snapshot(migrated / 'workspace.db', business)
    need(populated['business'] == after['business'] and populated['private']['schema_objects'] == after['private']['schema_objects']
         and all(populated['private']['tables'][name] == after['private']['tables'][name] for name in BASE_TABLES), 'SYNTHETIC_CACHE_SEED_SCOPE_DRIFT')
    runner.isolated('schema-compatible-old-api-startup-read', rollback_image, ROLLBACK_READ, mounts=private_only)
    need(release_snapshot(migrated / 'workspace.db', business) == populated, 'COMPATIBLE_ROLLBACK_API_CHANGED_ROWS_OR_SCHEMA')
    return {'stage': 'STRIPE_REPORT_SYNTHETIC_SCHEMA_AND_ROLLBACK_VERIFIED', 'tables': sorted(TARGET_TABLES),
            'original_tables': sorted(BASE_TABLES),
            'schema_objects': empty['schema_objects'], 'schema_validation_sha256': sha((runner.release / 'synthetic-schema-validation.json').read_bytes()),
            'base_image_id': BASE_IMAGE, 'candidate_image_id': image, 'rollback_image_id': rollback_image,
            'original_rows_columns_indexes_preserved': True, 'new_cache_initially_empty': True,
            'compatible_old_api_started_and_owner_read': True, 'encrypted_existing_credentials_decrypted': True,
            'populated_encrypted_report_cache_preserved': True, 'business_physically_readonly_for_init_and_read': True,
            'business_unchanged': True, 'production_database_access': False}


def regression_code(tools, tests):
    return ("import os,sys,subprocess\n"
        + "subprocess.check_call([sys.executable,'-m','pip','install','--disable-pip-version-check','--no-cache-dir','--no-index','--find-links','/test-wheels','--target','/tmp/test-deps','--no-deps',*" + repr(tools) + "])\n"
        + "os.environ['PYTHONPATH']='/tmp/test-deps:/app:/app/backend'\nsubprocess.check_call([sys.executable,'-c'," + repr(VERIFY_TOOLS) + "])\n"
        + "subprocess.check_call([sys.executable,'-m','pytest',*" + repr(['/app/' + name.removeprefix('app/') for name in tests if not name.endswith('/conftest.py')])
        + ",'-q','--disable-warnings','--tb=short','-p','no:cacheprovider','--junitxml=/test-results/regressions.xml'],cwd='/app/backend')\n")


def prepare(release, manifest, payload, *, frozen_source, payload_sha256, manifest_sha256, freeze_sha256, minimum_tests=None, runner=None):
    """Callable by the new upgrade helper after its fresh baseline validation."""
    os.umask(0o077); protected(release, directory=True)
    checked_payload(manifest, frozen_source, payload_sha256)
    need(sha(payload) == payload_sha256 and HASH.fullmatch(manifest_sha256 or '') and HASH.fullmatch(freeze_sha256 or ''), 'INDEPENDENT_FROZEN_ARTIFACT_HASHES_REQUIRED')
    need(manifest.get('frozen_manifest_sha256') == freeze_sha256, 'FROZEN_SOURCE_BINDING_REQUIRED')
    minimum = frozen_source['backend_regression_tests_minimum']
    need(minimum_tests is None or minimum_tests == minimum, 'REVIEWED_TEST_MINIMUM_DRIFT')
    root = release / 'prepared-backend'; need(not root.exists() and not root.is_symlink(), 'NEW_BACKEND_PREPARATION_REQUIRED'); root.mkdir(mode=0o700)
    runner = runner or Runner(root)
    need(runner.release == root, 'PREPARATION_RUNNER_DIRECTORY_REQUIRED')
    context = root / 'payload'; extract(payload, manifest, context)
    model = (context / 'backend/models/private_workspace.py').read_bytes()
    need(sha(model) == MODEL_SHA and len(model) > BASE_MODEL_BYTES and sha(model[:BASE_MODEL_BYTES]) == BASE_MODEL_SHA, 'ROLLBACK_MODEL_MUST_ONLY_APPEND_REVIEWED_CACHE_CLASS')
    base_inspection = inspect_image(BASE_IMAGE)
    checked_base_runtime(runner.scan('base-python-runtime', BASE_IMAGE, SCAN_RUNTIME))
    base = runner.scan('base-backend', BASE_IMAGE, SCAN_BACKEND)
    need(base.get('models/private_workspace.py') == BASE_MODEL_SHA, 'ACTUAL_RETAINED_MODEL_DRIFT')
    packages = runner.scan('base-packages', BASE_IMAGE, SCAN_PACKAGES); static = runner.scan('base-static', BASE_IMAGE, SCAN_STATIC)
    wheels = BASE_TEST_ROOT / 'test-wheels'
    wheel_manifest = json.loads(frozen_file(BASE_TEST_ROOT / 'test-wheel-manifest.json', BASE_WHEEL_MANIFEST_SHA, 1024**2))
    tools = wheel_tools(wheels, wheel_manifest)
    base_tag = 't24-private-stripe-report-base:' + SOURCE_SHA[:12] + '-' + uuid4().hex[:12]
    exists = subprocess.run(['docker', 'image', 'inspect', base_tag], capture_output=True, timeout=30, check=False)
    need(exists.returncode != 0, 'NEW_EXCLUSIVE_BASE_TAG_REQUIRED')
    runner.run('pin-accepted-base', ['docker', 'tag', BASE_IMAGE, base_tag])
    need(runner.run('base-pin-before-build', ['docker', 'image', 'inspect', '-f', '{{.Id}}', base_tag]).decode().strip() == BASE_IMAGE, 'BASE_PIN_DRIFT')
    images = {}
    for role in ('candidate', 'rollback'):
        tag = 't24-private-stripe-report-' + role + ':' + SOURCE_SHA[:12] + '-' + uuid4().hex[:12]
        exists = subprocess.run(['docker', 'image', 'inspect', tag], capture_output=True, timeout=30, check=False)
        need(exists.returncode != 0, 'NEW_EXCLUSIVE_IMAGE_TAG_REQUIRED')
        recipe_path = root / ('Dockerfile.' + role); write_new(recipe_path, recipe(manifest, base_tag, rollback=role == 'rollback'))
        runner.run(role + '-build', ['docker', 'build', '--pull=false', '--network=none', '--no-cache', '-f', str(recipe_path), '-t', tag, '.'], timeout=600, cwd=context)
        image = runner.run(role + '-image-id', ['docker', 'image', 'inspect', '-f', '{{.Id}}', tag]).decode().strip()
        need(IMAGE.fullmatch(image or '') and image != BASE_IMAGE and image not in images.values(), 'DISTINCT_IMMUTABLE_PREPARED_IMAGES_REQUIRED')
        verify_candidate_base(base_inspection, inspect_image(image))
        need(runner.scan(role + '-backend', image, SCAN_BACKEND) == expected_backend(base, manifest, rollback=role == 'rollback'), 'UNRELATED_BACKEND_BYTES_CHANGED')
        need(runner.scan(role + '-packages', image, SCAN_PACKAGES) == packages, 'RUNTIME_PACKAGE_BYTES_CHANGED')
        need(runner.scan(role + '-static', image, SCAN_STATIC) == static, 'BUNDLED_STATIC_BYTES_CHANGED')
        images[role] = image
    need(runner.run('base-pin-after-build', ['docker', 'image', 'inspect', '-f', '{{.Id}}', base_tag]).decode().strip() == BASE_IMAGE, 'BASE_PIN_DRIFT')
    results = root / 'test-results'; results.mkdir(mode=0o700)
    runner.isolated('all-private-regressions', images['candidate'], regression_code(tools, manifest['private_tests']),
                    mounts=[(wheels, '/test-wheels', True), (results, '/test-results', False)], timeout=600)
    xml_path = results / 'regressions.xml'; value = xml_path.lstat()
    need(stat.S_ISREG(value.st_mode) and value.st_uid == os.geteuid() and value.st_nlink == 1 and not xml_path.is_symlink()
         and not stat.S_IMODE(value.st_mode) & 0o022 and 0 < value.st_size <= 8 * 1024**2, 'PROTECTED_TEST_EVIDENCE_REQUIRED')
    xml_path.chmod(0o600); xml = xml_path.read_bytes(); total = test_report(xml, minimum)
    schema = schema_rehearsal(runner, images['candidate'], images['rollback'], manifest)
    receipt = {'format_version': 1, 'stage': 'STRIPE_REPORT_BACKEND_CANDIDATE_VERIFIED', 'source_sha': SOURCE_SHA,
               'baseline_private_source_sha': BASE_SOURCE, 'base_image_id': BASE_IMAGE, 'image_id': images['candidate'],
               'rollback_image_id': images['rollback'], 'rollback_model_only': True, 'base_layers_verified': True,
               'base_pin_verified_before_and_after_build': True, 'all_other_backend_bytes_identical': True,
               'all_runtime_package_bytes_identical': True, 'bundled_static_bytes_unchanged': True,
               'byte_identity': {'base_backend_sha256': digest(base),
                   'candidate_backend_sha256': digest(expected_backend(base, manifest)),
                   'rollback_backend_sha256': digest(expected_backend(base, manifest, rollback=True)),
                   'runtime_packages': packages, 'bundled_static_sha256': digest(static),
                   'base_layers_sha256': digest(base_inspection['RootFS']['Layers'])},
               'frozen_source_sha256': freeze_sha256, 'payload_manifest_sha256': manifest_sha256, 'payload_sha256': payload_sha256,
               'regressions': {'tests': total, 'minimum': minimum, 'python': BASE_PYTHON_VERSION, 'all_private_tests': manifest['private_tests'],
                   'xml_sha256': sha(xml), 'wheel_manifest_sha256': BASE_WHEEL_MANIFEST_SHA, 'network': 'none'},
               'synthetic_schema': schema, 'production_environment_loaded': False, 'production_database_access': False,
               'production_services_modified': False, 'public_assets_published': False, 'deployed': False}
    save(root / 'candidate.json', receipt)
    return receipt
