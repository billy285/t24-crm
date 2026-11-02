"""Freeze one explicit app commit and reviewed build, never deploy."""
import argparse,hashlib,importlib.util,json,os,re
from pathlib import Path
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('_unified_freeze_package',HERE/'build_payload.py');b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
def pin(path,values):
    text=path.read_text()
    for name,value in values.items():
        pattern=r'^'+re.escape(name)+r'\s*=.*$';b.need(len(list(re.finditer(pattern,text,re.M)))==1,'EXACT_SINGLE_PIN_ASSIGNMENT_REQUIRED');text=re.sub(pattern,name+' = '+repr(value),text,count=1,flags=re.M)
    compile(text,str(path),'exec');return text
def freeze(source,summary,dist):
    b.validate_summary(summary);before,after,changed=b.committed_sources(source);static=b.read_static(dist);version=b.frontend_version();b.need(b.strict_json(static['app-version.json'])=={'version':version},'EXACT_REVIEWED_DIST_REQUIRED');files={n:after[n] for n in sorted(changed)};old={n:before.get('app/backend/'+n) for n in sorted(b.BACKEND_SCOPE)};new={n:after['app/backend/'+n] for n in sorted(b.BACKEND_SCOPE)};value={'stage':'MEDIA_UNIFIED_SETTINGS_APPLICATION_FREEZE','source_sha':source,'frontend_version':version,'source_files':files,'preflight_sha256':summary['sha256'],'dist_inventory_sha256':b.static_inventory(static),'old_schema_revision':'h43fe567f803','schema_revision':'i54af678a914','new_empty_table_count':4,'flags_changed':False,'business_seed_rows':False,'provider_requests':False};body=b.encoded(value);sha=hashlib.sha256(body).hexdigest();pins={'SOURCE_SHA':source,'FRONTEND':version,'PREFLIGHT_SHA':summary['sha256'],'FREEZE_SHA':sha,'BACKEND_BEFORE':old,'BACKEND_AFTER':new,'SOURCE_FILES':files};prepared={HERE/'release.py':pin(HERE/'release.py',pins),HERE/'build_payload.py':pin(HERE/'build_payload.py',pins)};target=HERE/'application-freeze.json';b.need(not target.exists() and not target.is_symlink(),'FRESH_FREEZE_REQUIRED');fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as f:f.write(body);f.flush();os.fsync(f.fileno())
    for path,text in prepared.items():path.write_text(text)
    return {'source_sha':source,'frontend_version':version,'freeze_sha256':sha,'application_delta_count':len(changed),'runtime_overlay_count':len(b.BACKEND_SCOPE),'production_writes':False,'deployment_performed':False}
def main():
    p=argparse.ArgumentParser();p.add_argument('--source-sha',required=True);p.add_argument('--baseline-summary',type=Path,required=True);p.add_argument('--dist',type=Path,default=b.ROOT/'app/frontend/dist');a=p.parse_args();print(json.dumps(freeze(a.source_sha,b.strict_json(b.local_bytes(a.baseline_summary,1048576)),a.dist),sort_keys=True))
if __name__=='__main__':main()
