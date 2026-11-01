"""Freeze one committed application tree and reviewed local build, no deployment.

The input commit is explicit. This helper only writes this release's source pins
and a fresh local freeze receipt; it never builds, installs or calls a service.
"""
import argparse,hashlib,importlib.util,json,os,re
from pathlib import Path
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('_scale_package_freezer',HERE/'build_payload.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
H=lambda x:hashlib.sha256(x).hexdigest()

def pin(path,values):
    text=path.read_text()
    for name,value in values.items():
        pattern=r'^'+re.escape(name)+r'\s*=.*$'
        matches=list(re.finditer(pattern,text,re.M));b.need(len(matches)==1,'EXACT_SINGLE_RELEASE_PIN_ASSIGNMENT_REQUIRED')
        text=re.sub(pattern,name+' = '+repr(value),text,count=1,flags=re.M)
    compile(text,str(path),'exec');return text

def freeze(source,summary,dist):
    b.need(re.fullmatch('[a-f0-9]{40}',source or '') and source not in {b.BASE_SOURCE,b.APP_BASELINE},'EXPLICIT_NEW_IMMUTABLE_APPLICATION_REQUIRED')
    b.need(b.git('rev-parse','--verify',source+'^{commit}',maximum=100).decode().strip()==source,'EXACT_APPLICATION_COMMIT_REQUIRED')
    b.need(b.git('rev-parse','HEAD:app',maximum=100)==b.git('rev-parse',source+':app',maximum=100),'CURRENT_COMMITTED_APPLICATION_TREE_REQUIRED')
    b.need(re.fullmatch('[a-f0-9]{64}',summary.get('sha256','')) and summary['stage']=='MEDIA_WORKSPACE_PRIORITY_PREFLIGHT_CAPTURED','ACTUAL_SCALE_PREFLIGHT_SUMMARY_REQUIRED')
    b.PREFLIGHT_SHA=summary['sha256'];b.validate_summary(summary)
    before,after=b.inventory(b.APP_BASELINE),b.inventory(source)
    changed={name for name in before.keys()|after.keys() if before.get(name)!=after.get(name)}
    b.need(changed==b.SOURCE_FILES and set(before)<=set(after),'EXACT_SCOPED_APPLICATION_DELTA_REQUIRED')
    for name,sha in after.items():b.need(H(b.local_bytes(b.ROOT/name))==sha,'CURRENT_APPLICATION_SOURCE_DRIFT')
    b.need({name:before['app/backend/'+name] for name in b.BACKEND_FILES}==b.BACKEND_BEFORE,'EXACT_DEPLOYED_BACKEND_BEFORE_REQUIRED')
    version=b.frontend_version();static=b.read_static(dist);b.need(b.strict_json(static['app-version.json'])=={'version':version},'EXACT_REVIEWED_CURRENT_FRONTEND_BUILD_REQUIRED')
    value={'stage':'MEDIA_WORKSPACE_REVIEW_MONTH_APPLICATION_FREEZE','source_sha':source,'frontend_version':version,'baseline_source_sha':b.BASE_SOURCE,'baseline_static_source_sha':b.APP_BASELINE,'baseline_frontend_version':b.BASE_FRONTEND,'schema_revision':b.SCHEMA_REVISION,'old_schema_revision':b.SCHEMA_REVISION,'dist_inventory_sha256':b.static_inventory(static),'preflight_sha256':summary['sha256'],'files':{name:after[name] for name in sorted(changed)},**{key:True for key in b.TRUE_FLAGS},**{key:False for key in b.FALSE_FLAGS}}
    body=b.encoded(value);sha=H(body)
    backend={name:after['app/backend/'+name] for name in sorted(b.BACKEND_FILES)}
    prepared={HERE/'release.py':pin(HERE/'release.py',{'SOURCE_SHA':source,'FRONTEND':version,'APPLICATION_FREEZE_SHA':sha,'ACTUAL_PREFLIGHT_SHA':summary['sha256'],'FINAL_BACKEND_HASHES':backend}),HERE/'build_payload.py':pin(HERE/'build_payload.py',{'SOURCE_SHA':source,'FRONTEND':version,'APPLICATION_FREEZE_SHA':sha,'PREFLIGHT_SHA':summary['sha256'],'BACKEND_AFTER':backend})}
    target=HERE/'application-freeze.json';b.need(not target.exists() and not target.is_symlink(),'FRESH_APPLICATION_FREEZE_REQUIRED')
    fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as f:f.write(body);f.flush();os.fsync(f.fileno())
    for path,text in prepared.items():path.write_text(text)
    return {'source_sha':source,'frontend_version':version,'application_freeze_sha256':sha,'dist_inventory_sha256':value['dist_inventory_sha256'],'changed_source_files':sorted(changed),'backend_after':backend,'provider_requests':False,'database_writes':False,'deployment_performed':False}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source-sha',required=True);parser.add_argument('--preflight-summary',type=Path,required=True);parser.add_argument('--dist',type=Path,default=b.ROOT/'app/frontend/dist');args=parser.parse_args()
    print(json.dumps(freeze(args.source_sha,b.strict_json(b.local_bytes(args.preflight_summary,1048576)),args.dist),sort_keys=True))
if __name__=='__main__':main()
