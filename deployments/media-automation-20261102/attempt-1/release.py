"""Guarded additive draft-automation release; no business seed or publication.

Prepare migrates only a no-network clone. Activate stops the old writer before
the same transaction on the existing database inode. Recovery resumes the old
image while retaining additive tables and every current row; never restore DB.
"""
import argparse,copy,fcntl,hashlib,io,json,os,re,resource,socket,sqlite3,stat,tarfile,types
from pathlib import Path

HOST='iZj6c4cj7edgnhdimts4l7Z'
SCOPE='media-automation'
SOURCE_SHA = '53d66ebb6c69d283c22596e806778989206763ec'
FRONTEND = '569fa342f1c3'
APPLICATION_FREEZE_SHA = '711fb12eb54b1ca6f1f940a69cbadd581865579aff37bfd555ae1a3cfd2aaf81'
PREFLIGHT_SHA = 'ecc7ae9cf9dfbdff68306b928b9b3a8f0ad98c90e5785611a061730f78a8beda'
PREFLIGHT_CODE_SHA='57deb06c6c9ebd11336cf9408887f36754ba2246d294faa5cbe38896a56f99ce'
BASE_SOURCE='5fd379d625d6c18abdec1b98d388494d0900c780'
BASE_STATIC_SOURCE='eec3d1d02a97a5b52a1483e0c93f094242aade56'
BASE_FRONTEND='8c3b5e1302ac'
OLD_REVISION='g32ed456e792'
NEW_REVISION='h43fe567f803'
MIGRATION='alembic/versions/h43fe567f803_media_monthly_automation.py'
NEW_TABLES=frozenset({'media_monthly_automation_policies','media_monthly_automation_occurrences','media_monthly_automation_requests'})
NEW_INDEXES=frozenset({'ix_media_monthly_automation_policies_owner_id','ix_media_monthly_automation_occurrences_owner_id','ix_media_monthly_automation_occurrences_ai_attempted_at'})
BACKEND_SCOPE=frozenset({'main.py','services/media_monthly.py','alembic/versions/h43fe567f803_media_monthly_automation.py','models/media_monthly_automation.py','routers/media_monthly_automation.py','schemas/media_monthly_automation.py','services/media_monthly_automation.py','services/media_monthly_automation_worker.py','services/media_monthly_editorial.py'})
BACKEND_BEFORE = {'alembic/versions/h43fe567f803_media_monthly_automation.py': None, 'main.py': '1e7411f7cf58bd9dcbeb29b8976d507b9f09422c8da469def7aed98088f14255', 'models/media_monthly_automation.py': None, 'routers/media_monthly_automation.py': None, 'schemas/media_monthly_automation.py': None, 'services/media_monthly.py': '4033f5c2365a801b586315a08d72f1e0a670990ac749b31a4fd5493d79fa19a7', 'services/media_monthly_automation.py': None, 'services/media_monthly_automation_worker.py': None, 'services/media_monthly_editorial.py': None}
BACKEND_AFTER = {'alembic/versions/h43fe567f803_media_monthly_automation.py': '736cce595e9ae8d7903bba3308a69440c1c253c667c526b4a63196f1704df9e2', 'main.py': '9edae4fae9ecaedf8466176d61f51e7fda09ef2ab1aafb04496ddc95576f8203', 'models/media_monthly_automation.py': 'be7cc8a478820f499928d69095d0d96c9e7e134a6e1b5efde025e974ea1abb95', 'routers/media_monthly_automation.py': '79415b0f50b934376665d157dee9604832278368bc098532e082b5b9a75a6091', 'schemas/media_monthly_automation.py': '2f084a8ded8925287a3f2b58d2b78ba0898350f4c4435f9fc3f3425e90b211bb', 'services/media_monthly.py': '129a4752fb54c3299c1da799cba457671f2441474ea6f1db15f832cbf004699d', 'services/media_monthly_automation.py': 'dcd5c71a6bfc361127343c5f1262836641828a7941a7265446b059cbc624d851', 'services/media_monthly_automation_worker.py': 'e84b09dda41aea86d9e5957b59a2f21f1fe8824d59afeba774bc90809d110308', 'services/media_monthly_editorial.py': '5753761a0526aa81cf11f883f558d51201adfb517e6e68ad6486bc29b8957751'}
CHANGED_SOURCE_HASHES = {'app/backend/alembic/versions/h43fe567f803_media_monthly_automation.py': '736cce595e9ae8d7903bba3308a69440c1c253c667c526b4a63196f1704df9e2', 'app/backend/main.py': '9edae4fae9ecaedf8466176d61f51e7fda09ef2ab1aafb04496ddc95576f8203', 'app/backend/models/media_monthly_automation.py': 'be7cc8a478820f499928d69095d0d96c9e7e134a6e1b5efde025e974ea1abb95', 'app/backend/routers/media_monthly_automation.py': '79415b0f50b934376665d157dee9604832278368bc098532e082b5b9a75a6091', 'app/backend/schemas/media_monthly_automation.py': '2f084a8ded8925287a3f2b58d2b78ba0898350f4c4435f9fc3f3425e90b211bb', 'app/backend/services/media_monthly.py': '129a4752fb54c3299c1da799cba457671f2441474ea6f1db15f832cbf004699d', 'app/backend/services/media_monthly_automation.py': 'dcd5c71a6bfc361127343c5f1262836641828a7941a7265446b059cbc624d851', 'app/backend/services/media_monthly_automation_worker.py': 'e84b09dda41aea86d9e5957b59a2f21f1fe8824d59afeba774bc90809d110308', 'app/backend/services/media_monthly_editorial.py': '5753761a0526aa81cf11f883f558d51201adfb517e6e68ad6486bc29b8957751', 'app/backend/tests/test_media_monthly_automation.py': '6a4ae579ddf3bcfc280251dad51f393df94b6417551be09c0f2dfbf87dee46bf', 'app/backend/tests/test_media_monthly_editorial.py': 'e156ef032486013943c55db59985b540bc40f807eca44734aa2971c69f5278da', 'app/frontend/src/components/MediaAutomationOverview.tsx': 'dc479f69e5cb7664f3b2ee1486477769dc0fb7ce3038bf0efb02cff7080b69a7', 'app/frontend/src/components/MediaAutomationPanel.tsx': '9f054194df5c4db1e49ba95bdbbcac7aeaa73312d7465b1482dd0c56e5832244', 'app/frontend/src/components/MediaMerchantWorkspace.tsx': '13a28385a4772b1307c54e8824961eb98a67a5a60ac262eae37f8dd14cbce619', 'app/frontend/src/components/MediaMonthlyWorkspace.tsx': '9f11b5de6bfad21822d397b7764deb5c12a065329cdc340b4fdf78b77c416383', 'app/frontend/src/components/MediaPublicationImage.tsx': '10fd2e63b56de725599f45aa6bfaee45dabf97e05974c19e7cb23a4adcd64203', 'app/frontend/src/components/media-automation-panel.css': '135360a18aee60b312f5ed44d51e7452a8191a51d0bd44091025df6a66d64b7f', 'app/frontend/src/components/media-publication-image.css': '921e1aaadc0c3ef925220917df828ea952e14e99c9472382c0fef0c73cf4b595', 'app/frontend/src/lib/media-automation-api.ts': '1edd7d21c1257dc775c88bd0ea7d5e41cee292cb0801713a556c52614898085a', 'app/frontend/src/lib/media-monthly-api.ts': '98175ed225fc70900c93c368c4e9de4d65506316cffb02613bba6c9176426ac3', 'app/frontend/src/lib/media-publication-images.ts': '9f496e9d83e26633de02768ca1d2f1bbde8839054fc5451ba4fce6cb6641406b', 'app/frontend/tests/media-automation.test.mjs': '296e1f8c9df708ce3997594e91721e19275411eac5008b8b7e3635fe00a7b983', 'app/frontend/tests/media-publication-images.test.mjs': '0bb70f65513b0ed06b02a27d90c0488e3f622e98fc1ce9cd76173184c8102950'}
H=lambda body:hashlib.sha256(body).hexdigest()
def need(ok,code):
    if not ok:raise RuntimeError(code)
