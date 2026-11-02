"""Guarded 165→169 additive release with an explicit live-write frontier.

All old rows/sequences are compared after writer stop and before candidate start.
After start, existing workers remain enabled and may legitimately update old
business rows. No production row is seeded/restored and no flag is changed.
"""
import argparse,copy,fcntl,hashlib,io,json,os,re,resource,socket,stat,tarfile,types
from pathlib import Path
HOST='iZj6c4cj7edgnhdimts4l7Z'
SCOPE='media-unified-settings'
SOURCE_SHA = '54e027aad00e81a4ebb747ada1299e7a10e1ec52'
FRONTEND = '32a580644502'
PREFLIGHT_SHA = '0dd43fefcf43ee7c925cbf825b3d88fb125abe1168f3adde9478ba603205dc83'
FREEZE_SHA = '741cab247da5f316d946e76fb8fddda5cd92e46788b12a1ede835d822ef6e333'
PREFLIGHT_CODE_SHA='89f9685f829f96c94f1fe3c84f07b33f604948f375fc52edbb963feaadb76669'
BASE_SOURCE='c78b50a11e020674ad53b34fbbfb5b1badd4a9a5'
BASE_FRONTEND='569fa342f1c3'
OLD_REVISION='h43fe567f803'
NEW_REVISION='i54af678a914'
MIGRATION='alembic/versions/i54af678a914_media_automation_settings.py'
NEW_TABLES=frozenset({'media_automation_setting_versions','media_automation_template_versions','media_automation_settings_previews','media_automation_settings_receipts'})
NEW_INDEXES={('ix_media_automation_setting_versions_owner_id','media_automation_setting_versions'),('ix_media_automation_setting_versions_customer_id','media_automation_setting_versions'),('ix_media_automation_template_versions_owner_id','media_automation_template_versions'),('ix_media_automation_settings_previews_owner_id','media_automation_settings_previews'),('ix_media_automation_settings_receipts_owner_id','media_automation_settings_receipts')}
BACKEND_SCOPE=frozenset({'services/media_monthly.py','services/media_monthly_automation.py','services/media_monthly_editorial.py',MIGRATION,'models/media_automation_settings.py','routers/media_automation_settings.py','schemas/media_automation_settings.py','services/media_automation_settings.py'})
BACKEND_BEFORE = {'alembic/versions/i54af678a914_media_automation_settings.py': None, 'models/media_automation_settings.py': None, 'routers/media_automation_settings.py': None, 'schemas/media_automation_settings.py': None, 'services/media_automation_settings.py': None, 'services/media_monthly.py': '129a4752fb54c3299c1da799cba457671f2441474ea6f1db15f832cbf004699d', 'services/media_monthly_automation.py': '3b431233f665bd8cbae629cf965f66848270525a5ac9b22f1065457e2d47d06b', 'services/media_monthly_editorial.py': '5753761a0526aa81cf11f883f558d51201adfb517e6e68ad6486bc29b8957751'}
BACKEND_AFTER = {'alembic/versions/i54af678a914_media_automation_settings.py': '29146c5673cfce364eb1b868de25695c3815f02f40cbfc044f0000cf12e78bce', 'models/media_automation_settings.py': '3ec119125b27200aa75dd7df12e5c0d1f8416dbb444ffd6c0c118053adaab32a', 'routers/media_automation_settings.py': 'b5389eb5dc797b9c10d3ea8aa9b864a6735dd2ddf880aebaf719a7225feca622', 'schemas/media_automation_settings.py': 'c478c561476b4b6a943e371e1d12c57b8e17f6e5942c889dd1bda88eb055dbe6', 'services/media_automation_settings.py': '6bd889b58064194759c16beb91e73a408db85b0f33424f938194dd09990971ec', 'services/media_monthly.py': '21e079775d89bc6c97110c474786872508c05bd28ae40112f08fb2e3c3c5248a', 'services/media_monthly_automation.py': '04545a23eb1b6a2a3cdd7f718faca080118092bc6789e7e1ab98064f137e34ef', 'services/media_monthly_editorial.py': '91bcb1e27c5f955ed94a09b24a06f3970a59f9ecbcee8f0ce14e7f53053e6220'}
SOURCE_FILES = {'app/backend/alembic/versions/i54af678a914_media_automation_settings.py': '29146c5673cfce364eb1b868de25695c3815f02f40cbfc044f0000cf12e78bce', 'app/backend/models/media_automation_settings.py': '3ec119125b27200aa75dd7df12e5c0d1f8416dbb444ffd6c0c118053adaab32a', 'app/backend/routers/media_automation_settings.py': 'b5389eb5dc797b9c10d3ea8aa9b864a6735dd2ddf880aebaf719a7225feca622', 'app/backend/schemas/media_automation_settings.py': 'c478c561476b4b6a943e371e1d12c57b8e17f6e5942c889dd1bda88eb055dbe6', 'app/backend/services/media_automation_settings.py': '6bd889b58064194759c16beb91e73a408db85b0f33424f938194dd09990971ec', 'app/backend/services/media_monthly.py': '21e079775d89bc6c97110c474786872508c05bd28ae40112f08fb2e3c3c5248a', 'app/backend/services/media_monthly_automation.py': '04545a23eb1b6a2a3cdd7f718faca080118092bc6789e7e1ab98064f137e34ef', 'app/backend/services/media_monthly_editorial.py': '91bcb1e27c5f955ed94a09b24a06f3970a59f9ecbcee8f0ce14e7f53053e6220', 'app/backend/tests/test_media_automation_settings.py': 'ff09109393fc13f6671251514df0354712c8a00a21cdbdb5e008b40cae5f329a', 'app/backend/tests/test_media_monthly_editorial.py': 'e3d4ec229e649b5ce483a7dea2d1b333400a796a9f42534d446999482579e67d', 'app/frontend/src/components/MediaMerchantWorkspace.tsx': '8a8b0c4ddbedd642ebd060f22d67e82ffa5ed13f3a3e6a2999e8562a622cd6e5', 'app/frontend/src/components/MediaMonthlyWorkspace.tsx': 'f3d95599771b542a46c2b47205469951955d871a5914042f81fc72a93dacb3a8', 'app/frontend/src/components/MediaUnifiedAutomationSettings.tsx': '2987977b2e75c48001f39a05222aab1a5df31841b26249d4fb02446bd1ecc293', 'app/frontend/src/components/media-unified-automation-settings.css': 'fe808df63e660dc9dd6d2035c98f2ef6f4c8b89c2519c6189184038e57510c8b', 'app/frontend/src/lib/media-automation-settings-api.ts': '1885b3858fde29436e3e9a3097dd12c08bf67e38dcec8ff07c6061dde0fe04b5', 'app/frontend/src/lib/media-monthly-api.ts': '338bb94d6b848b11514ba7b8f145a5a3085ae85f21101c8913c995f438e97f7a', 'app/frontend/tests/media-automation-settings.test.mjs': '25798e87a724b64db40771883a8378c8d187625322a9005a0177ff46c1d68991'}
H=lambda b:hashlib.sha256(b).hexdigest()
def need(ok,code):
    if not ok:raise RuntimeError(code)
