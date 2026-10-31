"""Synthetic metadata/fingerprint checks, no provider or production access."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path); value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value

p = module('meta_readonly_preflight', HERE / 'preflight.py')
w = module('pilot_retained_workflow_fixture', HERE.parent / 'media-workflow-20261031/release.py')


@pytest.fixture
def baseline(tmp_path, monkeypatch):
    site = tmp_path/'static'; site.mkdir(); (site/'app-version.json').write_text(json.dumps({'version': p.BASE_FRONTEND}))
    nginx=tmp_path/'nginx.conf'
    nginx.write_text('http { access_log /var/log/nginx/access.log; error_log /var/log/nginx/error.log warn; server { listen 443 ssl; server_name t24-crm.com; error_log /var/log/nginx/t24-private-error.log warn; root '+str(site)+'; location = '+p.CALLBACK+' { access_log off; error_log /dev/null crit; } location ^~ '+p.DELIVERY_PREFIX+' { proxy_pass http://127.0.0.1:8000; access_log off; error_log /dev/null crit; } } }')
    active=b'# nginx full effective config\n'+nginx.read_bytes(); db=tmp_path/'data.db'; db.write_bytes(b'SYNTHETIC ONLY')
    runtime={'id':p.ORIGINAL_ID,'image':p.IMAGE,'config':'c'*64,'started':'2026-10-31T12:20:44.184469195Z','restart':0}
    env=['T24_GBP_'+key+'='+value for key,value in {'ENABLED':'true','API_APPROVED':'true','CLIENT_ID':'SYNTHETIC-CLIENT','CLIENT_SECRET':'DO_NOT_EXPORT_CLIENT_SECRET','TOKEN_KEY':'DO_NOT_EXPORT_TOKEN_KEY','PUBLIC_URL':'https://t24-crm.com','SCHEDULER_ENABLED':'true','SCHEDULER_ACTIVATION_FROM':p.ACTIVATION_FROM}.items()]
    crm={'Id':p.ORIGINAL_ID,'State':{'Running':True},'Config':{'Env':env},'_runtime':runtime}; inventory={'routers/google_business.py':'a'*64,'protected.py':'b'*64}
    receipt={'stage':'GOOGLE_PHOTO_PREVIEW_DEPLOYED_STATIC_VERIFIED','deployed':True,'source_sha':p.BASE_SOURCE,'frontend_version':p.BASE_FRONTEND,'backend_source_sha':p.BACKEND_SOURCE,'schema_revision':p.REVISION,'public_root':str(site),'preflight_sha256':'f'*64,'schema_sha256':'d'*64,'public_inventory_sha256':'e'*64,'nginx_sha256':p.H(nginx.read_bytes()),'sentinel_active_nginx_sha256':p.H(active),'crm':copy.deepcopy(runtime),'scheduler_enabled':True,'scheduler_activation_from':p.ACTIVATION_FROM,**{key:True for key in ('runtime_and_backend_unchanged','all_136_rows_and_schema_unchanged','existing_image_policies_and_data_preserved','callback_and_image_privacy_configuration_preserved')}}
    rows={'table_'+str(i):{'count':i,'rows_sha256':str(i%10)*64,'columns':['id','private_content'],'schema':{},'indexes':{},'raw_private_record':'DO_NOT_EXPORT_RAW_RECORD'} for i in range(130)}
    rows.update({name:copy.deepcopy(rows['table_1']) for name in w.NEW_TABLES}); calls=[]
    def read(path, sha=None):
        assert path==p.OLD/'deployed.json' and sha==p.DEPLOYED_SHA; return json.dumps(receipt).encode()
    monkeypatch.setattr(p,'read',read)
    csp=b"HTTP/1.1 200 OK\r\nContent-Security-Policy: default-src 'self'; img-src 'self' data: https:;\r\n\r\n"
    m=SimpleNamespace(inspect=lambda name:crm if name=='t24-crm' else pytest.fail('unknown live name'),runtime=lambda row:row['_runtime'],verify_secret_mount=lambda _:calls.append('mount-metadata'),verify_production_worker_enabled=lambda _:calls.append('worker-env'),retained=lambda:SimpleNamespace(require_safe_original_restart=lambda _:calls.append('restart-policy')),inventory=lambda _:inventory,schema_signature=lambda *_:'d'*64,digest=lambda value:value,tree=lambda _:'e'*64,NGINX=nginx,run=lambda argv,code,*timeout:active if argv==['nginx','-T'] else csp if argv[0]=='curl' else pytest.fail('unexpected command'),read=lambda *_:b'{"metadata_only":true}',BUSINESS=db,sql_snapshot=lambda _:rows,credential_boundary=lambda:{'metadata_only':True})
    helper=SimpleNamespace(db_metadata=lambda _:{'pragma_sha256':'2'*64,'sequence_exists':True,'sequence_sha256':p.digest([('protected-only',123)]),'sequence_values':{'protected-only':123}},docker_timestamp_probe=lambda:True)
    base=SimpleNamespace(PRIVATE_PINS=Path('/synthetic-private-pins'),PRIVATE_PINS_SHA='1'*64)
    safe=SimpleNamespace(safe_private_boundary=lambda *_:{'metadata_only':True},protected_metadata=lambda _:{'uid':0,'mode':384},GBP_ENV=Path('/synthetic-google.env'))
    core_receipt={'source_sha':p.BACKEND_SOURCE,'crm':copy.deepcopy(runtime),'candidate_inventory_sha256':p.H((json.dumps(inventory,sort_keys=True,indent=2)+'\n').encode())}
    prior_proof={'public_root':'/prior-static-root','active_nginx_config_sha256':p.H(active.replace(str(site).encode(),b'/prior-static-root',1))}
    def prior_read(path,sha):return json.dumps(core_receipt if path.name=='deployed.json' else prior_proof).encode()
    previous=SimpleNamespace(OLD=Path('/synthetic-prior-core'),DEPLOYED_SHA='c'*64,read=prior_read)
    static=module('meta_prior_static_compatibility',HERE.parent/'google-photo-preview-20261031/release.py')
    return SimpleNamespace(previous=previous,static=static,core_receipt=core_receipt,prior_proof=prior_proof,helper=helper,m=m,base=base,safe=safe,w=w,crm=crm,receipt=receipt,rows=rows,inventory=inventory,calls=calls,active=active)


def collect(s): return p.baseline(s.helper,s.m,s.base,s.safe,s.w,s.static,s.previous)


def test_existing_nonempty_policy_image_task_rows_captured_without_seeding_or_export(baseline):
    proof=collect(baseline); assert len(proof['rows'])==136 and proof['existing_image_policies_and_data_preserved']
    assert all(proof['rows'][name]['count']==1 for name in w.NEW_TABLES)
    assert proof['content_security_policy_sha256']==p.H(b"default-src 'self'; img-src 'self' data: https:;")
    body=json.dumps(proof)
    assert not any(value in body for value in ('DO_NOT_EXPORT_CLIENT_SECRET','DO_NOT_EXPORT_TOKEN_KEY','DO_NOT_EXPORT_RAW_RECORD'))
    assert all(set(row)=={'count','rows_sha256','shape_sha256'} for row in proof['rows'].values())


@pytest.mark.parametrize('key,value',[('T24_GBP_ENABLED','false'),('T24_GBP_SCHEDULER_ENABLED','false'),('T24_GBP_SCHEDULER_ACTIVATION_FROM','2026-11-01T00:00:00Z')])
def test_worker_env_and_cutoff_drift_rejected(baseline,key,value):
    baseline.crm['Config']['Env']=[key+'='+value if row.startswith(key+'=') else row for row in baseline.crm['Config']['Env']]
    with pytest.raises(RuntimeError):collect(baseline)


@pytest.mark.parametrize('change',['duplicate_env','new_env','runtime','inventory','schema','table_added','table_removed','active_nginx','receipt_scheduler','policy_table_removed'])
def test_scope_and_protections_fail_closed(baseline,change):
    s=baseline
    if change=='duplicate_env':s.crm['Config']['Env'].append('T24_GBP_ENABLED=true')
    elif change=='new_env':s.crm['Config']['Env'].append('T24_GBP_EXTRA=true')
    elif change=='runtime':s.crm['_runtime']={**s.crm['_runtime'],'config':'0'*64}
    elif change=='inventory':s.inventory['protected.py']='0'*64
    elif change=='schema':s.m.schema_signature=lambda *_:'0'*64
    elif change=='table_added':s.rows['unreviewed']=copy.deepcopy(s.rows['table_1'])
    elif change=='table_removed':del s.rows['table_1']
    elif change=='active_nginx':s.m.run=lambda *_:s.active+b'# unrelated change\n'
    elif change=='receipt_scheduler':s.receipt['scheduler_enabled']=False
    else:del s.rows['media_publication_image_policies']
    with pytest.raises(RuntimeError):collect(s)


@pytest.mark.parametrize('location',[p.CALLBACK,p.DELIVERY_PREFIX])
def test_both_existing_privacy_locations_must_remain_strict(baseline,location):
    bad=baseline.active.replace(('location '+('= ' if location==p.CALLBACK else '^~ ')+location+' {').encode(),b'location /unprotected {')
    with pytest.raises(RuntimeError):p.privacy_blocks(w,bad)


def test_retained_local_pins_match_actual_deployed_evidence():
    repo=HERE.parents[1]
    assert p.OLD_PREFLIGHT_SHA==hashlib.sha256((repo/'deployments/google-photo-preview-20261031/preflight.py').read_bytes()).hexdigest()
    assert p.OLD_RELEASE_SHA==hashlib.sha256((repo/'deployments/google-photo-preview-20261031/release.py').read_bytes()).hexdigest()
    assert p.DEPLOYED_SHA==hashlib.sha256((repo/'outputs/google-photo-preview-20261031/retry-actual-deployed.json').read_bytes()).hexdigest()


def test_dependency_seam_has_named_arity_and_exact_modules(monkeypatch):
    workflow=object();values=tuple(SimpleNamespace(name=n) for n in ('helper','m','base','safe'))+(workflow,object());previous=SimpleNamespace(dependencies=lambda:values);static=object()
    monkeypatch.setattr(p,'load',lambda path,sha,name:previous if path.name=='preflight.py' else static)
    assert p.dependencies()==(*values[:5],static,previous)
    previous.dependencies=lambda:(1,2,3)
    with pytest.raises(RuntimeError,match='RETAINED_DEPENDENCY_ARITY_REQUIRED'):p.dependencies()


def test_collect_two_samples_reject_other_drift_and_adopt_only_latest_observed_counter(monkeypatch):
    monkeypatch.setattr(p.os,'geteuid',lambda:0);monkeypatch.setattr(p.socket,'gethostname',lambda:p.HOST);monkeypatch.setattr(p.resource,'setrlimit',lambda *_:None);monkeypatch.setattr(p.os,'umask',lambda *_:0)
    static=module('meta_real_static_double_sample_guard',HERE.parent/'google-photo-preview-20261031/release.py')
    monkeypatch.setattr(p,'dependencies',lambda:(SimpleNamespace(docker_timestamp_probe=lambda:True),None,None,None,w,static,None));counter=[0]
    def sample(*_):
        counter[0]+=1;seq={'monthly_deduction_rates':counter[0]};return {'database_metadata':{'pragma_sha256':'1'*64,'sequence_exists':True,'sequence_values':seq,'sequence_sha256':p.digest(sorted(seq.items()))},'unchanged':'same'}
    monkeypatch.setattr(p,'baseline',sample);assert p.collect()['database_metadata']['sequence_values']['monthly_deduction_rates']==2
    def drift(*_):result=sample();result['unchanged']=counter[0];return result
    monkeypatch.setattr(p,'baseline',drift)
    with pytest.raises(RuntimeError,match='PREFLIGHT_CHANGED_DURING_READ'):p.collect()


@pytest.mark.parametrize('headers',[b'HTTP/1.1 200 OK\r\n\r\n',b'HTTP/1.1 302 Found\r\nContent-Security-Policy: img-src data:;\r\n\r\n',b'HTTP/1.1 200 OK\r\nContent-Security-Policy: img-src data:;\r\nContent-Security-Policy: img-src https:;\r\n\r\n',b'HTTP/1.1 200 OK\r\nContent-Security-Policy: default-src self;\r\n\r\n'])
def test_csp_header_must_be_one_nonempty_real_200_policy(headers):
    m=SimpleNamespace(run=lambda *args:headers)
    with pytest.raises(RuntimeError):p.security_headers(m)


def test_csp_read_is_loopback_without_credentials_or_response_body():
    commands=[]
    def run(argv,*args):commands.append(argv);return b"HTTP/1.1 200 OK\r\nContent-Security-Policy: default-src 'self'; img-src 'self' data: https:;\r\n\r\n"
    result=p.security_headers(SimpleNamespace(run=run));argv=commands[0]
    assert '--resolve' in argv and 't24-crm.com:443:127.0.0.1' in argv and argv[-1]=='https://t24-crm.com/media-ops'
    assert argv[argv.index('-o')+1]=='/dev/null' and '--cookie' not in argv and '--user' not in argv
    assert set(result)=={'content_security_policy_sha256'}


@pytest.mark.parametrize('key',['T24_META_ENABLED','T24_META_APP_SECRET','T24_META_TOKEN_KEY','T24_META_GRAPH_VERSION','T24_META_FUTURE_KEY'])
def test_first_meta_deploy_requires_every_meta_env_key_absent_even_false(baseline,key):
    baseline.crm['Config']['Env'].append(key+'=false')
    with pytest.raises(RuntimeError,match='NEW_META_ENVIRONMENT_MUST_START_ABSENT_DISABLED'):collect(baseline)


def test_meta_connect_tables_or_source_files_cannot_preexist(baseline):
    s=baseline;s.rows['meta_business_connections']=s.rows.pop('table_2')
    with pytest.raises(RuntimeError,match='EXACT_EXISTING_136_TABLES_REQUIRED'):collect(s)


def test_meta_preflight_reports_only_absent_disabled_flags_not_credentials(baseline):
    proof=collect(baseline)
    assert proof['meta_feature_enabled'] is proof['meta_credentials_present'] is False
    assert proof['meta_environment_keys_absent'] is proof['meta_callback_location_absent'] is True
    assert len(proof['backend_changed_before'])==5 and all(value is None for value in proof['backend_changed_before'].values())
