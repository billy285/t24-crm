"""Exact carrier/AST transport wrapper tests; no Git/server/browser operations."""
import ast
import base64
import importlib.util
import json
from pathlib import Path
import shutil
import pytest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('meta_transport_command_author_test',HERE/'make_transport_commands.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
CARRIER='b'*40


def summary():
    c=m.c
    return {'stage':'META_ACTIVATION_BASELINE_CAPTURED','sha256':m.BASELINE_SHA,'path':str(c.ROOT/'baseline.json'),'table_count':141,'source_sha':c.SOURCE_SHA,'frontend_version':c.FRONTEND,'schema_revision':c.SCHEMA_REVISION,'runtime':{'id':c.ORIGINAL_ID,'image':c.IMAGE,'restart':0},'meta_environment_keys_absent':True,'google_scheduler_enabled':True,'google_scheduler_activation_from':c.ACTIVATION_FROM,'business_writes':False,'credential_content_read':False,'provider_requests':False,'runtime_changed':False}


@pytest.fixture
def carrier(tmp_path,monkeypatch):
    for name in m.TOOL_PINS:shutil.copyfile(HERE/name,tmp_path/name)
    monkeypatch.setattr(m,'HERE',tmp_path);calls=[]
    def git(args):
        calls.append(args);assert args[0]=='git'
        if args[1]=='rev-parse':return b'SYNTHETIC_SAME_APP_TREE\n'
        assert args[1]=='show';ref,path=args[2].split(':',1);assert ref==CARRIER and path.startswith(m.DIRECTORY+'/');return (HERE/path.rsplit('/',1)[1]).read_bytes()
    monkeypatch.setattr(m.subprocess,'check_output',git);return tmp_path,calls


def embedded(command,marker):return command.split("<<'"+marker+"'\n",1)[1].rsplit(marker+'\n',1)[0]


def test_install_and_prepare_wrappers_use_exact_three_committed_tools_only(carrier):
    commands,pins=m.generate(CARRIER,summary());assert set(commands)=={'transport-tools-install-command.sh','transport-prepare-command.sh'}
    assert set(pins['tool_files'])=={'core.py','baseline.py','transport.py'} and pins['executed'] is False and not pins['ciphertext_included']
    install=commands['transport-tools-install-command.sh'];prepare=commands['transport-prepare-command.sh']
    assert len(install.encode())<11000 and len(prepare.encode())<11000
    ast.parse(embedded(install,'META_TOOLS'));ast.parse(embedded(prepare,'META_TRANSPORT'))
    assert install.index('os.geteuid()==0')<install.index('opener.open') and 'ProxyHandler({})' in install and 'redirect_request' in install
    assert "root.mkdir(mode=0o700)" in install and "O_EXCL|os.O_NOFOLLOW,0o600" in install and 'runtime.env' not in install
    assert "tools-transport-v1" in prepare and "modules['transport.py'].prepare(baseline.verify)" in prepare
    assert "sys.modules['core']=module" in prepare and "baseline.configure(core)" in prepare
    assert 'urllib' not in prepare and 'subprocess' not in prepare
    assert all('SYNTHETIC_META_SECRET' not in value for value in commands.values())


def test_install_wrapper_contains_ciphertext_only_no_plaintext_secret_argument(carrier):
    sealed=base64.b64encode(b'x'*384).decode();commands,pins=m.generate(CARRIER,summary(),transfer_id='c'*32,ciphertext=sealed)
    assert set(commands)=={'transport-tools-install-command.sh','transport-prepare-command.sh','transport-install-command.sh'}
    install=commands['transport-install-command.sh'];code=embedded(install,'META_TRANSPORT');tree=ast.parse(code)
    constants={x.value for x in ast.walk(tree) if isinstance(x,ast.Constant) and isinstance(x.value,str)}
    assert 'c'*32 in constants and sealed in constants and "modules['transport.py'].receive(baseline.verify," in code
    assert '--secret' not in install and pins['ciphertext_included'] is True


@pytest.mark.parametrize('file',['core.py','baseline.py','transport.py'])
def test_any_unreviewed_tool_byte_change_refused_before_carrier_install(carrier,file):
    path=carrier[0]/file;path.write_bytes(path.read_bytes()+b'\n')
    with pytest.raises(RuntimeError,match='EXACT_REVIEWED_TRANSPORT_BYTES_REQUIRED'):m.generate(CARRIER,summary())


def test_same_app_tree_is_required(carrier,monkeypatch):
    calls=[b'approved',b'other'];monkeypatch.setattr(m.subprocess,'check_output',lambda args:calls.pop(0))
    with pytest.raises(RuntimeError,match='TRANSPORT_CARRIER_APP_TREE_DRIFT'):m.generate(CARRIER,summary())


def test_committed_member_mismatch_refused(carrier,monkeypatch):
    run=m.subprocess.check_output
    monkeypatch.setattr(m.subprocess,'check_output',lambda args:b'OTHER' if args[1]=='show' else run(args))
    with pytest.raises(RuntimeError,match='EXACT_COMMITTED_TRANSPORT_MEMBER_REQUIRED'):m.generate(CARRIER,summary())


@pytest.mark.parametrize('field,value',[('sha256','a'*64),('path','/tmp/wrong'),('table_count',140),('meta_environment_keys_absent',False),('google_scheduler_enabled',False),('google_scheduler_activation_from','wrong'),('runtime_changed',True),('credential_content_read',True)])
def test_actual_readonly_baseline_scope_is_mandatory(carrier,field,value):
    sample=summary();sample[field]=value
    with pytest.raises(RuntimeError):m.generate(CARRIER,sample)


@pytest.mark.parametrize('transfer,ciphertext',[('c'*32,None),(None,base64.b64encode(b'x'*384).decode()),('bad',base64.b64encode(b'x'*384).decode()),('c'*32,'bad'),('c'*32,base64.b64encode(b'x'*383).decode())])
def test_dynamic_install_requires_exact_transfer_and_rsa_ciphertext(carrier,transfer,ciphertext):
    with pytest.raises(RuntimeError):m.generate(CARRIER,summary(),transfer_id=transfer,ciphertext=ciphertext)


def test_unknown_runtime_pins_fail_before_git_or_code_read(carrier,monkeypatch):
    monkeypatch.setattr(m.c,'CONFIG_ID',None);monkeypatch.setattr(m.subprocess,'check_output',lambda _:pytest.fail('git before knownpins'))
    with pytest.raises(RuntimeError,match='ACTUAL_USER_CONFIG_VERSION_AND_REVIEW_FREEZE_REQUIRED'):m.generate(CARRIER,summary())
