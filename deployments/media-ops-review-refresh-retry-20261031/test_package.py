import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
from types import SimpleNamespace

import pytest

HERE=Path(__file__).resolve().parent

def load(name):
    spec=importlib.util.spec_from_file_location('refresh_package_'+name,HERE/(name+'.py'));m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m);return m
r=load('release');b=load('build_payload');m=load('make_commands')


def test_actual_source_and_bundle_only_exact_two_runtime_patches():
    value=json.loads((HERE/'artifacts/manifest.json').read_bytes())
    assert value['source_sha']==r.SOURCE_SHA and value['frontend_version']==r.FRONTEND and set(value['changed_source_files'])==r.SOURCE_FILES
    assert set(value['backend_after'])==r.BACKEND_FILES and value['database_migration'] is False
    assert set(value['protected_source_inventory']) and not any('private-workspace' in n for n in set(value['changed_source_files']))
    before,after=b.inventory(r.BASE_SOURCE),b.inventory(r.SOURCE_SHA)
    assert {n for n in before.keys()|after.keys() if before.get(n)!=after.get(n)}==r.SOURCE_FILES
    with tarfile.open(HERE/'artifacts/payload.tar.gz','r:gz') as archive:
        items=archive.getmembers();assert all(x.isfile() for x in items)
        assert {x.name for x in items}==set(value['files'])
        assert {x.name for x in items if x.name.startswith('backend/')}=={'backend/'+n for n in r.BACKEND_FILES}
        for item in items:assert hashlib.sha256(archive.extractfile(item).read()).hexdigest()==value['files'][item.name]
    assert hashlib.sha256((HERE/'artifacts/payload.tar.gz').read_bytes()).hexdigest()==value['payload_sha256']


def valid_manifest_env():
    proof_sha='a'*64;payload_sha='b'*64;v=json.loads((HERE/'artifacts/manifest.json').read_bytes());v['preflight_sha256']=proof_sha;v['payload_sha256']=payload_sha
    p={'stage':'MEDIA_OPS_REVIEW_REFRESH_RETRY_READONLY_PREFLIGHT','host':r.HOST,'source_sha':r.BASE_SOURCE,'frontend_version':r.BASE_FRONTEND,'schema_revision':r.REVISION,'deployed_sha256':r.BASE_DEPLOYED_SHA,'crm':{'id':'original','image':'base-image'},'scheduler_disabled':True,'gbp_feature_enabled':True,'callback_logging_protection_retained':True,'rows':{str(i):{} for i in range(129)},'backend_changed_before':v['backend_before'],'recovered_sha256':'9'*64,'host_docker_timestamp_parser_verified':True}
    for k in ('provider_requests','business_writes','private_content_read','credential_content_read','container_or_configuration_changed'):p[k]=False
    w=object.__new__(r.Release);w.proof=p;w.manifest=v;w.args=SimpleNamespace(preflight_sha256=proof_sha,payload_sha256=payload_sha);w.pf=SimpleNamespace(DEPLOYED_SHA=r.BASE_DEPLOYED_SHA,ORIGINAL_ID='original',IMAGE='base-image',RECOVERED_SHA='9'*64);w.m=SimpleNamespace(static_path=b.static_path)
    return w


def test_exact_manifest_control_passes():valid_manifest_env().validate()


@pytest.mark.parametrize('mutation', ['source','frontend','migration','seed','credentials','extra_backend','extra_source','lost_table','scheduler','gbp','callback','business_write','private_content','backend_before','backend_hash','path_traversal'])
def test_unapproved_manifest_or_actual_baseline_rejected(mutation):
    w=valid_manifest_env();v,p=w.manifest,w.proof
    if mutation=='source':v['source_sha']='0'*40
    elif mutation=='frontend':v['frontend_version']='0'*12
    elif mutation=='migration':v['database_migration']=True
    elif mutation=='seed':v['production_seed_rows']=True
    elif mutation=='credentials':v['credentials_included']=True
    elif mutation=='extra_backend':v['backend_after']['services/financial.py']='a'*64
    elif mutation=='extra_source':v['changed_source_files'].append('app/backend/services/financial.py')
    elif mutation=='lost_table':p['rows'].pop('0')
    elif mutation=='scheduler':p['scheduler_disabled']=False
    elif mutation=='gbp':p['gbp_feature_enabled']=False
    elif mutation=='callback':p['callback_logging_protection_retained']=False
    elif mutation=='business_write':p['business_writes']=True
    elif mutation=='private_content':p['private_content_read']=True
    elif mutation=='backend_before':p['backend_changed_before']={n:'0'*64 for n in r.BACKEND_FILES}
    elif mutation=='backend_hash':v['backend_after']['services/google_business.py']='0'*64
    else:v['files']['static/assets/../../outside.js']='a'*64
    with pytest.raises(RuntimeError):w.validate()