def encoded(v):return (json.dumps(v,sort_keys=True,indent=2)+'\n').encode()
def digest(v):return H(json.dumps(v,sort_keys=True,separators=(',',':')).encode())
def strict_json(body):
    def pairs(rows):
        v={}
        for k,x in rows:need(k not in v,'DUPLICATE_JSON_KEY_REJECTED');v[k]=x
        return v
    def constant(v):raise RuntimeError('NONFINITE_JSON_REJECTED')
    return json.loads(body,object_pairs_hook=pairs,parse_constant=constant)
def protected(path,sha=None,maximum=16777216):
    need(path.is_absolute() and path.resolve()==path,'CANONICAL_ROOT_PRIVATE_PATH_REQUIRED')
    for parent in path.parents:
        row=parent.lstat();need(stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_PARENT_REQUIRED')
    before=path.lstat();need(stat.S_ISREG(before.st_mode) and before.st_uid==0 and before.st_nlink==1 and stat.S_IMODE(before.st_mode)==0o600 and 0<before.st_size<=maximum,'ROOT600_FILE_REQUIRED')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as f:opened=os.fstat(f.fileno());body=f.read(maximum+1);after=os.fstat(f.fileno())
    identity=lambda r:(r.st_dev,r.st_ino,r.st_uid,r.st_mode,r.st_nlink,r.st_size,r.st_mtime_ns,r.st_ctime_ns)
    need(identity(before)==identity(opened)==identity(after)==identity(path.lstat()) and len(body)==before.st_size and (sha is None or H(body)==sha),'EXACT_IMMUTABLE_FILE_BYTES_REQUIRED');return body
def pins_ready():
    need(re.fullmatch('[a-f0-9]{40}',SOURCE_SHA or '') and SOURCE_SHA not in {BASE_SOURCE,'0'*40} and re.fullmatch('[a-f0-9]{12}',FRONTEND or '') and FRONTEND!='0'*12,'FINAL_APPLICATION_PINS_REQUIRED')
    need(all(re.fullmatch('[a-f0-9]{64}',v or '') and v!='0'*64 for v in (PREFLIGHT_SHA,FREEZE_SHA,PREFLIGHT_CODE_SHA)),'FINAL_BASELINE_FREEZE_REQUIRED')
    need(set(BACKEND_BEFORE)==set(BACKEND_AFTER)==BACKEND_SCOPE and all(re.fullmatch('[a-f0-9]{64}',v or '') for v in BACKEND_AFTER.values()) and bool(SOURCE_FILES),'EXACT_BACKEND_OVERLAY_REQUIRED')
def validate_manifest(v,payload):
    pins_ready();need(v['stage']=='MEDIA_UNIFIED_SETTINGS_PAYLOAD' and v['source_sha']==SOURCE_SHA and v['frontend_version']==FRONTEND and v['baseline_source_sha']==BASE_SOURCE and v['old_schema_revision']==OLD_REVISION and v['schema_revision']==NEW_REVISION,'EXACT_UNIFIED_SETTINGS_SOURCE_REQUIRED')
    need(v['preflight_sha256']==PREFLIGHT_SHA and v['freeze_sha256']==FREEZE_SHA and v['payload_sha256']==payload and v['backend_before']==BACKEND_BEFORE and v['backend_after']==BACKEND_AFTER and v['source_files']==SOURCE_FILES and set(v['new_tables'])==NEW_TABLES,'EXACT_FROZEN_MEMBERS_REQUIRED')
    need(all(v[k] is False for k in ('dependencies_changed','credentials_included','environment_changed','worker_flags_changed','production_seed_rows','provider_requests','permissions_changed')),'NO_FLAGS_SEED_PERMISSIONS_PROVIDER_CHANGES_ALLOWED')
def compare_definitions(before,after,*,migrated=False):
    left={tuple(row[:3]):row[3] for row in before};right={tuple(row[:3]):row[3] for row in after};need(len(left)==len(before) and len(right)==len(after) and all(right.get(k)==v for k,v in left.items()),'ORIGINAL165_SCHEMA_OBJECT_CHANGED')
    new={('table',name,name) for name in NEW_TABLES}|{('index',name,table) for name,table in NEW_INDEXES};need(set(right)-set(left)==(new if migrated else set()),'ONLY_FOUR_TABLES_FIVE_INDEXES_ALLOWED')
def compare_rows(before,after,*,migrated=False):
    need(set(after)==set(before)|(NEW_TABLES if migrated else set()),'EXACT_ORIGINAL165_PLUS_FOUR_TABLES_REQUIRED')
    for name,old in before.items():
        cur=after[name];need(cur['shape_sha256']==old['shape_sha256'],'ORIGINAL165_TABLE_SHAPE_CHANGED')
        if name=='alembic_version' and migrated:need(cur['count']==1 and cur['rows_sha256']==H(json.dumps([NEW_REVISION]).encode()),'EXACT_NEW_HEAD_ROW_REQUIRED')
        else:need(cur==old,'ORIGINAL165_BUSINESS_ROWS_CHANGED_BEFORE_START')
    if migrated:need(all(after[name]['count']==0 for name in NEW_TABLES),'FOUR_NEW_SETTINGS_TABLES_MUST_START_EMPTY')
def next_nginx(body,old,new,expected):
    a=('root '+str(old)+';').encode();b=('root '+str(new)+';').encode();need(H(body)==expected and body.count(a)==1 and b not in body,'EXACT_EXISTING_PUBLIC_ROOT_REQUIRED');value=body.replace(a,b,1);need(value.replace(b,a,1)==body,'ONLY_PUBLIC_ROOT_SUBSTITUTION_ALLOWED');return value
def migration_script():
    return f'''import importlib.util,sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
engine=sa.create_engine('sqlite:///file:/app/backend/data/crm_prod.db?mode=rw&uri=true')
with engine.connect() as c:
 c.exec_driver_sql('BEGIN IMMEDIATE')
 assert c.exec_driver_sql('SELECT version_num FROM alembic_version').fetchall()==[({OLD_REVISION!r},)]
 seq=c.exec_driver_sql('SELECT name,seq FROM sqlite_sequence ORDER BY name').fetchall()
 pragmas=[c.exec_driver_sql('PRAGMA '+n).fetchone() for n in ('user_version','application_id')]
 spec=importlib.util.spec_from_file_location('reviewed_settings_migration','/app/backend/{MIGRATION}')
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 assert module.revision=={NEW_REVISION!r} and module.down_revision=={OLD_REVISION!r}
 with Operations.context(MigrationContext.configure(c)):module.upgrade()
 assert c.exec_driver_sql('SELECT name,seq FROM sqlite_sequence ORDER BY name').fetchall()==seq
 assert [c.exec_driver_sql('PRAGMA '+n).fetchone() for n in ('user_version','application_id')]==pragmas
 assert c.exec_driver_sql("UPDATE alembic_version SET version_num='{NEW_REVISION}' WHERE version_num='{OLD_REVISION}'").rowcount==1
 c.commit()
print('EXACT_FOUR_EMPTY_UNIFIED_SETTINGS_TABLES')
'''

class Release:
    def __init__(self,args):
        pins_ready();self.args=args;self.root=args.release;need(self.root==Path('/opt/t24-crm/releases/'+SCOPE+'-'+SOURCE_SHA[:12]+'-20261102'),'EXACT_NEW_RELEASE_NAMESPACE_REQUIRED')
        code=protected(self.root/'preflight.py',PREFLIGHT_CODE_SHA,131072);pf=types.ModuleType('_unified_baseline_once');pf.__file__=str(self.root/'preflight.py');exec(compile(code,pf.__file__,'exec'),pf.__dict__);self.pf=pf;self.base_module,self.base,self.inventory=pf.dependencies();self.m=self.base.m
        old=types.ModuleType('_unified_published_pure_census');old.__file__=str(pf.OLD/'at_write_release.py');exec(compile(pf.read(pf.OLD/'at_write_release.py',pf.CONTROLLER,131072),old.__file__,'exec'),old.__dict__);self.census=old
        self.proof=strict_json(protected(args.preflight,PREFLIGHT_SHA,1048576));self.manifest=strict_json(protected(self.root/'manifest.json',args.manifest_sha256,1048576));protected(self.root/'payload.tar.gz',args.payload_sha256);p=self.proof;v=self.manifest
        need(args.preflight==pf.ROOT/('media-unified-settings-baseline-'+PREFLIGHT_SHA[:12]+'.json') and p['stage']=='MEDIA_UNIFIED_SETTINGS_READONLY_BASELINE' and p['source_sha']==BASE_SOURCE and p['schema_revision']==OLD_REVISION and p['crm']==pf.RUNTIME and p['backend_inventory']==self.inventory and len(p['rows'])==165,'EXACT_CURRENT427_165_BASELINE_REQUIRED');validate_manifest(v,args.payload_sha256)
        need({name[8:] for name in v['files'] if name.startswith('backend/')}==BACKEND_SCOPE and all(name in {'backend/'+n for n in BACKEND_SCOPE} or name.startswith('static/') and self.m.static_path(name[7:]) for name in v['files']) and all(re.fullmatch('[a-f0-9]{64}',s or '') for s in v['files'].values()) and all(v['files']['backend/'+name]==sha and self.inventory.get(name)==BACKEND_BEFORE[name] for name,sha in BACKEND_AFTER.items()),'EXACT_RUNTIME_STATIC_PAYLOAD_REQUIRED')
        row=self.root.lstat();need(stat.S_ISDIR(row.st_mode) and row.st_uid==0 and stat.S_IMODE(row.st_mode)==0o700,'ROOT_PRIVATE_RELEASE_DIRECTORY_REQUIRED')
        self.old_public=Path(p['public_root']);self.public=Path('/var/www/t24-crm-public/'+SCOPE+'-'+SOURCE_SHA[:12]+'-20261102');self.old_name='t24-crm-before-'+SCOPE+'-'+SOURCE_SHA[:12];self.candidate_name='t24-crm-candidate-'+SCOPE+'-'+SOURCE_SHA[:12];self.offline_name='t24-'+SCOPE+'-probe-'+SOURCE_SHA[:12];self.baseline=None;self.prepared=None
        m=self.m;m.SOURCE,m.SCOPE,m.BACKEND=SOURCE_SHA,SCOPE,set(BACKEND_SCOPE);m.PUBLIC,m.STATIC_SHA,m.NGINX_SHA=self.old_public,p['public_inventory_sha256'],p['nginx_sha256'];m.OLD_ID,m.BASE_IMAGE,m.OLD_CONFIG=(p['crm'][k] for k in ('id','image','config'));m.FRONTEND_VERSION=FRONTEND;m.public_root=lambda:self.public
    def record(self,name,value):
        sha=self.m.write(self.root/name,value);fd=os.open(self.root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(fd)
        finally:os.close(fd)
        return sha
    def record_once(self,name,value):
        path=self.root/name
        if path.exists():body=protected(path);need(strict_json(body)==value,'EXISTING_RECOVERY_RECORD_CHANGED');return H(body)
        return self.record(name,value)
    def rows(self,path=None):return self.base.rows(path or self.m.BUSINESS)
    def definitions(self,path=None):return self.pf.table_definitions(path or self.m.BUSINESS)
    def metadata(self,path=None):return self.base.c.metadata(path or self.m.BUSINESS)
    def environment(self,info):
        env,ordered=self.pf.environment(self.base,info);need(env==self.proof['environment_sha256'] and ordered==self.proof['ordered_environment_sha256'],'ALL_EXISTING_ORDERED_ENVIRONMENT_FLAGS_CHANGED')
    def nginx(self,updated=False):
        body=self.m.NGINX.read_bytes();active=self.m.run(['nginx','-T'],'ACTIVE_NGINX_READ_FAILED');observed=H(active)
        if updated:
            a,b=os.fsencode(self.public),os.fsencode(self.old_public);need(body.count(a)==active.count(a)==1,'EXACT_NEW_STATIC_ROOT_REQUIRED');body=body.replace(a,b,1);active=active.replace(a,b,1)
        need(H(body)==self.proof['nginx_sha256'] and H(active)==self.proof['active_nginx_sha256'],'NGINX_HEADERS_PROXY_PRIVACY_CHANGED');return observed
    def shape(self,path=None,*,migrated=False,empty=True):
        path=path or self.m.BUSINESS;head=NEW_REVISION if migrated else OLD_REVISION;compare_definitions(self.proof['table_definitions'],self.definitions(path),migrated=migrated);schema=self.m.schema_signature(path,head)
        if not migrated:need(schema==self.proof['schema_sha256'],'ORIGINAL165_SCHEMA_CHANGED')
        elif self.prepared:need(schema==self.prepared['schema_after_sha256'],'REVIEWED169_SCHEMA_CHANGED')
        if migrated and empty:
            rows=self.rows(path);need(all(rows[name]['count']==0 for name in NEW_TABLES),'NEW_SETTINGS_TABLES_NOT_EMPTY')
        return schema
    def immutable(self,*,migrated=False,updated=False,recovery=False):
        p,c,m=self.proof,self.base.c,self.m;need(c.safe.safe_private_boundary(m,c.pins)==p['private_boundary'],'PRIVATE_BOUNDARY_CHANGED');credentials={'ops':c.safe.protected_metadata(c.c.ENV_FILE),'google':c.safe.protected_metadata(c.safe.GBP_ENV),'meta_read':c.safe.protected_metadata(c.ctx.workflow.core.ENV_FILE),'meta_legacy':c.safe.protected_metadata(c.ctx.workflow.core.LEGACY_ENV_FILE)}
        need(credentials==p['credential_metadata'] and m.credential_boundary()==p['credential_boundary'],'CREDENTIAL_METADATA_CHANGED');need([m.BUSINESS.stat().st_dev,m.BUSINESS.stat().st_ino]==p['database_identity'],'DATABASE_INODE_CHANGED');schema=self.shape(migrated=migrated,empty=not recovery);meta=self.metadata();need(meta['pragma_sha256']==p['database_metadata']['pragma_sha256'] and meta['sequence_exists'] is p['database_metadata']['sequence_exists'],'IMMUTABLE_DATABASE_PRAGMAS_CHANGED');need(digest(m.tree(self.old_public))==p['public_inventory_sha256'],'OLD_STATIC_BYTES_CHANGED');self.nginx(updated);return schema
    def writer_census(self,allowed=()):return self.census.Methods.writer_census(self,allowed)
    def current(self):
        self.immutable();old=self.m.inspect('t24-crm');need(old['State']['Running'] is True and self.m.runtime(old)==self.proof['crm'] and self.m.inventory(old['Id'])==self.inventory,'CURRENT427_RUNTIME_SOURCE_CHANGED');self.environment(old);self.writer_census((old['Id'],));return old
    def snapshot(self,path=None):
        path=path or self.m.BUSINESS;return {'rows':self.rows(path),'table_definitions':self.definitions(path),'database_metadata':self.metadata(path),'schema_sha256':self.m.schema_signature(path,OLD_REVISION),'database_identity':[path.stat().st_dev,path.stat().st_ino]}
    def compare_before_start(self,before,path=None,*,migrated=False):
        path=path or self.m.BUSINESS;compare_rows(before['rows'],self.rows(path),migrated=migrated);compare_definitions(before['table_definitions'],self.definitions(path),migrated=migrated);self.base.c.retained.sequence_boundary(before['database_metadata'],self.metadata(path));return self.shape(path,migrated=migrated)
    def extract(self):
        seen=set();total=0
        with tarfile.open(fileobj=io.BytesIO(protected(self.root/'payload.tar.gz',self.args.payload_sha256)),mode='r:gz') as archive:
            for member in archive:
                need(member.isfile() and member.name in self.manifest['files'] and member.name not in seen and 0<member.size<=16777216,'EXACT_UNIQUE_REGULAR_MEMBER_REQUIRED');seen.add(member.name);total+=member.size;need(total<=67108864,'BOUNDED_PAYLOAD_REQUIRED');body=archive.extractfile(member).read(member.size+1);need(len(body)==member.size and H(body)==self.manifest['files'][member.name],'EXACT_MEMBER_BYTES_REQUIRED');parent=self.root
                for part in Path(member.name).parts[:-1]:parent/=part;self.base.c.c.mkdir(parent)
                self.m.write(self.root/member.name,body)
        need(seen==set(self.manifest['files']),'COMPLETE_PAYLOAD_REQUIRED')
    def image(self):
        m=self.m;need(m.image_id(m.BASE_IMAGE)==m.BASE_IMAGE,'EXACT_BASE_IMAGE_REQUIRED');base='t24-crm:'+SCOPE+'-base-'+SOURCE_SHA[:12];prior=m.image_id(base);need(prior is None or prior==m.BASE_IMAGE,'BASE_TAG_CHANGED')
        if prior is None:m.run(['docker','image','tag',m.BASE_IMAGE,base],'BASE_TAG_FAILED')
        m.write(self.root/'Dockerfile',('FROM '+base+'\n'+''.join('COPY backend/'+name+' /app/backend/'+name+'\n' for name in sorted(BACKEND_SCOPE))).encode());m.write(self.root/'.dockerignore',b'*\n!Dockerfile\n!backend\n!backend/**\n');tag='t24-crm:'+SCOPE+'-'+SOURCE_SHA[:12]
        result=self.base.c.flow.flow.flow.pf.dependencies()[0].capture_public_build(['/usr/bin/env','DOCKER_BUILDKIT=0','docker','build','--network=none','--pull=false','-t',tag,str(self.root)],self.root/'app-build-public.log');self.record('app-build-result.json',result);need(result['exit_code']==0 and result['build_daemon_result_known'],'ISOLATED_IMAGE_BUILD_FAILED');image=m.image_id(tag);need(re.fullmatch('sha256:[a-f0-9]{64}',image or '') and m.image_id(base)==m.BASE_IMAGE,'EXACT_CANDIDATE_IMAGE_REQUIRED');return image
    def offline_args(self,data,image):
        adapter=copy.copy(self.base);adapter.args=self.args;return adapter.offline_args(data,image)
    def migration_identity(self,data):
        phase='production' if data==self.m.BUSINESS.parent else 'offline';return phase,self.root/('migration-'+phase+'-container.json')
    def settle_migration(self,data,image):
        phase,path=self.migration_identity(data)
        if not path.exists():return None
        saved=strict_json(protected(path));info=self.m.inspect(saved['id']);row=(data/'crm_prod.db').stat();need(saved=={'id':info['Id'],'name':'t24-'+SCOPE+'-migration-'+SOURCE_SHA[:12]+'-'+phase,'image':image,'phase':phase,'source_sha':SOURCE_SHA,'database_identity':[row.st_dev,row.st_ino]} and info['Image']==image and info['Name']=='/'+saved['name'] and info['Config']['Cmd']==['python','-B','-c',migration_script()] and info['HostConfig']['ReadonlyRootfs'] is True,'EXACT_MIGRATION_IDENTITY_IMAGE_COMMAND_REQUIRED');self.base.verify_offline(info)
        mounts={(v.get('Source'),v.get('Destination'),v.get('RW')) for v in info.get('Mounts',[]) if v.get('Type')=='bind'};need(mounts=={(str(data),'/app/backend/data',True),(str(self.root/'probe-logs'),'/app/backend/logs',True)} and all(v.get('Type')=='bind' or v.get('Type')=='tmpfs' and v.get('Destination')=='/tmp' for v in info.get('Mounts',[])),'EXACT_MIGRATION_MOUNTS_REQUIRED')
        if info['State']['Running']:self.m.run(['docker','wait',info['Id']],'MIGRATION_WAIT_INCOMPLETE',95);info=self.m.inspect(info['Id'])
        need(not info['State']['Running'],'MIGRATION_EXIT_REQUIRED');return info
    def run_migration(self,data,image):
        phase,path=self.migration_identity(data);need(not path.exists(),'MIGRATION_ALREADY_ATTEMPTED_REQUIRES_RECOVERY');name='t24-'+SCOPE+'-migration-'+SOURCE_SHA[:12]+'-'+phase;need(self.m.inspect_optional(name) is None,'FRESH_MIGRATION_NAME_REQUIRED');command=self.offline_args(data,image);command[1]='create';command.remove('--rm');command[2:2]=['--name',name];identity=self.m.run(command+['python','-B','-c',migration_script()],'MIGRATION_CREATE_FAILED',30).decode().strip();need(re.fullmatch('[a-f0-9]{64}',identity),'EXACT_CREATED_MIGRATION_ID_REQUIRED');row=(data/'crm_prod.db').stat();self.record(path.name,{'id':identity,'name':name,'image':image,'phase':phase,'source_sha':SOURCE_SHA,'database_identity':[row.st_dev,row.st_ino]});self.settle_migration(data,image);self.m.run(['docker','start',identity],'MIGRATION_START_FAILED');self.m.run(['docker','wait',identity],'MIGRATION_WAIT_INCOMPLETE',95);info=self.settle_migration(data,image);need(info['State']['Status']=='exited' and info['State']['ExitCode']==0,'MIGRATION_PROCESS_FAILED')
    def canary(self):
        return """import asyncio,socket,sys
from types import SimpleNamespace
from fastapi import HTTPException
def blocked(*a,**k):raise AssertionError('NO_PROVIDER_NETWORK')
socket.socket.connect=blocked
assert sys.version_info[:2]==(3,10)
from services.media_monthly_automation import enabled
assert enabled() is False
from main import app
import fastapi.routing
prefix='/api/v1/media-automation-settings'
expected={(prefix+'/templates','GET'),(prefix+'/templates','POST'),(prefix+'/customers','GET'),(prefix+'/customers/{customer_id}','GET'),(prefix+'/previews','POST'),(prefix+'/previews/{preview_id}/apply','POST'),(prefix+'/requests/{request_id}','GET')}
schema=app.openapi();actual={(p,m.upper()) for p,v in schema['paths'].items() if p.startswith(prefix) for m in v if m.lower() in {'get','post','put','patch','delete'}}
assert actual==expected
contexts=list(fastapi.routing.iter_route_contexts(app.routes)) if hasattr(fastapi.routing,'iter_route_contexts') else app.routes
registered=[(x.path,m,getattr(getattr(x,'endpoint',None),'__module__','')) for x in contexts if getattr(x,'path','').startswith(prefix) for m in (getattr(x,'methods',set()) or set())]
assert len(registered)==7 and {(p,m) for p,m,_ in registered}==expected and all(mod=='routers.media_automation_settings' for _,_,mod in registered)
from services import media_automation_settings as service
class NoDb:
 def __getattr__(self,k):raise AssertionError('NONOWNER_MUST_NOT_QUERY_DATABASE')
async def denied():
 for role in ('sales','finance','operations','admin','customer_service'):
  for write in (False,True):
   try:await service.context(NoDb(),SimpleNamespace(id='2147483647',role=role),42,write=write)
   except HTTPException as error:assert error.status_code==403
   else:raise AssertionError('SETTINGS_OWNER_ONLY_REQUIRED')
asyncio.run(denied())
print('EXACT_UNIFIED_SETTINGS_SEVEN_ROUTES_OWNER_ONLY_WORKERS_OFF')
"""
    def prepare(self):
        old=self.current();need({p.name for p in self.root.iterdir()}=={'release.py','preflight.py','manifest.json','payload.tar.gz'},'FRESH_STAGING_REQUIRED');self.extract();image=self.image();expected={**self.inventory,**BACKEND_AFTER};self.record('backend-original-inventory.json',self.inventory);candidate_sha=self.record('backend-candidate-inventory.json',expected)
        data=self.root/'probe-data';data.mkdir(mode=0o700);(self.root/'probe-logs').mkdir(mode=0o700);self.m.backup(self.m.BUSINESS,data/'crm_prod.db');before=self.snapshot(data/'crm_prod.db');need(len(before['rows'])==165,'EXACT165_ISOLATED_COPY_REQUIRED');self.shape(data/'crm_prod.db');before_sha=self.record('offline-before.json',before);self.run_migration(data,image);schema=self.compare_before_start(before,data/'crm_prod.db',migrated=True);migrated_rows=self.rows(data/'crm_prod.db');migrated_meta=self.metadata(data/'crm_prod.db')
        command=self.offline_args(data,image);command[2:2]=['--name',self.offline_name,'-d'];need(self.m.inspect_optional(self.offline_name) is None,'FRESH_OFFLINE_NAME_REQUIRED');self.m.run(command,'OFFLINE_START_FAILED')
        try:
            self.m.ready(self.offline_name);self.base.verify_offline(self.m.inspect(self.offline_name));need(self.m.inventory(self.offline_name)==expected,'EXACT_OFFLINE_SOURCE_REQUIRED');need(b'EXACT_UNIFIED_SETTINGS_SEVEN_ROUTES_OWNER_ONLY_WORKERS_OFF' in self.m.run(['docker','exec',self.offline_name,'python','-B','-c',self.canary()],'OFFLINE_SETTINGS_CANARY_FAILED'),'EXACT_SETTINGS_CANARY_MARKER_REQUIRED')
        finally:self.m.run(['docker','stop','--time','20',self.offline_name],'OFFLINE_STOP_FAILED',45)
        need(self.rows(data/'crm_prod.db')==migrated_rows and self.metadata(data/'crm_prod.db')==migrated_meta and self.compare_before_start(before,data/'crm_prod.db',migrated=True)==schema,'OFFLINE_STARTUP_OR_PROBE_CHANGED_DATA');public,static=self.m.stage_public(self.root,self.manifest);new=next_nginx(self.m.NGINX.read_bytes(),self.old_public,public,self.proof['nginx_sha256']);self.current()
        value={'stage':'MEDIA_UNIFIED_SETTINGS_PREPARED','source_sha':SOURCE_SHA,'frontend_version':FRONTEND,'schema_revision':NEW_REVISION,'old_schema_revision':OLD_REVISION,'old_table_count':165,'table_count':169,'old_crm':self.m.runtime(old),'candidate_image':image,'candidate_inventory_sha256':candidate_sha,'offline_before_sha256':before_sha,'schema_after_sha256':schema,'public_root':str(public),'public_inventory_sha256':static,'nginx_next_sha256':H(new),'preflight_sha256':PREFLIGHT_SHA,'manifest_sha256':self.args.manifest_sha256,'payload_sha256':self.args.payload_sha256,'all165_clone_rows_sequences_preserved':True,'four_new_tables_empty':True,'offline_no_network_credentials_workers':True,'existing_all_worker_flags_preserved':True,'production_writes':False,'business_seed_rows':False,'provider_requests':False,'database_restored':False};return {**value,'receipt_sha256':self.record('prepared.json',value)}
    def reviewed(self,*,recovery=False):
        value=strict_json(protected(self.root/'prepared.json',self.args.review_sha256));validate_prepared(value,self.args.manifest_sha256,self.args.payload_sha256,PREFLIGHT_SHA);old=self.m.inspect(self.proof['crm']['id']);need(old['Id']==self.proof['crm']['id'] and old['Image']==self.proof['crm']['image'] and self.m.runtime(old)['config']==self.proof['crm']['config'],'AUTHENTICATED_ORIGINAL_RUNTIME_REQUIRED')
        if not recovery:need(self.m.runtime(old)==self.proof['crm'],'ORIGINAL_RUNTIME_PROVENANCE_CHANGED')
        self.environment(old);self.base.c.source_boundary(old,self.inventory);need(self.m.image_id(value['candidate_image'])==value['candidate_image'] and self.m.verify_public(self.public,self.manifest)==value['public_inventory_sha256'],'REVIEWED_IMAGE_OR_STATIC_CHANGED');self.prepared=value;return value,old
    def identities(self,r,old):
        value=strict_json(protected(self.root/'candidate-created.json'));need(value=={'source_sha':SOURCE_SHA,'candidate_id':value['candidate_id'],'candidate_image':r['candidate_image'],'original_id':old['Id'],'review_sha256':self.args.review_sha256} and re.fullmatch('[a-f0-9]{64}',value['candidate_id']),'DURABLE_KNOWN_CANDIDATE_REQUIRED');a=self.m.inspect(old['Id']);b=self.m.inspect(value['candidate_id']);need(a['Image']==old['Image'] and self.m.runtime(a)['config']==self.proof['crm']['config'] and a['Name'] in {'/t24-crm','/'+self.old_name} and b['Image']==r['candidate_image'] and b['Name'] in {'/t24-crm','/'+self.candidate_name},'ONLY_KNOWN_CANDIDATE_ORIGINAL_ALLOWED');primary=self.m.inspect_optional('t24-crm');need(not primary or primary['Id'] in {a['Id'],b['Id']},'UNKNOWN_PRIMARY_NOT_CHANGED');return a,b
    def runtime_boundary(self,r,old,*,migrated=False,updated=False,live=False,recovery=False):
        self.immutable(migrated=migrated,updated=updated,recovery=recovery);a,b=self.identities(r,old);self.base.c.retained.compare(b,old,self.m);self.environment(a);self.environment(b);self.base.c.source_boundary(a,self.inventory);self.base.c.source_boundary(b,{**self.inventory,**BACKEND_AFTER});need(b['RestartCount']==0,'CANDIDATE_RESTARTED')
        need(live and b['State']['Running'] is True and a['State']['Running'] is False and self.m.inspect('t24-crm')['Id']==b['Id'] or not live and b['State']['Running'] is False,'SINGLE_KNOWN_APPLICATION_WRITER_REQUIRED')
        self.writer_census((b['Id'],) if live else ((a['Id'],) if a['State']['Running'] else ()))
        if not live and not a['State']['Running']:self.census.no_open_database_fds(self.m.BUSINESS)
        if live:self.base.c.helper.validation_window(b)
        # Data exactness is intentionally enforced only before start. Once
        # live, unchanged existing workers may update any old business table.
        if self.baseline is not None and not live and not recovery:self.compare_before_start(self.baseline,migrated=migrated)
        return a,b
    def stopped_snapshot(self,old):
        need(self.m.inspect(old['Id'])['State']['Running'] is False,'STOPPED_ORIGINAL_REQUIRED');self.writer_census();self.census.no_open_database_fds(self.m.BUSINESS);self.immutable();value=self.snapshot();need(len(value['rows'])==165,'EXACT_QUIESCENT165_TABLES_REQUIRED');self.writer_census();self.census.no_open_database_fds(self.m.BUSINESS);return value
    def capture_baseline(self,old,candidate):
        first=self.stopped_snapshot(old);second=self.stopped_snapshot(old);need(first==second,'QUIESCENT165_ROWS_SEQUENCE_CHANGED');value={'stage':'MEDIA_UNIFIED_SETTINGS_QUIESCENT_BASELINE','source_sha':SOURCE_SHA,'prepared_sha256':self.args.review_sha256,'preflight_sha256':PREFLIGHT_SHA,'original_runtime':self.proof['crm'],'candidate_id':candidate['Id'],**second};sha=self.record('activation-baseline.json',value);self.record('activation-baseline-identity.json',{'source_sha':SOURCE_SHA,'prepared_sha256':self.args.review_sha256,'baseline_sha256':sha,'original_id':old['Id'],'candidate_id':candidate['Id']});self.baseline=value;return sha
    def public_check(self):
        raw=self.m.run(['curl','-q','--silent','--show-error','--fail','--noproxy','*','--http1.1','--max-time','5','--max-redirs','0','--resolve','t24-crm.com:443:127.0.0.1','https://t24-crm.com/app-version.json?settings='+FRONTEND],'PUBLIC_VERSION_READ_FAILED',10);need(len(raw)<1024 and strict_json(raw)=={'version':FRONTEND},'PUBLIC_FRONTEND_VERSION_CHANGED');self.base.staticmod.public_security_policy(self.m,self.proof['content_security_policy_sha256'])
    def activate(self):
        r,old=self.reviewed();self.current();m=self.m;need(not(self.root/'activation-started.json').exists() and not m.inspect_optional(self.old_name) and not m.inspect_optional(self.candidate_name),'FRESH_ACTIVATION_REQUIRED');before=m.NGINX.read_bytes();after=next_nginx(before,self.old_public,self.public,self.proof['nginx_sha256']);need(H(after)==r['nginx_next_sha256'],'EXACT_PREPARED_NGINX_REQUIRED');self.record('nginx-before.conf',before);self.record('activation-started.json',{'source_sha':SOURCE_SHA,'prepared_sha256':self.args.review_sha256,'original_id':old['Id']});self.record('candidate-create-intent.json',{'source_sha':SOURCE_SHA,'name':self.candidate_name,'image':r['candidate_image'],'original_id':old['Id']})
        status,body=m.retained().docker_request('POST','/containers/create?name='+self.candidate_name,m.clone_config(r['candidate_image'],old));need(status==201,'CANDIDATE_CREATE_FAILED');identity=json.loads(body)['Id'];need(re.fullmatch('[a-f0-9]{64}',identity),'EXACT_CREATED_CANDIDATE_ID_REQUIRED');self.record('candidate-created.json',{'source_sha':SOURCE_SHA,'candidate_id':identity,'candidate_image':r['candidate_image'],'original_id':old['Id'],'review_sha256':self.args.review_sha256})
        try:
            _,candidate=self.runtime_boundary(r,old);need(candidate['State']['Status']=='created','NEVER_STARTED_CANDIDATE_REQUIRED');self.record('stop-intent.json',{'source_sha':SOURCE_SHA,'original_id':old['Id'],'candidate_id':identity,'original_runtime':self.proof['crm']});m.run(['docker','stop','--time','30',old['Id']],'ORIGINAL_STOP_FAILED',60);a,candidate=self.runtime_boundary(r,old);need(a['State']['Running'] is False,'ORIGINAL_STOPPED_REQUIRED');baseline_sha=self.capture_baseline(old,candidate);m.backup(m.BUSINESS,self.root/'production-before.db');self.compare_before_start(self.baseline);self.writer_census();self.census.no_open_database_fds(m.BUSINESS);self.run_migration(m.BUSINESS.parent,r['candidate_image']);schema=self.compare_before_start(self.baseline,migrated=True);need(schema==r['schema_after_sha256'],'EXACT_PRODUCTION_ADDITIVE_SCHEMA_REQUIRED')
            preservation={'stage':'MEDIA_UNIFIED_SETTINGS_PRESTART_DATA_PRESERVED','source_sha':SOURCE_SHA,'baseline_sha256':baseline_sha,'old_table_count':165,'new_table_count':169,'all165_rows_sequences_exact':True,'four_new_tables_empty':True,'schema_sha256':schema,'candidate_not_started':True};preservation_sha=self.record('prestart-preservation.json',preservation);self.runtime_boundary(r,old,migrated=True);m.run(['docker','rename',old['Id'],self.old_name],'ORIGINAL_RENAME_FAILED');m.run(['docker','rename',identity,'t24-crm'],'CANDIDATE_RENAME_FAILED');self.runtime_boundary(r,old,migrated=True);self.record('candidate-start-intent.json',{'candidate_id':identity,'prestart_preservation_sha256':preservation_sha,'live_business_writes_allowed_after_start':True});self.writer_census();self.census.no_open_database_fds(m.BUSINESS);m.run(['docker','start',identity],'CANDIDATE_START_FAILED');m.ready(identity);self.runtime_boundary(r,old,migrated=True,live=True);m.replace_nginx(before,after);m.retained().reload_nginx();self.runtime_boundary(r,old,migrated=True,updated=True,live=True);self.public_check();_,candidate=self.runtime_boundary(r,old,migrated=True,updated=True,live=True)
            result={'stage':'MEDIA_UNIFIED_SETTINGS_DEPLOYED','source_sha':SOURCE_SHA,'frontend_version':FRONTEND,'crm':m.runtime(candidate),'schema_revision':NEW_REVISION,'table_count':169,'schema_sha256':schema,'prepared_sha256':self.args.review_sha256,'preflight_sha256':PREFLIGHT_SHA,'quiescent165_baseline_sha256':baseline_sha,'prestart_preservation_sha256':preservation_sha,'all165_rows_sequences_preserved_before_start':True,'all169_table_definitions_verified_after_start':True,'post_start_live_business_rows_frozen':False,'four_new_tables_empty':True,'all_worker_flags_environment_credentials_private_preserved':True,'monthly_auto_prep_enabled':True,'google_scheduler_enabled':True,'meta_execution_enabled':False,'meta_scheduler_enabled':False,'public_root':str(self.public),'public_inventory_sha256':r['public_inventory_sha256'],'nginx_sha256':H(m.NGINX.read_bytes()),'content_security_policy_sha256':self.proof['content_security_policy_sha256'],'business_seed_rows':False,'provider_requests_by_tool':False,'database_restored':False};return {**result,'receipt_sha256':self.record('deployed.json',result)}
        except BaseException:self.recover_internal(r,old);raise
    def recover_internal(self,r,old):
        m=self.m;a,b=self.identities(r,old)
        if b['State']['Running']:m.run(['docker','stop','--time','30',b['Id']],'RECOVERY_CANDIDATE_CONTAINMENT_FAILED',60)
        a,b=self.identities(r,old);self.settle_migration(m.BUSINESS.parent,r['candidate_image']);head=self.migration_revision();migrated=head==NEW_REVISION;updated=H(m.NGINX.read_bytes())==r['nginx_next_sha256'];self.immutable(migrated=migrated,updated=updated,recovery=True);self.base.c.retained.compare(b,old,m);self.environment(a);self.environment(b);self.base.c.source_boundary(a,self.inventory);self.base.c.source_boundary(b,{**self.inventory,**BACKEND_AFTER});self.writer_census((a['Id'],) if a['State']['Running'] else ())
        if not a['State']['Running']:self.census.no_open_database_fds(m.BUSINESS)
        if updated:m.replace_nginx(m.NGINX.read_bytes(),protected(self.root/'nginx-before.conf',self.proof['nginx_sha256']))
        m.retained().reload_nginx()
        if b['Name']=='/t24-crm':m.run(['docker','rename',b['Id'],self.candidate_name],'RETAIN_FAILED_CANDIDATE_STOPPED')
        if a['Name']!='/t24-crm':m.run(['docker','rename',a['Id'],'t24-crm'],'RESTORE_ORIGINAL_NAME_FAILED')
        if not a['State']['Running']:
            self.record_once('original-resume-intent.json',{'source_sha':SOURCE_SHA,'original_id':a['Id'],'image':a['Image'],'config':m.runtime(a)['config'],'schema_revision':head,'candidate_id':b['Id']});m.run(['docker','start',a['Id']],'ORIGINAL_RESUME_FAILED');resumed=m.inspect(a['Id']);self.record_once('original-resume-started.json',{'source_sha':SOURCE_SHA,'runtime':m.runtime(resumed),'candidate_id':b['Id']})
        m.ready(a['Id']);resumed=m.inspect('t24-crm');need(resumed['Id']==self.proof['crm']['id'] and resumed['State']['Running'] is True and m.runtime(resumed)['config']==self.proof['crm']['config'],'EXACT_ORIGINAL_RESUMED_REQUIRED');self.environment(resumed);self.immutable(migrated=migrated,recovery=True);self.writer_census((resumed['Id'],));result={'stage':'MEDIA_UNIFIED_SETTINGS_ORIGINAL_RESUMED','source_sha':BASE_SOURCE,'crm':m.runtime(resumed),'schema_revision':head,'additive_tables_retained':migrated,'all_current_business_rows_preserved':True,'old_worker_flags_preserved':True,'database_restored':False,'provider_requests_by_tool':False};return {**result,'receipt_sha256':self.record_once('recovery.json',result)}
    def migration_revision(self):
        import sqlite3
        con=sqlite3.connect('file:'+str(self.m.BUSINESS)+'?mode=ro',uri=True)
        try:con.execute('PRAGMA query_only=ON');rows=con.execute('SELECT version_num FROM alembic_version').fetchall();need(len(rows)==1 and rows[0][0] in {OLD_REVISION,NEW_REVISION},'KNOWN_SCHEMA_HEAD_REQUIRED');return rows[0][0]
        finally:con.close()
    def recover(self):
        r,old=self.reviewed(recovery=True);need(not(self.root/'deployed.json').exists(),'SUCCESSFUL_RELEASE_RECOVERY_REQUIRES_SEPARATE_REVIEW');return self.recover_internal(r,old)

def validate_prepared(v,manifest,payload,preflight):
    pins_ready();need(v['stage']=='MEDIA_UNIFIED_SETTINGS_PREPARED' and v['source_sha']==SOURCE_SHA and v['frontend_version']==FRONTEND and v['old_schema_revision']==OLD_REVISION and v['schema_revision']==NEW_REVISION and v['old_table_count']==165 and v['table_count']==169 and v['manifest_sha256']==manifest and v['payload_sha256']==payload and v['preflight_sha256']==preflight==PREFLIGHT_SHA,'EXACT_PREPARED_CURRENT427_SETTINGS_SCOPE_REQUIRED');need(all(v[k] is True for k in ('all165_clone_rows_sequences_preserved','four_new_tables_empty','offline_no_network_credentials_workers','existing_all_worker_flags_preserved')) and all(v[k] is False for k in ('production_writes','business_seed_rows','provider_requests','database_restored')),'EXACT_ISOLATED_PREPARATION_REQUIRED');need(all(re.fullmatch('[a-f0-9]{64}',v[k] or '') for k in ('candidate_inventory_sha256','offline_before_sha256','schema_after_sha256','public_inventory_sha256','nginx_next_sha256')) and re.fullmatch('sha256:[a-f0-9]{64}',v['candidate_image'] or ''),'EXACT_PREPARED_ARTIFACT_HASHES_REQUIRED')
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=('prepare','activate','recover'),required=True);parser.add_argument('--release',type=Path,required=True);parser.add_argument('--manifest-sha256',required=True);parser.add_argument('--payload-sha256',required=True);parser.add_argument('--preflight',type=Path,required=True);parser.add_argument('--preflight-sha256',required=True);parser.add_argument('--review-sha256');args=parser.parse_args();pins_ready();need(os.geteuid()==0 and socket.gethostname()==HOST,'EXACT_ROOT_SERVER_REQUIRED');resource.setrlimit(resource.RLIMIT_CORE,(0,0));os.umask(0o077);need(args.preflight_sha256==PREFLIGHT_SHA and (args.phase=='prepare' or re.fullmatch('[a-f0-9]{64}',args.review_sha256 or '')),'EXACT_PHASE_REVIEW_REQUIRED')
    lock=Path('/opt/t24-crm/releases/.media-workspace-scale.lock')
    for p in lock.parents:
        row=p.lstat();need(p.resolve()==p and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_LOCK_PARENT_REQUIRED')
    fd=os.open(lock,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:row=os.fstat(fd);need(stat.S_ISREG(row.st_mode) and row.st_uid==0 and row.st_nlink==1 and stat.S_IMODE(row.st_mode)==0o600,'ROOT_PRIVATE_RELEASE_LOCK_REQUIRED');fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);print(json.dumps(getattr(Release(args),args.phase)(),sort_keys=True))
    finally:os.close(fd)
if __name__=='__main__':
    try:main()
    except BaseException as e:
        v=str(e);code=v if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',v) else 'MEDIA_UNIFIED_SETTINGS_RELEASE_REJECTED';print(json.dumps({'stage':'MEDIA_UNIFIED_SETTINGS_RELEASE_REJECTED','code':code,'database_restored':False},sort_keys=True));raise SystemExit(1)
