#!/usr/bin/env python3
"""Deploy only private API/worker and static frontend; never restart or write CRM."""
import argparse, hashlib, importlib.util, itertools, json, os, re, secrets, shutil, socket, sqlite3, subprocess, time
from pathlib import Path
import urllib.request, urllib.error

BASE_IMAGE='sha256:7a1b09bbb04899e7c6459491d32c45c25d789801a51b4a95e9b77b7dafcbb4ab'
BASE_CONTAINER='ca45180be18981a7c3727a9c7a031690946f2c4c77f0cd96608fc65da3a3fb26'
BASE_STARTED='2026-10-10T17:19:07.948520307Z'
NGINX=Path('/etc/nginx/sites-enabled/t24-crm')
NGINX_SHA='8760b8bf06693797b7835a25fc1e0ece7b85a655584c01a898879dae57a17456'
BUSINESS=Path('/opt/t24-crm/app/data/crm_prod.db')
PRIVATE=Path('/opt/t24-crm/private-workspace')
PREFIX='/api/v1/private-workspace'
PREPARE_SHA='8de2ecaec7aad3b56fa966a3d3509ebe522c46345f227c79584ebcaabfb73641'
SECURITY_HEADERS={
  "X-Frame-Options": "SAMEORIGIN",
  "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' data:; connect-src 'self' https: wss:; frame-ancestors 'self'; base-uri 'self'; form-action 'self'",
  "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
  "Referrer-Policy": "strict-origin-when-cross-origin",
  "Permissions-Policy": "camera=(), geolocation=(), microphone=(self)",
  "X-Content-Type-Options": "nosniff"
}
OLD_BLOCK='''    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 300;
        proxy_send_timeout 300;
    }'''