@pytest.fixture
def carrier(tmp_path,monkeypatch):
    repo=tmp_path/'repo';repo.mkdir();(repo/'app').mkdir();(repo/'app'/'code').write_text('synthetic')
    def git(*args):return subprocess.check_output(['git',*args],cwd=repo,stderr=subprocess.PIPE)
    git('init','-q');git('config','user.email','synthetic@example.invalid');git('config','user.name','Synthetic Test');git('add','.');git('commit','-qm','source');source=git('rev-parse','HEAD').decode().strip()
    directory=repo/m.DIRECTORY;directory.mkdir(parents=True);(directory/'artifacts').mkdir()
    summary={'stage':'MEDIA_OPS_REVIEW_REFRESH_RETRY_PREFLIGHT_CAPTURED','source_sha':m.r.BASE_SOURCE,'frontend_version':m.r.BASE_FRONTEND,'schema_revision':m.r.REVISION,'table_count':129,'sha256':'a'*64,'path':'/opt/t24-crm/releases/media-ops-review-refresh-retry-preflight-'+('a'*12)+'.json','deployed_sha256':m.r.BASE_DEPLOYED_SHA,'scheduler_disabled':True,'gbp_feature_enabled':True,'callback_logging_protection_retained':True,'private_boundary_verified':True,'credential_content_read':False,'private_content_read':False,'executed_business_writes':False,'recovered_sha256':m.r.RECOVERED_SHA,'host_docker_timestamp_parser_verified':True}
    manifest={'source_sha':source,'frontend_version':m.r.FRONTEND,'preflight_sha256':summary['sha256'],'database_migration':False}
    for n,body in {'release.py':(HERE/'release.py').read_bytes(),'preflight.py':(HERE/'preflight.py').read_bytes(),'artifacts/manifest.json':json.dumps(manifest).encode(),'artifacts/payload.tar.gz':b'synthetic-not-real-payload'}.items():(directory/n).write_bytes(body)
    git('add','.');git('commit','-qm','tools');commit=git('rev-parse','HEAD').decode().strip()
    check_output=subprocess.check_output
    def local(args,*a,**kw):
        if args and args[0]=='git':kw['cwd']=repo
        return check_output(args,*a,**kw)
    monkeypatch.setattr(m,'HERE',directory);monkeypatch.setattr(m.r,'SOURCE_SHA',source);monkeypatch.setattr(m.subprocess,'check_output',local)
    return SimpleNamespace(repo=repo,directory=directory,git=git,commit=commit,summary=summary)


def test_real_git_carrier_positive_and_prepare_only_initially(carrier):
    commands,pins=m.generate(carrier.commit,carrier.summary)
    assert set(commands)=={'prepare-command.sh'} and pins['prepared_sha256'] is None
    command=commands['prepare-command.sh'];assert len(command.encode())<11000 and 'sudo python3 -I -S -B' in command
    assert command.index('os.geteuid()==0')<command.index('opener(') if 'opener(' in command else command.index('os.geteuid()==0')<command.index('urllib.request.build_opener')
    assert carrier.commit in command and 'ProxyHandler({})' in command and 'NoRedirect()' in command


@pytest.mark.parametrize('name',['release.py','preflight.py','artifacts/manifest.json','artifacts/payload.tar.gz'])
def test_each_committed_carrier_member_drift_rejected(carrier,name):
    p=carrier.directory/name;p.write_bytes(p.read_bytes()+b'X')
    with pytest.raises(RuntimeError,match='EXACT_COMMITTED_MEMBER_REQUIRED'):m.generate(carrier.commit,carrier.summary)


def test_other_carrier_application_change_rejected(carrier):
    (carrier.repo/'app'/'code').write_text('changed');carrier.git('add','.');carrier.git('commit','-qm','wrong app');wrong=carrier.git('rev-parse','HEAD').decode().strip()
    with pytest.raises(RuntimeError,match='CARRIER_APP_TREE_DRIFT'):m.generate(wrong,carrier.summary)


@pytest.mark.parametrize('bad',['main','a'*39,'A'*40,'a'*40+';id'])
def test_wrong_carrier_rejected_before_git(monkeypatch,bad):
    monkeypatch.setattr(m.subprocess,'check_output',lambda *_a,**_kw:pytest.fail('unexpected git'))
    with pytest.raises(RuntimeError):m.generate(bad,{})
