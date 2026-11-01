"""Only isolated synthetic SQLite is read; no real server/database access."""
import ast
import copy
import importlib.util
import json
from pathlib import Path
import sqlite3
import pytest

HERE=Path(__file__).resolve().parent
def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
p=load(HERE/'postpilot_check.py','postpilot_checker_test')
maker=load(HERE/'make_postpilot_check.py','postpilot_maker_test')


def table(con,name,rows,*,autoincrement=False):
    columns=list(rows[0]);parts=[]
    for key in columns:
        value=rows[0][key];kind='INTEGER' if type(value)is int or key in {'owner_id','customer_id','material_id','prepared_by_id','revision','attempt','entity_id','width','height','byte_size','file_size'} else 'TEXT'
        if key=='id':kind+=' PRIMARY KEY'+(' AUTOINCREMENT' if autoincrement else '')
        parts.append(p.quote(key)+' '+kind)
    con.execute('CREATE TABLE '+p.quote(name)+'('+','.join(parts)+')')
    for row in rows:insert(con,name,row)


def insert(con,name,row):
    columns=list(row);con.execute('INSERT INTO '+p.quote(name)+'('+','.join(p.quote(x) for x in columns)+') VALUES('+','.join('?' for _ in columns)+')',tuple(row[x] for x in columns))


def fixture(path):
    con=sqlite3.connect(path);owner=7
    original_images=[{'id':str(i)*32,'material_id':i,'customer_id':20,'prepared_by_id':owner,'revoked_at':None,'source_sha256':str(i)*64,'image_sha256':str(i+2)*64,'byte_size':1000,'width':640,'height':480} for i in (1,2)]
    material=lambda mid:{'id':mid,'customer_id':20,'user_id':str(owner),'material_type':'image' if mid!=7 else 'video','visibility':'team','source_type':'upload','approval_status':'pending','usage_status':'unused','file_size':1000,'content_type':'image/png' if mid!=7 else 'video/mp4','title':'NEVER EXPORT PRIVATE MATERIAL TEXT'}
    table(con,'customer_materials',[material(i) for i in range(1,6)],autoincrement=True)
    table(con,'media_publication_images',original_images)
    audit=lambda aid,mid,job,sha,images:{'id':aid,'customer_id':20,'entity_type':'customer_materials','entity_id':mid,'actor_id':str(owner),'module':'materials','action':'create','before':'{}','after':json.dumps({'source_job_id':job,'output_sha256':sha,'source_image_ids':images,'approval_status':'pending'})}
    table(con,'customer_record_audits',[audit(1,1,'original-job','a'*64,[])],autoincrement=True)
    table(con,'media_monthly_workflows',[{'id':1,'customer_id':20,'owner_id':owner,'status':'prepared','preview_hash':'e'*64,'source_hash':'f'*64,'snapshot':'ORIGINAL PRIVATE PACKET'}])
    table(con,'alembic_version',[{'version_num':'e10cb234c570'}])
    table(con,'payments',[{'id':1,'amount':199,'closing_state':'closed','commission_owner':'original-owner'}])
    table(con,'customer_access_grants',[{'id':1,'customer_id':20,'scopes':'ORIGINAL ACL'}])
    for i in range(147):table(con,'legacy_'+str(i),[{'id':1,'value':'preserved legacy data'}])
    table(con,'monthly_deduction_rates',[{'id':1,'value':'preserved monthly rate'}],autoincrement=True)
    con.commit();before,_,old_metadata,_,_=p.snapshot(con)
    settings={'preset':'clean','brand_name':'PRIVATE BRAND NEVER EXPORT','primary_color':'#112233','accent_color':'#F59E0B','footer':'PRIVATE FOOTER NEVER EXPORT'}
    table(con,'media_asset_profiles',[{'owner_id':owner,'customer_id':20,'revision':1,'settings':json.dumps(settings)}])
    jobs=[]
    for index,kind in enumerate(('poster','video')):
        mid=6+index;sourceids=[x['id'] for x in original_images[:1+index]];identity=('a' if index==0 else 'b')*32
        output={'mime_type':'image/png' if index==0 else 'video/mp4','duration_seconds':None if index==0 else 6,'sha256':('c' if index==0 else 'd')*64,'byte_size':1000,'width':1080,'height':1080}
        snapshot={'profile':{'revision':1,**settings},'recipe':{'kind':kind,'rights_confirmed':True,'image_ids':sourceids},'proofs':[{'id':x['id'],'material_id':x['material_id'],'source_sha256':x['source_sha256'],'image_sha256':x['image_sha256']} for x in original_images[:1+index]]}
        jobs.append({'id':identity,'owner_id':owner,'customer_id':20,'status':'adopted','kind':kind,'revision':4,'attempt':1,'lease_token':None,'error_code':None,'request_id':f'00000000-0000-4000-8000-{index+2:012}', 'output':json.dumps(output),'snapshot':json.dumps(snapshot),'adoption':json.dumps({'material_id':mid,'image_id':'3'*32 if mid==6 else None,'preview_path':'/api/v1/media-publication-images/'+'3'*32+'/preview' if mid==6 else None})})
        insert(con,'customer_materials',material(mid));insert(con,'customer_record_audits',audit(index+2,mid,identity,output['sha256'],sourceids))
    insert(con,'media_publication_images',{'id':'3'*32,'material_id':6,'customer_id':20,'prepared_by_id':owner,'revoked_at':None,'source_sha256':'c'*64,'image_sha256':'c'*64,'byte_size':1000,'width':1080,'height':1080})
    table(con,'media_asset_jobs',jobs)
    requests=[]
    for i,(kind,jobid) in enumerate((('profile',None),('create','a'*32),('create','b'*32),('adopt','a'*32),('adopt','b'*32))):
        requests.append({'id':i+1,'owner_id':owner,'customer_id':20,'kind':kind,'request_id':f'00000000-0000-4000-8000-{i+1:012}','fingerprint':'f'*64,'result':json.dumps({'job_id':jobid})})
    table(con,'media_asset_requests',requests);con.execute("UPDATE alembic_version SET version_num='f21dc345d681'");con.commit()
    return con,before,old_metadata


