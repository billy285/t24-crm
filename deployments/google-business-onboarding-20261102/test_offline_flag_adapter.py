"""Strict one-flag projection into the frozen secret-isolation validator."""
import copy
import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
KEY='T24_GBP_ONBOARDING_WORKER_ENABLED'
def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
r=load(HERE/'release.py','onboarding_flag_adapter_release')
old=load(ROOT/'deployments/media-ops-management-20261031/release.py','onboarding_frozen_env_validator')

def info(rows=None):
    return {'Config':{'Env':['T24_GBP_ENABLED=false','T24_GBP_API_APPROVED=false','T24_GBP_SCHEDULER_ENABLED=false','STRIPE_AUTO_POSTING_ENABLED=false','STRIPE_HISTORY_DAILY_SCAN_ENABLED=false',*(rows if rows is not None else [KEY+'=false'])]},'Mounts':[],'HostConfig':{'NetworkMode':'none'}}

def verify(value):return r.Methods.verify_offline_environment(SimpleNamespace(_original_offline_validator=old.verify_disabled_environment),value)

def test_original_rejection_is_reproduced_then_one_false_flag_projection_passes_without_mutation():
    value=info();saved=copy.deepcopy(value)
    with pytest.raises(RuntimeError,match='OFFLINE_GOOGLE_SECRETS_REJECTED'):old.verify_disabled_environment(value)
    assert verify(value) is None and value==saved

@pytest.mark.parametrize('rows',[[],[KEY+'=true'],[KEY+'='],[KEY],[KEY+'=false',KEY+'=false'],[KEY+'=true',KEY+'=false'],[KEY+'=false',KEY+'=true']])
def test_missing_true_empty_malformed_and_duplicate_flag_fail_closed(rows):
    with pytest.raises(RuntimeError,match='EXACT_OFFLINE_ONBOARDING_WORKER_DISABLED_REQUIRED'):verify(info(rows))

@pytest.mark.parametrize('extra',['T24_GBP_ONBOARDING_WORKER_ENABLE=false','T24_GBP_ONBOARDING_WORKER_ENABLED_EXTRA=false','T24_GBP_CLIENT_SECRET=SYNTHETIC_SECRET','T24_GBP_TOKEN_KEY=SYNTHETIC_KEY','APP_AI_KEY=SYNTHETIC_KEY','OPENAI_API_KEY=SYNTHETIC_KEY','OTHER_PASSWORD=SYNTHETIC_PASSWORD'])
def test_near_names_and_real_credential_guards_are_not_projected_away(extra):
    value=info([KEY+'=false',extra]);saved=copy.deepcopy(value)
    with pytest.raises(RuntimeError):verify(value)
    assert value==saved

@pytest.mark.parametrize('attack',['network','mount','worker'])
def test_all_other_original_offline_guards_remain_unchanged(attack):
    value=info()
    if attack=='network':value['HostConfig']['NetworkMode']='bridge'
    elif attack=='mount':value['Mounts']=[{'Destination':'/run/secrets/synthetic'}]
    else:value['Config']['Env']=[x for x in value['Config']['Env'] if not x.startswith('STRIPE_AUTO_POSTING_ENABLED=')]+['STRIPE_AUTO_POSTING_ENABLED=true']
    with pytest.raises(RuntimeError):verify(value)


def test_final_r2_source_is_only_new_scope_adapter_and_call_site_delta():
    before=(HERE/'attempt1-release.py').read_bytes();assert hashlib.sha256(before).hexdigest()=='c07e2041379e5064d50b58d10a93717f6bda376737c4691ac3f7ce1cad6bc01a'
    current=(HERE/'attempt2-release.py').read_text()
    start=current.index('    def verify_offline_environment(self,info):\n');end=current.index('    def offline_args(self,data,image):\n',start)
    restored=current[:start]+current[end:]
    assert restored.count("SCOPE = 'google-business-onboarding-r2'")==1
    restored=restored.replace("SCOPE = 'google-business-onboarding-r2'","SCOPE = 'google-business-onboarding'",1)
    assert restored.count('self.verify_offline_environment(m.inspect(self.offline_name))')==1
    restored=restored.replace('self.verify_offline_environment(m.inspect(self.offline_name))','self.base.verify_disabled_environment(m.inspect(self.offline_name))',1)
    assert restored.encode()==before
