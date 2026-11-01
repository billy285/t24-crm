"""Fresh read-only current158 baseline before additive Google onboarding.

Only a new root-private aggregate receipt is written. Existing provider scopes,
rows, workers, credentials, runtime and Nginx are never changed by capture.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import socket
import sqlite3
import stat
from types import ModuleType, SimpleNamespace

HOST='iZj6c4cj7edgnhdimts4l7Z'
SOURCE='f595f3acfb5bfc4a28dadd3ec181b65f7c540fdd'
FRONTEND='c1d87dd771d8'
REVISION='f21dc345d681'
ROOT=Path('/opt/t24-crm/releases')
OLD=ROOT/'media-asset-studio-f595f3acfb5b-20261101'
RELEASE_SHA='334d6bb4b5a45538d019a03df19b0cd6b2d49671969b1dd7ea288c06f0976108'
DEPLOYED_SHA='c3dd937984cdf48429e124448b790cd8cb1a5ca47f4bb988c7e38e0d906ecac2'
PREPARED_SHA='aaded73460dff6689af78c5b7f90f6d4f39024c340bcde1e0bdfa2713308a274'
MANIFEST_SHA='2c526c73ec63ba59603fe304956c617f936ed53390c461890e959d98d413a504'
PAYLOAD_SHA='006c469c89b50217a253139c05f21a289386b521915c29bad3117238ca1afc15'
OLD_PREFLIGHT_SHA='bed4a64393ad4940a3e3c2a583d57a02f7970ce03ba6d96bec1991f7ba3d7bd2'
SCHEMA_SHA='61d80be409b79b85d1a1e85ccb879daa00943dd6c24cb25d7ba96e555efda780'
CSP_SHA='ead64b09efe8c4f35648aa8eafe8855c5268ecf0999e0918b3642dd9dfbfe7a6'
RUNTIME={'id':'8671f4b6bf4d43ee2db2d86ec9f9632edab01725c822cadac9c860b8a647e2b4','config':'8f1a8d57d968282bcbb1659613c386d123d97235407ab72ebbd9c4484ce33107','image':'sha256:3b203190c499b7e3f886f15156358403f7d10bd548df8a2ccc627f518f730b3a','restart':0,'started':'2026-11-01T06:17:46.343971823Z'}
NEW_TABLES=frozenset({'google_business_onboarding_catalogs','google_business_onboarding_batches','google_business_onboarding_items','google_business_onboarding_requests'})
H=lambda body:hashlib.sha256(body).hexdigest()
_CACHE=None


def need(value,code):
    if not value:raise RuntimeError(code)


def digest(value):return H(json.dumps(value,sort_keys=True,separators=(',',':')).encode())


def protected(path,sha):
    for parent in path.parents:
        row=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_SOURCE_PARENT_REQUIRED')
    before=path.lstat();need(path.resolve()==path and stat.S_ISREG(before.st_mode) and before.st_uid==0 and before.st_nlink==1 and stat.S_IMODE(before.st_mode)==0o600,'ROOT_PRIVATE_SOURCE_REQUIRED')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as stream:opened=os.fstat(stream.fileno());body=stream.read(131073);after=os.fstat(stream.fileno())
    fields=lambda row:(row.st_dev,row.st_ino,row.st_size,row.st_mtime_ns,row.st_ctime_ns,row.st_uid,row.st_mode,row.st_nlink)
    need(fields(before)==fields(opened)==fields(after)==fields(path.lstat()) and len(body)<=131072 and H(body)==sha,'EXACT_PROTECTED_SOURCE_BYTES_REQUIRED');return body


def dependencies():
    global _CACHE
    need(os.geteuid()==0 and socket.gethostname()==HOST,'EXACT_ROOT_SERVER_REQUIRED')
    resource.setrlimit(resource.RLIMIT_CORE,(0,0));os.umask(0o077)
    body=protected(OLD/'release.py',RELEASE_SHA)
    if _CACHE is None:
        module=ModuleType('_onboarding_current_asset_release');module.__file__=str(OLD/'release.py');exec(compile(body,module.__file__,'exec'),module.__dict__)
        need(module.SOURCE_SHA==SOURCE and module.FRONTEND==FRONTEND and module.NEW_REVISION==REVISION,'EXACT_CURRENT_DEPLOYED_SOURCE_REQUIRED')
        args=SimpleNamespace(release=OLD,manifest_sha256=MANIFEST_SHA,payload_sha256=PAYLOAD_SHA,preflight=ROOT/('media-asset-studio-preflight-'+OLD_PREFLIGHT_SHA[:12]+'.json'),preflight_sha256=OLD_PREFLIGHT_SHA,review_sha256=PREPARED_SHA)
        flow=module.Release(args);c=flow.c
        deployed=c.strict_json(c.read(OLD/'deployed.json',sha=DEPLOYED_SHA));prepared=c.strict_json(c.read(OLD/'prepared.json',sha=PREPARED_SHA))
        module.validate_prepared(prepared,MANIFEST_SHA,PAYLOAD_SHA,OLD_PREFLIGHT_SHA)
        need(deployed['stage']=='MEDIA_ASSET_STUDIO_DEPLOYED' and deployed['source_sha']==SOURCE and deployed['frontend_version']==FRONTEND and deployed['crm']==RUNTIME and deployed['schema_revision']==REVISION and deployed['table_count']==158 and deployed['schema_sha256']==SCHEMA_SHA,'EXACT_EXISTING_ASSET_DEPLOYMENT_RECEIPT_REQUIRED')
        need(all(deployed[key] is True for key in ('all155_original_tables_preserved_except_reviewed_schema_head','existing_full_environment_preserved','existing_ops_credentials_preserved','private_boundary_preserved','old_meta_google_cutoff_preserved','asset_worker_default_enabled_without_env_change')) and all(deployed[key] is False for key in ('operations_execution_enabled','operations_scheduler_enabled','database_restored','provider_requests','credentials_journaled')),'EXACT_EXISTING_AUTHORITY_REQUIRED')
        inventory=c.strict_json(c.read(OLD/'backend-candidate-inventory.json',sha=prepared['candidate_inventory_sha256']))
        _CACHE=(module,flow,inventory)
    return _CACHE


def business_markers(path):
    con=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True,timeout=3)
    try:
        con.execute('PRAGMA query_only=ON');con.execute('BEGIN')
        def grouped(table,allowed):
            rows=con.execute('SELECT status,count(*) FROM '+table+' GROUP BY status').fetchall()
            need(all(status in allowed and type(count)is int and count>=0 for status,count in rows),'KNOWN_BUSINESS_STATUS_AGGREGATES_REQUIRED');return dict(rows)
        bindings=con.execute('SELECT count(*),sum(CASE WHEN active=1 THEN 1 ELSE 0 END) FROM google_business_bindings').fetchone()
        need(bindings==(15,15),'EXACT_CURRENT15_ACTIVE_BINDINGS_REQUIRED')
        return {'google_binding_count':bindings[0],'google_active_binding_count':bindings[1],
            'monthly_workflow_status_counts':grouped('media_monthly_workflows',{'prepared','reviewed','scheduled','cancelled','stopped'}),
            'asset_job_status_counts':grouped('media_asset_jobs',{'queued','processing','succeeded','failed','unknown','adopted'})}
    finally:con.close()


def sample():
    module,flow,inventory=dependencies();m=flow.m
    current=m.inspect('t24-crm');need(current['State']['Running'] is True and m.runtime(current)==RUNTIME,'EXACT_CURRENT_CONFIGURED_RUNTIME_REQUIRED')
    envsha,opssha=flow.environment(current)
    flow.ctx.workflow.pf.google_environment(current);m.verify_secret_mount(current);m.verify_production_worker_enabled(current);m.retained().require_safe_original_restart(current)
    flow.source_boundary(current,inventory)
    # Legitimate post-deployment owner activity is captured fresh, never replayed
    # from the earlier empty-table acceptance or pre-binding business snapshot.
    flow.protections(updated=True,recovery=True,head=REVISION,schema=SCHEMA_SHA)
    rows=flow.retained.evidence(flow.rows());need(len(rows)==158 and not NEW_TABLES.intersection(rows),'EXACT_CURRENT158_WITHOUT_ONBOARDING_TABLES_REQUIRED')
    need(len(inventory)==414,'EXACT_CURRENT414_BACKEND_INVENTORY_REQUIRED')
    markers=business_markers(m.BUSINESS);need(rows['google_business_bindings']['count']==markers['google_binding_count'],'CONSISTENT_CURRENT_BINDINGS_REQUIRED')
    envkeys={entry.split('=',1)[0] for entry in current['Config']['Env'] if '=' in entry}
    need('CONTENT_SECURITY_POLICY' not in envkeys and 'T24_GBP_ONBOARDING_WORKER_ENABLED' not in envkeys,'UNCHANGED_DEFAULT_CSP_AND_NEW_WORKER_ENV_REQUIRED')
    credentials={'ops':flow.safe.protected_metadata(flow.c.ENV_FILE),'google':flow.safe.protected_metadata(flow.safe.GBP_ENV),'meta_read':flow.safe.protected_metadata(flow.ctx.workflow.core.ENV_FILE),'meta_legacy':flow.safe.protected_metadata(flow.ctx.workflow.core.LEGACY_ENV_FILE)}
    policy=flow.pf.public_security_policy(m,CSP_SHA)
    return {'stage':'GOOGLE_ONBOARDING_READONLY_PREFLIGHT','host':HOST,'source_sha':SOURCE,'frontend_version':FRONTEND,'schema_revision':REVISION,'deployed_receipt_sha256':DEPLOYED_SHA,
        'crm':m.runtime(current),'environment_sha256':envsha,'ops_environment_sha256':opssha,'schema_sha256':m.schema_signature(m.BUSINESS,REVISION),'rows':rows,
        'database_identity':flow.proof['database_identity'],'database_metadata':flow.metadata(m.BUSINESS),'business_markers':markers,
        'backend_inventory':inventory,'backend_inventory_sha256':digest(inventory),'backend_file_count':len(inventory),'credential_boundary':m.credential_boundary(),'credential_metadata':credentials,
        'private_boundary':flow.proof['private_boundary'],'public_root':str(flow.public),'public_inventory_sha256':m.verify_public(flow.public,flow.manifest),
        'nginx_sha256':H(m.NGINX.read_bytes()),'active_nginx_sha256':H(m.run(['nginx','-T'],'ACTIVE_NGINX_REQUIRED')),'content_security_policy_sha256':CSP_SHA,'public_content_security_policy':policy,
        'csp_environment_override_present':False,'new_onboarding_worker_env_present':False,'all158_current_tables_preserved':True,'ops_execution_enabled':False,'ops_scheduler_enabled':False,
        'google_scheduler_enabled':True,'google_scheduler_activation_from':'2026-10-30T19:42:04Z','existing_asset_worker_enabled':True,
        'schema_changed':False,'permissions_changed':False,'credential_file_content_read':False,'private_content_read':False,'business_writes':False,'provider_requests':False,'runtime_changed':False}


ENGINE_METADATA=r'''import hashlib,json,os,socket,stat,subprocess,sys
from pathlib import Path
import PIL
from PIL import ImageFont,features
def blocked(*a,**k):raise RuntimeError('NO_ENGINE_METADATA_NETWORK')
socket.socket.connect=blocked;socket.create_connection=blocked;socket.getaddrinfo=blocked
H=lambda b:hashlib.sha256(b).hexdigest()
def filehash(path,maximum):
 p=Path(path);before=p.lstat()
 if p.resolve()!=p or not stat.S_ISREG(before.st_mode) or before.st_uid!=0 or before.st_mode&0o022 or not 0<before.st_size<=maximum:raise RuntimeError('EXACT_SYSTEM_ENGINE_FILE_REQUIRED')
 fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW);h=hashlib.sha256()
 with os.fdopen(fd,'rb') as f:
  opened=os.fstat(f.fileno())
  for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
  after=os.fstat(f.fileno())
 fields=lambda x:(x.st_dev,x.st_ino,x.st_uid,x.st_mode,x.st_nlink,x.st_size,x.st_mtime_ns,x.st_ctime_ns)
 if fields(before)!=fields(opened) or fields(before)!=fields(after) or fields(before)!=fields(p.lstat()):raise RuntimeError('ENGINE_FILE_CHANGED_DURING_READ')
 return {'sha256':h.hexdigest(),'bytes':before.st_size}
noto='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc';latin='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf';ffmpeg='/usr/bin/ffmpeg';ffprobe='/usr/bin/ffprobe'
font=ImageFont.truetype(noto,32,index=2,layout_engine=ImageFont.Layout.BASIC)
missing=H(bytes(font.getmask('\U0010ffff')))
if any(H(bytes(font.getmask(c)))==missing for c in ('北','面','A')):raise RuntimeError('ACTUAL_CJK_AND_LATIN_GLYPHS_REQUIRED')
env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','OMP_NUM_THREADS':'1'}
version=subprocess.check_output([ffmpeg,'-version'],env=env,stdin=subprocess.DEVNULL,timeout=5).decode().splitlines()[0]
if len(version)>300:raise RuntimeError('BOUNDED_ENGINE_VERSION_REQUIRED')
print(json.dumps({'python':'.'.join(map(str,sys.version_info[:3])),'pillow':PIL.__version__,'freetype2':features.check('freetype2'),'font_name':font.getname(),'noto':filehash(noto,134217728),'latin':filehash(latin,16777216),'ffmpeg':filehash(ffmpeg,16777216),'ffprobe':filehash(ffprobe,16777216),'ffmpeg_version':version,'actual_cjk_latin_glyphs':True,'business_data_or_credentials_read':False,'provider_requests':False,'worker_started':False,'files_written':False},sort_keys=True))
'''


def engine_metadata():
    _,flow,_=dependencies();m=flow.m
    raw=m.run(['docker','exec',RUNTIME['id'],'python','-I','-B','-c',ENGINE_METADATA],'EXISTING_LOCAL_ENGINE_METADATA_FAILED',30)
    need(isinstance(raw,bytes) and len(raw)<16384,'BOUNDED_ENGINE_METADATA_REQUIRED');result=json.loads(raw)
    need(result['python'].startswith('3.10.') and result['pillow']=='12.3.0' and result['freetype2'] is True and result['font_name']==['Noto Sans CJK SC','Regular'] and result['actual_cjk_latin_glyphs'] is True,'EXISTING_LOCAL_RENDER_ENGINE_REQUIRED')
    need(result['noto']['sha256']=='b76b0433203017ca80401b2ee0dd69350349871c4b19d504c34dbdd80541690a' and result['latin']['sha256']=='57f73e11f51999432bf7ab22ce55b6f945d5eca1bf824404cfa9ec2e3718c84e','EXACT_EXISTING_FONTS_REQUIRED')
    need(all(result[k] is False for k in ('business_data_or_credentials_read','provider_requests','worker_started','files_written')),'READONLY_ENGINE_METADATA_REQUIRED')
    need(m.runtime(m.inspect('t24-crm'))==RUNTIME,'RUNTIME_CHANGED_DURING_ENGINE_METADATA');return result


def capture():
    first=sample();engine=engine_metadata();current=sample();_,flow,_=dependencies();c=flow.c
    flow.retained.live_sequence_boundary(first['database_metadata'],current['database_metadata'])
    need({**current,'database_metadata':first['database_metadata']}==first,'CURRENT158_BOUNDARIES_CHANGED_DURING_CAPTURE')
    proof={**current,'local_engine_metadata':engine};body=(json.dumps(proof,sort_keys=True,indent=2)+'\n').encode();sha=H(body)
    path=ROOT/('google-business-onboarding-preflight-'+sha[:12]+'.json')
    if path.exists():c.read(path,sha=sha)
    else:c.write(path,body)
    keys=('host','source_sha','frontend_version','schema_revision','deployed_receipt_sha256','crm','environment_sha256','ops_environment_sha256','schema_sha256','backend_inventory_sha256','backend_file_count','public_root','public_inventory_sha256','nginx_sha256','active_nginx_sha256','content_security_policy_sha256','csp_environment_override_present','new_onboarding_worker_env_present','all158_current_tables_preserved','ops_execution_enabled','ops_scheduler_enabled','google_scheduler_enabled','google_scheduler_activation_from','existing_asset_worker_enabled','business_markers')
    return {'stage':'GOOGLE_ONBOARDING_PREFLIGHT_CAPTURED','sha256':sha,'path':str(path),'bytes':len(body),'table_count':158,'rows_sha256':digest(current['rows']),**{k:current[k] for k in keys},
        'observed_asset_profile_count':current['rows']['media_asset_profiles']['count'],'observed_asset_job_count':current['rows']['media_asset_jobs']['count'],'observed_asset_request_count':current['rows']['media_asset_requests']['count'],'observed_private_monthly_packet_count':current['rows']['media_monthly_workflows']['count'],
        'local_engine_metadata':engine,'installation_performed':False,'worker_started':False,'schema_changed':False,'permissions_changed':False,'credential_file_content_read':False,'private_content_read':False,'business_writes':False,'provider_requests':False,'runtime_changed':False}
