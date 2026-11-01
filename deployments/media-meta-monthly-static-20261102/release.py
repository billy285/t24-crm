"""Static-only priority layout release. No database or container mutations.

The only live mutation is an exact reversible Nginx public-root substitution.
All162 current tables, runtime, credentials, private boundaries and CSP stay fixed.
"""
import argparse,copy,fcntl,hashlib,io,json,os,re,resource,socket,stat,tarfile,types
from pathlib import Path
HOST='iZj6c4cj7edgnhdimts4l7Z'
SCOPE='media-meta-monthly-static'
SOURCE_SHA='eec3d1d02a97a5b52a1483e0c93f094242aade56'
FRONTEND='8c3b5e1302ac'
BASE_SOURCE='5fd379d625d6c18abdec1b98d388494d0900c780'
BASE_FRONTEND='1d94d63752de'
HEAD='g32ed456e792'
FILES=frozenset(['app/frontend/src/components/MediaPortfolioPanels.tsx', 'app/frontend/src/components/media-merchant-workspace.css', 'app/frontend/tests/media-workspace-queue.test.mjs'])
CHANGED_SOURCE_HASHES={'app/frontend/src/components/MediaPortfolioPanels.tsx': '9842b5f124661e10ee6f72a16437f08685b20aa1b4de919fd44213f6fdbb2b22', 'app/frontend/src/components/media-merchant-workspace.css': '12c255efa167d02a51a596c3cc1794cdf3b21e3cf1e3db8b2e5a3da2f3f2c3a9', 'app/frontend/tests/media-workspace-queue.test.mjs': 'd6bf2929c6462a283f2070c1c5afdabfbb4fb6def4a6251c25952e0a7678179f'}
PREFLIGHT_CODE_SHA='8161ec8181fdc3bbfbed1f0063d01890618ee24b94fc6c19c3329d90cad3fa64'
PREFLIGHT_SHA='78bb1249abca9506a9158c88fcbc31edf36c0eef6926c07ddc07f6235e0a9143'
APPLICATION_FREEZE_SHA='917e7976c1474fc5882f39b3dbcd455793ea530f57d1c75224ac5e2e4db063a9'

CSP_SHA='ead64b09efe8c4f35648aa8eafe8855c5268ecf0999e0918b3642dd9dfbfe7a6'
TRUE_FLAGS=('static_only','exact_monthly_action_layout_only','original162_database_preservation_required','runtime_environment_and_private_boundaries_preservation_required','existing_hashed_assets_preserved')
FALSE_FLAGS=('backend_changes','database_migration','database_writes','container_restarts','environment_changes','permissions_changes','dependencies_changes','content_security_policy_changes','publications_or_provider_writes','credentials_included')
RUNTIME={'config': '5038d2dcddb9b0215926f5d45411c25b56542c678a082a8b05774054b1d9c94e', 'id': '1ee579193b73048fb1120f516d53d2400191c2499cfad5284184ca0506ed698e', 'image': 'sha256:05dc7e8e8ce620e0d92e07e95d304537250d17beb14dbeb63713e06d2319bf41', 'restart': 0, 'started': '2026-11-01T22:06:12.469255563Z'}
H=lambda b:hashlib.sha256(b).hexdigest()
def need(ok,code):
    if not ok:raise RuntimeError(code)
def encoded(value):return (json.dumps(value,sort_keys=True,indent=2)+'\n').encode()
def digest(value):return H(json.dumps(value,sort_keys=True,separators=(',',':')).encode())
def strict_json(body):
    def pairs(rows):
        value={}
        for k,v in rows:need(k not in value,'DUPLICATE_JSON_KEY_REJECTED');value[k]=v
        return value
    def constant(value):raise RuntimeError('NONFINITE_JSON_REJECTED')
    return json.loads(body,object_pairs_hook=pairs,parse_constant=constant)