def check(con,before,metadata):
    current,raw,after,_,objects=p.snapshot(con);return p.audit(before,current,raw,metadata,after,objects)


def test_exact_append_only_pilot_passes_without_raw_rows_exported(tmp_path):
    con,before,metadata=fixture(tmp_path/'synthetic.db')
    try:
        answer=check(con,before,metadata)
        assert answer['current_tables']==158 and answer['append_only_material_ids']==[6,7] and answer['asset_request_receipts']==5
        assert not any(x in json.dumps(answer) for x in ['PRIVATE','file_path','source_job_id','brand_name','scope'])
    finally:con.close()


@pytest.mark.parametrize('change',["UPDATE customer_materials SET title='edited old' WHERE id=1",'DELETE FROM customer_materials WHERE id=1',
    "INSERT INTO legacy_0 VALUES(2,'extra')","UPDATE payments SET amount=1","UPDATE customer_access_grants SET scopes='changed'",
    "UPDATE media_monthly_workflows SET source_hash='changed'","UPDATE media_asset_jobs SET owner_id=1","UPDATE customer_materials SET material_type='image' WHERE id=7",
    "UPDATE customer_materials SET approval_status='approved' WHERE id=6","DELETE FROM media_asset_requests WHERE id=5","UPDATE media_asset_jobs SET status='queued'",
    "UPDATE media_asset_requests SET kind='retry' WHERE id=5","UPDATE customer_record_audits SET actor_id='1' WHERE id=2",
    "UPDATE media_publication_images SET material_id=7 WHERE id='33333333333333333333333333333333'",
    "UPDATE sqlite_sequence SET seq=99 WHERE name='customer_materials'"])
def test_any_old_row_finance_acl_packet_or_unapproved_pilot_change_is_rejected(tmp_path,change):
    con,before,metadata=fixture(tmp_path/'synthetic.db')
    try:
        con.execute(change);con.commit()
        with pytest.raises(RuntimeError):check(con,before,metadata)
    finally:con.close()


def test_current_transaction_runs_only_reads_and_query_only_guard(tmp_path):
    con,before,metadata=fixture(tmp_path/'synthetic.db');con.close();read=sqlite3.connect('file:'+str(tmp_path/'synthetic.db')+'?mode=ro',uri=True)
    calls=[];read.set_trace_callback(calls.append)
    try:
        read.execute('PRAGMA query_only=ON');read.execute('BEGIN');check(read,before,metadata)
        assert all(not x.lstrip().upper().startswith(('UPDATE','INSERT','DELETE','CREATE','ALTER','DROP','REPLACE')) for x in calls)
    finally:read.close()


def test_checker_keeps_snapshot_hash_algorithm_and_short_frozen_loader():
    assert p.rows_hash([(1,'中文',b'\x01')])==p.H(json.dumps([1,'中文',b'\x01'],ensure_ascii=True,default=lambda x:bytes(x).hex()).encode())
    source=(HERE/'postpilot_check.py').read_text();ast.parse(source)
    assert 'pf.sample(' not in source.replace('current()/pf.sample()','') and 'ctx.current(' not in source
    assert "?mode=ro" in source and "PRAGMA query_only=ON" in source and "production-before-rows.json" in source
    command,pins=maker.generate();assert len(command.encode())<14336 and not pins['executed'] and not pins['database_writes']
    ast.parse(command.split("<<'POSTPILOT'\n",1)[1].rsplit('\nPOSTPILOT',1)[0])


def test_only_existing_monthly_insert_ignore_counter_can_move_forward_without_row_change(tmp_path):
    con,before,metadata=fixture(tmp_path/'synthetic.db')
    try:
        con.execute("UPDATE sqlite_sequence SET seq=12 WHERE name='monthly_deduction_rates'");con.commit()
        assert check(con,before,metadata)['protected_original_rows_unchanged'] is True
        con.execute("UPDATE sqlite_sequence SET seq=0 WHERE name='monthly_deduction_rates'");con.commit()
        with pytest.raises(RuntimeError,match='PROTECTED_SEQUENCE_COUNTER_CHANGED'):check(con,before,metadata)
    finally:con.close()
