"""No remote commands executed; real local Git and in-memory loader checks."""
import copy
import importlib.util
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import urllib.request

import pytest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('scheduler_commands_author',HERE/'make_commands.py')
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
# Pending live deployment pins remain disabled; synthetic tests pin their own receipt.
@pytest.fixture(autouse=True)
def synthetic_receipt(monkeypatch):monkeypatch.setattr(m,'RECEIPT','e'*64)

CARRIER='a'*40;ATTEMPT='11111111-1111-4111-8111-111111111111';PLAN='b'*64


def render(monkeypatch,**changes):
    args={'carrier':CARRIER,'phase':'plan','attempt':ATTEMPT,'receipt':m.RECEIPT,'owner':1,'plan':None,'confirmed':False};args.update(changes)
    monkeypatch.setattr(m,'reviewed_core',lambda _:b"def dispatch(*args):return {'stage':'SYNTHETIC_ONLY','args':args}\n")
    return m.render(**args)


@pytest.mark.parametrize('values',[
    {'carrier':'main'}, {'carrier':'a'*39}, {'carrier':'A'*40}, {'carrier':'a'*40+';id'},
    {'phase':'exec'}, {'attempt':'../escape'}, {'attempt':ATTEMPT.upper().replace('1','A',1)},
    {'receipt':'0'*64}, {'owner':0}, {'owner':True}, {'owner':'1'},
    {'phase':'activate','plan':PLAN,'confirmed':False}, {'phase':'activate','plan':PLAN,'confirmed':1},
    {'phase':'activate','plan':None,'confirmed':True}, {'phase':'rollback','plan':PLAN,'confirmed':True},
    {'phase':'plan','plan':PLAN}, {'phase':'plan','confirmed':True},
])
def test_unapproved_arguments_rejected_before_core_or_git(monkeypatch,values):
    args={'carrier':CARRIER,'phase':'plan','attempt':ATTEMPT,'receipt':m.RECEIPT,'owner':1,'plan':None,'confirmed':False};args.update(values)
    monkeypatch.setattr(m,'reviewed_core',lambda _:pytest.fail('arguments rejected after source access'))
    with pytest.raises((RuntimeError,ValueError,TypeError)):m.render(**args)


@pytest.mark.parametrize('phase,plan,confirmed',[('plan',None,False),('activate',PLAN,True),('rollback',PLAN,False)])
def test_all_phases_are_small_isolated_and_exact(monkeypatch,phase,plan,confirmed):
    command=render(monkeypatch,phase=phase,plan=plan,confirmed=confirmed)
    assert len(command.encode())<8000 and len(__import__('base64').b64encode(command.encode()))<16000
    assert "sudo python3 -I -S -B - <<'PY'" in command
    assert '/'+CARRIER+'/' in command and '/core.py' in command
    assert command.index('os.geteuid()==0')<command.index('opener.open')
    assert 'ProxyHandler({})' in command and 'redirect_request' in command


@pytest.fixture
def carrier(tmp_path,monkeypatch):
    repo=tmp_path/'repo';repo.mkdir();(repo/'app').mkdir();(repo/'app'/'unchanged').write_text('source')
    def git(*args):return subprocess.check_output(['git',*args],cwd=repo,stderr=subprocess.PIPE)
    git('init','-q');git('config','user.email','synthetic@example.invalid');git('config','user.name','Synthetic Test')
    git('add','app');git('commit','-qm','synthetic source');source=git('rev-parse','HEAD').decode().strip()
    directory=repo/m.DIRECTORY;directory.mkdir(parents=True)
    names=['core.py','make_commands.py','test_core.py','test_commands.py','test_independent.py','README.md']
    members={}
    for name in names:
        blob=(HERE/name).read_bytes();(directory/name).write_bytes(blob);members[name]={'sha256':m.H(blob),'size':len(blob)}
    freeze={'stage':'SCHEDULER_CONFIG_TOOL_REVIEW_READY','source_sha':source,'deployed_sha256':m.RECEIPT,'members':members}
    (directory/'tool-freeze.json').write_text(json.dumps(freeze))
    git('add','.');git('commit','-qm','synthetic tools');commit=git('rev-parse','HEAD').decode().strip()
    monkeypatch.setattr(m,'HERE',directory);monkeypatch.setattr(m,'SOURCE',source)
    return SimpleNamespace(repo=repo,git=git,directory=directory,commit=commit)


