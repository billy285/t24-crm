"""Generate exact immutable-download prepare and receipt-gated static activation."""
import argparse,hashlib,json,re,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parent
H=lambda b:hashlib.sha256(b).hexdigest()
def need(v,c):
 if not v:raise RuntimeError(c)
def main(a):
 need(bool(re.fullmatch('[a-f0-9]{40}',a.carrier)),'FULL_IMMUTABLE_CARRIER_REQUIRED')
 manifest=json.loads((ROOT/'artifacts/manifest.json').read_text());source=manifest['source_sha'];release='/opt/t24-crm/releases/mobile-spacing-'+source[:12]+'-20261025'
 need(subprocess.check_output(['git','rev-parse',a.carrier+':app'])==subprocess.check_output(['git','rev-parse',source+':app']),'CARRIER_APPLICATION_TREE_DIFFERS_FROM_REVIEWED_SOURCE')
 members={'baseline.py':'baseline.py','static_release.py':'static_release.py','artifacts/baseline.json':'baseline.json','artifacts/manifest.json':'manifest.json','artifacts/payload.tar.gz':'payload.tar.gz'}
 pins={}
 for name,target in members.items():
  local=ROOT/name;body=local.read_bytes();relative=str(local.relative_to(Path.cwd()))
  need(subprocess.check_output(['git','show',a.carrier+':'+relative])==body,'CARRIER_MEMBER_BYTES_DIFFER')
  pins[target]={'url':'https://raw.githubusercontent.com/billy285/t24-crm/'+a.carrier+'/'+relative,'sha256':H(body),'bytes':len(body)}
 args=['--release',release,'--module-sha256',pins['baseline.py']['sha256'],'--baseline-sha256',pins['baseline.json']['sha256'],'--manifest-sha256',pins['manifest.json']['sha256'],'--payload-sha256',pins['payload.tar.gz']['sha256']]
 def command(phase,review=None):
  payload={'release':release,'phase':phase,'files':pins,'args':['--phase',phase,*args]+(['--review-sha256',review] if review else [])}
  code="""import hashlib,json,os,pathlib,socket,stat,sys,urllib.request
p=PAYLOAD
assert os.geteuid()==0 and socket.gethostname()=='iZj6c4cj7edgnhdimts4l7Z','EXACT_SERVER_ROOT_REQUIRED'
os.umask(0o077);root=pathlib.Path(p['release'])
assert root.resolve()==root and root.parent==pathlib.Path('/opt/t24-crm/releases'),'EXACT_RELEASE_PATH_REQUIRED'
if p['phase']=='prepare':
 root.mkdir(mode=0o700)
 for name,pin in p['files'].items():
  body=urllib.request.urlopen(pin['url'],timeout=60).read(pin['bytes']+1)
  assert len(body)==pin['bytes'] and hashlib.sha256(body).hexdigest()==pin['sha256'],'IMMUTABLE_DOWNLOAD_MISMATCH'
  fd=os.open(root/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'wb') as f:f.write(body)
for name,pin in p['files'].items():
 path=root/name;s=path.lstat()
 assert path.resolve()==path and stat.S_ISREG(s.st_mode) and s.st_uid==0 and s.st_nlink==1 and not s.st_mode&0o077,'ROOT_PRIVATE_FILE_REQUIRED'
 body=path.read_bytes();assert len(body)==pin['bytes'] and hashlib.sha256(body).hexdigest()==pin['sha256'],'FROZEN_RELEASE_FILE_MISMATCH'
os.execv(sys.executable,[sys.executable,str(root/'static_release.py'),*p['args']])
""".replace('PAYLOAD',repr(payload),1)
  return "#!/bin/sh\npython3 - <<'T24_MOBILE_STATIC'\n"+code+'\nT24_MOBILE_STATIC\n'
 a.out.mkdir(parents=True,exist_ok=True);(a.out/'prepare-command.sh').write_text(command('prepare'))
 if a.prepared:
  body=a.prepared.read_bytes();r=json.loads(body)
  need(r['stage']=='MOBILE_SPACING_STATIC_PREPARED' and all(r[k]==v for k,v in {'source_sha':source,'frontend_version':manifest['frontend_version'],'baseline_sha256':pins['baseline.json']['sha256'],'manifest_sha256':pins['manifest.json']['sha256'],'payload_sha256':pins['payload.tar.gz']['sha256'],'runtime_and_schema_identity_unchanged':True,'old_assets_preserved':True,'database_mutations':False,'services_modified':False,'provider_requests':False}.items()),'ACTUAL_PREPARED_RECEIPT_REQUIRED')
  need(bool(re.fullmatch('[a-f0-9]{64}',r['nginx_next_sha256'])) and bool(re.fullmatch('[a-f0-9]{64}',r['public_inventory_sha256'])),'PREPARED_STATIC_HASHES_REQUIRED')
  for phase in ('activate','recover'):(a.out/(phase+'-command.sh')).write_text(command(phase,H(body)))
 (a.out/'pins.json').write_text(json.dumps({'carrier':a.carrier,'source_sha':source,'frontend_version':manifest['frontend_version'],'release':release,'files':pins},sort_keys=True,indent=2)+'\n')
 print(json.dumps({'commands':str(a.out),'source_sha':source,'frontend_version':manifest['frontend_version'],'activate_generated':bool(a.prepared)}))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--carrier',required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--prepared',type=Path);main(p.parse_args())
