#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'STATE'
import hashlib,json,os,re,socket,stat,subprocess
from pathlib import Path
H=lambda b:hashlib.sha256(b).hexdigest()
def need(v,c):
 if not v:raise RuntimeError(c)
def read(path,expected=None):
 for parent in path.parents:
  r=parent.lstat();need(parent.resolve()==parent and stat.S_ISDIR(r.st_mode) and r.st_uid==0 and not r.st_mode&0o022,'PROTECTED_PARENT_REQUIRED')
 before=path.lstat();need(path.resolve()==path and stat.S_ISREG(before.st_mode) and before.st_uid==0 and before.st_nlink==1 and stat.S_IMODE(before.st_mode)==0o600 and 0<before.st_size<1048576,'ROOT600_STATE_REQUIRED')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as f:opened=os.fstat(f.fileno());body=f.read(1048577);after=os.fstat(f.fileno())
 fields=lambda r:(r.st_dev,r.st_ino,r.st_uid,r.st_mode,r.st_nlink,r.st_size,r.st_mtime_ns,r.st_ctime_ns)
 need(fields(before)==fields(opened)==fields(after)==fields(path.lstat()) and len(body)==before.st_size and (expected is None or H(body)==expected),'EXACT_IMMUTABLE_STATE_REQUIRED');return body
try:
 need(os.geteuid()==0 and socket.gethostname()=='iZj6c4cj7edgnhdimts4l7Z','EXACT_ROOT_SERVER_REQUIRED');root=Path('/opt/t24-crm/releases/media-automation-c78b50a11e02-20261102')
 helper=read(root/'worker_enable.py','c5acd2d20de6ef07e1f417849b07ff6a0a28b6934cb6a590d08913207f5e66f9');main=json.loads(read(root/'deployed.json','bea765503d909b4ad5f7b1899cb040016ff44fdbe07970da3d82b0b4fbf1f212'));body=read(root/'worker-prepared.json');v=json.loads(body);need(body==(json.dumps(v,sort_keys=True,indent=2)+'\n').encode(),'CANONICAL_WORKER_PREPARED_REQUIRED')
 need(v['stage']=='MEDIA_AUTOMATION_WORKER_PREPARED' and v['source_sha']=='c78b50a11e020674ad53b34fbbfb5b1badd4a9a5' and v['main_deployed_sha256']=='bea765503d909b4ad5f7b1899cb040016ff44fdbe07970da3d82b0b4fbf1f212' and v['runtime']==main['crm'] and v['quiescent_baseline_sha256']==main['quiescent_baseline_sha256'] and v['three_tables_empty'] is True and v['existing_flags_environment_order_and_files_preserved'] is True and all(v[k] is False for k in ('policies_created','provider_requests','publications_requested','database_written')),'EXACT_ZERO_POLICY_PREPARED_STATE_REQUIRED')
 need(all(not(root/n).exists() for n in ('worker-candidate.json','worker-enabled.json','worker-recovered.json')),'UNEXPECTED_WORKER_ACTIVATION_RECORD')
 for name in ('t24-crm-before-autoprep-c78b50a11e02','t24-crm-autoprep-candidate-c78b50a11e02'):
  child=subprocess.run(['docker','container','inspect',name],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10);need(child.returncode==1,'UNEXPECTED_WORKER_CANDIDATE_CONTAINER')
 result=subprocess.run(['docker','container','inspect','t24-crm'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True,timeout=10);info=json.loads(result.stdout)[0];need(info['Id']==main['crm']['id'] and info['Image']==main['crm']['image'] and info['State']['Running'] is True and not any(x.split('=',1)[0]=='T24_MEDIA_MONTHLY_AUTOPREP_ENABLED' for x in info['Config']['Env']),'UNCHANGED_DEFAULT_OFF_MAIN_RUNTIME_REQUIRED')
 from types import SimpleNamespace
 namespace={'__name__':'worker_readonly_single_load','__file__':str(root/'worker_enable.py')};exec(compile(helper,namespace['__file__'],'exec'),namespace)
 args=SimpleNamespace(phase='activate',release=root,main_release_sha256='9cc1abc634f927fc0f3b54c1d8d6f8ede2fe5573eb4c730236f756015a97eefe',main_prepared_sha256='29ae8e354c8555a9aca186f5ef0b2368d17bd7f6007f73e57e6195e62558a47d',main_deployed_sha256='bea765503d909b4ad5f7b1899cb040016ff44fdbe07970da3d82b0b4fbf1f212',manifest_sha256='96f1baa987eeea40115fb8408ddb28d1a39b8a1dbbb254098f2da2ae554e44f8',payload_sha256='7054749c962d4cf5bd88b1ba040e6efd8ab85cca904675fb00aeb32340554c45',preflight=root.parent/'media-automation-preflight-b130a39759f3.json',preflight_sha256='b130a39759f3638b4428fd974913e1b1cf6b964f757f010ec7b76364baa2d8c0',review_sha256=H(body))
 match=False;reason=None
 try:
  instance=namespace['Enable'](args);instance.reviewed();instance.current();match=True
 except RuntimeError as e:
  reason=str(e);need(re.fullmatch('[A-Z][A-Z0-9_]{0,95}',reason),'BOUNDED_BASELINE_CHECK_RESULT_REQUIRED')
 print(json.dumps({'stage':'MEDIA_AUTOMATION_WORKER_READONLY_PREPARED_STATE','prepared':{**v,'receipt_sha256':H(body)},'all_current_rows_sequences_schema_match_main_quiescent_baseline':match,'baseline_check_code':reason,'main_runtime_unchanged':True,'worker_activation_records_absent':True,'worker_candidate_names_absent':True,'new_runtime_flag_absent':True,'business_writes':False,'provider_requests':False},sort_keys=True))
except BaseException as e:
 v=str(e);code=v if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',v) else 'WORKER_STATE_REJECTED';print(json.dumps({'stage':'WORKER_STATE_REJECTED','code':code,'business_writes':False}));raise SystemExit(1)
STATE
