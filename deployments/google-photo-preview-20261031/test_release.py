"""Static root switching on a synthetic runtime: Docker writes are unsupported."""
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

HERE=Path(__file__).resolve().parent

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v);return v

r=load('photo_static_release',HERE/'release.py');retained=load('photo_retained_record_snapshot',HERE.parent/'media-workflow-20261031/release.py')
CSP=r.H(b"default-src 'self'; img-src 'self' data: https:;")


class Runtime:
    def __init__(self,tmp_path):
        self.NGINX=tmp_path/'nginx.conf';self.NGINX.write_bytes(b"server { root /public/old; location = /api/v1/google-business/oauth/callback { access_log off; error_log /dev/null crit; } location ^~ /api/v1/media-publication-images/delivery/ { access_log off; error_log /dev/null crit; } }")
        self.BUSINESS=tmp_path/'data.db';self.BUSINESS.write_bytes(b'SYNTHETIC UNCHANGED DATABASE');self.rows={'table_'+str(i):{'count':i,'rows_sha256':r.H(str(i).encode()),'columns':['id'],'schema':{},'indexes':{}} for i in range(134)}
        self.rows.update({'media_publication_image_policies':{'count':1,'rows_sha256':r.H(b'ON'),'columns':['owner_id','enabled'],'schema':{},'indexes':{}},'media_publication_images':{'count':1,'rows_sha256':r.H(b'PRIVATE_IMAGE'),'columns':['id'],'schema':{},'indexes':{}}})
        self.current={'Id':'7'*64,'State':{'Running':True},'Config':{'Env':['SYNTHETIC=unchanged']},'_runtime':{'id':'7'*64,'image':'sha256:'+'8'*64,'config':'6'*64,'restart':0,'started':'same'}}
        self.PUBLIC=Path('/public/old');self.old_tree={'app-version.json':'1'*64,'assets/old.js':'2'*64};self.new_tree={'app-version.json':'3'*64,'assets/new.js':'4'*64};self.backend={'main.py':'a'*64,'services/google_business.py':'b'*64};self.schema='9'*64;self.csp=CSP;self.calls=[];self.fault=None
    def read(self,path,sha=None):
        body=path.read_bytes();r.need(sha is None or r.H(body)==sha,'SYNTHETIC_FILE_HASH_DRIFT');return body
    def write(self,path,value):
        with path.open('xb') as stream:stream.write(value if isinstance(value,bytes) else r.encoded(value))
        return r.H(path.read_bytes())
    def run(self,argv,*args):
        self.calls.append(argv)
        if self.fault:self.fault(argv)
        if argv==['nginx','-T']:return b'# effective configuration\n'+self.NGINX.read_bytes()
        if argv[0]=='curl':
            if argv[-1].endswith('/app-version.json'):return json.dumps({'version':r.FRONTEND if b'/public/new' in self.NGINX.read_bytes() else r.BASE_FRONTEND}).encode()
            if argv[-1].endswith('/ready'):return b'{"status":"ready"}'
        pytest.fail('unexpected command, especially Docker write: '+repr(argv[:2]))
    def inspect(self,name):assert name=='t24-crm';return copy.deepcopy(self.current)
    def runtime(self,row):return row['_runtime']
    def sql_snapshot(self,_):return copy.deepcopy(self.rows)
    def schema_signature(self,*_):return self.schema
    def inventory(self,identity):assert identity==self.current['Id'];return self.backend
    def tree(self,root):return self.old_tree if root==self.PUBLIC else self.new_tree
    def credential_boundary(self):return {'same':True}
    def verify_secret_mount(self,_):pass
    def verify_production_worker_enabled(self,_):pass
    def retained(self):return self
    def require_safe_original_restart(self,_):pass
    def ready(self,identity):assert identity==self.current['Id']
    def stage_public(self,*_):return Path('/public/new'),r.digest(self.new_tree)
    def verify_public(self,*_):return r.digest(self.new_tree)
    def extract(self,*_):pass
    def replace_nginx(self,before,after):assert self.NGINX.read_bytes()==before;self.NGINX.write_bytes(after)
    def cleanup_nginx_temp(self,*_):self.calls.append(['cleanup-owned-nginx-temp'])
    def reload_nginx(self):
        self.calls.append(['reload-nginx'])
        if self.fault:self.fault(['reload-nginx'])


@pytest.fixture
def publisher(tmp_path,monkeypatch):
    monkeypatch.setattr(r,'SOURCE_SHA','e'*40);monkeypatch.setattr(r,'FRONTEND','f'*12)
    v=object.__new__(r.Release);v.w=retained;v.m=Runtime(tmp_path);release=tmp_path/'release';release.mkdir();v.args=SimpleNamespace(release=release,review_sha256='d'*64,manifest_sha256='a'*64,payload_sha256='b'*64,preflight_sha256='c'*64);v.public=Path('/public/new');v.pins={}
    metadata={'pragma_sha256':'1'*64,'sequence_exists':True,'sequence_values':{'same':10},'sequence_sha256':r.digest([('same',10)])}
    v.helper=SimpleNamespace(docker_timestamp_probe=lambda:True,db_metadata=lambda _:copy.deepcopy(metadata));v.safe=SimpleNamespace(safe_private_boundary=lambda *_:{'same':True},protected_metadata=lambda _:{'same':True},GBP_ENV=Path('/synthetic-env'))
    v.pf=SimpleNamespace(google_environment=lambda _:None,security_headers=lambda m:{'content_security_policy_sha256':m.csp})
    identity=v.m.BUSINESS.stat();v.proof={'private_boundary':{'same':True},'credential_boundary':{'same':True},'google_credential_metadata':{'same':True},'database_identity':[identity.st_dev,identity.st_ino],'database_metadata':metadata,'rows':retained.evidence(v.m.rows),'schema_sha256':v.m.schema,'public_inventory_sha256':r.digest(v.m.old_tree),'nginx_sha256':r.H(v.m.NGINX.read_bytes()),'active_nginx_config_sha256':r.H(b'# effective configuration\n'+v.m.NGINX.read_bytes()),'crm':copy.deepcopy(v.m.current['_runtime']),'backend_inventory_sha256':r.digest(v.m.backend),'backend_file_count':len(v.m.backend),'environment_sha256':r.digest(sorted(v.m.current['Config']['Env'])),'content_security_policy_sha256':CSP,'public_root':'/public/old'}
    v.manifest={};return v


