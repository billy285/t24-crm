"""Freeze an exact committed navigation CSS fix and a matching reviewed build."""
import argparse,hashlib,importlib.util,json,os,re
from pathlib import Path
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('_navigation_freezer',HERE/'build_payload.py');b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
H=lambda x:hashlib.sha256(x).hexdigest()
def pin(path,values):
    text=path.read_text()
    for name,value in values.items():
        pattern=r'^'+re.escape(name)+r'\s*=.*$';b.need(len(list(re.finditer(pattern,text,re.M)))==1,'EXACT_SINGLE_RELEASE_PIN_REQUIRED')
        text=re.sub(pattern,name+'='+repr(value),text,count=1,flags=re.M)
    compile(text,str(path),'exec');return text

def freeze(source,summary,dist):
    b.need(isinstance(source,str) and re.fullmatch('[a-f0-9]{40}',source) and source!=b.BASE_SOURCE,'EXACT_NEW_COMMITTED_SOURCE_REQUIRED')
    b.need(b.git('rev-parse','--verify',source+'^{commit}',maximum=100).decode().strip()==source,'EXACT_APPLICATION_COMMIT_REQUIRED')
    b.need(b.git('rev-parse','HEAD:app',maximum=100)==b.git('rev-parse',source+':app',maximum=100),'CURRENT_COMMITTED_APP_REQUIRED')
    b.PREFLIGHT_SHA=summary['sha256'];b.validate_summary(summary)
    before,after=b.inventory(b.BASE_SOURCE),b.inventory(source)
    changed={name for name in before.keys()|after.keys() if before.get(name)!=after.get(name)}
    b.need(changed==b.FILES and set(before)==set(after),'EXACT_PRIORITY_COMPONENT_AND_TEST_DELTA_REQUIRED')
    b.need(all(H(b.local_bytes(b.ROOT/name))==sha for name,sha in after.items()),'COMMITTED_SOURCE_DRIFT')
    version=b.frontend_version();static=b.read_static(dist);b.need(b.strict_json(static['app-version.json'])=={'version':version},'MATCHING_REVIEWED_DIST_REQUIRED')
    changed_files={name:after[name] for name in sorted(changed)}
    value={'stage':'MEDIA_NAVIGATION_STICKY_APPLICATION_FREEZE','source_sha':source,'baseline_source_sha':b.BASE_SOURCE,'frontend_version':version,'baseline_frontend_version':b.BASE_FRONTEND,'files':changed_files,'dist_inventory_sha256':b.static_inventory(static),'preflight_sha256':summary['sha256'],**{x:True for x in b.TRUE_FLAGS},**{x:False for x in b.FALSE_FLAGS}}
    body=b.encoded(value);sha=H(body)
    replacements={HERE/'release.py':pin(HERE/'release.py',{'SOURCE_SHA':source,'FRONTEND':version,'PREFLIGHT_SHA':summary['sha256'],'APPLICATION_FREEZE_SHA':sha,'CHANGED_SOURCE_HASHES':changed_files}),HERE/'build_payload.py':pin(HERE/'build_payload.py',{'SOURCE':source,'FRONTEND':version,'PREFLIGHT_SHA':summary['sha256'],'APPLICATION_FREEZE_SHA':sha})}
    target=HERE/'application-freeze.json';b.need(not target.exists() and not target.is_symlink(),'FRESH_APPLICATION_FREEZE_REQUIRED')
    fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as f:f.write(body);f.flush();os.fsync(f.fileno())
    for path,text in replacements.items():path.write_text(text)
    return {'source_sha':source,'frontend_version':version,'application_freeze_sha256':sha,'dist_inventory_sha256':value['dist_inventory_sha256'],'changed_source_files':changed_files,'deployment_performed':False}
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source-sha',required=True);parser.add_argument('--preflight-summary',type=Path,required=True);parser.add_argument('--dist',type=Path,default=b.ROOT/'app/frontend/dist');args=parser.parse_args()
    print(json.dumps(freeze(args.source_sha,b.strict_json(b.local_bytes(args.preflight_summary)),args.dist),sort_keys=True))
if __name__=='__main__':main()
