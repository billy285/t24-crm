"""Generate the reviewed zero-policy worker prepare+enable invocation."""
import argparse,hashlib,importlib.util,json,os
from pathlib import Path
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('_quick_worker_commands',HERE/'make_commands.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def main():
    p=argparse.ArgumentParser();p.add_argument('--carrier',required=True);p.add_argument('--main-deployed-receipt',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    summary=m.strict_json(m.local_bytes(HERE/'preflight-current.json'));prepared=m.canonical_prepared(m.local_bytes(HERE/'prepared-envelope.json'));deployed=m.canonical_prepared(m.local_bytes(a.main_deployed_receipt));commands,pins=m.generate_worker(a.carrier,summary,prepared,deployed)
    body=commands['worker-prepare-command.sh'];old="'--phase', 'prepare',";m.r.need(body.count(old)==1,'EXACT_REVIEWED_PREPARE_ARGUMENT_REQUIRED');body=body.replace(old,"'--phase', 'prepare_activate',",1);m.r.need(len(body.encode())<11000,'BOUNDED_SINGLE_WORKER_WRAPPER_REQUIRED')
    pins={**pins,'prepare_and_activate_in_one_reviewed_invocation':True,'command_sha256':hashlib.sha256(body.encode()).hexdigest(),'command_bytes':len(body.encode()),'executed':False};a.out.mkdir(parents=True,exist_ok=True)
    for name,data in (('worker-enable-command.sh',body.encode()),('command-pins.json',(json.dumps(pins,sort_keys=True,indent=2)+'\n').encode())):
        fd=os.open(a.out/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
    print(json.dumps(pins,sort_keys=True))
if __name__=='__main__':main()