def prepared(v):
    for name in ('release.py','preflight.py','manifest.json','payload.tar.gz'):(v.args.release/name).write_bytes(b'synthetic-public-tool')
    result=v.prepare();v.args.review_sha256=result.pop('receipt_sha256');return result


def test_static_prepare_and_switch_leave_runtime_api_csp_and_136_rows_exact(publisher):
    v=publisher;before=copy.deepcopy((v.m.current,v.m.rows,v.m.backend));data=v.m.BUSINESS.read_bytes();prepared(v);result=v.activate()
    assert result['stage']=='GOOGLE_PHOTO_PREVIEW_DEPLOYED_STATIC_VERIFIED' and result['static_only']
    assert result['container_changed_or_restarted'] is result['database_migration'] is result['csp_changed'] is False
    assert before==(v.m.current,v.m.rows,v.m.backend) and v.m.BUSINESS.read_bytes()==data and b'/public/new' in v.m.NGINX.read_bytes()
    assert not any(c[0]=='docker' for c in v.m.calls)


@pytest.mark.parametrize('failure',['reload-nginx','curl'])
def test_failure_restores_only_old_nginx_root_without_runtime_or_db_write(publisher,failure):
    v=publisher;prepared(v);before=copy.deepcopy((v.m.current,v.m.rows));fired=[False]
    def fail(argv):
        if argv[0]==failure and not fired[0]:fired[0]=True;raise RuntimeError('SYNTHETIC_STATIC_FAILURE')
    v.m.fault=fail
    with pytest.raises(RuntimeError,match='SYNTHETIC_STATIC_FAILURE'):v.activate()
    assert before==(v.m.current,v.m.rows) and b'/public/old' in v.m.NGINX.read_bytes()
    assert not any(c[0]=='docker' for c in v.m.calls)


def test_recovery_keeps_independent_owner_policy_and_picture_changes(publisher):
    v=publisher;prepared(v);fired=[False]
    def fail(argv):
        if argv[0]=='reload-nginx' and not fired[0]:fired[0]=True;v.m.rows['media_publication_images']['count']=2;raise RuntimeError('SYNTHETIC_INDEPENDENT_CHANGE')
    v.m.fault=fail
    with pytest.raises(RuntimeError,match='SYNTHETIC_INDEPENDENT_CHANGE'):v.activate()
    assert v.m.rows['media_publication_images']['count']==2 and b'/public/old' in v.m.NGINX.read_bytes()


@pytest.mark.parametrize('change',['restart','backend','schema','rows','csp','environment','nginx'])
def test_before_switch_any_unreviewed_runtime_data_or_csp_drift_is_refused(publisher,change):
    v=publisher;prepared(v);old=v.m.NGINX.read_bytes()
    if change=='restart':v.m.current['_runtime']['restart']=1
    elif change=='backend':v.m.backend['main.py']='0'*64
    elif change=='schema':v.m.schema='0'*64
    elif change=='rows':v.m.rows['media_publication_images']['count']=2
    elif change=='csp':v.m.csp='0'*64
    elif change=='environment':v.m.current['Config']['Env'].append('CHANGED=true')
    else:v.m.NGINX.write_bytes(old+b'# unreviewed change')
    with pytest.raises(RuntimeError):v.activate()
    assert b'/public/new' not in v.m.NGINX.read_bytes()


def test_unknown_nginx_change_after_reload_is_never_overwritten(publisher):
    v=publisher;prepared(v)
    def change(argv):
        if argv[0]=='reload-nginx':v.m.NGINX.write_bytes(v.m.NGINX.read_bytes()+b'# INDEPENDENT NGINX CHANGE')
    v.m.fault=change
    with pytest.raises(RuntimeError,match='UNKNOWN_NGINX_STATE_REQUIRES_REVIEW'):v.activate()
    assert b'INDEPENDENT NGINX CHANGE' in v.m.NGINX.read_bytes()


def test_missing_final_pins_refuse_before_loading_helpers(monkeypatch):
    monkeypatch.setattr(r,'SOURCE_SHA',None);monkeypatch.setattr(r,'protected_read',lambda *_:pytest.fail('read before pins'))
    with pytest.raises(RuntimeError,match='ACTUAL_REVIEWED_SOURCE_FRONTEND_AND_FREEZE_REQUIRED'):r.Release(SimpleNamespace())
