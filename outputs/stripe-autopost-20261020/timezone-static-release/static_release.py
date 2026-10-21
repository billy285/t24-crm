"""Static timezone display correction only; never stop services or write data.

Prepare creates a fresh unserved public directory retaining old hashed assets.
Activation changes exactly one Nginx root after an independently reviewed receipt.
Any failure can roll back only that root; no database rollback is implemented.
"""
import argparse
import fcntl
import hashlib
import json
import os
import re
import socket
import sqlite3
import stat
import sys
import time
from pathlib import Path
from types import SimpleNamespace

H=lambda body:hashlib.sha256(body).hexdigest()
BASE_SOURCE='515bd526f087891e4b2ca586508ed7a47c39956e'
BASE_VERSION='9c1da3b9d1c0'
BASE_FOLDER=Path('/opt/t24-crm/releases/stripe-autopost-515bd526f087-20261020')
BASE_PUBLIC=Path('/var/www/t24-crm-public/stripe-autopost-515bd526f087-20261020')
BASE_HELPER_SHA='1220b5b4506a9c53a4cbc9950d34b76cbb26a43e73997fb2041dafff622629ee'
BASE_MANIFEST_SHA='175fce4d511025d2c96d1b36aaa4ebb9ba0cf983b591bb409144bb49c1b27a16'
BASE_PAYLOAD_SHA='39b13362ac74e87194fe135455e238dc596b952c45c153fabd4e423230857dc8'
BASE_PREFLIGHT=Path('/opt/t24-crm/releases/stripe-autopost-preflight-df3adabdea3e.json')
BASE_PREFLIGHT_SHA='df3adabdea3e5607bb871439a18f49ba9249b457de0f9abf5be622a54366c0d0'
BASE_PREPARED_SHA='7203f085014b43145dd2cce05f9dda2a3207becb8a86063a7367cab2980f3de1'
BASE_DEPLOYED_SHA='32894ab51437e546c62c54a8a1759225abbca162f53128518286448927f4796a'
POST_PILOT_SHA='ba96ba62921742b7ed2dd82a4e3c57403f8036f3f94b4ab1cb6b6c1243e1d7d6'
BASE_NGINX_SHA='2d86ecea31b1ca0d83e4769b1d1ec423210b143ebfc7e4f62df997ffbc0a743e'
BASE_STATIC_SHA='40caed8025a42eba911568f7a970ea06546968c36bfcb5b1c14f5ff4bf34a1d7'
SCHEMA='f3c7d1a9b456'
SCHEMA_SHA='3633fa48c7b84ff585f600fa873e1c67bf4c80578715d9dd1d9cfcea709545d7'
ALLOWED_SOURCE_FILES={'app/frontend/src/lib/stripe-auto-posting.ts','app/frontend/src/components/StripeAutoPosting.tsx',
 'app/frontend/src/components/StripeHistoryReconciliation.tsx','app/frontend/tests/stripe-auto-posting.unit.test.mjs'}


def need(ok,code):
 if not ok:raise RuntimeError(code)


def safe_error(error):
 value=str(error)
 return value if re.fullmatch('[A-Z0-9_]+',value) else type(error).__name__.upper()


def compare_rows(before,after):
 need(set(before)==set(after) and len(before)==114,'EXACT_114_TABLES_REQUIRED')
 for table,row in before.items():
  if table=='stripe_history_scan_states':
   need(all(after[table][key]==row[key] for key in ('count','columns','schema','indexes')),'SCAN_CHECKPOINT_SHAPE_OR_COUNT_CHANGED')
  else:need(after[table]==row,'BUSINESS_ROWS_CHANGED_'+table.upper())
 return before['stripe_history_scan_states']!=after['stripe_history_scan_states']