def test_real_carrier_and_source_tree_positive_control(carrier):
    assert m.reviewed_core(carrier.commit)==(carrier.directory/'core.py').read_bytes()


@pytest.mark.parametrize('name',['core.py','make_commands.py','test_core.py','test_commands.py','test_independent.py','README.md','tool-freeze.json'])
def test_local_or_carrier_member_tampering_rejected(carrier,name):
    path=carrier.directory/name;path.write_bytes(path.read_bytes()+b'\n')
    with pytest.raises(RuntimeError):m.reviewed_core(carrier.commit)


def test_carrier_other_app_change_rejected(carrier):
    (carrier.repo/'app'/'unchanged').write_text('changed');carrier.git('add','.');carrier.git('commit','-qm','unapproved app')
    with pytest.raises(RuntimeError,match='CARRIER_APPLICATION_SOURCE_DRIFT'):m.reviewed_core(carrier.git('rev-parse','HEAD').decode().strip())


class Response:
    def __init__(self,blob,url,status=200):self.blob=blob;self.url=url;self.status=status;self.maximum=None
    def __enter__(self):return self
    def __exit__(self,*_):pass
    def geturl(self):return self.url
    def read(self,maximum):self.maximum=maximum;return self.blob[:maximum]


def execute_loader(command,monkeypatch,mode=None):
    calls=[];body=b"def dispatch(*args):return {'stage':'SYNTHETIC_ONLY','args':args}\n"
    url='https://raw.githubusercontent.com/billy285/t24-crm/'+CARRIER+'/'+m.DIRECTORY+'/core.py'
    response=Response(body+(b'X' if mode=='oversize' else b''),url)
    if mode=='hash':response.blob=body[:-2]+b'X\n'
    if mode=='redirect':response.url='https://other.invalid/source'
    if mode=='status':response.status=302
    def opener(*handlers):
        def open(request,timeout):
            calls.append((request.full_url,timeout));return response
        return SimpleNamespace(open=open)
    monkeypatch.setattr(urllib.request,'build_opener',opener)
    monkeypatch.setattr(__import__('os'),'geteuid',lambda:1 if mode=='uid' else 0)
    monkeypatch.setattr(__import__('socket'),'gethostname',lambda:'other' if mode=='host' else m.HOST)
    monkeypatch.setattr(__import__('resource'),'setrlimit',lambda *_:None)
    monkeypatch.setattr(sys,'dont_write_bytecode',True)
    code=command.split("<<'PY'\n",1)[1].rsplit('PY\n',1)[0]
    try:exec(compile(code,'<synthetic-loader>','exec'),{})
    except SystemExit as error:assert error.code==1;return calls,response,False
    return calls,response,True


def test_actual_generated_loader_dispatches_only_exact_bytes(monkeypatch,capsys):
    command=render(monkeypatch);calls,response,okay=execute_loader(command,monkeypatch)
    result=json.loads(capsys.readouterr().out);assert okay and result['stage']=='SYNTHETIC_ONLY'
    assert result['args']==['plan',ATTEMPT,m.RECEIPT,1,None,False] and len(calls)==1
    assert response.maximum==len(response.blob)+1


@pytest.mark.parametrize('mode',['uid','host','hash','oversize','redirect','status'])
def test_generated_loader_rejects_root_host_bytes_redirect_without_dispatch(monkeypatch,capsys,mode):
    command=render(monkeypatch);calls,_,okay=execute_loader(command,monkeypatch,mode)
    output=capsys.readouterr().out;assert not okay and 'SYNTHETIC_ONLY' not in output
    assert json.loads(output)['stage']=='SCHEDULER_CONFIG_REJECTED'
    if mode in {'uid','host'}:assert calls==[]
