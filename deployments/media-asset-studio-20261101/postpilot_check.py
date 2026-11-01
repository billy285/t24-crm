"""Read-only aggregate audit of the two explicit owner asset pilot adoptions."""
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import socket
import sqlite3
import types
from uuid import UUID

ROOT=Path('/opt/t24-crm/releases/media-asset-studio-f595f3acfb5b-20261101')
SOURCE='f595f3acfb5bfc4a28dadd3ec181b65f7c540fdd'
HELPER='334d6bb4b5a45538d019a03df19b0cd6b2d49671969b1dd7ea288c06f0976108'
DEPLOYED='c3dd937984cdf48429e124448b790cd8cb1a5ca47f4bb988c7e38e0d906ecac2'
PREPARED='aaded73460dff6689af78c5b7f90f6d4f39024c340bcde1e0bdfa2713308a274'
MANIFEST='2c526c73ec63ba59603fe304956c617f936ed53390c461890e959d98d413a504'
PAYLOAD='006c469c89b50217a253139c05f21a289386b521915c29bad3117238ca1afc15'
PREFLIGHT='bed4a64393ad4940a3e3c2a583d57a02f7970ce03ba6d96bec1991f7ba3d7bd2'
RUNTIME={'id':'8671f4b6bf4d43ee2db2d86ec9f9632edab01725c822cadac9c860b8a647e2b4','config':'8f1a8d57d968282bcbb1659613c386d123d97235407ab72ebbd9c4484ce33107','image':'sha256:3b203190c499b7e3f886f15156358403f7d10bd548df8a2ccc627f518f730b3a','restart':0,'started':'2026-11-01T06:17:46.343971823Z'}
NEW={'media_asset_profiles','media_asset_jobs','media_asset_requests'}
APPEND={'customer_materials','media_publication_images','customer_record_audits'}
RAW=NEW|APPEND|{'media_monthly_workflows'}
H=lambda body:hashlib.sha256(body).hexdigest()
def need(ok,code):
    if not ok:raise RuntimeError(code)
def digest(value):return H(json.dumps(value,sort_keys=True,separators=(',',':')).encode())
def quote(value):return '"'+value.replace('"','""')+'"'
def rows_hash(rows):return H('\n'.join(sorted(json.dumps(list(row),ensure_ascii=True,default=lambda x:bytes(x).hex()) for row in rows)).encode())
def decoded(value):return json.loads(value) if isinstance(value,str) else value
def uuid(value):
    try:return str(UUID(value))==value
    except (ValueError,TypeError,AttributeError):return False
def sha(value):return isinstance(value,str) and re.fullmatch('[a-f0-9]{64}',value) is not None