class Publisher:
 def __init__(self,args):
  self.args=args
  body=(BASE_FOLDER/'release.py').read_bytes();need(H(body)==BASE_HELPER_SHA,'IMMUTABLE_BASE_HELPER_REQUIRED')
  self.ns={'__name__':'stripe_auto_timezone_static_primitives','__file__':str(BASE_FOLDER/'release.py')}
  exec(compile(body,self.ns['__file__'],'exec'),self.ns)
  old_args=SimpleNamespace(release=BASE_FOLDER,manifest_sha256=BASE_MANIFEST_SHA,payload_sha256=BASE_PAYLOAD_SHA,preflight=BASE_PREFLIGHT,preflight_sha256=BASE_PREFLIGHT_SHA,review_sha256=BASE_PREPARED_SHA)
  self.base=self.ns['Release'](old_args);self.m=self.base.m;m=self.m
  self.deployed=json.loads(m.read(BASE_FOLDER/'deployed.json',BASE_DEPLOYED_SHA))
  self.post=json.loads(m.read(args.release/'post-pilot-baseline.json',POST_PILOT_SHA))
  self.manifest=json.loads(m.read(args.release/'static-manifest.json',args.manifest_sha256))
  m.read(args.release/'static-payload.tar.gz',args.payload_sha256)
  self.validate_manifest()
  self.source=self.manifest['source_sha'];self.version=self.manifest['frontend_version']
  need(args.release==Path('/opt/t24-crm/releases/stripe-auto-timezone-'+self.source[:12]+'-20261021'),'EXACT_STATIC_RELEASE_PATH_REQUIRED')
  self.public=Path('/var/www/t24-crm-public/stripe-auto-timezone-'+self.source[:12]+'-20261021')
  # Keep m.SOURCE and m.SCOPE on the unchanged backend for runtime-label checks.
  m.PUBLIC=BASE_PUBLIC;m.BASELINE_FRONTEND=BASE_VERSION;m.FRONTEND_VERSION=self.version
  m.NGINX_SHA=BASE_NGINX_SHA;m.STATIC_SHA=BASE_STATIC_SHA;m.public_root=lambda:self.public

 def validate_manifest(self):
  v=self.manifest;p=self.post;a=self.args
  need(v['stage']=='STRIPE_AUTO_TIMEZONE_STATIC_PACKAGE' and re.fullmatch('[a-f0-9]{40}',v['source_sha']) and re.fullmatch('[a-f0-9]{12}',v['frontend_version']),'FROZEN_FRONTEND_SOURCE_REQUIRED')
  need(v['backend_source_sha']==BASE_SOURCE and v['previous_frontend_version']==BASE_VERSION and v['source_sha']!=BASE_SOURCE and v['frontend_version']!=BASE_VERSION,'EXACT_FRONTEND_ONLY_BASELINE_REQUIRED')
  need(set(v['changed_source_files'])==ALLOWED_SOURCE_FILES and all(re.fullmatch('[a-f0-9]{64}',value) for value in v['changed_source_files'].values()),'EXACT_TIMEZONE_SOURCE_SCOPE_REQUIRED')
  need(v['static_only'] is True and all(v[key] is False for key in ('backend_changes','database_changes','credentials_included','service_changes','environment_changes')),'STATIC_ONLY_SCOPE_REQUIRED')
  need(v['post_pilot_sha256']==POST_PILOT_SHA and v['payload_sha256']==a.payload_sha256,'EXACT_STATIC_PAYLOAD_AND_BASELINE_REQUIRED')
  need(v['base_deployed_sha256']==BASE_DEPLOYED_SHA and v['base_public_inventory_sha256']==BASE_STATIC_SHA and v['base_nginx_sha256']==BASE_NGINX_SHA,'EXACT_DEPLOYED_STATIC_PINS_REQUIRED')
  need(p['stage']=='STRIPE_AUTOMATIC_POSTING_POST_PILOT_READONLY_VERIFIED' and p['verified'] is True and p['source_sha']==BASE_SOURCE and p['frontend_version']==BASE_VERSION,'SUCCESSFUL_PILOT_BASELINE_REQUIRED')
  need(p['enabled_pilot_binding_ids']==[2,14,18] and p['enabled_pilot_count']==3 and p['payments']==191 and p['historical_pending_reviews']==26 and p['historical_postings']==0 and p['automatic_jobs']==0,'EXACT_THREE_PILOT_BASELINE_REQUIRED')
  need(all(p[key] is True for key in ('original_42_financial_tables_unchanged','customer_permissions_unchanged','commission_attribution_unchanged','private_runtime_unchanged','environment_network_mounts_unchanged','all_three_real_trials_passed','all_historical_reviews_excluded','original_history_audits_preserved')),'COMPLETE_PILOT_PROTECTION_PROOF_REQUIRED')
  need(p['crm']==self.deployed['crm'],'PILOT_DEPLOYED_RUNTIME_DRIFT')
  files=v['files'];need({'static/index.html','static/app-version.json'}<=set(files),'STATIC_ENTRYPOINTS_REQUIRED')
  need(all(name.startswith('static/') and self.m.static_path(name[7:]) and re.fullmatch('[a-f0-9]{64}',value) for name,value in files.items()),'STATIC_FILE_SCOPE_REJECTED')

 def common(self):
  m=self.m
  original=json.loads(m.read(BASE_FOLDER/'original-container.json'));live=m.inspect('t24-crm')
  need(live['State']['Running'] and m.runtime(live)==self.post['crm'],'UNCHANGED_BACKEND_RUNTIME_REQUIRED')
  m.verify_clone(live,original);m.verify_secret_mount(live);m.verify_production_worker_enabled(live)
  expected=json.loads(m.read(BASE_FOLDER/'backend-candidate-inventory.json',self.deployed['candidate_inventory_sha256']))
  need(m.inventory(live['Id'])==expected,'UNCHANGED_BACKEND_SOURCE_REQUIRED')
  need(m.schema_signature(m.BUSINESS,SCHEMA)==SCHEMA_SHA,'UNCHANGED_DATABASE_SCHEMA_REQUIRED')
  m.private_boundary(self.base.pins);need(m.credential_boundary()==self.base.proof['credential_boundary'],'STRIPE_CREDENTIAL_METADATA_DRIFT')
  m.ready(live['Id'])
  rows=m.sql_snapshot(m.BUSINESS)
  need(len(rows)==114 and rows['payments']['count']==191 and rows['stripe_history_invoice_reviews']['count']==26 and rows['stripe_history_postings']['count']==0 and rows['stripe_auto_posting_jobs']['count']==0,'PILOT_LEDGER_CHANGED_REVIEW_REQUIRED')
  compact=self.ns['snapshot_evidence'](rows)
  for table,baseline in self.base.proof['rows'].items():
   if table not in {'alembic_version','stripe_history_audits','stripe_history_scan_states'}:
    need(compact[table]==baseline,'ORIGINAL_ROW_CHANGED_'+table.upper())
  con=sqlite3.connect(f'file:{m.BUSINESS}?mode=ro',uri=True)
  try:
   con.execute('PRAGMA query_only=ON');con.execute('BEGIN')
   need([row[0] for row in con.execute('SELECT binding_id FROM stripe_auto_posting_policies WHERE enabled=1 ORDER BY binding_id')]==[2,14,18],'SELECTED_PILOT_POLICIES_CHANGED')
   for trial_text, in con.execute('SELECT trial FROM stripe_auto_posting_policies WHERE enabled=1'):
    trial=json.loads(trial_text);need(trial.get('passed') is True and sorted(trial.get('batch_ids') or [])==[2,14,18],'ENABLED_PILOT_TRIAL_CHANGED')
  finally:con.close()
  return rows,live

 def old_static(self):
  m=self.m
  need(m.static_boundary()==BASE_STATIC_SHA,'OLD_STATIC_BASELINE_DRIFT')

 def new_static(self,receipt):
  m=self.m
  need(m.digest(m.tree(BASE_PUBLIC))==BASE_STATIC_SHA,'OLD_PUBLIC_ASSETS_CHANGED')
  need(m.verify_public(self.public,self.manifest)==receipt['public_inventory_sha256'],'NEW_STATIC_INVENTORY_DRIFT')
  need(H(m.NGINX.read_bytes())==receipt['nginx_next_sha256'],'NEW_STATIC_ROOT_DRIFT')

 def prepare(self):
  m=self.m;a=self.args
  need(set(path.name for path in a.release.iterdir())=={'static_release.py','static-manifest.json','static-payload.tar.gz','post-pilot-baseline.json'},'FRESH_STATIC_STAGING_REQUIRED')
  before,live=self.common();self.old_static()
  # Retained extractor expects a generic payload.tar.gz; extract exact static members here.
  import io,tarfile
  seen=set()
  with tarfile.open(fileobj=io.BytesIO(m.read(a.release/'static-payload.tar.gz',a.payload_sha256)),mode='r:gz') as archive:
   for item in archive:
    need(item.isfile() and item.name in self.manifest['files'] and item.name not in seen and 0<=item.size<16*1024**2,'STATIC_PAYLOAD_MEMBER_REJECTED')
    body=archive.extractfile(item).read();need(H(body)==self.manifest['files'][item.name],'STATIC_PAYLOAD_HASH_DRIFT')
    target=a.release/item.name;target.parent.mkdir(parents=True,exist_ok=True,mode=0o700);need(target.parent.resolve()==target.parent,'STATIC_STAGE_LINK_REJECTED');m.write(target,body);seen.add(item.name)
  need(seen==set(self.manifest['files']),'STATIC_PAYLOAD_INCOMPLETE')
  root,static_sha=m.stage_public(a.release,self.manifest)
  nginx=m.NGINX.read_bytes();new_nginx=m.next_nginx(nginx)
  after,current=self.common();self.old_static();checkpoint=compare_rows(before,after)
  need(m.runtime(live)==m.runtime(current),'RUNTIME_CHANGED_DURING_STATIC_PREPARE')
  rows_sha=m.write(a.release/'prepared-before-rows.json',after)
  m.write(a.release/'nginx-before.conf',nginx)
  result={'stage':'STRIPE_AUTO_TIMEZONE_STATIC_PREPARED','source_sha':self.source,'backend_source_sha':BASE_SOURCE,'frontend_version':self.version,'previous_frontend_version':BASE_VERSION,'post_pilot_sha256':POST_PILOT_SHA,'base_deployed_sha256':BASE_DEPLOYED_SHA,'manifest_sha256':a.manifest_sha256,'payload_sha256':a.payload_sha256,'prepared_before_rows_sha256':rows_sha,'public_root':str(root),'public_inventory_sha256':static_sha,'nginx_next_sha256':H(new_nginx),'crm':m.runtime(live),'schema_revision':SCHEMA,'schema_sha256':SCHEMA_SHA,'selected_pilots':[2,14,18],'all_113_noncheckpoint_tables_unchanged':True,'daily_checkpoint_changed':checkpoint,'old_assets_preserved':True,'production_database_written':False,'services_changed':False,'credentials_used':False,'provider_requests':False}
  sha=m.write(a.release/'static-prepared.json',result);print(json.dumps({**result,'receipt_sha256':sha}))

 def reviewed(self):
  m=self.m;a=self.args
  need(bool(re.fullmatch('[a-f0-9]{64}',a.review_sha256 or '')),'INDEPENDENT_STATIC_PREPARED_REVIEW_REQUIRED')
  r=json.loads(m.read(a.release/'static-prepared.json',a.review_sha256))
  need(r['stage']=='STRIPE_AUTO_TIMEZONE_STATIC_PREPARED' and r['source_sha']==self.source and r['frontend_version']==self.version and r['backend_source_sha']==BASE_SOURCE,'STATIC_PREPARED_SOURCE_DRIFT')
  need(r['manifest_sha256']==a.manifest_sha256 and r['payload_sha256']==a.payload_sha256 and r['post_pilot_sha256']==POST_PILOT_SHA,'STATIC_PREPARED_IDENTITY_DRIFT')
  need(r['crm']==self.post['crm'] and r['schema_sha256']==SCHEMA_SHA and r['all_113_noncheckpoint_tables_unchanged'] is True and r['old_assets_preserved'] is True,'STATIC_PREPARED_BOUNDARY_DRIFT')
  need(all(r[key] is False for key in ('production_database_written','services_changed','credentials_used','provider_requests')),'STATIC_PREPARED_SIDE_EFFECT_REJECTED')
  need(m.verify_public(self.public,self.manifest)==r['public_inventory_sha256'],'REVIEWED_STATIC_FILES_DRIFT')
  before=json.loads(m.read(a.release/'prepared-before-rows.json',r['prepared_before_rows_sha256']))
  return r,before

 def rollback_root(self,receipt):
  m=self.m;a=self.args
  original=m.read(a.release/'nginx-before.conf',BASE_NGINX_SHA);changed=m.next_nginx(original)
  m.cleanup_nginx_temp(original,changed)
  current=m.NGINX.read_bytes()
  if current==changed:m.replace_nginx(changed,original);m.retained().reload_nginx()
  else:need(current==original,'UNKNOWN_NGINX_CHANGE_REQUIRES_REVIEW')
  need(H(m.NGINX.read_bytes())==BASE_NGINX_SHA and m.digest(m.tree(BASE_PUBLIC))==BASE_STATIC_SHA,'STATIC_ROOT_RECOVERY_FAILED')

 def activate(self):
  m=self.m;a=self.args;r,prepared_rows=self.reviewed()
  before,live=self.common();self.old_static();compare_rows(prepared_rows,before)
  need(not (a.release/'static-deployed.json').exists() and not (a.release/'static-activation-started.json').exists(),'FRESH_STATIC_ACTIVATION_REQUIRED')
  original=m.read(a.release/'nginx-before.conf',BASE_NGINX_SHA);changed=m.next_nginx(original)
  need(H(changed)==r['nginx_next_sha256'],'REVIEWED_NGINX_ROOT_REQUIRED')
  before_sha=m.write(a.release/'activation-before-rows.json',before)
  m.write(a.release/'static-activation-started.json',{'source_sha':self.source,'review_sha256':a.review_sha256,'nginx_next_sha256':r['nginx_next_sha256']})
  try:
   m.replace_nginx(original,changed);m.retained().reload_nginx();self.new_static(r)
   version=json.loads(m.run(['curl','-fsS','--max-time','20','https://t24-crm.com/app-version.json'],'PUBLIC_VERSION_READ_FAILED',25))
   need(version.get('version')==self.version,'PUBLIC_FRONTEND_VERSION_DRIFT')
   after,current=self.common();checkpoint=compare_rows(before,after)
   need(m.runtime(live)==m.runtime(current),'BACKEND_RUNTIME_CHANGED_DURING_STATIC_SWITCH')
   self.new_static(r);after_sha=m.write(a.release/'activation-after-rows.json',after)
   result={'stage':'STRIPE_AUTO_TIMEZONE_STATIC_DEPLOYED_VERIFIED','deployed':True,'source_sha':self.source,'backend_source_sha':BASE_SOURCE,'frontend_version':self.version,'previous_frontend_version':BASE_VERSION,'prepared_sha256':a.review_sha256,'post_pilot_sha256':POST_PILOT_SHA,'public_root':str(self.public),'public_inventory_sha256':r['public_inventory_sha256'],'nginx_sha256':r['nginx_next_sha256'],'crm':m.runtime(current),'schema_revision':SCHEMA,'schema_sha256':SCHEMA_SHA,'table_count':114,'selected_pilots':[2,14,18],'payments':191,'historical_pending_reviews':26,'historical_postings':0,'automatic_jobs':0,'all_113_noncheckpoint_tables_unchanged':True,'daily_checkpoint_changed':checkpoint,'before_rows_sha256':before_sha,'after_rows_sha256':after_sha,'backend_and_private_services_unchanged':True,'old_static_assets_preserved':True,'nginx_only_public_root_changed':True,'production_database_written':False,'database_restored':False,'credentials_used':False,'provider_requests':False}
   sha=m.write(a.release/'static-deployed.json',result);print(json.dumps({**result,'receipt_sha256':sha}))
  except BaseException as error:
   self.rollback_root(r)
   m.write(a.release/('static-root-rollback-'+str(time.time_ns())+'.json'),{'stage':'STRIPE_AUTO_TIMEZONE_STATIC_ROOT_ROLLED_BACK','source_sha':self.source,'reason':safe_error(error),'database_restored':False,'services_changed':False})
   raise

 def recover(self):
  r,_=self.reviewed();self.rollback_root(r)
  print(json.dumps({'stage':'STRIPE_AUTO_TIMEZONE_STATIC_ROOT_RECOVERED','deployed':False,'source_sha':self.source,'frontend_version':BASE_VERSION,'database_restored':False,'services_changed':False}))


