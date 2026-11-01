"""Read-only aggregate proof for exactly one owner discovery, never a binding."""
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import socket
import sqlite3
import stat
import types
from datetime import datetime, timezone
from uuid import UUID

SOURCE='8b429dad8a2f144ea27527717d4811fb7ddc9b3c'
FRONTEND='b0e161d74fe5'
MANIFEST='3c714aba0a597b1c46d66d8979bf43ec6464d0d5ff9c219dd0e47dd0ba816ad0'
PAYLOAD='61cdb231e54302f44a13c59c42ee488f97e892c45bfbee50c2cfcced72db4bb1'
PREFLIGHT='2b1a9dde5020023ef33136b45bc54384745aeed30ab5f2c2e3312a59a8ebd485'
HEAD='g32ed456e792'
PREFIX='google_business_onboarding_'
CAT=PREFIX+'catalogs';REQ=PREFIX+'requests';BATCH=PREFIX+'batches';ITEM=PREFIX+'items'
NEW={CAT,REQ,BATCH,ITEM}
CONNECTIONS='google_business_connections'
RAW=NEW|{CONNECTIONS,'employees'}
H=lambda body:hashlib.sha256(body).hexdigest()

def need(ok,code):
    if not ok:raise RuntimeError(code)

def digest(value):return H(json.dumps(value,sort_keys=True,separators=(',',':')).encode())
def quote(value):return '"'+value.replace('"','""')+'"'
def rows_hash(rows):return H('\n'.join(sorted(json.dumps(list(row),ensure_ascii=True,default=lambda x:bytes(x).hex()) for row in rows)).encode())
def decoded(value):return json.loads(value) if isinstance(value,str) else value
def sha(value):return isinstance(value,str) and re.fullmatch('[a-f0-9]{64}',value) is not None
def hexid(value):return isinstance(value,str) and re.fullmatch('[a-f0-9]{32}',value) is not None
def uuid(value):
    try:return str(UUID(value))==value
    except (ValueError,TypeError,AttributeError):return False
def stamp(value):
    need(isinstance(value,str),'EXACT_TIMESTAMP_REQUIRED')
    match=re.fullmatch(r'([0-9]{4}-[0-9]{2}-[0-9]{2})[T ]([0-9]{2}:[0-9]{2}:[0-9]{2})(?:\.([0-9]{1,9}))?(Z|[+-][0-9]{2}:[0-9]{2})?',value)
    need(match is not None,'EXACT_BOUNDED_TIMESTAMP_FORMAT_REQUIRED')
    date,time,fraction,zone=match.groups()
    # Python 3.10 rejects Docker's 8/9 digit fraction. Normalize ONLY this
    # bounded comparison value; the original runtime bytes/hash remain exact.
    normalized=date+'T'+time+('.'+(fraction+'000000')[:6] if fraction else '')+('+00:00' if zone=='Z' else zone or '')
    parsed=datetime.fromisoformat(normalized)
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)

def timestamp_canary():
    base=datetime(2026,11,1,19,0,56,tzinfo=timezone.utc)
    for fraction,microsecond in (('',0),('.1',100000),('.123',123000),('.123456',123456),('.90391494',903914),('.123456789',123456)):
        expected=base.replace(microsecond=microsecond)
        need(stamp('2026-11-01T19:00:56'+fraction+'Z')==expected and stamp('2026-11-01 19:00:56'+fraction)==expected and stamp('2026-11-01T19:00:56'+fraction+'+00:00')==expected,'HOST_TIMESTAMP_COMPARISON_CANARY_FAILED')
    return True

def identity(row):return (row.st_dev,row.st_ino,row.st_uid,row.st_mode,row.st_nlink,row.st_size,row.st_mtime_ns,row.st_ctime_ns)

def protected(path,*,file=True):
    need(path.is_absolute() and path.resolve()==path,'CANONICAL_PROTECTED_PATH_REQUIRED')
    for parent in path.parents:
        row=parent.lstat();need(stat.S_ISDIR(row.st_mode) and row.st_uid==0 and not row.st_mode&0o022 and not parent.is_symlink(),'ROOT_PROTECTED_PARENT_REQUIRED')
    row=path.lstat()
    need(row.st_uid==0 and not path.is_symlink() and not row.st_mode&0o022,'ROOT_PROTECTED_PATH_REQUIRED')
    if file:need(stat.S_ISREG(row.st_mode) and row.st_nlink==1 and stat.S_IMODE(row.st_mode)==0o600,'ROOT600_REGULAR_FILE_REQUIRED')
    else:need(stat.S_ISDIR(row.st_mode),'ROOT_PROTECTED_DIRECTORY_REQUIRED')
    return row

