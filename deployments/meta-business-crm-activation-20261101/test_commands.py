"""Immutable carrier simulations: parse emitted code, never execute commands."""
import ast
import base64
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('meta_crm_rotation_commands_test', HERE/'make_commands.py')
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)


@pytest.fixture
def pins(monkeypatch):
    c = SimpleNamespace(HOST='reviewed-host', ROOT=Path('/opt/t24-crm/releases/independent-meta-crm-rotation'), SOURCE_SHA='1'*40,
        FRONTEND='58d2c585210f', SCHEMA_REVISION='bde8da01f247', ORIGINAL_ID='2'*64, IMAGE='sha256:'+'3'*64,
        CONFIG_ID='1146714154579519', GRAPH_VERSION='v26.0', CONFIG_FREEZE_SHA='4'*64, ACTIVATION_FROM='2026-10-30T19:42:04Z')
    b = SimpleNamespace(BASELINE_SHA='5'*64)
    monkeypatch.setattr(g, 'identities', lambda: (c,b))
    return c,b


def summary(pins):
    c,b=pins
    return {'stage':'META_CRM_ROTATION_BASELINE_CAPTURED','sha256':b.BASELINE_SHA,'path':str(c.ROOT/'baseline.json'),
        'source_sha':c.SOURCE_SHA,'frontend_version':c.FRONTEND,'schema_revision':c.SCHEMA_REVISION,'table_count':141,
        'key_rotation_eligibility':{'meta_business_connections':0,'meta_business_assets':0,'meta_business_bindings':0,'meta_business_requests':0,
            'oauth_flow_count':3,'unconsumed_or_encrypted_flow_count':0,'safe_to_rotate':True},
        'google_scheduler_enabled':True,'google_scheduler_activation_from':c.ACTIVATION_FROM,
        'business_writes':False,'credential_file_content_read':False,'provider_requests':False,'runtime_changed':False,
        'runtime':{'id':c.ORIGINAL_ID,'image':c.IMAGE,'restart':0,'config':'6'*64}}


@pytest.fixture
def carrier(monkeypatch):
    def git(argv):
        assert argv[0]=='git'
        if argv[1]=='rev-parse':return b'exact-application-tree\n'
        assert argv[1]=='show'; name=argv[2].split(':',1)[1].removeprefix(g.DIRECTORY+'/')
        return (HERE/name).read_bytes()
    monkeypatch.setattr(g.subprocess,'check_output',git)
    return 'a'*40


def python_body(command):return command.split("<<'META_CRM_ROTATION'\n",1)[1].rsplit('\nMETA_CRM_ROTATION',1)[0]


def test_exact_carrier_generates_small_commands_without_inline_credentials(pins,carrier):
    commands,report=g.generate(carrier,summary(pins))
    assert set(commands)=={'stage-command.sh','prepare-command.sh','activate-command.sh','recover-command.sh'}
    for name,command in commands.items():
        assert len(command.encode())<11000;ast.parse(python_body(command))
        assert 'tools-activation-v1' in command and "sys.modules['core']=module" in command
        assert report['commands'][name]==g.H(command.encode())
        assert 'APP_SECRET=' not in command and 'TOKEN_KEY=' not in command
    stage=commands['stage-command.sh']
    assert 'ProxyHandler({})' in stage and 'NoRedirect' in stage and "verify('tool-staging-before')" in stage
    assert 'baseline.json' not in stage.split('c.write(',1)[1] and 'ENV_FILE' not in stage
    assert report['members']=={name:{'sha256':g.H((HERE/name).read_bytes()),'bytes':(HERE/name).stat().st_size} for name in g.MEMBERS}
    assert report['executed'] is False


@pytest.mark.parametrize('mutation',['tree','member'])
def test_carrier_tree_and_member_drift_rejected(pins,carrier,monkeypatch,mutation):
    real=g.subprocess.check_output
    def altered(argv):
        if mutation=='member' and argv[1]=='show':return real(argv)+b'changed'
        if mutation=='tree' and argv[1]=='rev-parse' and argv[2].startswith(carrier):return b'other-app\n'
        return real(argv)
    monkeypatch.setattr(g.subprocess,'check_output',altered)
    with pytest.raises(RuntimeError,match='CARRIER_APPLICATION_TREE_DRIFT|EXACT_COMMITTED_TOOL_REQUIRED'):g.generate(carrier,summary(pins))


@pytest.mark.parametrize('key,value',[('sha256','b'*64),('table_count',140),('source_sha','b'*40),('credential_file_content_read',True),
    ('key_rotation_eligibility',{'safe_to_rotate':True}),('google_scheduler_enabled',False)])
def test_wrong_actual_baseline_rejected(pins,carrier,key,value):
    row=summary(pins);row[key]=value
    with pytest.raises(RuntimeError,match='EXACT_ACTUAL_BASELINE_SUMMARY_REQUIRED'):g.generate(carrier,row)


@pytest.mark.parametrize('key,value',[('id','b'*64),('image','sha256:'+'b'*64),('restart',1),('config','not-hash')])
def test_original_runtime_drift_rejected(pins,carrier,key,value):
    row=summary(pins);row['runtime'][key]=value
    with pytest.raises(RuntimeError,match='EXACT_CURRENT_ORIGINAL_RUNTIME_REQUIRED'):g.generate(carrier,row)


def test_receive_wrapper_only_bounded_canonical_ciphertext(pins,carrier):
    _,report=g.generate(carrier,summary(pins));cipher=base64.b64encode(bytes(384)).decode()
    command=g.entry_command(report['members'],'receive',transfer_id='a'*32,ciphertext=cipher)
    ast.parse(python_body(command));assert len(command.encode())<11000 and cipher in command
    assert 'APP_SECRET=' not in command and 'TOKEN_KEY=' not in command
    for value in ('not-ciphertext',base64.b64encode(bytes(383)).decode(),cipher+'\n'):
        with pytest.raises(RuntimeError):g.entry_command(report['members'],'receive',transfer_id='a'*32,ciphertext=value)
    with pytest.raises(RuntimeError):g.entry_command(report['members'],'receive',transfer_id='wrong',ciphertext=cipher)
    with pytest.raises(RuntimeError):g.entry_command(report['members'],'activate',transfer_id='a'*32,ciphertext=cipher)


def test_tool_pin_dictionary_cannot_retarget(pins,carrier):
    _,report=g.generate(carrier,summary(pins));report['members']['baseline.py']['sha256']='b'*64
    with pytest.raises(RuntimeError,match='EXACT_CURRENT_FOUR_TOOL_PINS_REQUIRED'):g.entry_command(report['members'],'activate')


def test_unverified_configuration_still_fails_closed(monkeypatch):
    real=g.importlib.util.spec_from_file_location
    def missing(name,path):
        spec=real(name,path);execute=spec.loader.exec_module
        def load(module):
            execute(module)
            if str(path).endswith('/core.py'):module.CONFIG_ID=None
        spec.loader.exec_module=load;return spec
    monkeypatch.setattr(g.importlib.util,'spec_from_file_location',missing)
    with pytest.raises(RuntimeError,match='ACTUAL_NEW_APP_USER_CONFIG_VERSION_AND_REVIEW_REQUIRED'):g.identities()