def protected(path,sha=None,maximum=16777216):
    need(path.is_absolute() and path.resolve()==path,'CANONICAL_ROOT_PRIVATE_PATH_REQUIRED')
    for p in path.parents:
        row=p.lstat();need(stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_PARENT_REQUIRED')
    row=path.lstat();need(stat.S_ISREG(row.st_mode) and row.st_uid==0 and row.st_nlink==1 and stat.S_IMODE(row.st_mode)==0o600,'ROOT_PRIVATE_REGULAR_FILE_REQUIRED')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as stream:opened=os.fstat(stream.fileno());body=stream.read(maximum+1);after=os.fstat(stream.fileno())
    ident=lambda x:(x.st_dev,x.st_ino,x.st_mode,x.st_uid,x.st_size,x.st_nlink,x.st_mtime_ns,x.st_ctime_ns)
    need(ident(row)==ident(opened)==ident(after)==ident(path.lstat()) and len(body)==row.st_size<=maximum and (sha is None or H(body)==sha),'EXACT_STABLE_PROTECTED_BYTES_REQUIRED');return body

def pins_ready():
    need(all(isinstance(v,str) and re.fullmatch('[a-f0-9]{64}',v) for v in (PREFLIGHT_CODE_SHA,PREFLIGHT_SHA,APPLICATION_FREEZE_SHA)) and isinstance(SOURCE_SHA,str) and re.fullmatch('[a-f0-9]{40}',SOURCE_SHA) and isinstance(FRONTEND,str) and re.fullmatch('[a-f0-9]{12}',FRONTEND),'FINAL_PRIORITY_PROOF_AND_FREEZE_REQUIRED')
    need(SOURCE_SHA!='0'*40 and SOURCE_SHA!=BASE_SOURCE and FRONTEND!='0'*12 and FRONTEND!=BASE_FRONTEND and PREFLIGHT_SHA!='0'*64 and APPLICATION_FREEZE_SHA!='0'*64,'FINAL_NONZERO_STATIC_PINS_REQUIRED')
    need(bool(FILES) and set(CHANGED_SOURCE_HASHES)==FILES and all(re.fullmatch('[a-f0-9]{64}',v) for v in CHANGED_SOURCE_HASHES.values()),'EXACT_COMPONENT_AND_TEST_FREEZE_REQUIRED')
def validate_manifest(v,payload):
    pins_ready();need(v['stage']=='MEDIA_META_MONTHLY_UI_STATIC_PAYLOAD' and v['source_sha']==SOURCE_SHA and v['backend_source_sha']==BASE_SOURCE and v['baseline_source_sha']==BASE_SOURCE and v['frontend_version']==FRONTEND and v['baseline_frontend_version']==BASE_FRONTEND,'EXACT_PRIORITY_ONLY_APPLICATION_SCOPE_REQUIRED')
    need(v['schema_revision']==HEAD and v['table_count']==162 and v['preflight_sha256']==PREFLIGHT_SHA and v['application_freeze_sha256']==APPLICATION_FREEZE_SHA and v['payload_sha256']==payload and v['changed_source_files']==CHANGED_SOURCE_HASHES,'EXACT_STATIC_PROOF_FILE_PINS_REQUIRED')
    need(all(v[x] is True for x in TRUE_FLAGS) and all(v[x] is False for x in FALSE_FLAGS),'NO_BACKEND_DATABASE_RUNTIME_OR_PERMISSION_MUTATIONS_ALLOWED')
    need(isinstance(v['protected_source_inventory'],dict) and len(v['protected_source_inventory'])>1000 and not FILES.intersection(v['protected_source_inventory']) and all(re.fullmatch('[a-f0-9]{64}',s) for s in v['protected_source_inventory'].values()),'COMPLETE_UNCHANGED_APP_SOURCE_INVENTORY_REQUIRED')

def changed_nginx(body,old,new,expected):
    a=('root '+str(old)+';').encode();b=('root '+str(new)+';').encode()
    need(H(body)==expected and body.count(a)==1 and b not in body,'EXACT_CURRENT_STATIC_ROOT_REQUIRED')
    value=body.replace(a,b,1);need(value.replace(b,a,1)==body,'ONLY_STATIC_ROOT_SUBSTITUTION_ALLOWED');return value

def public_security_policy(m, expected_sha):
    # Public SPA header only: no cookie, authenticated API, provider or body.
    argv = ['curl', '-q', '--silent', '--show-error', '--noproxy', '*', '--http1.1', '--max-time', '5', '--max-redirs', '0', '--resolve', 't24-crm.com:443:127.0.0.1', '-D', '-', '-o', '/dev/null', 'https://t24-crm.com/media-ops']
    body = m.run(argv, 'PUBLIC_CSP_HEADER_READ_FAILED', 10)
    need(isinstance(body, bytes) and len(body) < 16384, 'BOUNDED_PUBLIC_HEADERS_REQUIRED')
    lines = body.decode('iso-8859-1').splitlines()
    need(lines and re.fullmatch(r'HTTP/1[.]1 200(?: .*)?', lines[0]), 'EXACT_PUBLIC_SPA_200_REQUIRED')
    values = [line.split(':', 1)[1].strip() for line in lines[1:] if ':' in line and line.split(':', 1)[0].lower() == 'content-security-policy']
    need(len(values) == 1 and 0 < len(values[0]) < 8192 and H(values[0].encode()) == expected_sha, 'EXACT_EXISTING_PUBLIC_CSP_REQUIRED')
    return values[0]


class Release:
    def __init__(self,args):
        pins_ready();self.args=args;self.root=args.release
        need(self.root==Path('/opt/t24-crm/releases/'+SCOPE+'-'+SOURCE_SHA[:12]+'-20261102'),'EXACT_FRESH_RELEASE_NAMESPACE_REQUIRED')
        code=protected(self.root/'preflight.py',PREFLIGHT_CODE_SHA,131072);pf=types.ModuleType('_exact_priority_preflight');pf.__file__=str(self.root/'preflight.py');exec(compile(code,pf.__file__,'exec'),pf.__dict__)
        self.pf=pf;_,self.ctx,self.inventory=pf.dependencies();self.m=self.ctx.m
        self.proof=strict_json(protected(args.preflight,PREFLIGHT_SHA,1048576));self.manifest=strict_json(protected(self.root/'manifest.json',args.manifest_sha256,1048576));protected(self.root/'payload.tar.gz',args.payload_sha256)
        need(args.preflight==Path('/opt/t24-crm/releases/media-meta-monthly-static-preflight-'+PREFLIGHT_SHA[:12]+'.json') and self.proof['stage']=='MEDIA_META_MONTHLY_STATIC_READONLY_PREFLIGHT' and self.proof['crm']==RUNTIME and self.proof['source_sha']==BASE_SOURCE and self.proof['frontend_version']==BASE_FRONTEND and self.proof['schema_revision']==HEAD and len(self.proof['rows'])==162 and self.proof['backend_inventory']==self.inventory,'EXACT_FRESH_CURRENT162_BASELINE_REQUIRED')
        need(self.proof['content_security_policy_sha256']==CSP_SHA,'EXACT_CURRENT_CSP_REQUIRED')
        validate_manifest(self.manifest,args.payload_sha256)
        need(all(name.startswith('static/') and self.m.static_path(name[7:]) and re.fullmatch('[a-f0-9]{64}',sha) for name,sha in self.manifest['files'].items()) and {'static/index.html','static/app-version.json'}<=set(self.manifest['files']),'STATIC_MEMBERS_ONLY_REQUIRED')
        self.public=Path('/var/www/t24-crm-public/'+SCOPE+'-'+SOURCE_SHA[:12]+'-20261102');self.old_public=Path(self.proof['public_root'])
        self.m.PUBLIC=self.old_public;self.m.STATIC_SHA=self.proof['public_inventory_sha256'];self.m.SCOPE=SCOPE;self.m.NGINX_SHA=self.proof['nginx_sha256'];self.m.FRONTEND_VERSION=FRONTEND;self.m.public_root=lambda:self.public
    def record(self,name,value):
        sha=self.m.write(self.root/name,value)
        fd=os.open(self.root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(fd)
        finally:os.close(fd)
        return sha
    def nginx(self,updated):
        body=self.m.NGINX.read_bytes();active=self.m.run(['nginx','-T'],'NGINX_READ_FAILED');expected=self.proof
        if updated:
            new,old=os.fsencode(self.public),os.fsencode(self.old_public);need(body.count(new)==active.count(new)==1,'EXACT_NEW_ROOT_REQUIRED');body=body.replace(new,old,1);active=active.replace(new,old,1)
        need(H(body)==expected['nginx_sha256'] and H(active)==expected['active_nginx_sha256'],'NGINX_PROXY_HEADERS_CSP_OR_OTHER_BYTES_CHANGED')
    def boundary(self,updated=False):
        p,m,c=self.proof,self.m,self.ctx;info=m.inspect('t24-crm')
        need(info['State']['Running'] is True and m.runtime(info)==RUNTIME and m.inventory(RUNTIME['id'])==self.inventory,'BACKEND_RUNTIME_ENV_OR_SOURCE_CHANGED')
        env,ops=c.environment(info);need(env==p['environment_sha256'] and ops==p['ops_environment_sha256'],'FULL_ENVIRONMENT_CHANGED');c.ctx.workflow.pf.google_environment(info);m.verify_secret_mount(info);m.verify_production_worker_enabled(info)
        need(c.safe.safe_private_boundary(m,c.pins)==p['private_boundary'],'PRIVATE_BOUNDARY_CHANGED')
        credentials={'ops':c.safe.protected_metadata(c.c.ENV_FILE),'google':c.safe.protected_metadata(c.safe.GBP_ENV),'meta_read':c.safe.protected_metadata(c.ctx.workflow.core.ENV_FILE),'meta_legacy':c.safe.protected_metadata(c.ctx.workflow.core.LEGACY_ENV_FILE)}
        need(credentials==p['credential_metadata'] and m.credential_boundary()==p['credential_boundary'],'CREDENTIAL_METADATA_CHANGED')
        need([m.BUSINESS.stat().st_dev,m.BUSINESS.stat().st_ino]==p['database_identity'] and m.schema_signature(m.BUSINESS,HEAD)==p['schema_sha256'],'DATABASE_IDENTITY_OR_SCHEMA_CHANGED')
        rows=c.retained.evidence(c.rows());need(rows==p['rows'] and len(rows)==162,'ANY_CURRENT162_ROWS_CHANGED');c.retained.live_sequence_boundary(p['database_metadata'],c.metadata(m.BUSINESS))
        need(digest(m.tree(self.old_public))==p['public_inventory_sha256'],'OLD_STATIC_BYTES_CHANGED');self.nginx(updated)
        return {'runtime':RUNTIME,'rows_sha256':digest(rows),'schema_sha256':p['schema_sha256'],'environment_sha256':env,'ops_environment_sha256':ops,'original162_rows_preserved':True,'backend_source_unchanged':True,'private_boundary_preserved':True,'credentials_preserved':True,'content_security_policy_unchanged':True}
    def extract(self):
        payload=protected(self.root/'payload.tar.gz',self.args.payload_sha256);seen=set();total=0
        with tarfile.open(fileobj=io.BytesIO(payload),mode='r:gz') as archive:
            for item in archive:
                need(item.isfile() and item.name in self.manifest['files'] and item.name not in seen and 0<item.size<=16777216,'EXACT_UNIQUE_REGULAR_STATIC_MEMBER_REQUIRED');seen.add(item.name);total+=item.size;need(total<=67108864,'BOUNDED_STATIC_PAYLOAD_REQUIRED')
                body=archive.extractfile(item).read(item.size+1);need(len(body)==item.size and H(body)==self.manifest['files'][item.name],'STATIC_MEMBER_BYTES_CHANGED')
                target=self.root/item.name
                # These paths are closed by static_path; create only private
                # payload directories, never an arbitrary archive destination.
                parent=self.root
                for part in Path(item.name).parts[:-1]:
                    parent/=part
                    if not parent.exists():parent.mkdir(mode=0o700)
                    need(parent.resolve()==parent and parent.is_dir() and parent.stat().st_uid==0 and not parent.stat().st_mode&0o077,'PRIVATE_STATIC_STAGE_REQUIRED')
                self.m.write(target,body)
        need(seen==set(self.manifest['files']),'COMPLETE_STATIC_PAYLOAD_REQUIRED')
    def public_check(self):
        m=self.m;body=m.run(['curl','-q','--silent','--show-error','--fail','--noproxy','*','--http1.1','--max-time','5','--max-redirs','0','--resolve','t24-crm.com:443:127.0.0.1','https://t24-crm.com/app-version.json?priority='+FRONTEND],'PUBLIC_VERSION_READ_FAILED',10)
        need(len(body)<1024 and strict_json(body)=={'version':FRONTEND},'PUBLIC_FRONTEND_VERSION_CHANGED');public_security_policy(m,CSP_SHA)
    def prepare(self):
        self.boundary();need(not(self.root/'prepared.json').exists() and not self.public.exists(),'FRESH_STATIC_PREPARE_REQUIRED');self.extract();root,inventory=self.m.stage_public(self.root,self.manifest);after=self.boundary()
        changed=changed_nginx(self.m.NGINX.read_bytes(),self.old_public,root,self.proof['nginx_sha256'])
        value={'stage':'MEDIA_META_MONTHLY_UI_STATIC_PREPARED','source_sha':SOURCE_SHA,'backend_source_sha':BASE_SOURCE,'frontend_version':FRONTEND,'manifest_sha256':self.args.manifest_sha256,'payload_sha256':self.args.payload_sha256,'preflight_sha256':PREFLIGHT_SHA,'public_root':str(root),'public_inventory_sha256':inventory,'nginx_next_sha256':H(changed),'boundary':after,'static_only':True,'database_writes':False,'container_restarts':False,'schema_changes':False,'permissions_changes':False,'provider_or_publication_actions':False};return {**value,'receipt_sha256':self.record('prepared.json',value)}
    def reviewed(self):
        value=strict_json(protected(self.root/'prepared.json',self.args.review_sha256));validate_prepared(value,self.args.manifest_sha256,self.args.payload_sha256,PREFLIGHT_SHA);need(self.m.verify_public(self.public,self.manifest)==value['public_inventory_sha256'],'REVIEWED_STATIC_CONTENT_CHANGED');return value
    def recover(self):
        value=self.reviewed();old=protected(self.root/'nginx-before.conf');new=changed_nginx(old,self.old_public,self.public,self.proof['nginx_sha256']);need(H(new)==value['nginx_next_sha256'],'EXACT_STATIC_RECOVERY_BYTES_REQUIRED');current=self.m.NGINX.read_bytes()
        need(current in (old,new),'UNKNOWN_NGINX_CONFIG_NOT_REPLACED');self.boundary(updated=current==new)
        if current==new:self.m.replace_nginx(new,old);self.m.retained().reload_nginx()
        self.boundary(False);result={'stage':'MEDIA_META_MONTHLY_UI_STATIC_ROOT_RESTORED','database_restored':False,'container_restarts':False,'backend_source_unchanged':True,'provider_requests':False};return {**result,'receipt_sha256':self.record('recovered.json',result)}
    def activate(self):
        value=self.reviewed();self.boundary();need(not(self.root/'activation-started.json').exists(),'FRESH_STATIC_ACTIVATION_REQUIRED');old=self.m.NGINX.read_bytes();new=changed_nginx(old,self.old_public,self.public,self.proof['nginx_sha256']);need(H(new)==value['nginx_next_sha256'],'EXACT_REVIEWED_ROOT_REQUIRED');self.record('nginx-before.conf',old);self.record('activation-started.json',{'prepared_sha256':self.args.review_sha256,'old_sha256':H(old),'new_sha256':H(new)})
        try:
            self.m.replace_nginx(old,new);self.m.retained().reload_nginx();after=self.boundary(True);self.public_check();self.boundary(True)
            result={'stage':'MEDIA_META_MONTHLY_UI_STATIC_DEPLOYED','source_sha':SOURCE_SHA,'backend_source_sha':BASE_SOURCE,'frontend_version':FRONTEND,'prepared_sha256':self.args.review_sha256,'preflight_sha256':PREFLIGHT_SHA,'runtime':RUNTIME,'public_root':str(self.public),'public_inventory_sha256':value['public_inventory_sha256'],'boundary':after,'all162_rows_preserved':True,'static_only':True,'content_security_policy_unchanged':True,'old_hashed_assets_preserved':True,'database_writes':False,'schema_changes':False,'container_restarts':False,'permissions_changes':False,'environment_changes':False,'provider_or_publication_actions':False};return {**result,'receipt_sha256':self.record('deployed.json',result)}
        except BaseException:self.recover();raise

def validate_prepared(v,manifest,payload,preflight):
    pins_ready();need(v['stage']=='MEDIA_META_MONTHLY_UI_STATIC_PREPARED' and v['source_sha']==SOURCE_SHA and v['backend_source_sha']==BASE_SOURCE and v['frontend_version']==FRONTEND and v['manifest_sha256']==manifest and v['payload_sha256']==payload and v['preflight_sha256']==preflight==PREFLIGHT_SHA,'EXACT_STATIC_PREPARED_SCOPE_REQUIRED')
    need(v['public_root']=='/var/www/t24-crm-public/'+SCOPE+'-'+SOURCE_SHA[:12]+'-20261102' and all(re.fullmatch('[a-f0-9]{64}',v[k]) for k in ('public_inventory_sha256','nginx_next_sha256')) and v['boundary']['runtime']==RUNTIME and v['boundary']['original162_rows_preserved'] is True,'EXACT_STATIC_PREPARED_BOUNDARY_REQUIRED')
    need(v['static_only'] is True and all(v[k] is False for k in ('database_writes','container_restarts','schema_changes','permissions_changes','provider_or_publication_actions')),'STATIC_ONLY_PREPARE_REQUIRED')
    need(all(v['boundary'][key] is True for key in ('original162_rows_preserved','backend_source_unchanged','private_boundary_preserved','credentials_preserved','content_security_policy_unchanged')) and all(re.fullmatch('[a-f0-9]{64}',v['boundary'][key]) for key in ('rows_sha256','schema_sha256','environment_sha256','ops_environment_sha256')),'ALL_STATIC_PREPARED_PROTECTIONS_REQUIRED')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=('prepare','activate','recover'),required=True);parser.add_argument('--release',type=Path,required=True);parser.add_argument('--manifest-sha256',required=True);parser.add_argument('--payload-sha256',required=True);parser.add_argument('--preflight',type=Path,required=True);parser.add_argument('--preflight-sha256',required=True);parser.add_argument('--review-sha256');args=parser.parse_args()
    need(os.geteuid()==0 and socket.gethostname()==HOST,'EXACT_ROOT_SERVER_REQUIRED');resource.setrlimit(resource.RLIMIT_CORE,(0,0));os.umask(0o077);need(args.preflight_sha256==PREFLIGHT_SHA,'EXACT_PREFLIGHT_ARGUMENT_REQUIRED')
    lock=Path('/opt/t24-crm/releases/.media-workspace-scale.lock')
    for parent in lock.parents:
        row=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_RELEASE_LOCK_PARENT_REQUIRED')
    fd=os.open(lock,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        row=os.fstat(fd);need(stat.S_ISREG(row.st_mode) and row.st_uid==0 and row.st_nlink==1 and stat.S_IMODE(row.st_mode)==0o600,'ROOT_PRIVATE_SHARED_RELEASE_LOCK_REQUIRED');fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        release=Release(args);need(args.phase=='prepare' or args.review_sha256,'CANONICAL_PREPARED_REVIEW_REQUIRED');print(json.dumps(getattr(release,args.phase)(),sort_keys=True))
    finally:os.close(fd)
if __name__=='__main__':main()
