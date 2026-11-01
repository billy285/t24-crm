"""One-rule static payload attacks; no network, live data, or deployment."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import pytest
HERE=Path(__file__).resolve().parent
s=importlib.util.spec_from_file_location('mobile_static_package_test',HERE/'build_payload.py');b=importlib.util.module_from_spec(s);s.loader.exec_module(b)

@pytest.fixture
def candidate(tmp_path,monkeypatch):
    root=tmp_path/'repo';root.mkdir();css=root/b.CSS;css.parent.mkdir(parents=True)
    old=('@media (max-width: 700px) {\n'+b.OLD_RULE+'\n}\n').encode();new=old.replace(b.OLD_RULE.encode(),b.NEW_RULE.encode())
    css.write_bytes(new)
    private=root/'app/frontend/src/private.css';private.write_bytes(b'PRIVATE_FRONTEND_UNCHANGED')
    backend=root/'app/backend/stable.py';backend.parent.mkdir(parents=True);backend.write_bytes(b'BACKEND_UNCHANGED')
    before={b.CSS:b.H(old),'app/frontend/src/private.css':b.H(private.read_bytes()),'app/backend/stable.py':b.H(backend.read_bytes())};after={**before,b.CSS:b.H(new)}
    monkeypatch.setattr(b,'ROOT',root);monkeypatch.setattr(b,'inventory',lambda ref:copy.deepcopy(before if ref==b.BASE_SOURCE else after));monkeypatch.setattr(b,'git',lambda *a,**k:old);monkeypatch.setattr(b,'frontend_version',lambda:b.FRONTEND);monkeypatch.setattr(b,'PREFLIGHT_SHA','d'*64)
    dist=root/'app/frontend/dist';(dist/'assets').mkdir(parents=True);(dist/'app-version.json').write_bytes(json.dumps({'version':b.FRONTEND}).encode());(dist/'index.html').write_bytes(b'<html>synthetic</html>');(dist/'assets/test.css').write_bytes(b'.mobile{position:static}')
    freeze={'source_sha':b.SOURCE,'baseline_source_sha':b.BASE_SOURCE,'frontend_version':b.FRONTEND,'baseline_frontend_version':b.BASE_FRONTEND,'files':{b.CSS:after[b.CSS]},'dist_inventory_sha256':b.static_inventory(b.read_static(dist)),**{x:True for x in b.TRUE_FLAGS},**{x:False for x in b.FALSE_FLAGS}}
    body=b.encoded(freeze);monkeypatch.setattr(b,'APPLICATION_FREEZE_SHA',b.H(body))
    summary={'stage':'GOOGLE_ONBOARDING_MOBILE_PREFLIGHT_CAPTURED','sha256':'d'*64,'path':'/opt/t24-crm/releases/google-business-onboarding-mobile-preflight-'+'d'*12+'.json','source_sha':b.BASE_SOURCE,'frontend_version':b.BASE_FRONTEND,'schema_revision':'g32ed456e792','table_count':162,'backend_file_count':419,'all162_current_tables_preserved':True,'crm':{'id':'9b247014d54e57e5f671d3f8378c6b387c5301a87471b823e790b0d4965d072b','image':'sha256:ed057407d8866958a2966043ddc2457488d77cc00dd7bbabb608bcedc7c0bb09'},'content_security_policy_sha256':'ead64b09efe8c4f35648aa8eafe8855c5268ecf0999e0918b3642dd9dfbfe7a6',**{x:False for x in ('schema_changed','permissions_changed','business_writes','provider_requests','credential_file_content_read','private_content_read','runtime_changed')}}
    return root,dist,before,after,summary,freeze,body


def test_package_is_deterministic_static_only_one_mobile_rule_with_every_other_source_protected(candidate):
    root,dist,before,after,summary,freeze,body=candidate
    blob,manifest=b.build(summary,body,dist);again,other=b.build(summary,body,dist)
    assert blob==again and manifest==other and manifest['changed_source_files']=={b.CSS:after[b.CSS]}
    assert manifest['protected_source_inventory']=={k:v for k,v in before.items() if k!=b.CSS}
    assert all(manifest[k] is True for k in b.TRUE_FLAGS) and all(manifest[k] is False for k in b.FALSE_FLAGS)
    with tarfile.open(fileobj=io.BytesIO(blob),mode='r:gz') as archive:
        rows=archive.getmembers();assert len(rows)==3 and all(x.isfile() and x.name.startswith('static/') and not x.name.startswith('backend/') for x in rows)
        assert {x.name:b.H(archive.extractfile(x).read()) for x in rows}==manifest['files']
    assert (root/'app/backend/stable.py').read_bytes()==b'BACKEND_UNCHANGED' and (root/'app/frontend/src/private.css').read_bytes()==b'PRIVATE_FRONTEND_UNCHANGED'

@pytest.mark.parametrize('attack',['extra_rule','backend_diff','private_diff','untracked_frontend','local_source_drift','wrong_source','old_version','old_table_count','backend_count','runtime','csp','proof_sha','proof_path','write_flag','version_file','dist_symlink','freeze_hash','freeze_flag'])
def test_unreviewed_changes_and_stale_live_or_static_evidence_are_rejected(candidate,monkeypatch,attack):
    root,dist,before,after,summary,freeze,body=candidate
    if attack=='extra_rule':
        p=root/b.CSS;p.write_bytes(p.read_bytes()+b'.other{display:none}');after[b.CSS]=b.H(p.read_bytes())
    elif attack=='backend_diff':after['app/backend/stable.py']='a'*64
    elif attack=='private_diff':after['app/frontend/src/private.css']='a'*64
    elif attack=='untracked_frontend':(root/'app/frontend/src/evil.ts').write_bytes(b'UNTRACKED')
    elif attack=='local_source_drift':(root/'app/backend/stable.py').write_bytes(b'CHANGED')
    elif attack=='wrong_source':summary['source_sha']='a'*40
    elif attack=='old_version':summary['frontend_version']='a'*12
    elif attack=='old_table_count':summary['table_count']=158
    elif attack=='backend_count':summary['backend_file_count']=414
    elif attack=='runtime':summary['crm']['id']='a'*64
    elif attack=='csp':summary['content_security_policy_sha256']='a'*64
    elif attack=='proof_sha':summary['sha256']='a'*64
    elif attack=='proof_path':summary['path']='/tmp/unknown.json'
    elif attack=='write_flag':summary['business_writes']=True
    elif attack=='version_file':(dist/'app-version.json').write_text(json.dumps({'version':'a'*12}))
    elif attack=='dist_symlink':(dist/'assets/linked.css').symlink_to(root/b.CSS)
    elif attack=='freeze_hash':body+=b' '
    else:
        freeze['backend_changes']=True;body=b.encoded(freeze);monkeypatch.setattr(b,'APPLICATION_FREEZE_SHA',b.H(body))
    with pytest.raises(RuntimeError):b.build(summary,body,dist)