def encoded(v):return (json.dumps(v,sort_keys=True,indent=2)+'\n').encode()
def digest(v):return H(json.dumps(v,sort_keys=True,separators=(',',':')).encode())
def strict_json(body):
    def pairs(rows):
        v={}
        for k,x in rows:need(k not in v,'DUPLICATE_JSON_KEY_REJECTED');v[k]=x
        return v
    def invalid(v):raise RuntimeError('NONFINITE_JSON_REJECTED')
    return json.loads(body,object_pairs_hook=pairs,parse_constant=invalid)
def protected(path,sha=None,maximum=16777216):
    need(path.is_absolute() and path.resolve()==path,'CANONICAL_ROOT_PRIVATE_PATH_REQUIRED')
    for p in path.parents:
        r=p.lstat();need(stat.S_ISDIR(r.st_mode) and r.st_uid==0 and not r.st_mode&0o022,'ROOT_PROTECTED_PARENT_REQUIRED')
    r=path.lstat();need(stat.S_ISREG(r.st_mode) and r.st_uid==0 and stat.S_IMODE(r.st_mode)==0o600 and r.st_nlink==1 and 0<r.st_size<=maximum,'ROOT600_REGULAR_FILE_REQUIRED')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as f:o=os.fstat(f.fileno());b=f.read(maximum+1);a=os.fstat(f.fileno())
    fields=lambda x:(x.st_dev,x.st_ino,x.st_mode,x.st_uid,x.st_nlink,x.st_size,x.st_mtime_ns,x.st_ctime_ns)
    need(fields(r)==fields(o)==fields(a)==fields(path.lstat()) and len(b)==r.st_size and (sha is None or H(b)==sha),'EXACT_STABLE_PROTECTED_BYTES_REQUIRED');return b
def pins_ready():
    need(re.fullmatch('[a-f0-9]{40}',SOURCE_SHA or '') and SOURCE_SHA not in {'0'*40,BASE_SOURCE,BASE_STATIC_SOURCE} and re.fullmatch('[a-f0-9]{12}',FRONTEND or '') and FRONTEND not in {'0'*12,BASE_FRONTEND},'FINAL_APPLICATION_PINS_REQUIRED')
    need(all(re.fullmatch('[a-f0-9]{64}',v or '') and v!='0'*64 for v in (APPLICATION_FREEZE_SHA,PREFLIGHT_SHA,PREFLIGHT_CODE_SHA)),'FINAL_FREEZE_AND_PREFLIGHT_REQUIRED')
    need(set(BACKEND_BEFORE)==set(BACKEND_AFTER)==BACKEND_SCOPE and all(re.fullmatch('[a-f0-9]{64}',s or '') for s in BACKEND_AFTER.values()) and bool(CHANGED_SOURCE_HASHES) and all(re.fullmatch('[a-f0-9]{64}',s or '') for s in CHANGED_SOURCE_HASHES.values()),'EXACT_FINAL_SOURCE_ALLOWLIST_REQUIRED')
def validate_manifest(v,payload):
    pins_ready()
    need(v['stage']=='MEDIA_AUTOMATION_PAYLOAD' and v['source_sha']==SOURCE_SHA and v['frontend_version']==FRONTEND and v['baseline_source_sha']==BASE_SOURCE and v['baseline_static_source_sha']==BASE_STATIC_SOURCE and v['old_schema_revision']==OLD_REVISION and v['schema_revision']==NEW_REVISION,'EXACT_ADDITIVE_AUTOMATION_SCOPE_REQUIRED')
    need(v['preflight_sha256']==PREFLIGHT_SHA and v['application_freeze_sha256']==APPLICATION_FREEZE_SHA and v['payload_sha256']==payload and v['changed_source_files']==CHANGED_SOURCE_HASHES and v['backend_before']==BACKEND_BEFORE and v['backend_after']==BACKEND_AFTER and set(v['additive_tables'])==NEW_TABLES,'EXACT_FROZEN_SOURCE_AND_MIGRATION_REQUIRED')
    need(all(v[k] is False for k in ('dependencies_changed','credentials_included','runtime_environment_changed','production_seed_rows','provider_requests','automation_worker_enabled','operations_execution_enabled','operations_scheduler_enabled','permissions_changed')),'NO_BUSINESS_SEED_PERMISSION_ENV_OR_PROVIDER_ACTION_ALLOWED')
def next_nginx(body,old,new,sha):
    a=('root '+str(old)+';').encode();b=('root '+str(new)+';').encode()
    need(H(body)==sha and body.count(a)==1 and b not in body,'EXACT_EXISTING_STATIC_ROOT_REQUIRED')
    value=body.replace(a,b,1);need(value.replace(b,a,1)==body,'ONLY_STATIC_ROOT_SUBSTITUTION_ALLOWED');return value