def need(value, code):
    if not value: raise RuntimeError(code)

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def digest(o):return hashlib.sha256(json.dumps(o,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def write(p,b):
    need(not p.exists() and not p.is_symlink(),'NEW_FILE_REQUIRED')
    with p.open('xb') as f:f.write(b);f.flush();os.fsync(f.fileno())
    p.chmod(0o600)
def save(p,o):write(p,(json.dumps(o,sort_keys=True,indent=2)+'\n').encode())
def secure(p,directory=False):
    need(p.exists() and not p.is_symlink() and p.resolve()==p and p.stat().st_uid==0 and not p.stat().st_mode & 0o077,'PROTECTED_PATH_REQUIRED')
    need(p.is_dir() if directory else p.is_file(),'PATH_TYPE_REQUIRED')
def inspect(name):
    r=subprocess.run(['docker','inspect',name],capture_output=True,text=True,timeout=30)
    need(r.returncode==0,'CONTAINER_INSPECT_FAILED');return json.loads(r.stdout)[0]
def crm():
    c=inspect('t24-crm');need(c['Id']==BASE_CONTAINER and c['Image']==BASE_IMAGE and c['State']['StartedAt']==BASE_STARTED and c['State']['Running'] and c['State']['Health']['Status']=='healthy','CRM_RUNTIME_DRIFT')
    return c

def crm_matches_preparation(prep, before):
    # Docker serializes its mount map in varying list order. Preserve every
    # Config/HostConfig value and accept only the exact original mount tuples.
    observed=prep.crm_identity()
    current=crm()
    need(len(current['Mounts'])==2,'CRM_MOUNT_COUNT_DRIFT')
    need(all(observed[key]==before[key] for key in ('container_id','image_id','started_at')),'CRM_PREPARATION_IDENTITY_DRIFT')
    variants=[digest({'Config':current['Config'],'HostConfig':current['HostConfig'],'Mounts':list(order)})
              for order in itertools.permutations(current['Mounts'])]
    return before['configuration_sha256'] in variants

def request(url):
    try:
        with urllib.request.urlopen(url,timeout=15) as r:return r.status,dict(r.headers),r.read()
    except urllib.error.HTTPError as e:return e.code,dict(e.headers),e.read()

def wait_ready():
    for _ in range(45):
        try:
            code,headers,body=request('http://127.0.0.1:8001/ready')
            if code==200 and json.loads(body)=={'ready':True}:return
        except Exception:pass
        time.sleep(1)
    raise RuntimeError('PRIVATE_SERVICE_NOT_READY')

def snapshot(path,output):
    # SQLite's backup API takes a consistent live snapshot without a business write.
    need(path.is_file() and not path.is_symlink(),'BUSINESS_FILE_REQUIRED')
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as source:
        source.execute('PRAGMA query_only=ON')
        need(not output.exists() and not output.is_symlink(),'NEW_BACKUP_REQUIRED')
        fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);os.close(fd)
        with sqlite3.connect(output) as target:source.backup(target)
    output.chmod(0o600)
    with sqlite3.connect(output.as_uri()+'?mode=ro',uri=True) as db:
        db.execute('PRAGMA query_only=ON');need(db.execute('PRAGMA integrity_check').fetchone()[0]=='ok','SNAPSHOT_INTEGRITY_FAILURE')
        tables=sorted(x[0] for x in db.execute("SELECT name FROM sqlite_master WHERE type='table'"))
        need(len(tables)==83 and db.execute('SELECT version_num FROM alembic_version').fetchall()==[('ab6d8e2f0411',)],'BUSINESS_SCHEMA_DRIFT')
        need(db.execute('SELECT name,role,status FROM employees WHERE id=4').fetchone()==('李炳斌','super_admin','active'),'OWNER_IDENTITY_DRIFT')
        result={}
        for name in tables:
            quoted='"'+name.replace('"','""')+'"'
            rows=db.execute('SELECT * FROM '+quoted).fetchall()
            encoded=sorted(json.dumps(row,ensure_ascii=False,default=lambda x:{'bytes':bytes(x).hex()},separators=(',',':')) for row in rows)
            result[name]={'rows':len(rows),'sha256':digest(encoded)}
        need(not any(x.startswith('private_') for x in tables),'PRIVATE_SCHEMA_INSIDE_BUSINESS')
    return result

def proxy(path,port,private=False):
    extra='''        access_log off;
        error_log /var/log/nginx/t24-private-error.log crit;
        proxy_next_upstream off;
        client_max_body_size 1m;
''' if private else ''
    return '''    location '''+path+''' {
'''+extra+'''        proxy_pass http://127.0.0.1:'''+str(port)+''';
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 300;
        proxy_send_timeout 300;
    }
'''

def static_block(public):
    root='    root '+str(public)+';\n    index index.html;\n'
    blocks=proxy('= '+PREFIX,8001,True)+proxy('^~ '+PREFIX+'/',8001,True)+proxy('^~ /api/',8000)+proxy('= /health',8000)+proxy('= /ready',8000)
    static=r'''    location ^~ /assets/ {
        try_files $uri =404;
        add_header Cache-Control "public, max-age=31536000, immutable";
    }
    location = /sw.js {
        try_files $uri =404;
        add_header Cache-Control "no-store, no-cache, must-revalidate" always;
        add_header Service-Worker-Allowed "/" always;
    }
    location ~ ^/(?:app-version\.json|manifest\.webmanifest|offline\.html)$ {
        try_files $uri =404;
        add_header Cache-Control "no-store, no-cache, must-revalidate" always;
    }
    location ~ ^/(?:pwa-|apple-touch-icon|favicon) {
        try_files $uri =404;
        add_header Cache-Control "no-cache, max-age=0, must-revalidate" always;
    }
    location ~ /\. {
        return 404;
    }
    location / {
        try_files $uri $uri/ /index.html;
        add_header Cache-Control "no-store, no-cache, must-revalidate" always;
    }
'''
    safety=''.join('        add_header '+name+' '+json.dumps(value)+' always;\n' for name,value in SECURITY_HEADERS.items())
    static=static.replace('    }\n',safety+'    }\n')
    return root+blocks+static.rstrip()

def main(a):
    need(os.geteuid()==0 and socket.gethostname()=='iZj6c4cj7edgnhdimts4l7Z','SERVER_IDENTITY_DRIFT');os.umask(0o077)
    need(re.fullmatch('[a-f0-9]{40}',a.source_sha) and re.fullmatch('[a-f0-9]{64}',a.candidate_sha256),'ARGUMENT_HASH_SHAPE')
    release=Path('/opt/t24-crm/releases/private-workspace-'+a.source_sha[:7]+'-20261011-retry2');secure(release,True)
    p=release/'prepare_private_v3.py';secure(p)
    need(sha(p)==PREPARE_SHA,'PREPARATION_HELPER_DRIFT')
    sp=importlib.util.spec_from_file_location('prepare_private',p);prep=importlib.util.module_from_spec(sp);sp.loader.exec_module(prep)
    candidate_path=release/'candidate.json';secure(candidate_path);need(sha(candidate_path)==a.candidate_sha256,'CANDIDATE_RECEIPT_DRIFT')
    c=json.loads(candidate_path.read_text());need(c['stage']=='PRIVATE_WORKSPACE_CANDIDATE_VERIFIED' and c['source_sha']==a.source_sha and c['candidate_runtime_tests_verified'] and c['candidate_runtime_regression_tests']>=87 and c['all_baseline_backend_bytes_identical'] and c['runtime_package_bytes_identical'] and c['crm_container_id']==BASE_CONTAINER,'VERIFIED_CANDIDATE_REQUIRED')
    public=Path(c['public_directory']);need(public==Path('/opt/t24-crm/public-releases')/release.name,'PUBLIC_ROOT_DRIFT')
    need(sha(release/'candidate-public-files.json')==c['public_manifest_sha256'] and sha(release/'candidate-current-assets.json')==c['current_assets_proof_sha256'],'ASSET_PROOF_DRIFT')
    public_map=json.loads((release/'candidate-public-files.json').read_text());need({'/'+x:y for x,y in prep.file_manifest(public).items()}==public_map,'PUBLIC_BYTES_DRIFT')
    need(prep.current_graph(public,c['version'])==json.loads((release/'candidate-current-assets.json').read_text()),'CURRENT_GRAPH_DRIFT')
    original_crm=crm();need(crm_matches_preparation(prep,json.loads((release/'crm-before-safe.json').read_text())),'CRM_CONFIGURATION_DRIFT')
    need(NGINX.is_file() and NGINX.resolve()==NGINX and not NGINX.is_symlink() and sha(NGINX)==NGINX_SHA,'NGINX_BASELINE_DRIFT')
    original=NGINX.read_bytes();need(original.decode().count(OLD_BLOCK)==1,'EXACT_NGINX_BLOCK_REQUIRED')
    need(not PRIVATE.exists() and not PRIVATE.is_symlink(),'PRIVATE_LOCATION_ALREADY_EXISTS')
    need(not any(x['Names']=='t24-private-api' or x['Names']=='t24-private-worker' for x in map(json.loads,subprocess.check_output(['docker','ps','-a','--format','{{json .}}'],text=True).splitlines())),'PRIVATE_CONTAINER_COLLISION')
    try:
        s=socket.socket();s.bind(('127.0.0.1',8001));s.close()
    except OSError:raise RuntimeError('PRIVATE_PORT_IN_USE') from None
    old_backup=release/'nginx-original.conf';write(old_backup,original)
    before=snapshot(BUSINESS,release/'business-before.db');save(release/'business-before-safe.json',before)
    # Restore only into a protected scratch file to verify backup usability, never into production.
    restored=release/'business-backup-restore-verification.db'
    need(not restored.exists() and not restored.is_symlink(),'NEW_RESTORE_SCRATCH_REQUIRED')
    fd=os.open(restored,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);os.close(fd)
    with sqlite3.connect((release/'business-before.db').as_uri()+'?mode=ro',uri=True) as b:
        with sqlite3.connect(restored) as dst:b.backup(dst)
    restored.chmod(0o600)
    with sqlite3.connect(restored.as_uri()+'?mode=ro',uri=True) as b:need(b.execute('PRAGMA integrity_check').fetchone()[0]=='ok','BACKUP_RESTORE_VALIDATION_FAILED')
    env=dict(x.split('=',1) for x in original_crm['Config']['Env'])
    jwt=env.get('JWT_SECRET_KEY','');need(len(jwt)>=32 and '\n' not in jwt and '\r' not in jwt,'JWT_CONFIG_INVALID')
    need(not any('\x00' in x for x in env.values()),'ENV_INVALID')
    PRIVATE.mkdir(mode=0o700)
    for n in ('data','config','logs'):(PRIVATE/n).mkdir(mode=0o700)
    # Key is generated once on host, never returned in receipts or inserted into client files.
    private_env={'JWT_SECRET_KEY':jwt,'JWT_ALGORITHM':'HS256','APP_ENV':'production','ENVIRONMENT':'production',
      'DATABASE_URL':'sqlite:///./data/crm_prod.db','DATABASE_SCHEMA_MODE':'verify_only',
      'ENFORCE_EMPLOYEE_STATUS':'true','ENFORCE_EMPLOYEE_SESSIONS':'true','ENABLE_DEFAULT_EMPLOYEE_ADMIN':'false',
      'ENABLE_LEGACY_AUTH':'false','AUTOMATION_SCAN_ENABLED':'false','PRIVATE_WORKSPACE_OWNER_IDS':'4',
      'PRIVATE_WORKSPACE_DATABASE_URL':'sqlite+aiosqlite:////private-data/workspace.db',
      'PRIVATE_WORKSPACE_ENCRYPTION_KEY':secrets.token_urlsafe(48),'PRIVATE_WORKSPACE_PUBLIC_URL':'https://t24-crm.com',
      'PYTHONDONTWRITEBYTECODE':'1','PYTHONUNBUFFERED':'1','DEBUG':'false','TZ':'Asia/Shanghai'}
    # JSON docker compose environment interpolation of credentials is disabled through env_file format raw.
    # Use Docker --env-file directly so dollar/quote characters preserve exact existing JWT bytes.
    config=PRIVATE/'config/runtime.env';write(config,('\n'.join(k+'='+v for k,v in sorted(private_env.items()))+'\n').encode())
    def run(stage,cmd,timeout=120):
        r=subprocess.run(cmd,capture_output=True,text=True,timeout=timeout)
        # All commands are bounded, no secret values are command arguments or logs.
        write(release/(stage+'.log'),(r.stdout+'\n'+r.stderr).encode());need(r.returncode==0,stage.upper()+'_FAILED');return r.stdout.strip()
    def private_container(name,command,api=False):
        common=['docker','run','-d','--name',name,'--restart','unless-stopped','--read-only','--cap-drop','ALL',
          '--security-opt','no-new-privileges','--log-opt','max-size=5m','--log-opt','max-file=3',
          '--env-file',str(config),'--tmpfs','/tmp:rw,nosuid,noexec,size=128m',
          '--mount','type=bind,src=/opt/t24-crm/app/data,dst=/app/backend/data,readonly',
          '--mount','type=bind,src='+str(PRIVATE/'data')+',dst=/private-data',
          '--label','t24.private.source.sha='+a.source_sha,'--label','t24.private.role='+('api' if api else 'worker')]
        if api:common+=['--publish','127.0.0.1:8001:8001','--health-cmd','curl -fsS http://127.0.0.1:8001/ready || exit 1','--health-interval','15s','--health-timeout','5s','--health-start-period','15s','--health-retries','3']
        else:common+=['--no-healthcheck']
        return run(name+'-start',common+['--entrypoint',command[0],c['image_id'],*command[1:]])
    api_id=worker_id=None; switched=False
    try:
        api_id=private_container('t24-private-api',['uvicorn','services.private_workspace_app:app','--host','0.0.0.0','--port','8001','--no-access-log'],True)
        wait_ready()
        worker_id=private_container('t24-private-worker',['python','-m','services.private_workspace_worker'])
        time.sleep(2)
        for name,identity in [('t24-private-api',api_id),('t24-private-worker',worker_id)]:
            info=inspect(name);need(info['Id']==identity and info['Image']==c['image_id'] and info['State']['Running'],'PRIVATE_CONTAINER_START_FAILED')
            need(info['HostConfig']['ReadonlyRootfs'] and info['HostConfig']['CapDrop']==['ALL'],'PRIVATE_CONTAINER_PROTECTION_DRIFT')
            mounts={(m['Source'],m['Destination'],m['RW']) for m in info['Mounts']}
            need(mounts=={('/opt/t24-crm/app/data','/app/backend/data',False),(str(PRIVATE/'data'),'/private-data',True),('','/tmp',True)} or mounts=={('/opt/t24-crm/app/data','/app/backend/data',False),(str(PRIVATE/'data'),'/private-data',True)},'PRIVATE_MOUNT_DRIFT')
            configured=dict(x.split('=',1) for x in info['Config']['Env']);need(all(configured.get(k)==v for k,v in private_env.items()),'PRIVATE_ENV_DRIFT')
            need(not any(k.startswith(('STRIPE_','OPENAI_','RINGCENTRAL_','OSS_','PRIVATE_GOOGLE_')) for k in configured),'UNAUTHORIZED_PLATFORM_SECRET_PRESENT')
        private_db=PRIVATE/'data/workspace.db';secure(private_db)
        need(not os.path.samefile(private_db,BUSINESS),'PRIVATE_DATABASE_ALIASED_TO_BUSINESS')
        # Exercise a benign manual note directly in private storage, then archive it;
        # it never enters the visible queue or any business table, and survives restarts.
        marker='release-'+secrets.token_hex(12)
        persist_code="""import asyncio,json
from models.private_workspace import PrivateItem
from services.private_workspace import private_session_factory,close_private_workspace_storage
async def main():
  sessions=await private_session_factory()
  async with sessions() as db:
    item=PrivateItem(owner_id='4',source_id='manual',kind='note',external_id=MARKER,title='私人空间上线验证',summary='',status='manual',priority='low',evidence={},action_status='archived')
    db.add(item);await db.commit()
  await close_private_workspace_storage()
asyncio.run(main());print('PRIVATE_PERSISTENCE_PROBE_WRITTEN')
""".replace('MARKER',repr(marker))
        run('private-persistence-write',['docker','exec','t24-private-api','python','-c',persist_code])
        run('private-restart',['docker','restart','t24-private-api','t24-private-worker']);wait_ready()
        with sqlite3.connect(private_db.as_uri()+'?mode=ro',uri=True) as db:
            need(db.execute('SELECT owner_id,action_status FROM private_items WHERE external_id=?',(marker,)).fetchone()==('4','archived'),'PRIVATE_PERSISTENCE_LOST')
            private_tables=sorted(x[0] for x in db.execute("SELECT name FROM sqlite_master WHERE type='table'"))
            need(private_tables==['private_connections','private_items','private_preferences','private_sync_runs'],'PRIVATE_SCHEMA_DRIFT')
        for path in (PREFIX,PREFIX+'/access'):
            code,headers,body=request('http://127.0.0.1:8001'+path);need(code==401 and 'no-store' in headers.get('Cache-Control',''),'PRIVATE_AUTH_OR_CACHE_FAILURE')
        need(crm()['Id']==BASE_CONTAINER,'CRM_CHANGED_BEFORE_SWITCH')
        updated=original.decode().replace(OLD_BLOCK,static_block(public));newconf=release/'nginx-private.conf';write(newconf,updated.encode())
        need(sha(NGINX)==NGINX_SHA,'NGINX_CHANGED_DURING_PREPARATION')
        # Atomic replacement, same target/owner/mode. Save independent rollback command first.
        rollback={'source_sha':a.source_sha,'nginx_original_sha256':NGINX_SHA,'original_crm_container':BASE_CONTAINER,'private_data_retained':True,'business_db_restore_forbidden':True}
        save(release/'rollback-spec.json',rollback)
        temp=NGINX.parent/('.t24-private-'+a.source_sha[:7]);need(not temp.exists(),'NGINX_TEMP_EXISTS')
        write(temp,updated.encode());temp.chmod(0o644);os.replace(temp,NGINX);switched=True
        run('nginx-test',['nginx','-t']);run('nginx-reload',['systemctl','reload','nginx'])
        code,h,b=request('https://t24-crm.com/app-version.json');need(code==200 and json.loads(b)=={'version':c['version']} and 'no-store' in h.get('Cache-Control',''),'PUBLIC_VERSION_DRIFT')
        code,h,b=request('https://t24-crm.com/private-workspace');need(code==200 and hashlib.sha256(b).hexdigest()==sha(public/'index.html'),'PUBLIC_FRONTEND_DRIFT')
        need(all(h.get(k)==v for k,v in SECURITY_HEADERS.items()),'PUBLIC_SECURITY_HEADERS_DRIFT')
        graph=json.loads((release/'candidate-current-assets.json').read_text())
        for asset,assetsha in graph['assets'].items():
            code,h,b=request('https://t24-crm.com'+asset);need(code==200 and hashlib.sha256(b).hexdigest()==assetsha,'PUBLIC_CURRENT_ASSET_DRIFT')
        for path in (PREFIX,PREFIX+'/access'):
            code,h,b=request('https://t24-crm.com'+path);need(code==401 and 'no-store' in h.get('Cache-Control',''),'PUBLIC_PRIVATE_AUTH_FAILURE')
        code,h,b=request('https://t24-crm.com/ready');need(code==200,'EXISTING_CRM_NOT_READY')
        # Bound HTTP only and no public worker port; startup/readiness after restart confirmed.
        ai=inspect('t24-private-api');wi=inspect('t24-private-worker')
        need(ai['HostConfig']['PortBindings']=={'8001/tcp':[{'HostIp':'127.0.0.1','HostPort':'8001'}]} and not wi['HostConfig']['PortBindings'] and wi['State']['Running'],'PRIVATE_NETWORK_DRIFT')
        need(crm_matches_preparation(prep,json.loads((release/'crm-before-safe.json').read_text())),'EXISTING_CRM_CHANGED')
        after=snapshot(BUSINESS,release/'business-after.db');save(release/'business-after-safe.json',after)
        changed=sorted(name for name in before if before[name]!=after[name])
        # Live users may legitimately update CRM during release; no global write pause is introduced.
        result={'stage':'PRIVATE_WORKSPACE_DEPLOYED_SERVER_VERIFIED','source_sha':a.source_sha,'private_image_id':c['image_id'],
          'version':c['version'],'private_owner_ids':[4],'private_api_container_id':api_id,'private_worker_container_id':worker_id,
          'private_database':str(private_db),'private_database_independent':True,'private_persistence_after_restart':True,
          'crm_identity_unchanged':True,'crm_container_id':BASE_CONTAINER,'crm_image_id':BASE_IMAGE,'crm_started_at':BASE_STARTED,
          'crm_mount_read_only_in_private_services':True,'business_table_count':83,'business_schema_unchanged':True,
          'business_tables_changed_during_live_window':changed,'all_business_table_fingerprints_equal':not changed,
          'business_backup_restore_verified_in_scratch_only':True,'business_database_writes_performed_by_deployer':False,
          'nginx_new_sha256':sha(NGINX),'public_current_assets_verified':len(graph['assets']),
          'public_version_verified':True,'public_unauthenticated_access_rejected':True,'candidate_runtime_tests':c['candidate_runtime_regression_tests'],
          'real_platform_accounts_connected':False,'browser_owner_acceptance_pending':True}
        save(release/'deployment-receipt.json',result);print(json.dumps(result,sort_keys=True),flush=True)
    except BaseException:
        # Frontend/private proxy rollback is independent; CRM is never restarted/restored.
        if switched:
            t=NGINX.parent/('.t24-private-rollback-'+a.source_sha[:7]);need(not t.exists(),'ROLLBACK_TEMP_EXISTS');write(t,original);t.chmod(0o644);os.replace(t,NGINX)
            subprocess.run(['nginx','-t'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            subprocess.run(['systemctl','reload','nginx'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for name,identity in [('t24-private-worker',worker_id),('t24-private-api',api_id)]:
            if identity:
                info=inspect(name);need(info['Id']==identity and info['Image']==c['image_id'],'ROLLBACK_CONTAINER_IDENTITY_DRIFT');subprocess.run(['docker','stop',name],check=True,stdout=subprocess.DEVNULL)
        need(crm()['Id']==BASE_CONTAINER,'CRM_CHANGED_DURING_ROLLBACK')
        print('PRIVATE_DEPLOYMENT_FAILED_SAFE_ROLLBACK; CRM unchanged; private data retained',flush=True)
        raise

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');p.add_argument('--source-sha',required=True);p.add_argument('--candidate-sha256',required=True);a=p.parse_args()
    if a.execute:main(a)
    else:print('PLAN_ONLY; NO_PRODUCTION_ACTIONS')
