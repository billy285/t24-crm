"""Local-only generator for root's immutable frontend-only artifact commit."""
import argparse,hashlib,json,re
from pathlib import Path

SOURCE='30d9748a43f7a5d021968b2bc69704172b6487c4'
VERSION='54da68143ed2'
RELEASE='/opt/t24-crm/releases/ads-health-responsive-30d9748-20261011'
ROOT=Path(__file__).resolve().parent
DEPLOY_PATH='deployments/ads-health-responsive-20261011'

def generate(artifact_commit):
    assert re.fullmatch('[a-f0-9]{40}',artifact_commit) and re.fullmatch('[a-f0-9]{40}',SOURCE) and re.fullmatch('[a-f0-9]{12}',VERSION) and '__' not in RELEASE,'REVIEWED_PINS_REQUIRED'
    files={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ('static_only_upgrade.py','static-manifest.json','static-payload.tar.gz')}
    manifest=json.loads((ROOT/'static-manifest.json').read_bytes())
    assert manifest['source_sha']==SOURCE and manifest['frontend_version']==VERSION and manifest['static_only'] is True and manifest['backend_changes'] is False and manifest['credentials_included'] is False and manifest['payload_sha256']==files['static-payload.tar.gz'],'STATIC_PAYLOAD_SCOPE_REQUIRED'
    return '''#!/bin/bash
set -euo pipefail
umask 077
python3 - <<'PYSTATIC'
import hashlib,os,socket,subprocess,urllib.request
from pathlib import Path
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None
assert os.geteuid()==0 and socket.gethostname()=='iZj6c4cj7edgnhdimts4l7Z','SERVER_IDENTITY_REQUIRED'
r=Path('''+repr(RELEASE)+''')
assert not r.exists() and not r.is_symlink(),'NEW_RELEASE_REQUIRED'
assert r.parent.is_dir() and not r.parent.is_symlink() and r.parent.resolve()==r.parent and r.parent.stat().st_uid==0 and not r.parent.stat().st_mode & 0o022,'PROTECTED_RELEASE_PARENT_REQUIRED'
r.mkdir(mode=0o700)
base='https://raw.githubusercontent.com/billy285/t24-crm/'''+artifact_commit+'/'+DEPLOY_PATH+'''/'
files='''+repr(files)+'''
opener=urllib.request.build_opener(NoRedirect())
for name,expected in files.items():
    with opener.open(base+name,timeout=45) as reply:
        assert reply.status==200,'PINNED_STATIC_ARTIFACT_HTTP_FAILED'
        data=reply.read(8*1024*1024+1)
    assert len(data)<=8*1024*1024 and hashlib.sha256(data).hexdigest()==expected,'STATIC_ARTIFACT_HASH_REQUIRED'
    fd=os.open(r/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
print('ADS_HEALTH_STATIC_ARTIFACTS_VERIFIED',flush=True)
result=subprocess.run(['python3',str(r/'static_only_upgrade.py'),'--execute','--manifest-sha256',files['static-manifest.json']],cwd=r)
raise SystemExit(result.returncode)
PYSTATIC
'''

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--artifact-commit',required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();source=generate(args.artifact_commit)
    assert not args.output.exists(),'NEW_COMMAND_REQUIRED'
    args.output.write_text(source);args.output.chmod(0o600)
    print(json.dumps({'command_path':str(args.output.resolve()),'command_sha256':hashlib.sha256(source.encode()).hexdigest(),'server_executed':False}))
