"""Additive owner Meta operations release; real operations remain disabled.

The retained, byte-pinned Meta release supplies migration identity, candidate
provenance, forward-only recovery and bounded privacy sentinels. A fresh module
namespace receives this release's reviewed constants; no retained file changes.
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
import socket
import stat
import tarfile
import types

HOST = 'iZj6c4cj7edgnhdimts4l7Z'
SCOPE = 'meta-operations'
SOURCE_SHA = '95588aa2e630784a419704bb4ce3da89965586e6'
FRONTEND = 'd2dbd67fa15d'
APPLICATION_FREEZE_SHA = '6d6e6e75d7db2b4423ce5cc368af97210485a8800da72446b0e8f10a916bd9d9'
PREFLIGHT_SHA = 'f08cc8d90fe726b4fe89b18b0c4018ceed0b0b32c54763e7bb04ace911ed45dc'
ACTUAL_PREFLIGHT_SHA = '3ee6ceadf311ed15fdb63be14461fc0460e2b560a6be422af05a5cd2ec2a4262'
BASE_SOURCE = 'a03766539ef3430f350f467652511a43ee3c4abf'
BASE_FRONTEND = '58d2c585210f'
ACTIVATION_FROM = '2026-10-30T19:42:04Z'
OLD_REVISION = 'bde8da01f247'
NEW_REVISION = 'cefa9b12a358'
MIGRATION = 'alembic/versions/cefa9b12a358_meta_operations.py'
MIGRATIONS = ((MIGRATION, NEW_REVISION, OLD_REVISION),)
NEW_TABLES = frozenset('meta_operations_' + name for name in ('credentials', 'bindings', 'oauth_states', 'media', 'targets', 'drafts', 'actions', 'schedules', 'requests'))
NEW_INDEXES = frozenset({'ix_meta_operations_media_customer_id', 'ix_meta_operations_targets_owner_id', 'ix_meta_operations_bindings_owner_id', 'ix_meta_operations_oauth_states_expires_at', 'ix_meta_operations_credentials_owner_id', 'ix_meta_operations_actions_owner_id', 'uq_meta_ops_active_global_asset', 'uq_meta_ops_active_customer_platform', 'ix_meta_operations_schedules_binding_id', 'ix_meta_operations_bindings_customer_id', 'ix_meta_operations_schedules_planned_at', 'ix_meta_operations_drafts_owner_id', 'ix_meta_operations_media_owner_id', 'ix_meta_operations_schedules_status', 'ix_meta_operations_drafts_binding_id', 'ix_meta_operations_schedules_owner_id', 'ix_meta_operations_targets_binding_id', 'ix_meta_operations_actions_binding_id'})
NEW_TABLE_SHAPES = {'meta_operations_actions': 'b837b84e3db60ad68de21a2710a830ee4cc41bd0495b6b2d3c2bc76219664fdc', 'meta_operations_bindings': '321593fbe0a6a3a78fc0501f83e427127383bde67266a9298dc24f6fd50e5dcf', 'meta_operations_credentials': '68ada61fdaba718a9c11ca178c32ba9730331dd906f2ad5460c9b788cd4884f2', 'meta_operations_drafts': 'a9fef0a13643eec45715a3a17a8d96fbb0b5124932049801cc70f5e8613ee239', 'meta_operations_media': '91c1218e8ff115711975024a687b75c5f30cdf5a830642a50e5b8ed2b75da923', 'meta_operations_oauth_states': 'd8cc159b4a6c1bf76e416c62d4344e0c8a43462efbdfd990a7a695aa62f28753', 'meta_operations_requests': '8e5c6d0391562f70e205621bd81f1edb63852de0ad6c1918b297b468ea564ae5', 'meta_operations_schedules': 'c408b85d8502ad9ced6e2f3c95a14df6ad3fe104eb9f38be497171c631fd55f6', 'meta_operations_targets': 'ae167a6d61cae837d4d008368a3bb752b358d699a10230115f1323e718e32821'}
BACKEND_FILES = frozenset({'requirements.txt', 'routers/meta_operations.py', 'main.py', 'services/meta_operations_provider.py', 'services/meta_operations_scheduler.py', 'services/meta_operations_media.py', 'models/meta_operations.py', 'alembic/versions/cefa9b12a358_meta_operations.py', 'services/meta_operations.py'})
EXISTING_BACKEND_FILES = frozenset({'main.py', 'requirements.txt'})
FRONTEND_FILES = frozenset('app/frontend/src/' + name for name in ('components/MetaBusinessWorkspace.tsx', 'components/MetaOperationsWorkspace.tsx', 'components/meta-operations.css', 'lib/meta-operations-api.ts', 'pages/MediaOperations.tsx'))
TEST_FILES = frozenset({'app/backend/tests/test_meta_operations_provider.py', 'app/frontend/tests/meta-operations-workflow.test.mjs', 'app/frontend/tests/meta-business-workflow.test.mjs', 'app/backend/tests/test_meta_operations.py'})
SOURCE_FILES = frozenset('app/backend/' + name for name in BACKEND_FILES) | FRONTEND_FILES | TEST_FILES
OPS_ROUTES = frozenset({('/api/v1/meta-operations/drafts/{draft_id}/approve', 'POST'), ('/api/v1/meta-operations/requests/{request_id}', 'GET'), ('/api/v1/meta-operations/media/{media_id}/preview', 'GET'), ('/api/v1/meta-operations/drafts/{draft_id}/schedules', 'POST'), ('/api/v1/meta-operations/actions/{action_id}/continue', 'POST'), ('/api/v1/meta-operations/oauth/start', 'POST'), ('/api/v1/meta-operations/delivery/{token}.jpg', 'GET'), ('/api/v1/meta-operations/actions/{action_id}', 'GET'), ('/api/v1/meta-operations/drafts/{draft_id}/publish', 'POST'), ('/api/v1/meta-operations/bindings/{binding_id}/disconnect', 'POST'), ('/api/v1/meta-operations/bindings/{binding_id}/drafts', 'POST'), ('/api/v1/meta-operations/bindings/{binding_id}/media', 'POST'), ('/api/v1/meta-operations/delivery/{token}.jpg', 'HEAD'), ('/api/v1/meta-operations/oauth/callback', 'GET'), ('/api/v1/meta-operations/drafts/{draft_id}', 'PATCH'), ('/api/v1/meta-operations/bindings/{binding_id}/posts', 'GET'), ('/api/v1/meta-operations/drafts/{draft_id}/preview', 'POST'), ('/api/v1/meta-operations/status', 'GET'), ('/api/v1/meta-operations/bindings/{binding_id}/comments', 'GET'), ('/api/v1/meta-operations/oauth/requests/{request_id}', 'GET'), ('/api/v1/meta-operations/bindings/{binding_id}/workspace', 'GET'), ('/api/v1/meta-operations/schedules/{schedule_id}/cancel', 'POST'), ('/api/v1/meta-operations/schedules/{schedule_id}/activate', 'POST')})
ORIGINAL_BACKEND_HASHES = {'main.py': '599d0b38dc0369b5e810ac41496c5b05862aba243fa2a82130fe582c75659524', 'requirements.txt': 'ee434720ed250405427164a42eee2bd76148ace2816ce032d097c638e2bf930f'}
OPS_CALLBACK = '/api/v1/meta-operations/oauth/callback'
OPS_DELIVERY = '/api/v1/meta-operations/delivery/'
OLD_DELIVERY = '/api/v1/media-publication-images/delivery/'
RETAINED_ROOT = Path('/opt/t24-crm/releases/meta-business-6cf69fbe4cbe-20261031')
RETAINED_SHA = 'a14f6d41eb6089e1a124c8326a27031280af4dbc9f58c5a73e797565d0135c98'
WHEEL = 'pillow-12.3.0-cp310-cp310-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl'
WHEEL_MEMBER = 'vendor/' + WHEEL
WHEEL_SHA = 'f0606c8bf2cdefea14a43530f7657cbbb7ecf1c4222512492ef4a4434a9501ec'
WHEEL_BYTES = 6925605
H = lambda body: hashlib.sha256(body).hexdigest()


def need(ok, code):
    if not ok: raise RuntimeError(code)


def digest(value): return H(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())
def encoded(value): return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def pins_ready():
    need(isinstance(SOURCE_SHA, str) and re.fullmatch('[a-f0-9]{40}', SOURCE_SHA) and SOURCE_SHA != '0'*40 and
         isinstance(FRONTEND, str) and re.fullmatch('[a-f0-9]{12}', FRONTEND) and FRONTEND != '0'*12 and
         isinstance(APPLICATION_FREEZE_SHA, str) and re.fullmatch('[a-f0-9]{64}', APPLICATION_FREEZE_SHA) and APPLICATION_FREEZE_SHA != '0'*64,
         'FINAL_SOURCE_FRONTEND_FREEZE_REQUIRED')
    need(isinstance(NEW_INDEXES, frozenset) and bool(NEW_INDEXES) and isinstance(NEW_TABLE_SHAPES, dict) and set(NEW_TABLE_SHAPES) == NEW_TABLES and
         isinstance(BACKEND_FILES, frozenset) and EXISTING_BACKEND_FILES <= BACKEND_FILES and isinstance(FRONTEND_FILES, frozenset) and bool(FRONTEND_FILES) and
         isinstance(TEST_FILES, frozenset) and bool(TEST_FILES) and SOURCE_FILES == frozenset('app/backend/'+name for name in BACKEND_FILES) | FRONTEND_FILES | TEST_FILES and
         isinstance(OPS_ROUTES, frozenset) and bool(OPS_ROUTES) and isinstance(ORIGINAL_BACKEND_HASHES, dict) and set(ORIGINAL_BACKEND_HASHES) == EXISTING_BACKEND_FILES and
         all(re.fullmatch('[a-f0-9]{64}', value) for value in ORIGINAL_BACKEND_HASHES.values()), 'FINAL_SCHEMA_ROUTES_AND_SOURCE_REQUIRED')


def protected_read(path, sha, maximum=1048576):
    path = Path(path)
    for parent in path.parents:
        row = parent.lstat(); need(parent.resolve() == parent and stat.S_ISDIR(row.st_mode) and row.st_uid == 0 and not row.st_mode & 0o022, 'PROTECTED_HELPER_PARENT_REQUIRED')
    prior = path.lstat(); need(path.resolve() == path and stat.S_ISREG(prior.st_mode) and prior.st_uid == 0 and prior.st_nlink == 1 and stat.S_IMODE(prior.st_mode) == 0o600, 'PROTECTED_HELPER_REQUIRED')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream: opened = os.fstat(stream.fileno()); body = stream.read(maximum+1)
    after = path.lstat(); identity = lambda r: (r.st_dev,r.st_ino,r.st_size,r.st_mtime_ns,r.st_ctime_ns,r.st_mode,r.st_uid,r.st_nlink)
    need(identity(prior) == identity(opened) == identity(after) and len(body) <= maximum and H(body) == sha, 'EXACT_REVIEWED_HELPER_BYTES_REQUIRED')
    return body


def local_bytes(path, maximum=16*1024**2):
    path = Path(path); row = path.lstat()
    need(path.resolve() == path.absolute() and stat.S_ISREG(row.st_mode) and row.st_nlink == 1, 'REGULAR_LOCAL_INPUT_REQUIRED')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream: opened = os.fstat(stream.fileno()); body = stream.read(maximum+1)
    after = path.lstat(); identity = lambda r: (r.st_dev,r.st_ino,r.st_size,r.st_mtime_ns,r.st_ctime_ns,r.st_mode,r.st_nlink)
    need(identity(row) == identity(opened) == identity(after) and len(body) <= maximum, 'BOUNDED_LOCAL_INPUT_REQUIRED')
    return body


def validate_summary(value):
    need(value['stage'] == 'META_OPERATIONS_PREFLIGHT_CAPTURED' and value['sha256'] == ACTUAL_PREFLIGHT_SHA and
         value['path'] == '/opt/t24-crm/releases/meta-operations-preflight-'+ACTUAL_PREFLIGHT_SHA[:12]+'.json' and
         value['source_sha'] == BASE_SOURCE and value['frontend_version'] == BASE_FRONTEND and value['schema_revision'] == OLD_REVISION and value['table_count'] == 141 and
         value['crm']['id'] == '4c4085ff201a88ad685ab69d7a85c8615567acdcb2225d529e23b95858997811' and value['crm']['config'] == '81ae2c6ccb2074531929aae8812a5d48806a19a185e515e7ed62b48148b01834' and
         value['google_scheduler_enabled'] is True and value['google_scheduler_activation_from'] == ACTIVATION_FROM and value['meta_operations_environment_absent'] is True,
         'EXACT_CURRENT_META_OWNER_PREFLIGHT_REQUIRED')


def extract_payload(release, manifest, core):
    """Bounded, exact-member extraction; no tar path/link interpretation."""
    expected = manifest['files']; seen = set(); total = 0
    need(len(expected) <= 10000 and WHEEL_MEMBER in expected and expected[WHEEL_MEMBER] == WHEEL_SHA, 'EXACT_OFFLINE_WHEEL_REQUIRED')
    with tarfile.open(release/'payload.tar.gz', 'r:gz') as archive:
        for item in archive:
            need(item.isfile() and item.name in expected and item.name not in seen and 0 < item.size <= 16*1024**2, 'EXACT_REGULAR_PAYLOAD_MEMBER_REQUIRED')
            path = Path(item.name); need(not path.is_absolute() and '..' not in path.parts and str(path) == item.name, 'CANONICAL_PAYLOAD_MEMBER_REQUIRED')
            total += item.size; need(total <= 100*1024**2, 'BOUNDED_EXTRACTED_PAYLOAD_REQUIRED')
            stream = archive.extractfile(item); need(stream is not None, 'PAYLOAD_STREAM_REQUIRED')
            body = stream.read(item.size+1); need(len(body) == item.size and H(body) == expected[item.name], 'EXACT_PAYLOAD_MEMBER_HASH_REQUIRED')
            parent = release
            for part in path.parts[:-1]: parent = parent/part; core.mkdir(parent)
            core.write(release/path, body); seen.add(item.name)
    need(seen == set(expected), 'COMPLETE_EXACT_PAYLOAD_REQUIRED')


def added_nginx(retained, original):
    """Copy existing protected blocks, changing only their exact route names."""
    updated, callback = retained.meta_callback_nginx(original)
    text, blocks = retained.nginx_blocks(updated)
    need(OPS_DELIVERY not in text, 'OPERATIONS_DELIVERY_MUST_START_ABSENT')
    servers = [row for row in blocks if row['header'] == ['server'] and any(item[0]=='server_name' and 't24-crm.com' in item[1:] for item in row['directives']) and any(item[0]=='listen' and any(v=='443' or v.endswith(':443') for v in item[1:]) for item in row['directives'])]
    need(len(servers)==1,'EXACT_CRM_DELIVERY_SERVER_REQUIRED')
    rows = [row for row in blocks if row['parent'] is servers[0] and row['header'] == ['location','^~',OLD_DELIVERY]]
    need(len(rows) == 1, 'EXACT_PROTECTED_DELIVERY_TEMPLATE_REQUIRED'); row = rows[0]
    need(not any(child['parent'] is row for child in blocks) and ['access_log','off'] in row['directives'] and ['error_log','/dev/null','crit'] in row['directives'], 'PROTECTED_DELIVERY_TEMPLATE_REQUIRED')
    passes = [value for value in row['directives'] if value[0] == 'proxy_pass']
    need(len(passes) == 1 and len(passes[0]) == 2 and re.fullmatch(r'http://127[.]0[.]0[.]1:[0-9]{2,5}',passes[0][1]), 'EXACT_LOOPBACK_MEDIA_UPSTREAM_REQUIRED')
    position = text.rfind('\n',0,row['start'])+1
    need(not text[position:row['start']].strip(), 'INLINE_DELIVERY_TEMPLATE_REJECTED')
    block = text[position:row['end']]; need(block.count(OLD_DELIVERY) == 1 and block.count('location') == 1, 'SINGLE_DELIVERY_TEMPLATE_REQUIRED')
    added = block.replace(OLD_DELIVERY,OPS_DELIVERY,1)+'\n\n'
    result = (text[:position]+added+text[position:]).encode()
    need(result.replace(added.encode(),b'',1).replace(callback,b'',1) == original, 'ONLY_TWO_PROTECTED_BLOCK_COPIES_ALLOWED')
    return result, (callback,added.encode())


def next_nginx(retained, original, old_root, new_root):
    old,new = os.fsencode(str(old_root)),os.fsencode(str(new_root))
    need(original.count(old) == 1 and new not in original, 'EXACT_SINGLE_STATIC_ROOT_REQUIRED')
    result, added = added_nginx(retained, original); result = result.replace(old,new,1)
    normalized = result.replace(new,old,1)
    for block in reversed(added): normalized = normalized.replace(block,b'',1)
    need(normalized == original, 'OTHER_NGINX_BYTES_CHANGED')
    return result


def _load(args):
    pf = types.ModuleType('_current_meta_operations_preflight'); pf.__file__ = str(args.release/'preflight.py')
    exec(compile(protected_read(args.release/'preflight.py',PREFLIGHT_SHA),pf.__file__,'exec'),pf.__dict__)
    core,_,ctx = pf.dependencies()
    retained = types.ModuleType('_isolated_retained_meta_operations_release'); retained.__file__ = str(RETAINED_ROOT/'release.py')
    exec(compile(core.read(RETAINED_ROOT/'release.py',sha=RETAINED_SHA),retained.__file__,'exec'),retained.__dict__)
    old_routes = retained.META_ROUTES
    for name,value in {'SOURCE_SHA':SOURCE_SHA,'FRONTEND':FRONTEND,'APPLICATION_FREEZE_SHA':APPLICATION_FREEZE_SHA,'PREFLIGHT_SHA':PREFLIGHT_SHA,
        'BASE_SOURCE':BASE_SOURCE,'BACKEND_SOURCE':BASE_SOURCE,'BASE_FRONTEND':BASE_FRONTEND,'SCOPE':SCOPE,'OLD_REVISION':OLD_REVISION,'NEW_REVISION':NEW_REVISION,
        'MIGRATION':MIGRATION,'MIGRATIONS':MIGRATIONS,'NEW_TABLES':NEW_TABLES,'NEW_INDEXES':NEW_INDEXES,'NEW_TABLE_SHAPES':NEW_TABLE_SHAPES,
        'BACKEND_FILES':BACKEND_FILES,'EXISTING_BACKEND_FILES':EXISTING_BACKEND_FILES,'FRONTEND_FILES':FRONTEND_FILES,'TEST_FILES':TEST_FILES,'SOURCE_FILES':SOURCE_FILES,
        'META_ROUTES':OPS_ROUTES,'META_CALLBACK':OPS_CALLBACK,'DELIVERY_PREFIX':OPS_DELIVERY}.items(): setattr(retained,name,value)
    original_callback_headers = retained.callback_headers
    def callback_headers(body):
        need(b'Location: /media-ops?meta_ops=failed' in body or b'location: /media-ops?meta_ops=failed' in body, 'EXACT_OPERATIONS_FAILURE_REDIRECT_REQUIRED')
        return original_callback_headers(body.replace(b'/media-ops?meta_ops=failed',b'/media-ops?meta=failed'))
    retained.callback_headers = callback_headers
    return pf,core,ctx,retained,old_routes


class OperationsMethods:
    def __init__(self,args,pf,core,ctx,retained,old_routes):
        self.args,self.pf,self.core,self.ctx,self.retained,self.old_meta_routes = args,pf,core,ctx,retained,old_routes
        self.helper,self.m,self.base,self.safe,self.w,self.static,_ = ctx.ctx.pf.dependencies()
        self.proof = core.strict_json(core.read(args.preflight,sha=args.preflight_sha256))
        self.manifest = core.strict_json(core.read(args.release/'manifest.json',sha=args.manifest_sha256))
        core.read(args.release/'payload.tar.gz',maximum=16*1024**2,sha=args.payload_sha256)
        self.source,self.version = SOURCE_SHA,FRONTEND
        self.public = Path('/var/www/t24-crm-public/'+SCOPE+'-'+SOURCE_SHA[:12]+'-20261101')
        need(args.release == Path('/opt/t24-crm/releases/'+SCOPE+'-'+SOURCE_SHA[:12]+'-20261101'), 'EXACT_RELEASE_NAMESPACE_REQUIRED')
        self.validate(); m=self.m
        self.pins = core.strict_json(m.read(self.base.PRIVATE_PINS,self.base.PRIVATE_PINS_SHA))
        self.pf.google_environment = ctx.ctx.pf.google_environment
        self.pf.meta_environment = self.meta_environment
        self.pf.security_headers = ctx.ctx.pf.security_headers
        self.pf.ACTIVATION_FROM = ACTIVATION_FROM
        self.old_name='t24-crm-before-'+SCOPE+'-'+SOURCE_SHA[:12]
        self.candidate_name='t24-crm-candidate-'+SCOPE+'-'+SOURCE_SHA[:12]
        self.offline_name='t24-'+SCOPE+'-probe-'+SOURCE_SHA[:12]
        m.SOURCE,m.SCOPE,m.BACKEND=SOURCE_SHA,SCOPE,set(BACKEND_FILES)
        m.BASELINE_FRONTEND,m.FRONTEND_VERSION=BASE_FRONTEND,FRONTEND
        m.PUBLIC,m.NGINX_SHA,m.STATIC_SHA=Path(self.proof['public_root']),self.proof['nginx_sha256'],self.proof['public_inventory_sha256']
        m.OLD_ID,m.BASE_IMAGE,m.OLD_CONFIG=(self.proof['crm'][key] for key in ('id','image','config'))
        m.public_root=lambda:self.public
        m.next_nginx=lambda original:next_nginx(retained,original,self.proof['public_root'],self.public)
        self.base.OLD_REVISION,self.base.NEW_REVISION,self.base.MIGRATION=OLD_REVISION,NEW_REVISION,MIGRATION
        self.base.migration_script=retained.migration_script

    def validate(self):
        p,v,a=self.proof,self.manifest,self.args
        need(p['stage']=='META_OPERATIONS_READONLY_PREFLIGHT' and p['source_sha']==BASE_SOURCE and p['frontend_version']==BASE_FRONTEND and p['schema_revision']==OLD_REVISION and len(p['rows'])==141 and not NEW_TABLES.intersection(p['rows']), 'EXACT_CURRENT_141_TABLE_BASELINE_REQUIRED')
        need(p['google_scheduler_enabled'] is True and p['google_scheduler_activation_from']==ACTIVATION_FROM and p['meta_operations_environment_absent'] is True and all(p[key] is False for key in ('credential_file_content_read','private_content_read','business_writes','provider_requests','runtime_changed')), 'READONLY_PRESERVING_BASELINE_REQUIRED')
        need(v['source_sha']==SOURCE_SHA and v['frontend_version']==FRONTEND and v['baseline_source_sha']==BASE_SOURCE and v['baseline_frontend_version']==BASE_FRONTEND and v['schema_revision']==NEW_REVISION and v['old_schema_revision']==OLD_REVISION and v['additive_tables']==sorted(NEW_TABLES), 'EXACT_SOURCE_SCHEMA_REQUIRED')
        need(v['application_freeze_sha256']==APPLICATION_FREEZE_SHA and set(v['changed_source_files'])==SOURCE_FILES and len(v['changed_source_files'])==len(SOURCE_FILES), 'EXACT_SOURCE_FREEZE_DELTA_REQUIRED')
        need(v['preflight_sha256']==a.preflight_sha256==ACTUAL_PREFLIGHT_SHA and v['payload_sha256']==a.payload_sha256 and v['database_migration'] is True and v['existing_meta_environment_preserved'] is True and v['ops_environment_keys_absent'] is True and all(v[key] is False for key in ('credentials_included','runtime_environment_changed','production_seed_rows','ops_feature_enabled','ops_execution_enabled','ops_scheduler_enabled')), 'EXACT_DISABLED_OPERATIONS_SCOPE_REQUIRED')
        need(set(v['backend_before'])==set(v['backend_after'])==BACKEND_FILES and v['backend_before']=={name:ORIGINAL_BACKEND_HASHES.get(name) for name in BACKEND_FILES}, 'EXACT_EXISTING_AND_NEW_BACKEND_MEMBERS_REQUIRED')
        need({name[8:] for name in v['files'] if name.startswith('backend/')}==BACKEND_FILES and all(v['files']['backend/'+name]==v['backend_after'][name] for name in BACKEND_FILES), 'EXACT_BACKEND_HASHES_REQUIRED')
        need(v['files'].get(WHEEL_MEMBER)==WHEEL_SHA and all(re.fullmatch('[a-f0-9]{64}',value) for value in v['files'].values()) and all(name==WHEEL_MEMBER or name.startswith('backend/') and name[8:] in BACKEND_FILES or name.startswith('static/') and self.m.static_path(name[7:]) for name in v['files']), 'EXACT_STATIC_BACKEND_WHEEL_PAYLOAD_REQUIRED')
        need({'static/index.html','static/app-version.json'}<=set(v['files']), 'COMPLETE_FRONTEND_REQUIRED')

    def meta_environment(self,info):
        env=info['Config']['Env']
        need(not any(row.split('=',1)[0].startswith('T24_META_OPS_') for row in env), 'OPERATIONS_ENVIRONMENT_MUST_REMAIN_ABSENT')
        selected=[row for row in env if row.split('=',1)[0].startswith('T24_META_')]
        self.core.validate_meta_env(selected)
        need(digest(selected)==self.proof['meta_environment_sha256'] and digest(env)==self.proof['environment_sha256'], 'EXACT_ALL_CURRENT_ENVIRONMENT_VALUES_AND_ORDER_REQUIRED')

    def nginx(self,updated=False):
        m,p=self.m,self.proof;body=m.NGINX.read_bytes();active=m.run(['nginx','-T'],'ACTIVE_NGINX_REQUIRED');observed=H(active)
        if updated:
            original=m.read(self.args.release/'nginx-before.conf',p['nginx_sha256']);_,blocks=added_nginx(self.retained,original)
            for block in reversed(blocks):
                need(body.count(block)==active.count(block)==1,'EXACT_ADDED_PRIVACY_BLOCK_REQUIRED');body=body.replace(block,b'',1);active=active.replace(block,b'',1)
            old,new=os.fsencode(p['public_root']),os.fsencode(str(self.public))
            need(body.count(new)==active.count(new)==1,'EXACT_SINGLE_NEW_PUBLIC_ROOT_REQUIRED');body=body.replace(new,old,1);active=active.replace(new,old,1)
        need(H(body)==p['nginx_sha256'] and H(active)==p['active_nginx_sha256'],'OTHER_NGINX_CONFIGURATION_DRIFT')
        return observed

    def protections(self,*,updated=False,head=OLD_REVISION,recovery=False,schema=None):
        m,p=self.m,self.proof;self.private_boundary()
        need(m.credential_boundary()==p['credential_boundary'] and self.safe.protected_metadata(self.safe.GBP_ENV)==p['google_credential_metadata'] and self.safe.protected_metadata(self.core.ENV_FILE)==p['meta_credential_metadata'] and self.safe.protected_metadata(self.core.LEGACY_ENV_FILE)==p['legacy_meta_credential_metadata'],'EXISTING_CREDENTIAL_METADATA_DRIFT')
        row=m.BUSINESS.stat();need([row.st_dev,row.st_ino]==p['database_identity'],'BUSINESS_DATABASE_INODE_DRIFT')
        (self.retained.sequence_boundary(p['database_metadata'],self.metadata(m.BUSINESS),recovery=True) if recovery else self.retained.live_sequence_boundary(p['database_metadata'],self.metadata(m.BUSINESS)))
        need(m.schema_signature(m.BUSINESS,head)==(p['schema_sha256'] if head==OLD_REVISION else schema),'EXACT_SCHEMA_DRIFT')
        need(digest(m.tree(m.PUBLIC))==p['public_inventory_sha256'],'OLD_STATIC_CONTENT_DRIFT');self.nginx(updated)

    def current(self):
        m,p=self.m,self.proof;self.protections();old=m.inspect('t24-crm')
        need(old['State']['Running'] is True and m.runtime(old)==p['crm'],'CURRENT_RUNTIME_DRIFT')
        self.pf.google_environment(old);self.meta_environment(old);m.verify_secret_mount(old);m.verify_production_worker_enabled(old);m.retained().require_safe_original_restart(old)
        inventory=m.inventory(old['Id']);need(digest(inventory)==p['backend_inventory_sha256'] and len(inventory)==p['backend_file_count'] and all(inventory.get(name)==value for name,value in ORIGINAL_BACKEND_HASHES.items()) and not (BACKEND_FILES-EXISTING_BACKEND_FILES).intersection(inventory),'CURRENT_BACKEND_SOURCE_DRIFT')
        need(self.retained.evidence(self.rows())==p['rows'],'CURRENT_BUSINESS_ROWS_DRIFT');m.ready(old['Id']);return old,inventory

    def image(self):
        m=self.m;need(m.image_id(m.BASE_IMAGE)==m.BASE_IMAGE,'EXACT_BASE_IMAGE_REQUIRED')
        wheel=self.args.release/WHEEL_MEMBER;need(H(self.core.read(wheel,maximum=WHEEL_BYTES,sha=WHEEL_SHA))==WHEEL_SHA and wheel.stat().st_size==WHEEL_BYTES,'EXACT_OFFICIAL_PILLOW_WHEEL_REQUIRED')
        base='t24-crm:'+SCOPE+'-base-'+SOURCE_SHA[:12];prior=m.image_id(base);need(prior is None or prior==m.BASE_IMAGE,'BASE_TAG_DRIFT')
        if prior is None:m.run(['docker','image','tag',m.BASE_IMAGE,base],'BASE_TAG_FAILED')
        dockerfile='FROM '+base+'\nCOPY '+WHEEL_MEMBER+' /tmp/'+WHEEL+'\nRUN python -m pip install --no-index --no-deps --disable-pip-version-check /tmp/'+WHEEL+'\n'+''.join('COPY backend/'+name+' /app/backend/'+name+'\n' for name in sorted(BACKEND_FILES))
        m.write(self.args.release/'Dockerfile',dockerfile.encode());m.write(self.args.release/'.dockerignore',b'*\n!Dockerfile\n!backend\n!backend/**\n!vendor\n!vendor/**\n')
        tag='t24-crm:'+SCOPE+'-'+SOURCE_SHA[:12];m.run(['docker','build','--network=none','--pull=false','-t',tag,str(self.args.release)],'OFFLINE_WHEEL_BUILD_FAILED',300)
        image=m.image_id(tag);need(m.image_id(base)==m.BASE_IMAGE and re.fullmatch('sha256:[a-f0-9]{64}',image or ''),'EXACT_BUILT_IMAGE_REQUIRED');return image

    def offline_args(self,data,image):
        command=self.base.Release.offline_args(self,data,image)
        command[-1:-1]=['-e','T24_GBP_SCHEDULER_ACTIVATION_FROM=','-e','T24_META_OPS_ENABLED=false','-e','T24_META_OPS_EXECUTION_ENABLED=false','-e','T24_META_OPS_SCHEDULER_ENABLED=false']
        return command

    def route_probe(self):
        expected={'/api/v1/google-business':('routers.google_business',self.base.GBP_ROUTES|{('/api/v1/google-business/bindings/{binding_id}/review','GET'),('/api/v1/google-business/bindings/{binding_id}/readiness','GET')}),
                  '/api/v1/media-operations':('routers.media_operations',self.base.MEDIA_ROUTES),'/api/v1/media-publication-images':('routers.media_publication_images',self.retained.IMAGE_ROUTES),
                  '/api/v1/media-planning':('routers.media_planning',self.retained.PLANNING_ROUTES),'/api/v1/meta-business':('routers.meta_business',self.old_meta_routes),'/api/v1/meta-operations':('routers.meta_operations',OPS_ROUTES)}
        return "import socket\ndef blocked(*a,**k):raise AssertionError('NO_PROVIDER_NETWORK')\nsocket.socket.connect=blocked\nfrom main import app\nimport fastapi.routing\nexpected="+repr(expected)+"\nschema=app.openapi()\ncontexts=list(fastapi.routing.iter_route_contexts(app.routes)) if hasattr(fastapi.routing,'iter_route_contexts') else app.routes\nfor prefix,(module,methods) in expected.items():\n hidden={(prefix+'/delivery/{token}.png',m) for m in ('GET','HEAD')} if prefix=='/api/v1/media-publication-images' else {(prefix+'/delivery/{token}.jpg',m) for m in ('GET','HEAD')} if prefix=='/api/v1/meta-operations' else set()\n actual={(p,m.upper()) for p,v in schema['paths'].items() if p.startswith(prefix) for m in v if m.lower() in {'get','post','put','patch','delete','head','options','trace'}}\n assert actual==methods-hidden\n registered=[(x.path,m,getattr(getattr(x,'endpoint',None),'__module__',''),getattr(x,'include_in_schema',True)) for x in contexts if getattr(x,'path','').startswith(prefix) for m in (getattr(x,'methods',set()) or set())]\n assert len(registered)==len(methods) and {(p,m) for p,m,_,_ in registered}==methods and all(mod==module for _,_,mod,_ in registered)\n assert all(visible is False for p,m,_,visible in registered if (p,m) in hidden)\nprint('EXACT_OPERATIONS_AND_EXISTING_ROUTES')\n"

    def operations_disabled_probe(self):
        return "import os,socket\ndef blocked(*a,**k):raise AssertionError('NO_PROVIDER_NETWORK')\nsocket.socket.connect=blocked\nfrom services.meta_operations_provider import enabled,execution_enabled,settings\nassert enabled() is False and execution_enabled() is False and settings()[1]\nfrom services.meta_operations_scheduler import enabled as scheduler\nassert scheduler() is False\nassert all(not os.environ.get('T24_META_OPS_'+k) for k in ('APP_ID','APP_SECRET','TOKEN_KEY','CONFIG_ID'))\nprint('EXACT_OPERATIONS_UNCONFIGURED_OFF_NO_NETWORK')\n"

    def meta_disabled_probe(self):
        return "import os,socket\ndef blocked(*a,**k):raise AssertionError('NO_PROVIDER_NETWORK')\nsocket.socket.connect=blocked\nassert not any(k.startswith('T24_META_') and not k.startswith('T24_META_OPS_') for k in os.environ)\nfrom services.meta_business_provider import enabled,settings\nassert enabled() is False and settings()[1]\nprint('EXACT_META_ABSENT_DISABLED_NO_NETWORK')\n"

    def owner_denied_probe(self):
        # Synthetic authenticated roles; never authenticate as a real employee
        # and never query the copied customer/credential tables. Any accidental
        # SQL or provider access fails the process rather than being hidden.
        return """import asyncio,socket
