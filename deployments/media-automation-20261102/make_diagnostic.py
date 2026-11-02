"""Generate a bounded inline reviewed read-only diagnosis; do not execute."""
import argparse,base64,hashlib,json,os,zlib
from pathlib import Path
HERE=Path(__file__).resolve().parent
H=lambda b:hashlib.sha256(b).hexdigest()
def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();path=HERE/'diagnose.py';body=path.read_bytes();need=lambda x:None if x else (_ for _ in ()).throw(RuntimeError('CANONICAL_BOUNDED_DIAGNOSIS_REQUIRED'))
    need(path.resolve()==path and path.is_file() and not path.is_symlink() and path.stat().st_nlink==1 and 0<len(body)<65536);payload=base64.b64encode(zlib.compress(body,9)).decode();sha=H(body)
    command="""#!/bin/bash
set -eu
sudo python3 -I -S -B - <<'DIAGNOSE'
import base64,hashlib,zlib
payload=%r
expected=%r
d=zlib.decompressobj();body=d.decompress(base64.b64decode(payload,validate=True),65537)
if len(body)>65536 or not d.eof or d.unused_data or d.unconsumed_tail or hashlib.sha256(body).hexdigest()!=expected:raise RuntimeError('EXACT_REVIEWED_DIAGNOSIS_REQUIRED')
exec(compile(body,'<reviewed-read-only-media-automation-diagnosis>','exec'),{'__name__':'__main__'})
DIAGNOSE
"""%(payload,sha)
    need(len(command.encode())<14000);a.out.mkdir(parents=True,exist_ok=True);pins={'diagnosis_sha256':sha,'diagnosis_bytes':len(body),'command_sha256':H(command.encode()),'command_bytes':len(command.encode()),'executed':False,'business_rows_written':False,'provider_requests':False,'existing_files_changed':False}
    for name,data in (('diagnose-command.sh',command.encode()),('diagnose-pins.json',(json.dumps(pins,sort_keys=True,indent=2)+'\n').encode())):
        fd=os.open(a.out/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
    print(json.dumps(pins,sort_keys=True))
if __name__=='__main__':main()