def snapshot(con):
    tables=[x[0] for x in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    result={};raw={}
    for name in tables:
        schema={row[1]:(row[2],row[3],row[4],row[5]) for row in con.execute('PRAGMA table_info('+quote(name)+')')};columns=list(schema)
        indexes={row[1]:(row[2],row[3],row[4],tuple(item[2] for item in con.execute('PRAGMA index_info('+quote(row[1])+')'))) for row in con.execute('PRAGMA index_list('+quote(name)+')')}
        values=list(con.execute('SELECT '+','.join(quote(x) for x in columns)+' FROM '+quote(name)))
        result[name]={'columns':columns,'schema':schema,'indexes':indexes,'count':len(values),'rows_sha256':rows_hash(values)}
        if name in RAW:raw[name]=[dict(zip(columns,row)) for row in values]
    objects=con.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
    present=con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'").fetchone() is not None
    seq=dict(con.execute('SELECT name,seq FROM sqlite_sequence ORDER BY name').fetchall()) if present else {}
    pragma=[con.execute('PRAGMA '+n).fetchone()[0] for n in ('user_version','application_id')]
    return json.loads(json.dumps(result)),raw,{'pragma_sha256':digest(pragma),'sequence_exists':present,'sequence_values':seq,'sequence_sha256':digest(sorted(seq.items()))},digest(objects),objects


def filtered_hash(current,raw,excluded):
    columns=current['columns'];rows=[tuple(row[x] for x in columns) for row in raw if row['id'] not in excluded]
    return len(rows),rows_hash(rows)


def audit(before,current,raw,old_metadata,metadata,objects):
    need(len(before)==155 and len(current)==158 and set(current)==set(before)|NEW,'EXACT_155_PLUS3_TABLES_REQUIRED')
    need(before['media_monthly_workflows']['count']==1 and before['media_publication_images']['count']==2,'EXACT_ORIGINAL_PRIVATE_PACKET_AND2_PHOTOS_REQUIRED')
    monthly=raw['media_monthly_workflows'];need(len(monthly)==1 and monthly[0]['customer_id']==20 and monthly[0]['status']=='prepared','PRIVATE_PACKET_MUST_REMAIN_PREPARED')
    owner=monthly[0]['owner_id'];need(type(owner)is int and owner>0,'ORIGINAL_OWNER_REQUIRED')
    materials=[x for x in raw['customer_materials'] if x['id'] in {6,7}]
    need(len(materials)==2 and {x['id'] for x in materials}=={6,7},'EXACT_TWO_NEW_MATERIALS_REQUIRED')
    for x in materials:
        need(x['customer_id']==20 and x['user_id']==str(owner) and x['material_type']==('image' if x['id']==6 else 'video') and x['visibility']=='team' and x['source_type']=='upload' and x['approval_status']=='pending' and x['usage_status']=='unused','NEW_MATERIAL_SCOPE_STATE_OR_TYPE_MISMATCH')
    versions=[x for x in raw['media_publication_images'] if x['material_id'] in {6,7}]
    need(len(versions)==1 and versions[0]['material_id']==6 and versions[0]['customer_id']==20 and versions[0]['prepared_by_id']==owner and versions[0]['revoked_at'] is None,'ONLY_POSTER_MAY_HAVE_NEW_FIXED_IMAGE')
    image=versions[0];old_images={x['id']:x for x in raw['media_publication_images'] if x['id']!=image['id']}
    need(len(old_images)==2,'EXACT_TWO_ORIGINAL_FIXED_IMAGES_REQUIRED')
    audits=[x for x in raw['customer_record_audits'] if x['entity_type']=='customer_materials' and x['entity_id'] in {6,7}]
    need(len(audits)==2 and {x['entity_id'] for x in audits}=={6,7},'EXACT_TWO_NEW_MATERIAL_AUDITS_REQUIRED')
    profiles=raw['media_asset_profiles'];jobs=raw['media_asset_jobs'];requests=raw['media_asset_requests']
    need(len(profiles)==1 and profiles[0]['customer_id']==20 and profiles[0]['owner_id']==owner and profiles[0]['revision']==1,'EXACT_OWNER_PROFILE1_REQUIRED')
    settings=decoded(profiles[0]['settings']);need(set(settings)=={'preset','brand_name','primary_color','accent_color','footer'},'PROFILE_FIELDS_REQUIRED')
    need(len(jobs)==2 and {x['kind'] for x in jobs}=={'poster','video'},'EXACT_POSTER_AND_VIDEO_JOBS_REQUIRED')
    jobmap={};expected_profile={'revision':1,**settings}
    for job in jobs:
        need(job['owner_id']==owner and job['customer_id']==20 and job['status']=='adopted' and job['revision']==4 and job['attempt']==1 and job['lease_token'] is None and job['error_code'] is None and uuid(job['request_id']),'ADOPTED_JOB_OWNER_OR_STATE_MISMATCH')
        output=decoded(job['output']);adoption=decoded(job['adoption']);saved=decoded(job['snapshot']);mid=6 if job['kind']=='poster' else 7
        need(sha(output.get('sha256')) and output['mime_type']==('image/png' if mid==6 else 'video/mp4') and output['duration_seconds']==(None if mid==6 else 6),'EXACT_PNG_AND6_SECOND_MP4_REQUIRED')
        need(saved['profile']==expected_profile and saved['recipe']['kind']==job['kind'] and saved['recipe']['rights_confirmed'] is True,'EXACT_FROZEN_PROFILE_AND_RECIPE_REQUIRED')
        sourceids=[x['id'] for x in saved['proofs']]
        need(len(sourceids)==(1 if mid==6 else 2) and len(set(sourceids))==len(sourceids) and set(sourceids)<=set(old_images) and saved['recipe']['image_ids']==sourceids,'ONLY_ORIGINAL_FIXED_PHOTOS_MAY_BE_USED')
        for proof in saved['proofs']:
            original=old_images[proof['id']]
            need(proof['image_sha256']==original['image_sha256'] and proof['source_sha256']==original['source_sha256'] and proof['material_id']==original['material_id'],'ORIGINAL_SOURCE_PROOF_CHANGED')
        need(adoption['material_id']==mid and adoption['image_id']==(image['id'] if mid==6 else None) and adoption['preview_path']==('/api/v1/media-publication-images/'+image['id']+'/preview' if mid==6 else None),'NATIVE_ADOPTION_LINEAGE_MISMATCH')
        material=next(x for x in materials if x['id']==mid)
        need(material['file_size']==output['byte_size'] and material['content_type']==output['mime_type'],'MATERIAL_OUTPUT_METADATA_MISMATCH')
        if mid==6:need(image['source_sha256']==image['image_sha256']==output['sha256'] and image['byte_size']==output['byte_size'] and (image['width'],image['height'])==(output['width'],output['height']),'POSTER_NATIVE_FIXED_IMAGE_HASH_MISMATCH')
        record=next(x for x in audits if x['entity_id']==mid);after=decoded(record['after'])
        need(record['customer_id']==20 and record['actor_id']==str(owner) and record['module']=='materials' and record['action']=='create' and decoded(record['before'])=={} and after['source_job_id']==job['id'] and after['output_sha256']==output['sha256'] and after['source_image_ids']==sourceids and after['approval_status']=='pending','EXACT_SOURCE_JOB_CREATE_AUDIT_REQUIRED')
        jobmap[job['id']]=job
    need(len(jobmap)==2 and len(requests)==5 and all(x['owner_id']==owner and x['customer_id']==20 and uuid(x['request_id']) and sha(x['fingerprint']) for x in requests),'EXACT_FIVE_OWNER_REQUESTS_REQUIRED')
    need(len({x['request_id'] for x in requests})==5 and sorted(x['kind'] for x in requests)==['adopt','adopt','create','create','profile'],'EXACT_PROFILE_CREATE_ADOPT_RECEIPTS_REQUIRED')
    for kind in ('profile','create','adopt'):
        selected=[x for x in requests if x['kind']==kind];linked=[decoded(x['result']) for x in selected]
        need(all(set(x)=={'job_id'} for x in linked),'REQUEST_RESULT_FIELDS_REQUIRED')
        need([x['job_id'] for x in linked]==[None] if kind=='profile' else len(linked)==2 and {x['job_id'] for x in linked}==set(jobmap),'REQUEST_JOB_LINKAGE_MISMATCH')
        if kind=='create':need(all(jobmap[decoded(x['result'])['job_id']]['request_id']==x['request_id'] for x in selected),'ORIGINAL_CREATE_UUID_MISMATCH')
    excluded={'customer_materials':{6,7},'media_publication_images':{image['id']},'customer_record_audits':{x['id'] for x in audits}}
    for name,old in before.items():
        now=current[name];need(all(now[k]==old[k] for k in ('columns','schema','indexes')),'ORIGINAL_TABLE_SHAPE_CHANGED')
        if name=='alembic_version':need(now['count']==1 and now['rows_sha256']==rows_hash([('f21dc345d681',)]),'EXACT_REVIEWED_SCHEMA_HEAD_REQUIRED')
        elif name in APPEND:need(filtered_hash(now,raw[name],excluded[name])==(old['count'],old['rows_sha256']) and now['count']==old['count']+len(excluded[name]),'APPEND_ONLY_OLD_ROWS_CHANGED')
        else:need((now['count'],now['rows_sha256'])==(old['count'],old['rows_sha256']),'PROTECTED_ORIGINAL_ROWS_CHANGED')
    need(old_metadata['pragma_sha256']==metadata['pragma_sha256'] and old_metadata['sequence_exists'] is metadata['sequence_exists'],'ORIGINAL_SQLITE_METADATA_CHANGED')
    oldseq=old_metadata['sequence_values'];seq=metadata['sequence_values'];newkeys=set(seq)-set(oldseq)
    need(set(oldseq)<=set(seq) and newkeys<=APPEND,'UNEXPECTED_SEQUENCE_KEYS_CHANGED')
    for name,value in seq.items():
        if name in APPEND:
            maximum=max([x['id'] for x in raw[name] if type(x['id']) is int],default=0)
            need(type(value)is int and value==max(oldseq.get(name,0),maximum),'APPEND_COUNTER_MISMATCH')
        elif name=='monthly_deduction_rates':
            # Preserve the existing reviewed exception for INSERT OR IGNORE:
            # this one counter can move forward while every row remains exact.
            need(type(value)is int and value>=oldseq[name],'PROTECTED_SEQUENCE_COUNTER_CHANGED')
        else:need(value==oldseq[name],'PROTECTED_SEQUENCE_COUNTER_CHANGED')
    return {'original_tables':155,'current_tables':158,'protected_original_rows_unchanged':True,'append_only_material_ids':[6,7],
        'new_fixed_images':1,'new_create_audits':2,'asset_profiles':1,'adopted_asset_jobs':2,'asset_request_receipts':5,
        'poster_material_pending':True,'video_material_pending':True,'video_duration_seconds':6,'original_private_monthly_packet_preserved':True,
        'original_schema_preserved':True,'sequence_counters_verified_with_existing_monthly_rate_exception':True,
        'existing_monthly_rate_counter_forward_only':True}


def main():
    need(os.geteuid()==0 and socket.gethostname()=='iZj6c4cj7edgnhdimts4l7Z','EXACT_ROOT_SERVER_REQUIRED');resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    # Load only frozen helper code and protected aggregate receipts. Do not call
    # current()/pf.sample(), whose pre-pilot row equality is intentionally old.
    def read(path,sha=None):
        for p in (path,*path.parents):
            row=p.lstat();need(p.resolve()==p and row.st_uid==0 and not row.st_mode&0o022,'PROTECTED_AGGREGATE_PARENT_REQUIRED')
        row=path.lstat();need(path.is_file() and row.st_nlink==1 and row.st_mode&0o777==0o600 and row.st_size<16777216,'ROOT600_AGGREGATE_REQUIRED')
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
        with os.fdopen(fd,'rb') as stream:
            opened=os.fstat(stream.fileno());body=stream.read(16777217);after=os.fstat(stream.fileno())
        identity=lambda s:(s.st_dev,s.st_ino,s.st_uid,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
        need(identity(row)==identity(opened)==identity(after)==identity(path.lstat()) and len(body)==row.st_size and
            (sha is None or H(body)==sha),'EXACT_PROTECTED_AGGREGATE_REQUIRED');return body
    body=read(ROOT/'release.py',HELPER);r=types.ModuleType('_postpilot_exact_release');r.__file__=str(ROOT/'release.py');exec(compile(body,r.__file__,'exec'),r.__dict__)
    args=types.SimpleNamespace(release=ROOT,preflight=ROOT.parent/'media-asset-studio-preflight-bed4a64393ad.json',preflight_sha256=PREFLIGHT,manifest_sha256=MANIFEST,payload_sha256=PAYLOAD,review_sha256=PREPARED)
    ctx=r.Release(args);m=ctx.m
    deployed=json.loads(read(ROOT/'deployed.json',DEPLOYED));need(deployed['crm']==RUNTIME and deployed['source_sha']==SOURCE and deployed['prepared_sha256']==PREPARED,'EXACT_DEPLOYED_RUNTIME_PROOF_REQUIRED')
    prepared=json.loads(read(ROOT/'prepared.json',PREPARED));r.validate_prepared(prepared,MANIFEST,PAYLOAD,PREFLIGHT)
    identity=json.loads(read(ROOT/'production-baseline-identity.json'))
    need(identity=={'source_sha':SOURCE,'original_id':ctx.proof['crm']['id'],'candidate_id':RUNTIME['id'],'review_sha256':PREPARED,'rows_sha256':identity['rows_sha256']} and sha(identity['rows_sha256']),'ACTIVATION_BASELINE_IDENTITY_REQUIRED')
    before=json.loads(read(ROOT/'production-before-rows.json',identity['rows_sha256']))
    need(ctx.retained.evidence(before)==ctx.proof['rows'],'ORIGINAL155_BASELINE_HASH_CHAIN_REQUIRED')
    info=m.inspect('t24-crm');need(info['State']['Running'] is True and m.runtime(info)==RUNTIME,'CURRENT_RUNTIME_OR_ENVIRONMENT_CHANGED')
    expected=json.loads(read(ROOT/'backend-candidate-inventory.json',prepared['candidate_inventory_sha256']))
    need(m.inventory(RUNTIME['id'])==expected,'CURRENT_APPLICATION_SOURCE_CHANGED')
    need(ctx.safe.safe_private_boundary(m,ctx.pins)==ctx.proof['private_boundary'],'PRIVATE_SPACE_BOUNDARY_CHANGED');ctx.nginx(updated=True)
    con=sqlite3.connect('file:'+str(m.BUSINESS)+'?mode=ro',uri=True,timeout=3)
    try:
        con.execute('PRAGMA query_only=ON');con.execute('BEGIN');current,raw,metadata,schema,objects=snapshot(con)
        need(schema==deployed['schema_sha256'],'EXACT_DEPLOYED158_SCHEMA_REQUIRED')
        result=audit(before,current,raw,ctx.proof['database_metadata'],metadata,objects)
    finally:con.close()
    need(m.runtime(m.inspect('t24-crm'))==RUNTIME,'RUNTIME_CHANGED_DURING_READ_ONLY_CHECK')
    print(json.dumps({'stage':'ASSET_STUDIO_POSTPILOT_READONLY_VERIFIED','source_sha':SOURCE,'deployed_sha256':DEPLOYED,'prepared_sha256':PREPARED,
        'runtime_config_unchanged':True,'private_space_boundary_unchanged':True,'application_source_unchanged':True,'checks':result,
        'database_writes':0,'provider_requests':0,'credential_file_content_read':False,'raw_rows_exported':False},sort_keys=True))


if __name__=='__main__':
    try:main()
    except Exception as error:
        value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'POSTPILOT_READONLY_CHECK_REJECTED'
        print(json.dumps({'stage':'ASSET_STUDIO_POSTPILOT_READONLY_REJECTED','code':code},sort_keys=True));raise SystemExit(1)