def main():
 p=argparse.ArgumentParser();p.add_argument('--phase',choices=['prepare','activate','recover'],required=True);p.add_argument('--release',type=Path,required=True);p.add_argument('--manifest-sha256',required=True);p.add_argument('--payload-sha256',required=True);p.add_argument('--review-sha256');a=p.parse_args()
 need(os.geteuid()==0 and socket.gethostname()=='iZj6c4cj7edgnhdimts4l7Z','EXACT_SERVER_ROOT_REQUIRED');sys.dont_write_bytecode=True;os.umask(0o077)
 need(a.release.resolve()==a.release and a.release.parent==Path('/opt/t24-crm/releases'),'EXACT_PROTECTED_RELEASE_PATH_REQUIRED');info=a.release.lstat();need(stat.S_ISDIR(info.st_mode) and info.st_uid==0 and stat.S_IMODE(info.st_mode)==0o700,'PROTECTED_RELEASE_DIRECTORY_REQUIRED')
 need(all(re.fullmatch('[a-f0-9]{64}',value) for value in (a.manifest_sha256,a.payload_sha256)),'EXACT_ARTIFACT_HASH_PINS_REQUIRED')
 lock=os.open('/opt/t24-crm/releases/.stripe-autopost-release.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600);fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 getattr(Publisher(a),a.phase)()


if __name__=='__main__':
 try:main()
 except BaseException as error:
  print(json.dumps({'stage':'STRIPE_AUTO_TIMEZONE_STATIC_RELEASE_REJECTED','code':safe_error(error),'database_restored':False,'services_changed':False}));sys.exit(1)
