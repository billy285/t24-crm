"""Finalize an already-running, verified candidate after transient frontend check.

No container/nginx/database mutation. The only write is deployed.json after all
fresh boundaries match. Never rerun activate to finish an interrupted receipt.
"""
import argparse,fcntl,hashlib,json,os,re,socket,stat,time,types
from pathlib import Path
from types import SimpleNamespace

HELPER_SHA='922e0ed7d3fbde5d2985a5ea2a02b90b9622262f1969c8146535665133589f85'
MANIFEST_SHA='2201b8bdc780f751a3ef9f917eaa4d1a49e03070ab6fe54135030c8d40e5cd88'
SOURCE='18240e28774a1ce6043d06d1f7f913af2e9a369e'
ROOT=Path('/opt/t24-crm/releases/ringcentral-team-18240e28774a-20261109')
HOST='iZj6c4cj7edgnhdimts4l7Z'
H=lambda b:hashlib.sha256(b).hexdigest()

def need(ok,code):
 if not ok:raise RuntimeError(code)

def finalize(root=ROOT):
 need(os.geteuid()==0 and socket.gethostname()==HOST,'EXACT_ROOT_SERVER_REQUIRED')
 need(root==ROOT and root.resolve()==root and root.stat().st_uid==0 and not root.stat().st_mode&0o077,'EXACT_PRIVATE_RELEASE_REQUIRED')
 body=(root/'release.py').read_bytes();need(H(body)==HELPER_SHA,'RELEASE_HELPER_PIN_MISMATCH')
 m=types.ModuleType('ringcentral_finalization_helper');m.__file__=str(root/'release.py');exec(compile(body,m.__file__,'exec'),m.__dict__)
 need(m.SOURCE==SOURCE,'SOURCE_PIN_MISMATCH')
 release=m.Release(SimpleNamespace(release=root,manifest_sha256=MANIFEST_SHA))
 b=release.baseline();p=m.read(root/'prepared.json');start=m.read(root/'activation-started.json');candidate=m.read(root/'candidate.json');migration=m.read(root/'production-migrated.json')
 need(start['prepared_sha256']==H((root/'prepared.json').read_bytes()),'ACTIVATION_PREPARED_RECEIPT_MISMATCH')
 need(start['old_id']==b['runtime']['id'],'ACTIVATION_ORIGINAL_ID_MISMATCH')
 need(p['source_sha']==SOURCE and p['manifest_sha256']==MANIFEST_SHA and p['stage']=='PREPARED','PREPARED_SCOPE_MISMATCH')
 need(all(p[v] is True for v in ('offline_candidate_ready','offline_fallback_ready','offline_row_preservation')),'OFFLINE_REHEARSAL_PROOF_REQUIRED')
 evidence=m.read(root/'production-row-evidence-before.json')
 need(migration['schema_revision']==m.NEW and migration['original_rows_preserved'] is True and migration['row_evidence_sha256']==m.digest(evidence),'MIGRATION_ROW_PRESERVATION_PROOF_REQUIRED')
 migration_id=m.read(root/'migration-production.json');mi=m.inspect(migration_id['id'])
 need(not mi['State']['Running'] and mi['State']['ExitCode']==0 and mi['Image']==p['candidate_image'],'SUCCESSFUL_MIGRATION_EXIT_REQUIRED')
 old=m.inspect(b['runtime']['id'])
 need(not old['State']['Running'] and m.runtime(old)==b['runtime'],'EXACT_STOPPED_ORIGINAL_REQUIRED')
 need(old['Name']=='/'+candidate['retained'],'RETAINED_ORIGINAL_NAME_MISMATCH')
 live=m.inspect('t24-crm')
 need(live['Id']==candidate['id'] and live['Image']==p['candidate_image'] and live['State']['Running'],'EXACT_LIVE_CANDIDATE_REQUIRED')
 m.configuration_equal(live,old);need(m.inventory(live['Id'])==release.expected(),'LIVE_BACKEND_INVENTORY_MISMATCH')
 need(m.revision(m.DB)==m.NEW and m.schema(m.DB)==p['schema_after'],'MIGRATED_SCHEMA_MISMATCH')
 release.static_check()
 original=(root/'nginx-before.conf').read_bytes();oldroot=os.fsencode(b['public_root']);need(original.count(oldroot)==1,'EXACT_ORIGINAL_NGINX_ROOT_REQUIRED')
 expected=original.replace(oldroot,os.fsencode(release.public),1)
 need(m.NGINX.read_bytes()==expected and m.public_root()==release.public,'EXACT_UPDATED_NGINX_REQUIRED')
 need(m.private_runtimes()==b['private_runtimes'],'PRIVATE_SERVICES_CHANGED')
 # Use fresh local TLS requests and query strings so an old worker/cache cannot
 # be mistaken for the final active version. Require three stable observations.
 versions=[]
 for i in range(3):
  url='https://t24-crm.com/app-version.json?ringcentral-finalize='+str(time.time_ns())
  value=json.loads(m.run(['curl','-q','--silent','--show-error','--fail','--http1.1','--max-time','10','--noproxy','*','--resolve','t24-crm.com:443:127.0.0.1','-H','Cache-Control: no-cache',url],'FRESH_PUBLIC_VERSION_FAILED',15))
  need(value=={'version':release.manifest['frontend_version']},'FRESH_PUBLIC_VERSION_MISMATCH');versions.append(value['version'])
  release.public_check()  # Default version URL and public readiness must match too.
  if i<2:time.sleep(1)
 m.ready(live['Id']);need(m.runtime(m.inspect('t24-crm'))==m.runtime(live),'CANDIDATE_CHANGED_DURING_FINALIZATION')
 need(m.NGINX.read_bytes()==expected and m.private_runtimes()==b['private_runtimes'],'FINAL_BOUNDARY_CHANGED')
 result={'stage':'DEPLOYED','source_sha':SOURCE,'frontend_version':release.manifest['frontend_version'],'schema_revision':m.NEW,'runtime':m.runtime(live),'public_root':str(release.public),'retained_original':candidate['retained'],'original_rows_preserved_during_migration':True,'environment_preserved':True,'private_services_preserved':True,'receipt_finalized_after_fresh_public_checks':True,'stable_public_versions':versions}
 receipt=root/'deployed.json'
 if receipt.exists():
  previous=m.read(receipt)
  for k in ('stage','source_sha','frontend_version','schema_revision','runtime','public_root','retained_original'):need(previous[k]==result[k],'EXISTING_DEPLOYED_RECEIPT_MISMATCH')
  return previous
 m.write(receipt,result)
 return result

def main():
 os.umask(0o077)
 fd=os.open('/opt/t24-crm/releases/.ringcentral-team-release.lock',os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW,0o600)
 try:
  fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);print(json.dumps(finalize(),sort_keys=True))
 except BaseException as exc:
  reason=str(exc) if type(exc) is RuntimeError and re.fullmatch('[A-Z0-9_]+',str(exc)) else type(exc).__name__.upper()
  print(json.dumps({'stage':'FINALIZATION_REFUSED','reason':reason}));raise SystemExit(1)
 finally:os.close(fd)
if __name__=='__main__':main()
