import json
from pathlib import Path
from unittest.mock import patch
import pytest
import static_completed as s


def candidate():
    return {'source_sha':'a'*40,'image_id':'sha256:'+'b'*64,'frontend_version':'c'*12}


def state():
    return {'phase':'PRIVATE_COMPLETED_RELEASE_SERVER_VERIFIED','source_sha':'a'*40,'candidate_image':'sha256:'+'b'*64,
            'deployed':True,'public_assets_published':False,'bank_enabled':False,'ai_enabled':False,
            'business_tables_verified':83,'new_ids':{'api':'x','worker':'y'},'new_private':{'api':{},'worker':{}}}


@pytest.mark.parametrize('field,value', [('phase','PRIVATE_COMPLETED_RELEASE_API_READY'),('deployed',False),
    ('bank_enabled',True),('ai_enabled',True),('source_sha','d'*40),('candidate_image','sha256:'+'e'*64),
    ('business_tables_verified',82),('new_ids',{'api':'x'})])
def test_unaccepted_release_cannot_publish(field,value):
    value_state=state();value_state[field]=value
    with pytest.raises(s.SwitchError):s.checked_state(value_state,candidate())


def test_root_only_change_preserves_every_other_byte():
    with patch.object(s,'PUBLIC',Path('/var/www/t24-crm-public/private-test')):
        original=(str(s.OLD_PUBLIC)+'; proxy_pass http://127.0.0.1:8000; proxy_pass http://127.0.0.1:8001; '+
                  ' '.join(s.HEADERS)).encode()
        result=s.changed_nginx(original,s.sha(original))
        assert result.replace(str(s.PUBLIC).encode(),str(s.OLD_PUBLIC).encode())==original
        with pytest.raises(s.SwitchError):s.changed_nginx(original+b'other',s.sha(original))
        with pytest.raises(s.SwitchError):s.changed_nginx(original+str(s.OLD_PUBLIC).encode(),s.sha(original+str(s.OLD_PUBLIC).encode()))


def test_candidate_complete_dist_and_frozen_version(tmp_path):
    root=tmp_path/'candidate';dist=root/'payload/frontend/dist';dist.mkdir(parents=True)
    (dist/'index.html').write_text('<html></html>');(dist/'app-version.json').write_text(json.dumps({'version':'c'*12}))
    manifest={'source_sha':'a'*40,'frontend_version':'c'*12,'credentials_included':False,
              'payload_files':{'frontend/dist/'+name:value for name,value in s.file_map(dist).items()}}
    fixed=tmp_path/'manifest.json';fixed.write_text(json.dumps(manifest))
    c=candidate();c['payload_manifest_sha256']=s.sha(fixed.read_bytes())
    with patch.object(s,'read_protected',lambda path,maximum=0:path.read_bytes()):
        assert s.candidate_payload(root,c,fixed)==dist
        (dist/'index.html').write_text('changed')
        with pytest.raises(s.SwitchError):s.candidate_payload(root,c,fixed)


def test_static_rollback_restores_root_without_private_mutation(tmp_path):
    original=b'old';changed=b'new';calls=[]
    with patch.object(s,'runtime_snapshot',return_value={}),patch.object(s,'read_nginx',side_effect=[changed,original]),\
         patch.object(s,'atomic_nginx',side_effect=lambda data,allowed:calls.append((data,allowed))),\
         patch.object(s,'run',return_value=b''),patch.object(s,'public_check'),patch.object(s,'file_map',return_value={}):
        s.rollback_static(original,changed,state(),candidate())
    assert calls==[(original,{s.sha(changed)})]


def test_static_rollback_does_not_overwrite_concurrent_nginx_edit():
    with patch.object(s,'runtime_snapshot',return_value={}),patch.object(s,'read_nginx',return_value=b'unrelated'),\
         patch.object(s,'atomic_nginx') as replace:
        with pytest.raises(s.SwitchError):s.rollback_static(b'old',b'new',state(),candidate())
        replace.assert_not_called()


def test_late_success_receipt_failure_never_claims_deployed_after_rollback(tmp_path):
    from types import SimpleNamespace
    from copy import deepcopy
    import seed_private_stripe as seed
    candidate_root=tmp_path/'candidate';candidate_root.mkdir()
    completed=candidate_root/'completed-release';completed.mkdir()
    config=tmp_path/'config';config.mkdir()
    args=SimpleNamespace(execute=True,source_sha='a'*40,candidate=candidate_root/'candidate.json',candidate_sha256='f'*64,
        switch_state=completed/'switch-state.json',switch_state_sha256='e'*64,manifest=tmp_path/'manifest.json')
    receipts=[]
    def fixed(path,expected):
        if path==args.candidate:return candidate()
        if path==args.switch_state:return state()
        return {'new_nginx_sha256':'d'*64}
    failed=False
    def save(path,value,replace=False):
        nonlocal failed
        receipts.append(deepcopy(value))
        if value['phase']=='PRIVATE_COMPLETED_PUBLIC_RELEASE_VERIFIED' and not failed:
            failed=True
            raise OSError('synthetic late receipt failure')
    with patch.object(s.os,'geteuid',return_value=0),patch.object(s.socket,'gethostname',return_value=s.HOST),\
         patch.object(s,'CONFIG',config),patch.object(s,'fixed_json',side_effect=fixed),\
         patch.object(seed,'checked_candidate'),patch.object(s,'secure'),patch.object(s,'runtime_snapshot',return_value={}),\
         patch.object(s,'read_nginx',side_effect=[b'old',b'old',b'old',b'new']),\
         patch.object(s,'changed_nginx',return_value=b'new'),patch.object(s,'candidate_payload',return_value=tmp_path/'dist'),\
         patch.object(s,'install_public',return_value={'index.html':'f'*64}),patch.object(s,'business_fingerprints',return_value={}),\
         patch.object(s,'save',side_effect=save),patch.object(s,'atomic_nginx'),patch.object(s,'run'),\
         patch.object(s,'public_check'),patch.object(s,'file_map',return_value={'index.html':'f'*64}),\
         patch.object(s,'rollback_static') as rollback:
        with pytest.raises(s.SwitchError,match='STATIC_RELEASE_REJECTED_ROLLBACK_VERIFIED'):s.main(args)
    rollback.assert_called_once()
    assert receipts[-1]['phase']=='COMPLETED_STATIC_ROLLBACK_VERIFIED'
    assert receipts[-1]['deployed'] is False
