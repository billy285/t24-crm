"""Generate, never execute, a bounded pinned aggregate-only postflight."""
import argparse,base64,hashlib,json,os,stat,zlib
from pathlib import Path
HERE=Path(__file__).resolve().parent
H=lambda b:hashlib.sha256(b).hexdigest()
def need(ok,code):
    if not ok:raise RuntimeError(code)
def main():
    p=argparse.ArgumentParser();p.add_argument('--deployed-receipt',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();value=json.loads(a.deployed_receipt.read_text());marker=value.pop('receipt_sha256');canonical=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode();need(marker==H(canonical) and value['stage']=='MEDIA_UNIFIED_SETTINGS_DEPLOYED' and value['source_sha']=='54e027aad00e81a4ebb747ada1299e7a10e1ec52' and value['schema_revision']=='i54af678a914' and value['table_count']==169 and value['all165_rows_sequences_preserved_before_start'] is True and value['post_start_live_business_rows_frozen'] is False,'EXACT_CANONICAL_DEPLOYMENT_REQUIRED')
    path=HERE/'postflight.py';before=path.lstat();need(path.resolve()==path and stat.S_ISREG(before.st_mode) and before.st_nlink==1 and 0<before.st_size<65536,'CANONICAL_POSTFLIGHT_SOURCE_REQUIRED');fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as f:opened=os.fstat(f.fileno());body=f.read(65537)
    identity=lambda r:(r.st_dev,r.st_ino,r.st_size,r.st_mode,r.st_nlink,r.st_mtime_ns,r.st_ctime_ns);need(identity(before)==identity(opened)==identity(path.lstat()) and len(body)==before.st_size,'POSTFLIGHT_SOURCE_CHANGED');sha=H(body);payload=base64.b64encode(zlib.compress(body,9)).decode()
    command="""#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'POSTFLIGHT'
import base64,hashlib,sys,zlib
payload=%r
expected=%r
d=zlib.decompressobj();body=d.decompress(base64.b64decode(payload,validate=True),65537)
if len(body)>65536 or not d.eof or d.unused_data or d.unconsumed_tail or hashlib.sha256(body).hexdigest()!=expected:raise RuntimeError('EXACT_REVIEWED_POSTFLIGHT_REQUIRED')
sys.argv=['reviewed-readonly-postflight','--deployed-sha256',%r]
exec(compile(body,'<reviewed-aggregate-only-postflight>','exec'),{'__name__':'__main__'})
POSTFLIGHT
"""%(payload,sha,marker)
    need(len(command.encode())<14000,'BOUNDED_POSTFLIGHT_COMMAND_REQUIRED');a.out.mkdir(parents=True,exist_ok=True);pins={'postflight_sha256':sha,'postflight_bytes':len(body),'deployed_sha256':marker,'command_sha256':H(command.encode()),'command_bytes':len(command.encode()),'business_writes':False,'provider_requests':False,'runtime_mutations':False,'executed':False}
    for name,data in (('postflight-command.sh',command.encode()),('command-pins.json',(json.dumps(pins,sort_keys=True,indent=2)+'\n').encode())):
        fd=os.open(a.out/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
    print(json.dumps(pins,sort_keys=True))
if __name__=='__main__':main()