def compare_rows(before,after,*,migrated=False,rows=True,empty=True):
    need(set(after)==set(before)|(NEW_TABLES if migrated else set()),'EXACT_ORIGINAL162_PLUS_THREE_TABLES_REQUIRED')
    for name,old in before.items():
        cur=after[name];need(cur['shape_sha256']==old['shape_sha256'],'ORIGINAL_TABLE_DEFINITION_CHANGED')
        if name=='alembic_version' and migrated:
            need(cur['count']==1 and cur['rows_sha256']==H(json.dumps([NEW_REVISION]).encode()),'EXACT_NEW_HEAD_ROW_REQUIRED')
        elif rows:need(cur==old,'ORIGINAL_BUSINESS_ROWS_CHANGED')
    if migrated and empty:need(all(after[n]['count']==0 for n in NEW_TABLES),'NEW_AUTOMATION_TABLES_MUST_START_EMPTY')
def compare_definitions(before,after,*,migrated=False):
    left={tuple(r[:3]):r[3] for r in before};right={tuple(r[:3]):r[3] for r in after}
    need(len(left)==len(before) and len(right)==len(after) and all(right.get(k)==v for k,v in left.items()),'ORIGINAL162_SCHEMA_OBJECT_CHANGED')
    expected={('table',n,n) for n in NEW_TABLES}|{('index',n,'media_monthly_automation_policies' if 'policies' in n else 'media_monthly_automation_occurrences') for n in NEW_INDEXES}
    need(set(right)-set(left)==(expected if migrated else set()),'ONLY_EXACT_THREE_TABLES_AND_INDEXES_ALLOWED')
def migration_script():
    # Explicit BEGIN makes SQLite DDL and the head update one transaction.
    return f'''import importlib.util,sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
e=sa.create_engine('sqlite:///file:/app/backend/data/crm_prod.db?mode=rw&uri=true')
with e.connect() as c:
 c.exec_driver_sql('BEGIN IMMEDIATE')
 assert c.exec_driver_sql('SELECT version_num FROM alembic_version').fetchall()==[({OLD_REVISION!r},)]
 seq=c.exec_driver_sql('SELECT name,seq FROM sqlite_sequence ORDER BY name').fetchall()
 pragma=[c.exec_driver_sql('PRAGMA '+n).fetchone() for n in ('user_version','application_id')]
 s=importlib.util.spec_from_file_location('reviewed_automation_migration','/app/backend/{MIGRATION}')
 m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
 assert m.revision=={NEW_REVISION!r} and m.down_revision=={OLD_REVISION!r}
 with Operations.context(MigrationContext.configure(c)):m.upgrade()
 assert c.exec_driver_sql('SELECT name,seq FROM sqlite_sequence ORDER BY name').fetchall()==seq
 assert [c.exec_driver_sql('PRAGMA '+n).fetchone() for n in ('user_version','application_id')]==pragma
 assert c.exec_driver_sql("UPDATE alembic_version SET version_num='{NEW_REVISION}' WHERE version_num='{OLD_REVISION}'").rowcount==1
 c.commit()
print('EXACT_THREE_EMPTY_AUTOMATION_TABLES_MIGRATED')
'''

