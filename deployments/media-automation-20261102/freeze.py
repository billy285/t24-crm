"""Pin only a committed scoped application and its reviewed static build."""
import argparse,hashlib,importlib.util,json,os,re
from pathlib import Path
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('_automation_freeze_package',HERE/'build_payload.py');b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
H=lambda v:hashlib.sha256(v).hexdigest()
def pin(path,values):
    text=path.read_text()
    for name,value in values.items():
        pattern=r'^'+re.escape(name)+r'\s*=.*$';b.need(len(list(re.finditer(pattern,text,re.M)))==1,'EXACT_SINGLE_PIN_ASSIGNMENT_REQUIRED');text=re.sub(pattern,name+' = '+repr(value),text,count=1,flags=re.M)
    compile(text,str(path),'exec');return text
def freeze(source,summary,dist):
    b.validate_summary(summary);before,after,changed=b.committed_sources(source);r=b.release_module();b.need(source not in {r.BASE_SOURCE,r.BASE_STATIC_SOURCE},'NEW_APPLICATION_COMMIT_REQUIRED')
    version=b.frontend_version();static=b.read_static(dist);b.need(b.strict_json(static['app-version.json'])=={'version':version},'CURRENT_REVIEWED_FRONTEND_BUILD_REQUIRED')
    hashes={n:after[n] for n in sorted(changed)};old={n:before.get('app/backend/'+n) for n in sorted(b.BACKEND_SCOPE)};new={n:after['app/backend/'+n] for n in sorted(b.BACKEND_SCOPE)}
    value={'stage':'MEDIA_AUTOMATION_APPLICATION_FREEZE','source_sha':source,'frontend_version':version,'baseline_source_sha':r.BASE_SOURCE,'baseline_static_source_sha':b.APP_BASELINE,'old_schema_revision':r.OLD_REVISION,'schema_revision':r.NEW_REVISION,'files':hashes,'dist_inventory_sha256':b.static_inventory(static),'preflight_sha256':summary['sha256'],'provider_requests':False,'production_seed_rows':False,'automation_worker_enabled':False}
    body=b.encoded(value);sha=H(body);common={'SOURCE_SHA':source,'FRONTEND':version,'APPLICATION_FREEZE_SHA':sha,'PREFLIGHT_SHA':summary['sha256'],'BACKEND_BEFORE':old,'BACKEND_AFTER':new,'CHANGED_SOURCE_HASHES':hashes}
    prepared={HERE/'release.py':pin(HERE/'release.py',common),HERE/'build_payload.py':pin(HERE/'build_payload.py',common)};target=HERE/'application-freeze.json';b.need(not target.exists() and not target.is_symlink(),'FRESH_FREEZE_REQUIRED')
    fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as f:f.write(body);f.flush();os.fsync(f.fileno())
    for path,text in prepared.items():path.write_text(text)
    return {'source_sha':source,'frontend_version':version,'application_freeze_sha256':sha,'changed_source_count':len(changed),'provider_requests':False,'deployment_performed':False}
def main():
    p=argparse.ArgumentParser();p.add_argument('--source-sha',required=True);p.add_argument('--preflight-summary',type=Path,required=True);p.add_argument('--dist',type=Path,default=b.ROOT/'app/frontend/dist');a=p.parse_args();print(json.dumps(freeze(a.source_sha,b.strict_json(b.local_bytes(a.preflight_summary,1048576)),a.dist),sort_keys=True))
if __name__=='__main__':main()