from types import SimpleNamespace
def blocked(*a,**k):raise AssertionError('NO_PROVIDER_NETWORK')
socket.socket.connect=blocked
import httpx
from fastapi import FastAPI
from routers.meta_operations import router
from dependencies.auth import get_current_user
from core.database import get_db
class NoDb:
 def __getattr__(self,name):raise AssertionError('NONOWNER_MUST_NOT_QUERY_DATABASE')
async def database():yield NoDb()
actor=SimpleNamespace(id='2147483647',role='sales',email='synthetic-role-probe@invalid.local')
async def user():return actor
app=FastAPI();app.include_router(router)
app.dependency_overrides[get_db]=database;app.dependency_overrides[get_current_user]=user
async def check():
 async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://t24-crm.com',follow_redirects=False) as client:
  for role in ('sales','finance'):
   actor.role=role
   for path in ('/status','/bindings/1/workspace','/bindings/1/posts','/actions/1','/media/'+'0'*32+'/preview'):
    response=await client.get('/api/v1/meta-operations'+path)
    assert response.status_code==403
    assert set(response.json())=={'detail'} and response.headers['referrer-policy']=='no-referrer'
asyncio.run(check())
print('EXACT_NONOWNER_ROLE_READ_DENIED_NO_SQL_OR_NETWORK')
"""

    def active_probe(self):
        return self.retained.Release.active_probe(self)+"from services.meta_business_provider import enabled as meta,settings as metas\nassert meta() is True and not metas()[1]\nfrom services.meta_operations_provider import enabled as ops,execution_enabled\nfrom services.meta_operations_scheduler import enabled as opworker\nassert ops() is False and execution_enabled() is False and opworker() is False\n"

    def prepare(self):
        self.helper.docker_timestamp_probe();m,a=self.m,self.args;old,before=self.current()
        need({p.name for p in a.release.iterdir()}=={'release.py','preflight.py','manifest.json','payload.tar.gz'},'FRESH_STAGING_REQUIRED')
        extract_payload(a.release,self.manifest,self.core);expected={**before,**self.manifest['backend_after']}
        original_sha=self.record('original-runtime.json',m.runtime(old));before_sha=self.record('backend-original-inventory.json',before);after_sha=self.record('backend-candidate-inventory.json',expected)
        image=self.image();data=a.release/'probe-data';data.mkdir(mode=0o700);(a.release/'probe-logs').mkdir(mode=0o700)
        m.backup(m.BUSINESS,data/'crm_prod.db');rows=self.rows(data/'crm_prod.db');metadata=self.metadata(data/'crm_prod.db')
        need(self.retained.evidence(rows)==self.proof['rows'] and m.schema_signature(data/'crm_prod.db',OLD_REVISION)==self.proof['schema_sha256'],'ISOLATED_COPY_DRIFT')
        self.retained.live_sequence_boundary(self.proof['database_metadata'],metadata);before_objects=self.retained.objects(data/'crm_prod.db')
        self.run_migration(data,image);schema=self.new_schema(data/'crm_prod.db');migrated=self.rows(data/'crm_prod.db')
        self.retained.additive_objects(before_objects,self.retained.objects(data/'crm_prod.db'));self.retained.compare_original(rows,migrated);self.retained.sequence_boundary(metadata,self.metadata(data/'crm_prod.db'))
        need(not m.inspect_optional(self.offline_name),'FRESH_OFFLINE_NAME_REQUIRED');command=self.offline_args(data,image);command[2:2]=['--name',self.offline_name,'-d'];m.run(command,'OFFLINE_START_FAILED')
        try:
            m.ready(self.offline_name);self.base.verify_disabled_environment(m.inspect(self.offline_name));need(m.inventory(self.offline_name)==expected,'OFFLINE_BACKEND_SOURCE_DRIFT')
            checks=[("import sys,PIL;assert sys.version_info[:2]==(3,10) and PIL.__version__=='12.3.0';print('EXACT_PYTHON310_PILLOW')",b'EXACT_PYTHON310_PILLOW'),(self.route_probe(),b'EXACT_OPERATIONS_AND_EXISTING_ROUTES'),(self.base.gbp_disabled_probe(),b'EXACT_GBP_DISABLED_UNCONFIGURED_NO_NETWORK'),(self.meta_disabled_probe(),b'EXACT_META_ABSENT_DISABLED_NO_NETWORK'),(self.operations_disabled_probe(),b'EXACT_OPERATIONS_UNCONFIGURED_OFF_NO_NETWORK'),(self.owner_denied_probe(),b'EXACT_NONOWNER_ROLE_READ_DENIED_NO_SQL_OR_NETWORK')]
            for code,marker in checks:need(marker in m.run(['docker','exec',self.offline_name,'python','-B','-c',code],'OFFLINE_PROBE_FAILED'),'EXACT_OFFLINE_MARKER_REQUIRED')
        finally:m.run(['docker','stop','--time','20',self.offline_name],'OFFLINE_STOP_FAILED',45)
        need(self.rows(data/'crm_prod.db')==migrated and self.new_schema(data/'crm_prod.db')==schema and self.metadata(data/'crm_prod.db')==metadata,'OFFLINE_STARTUP_CHANGED_DATABASE')
        root,static=m.stage_public(a.release,self.manifest);next_sha=H(m.next_nginx(m.NGINX.read_bytes()));self.current()
        result={'stage':'META_OPERATIONS_PREPARED_OFFLINE_VERIFIED','source_sha':SOURCE_SHA,'frontend_version':FRONTEND,'old_schema_revision':OLD_REVISION,'schema_revision':NEW_REVISION,'schema_after_sha256':schema,'old_crm':m.runtime(old),'candidate_image':image,'preflight_sha256':a.preflight_sha256,'manifest_sha256':a.manifest_sha256,'payload_sha256':a.payload_sha256,'original_runtime_sha256':original_sha,'original_inventory_sha256':before_sha,'candidate_inventory_sha256':after_sha,'public_root':str(root),'public_inventory_sha256':static,'nginx_next_sha256':next_sha,'original_table_count':141,'new_table_count':150,'additive_tables':sorted(NEW_TABLES),'pillow_wheel_sha256':WHEEL_SHA,
            'offline_additive_only':True,'offline_original_rows_unchanged':True,'offline_new_tables_empty':True,'offline_own_metadata_exact':True,'actual_python310_pillow_verified':True,'exact_routes_verified':True,'offline_nonowner_role_denied_without_sql':True,'offline_network_none':True,'offline_credentials_absent':True,'offline_workers_off':True,'google_on_cutoff_preserved':True,'existing_meta_environment_preserved':True,'operations_env_absent':True,'operations_execution_disabled':True,'operations_scheduler_disabled':True,'new_callback_and_delivery_privacy_prepared':True,'provider_requests':False,'production_database_migrated':False,'credential_values_journaled':False,'sequence_written_by_tool':False}
        return {**result,'receipt_sha256':self.record('prepared.json',result)}

    def reviewed(self):
        m,a=self.m,self.args;need(re.fullmatch('[a-f0-9]{64}',a.review_sha256 or ''),'CANONICAL_PREPARED_REVIEW_REQUIRED')
        r=self.core.strict_json(m.read(a.release/'prepared.json',a.review_sha256))
        validate_prepared(r,a.manifest_sha256,a.payload_sha256,a.preflight_sha256)
        runtime=self.core.strict_json(m.read(a.release/'original-runtime.json',r['original_runtime_sha256']));old=m.inspect(runtime['id'])
        before=self.core.strict_json(m.read(a.release/'backend-original-inventory.json',r['original_inventory_sha256']));expected=self.core.strict_json(m.read(a.release/'backend-candidate-inventory.json',r['candidate_inventory_sha256']))
        need(m.runtime(old)==runtime==r['old_crm']==self.proof['crm'] and digest(before)==self.proof['backend_inventory_sha256'] and expected=={**before,**self.manifest['backend_after']},'EXACT_PREPARED_RUNTIME_AND_SOURCE_REQUIRED')
        need(m.image_id(r['candidate_image'])==r['candidate_image'] and m.verify_public(self.public,self.manifest)==r['public_inventory_sha256'],'EXACT_PREPARED_IMAGE_AND_STATIC_REQUIRED')
        return r,old,before,expected

    def accept(self,r,old,before,expected,state,baseline,*,updated,recovery=False):
        _,candidate=self.fresh(r,old,before,expected,state,migrated=True,updated=updated,live=True,baseline=baseline,recovery=recovery)
        need(b'EXACT_EXISTING_ON_WORKER_CUTOFF_NO_NETWORK' in self.m.run(['docker','exec',candidate['Id'],'python','-B','-c',self.active_probe()],'LIVE_EXISTING_META_GOOGLE_PROBE_FAILED'),'LIVE_EXISTING_META_GOOGLE_MARKER_REQUIRED')
        need(b'EXACT_OPERATIONS_UNCONFIGURED_OFF_NO_NETWORK' in self.m.run(['docker','exec',candidate['Id'],'python','-B','-c',self.operations_disabled_probe()],'LIVE_OPERATIONS_OFF_PROBE_FAILED'),'LIVE_OPERATIONS_OFF_MARKER_REQUIRED')
        need(self.m.verify_public(self.public,self.manifest)==r['public_inventory_sha256'],'LIVE_PUBLIC_STATIC_DRIFT')
        return self.fresh(r,old,before,expected,state,migrated=True,updated=updated,live=True,baseline=baseline,recovery=recovery)[1]

    def delivery_sentinel(self,candidate_id):
        # Keep all retained provenance/log-bounds checks; the new route serves
        # JPEG rather than the old PNG. Rewrite only the noncapability GET/HEAD
        # probe URL, never a real media lease or any other command.
        original_run=self.m.run
        def jpeg_probe(argv,code,*args,**kwargs):
            if code=='NONCAPABILITY_SENTINEL_REQUEST_FAILED':
                need(argv[-1].startswith('https://t24-crm.com'+OPS_DELIVERY+'t24_noncapability_probe_') and argv[-1].endswith('.png') and '--max-redirs' in argv and '--resolve' in argv,'EXACT_RETAINED_NONCAPABILITY_PROBE_REQUIRED')
                argv=[*argv[:-1],argv[-1][:-4]+'.jpg']
            return original_run(argv,code,*args,**kwargs)
        self.m.run=jpeg_probe
        try:return self.retained.Release.delivery_sentinel(self,candidate_id)
        finally:self.m.run=original_run

    def activate(self):
        m,a=self.m,self.args;r,old,before,expected=self.reviewed();self.current()
        need(not(a.release/'activation-started.json').exists() and not m.inspect_optional(self.old_name) and not m.inspect_optional(self.candidate_name),'FRESH_SWITCH_REQUIRED')
        original=m.NGINX.read_bytes();need(H(m.next_nginx(original))==r['nginx_next_sha256'],'EXACT_REVIEWED_NGINX_REQUIRED')
        self.record('nginx-before.conf',original);self.record('activation-started.json',{'source_sha':SOURCE_SHA,'review_sha256':a.review_sha256,'original_id':old['Id'],'candidate_image':r['candidate_image']})
        status,body=m.retained().docker_request('POST','/containers/create?name='+self.candidate_name,m.clone_config(r['candidate_image'],old));need(status==201,'CANDIDATE_CREATE_FAILED')
        identity=json.loads(body)['Id'];need(re.fullmatch('[a-f0-9]{64}',identity),'EXACT_CREATED_ID_REQUIRED')
        self.record('candidate-created.json',{'source_sha':SOURCE_SHA,'candidate_id':identity,'candidate_image':r['candidate_image'],'original_id':old['Id'],'review_sha256':a.review_sha256});state=self.state(r,old)
        try:
            _,candidate=self.fresh(r,old,before,expected,state)
            need(candidate['State']['Status']=='created' and candidate['State'].get('StartedAt') in {'','0001-01-01T00:00:00Z','0001-01-01T00:00:00.000000000Z'},'NEVER_STARTED_CANDIDATE_REQUIRED')
            m.run(['docker','stop','--time','30',old['Id']],'ORIGINAL_STOP_FAILED',60);retained,_=self.fresh(r,old,before,expected,state);need(retained['State']['Running'] is False,'ORIGINAL_STOPPED_REQUIRED')
            baseline=self.rows();need(self.retained.evidence(baseline)==self.proof['rows'],'STOPPED_ORIGINAL_ROWS_DRIFT')
            baseline_sha=self.record('production-before-rows.json',baseline);self.record('production-baseline-identity.json',{'source_sha':SOURCE_SHA,'original_id':old['Id'],'candidate_id':identity,'review_sha256':a.review_sha256,'rows_sha256':baseline_sha})
            self.run_migration(m.BUSINESS.parent,r['candidate_image']);self.retained.compare_original(baseline,self.rows());need(self.new_schema(m.BUSINESS)==r['schema_after_sha256'],'PRODUCTION_ADDITIVE_SCHEMA_DRIFT')
            self.fresh(r,old,before,expected,state,migrated=True,baseline=baseline)
            m.run(['docker','rename',old['Id'],self.old_name],'ORIGINAL_RENAME_FAILED');m.run(['docker','rename',identity,'t24-crm'],'CANDIDATE_RENAME_FAILED')
            self.fresh(r,old,before,expected,state,migrated=True,baseline=baseline);m.run(['docker','start',identity],'CANDIDATE_START_FAILED');m.ready(identity)
            self.accept(r,old,before,expected,state,baseline,updated=False)
            m.replace_nginx(original,m.next_nginx(original));m.retained().reload_nginx();candidate=self.accept(r,old,before,expected,state,baseline,updated=True);sentinels=self.public_check(identity)
            candidate=self.accept(r,old,before,expected,state,baseline,updated=True)
            result={'stage':'META_OPERATIONS_DEPLOYED_OFF_VERIFIED','deployed':True,'source_sha':SOURCE_SHA,'frontend_version':FRONTEND,'schema_revision':NEW_REVISION,'schema_sha256':r['schema_after_sha256'],'crm':m.runtime(candidate),'original_id':old['Id'],'preflight_sha256':a.preflight_sha256,'prepared_sha256':a.review_sha256,'candidate_inventory_sha256':r['candidate_inventory_sha256'],'public_root':str(self.public),'public_inventory_sha256':r['public_inventory_sha256'],'nginx_sha256':H(m.NGINX.read_bytes()),'all_141_original_rows_preserved_except_reviewed_schema_head':True,'nine_new_operations_tables_empty':True,'google_on_cutoff_preserved':True,'old_meta_nine_env_and_owner_connections_bindings_preserved':True,'all_environment_order_mounts_network_preserved':True,'private_boundary_preserved':True,'operations_environment_absent':True,'operations_execution_enabled':False,'operations_scheduler_enabled':False,'external_publish_or_reply_performed':False,'provider_requests_by_deployment':False,'credential_values_journaled':False,'database_restored':False,'production_containers_deleted':False,**sentinels}
            return {**result,'receipt_sha256':self.record('deployed.json',result)}
        except BaseException:self.recover_internal(r,old,before,expected);raise

    def recover_internal(self,*args):
        result=self.retained.Release.recover_internal(self,*args)
        result={**result,'stage':result['stage'].replace('META_BUSINESS_','META_OPERATIONS_'),'operations_execution_enabled':False,'operations_scheduler_enabled':False}
        self.record('operations-recovery-result.json',result);return result


def validate_prepared(value,manifest,payload,preflight):
    need(value['stage']=='META_OPERATIONS_PREPARED_OFFLINE_VERIFIED' and value['source_sha']==SOURCE_SHA and value['frontend_version']==FRONTEND and value['schema_revision']==NEW_REVISION and value['old_schema_revision']==OLD_REVISION and value['original_table_count']==141 and value['new_table_count']==150 and value['additive_tables']==sorted(NEW_TABLES),'EXACT_PREPARED_RELEASE_REQUIRED')
    need(value['manifest_sha256']==manifest and value['payload_sha256']==payload and value['preflight_sha256']==preflight==ACTUAL_PREFLIGHT_SHA and value['pillow_wheel_sha256']==WHEEL_SHA,'EXACT_PREPARED_IDENTITIES_REQUIRED')
    need(all(isinstance(value.get(key),str) and re.fullmatch('[a-f0-9]{64}',value[key]) for key in ('schema_after_sha256','original_runtime_sha256','original_inventory_sha256','candidate_inventory_sha256','public_inventory_sha256','nginx_next_sha256')) and re.fullmatch('sha256:[a-f0-9]{64}',value.get('candidate_image','')) and value.get('public_root')=='/var/www/t24-crm-public/'+SCOPE+'-'+SOURCE_SHA[:12]+'-20261101','EXACT_PREPARED_RUNTIME_STATIC_AND_SCHEMA_HASHES_REQUIRED')
    need(all(value[key] is True for key in ('offline_additive_only','offline_original_rows_unchanged','offline_new_tables_empty','offline_own_metadata_exact','actual_python310_pillow_verified','exact_routes_verified','offline_nonowner_role_denied_without_sql','offline_network_none','offline_credentials_absent','offline_workers_off','google_on_cutoff_preserved','existing_meta_environment_preserved','operations_env_absent','operations_execution_disabled','operations_scheduler_disabled','new_callback_and_delivery_privacy_prepared')) and all(value[key] is False for key in ('provider_requests','production_database_migrated','credential_values_journaled','sequence_written_by_tool')),'EXACT_OFFLINE_ACCEPTANCE_REQUIRED')


def Release(args):
    pins_ready();pf,core,ctx,retained,old_routes=_load(args)
    return type('GuardedMetaOperationsRelease',(OperationsMethods,retained.Release),{})(args,pf,core,ctx,retained,old_routes)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=['prepare','activate','recover'],required=True)
    parser.add_argument('--release',type=Path,required=True);parser.add_argument('--manifest-sha256',required=True);parser.add_argument('--payload-sha256',required=True)
    parser.add_argument('--preflight',type=Path,required=True);parser.add_argument('--preflight-sha256',required=True);parser.add_argument('--review-sha256');args=parser.parse_args()
    pins_ready();need(os.geteuid()==0 and socket.gethostname()==HOST,'EXACT_ROOT_SERVER_REQUIRED');resource.setrlimit(resource.RLIMIT_CORE,(0,0));os.umask(0o077)
    need(args.release.resolve()==args.release and args.release.parent==Path('/opt/t24-crm/releases'),'EXACT_PROTECTED_RELEASE_PATH_REQUIRED')
    for parent in (args.release,*args.release.parents):
        row=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_RELEASE_PARENT_REQUIRED')
    need(stat.S_IMODE(args.release.lstat().st_mode)==0o700 and args.preflight_sha256==ACTUAL_PREFLIGHT_SHA and args.preflight==Path('/opt/t24-crm/releases/meta-operations-preflight-'+ACTUAL_PREFLIGHT_SHA[:12]+'.json'),'EXACT_ACTUAL_PROOF_AND_PRIVATE_RELEASE_REQUIRED')
    need(all(re.fullmatch('[a-f0-9]{64}',value) for value in (args.manifest_sha256,args.payload_sha256,args.preflight_sha256)) and (args.phase!='prepare' or args.review_sha256 is None),'EXACT_PHASE_ARGUMENTS_REQUIRED')
    fd=os.open('/opt/t24-crm/releases/.meta-operations-release.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        row=os.fstat(fd);need(stat.S_ISREG(row.st_mode) and row.st_uid==0 and row.st_nlink==1 and stat.S_IMODE(row.st_mode)==0o600,'PROTECTED_RELEASE_LOCK_REQUIRED');fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        print(json.dumps(getattr(Release(args),args.phase)(),sort_keys=True))
    finally:os.close(fd)


if __name__=='__main__':
    try:main()
    except BaseException as error:
        message=str(error);code=message if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',message) else 'META_OPERATIONS_RELEASE_REJECTED'
        print(json.dumps({'stage':'META_OPERATIONS_RELEASE_REJECTED','code':code,'database_restored':False}));raise SystemExit(1)
