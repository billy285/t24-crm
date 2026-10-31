"""Current active Meta fixture with two legitimate flows; no server access."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

HERE=Path(__file__).resolve().parent

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v);return v
p=load('meta_diagnostic_pf_author',HERE/'preflight.py')
c=load('meta_diagnostic_original_public_core',HERE.parent/'meta-business-activation-20261101/core.py')
r=load('meta_diagnostic_sequence_guard',HERE.parent/'meta-business-20261031/release.py')


def metadata(number=326467):
    seq={'monthly_deduction_rates':number,'unchanged_finance':42}
    return {'pragma_sha256':'p','sequence_exists':True,'sequence_values':seq,'sequence_sha256':r.digest(sorted(seq.items()))}


@pytest.fixture
def active(monkeypatch):
    values={'ENABLED':'true','APP_ID':c.APP_ID,'APP_SECRET':'SYNTHETIC_META_SECRET_12345678','TOKEN_KEY':'eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHg=','CONFIG_ID':c.CONFIG_ID,'GRAPH_VERSION':c.GRAPH_VERSION,'PUBLIC_URL':c.ORIGIN,'EXPECTED_SCOPES':','.join(c.READ_SCOPES),'LOGIN_CONFIG_REVIEWED':'true'}
    info={'Id':p.ORIGINAL_ID,'Image':p.IMAGE,'State':{'Running':True},'Config':{'Env':['PRESERVED=DO_NOT_EXPORT','T24_GBP_TOKEN_KEY=OTHER']+['T24_META_'+k+'='+v for k,v in values.items()]}}
    runtime={'id':p.ORIGINAL_ID,'image':p.IMAGE,'config':'original-config','restart':0,'started':'original-start'}
    inv={name:'a'*64 for name in p.BACKEND_FILES}|{'main.py':'b'*64}
    m=SimpleNamespace(inspect=lambda _:info,runtime=lambda _:copy.deepcopy(runtime),verify_secret_mount=lambda _:None,verify_production_worker_enabled=lambda _:None,retained=lambda:SimpleNamespace(require_safe_original_restart=lambda _:None),inventory=lambda _:inv)
    rows={f'old_{n}':{'count':1,'rows_sha256':'a'*64,'shape_sha256':'b'*64} for n in range(138)}
    rows.update(meta_business_oauth_states={'count':2,'rows_sha256':'two-legitimate-consumed-flows','shape_sha256':'same'},media_publication_image_policies={'count':1,'rows_sha256':'owner-on','shape_sha256':'same'},google_business_actions={'count':8,'rows_sha256':'already-live','shape_sha256':'same'})
    protected={'rows':rows,'schema_sha256':'schema','database_metadata':metadata(),'nginx_sha256':'nginx','active_nginx_sha256':'active','public_root':'/existing/static','public_inventory_sha256':'static','content_security_policy_sha256':'csp','private_boundary':'private','credential_boundary':'stripe','google_credential_metadata':'google'}
    ctx=SimpleNamespace(m=m,inventory=inv,pf=SimpleNamespace(google_environment=lambda _:None),safe=SimpleNamespace(protected_metadata=lambda path:{'mode':0o600,'uid':0,'inode':42}),helper=SimpleNamespace(docker_timestamp_probe=lambda:None),release=r)
    baseline=SimpleNamespace(protected_sample=lambda _:copy.deepcopy(protected))
    receipt={'stage':'META_USER_CONNECTION_RUNTIME_ACTIVATED','source_sha':p.BASE_SOURCE,'frontend_version':p.FRONTEND,'meta_configured':True,'crm':runtime}
    for key in ('same_application_image','exact_nine_meta_environment_keys_added','old_environment_options_mounts_network_labels_preserved','all_141_business_rows_schema_and_private_boundaries_unchanged','google_on_cutoff_preserved'):receipt[key]=True
    for key in ('database_restored','business_writes','provider_requests','nginx_changed','credential_values_exported','production_containers_deleted'):receipt[key]=False
    cred={'env_sha256':p.ENV_SHA,'env_path':str(c.ENV_FILE),'app_id':c.APP_ID,'config_id':c.CONFIG_ID,'configuration_freeze_sha256':c.CONFIG_FREEZE_SHA,'independent_fernet_key_generated':True}
    for key in ('runtime_changed','business_writes','provider_requests','credential_values_exported'):cred[key]=False
    reads=[]
    def read(path,sha,*_):
        reads.append((path,sha));assert path.name in {'activated.json','credential-receipt.json'}
        return json.dumps(receipt if path.name=='activated.json' else cred).encode()
    monkeypatch.setattr(p,'read',read);monkeypatch.setattr(c,'directory',lambda path:None)
    return SimpleNamespace(core=c,baseline=baseline,ctx=ctx,info=info,runtime=runtime,inv=inv,protected=protected,receipt=receipt,cred=cred,reads=reads)


def take(v):return p.sample(v.core,v.baseline,SimpleNamespace(),v.ctx)


def test_active_nine_env_and_nonempty_two_flows_are_preserved_without_secret_file_read(active):
    value=take(active);assert len(value['rows'])==141 and value['rows']['meta_business_oauth_states']['count']==2
    assert value['rows']['media_publication_image_policies']['rows_sha256']=='owner-on' and value['rows']['google_business_actions']['count']==8
    assert value['meta_enabled_configured'] and value['exact_nine_meta_environment_keys_preserved'] and value['credential_file_content_read'] is False
    assert all(path.name!='runtime.env' for path,sha in active.reads)
    exported=json.dumps(value);assert 'SYNTHETIC_META_SECRET' not in exported and 'DO_NOT_EXPORT' not in exported and 'eHh4eHh4' not in exported


@pytest.mark.parametrize('kind',['old_meta_absent','unknown_meta','scope','key','duplicate','runtime','inventory','receipt','envreceipt'])
def test_any_current_configuration_or_provenance_drift_is_rejected(active,kind):
    if kind=='old_meta_absent':active.info['Config']['Env']=[x for x in active.info['Config']['Env'] if not x.startswith('T24_META_')]
    if kind=='unknown_meta':active.info['Config']['Env'].append('T24_META_EXTRA=true')
    if kind=='scope':active.info['Config']['Env']=[x.replace(','.join(c.READ_SCOPES),'instagram_content_publish') for x in active.info['Config']['Env']]
    if kind=='key':active.info['Config']['Env']=[x.replace('T24_GBP_TOKEN_KEY=OTHER','T24_GBP_TOKEN_KEY='+next(z.split('=',1)[1] for z in active.info['Config']['Env'] if z.startswith('T24_META_TOKEN_KEY='))) for x in active.info['Config']['Env']]
    if kind=='duplicate':active.info['Config']['Env'].append(active.info['Config']['Env'][0])
    if kind=='runtime':active.runtime['id']='wrong'
    if kind=='inventory':active.ctx.m.inventory=lambda _:{}
    if kind=='receipt':active.receipt['meta_configured']=False
    if kind=='envreceipt':active.cred['env_sha256']='wrong'
    with pytest.raises(RuntimeError):take(active)


def test_collect_adopts_only_monthly_counter_and_rejects_row_changes(active,monkeypatch):
    values=(active.core,active.baseline,SimpleNamespace(),active.ctx);monkeypatch.setattr(p,'dependencies',lambda:values);monkeypatch.setattr(p.os,'geteuid',lambda:0);monkeypatch.setattr(p.socket,'gethostname',lambda:p.HOST);monkeypatch.setattr(p.resource,'setrlimit',lambda *_:None)
    first=take(active);second=copy.deepcopy(first);second['database_metadata']=metadata(326468);queue=iter([first,second]);monkeypatch.setattr(p,'sample',lambda *_:next(queue));assert p.collect()==second
    second['rows']['meta_business_oauth_states']['count']=3;queue=iter([first,second]);monkeypatch.setattr(p,'sample',lambda *_:next(queue))
    with pytest.raises(RuntimeError,match='PREFLIGHT_CHANGED_DURING_READ'):p.collect()


def test_exact_wrapper_embeds_only_reviewed_pf():
    import ast,base64,zlib
    g=load('meta_diagnostic_pf_generator',HERE/'generate_preflight_command.py');body=g.generate().encode();assert body==(HERE/'preflight-command.sh').read_bytes() and len(body)<11000
    code=body.decode().split("<<'META_DIAGNOSTIC_PREFLIGHT'\n",1)[1].rsplit('META_DIAGNOSTIC_PREFLIGHT\n',1)[0];tree=ast.parse(code)
    packed=next(x.value for x in ast.walk(tree) if isinstance(x,ast.Constant) and isinstance(x.value,str) and x.value.startswith('eN'))
    assert zlib.decompress(base64.b64decode(packed,validate=True))==(HERE/'preflight.py').read_bytes()
