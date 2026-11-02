"""Exact scoped static packaging rejects backend/private/uncommitted drift."""
import copy,importlib.util,io,json,tarfile
from pathlib import Path
import pytest
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('_priority_package_test',HERE/'build_payload.py');b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
@pytest.fixture
def candidate(tmp_path,monkeypatch):
    root=tmp_path/'repo';root.mkdir();before={};after={}
    for name in b.FILES:
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'REVIEWED_PRIORITY_FIX')
        before[name]=b.H(b'BASELINE');after[name]=b.H(path.read_bytes())
    for name in ['app/frontend/src/private.css','app/backend/stable.py']:
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'UNCHANGED_SOURCE')
        before[name]=after[name]=b.H(path.read_bytes())
    monkeypatch.setattr(b,'ROOT',root);monkeypatch.setattr(b,'SOURCE','a'*40);monkeypatch.setattr(b,'FRONTEND','a'*12)
    monkeypatch.setattr(b,'inventory',lambda ref:copy.deepcopy(before if ref==b.BASE_SOURCE else after));monkeypatch.setattr(b,'frontend_version',lambda:b.FRONTEND);monkeypatch.setattr(b,'PREFLIGHT_SHA','d'*64)
    dist=root/'app/frontend/dist';(dist/'assets').mkdir(parents=True);(dist/'app-version.json').write_text(json.dumps({'version':b.FRONTEND}));(dist/'index.html').write_bytes(b'<html>synthetic</html>');(dist/'assets/test.js').write_bytes(b'/*reviewed static UI only*/')
    freeze={'source_sha':b.SOURCE,'baseline_source_sha':b.BASE_SOURCE,'frontend_version':b.FRONTEND,'baseline_frontend_version':b.BASE_FRONTEND,'files':{name:after[name] for name in b.FILES},'dist_inventory_sha256':b.static_inventory(b.read_static(dist)),**{x:True for x in b.TRUE_FLAGS},**{x:False for x in b.FALSE_FLAGS}}
    body=b.encoded(freeze);monkeypatch.setattr(b,'APPLICATION_FREEZE_SHA',b.H(body))
    summary={'stage':'MEDIA_NAVIGATION_STICKY_BASELINE_CAPTURED','sha256':'d'*64,'path':'/opt/t24-crm/releases/media-navigation-sticky-baseline-'+'d'*12+'.json','source_sha':b.BASE_SOURCE,'frontend_version':b.BASE_FRONTEND,'schema_revision':'i54af678a914','table_count':169,'backend_file_count':432,'old_flags_preserved':True,'crm':{'config':'e910c0852b1a2dbe12474ed55040544feb85dc3dfd037ef603c94d86bea5b84a','id':'6f826ade371a37fbf405c2e90ee405abb4e7d5ad5c9344139cb65a46596e5757','image':'sha256:1b6caabf90c809def8e180811336ebdc12e49305ad0f11bf4126730790d09bee','restart':0,'started':'2026-11-02T07:13:16.110095163Z'},'content_security_policy_sha256':'ead64b09efe8c4f35648aa8eafe8855c5268ecf0999e0918b3642dd9dfbfe7a6',**{x:False for x in ('schema_changed','business_writes','provider_requests','credentials_exported','private_content_exported','runtime_changed','business_rows_read_or_frozen')}}
    return root,dist,before,after,summary,freeze,body

def test_exact_deterministic_two_file_ui_fix_static_only_all_other_sources_protected(candidate):
    root,dist,before,after,summary,freeze,body=candidate
    blob,manifest=b.build(summary,body,dist);again,other=b.build(summary,body,dist)
    assert blob==again and manifest==other
    assert manifest['changed_source_files']=={name:after[name] for name in b.FILES}
    assert manifest['protected_source_inventory']=={name:sha for name,sha in before.items() if name not in b.FILES}
    assert all(manifest[x] is True for x in b.TRUE_FLAGS) and all(manifest[x] is False for x in b.FALSE_FLAGS)
    with tarfile.open(fileobj=io.BytesIO(blob),mode='r:gz') as archive:
        assert all(x.isfile() and x.name.startswith('static/') for x in archive.getmembers())
        assert {x.name:b.H(archive.extractfile(x).read()) for x in archive.getmembers()}==manifest['files']

@pytest.mark.parametrize('attack',['backend_diff','private_diff','untracked','local_drift','source','version','count','runtime','csp','proof_path','write_flag','dist_version','dist_link','freeze_hash','freeze_flag','freeze_source'])
def test_unreviewed_source_or_private_or_proof_changes_rejected(candidate,monkeypatch,attack):
    root,dist,before,after,summary,freeze,body=candidate
    if attack=='backend_diff':after['app/backend/stable.py']='f'*64
    elif attack=='private_diff':after['app/frontend/src/private.css']='f'*64
    elif attack=='untracked':(root/'app/frontend/src/other.ts').write_bytes(b'UNTRACKED')
    elif attack=='local_drift':(root/'app/backend/stable.py').write_bytes(b'CHANGED')
    elif attack=='source':summary['source_sha']='f'*40
    elif attack=='version':summary['frontend_version']='f'*12
    elif attack=='count':summary['table_count']=158
    elif attack=='runtime':summary['crm']['id']='f'*64
    elif attack=='csp':summary['content_security_policy_sha256']='f'*64
    elif attack=='proof_path':summary['path']='/tmp/other.json'
    elif attack=='write_flag':summary['business_writes']=True
    elif attack=='dist_version':(dist/'app-version.json').write_text(json.dumps({'version':'f'*12}))
    elif attack=='dist_link':(dist/'assets/linked.js').symlink_to(root/'app/backend/stable.py')
    elif attack=='freeze_hash':body+=b' '
    else:
        if attack=='freeze_flag':freeze['backend_changes']=True
        else:freeze['files']={}
        body=b.encoded(freeze);monkeypatch.setattr(b,'APPLICATION_FREEZE_SHA',b.H(body))
    with pytest.raises(RuntimeError):b.build(summary,body,dist)