class Release:
    def __init__(self,args):
        pins_ready();self.args=args;self.root=args.release
        need(self.root==Path('/opt/t24-crm/releases/'+SCOPE+'-'+SOURCE_SHA[:12]+'-20261102'),'EXACT_RELEASE_NAMESPACE_REQUIRED')
        body=protected(self.root/'preflight.py',PREFLIGHT_CODE_SHA,131072);pf=types.ModuleType('_automation_fresh_preflight');pf.__file__=str(self.root/'preflight.py');exec(compile(body,pf.__file__,'exec'),pf.__dict__)
        self.pf=pf;self.staticmod,self.static,self.original_inventory=pf.dependencies();self.c=self.static.ctx;self.m=self.c.m
        self.proof=strict_json(protected(args.preflight,PREFLIGHT_SHA,1048576));self.manifest=strict_json(protected(self.root/'manifest.json',args.manifest_sha256,1048576));protected(self.root/'payload.tar.gz',args.payload_sha256)
        p,v=self.proof,self.manifest
        need(args.preflight==pf.ROOT/('media-automation-preflight-'+PREFLIGHT_SHA[:12]+'.json') and p['stage']=='MEDIA_AUTOMATION_READONLY_PREFLIGHT' and p['source_sha']==BASE_SOURCE and p['frontend_version']==BASE_FRONTEND and p['schema_revision']==OLD_REVISION and p['backend_inventory']==self.original_inventory and len(p['rows'])==162 and p['crm']==pf.RUNTIME,'EXACT_FRESH_162_TABLE_BASELINE_REQUIRED')
        need(v['stage']=='MEDIA_AUTOMATION_PAYLOAD' and v['source_sha']==SOURCE_SHA and v['frontend_version']==FRONTEND and v['baseline_source_sha']==BASE_SOURCE and v['baseline_static_source_sha']==BASE_STATIC_SOURCE and v['old_schema_revision']==OLD_REVISION and v['schema_revision']==NEW_REVISION,'EXACT_ADDITIVE_AUTOMATION_SCOPE_REQUIRED')
        need(v['preflight_sha256']==PREFLIGHT_SHA and v['application_freeze_sha256']==APPLICATION_FREEZE_SHA and v['payload_sha256']==args.payload_sha256 and v['changed_source_files']==CHANGED_SOURCE_HASHES and v['backend_before']==BACKEND_BEFORE and v['backend_after']==BACKEND_AFTER and set(v['additive_tables'])==NEW_TABLES,'EXACT_FROZEN_SOURCE_AND_MIGRATION_REQUIRED')
        need(all(v[k] is False for k in ('dependencies_changed','credentials_included','runtime_environment_changed','production_seed_rows','provider_requests','automation_worker_enabled','operations_execution_enabled','operations_scheduler_enabled','permissions_changed')),'NO_BUSINESS_SEED_PERMISSION_ENV_OR_PROVIDER_ACTION_ALLOWED')
        allowed={'backend/'+n for n in BACKEND_AFTER};need({n[8:] for n in v['files'] if n.startswith('backend/')}==set(BACKEND_AFTER) and all(n in allowed or n.startswith('static/') and self.m.static_path(n[7:]) for n in v['files']) and all(re.fullmatch('[a-f0-9]{64}',s) for s in v['files'].values()),'EXACT_PAYLOAD_MEMBER_ALLOWLIST_REQUIRED')
        need(all(v['files']['backend/'+n]==s and self.original_inventory.get(n)==BACKEND_BEFORE[n] for n,s in BACKEND_AFTER.items()),'EXACT_RUNTIME_SOURCE_OVERLAY_REQUIRED')
        self.public=Path('/var/www/t24-crm-public/'+SCOPE+'-'+SOURCE_SHA[:12]+'-20261102');self.old_public=Path(p['public_root'])
        row=self.root.lstat();need(stat.S_ISDIR(row.st_mode) and row.st_uid==0 and stat.S_IMODE(row.st_mode)==0o700,'ROOT_PRIVATE_RELEASE_DIRECTORY_REQUIRED')
        self.old_name='t24-crm-before-'+SCOPE+'-'+SOURCE_SHA[:12];self.candidate_name='t24-crm-candidate-'+SCOPE+'-'+SOURCE_SHA[:12];self.offline_name='t24-'+SCOPE+'-probe-'+SOURCE_SHA[:12]
        m=self.m;m.SOURCE,m.SCOPE,m.BACKEND=SOURCE_SHA,SCOPE,set(BACKEND_AFTER);m.BASELINE_FRONTEND,m.FRONTEND_VERSION=BASE_FRONTEND,FRONTEND
        m.PUBLIC,m.STATIC_SHA,m.NGINX_SHA=self.old_public,p['public_inventory_sha256'],p['nginx_sha256'];m.OLD_ID,m.BASE_IMAGE,m.OLD_CONFIG=(p['crm'][k] for k in ('id','image','config'));m.public_root=lambda:self.public
    def record(self,name,value):
        sha=self.m.write(self.root/name,value);fd=os.open(self.root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(fd)
        finally:os.close(fd)
        return sha
    def rows(self,path=None):return self.c.retained.evidence(self.c.rows(path or self.m.BUSINESS))
    def definitions(self,path=None):return self.pf.table_definitions(path or self.m.BUSINESS)
    def revision(self,path=None):
        con=sqlite3.connect('file:'+str(path or self.m.BUSINESS)+'?mode=ro',uri=True,timeout=3)
        try:
            con.execute('PRAGMA query_only=ON');rows=con.execute('SELECT version_num FROM alembic_version').fetchall();need(len(rows)==1 and rows[0][0] in {OLD_REVISION,NEW_REVISION},'ONLY_KNOWN_DATABASE_REVISION_ALLOWED');return rows[0][0]
        finally:con.close()
    def db_boundary(self,path=None,*,migrated=False,rows=True,empty=True):
        path=path or self.m.BUSINESS;p=self.proof;need(self.revision(path)==(NEW_REVISION if migrated else OLD_REVISION),'EXACT_DATABASE_REVISION_REQUIRED')
        compare_rows(p['rows'],self.rows(path),migrated=migrated,rows=rows,empty=empty);compare_definitions(p['table_definitions'],self.definitions(path),migrated=migrated)
        self.c.retained.live_sequence_boundary(p['database_metadata'],self.c.metadata(path))
        return self.m.schema_signature(path,NEW_REVISION if migrated else OLD_REVISION)
    def environment(self,info):
        need(self.c.environment(info)==(self.proof['environment_sha256'],self.proof['ops_environment_sha256']),'FULL_ENVIRONMENT_CHANGED')
        self.c.ctx.workflow.pf.google_environment(info);self.m.verify_secret_mount(info);self.m.verify_production_worker_enabled(info)
        need(not any(row.split('=',1)[0]=='T24_MEDIA_MONTHLY_AUTOPREP_ENABLED' for row in info['Config']['Env']),'NEW_DRAFT_WORKER_MUST_STAY_DEFAULT_OFF')
    def nginx(self,updated=False):
        body=self.m.NGINX.read_bytes();active=self.m.run(['nginx','-T'],'NGINX_READ_FAILED');observed=H(active)
        if updated:
            a,b=os.fsencode(self.public),os.fsencode(self.old_public);need(body.count(a)==active.count(a)==1,'EXACT_NEW_PUBLIC_ROOT_REQUIRED');body=body.replace(a,b,1);active=active.replace(a,b,1)
        need(H(body)==self.proof['nginx_sha256'] and H(active)==self.proof['active_nginx_sha256'],'NGINX_PROXY_CSP_OR_OTHER_BYTES_CHANGED');return observed
    def protections(self,*,migrated=False,updated=False,recovery=False):
        p,c,m=self.proof,self.c,self.m
        need(c.safe.safe_private_boundary(m,c.pins)==p['private_boundary'],'PRIVATE_BOUNDARY_CHANGED')
        meta={'ops':c.safe.protected_metadata(c.c.ENV_FILE),'google':c.safe.protected_metadata(c.safe.GBP_ENV),'meta_read':c.safe.protected_metadata(c.ctx.workflow.core.ENV_FILE),'meta_legacy':c.safe.protected_metadata(c.ctx.workflow.core.LEGACY_ENV_FILE)}
        need(meta==p['credential_metadata'] and m.credential_boundary()==p['credential_boundary'],'CREDENTIAL_METADATA_CHANGED')
        need([m.BUSINESS.stat().st_dev,m.BUSINESS.stat().st_ino]==p['database_identity'],'DATABASE_INODE_CHANGED')
        schema=self.db_boundary(migrated=migrated,rows=not recovery,empty=not recovery)
        need(digest(m.tree(self.old_public))==p['public_inventory_sha256'],'ORIGINAL_STATIC_BYTES_CHANGED');self.nginx(updated);return schema
    def current(self):
        self.protections();info=self.m.inspect('t24-crm');need(info['State']['Running'] is True and self.m.runtime(info)==self.proof['crm'] and self.m.inventory(info['Id'])==self.original_inventory,'CURRENT420_RUNTIME_OR_SOURCE_CHANGED');self.environment(info);self.m.ready(info['Id']);return info
    def extract(self):
        seen=set();total=0;blob=protected(self.root/'payload.tar.gz',self.args.payload_sha256)
        with tarfile.open(fileobj=io.BytesIO(blob),mode='r:gz') as arc:
            for item in arc:
                need(item.isfile() and item.name in self.manifest['files'] and item.name not in seen and 0<item.size<=16777216,'EXACT_UNIQUE_REGULAR_MEMBER_REQUIRED');seen.add(item.name);total+=item.size;need(total<=67108864,'BOUNDED_PAYLOAD_REQUIRED')
                data=arc.extractfile(item).read(item.size+1);need(len(data)==item.size and H(data)==self.manifest['files'][item.name],'EXACT_PAYLOAD_MEMBER_BYTES_REQUIRED')
                parent=self.root
                for part in Path(item.name).parts[:-1]:parent/=part;self.c.c.mkdir(parent)
                self.m.write(self.root/item.name,data)
        need(seen==set(self.manifest['files']),'COMPLETE_PAYLOAD_REQUIRED')
    def image(self):
        m=self.m;need(m.image_id(m.BASE_IMAGE)==m.BASE_IMAGE,'EXACT_EXISTING_BASE_IMAGE_REQUIRED');base='t24-crm:'+SCOPE+'-base-'+SOURCE_SHA[:12];prior=m.image_id(base);need(prior is None or prior==m.BASE_IMAGE,'BASE_IMAGE_TAG_CHANGED')
        if prior is None:m.run(['docker','image','tag',m.BASE_IMAGE,base],'BASE_TAG_FAILED')
        m.write(self.root/'Dockerfile',('FROM '+base+'\n'+''.join('COPY backend/'+n+' /app/backend/'+n+'\n' for n in sorted(BACKEND_AFTER))).encode());m.write(self.root/'.dockerignore',b'*\n!Dockerfile\n!backend\n!backend/**\n')
        tag='t24-crm:'+SCOPE+'-'+SOURCE_SHA[:12]
        result=self.c.flow.flow.flow.pf.dependencies()[0].capture_public_build(['/usr/bin/env','DOCKER_BUILDKIT=0','docker','build','--network=none','--pull=false','-t',tag,str(self.root)],self.root/'app-build-public.log')
        self.record('app-build-result.json',result);need(result['exit_code']==0 and result['build_daemon_result_known'],'EXACT_OFFLINE_IMAGE_BUILD_REQUIRED');image=m.image_id(tag);need(re.fullmatch('sha256:[a-f0-9]{64}',image or '') and m.image_id(base)==m.BASE_IMAGE,'EXACT_CANDIDATE_IMAGE_REQUIRED');return image
    def offline_args(self,data,image):
        adapter=copy.copy(self.c);adapter.args=self.args;command=adapter.offline_args(data,image)
        need(command[-1]==image,'OFFLINE_IMAGE_POSITION_REQUIRED');command[-1:-1]=['-e','T24_MEDIA_MONTHLY_AUTOPREP_ENABLED=false'];return command
    def verify_offline(self,info):
        rows=info['Config']['Env'];need([x for x in rows if x.split('=',1)[0]=='T24_MEDIA_MONTHLY_AUTOPREP_ENABLED']==['T24_MEDIA_MONTHLY_AUTOPREP_ENABLED=false'],'ISOLATED_DRAFT_WORKER_DISABLED_REQUIRED')
        projected=copy.deepcopy(info);projected['Config']['Env']=[x for x in rows if x.split('=',1)[0]!='T24_MEDIA_MONTHLY_AUTOPREP_ENABLED'];self.c.verify_offline_environment(projected)
    def migration_identity(self,data):
        phase='production' if data==self.m.BUSINESS.parent else 'offline';return phase,self.root/('migration-'+phase+'-container.json')
    def settle_migration(self,data,image):
        phase,path=self.migration_identity(data)
        if not path.exists():return None
        saved=strict_json(protected(path));info=self.m.inspect(saved['id']);row=(data/'crm_prod.db').stat()
        need(saved=={'id':info['Id'],'name':'t24-'+SCOPE+'-migration-'+SOURCE_SHA[:12]+'-'+phase,'image':info['Image'],'phase':phase,'source_sha':SOURCE_SHA,'database_identity':[row.st_dev,row.st_ino]},'EXACT_DURABLE_MIGRATION_IDENTITY_REQUIRED')
        need(info['Image']==image and info['Name']=='/'+saved['name'] and info['Config'].get('Cmd')==['python','-B','-c',migration_script()] and info['HostConfig'].get('ReadonlyRootfs') is True,'EXACT_MIGRATION_IMAGE_COMMAND_AND_ROOTFS_REQUIRED');self.verify_offline(info)
        mounts={(r.get('Source'),r.get('Destination'),r.get('RW')) for r in info.get('Mounts',[]) if r.get('Type')=='bind'}
        need(mounts=={(str(data),'/app/backend/data',True),(str(self.root/'probe-logs'),'/app/backend/logs',True)} and all(r.get('Type')=='bind' or r.get('Type')=='tmpfs' and r.get('Destination')=='/tmp' for r in info.get('Mounts',[])),'EXACT_MIGRATION_MOUNTS_REQUIRED')
        if info['State']['Running']:self.m.run(['docker','wait',saved['id']],'MIGRATION_WAIT_INCOMPLETE',95);info=self.m.inspect(saved['id'])
        need(not info['State']['Running'],'MIGRATION_EXIT_REQUIRED');return info
    def run_migration(self,data,image):
        phase,path=self.migration_identity(data);need(not path.exists(),'MIGRATION_ALREADY_ATTEMPTED_REQUIRES_RECOVERY_REVIEW');name='t24-'+SCOPE+'-migration-'+SOURCE_SHA[:12]+'-'+phase;need(self.m.inspect_optional(name) is None,'FRESH_MIGRATION_NAME_REQUIRED')
        command=self.offline_args(data,image);command[1]='create';command.remove('--rm');command[2:2]=['--name',name]
        raw=self.m.run(command+['python','-B','-c',migration_script()],'MIGRATION_CREATE_FAILED',30);identity=raw.decode().strip();need(re.fullmatch('[a-f0-9]{64}',identity),'EXACT_MIGRATION_CONTAINER_ID_REQUIRED');row=(data/'crm_prod.db').stat()
        self.record(path.name,{'id':identity,'name':name,'image':image,'phase':phase,'source_sha':SOURCE_SHA,'database_identity':[row.st_dev,row.st_ino]});self.settle_migration(data,image)
        self.m.run(['docker','start',identity],'MIGRATION_START_FAILED',30);self.m.run(['docker','wait',identity],'MIGRATION_WAIT_INCOMPLETE',95);info=self.settle_migration(data,image)
        need(info['State'].get('Status')=='exited' and info['State'].get('ExitCode')==0,'MIGRATION_PROCESS_FAILED')
    def probe(self):
        return """import asyncio,socket,sys
def blocked(*a,**k):raise AssertionError('NO_PROVIDER_NETWORK')
socket.socket.connect=blocked
assert sys.version_info[:2]==(3,10)
from services import media_monthly_automation as service
from services.media_monthly_automation_worker import start_worker
assert service.enabled() is False and start_worker() is None
from main import app
import fastapi.routing
schema=app.openapi();prefix='/api/v1/media-monthly'
expected={(prefix+'/customers/{customer_id}/automation','GET'),(prefix+'/customers/{customer_id}/automation','PUT'),(prefix+'/automation/requests/{request_id}','GET'),(prefix+'/automation/overview','GET')}
actual={(p,m.upper()) for p,v in schema['paths'].items() if p.startswith(prefix) and '/automation' in p for m in v if m.lower() in {'get','put','post','patch','delete'}}
assert actual==expected
contexts=list(fastapi.routing.iter_route_contexts(app.routes)) if hasattr(fastapi.routing,'iter_route_contexts') else app.routes
registered=[(x.path,m,getattr(getattr(x,'endpoint',None),'__module__','')) for x in contexts if '/automation' in getattr(x,'path','') and getattr(getattr(x,'endpoint',None),'__module__','')=='routers.media_monthly_automation' for m in (getattr(x,'methods',set()) or set())]
assert len(registered)==4 and {(p,m) for p,m,_ in registered}==expected
from types import SimpleNamespace
from fastapi import HTTPException
class NoDb:
 def __getattr__(self,name):raise AssertionError('UNAUTHORIZED_AUTOMATION_MUST_NOT_QUERY_SQL')
async def denied():
 for role in ('sales','finance','operations','admin','customer_service'):
  user=SimpleNamespace(id='2147483647',role=role)
  calls=[service.get_policy(NoDb(),user,42),service.overview(NoDb(),user),service.request_result(NoDb(),user,'00000000-0000-4000-8000-000000000001'),service.save_policy(NoDb(),user,42,request_id='00000000-0000-4000-8000-000000000001',expected_revision=0,enabled=True,lead_days=7,local_time='09:00',source_signature='a'*64,runtime_fingerprint='b'*64,confirmed=True,notice_version=service.NOTICE_VERSION)]
  for call in calls:
   try:await call
   except HTTPException as error:assert error.status_code==403
   else:raise AssertionError('AUTOMATION_OWNER_ONLY_BOUNDARY_REQUIRED')
asyncio.run(denied())
print('EXACT_DRAFT_AUTOMATION_DEFAULT_OFF_ROUTES_NO_NETWORK')
"""
    def monthly_scope_probe(self):
        value=self.c.monthly_scope_probe();old="schema=app.openapi()"
        need(value.count(old)==1 and value.count('assert len(expected)==16')==1 and value.count('assert len(registered)==16')==1,'EXACT_RETAINED_MONTHLY_CANARY_REQUIRED')
        added="expected|={(prefix+'/customers/{customer_id}/automation','GET','routers.media_monthly_automation'),(prefix+'/customers/{customer_id}/automation','PUT','routers.media_monthly_automation'),(prefix+'/automation/requests/{request_id}','GET','routers.media_monthly_automation'),(prefix+'/automation/overview','GET','routers.media_monthly_automation')}\n"
        return value.replace(old,added+old,1).replace('assert len(expected)==16','assert len(expected)==20',1).replace('assert len(registered)==16','assert len(registered)==20',1)
    def prepare(self):
        m=self.m;old=self.current();need({p.name for p in self.root.iterdir()}=={'release.py','preflight.py','manifest.json','payload.tar.gz'},'FRESH_STAGING_REQUIRED');self.extract();expected={**self.original_inventory,**BACKEND_AFTER};image=self.image()
        self.record('original-runtime.json',m.runtime(old));self.record('backend-original-inventory.json',self.original_inventory);candidate_inventory=self.record('backend-candidate-inventory.json',expected)
        data=self.root/'probe-data';data.mkdir(mode=0o700);(self.root/'probe-logs').mkdir(mode=0o700);m.backup(m.BUSINESS,data/'crm_prod.db');self.db_boundary(data/'crm_prod.db');self.run_migration(data,image);schema=self.db_boundary(data/'crm_prod.db',migrated=True);metadata=self.c.metadata(data/'crm_prod.db');rows=self.rows(data/'crm_prod.db')
        command=self.offline_args(data,image);command[2:2]=['--name',self.offline_name,'-d'];need(not m.inspect_optional(self.offline_name),'FRESH_OFFLINE_NAME_REQUIRED');m.run(command,'OFFLINE_START_FAILED')
        try:
            m.ready(self.offline_name);self.verify_offline(m.inspect(self.offline_name));need(m.inventory(self.offline_name)==expected,'EXACT_OFFLINE_SOURCE_REQUIRED')
            checks=[(self.probe(),b'EXACT_DRAFT_AUTOMATION_DEFAULT_OFF_ROUTES_NO_NETWORK'),(self.c.meta_monthly_probe(),b'EXACT_META_MONTHLY_PLATFORM_OWNER_PREPARED_BOUNDARY'),(self.monthly_scope_probe(),b'EXACT_PY310_GENERIC_MONTH_RULES_OWNER_BOUNDARY_NO_NETWORK'),(self.c.projection_probe(),b'EXACT_PY310_TWO_GET_PROJECTION_ROUTES_ROLE_DENIED'),(self.c.ctx.workflow.owner_denied_probe(),b'EXACT_NONOWNER_ROLE_READ_DENIED_NO_SQL_OR_NETWORK')]
            for code,marker in checks:need(marker in m.run(['docker','exec',self.offline_name,'python','-B','-c',code],'OFFLINE_CANARY_FAILED'),'EXACT_OFFLINE_CANARY_MARKER_REQUIRED')
        finally:m.run(['docker','stop','--time','20',self.offline_name],'OFFLINE_STOP_FAILED',45)
        need(self.rows(data/'crm_prod.db')==rows and self.c.metadata(data/'crm_prod.db')==metadata and self.db_boundary(data/'crm_prod.db',migrated=True)==schema,'OFFLINE_STARTUP_OR_PROBE_CHANGED_ROWS')
        root,static=m.stage_public(self.root,self.manifest);nginx=next_nginx(m.NGINX.read_bytes(),self.old_public,root,self.proof['nginx_sha256']);self.current()
        result={'stage':'MEDIA_AUTOMATION_PREPARED','source_sha':SOURCE_SHA,'frontend_version':FRONTEND,'old_schema_revision':OLD_REVISION,'schema_revision':NEW_REVISION,'table_count':165,'old_crm':m.runtime(old),'candidate_image':image,'candidate_inventory_sha256':candidate_inventory,'schema_after_sha256':schema,'public_root':str(root),'public_inventory_sha256':static,'nginx_next_sha256':H(nginx),'preflight_sha256':PREFLIGHT_SHA,'manifest_sha256':self.args.manifest_sha256,'payload_sha256':self.args.payload_sha256,'offline_three_empty_tables_verified':True,'original162_rows_schema_preserved':True,'offline_network_none_credentials_absent_workers_off':True,'automation_worker_enabled':False,'production_database_written':False,'provider_requests':False,'business_seed_rows':False,'database_restored':False}
        return {**result,'receipt_sha256':self.record('prepared.json',result)}
    def reviewed(self):
        r=strict_json(protected(self.root/'prepared.json',self.args.review_sha256));validate_prepared(r,self.args.manifest_sha256,self.args.payload_sha256,PREFLIGHT_SHA);old=self.m.inspect(self.proof['crm']['id']);need(self.m.runtime(old)==self.proof['crm'] and self.m.image_id(r['candidate_image'])==r['candidate_image'],'EXACT_ORIGINAL_AND_REVIEWED_IMAGE_REQUIRED');need(self.m.verify_public(self.public,self.manifest)==r['public_inventory_sha256'],'REVIEWED_STATIC_CHANGED');return r,old
    def identities(self,r,old):
        state=strict_json(protected(self.root/'candidate-created.json'));need(state=={'source_sha':SOURCE_SHA,'candidate_id':state['candidate_id'],'candidate_image':r['candidate_image'],'original_id':old['Id'],'review_sha256':self.args.review_sha256} and re.fullmatch('[a-f0-9]{64}',state['candidate_id']),'EXACT_DURABLE_CANDIDATE_REQUIRED');a=self.m.inspect(old['Id']);b=self.m.inspect(state['candidate_id'])
        need(a['Image']==old['Image'] and self.m.runtime(a)['config']==self.m.runtime(old)['config'] and a['Name'] in {'/t24-crm','/'+self.old_name} and b['Image']==r['candidate_image'] and b['Name'] in {'/t24-crm','/'+self.candidate_name},'KNOWN_ORIGINAL_AND_CANDIDATE_REQUIRED')
        primary=self.m.inspect_optional('t24-crm');need(not primary or primary['Id'] in {a['Id'],b['Id']},'UNKNOWN_PRIMARY_NOT_CHANGED');return a,b
    def fresh(self,r,old,*,migrated=False,updated=False,live=False,recovery=False):
        schema=self.protections(migrated=migrated,updated=updated,recovery=recovery);need(not migrated or schema==r['schema_after_sha256'],'EXACT_REVIEWED_ADDITIVE_SCHEMA_REQUIRED');a,b=self.identities(r,old);self.c.retained.compare(b,old,self.m);self.environment(a);self.environment(b);self.c.source_boundary(a,self.original_inventory);self.c.source_boundary(b,{**self.original_inventory,**BACKEND_AFTER})
        need(b['RestartCount']==0,'CANDIDATE_RESTARTED');need(live and b['State']['Running'] is True and a['State']['Running'] is False and self.m.inspect('t24-crm')['Id']==b['Id'] or not live and b['State']['Running'] is False,'ONLY_SINGLE_KNOWN_WRITER_ALLOWED')
        if live:self.c.helper.validation_window(b)
        return a,b
    def public_check(self,identity):
        body=self.m.run(['curl','-q','--silent','--show-error','--fail','--noproxy','*','--http1.1','--max-time','5','--max-redirs','0','--resolve','t24-crm.com:443:127.0.0.1','https://t24-crm.com/app-version.json?automation='+FRONTEND],'PUBLIC_VERSION_READ_FAILED',10);need(len(body)<1024 and strict_json(body)=={'version':FRONTEND},'PUBLIC_FRONTEND_VERSION_CHANGED');self.staticmod.public_security_policy(self.m,self.proof['content_security_policy_sha256'])
        probe=types.SimpleNamespace(m=self.m,retained=self.c.retained,proof=self.proof,nginx=self.nginx,pf=types.SimpleNamespace(meta_environment=self.environment),rows=self.c.rows)
        privacy={**self.c.ctx.module.OperationsMethods.delivery_sentinel(probe,identity),**self.c.retained.Release.meta_callback_sentinel(probe,identity),**self.c.ctx.workflow.pf.security_headers(self.m)}
        need(privacy['content_security_policy_sha256']==self.proof['content_security_policy_sha256'],'EXACT_PUBLIC_PRIVACY_POLICY_REQUIRED');return privacy
    def activate(self):
        m=self.m;r,old=self.reviewed();self.current();need(not(self.root/'activation-started.json').exists() and not m.inspect_optional(self.old_name) and not m.inspect_optional(self.candidate_name),'FRESH_SWITCH_REQUIRED');nginx=m.NGINX.read_bytes();new=next_nginx(nginx,self.old_public,self.public,self.proof['nginx_sha256']);need(H(new)==r['nginx_next_sha256'],'EXACT_REVIEWED_NGINX_REQUIRED');self.record('nginx-before.conf',nginx);self.record('activation-started.json',{'source_sha':SOURCE_SHA,'prepared_sha256':self.args.review_sha256,'original_id':old['Id']})
        status,body=m.retained().docker_request('POST','/containers/create?name='+self.candidate_name,m.clone_config(r['candidate_image'],old));need(status==201,'CANDIDATE_CREATE_FAILED');identity=json.loads(body)['Id'];need(re.fullmatch('[a-f0-9]{64}',identity),'EXACT_CREATED_CONTAINER_ID_REQUIRED');self.record('candidate-created.json',{'source_sha':SOURCE_SHA,'candidate_id':identity,'candidate_image':r['candidate_image'],'original_id':old['Id'],'review_sha256':self.args.review_sha256})
        try:
            _,candidate=self.fresh(r,old);need(candidate['State']['Status']=='created','NEVER_STARTED_CANDIDATE_REQUIRED');m.run(['docker','stop','--time','30',old['Id']],'ORIGINAL_STOP_FAILED',60);a,_=self.fresh(r,old);need(a['State']['Running'] is False,'STOPPED_ORIGINAL_REQUIRED')
            m.backup(m.BUSINESS,self.root/'production-before.db');self.run_migration(m.BUSINESS.parent,r['candidate_image']);self.fresh(r,old,migrated=True)
            m.run(['docker','rename',old['Id'],self.old_name],'ORIGINAL_RENAME_FAILED');m.run(['docker','rename',identity,'t24-crm'],'CANDIDATE_RENAME_FAILED');self.fresh(r,old,migrated=True)
            m.run(['docker','start',identity],'CANDIDATE_START_FAILED');m.ready(identity);self.fresh(r,old,migrated=True,live=True);m.replace_nginx(nginx,new);m.retained().reload_nginx();self.fresh(r,old,migrated=True,updated=True,live=True);privacy=self.public_check(identity);_,candidate=self.fresh(r,old,migrated=True,updated=True,live=True)
            result={'stage':'MEDIA_AUTOMATION_DEPLOYED','source_sha':SOURCE_SHA,'frontend_version':FRONTEND,'schema_revision':NEW_REVISION,'table_count':165,'crm':m.runtime(candidate),'prepared_sha256':self.args.review_sha256,'preflight_sha256':PREFLIGHT_SHA,'schema_after_sha256':r['schema_after_sha256'],'public_root':str(self.public),'public_inventory_sha256':r['public_inventory_sha256'],'nginx_sha256':H(m.NGINX.read_bytes()),'original162_rows_schema_preserved':True,'three_new_tables_empty':True,'environment_credentials_private_acl_preserved':True,'google_meta_cutoffs_preserved':True,'automation_worker_enabled':False,'operations_execution_enabled':False,'operations_scheduler_enabled':False,'provider_requests':False,'business_seed_rows':False,'database_restored':False,'privacy':privacy};return {**result,'receipt_sha256':self.record('deployed.json',result)}
        except BaseException:self.recover_internal(r,old);raise
    def recover_internal(self,r,old):
        m=self.m;self.settle_migration(m.BUSINESS.parent,r['candidate_image']);a,b=self.identities(r,old)
        if b['State']['Running']:m.run(['docker','stop','--time','30',b['Id']],'RECOVERY_CANDIDATE_STOP_FAILED',60)
        head=self.revision();updated=H(m.NGINX.read_bytes())==r['nginx_next_sha256'];self.fresh(r,old,migrated=head==NEW_REVISION,updated=updated,recovery=True)
        # The old image ignores the three additive tables. Keep the new head
        # and current rows; no downgrade, drop, DELETE or database file restore.
        if updated:m.replace_nginx(m.NGINX.read_bytes(),protected(self.root/'nginx-before.conf',self.proof['nginx_sha256']))
        m.retained().reload_nginx();a,b=self.identities(r,old)
        if b['Name']=='/t24-crm':m.run(['docker','rename',b['Id'],self.candidate_name],'RETAIN_STOPPED_CANDIDATE_FAILED')
        if a['Name']!='/t24-crm':m.run(['docker','rename',a['Id'],'t24-crm'],'RESTORE_ORIGINAL_NAME_FAILED')
        if not a['State']['Running']:m.run(['docker','start',a['Id']],'ORIGINAL_RESUME_FAILED')
        m.ready(a['Id']);restored=m.inspect('t24-crm');need(restored['Id']==old['Id'] and restored['State']['Running'] is True and m.runtime(restored)['config']==m.runtime(old)['config'],'EXACT_ORIGINAL_RESTORED_REQUIRED');self.environment(restored);self.protections(migrated=head==NEW_REVISION,recovery=True)
        result={'stage':'MEDIA_AUTOMATION_ORIGINAL_RESUMED','source_sha':BASE_SOURCE,'schema_revision':head,'additive_tables_retained':head==NEW_REVISION,'all_current_rows_preserved':True,'database_restored':False,'provider_requests':False,'candidate_retained_stopped':True};return {**result,'receipt_sha256':self.record('recovery.json',result)}
    def recover(self):
        r,old=self.reviewed();need(not(self.root/'deployed.json').exists(),'SUCCESSFUL_RELEASE_RECOVERY_REQUIRES_SEPARATE_REVIEW')
        if not(self.root/'candidate-created.json').exists():self.current();return {'stage':'MEDIA_AUTOMATION_ORIGINAL_UNCHANGED','database_restored':False,'orphan_review_required':True}
        return self.recover_internal(r,old)

def validate_prepared(r,manifest,payload,preflight):
    pins_ready();need(r['stage']=='MEDIA_AUTOMATION_PREPARED' and r['source_sha']==SOURCE_SHA and r['frontend_version']==FRONTEND and r['old_schema_revision']==OLD_REVISION and r['schema_revision']==NEW_REVISION and r['table_count']==165 and r['manifest_sha256']==manifest and r['payload_sha256']==payload and r['preflight_sha256']==preflight==PREFLIGHT_SHA,'EXACT_PREPARED_ADDITIVE_SCOPE_REQUIRED')
    need(all(r[k] is True for k in ('offline_three_empty_tables_verified','original162_rows_schema_preserved','offline_network_none_credentials_absent_workers_off')) and all(r[k] is False for k in ('automation_worker_enabled','production_database_written','provider_requests','business_seed_rows','database_restored')),'EXACT_ISOLATED_PREPARE_REQUIRED')
    need(all(re.fullmatch('[a-f0-9]{64}',r[k]) for k in ('candidate_inventory_sha256','schema_after_sha256','public_inventory_sha256','nginx_next_sha256')) and re.fullmatch('sha256:[a-f0-9]{64}',r['candidate_image']) and r['public_root']=='/var/www/t24-crm-public/'+SCOPE+'-'+SOURCE_SHA[:12]+'-20261102','EXACT_PREPARED_ARTIFACT_PINS_REQUIRED')
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=('prepare','activate','recover'),required=True);parser.add_argument('--release',type=Path,required=True);parser.add_argument('--manifest-sha256',required=True);parser.add_argument('--payload-sha256',required=True);parser.add_argument('--preflight',type=Path,required=True);parser.add_argument('--preflight-sha256',required=True);parser.add_argument('--review-sha256');args=parser.parse_args()
    pins_ready();need(os.geteuid()==0 and socket.gethostname()==HOST,'EXACT_ROOT_SERVER_REQUIRED');resource.setrlimit(resource.RLIMIT_CORE,(0,0));os.umask(0o077);need(args.preflight_sha256==PREFLIGHT_SHA,'EXACT_PREFLIGHT_ARGUMENT_REQUIRED')
    lock=Path('/opt/t24-crm/releases/.media-workspace-scale.lock')
    for p in lock.parents:
        row=p.lstat();need(p.resolve()==p and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_SHARED_LOCK_PARENT_REQUIRED')
    fd=os.open(lock,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        r=os.fstat(fd);need(stat.S_ISREG(r.st_mode) and r.st_uid==0 and r.st_nlink==1 and stat.S_IMODE(r.st_mode)==0o600,'ROOT_PRIVATE_SHARED_LOCK_REQUIRED');fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);release=Release(args);need(args.phase=='prepare' or args.review_sha256,'PREPARED_REVIEW_REQUIRED');print(json.dumps(getattr(release,args.phase)(),sort_keys=True))
    finally:os.close(fd)
if __name__=='__main__':
    try:main()
    except BaseException as e:
        value=str(e);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'MEDIA_AUTOMATION_RELEASE_REJECTED';print(json.dumps({'stage':'MEDIA_AUTOMATION_RELEASE_REJECTED','code':code,'database_restored':False},sort_keys=True));raise SystemExit(1)