def read(path,expected=None,maximum=16777216):
    row=protected(path);need(0<row.st_size<=maximum,'BOUNDED_PROTECTED_RECEIPT_REQUIRED')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as stream:
        opened=os.fstat(stream.fileno());body=stream.read(maximum+1);after=os.fstat(stream.fileno())
    need(identity(row)==identity(opened)==identity(after)==identity(path.lstat()) and len(body)==row.st_size and (expected is None or H(body)==expected),'PROTECTED_RECEIPT_CHANGED')
    return body

def snapshot(con):
    tables=[x[0] for x in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    need(len(tables)==162,'EXACT162_TABLES_REQUIRED');result={};raw={};shapes={}
    for name in tables:
        info=con.execute('PRAGMA table_info('+quote(name)+')').fetchall()
        index=con.execute('PRAGMA index_list('+quote(name)+')').fetchall()
        schema={row[1]:(row[2],row[3],row[4],row[5]) for row in info};columns=list(schema)
        indexes={row[1]:(row[2],row[3],row[4],tuple(x[2] for x in con.execute('PRAGMA index_info('+quote(row[1])+')'))) for row in index}
        rows=list(con.execute('SELECT '+','.join(quote(x) for x in columns)+' FROM '+quote(name)))
        result[name]={'columns':columns,'schema':schema,'indexes':indexes,'count':len(rows),'rows_sha256':rows_hash(rows)}
        if name in RAW:raw[name]=[dict(zip(columns,row)) for row in rows]
        if name in NEW:
            shapes[name]=digest([info,index,con.execute('PRAGMA foreign_key_list('+quote(name)+')').fetchall(),con.execute('SELECT type,name,tbl_name,sql FROM sqlite_master WHERE tbl_name=? ORDER BY type,name',(name,)).fetchall()])
    objects=con.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
    present=con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'").fetchone() is not None
    seq=dict(con.execute('SELECT name,seq FROM sqlite_sequence ORDER BY name').fetchall()) if present else {}
    pragma=[con.execute('PRAGMA '+x).fetchone()[0] for x in ('user_version','application_id')]
    return json.loads(json.dumps(result)),raw,{'pragma_sha256':digest(pragma),'sequence_exists':present,'sequence_values':seq,'sequence_sha256':digest(sorted(seq.items()))},digest(objects),shapes

def copy_connections(path,before,*,schema_sha256=None,metadata_check=None):
    """The stopped, isolated copy proves old columns without exporting tokens."""
    row=protected(path);fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        need(identity(row)==identity(os.fstat(fd)),'OLD_COPY_IDENTITY_CHANGED')
        con=sqlite3.connect('file:'+str(path)+'?mode=ro&immutable=1',uri=True,timeout=3)
        try:
            con.execute('PRAGMA query_only=ON');con.execute('BEGIN')
            info=con.execute('PRAGMA table_info('+CONNECTIONS+')').fetchall();columns=[x[1] for x in info]
            rows=con.execute('SELECT '+','.join(quote(x) for x in columns)+' FROM '+CONNECTIONS).fetchall()
            need(columns==before['columns'] and len(rows)==before['count'] and rows_hash(rows)==before['rows_sha256'],'OLD_CONNECTION_COPY_BASELINE_HASH_REQUIRED')
            need(con.execute('SELECT version_num FROM alembic_version').fetchall()==[(HEAD,)],'OLD_COPY_REVIEWED_SCHEMA_HEAD_REQUIRED')
            if schema_sha256 is not None:
                objects=con.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
                need(digest(objects)==schema_sha256,'OLD_COPY_REVIEWED_SCHEMA_OBJECTS_REQUIRED')
            if metadata_check is not None:
                present=con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'").fetchone() is not None
                seq=dict(con.execute('SELECT name,seq FROM sqlite_sequence ORDER BY name').fetchall()) if present else {}
                pragma=[con.execute('PRAGMA '+x).fetchone()[0] for x in ('user_version','application_id')]
                metadata_check({'pragma_sha256':digest(pragma),'sequence_exists':present,'sequence_values':seq,'sequence_sha256':digest(sorted(seq.items()))})
            result=[dict(zip(columns,x)) for x in rows]
        finally:con.close()
        need(identity(row)==identity(os.fstat(fd))==identity(path.lstat()),'OLD_CONNECTION_COPY_CHANGED')
        return result
    finally:os.close(fd)

def verify_copy_writer_absent(ctx,root,image):
    """The API probe used --rm. A missing probe is expected, not an error waiver."""
    m=ctx.m;argv=ctx.offline_args(root/'probe-data',image)
    need(argv[:3]==['docker','run','--rm'] and argv.count('--rm')==1 and '--network=none' in argv and '--read-only' in argv and argv[-1]==image,'EXACT_AUTO_REMOVE_OFFLINE_SOURCE_REQUIRED')
    probe=m.inspect_optional(ctx.offline_name)
    if probe is not None:
        need(probe.get('Name')=='/'+ctx.offline_name and probe.get('Image')==image and probe.get('Config',{}).get('Image')==image and probe.get('State',{}).get('Running') is False and probe['State'].get('Status')=='exited' and probe['State'].get('ExitCode')==0,'EXACT_STOPPED_API_PROBE_REQUIRED')
        host=probe.get('HostConfig',{});need(host.get('AutoRemove') is True and host.get('ReadonlyRootfs') is True and host.get('NetworkMode')=='none','EXACT_API_PROBE_ISOLATION_REQUIRED')
        mounts=probe.get('Mounts');need(isinstance(mounts,list) and len(mounts)==2,'EXACT_API_PROBE_MOUNTS_REQUIRED')
        expected={('/app/backend/data',str(root/'probe-data')),('/app/backend/logs',str(root/'probe-logs'))}
        need({(x.get('Destination'),x.get('Source')) for x in mounts}==expected and all(x.get('Type')=='bind' and x.get('RW') is True for x in mounts),'EXACT_API_PROBE_MOUNTS_REQUIRED')
        ctx.verify_offline_environment(probe)
        code,blob=m.retained().docker_request('GET','/images/'+image+'/json');need(code==200,'EXACT_API_PROBE_IMAGE_METADATA_REQUIRED');base=json.loads(blob)
        need(base.get('Id')==image and all(probe['Config'].get(key)==base.get('Config',{}).get(key) for key in ('Cmd','Entrypoint','WorkingDir','User')),'EXACT_API_PROBE_IMAGE_COMMAND_REQUIRED')
    # Only running-container mount metadata is read. No environment/credential
    # content is exported, and no unknown writer is stopped or altered.
    code,blob=m.retained().docker_request('GET','/containers/json?all=0');need(code==200 and len(blob)<=2097152,'RUNNING_WRITER_METADATA_REQUIRED')
    running=json.loads(blob);need(isinstance(running,list) and len(running)<=128,'BOUNDED_RUNNING_WRITER_METADATA_REQUIRED')
    copy_path=root/'probe-data'/'crm_prod.db'
    for row in running:
        need(isinstance(row,dict) and isinstance(row.get('Mounts'),list) and len(row['Mounts'])<=64,'KNOWN_RUNNING_MOUNT_METADATA_REQUIRED')
        for mount in row['Mounts']:
            need(isinstance(mount,dict) and type(mount.get('RW'))is bool,'KNOWN_RUNNING_MOUNT_MODE_REQUIRED')
            source=mount.get('Source')
            if mount['RW'] and isinstance(source,str) and source.startswith('/'):
                path=Path(source)
                need(path!=copy_path and path not in copy_path.parents and copy_path not in path.parents,'RUNNING_OLD_COPY_WRITER_REJECTED')
    return 'auto_removed' if probe is None else 'exact_stopped'

def audit(before,current,raw,old_metadata,metadata,*,started,expected_customer_id=None,old_connections=None,allow_refresh=False):
    need(len(before)==158 and set(current)==set(before)|NEW and len(current)==162,'EXACT158_PLUS4_TABLES_REQUIRED')
    need(before['customers']['count']==43 and before['google_business_bindings']['count']==15,'EXACT_ORIGINAL43_CUSTOMERS15_BINDINGS_REQUIRED')
    need(current[BATCH]['count']==current[ITEM]['count']==0 and not raw[BATCH] and not raw[ITEM],'NO_PREVIEW_BATCH_ITEM_OR_BINDING_ALLOWED')
    need(len(raw[CAT])==len(raw[REQ])==1,'EXACT_ONE_DISCOVERY_AND_RECEIPT_REQUIRED')
    catalog=raw[CAT][0];request=raw[REQ][0]
    need(hexid(catalog['id']) and catalog['status']=='ready' and catalog['revision']==3 and catalog['lease_token'] is None and catalog['error_code'] is None,'READY_SINGLE_DISCOVERY_WITH_RELEASED_LEASE_REQUIRED')
    need(catalog['customer_id']==expected_customer_id and (expected_customer_id is None or type(expected_customer_id)is int and expected_customer_id>0),'EXACT_REQUESTED_CUSTOMER_SCOPE_REQUIRED')
    need(type(catalog['owner_id'])is int and catalog['owner_id']>0 and type(catalog['connection_id'])is int,'CATALOG_OWNER_CONNECTION_REQUIRED')
    owner=catalog['owner_id'];connection=next((x for x in raw[CONNECTIONS] if x['id']==catalog['connection_id']),None)
    need(connection is not None and connection['owner_id']==owner and connection['active']==1 and connection['needs_reconnect']==0 and connection['last_error'] is None,'ACTIVE_SAME_OWNER_CONNECTION_REQUIRED')
    employee=next((x for x in raw['employees'] if x['id']==owner),None)
    need(employee is not None and employee['role']=='super_admin' and employee['status'] in {'active','probation'},'LIVE_OWNER_ROLE_REQUIRED')
    marker=decoded(catalog['connection_marker'])
    need(isinstance(marker,dict) and set(marker)=={'id','owner_id','connected_at'} and marker['id']==connection['id'] and marker['owner_id']==owner and stamp(marker['connected_at'])==stamp(connection['connected_at']),'EXACT_CONNECTION_IDENTITY_MARKER_REQUIRED')
    created=stamp(catalog['created_at']);observed=stamp(catalog['observed_at']);leased=stamp(catalog['lease_at']);expires=stamp(catalog['expires_at'])
    need(stamp(started)<=created<=leased<=observed and stamp(catalog['updated_at'])==observed and 0<=(observed-leased).total_seconds()<120 and (expires-observed).total_seconds()==600,'DISCOVERY_TIME_LEASE_TTL_MISMATCH')
    locations=decoded(catalog['locations']);need(isinstance(locations,list) and 0<len(locations)<=500 and catalog['truncated'] in {0,1},'BOUNDED_SANITIZED_CATALOG_REQUIRED')
    names=set()
    for row in locations:
        need(isinstance(row,dict) and set(row)=={'location_name','title','address','observed_at'} and isinstance(row['location_name'],str) and re.fullmatch(r'accounts/[0-9]+/locations/[0-9]+',row['location_name']) and len(row['location_name'])<=200 and isinstance(row['title'],str) and len(row['title'])<=255 and isinstance(row['address'],str) and len(row['address'])<=1000 and stamp(row['observed_at'])==observed,'SANITIZED_LOCATION_FIELDS_REQUIRED')
        need(row['location_name'] not in names,'DUPLICATE_CATALOG_PATH_REJECTED');names.add(row['location_name'])
    need(request['owner_id']==owner and request['kind']=='discovery' and request['resource_id']==catalog['id'] and uuid(request['request_id']) and request['fingerprint']==digest({'connection_id':connection['id'],'customer_id':expected_customer_id}) and created<=stamp(request['created_at'])<=observed,'EXACT_ORIGINAL_DISCOVERY_RECEIPT_REQUIRED')
    connection_changed=False
    for name,old in before.items():
        now=current[name];need(all(now[k]==old[k] for k in ('columns','schema','indexes')),'ORIGINAL_TABLE_SHAPE_CHANGED')
        if name=='alembic_version':need(now['count']==1 and now['rows_sha256']==rows_hash([(HEAD,)]),'EXACT_REVIEWED_SCHEMA_HEAD_REQUIRED')
        elif name==CONNECTIONS and (now['count'],now['rows_sha256'])!=(old['count'],old['rows_sha256']):
            need(allow_refresh and old_connections is not None,'CONNECTION_CHANGE_REQUIRES_EXPLICIT_OLD_COLUMN_PROOF')
            columns=old['columns'];need(len(old_connections)==old['count'] and rows_hash([tuple(x[k] for k in columns) for x in old_connections])==old['rows_sha256'],'OLD_CONNECTION_COLUMNS_NOT_BASELINE_BOUND')
            oldmap={x['id']:x for x in old_connections};newmap={x['id']:x for x in raw[CONNECTIONS]}
            need(len(oldmap)==len(old_connections) and set(newmap)==set(oldmap) and now['count']==old['count'],'CONNECTION_ROWS_ADDED_OR_REMOVED')
            for key,previous in oldmap.items():
                changed={column for column in columns if previous[column]!=newmap[key][column]}
                need(not changed or key==connection['id'] and changed<={'token_encrypted','last_error'} and newmap[key]['last_error'] is None and isinstance(newmap[key]['token_encrypted'],str) and 0<len(newmap[key]['token_encrypted'])<=65536,'UNAUTHORIZED_CONNECTION_COLUMN_CHANGED')
            connection_changed=True
        else:need((now['count'],now['rows_sha256'])==(old['count'],old['rows_sha256']),'PROTECTED_ORIGINAL_ROWS_CHANGED')
    need(old_metadata['pragma_sha256']==metadata['pragma_sha256'] and old_metadata['sequence_exists'] is metadata['sequence_exists'],'ORIGINAL_SQLITE_METADATA_CHANGED')
    oldseq=old_metadata['sequence_values'];seq=metadata['sequence_values'];need(set(oldseq)==set(seq),'ORIGINAL_SEQUENCE_KEYS_CHANGED')
    for key,value in seq.items():
        need(type(value)is int and (value>=oldseq[key] if key=='monthly_deduction_rates' else value==oldseq[key]),'PROTECTED_SEQUENCE_COUNTER_CHANGED')
    return {'original_tables':158,'current_tables':162,'original158_shapes_preserved':True,'original158_rows_preserved_except_schema_head_and_explicit_connection_refresh':True,'crm_customers':43,'existing_google_bindings':15,'new_catalogs':1,'new_discovery_receipts':1,'new_batches':0,'new_items':0,'catalog_locations':len(locations),'catalog_truncated':bool(catalog['truncated']),'owner_and_connection_scope_verified':True,'connection_refresh_columns_changed':connection_changed,'connection_refresh_allowed_columns':['last_error','token_encrypted'] if connection_changed else [],'existing_monthly_rate_counter_forward_only':True,'all_other_sequence_counters_unchanged':True}

def main(pins):
    need(isinstance(pins,dict),'ACTUAL_PREPARED_DEPLOYED_PINS_REQUIRED')
    need(os.geteuid()==0 and socket.gethostname()=='iZj6c4cj7edgnhdimts4l7Z','EXACT_ROOT_SERVER_REQUIRED');resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    timestamp_canary()
    root=Path(pins['release']);need(re.fullmatch(r'/opt/t24-crm/releases/google-business-onboarding(?:-r[2-9][0-9]*)?-8b429dad8a2f-20261102',str(root)) is not None,'EXACT_RELEASE_NAMESPACE_REQUIRED');protected(root,file=False)
    body=read(root/'release.py',pins['helper_sha256']);r=types.ModuleType('_exact_onboarding_postpilot_release');r.__file__=str(root/'release.py');exec(compile(body,r.__file__,'exec'),r.__dict__)
    need(r.SOURCE_SHA==SOURCE and r.FRONTEND==FRONTEND and str(root)=='/opt/t24-crm/releases/'+r.SCOPE+'-'+SOURCE[:12]+'-20261102','EXACT_FROZEN_APPLICATION_REQUIRED')
    args=types.SimpleNamespace(release=root,preflight=root.parent/('google-business-onboarding-preflight-'+PREFLIGHT[:12]+'.json'),preflight_sha256=PREFLIGHT,manifest_sha256=MANIFEST,payload_sha256=PAYLOAD,review_sha256=pins['prepared_sha256'])
    ctx=r.Release(args);m=ctx.m;runtime=pins['runtime']
    prepared=json.loads(read(root/'prepared.json',pins['prepared_sha256']));r.validate_prepared(prepared,MANIFEST,PAYLOAD,PREFLIGHT)
    deployed=json.loads(read(root/'deployed.json',pins['deployed_sha256']))
    need(deployed['stage']=='GOOGLE_ONBOARDING_DEPLOYED' and deployed['source_sha']==SOURCE and deployed['frontend_version']==FRONTEND and deployed['schema_revision']==HEAD and deployed['crm']==runtime and deployed['prepared_sha256']==pins['prepared_sha256'] and deployed['preflight_sha256']==PREFLIGHT and deployed['schema_sha256']==prepared['schema_after_sha256'],'EXACT_DEPLOYED_RUNTIME_PROOF_REQUIRED')
    baseline_id=json.loads(read(root/'production-baseline-identity.json'))
    need(baseline_id=={'source_sha':SOURCE,'original_id':ctx.proof['crm']['id'],'candidate_id':runtime['id'],'review_sha256':pins['prepared_sha256'],'rows_sha256':baseline_id['rows_sha256']} and sha(baseline_id['rows_sha256']),'ACTIVATION_BASELINE_IDENTITY_REQUIRED')
    before=json.loads(read(root/'production-before-rows.json',baseline_id['rows_sha256']));need(ctx.retained.evidence(before)==ctx.proof['rows'],'ORIGINAL158_BASELINE_HASH_CHAIN_REQUIRED')
    info=m.inspect('t24-crm');need(info['State']['Running'] is True and m.runtime(info)==runtime,'CURRENT_RUNTIME_ENV_OR_CONFIG_CHANGED')
    expected=json.loads(read(root/'backend-candidate-inventory.json',prepared['candidate_inventory_sha256']));need(m.inventory(runtime['id'])==expected,'CURRENT_APPLICATION_SOURCE_CHANGED')
    need(ctx.safe.safe_private_boundary(m,ctx.pins)==ctx.proof['private_boundary'],'PRIVATE_SPACE_BOUNDARY_CHANGED');ctx.nginx(updated=True)
    need(m.BUSINESS==Path('/opt/t24-crm/app/data/crm_prod.db'),'EXACT_BUSINESS_DB_PATH_REQUIRED');dbrow=m.BUSINESS.lstat();need(not m.BUSINESS.is_symlink() and [dbrow.st_dev,dbrow.st_ino]==ctx.proof['database_identity'],'EXACT_BUSINESS_DB_IDENTITY_REQUIRED')
    old_connections=None
    if pins['allow_connection_refresh']:
        verify_copy_writer_absent(ctx,root,runtime['image'])
        old_connections=copy_connections(root/'probe-data'/'crm_prod.db',before[CONNECTIONS],schema_sha256=deployed['schema_sha256'],metadata_check=lambda value:ctx.retained.live_sequence_boundary(ctx.proof['database_metadata'],value))
    con=sqlite3.connect('file:'+str(m.BUSINESS)+'?mode=ro',uri=True,timeout=3)
    try:
        con.execute('PRAGMA query_only=ON');con.execute('BEGIN');current,raw,metadata,schema,shapes=snapshot(con)
        need(schema==deployed['schema_sha256'] and shapes==r.NEW_TABLE_SHAPES,'EXACT_DEPLOYED162_SCHEMA_REQUIRED')
        result=audit(before,current,raw,ctx.proof['database_metadata'],metadata,started=runtime['started'],expected_customer_id=pins['customer_id'],old_connections=old_connections,allow_refresh=pins['allow_connection_refresh'])
    finally:con.close()
    need(m.runtime(m.inspect('t24-crm'))==runtime and [m.BUSINESS.stat().st_dev,m.BUSINESS.stat().st_ino]==ctx.proof['database_identity'],'RUNTIME_OR_DATABASE_CHANGED_DURING_READ')
    result={'stage':'GOOGLE_ONBOARDING_POSTPILOT_READONLY_VERIFIED','source_sha':SOURCE,'prepared_sha256':pins['prepared_sha256'],'deployed_sha256':pins['deployed_sha256'],'application_source_unchanged':True,'runtime_config_unchanged':True,'timestamp_1_to_9_fraction_compatibility_verified':True,'private_boundary_unchanged':True,'checks':result,'database_writes':0,'provider_requests':0,'credentials_decrypted':False,'credential_file_content_read':False,'raw_rows_exported':False}
    output=json.dumps(result,sort_keys=True);need(len(output.encode())<15000,'BOUNDED_AGGREGATE_REQUIRED');print(output)

if __name__=='__main__':
    try:main(globals().get('PINS'))
    except Exception as error:
        value=str(error);code=value if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',value) else 'POSTPILOT_READONLY_CHECK_REJECTED'
        print(json.dumps({'stage':'GOOGLE_ONBOARDING_POSTPILOT_READONLY_REJECTED','code':code},sort_keys=True));raise SystemExit(1)
