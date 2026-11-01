"""Independent new AI transport attacks; synthetic HTTPX streams, no network."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[2]
BACKEND=ROOT/'app/backend'
if str(BACKEND) not in sys.path:sys.path.insert(0,str(BACKEND))
from services import media_monthly as monthly


def runtime(**overrides):
    return SimpleNamespace(enabled=True,api_key='SYNTHETIC-SECRET-KEY',base_url='https://api.example.com/v1',provider='synthetic',model='synthetic-text',**overrides)


def snapshot():
    return {'public_facts':{'public_name':'Synthetic Merchant','location':'Houston','highlights':['Confirmed storefront']},
        'menu_items':[{'id':4,'name':'Confirmed Dish','category':'Menu','selling_points':'Confirmed only','price':'9.00','internal_note':'PRIVATE-MENU-NOTE'}],
        'rules':{'language':'en','include_prices':False,'forbidden_claims':['best in town']},
        'slots':[{'slot_id':'slot1','menu_item_ids':[4],'proposed_publish_at':'PRIVATE-DATE-NOT-AI'}],
        'images':[{'private_bytes':'PRIVATE-IMAGE-BYTES','file_url':'PRIVATE-URL','title':'PRIVATE-TITLE'}],
        'customer_name':'PRIVATE-CRM-ALIAS','finances':'PRIVATE-COMPANY-FINANCE','contacts':'PRIVATE-CONTACT'}


@pytest.fixture
def fake(monkeypatch):
    state=SimpleNamespace(status=200,chunks=[json.dumps({'choices':[{'finish_reason':'stop','message':{'content':'SYNTHETIC-CONTENT'}}]}).encode()],requests=[],client_options=[],transport_options=[],consumed=0,closed=0,error=None,headers={})
    class Response:
        status_code=200
        async def aiter_bytes(self,chunk_size):
            assert chunk_size==65536
            for chunk in state.chunks:
                state.consumed+=1
                if isinstance(chunk,Exception):raise chunk
                yield chunk
    class Stream:
        async def __aenter__(self):
            if state.error:raise state.error
            value=Response();value.status_code=state.status;value.headers=monthly.httpx.Headers(state.headers);return value
        async def __aexit__(self,*args):state.closed+=1
    class Client:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):state.closed+=1
        def stream(self,method,url,**kwargs):state.requests.append((method,url,kwargs));return Stream()
    def client(**kwargs):state.client_options.append(kwargs);return Client()
    def transport(**kwargs):state.transport_options.append(kwargs);return object()
    monkeypatch.setattr(monthly.httpx,'AsyncClient',client);monkeypatch.setattr(monthly.httpx,'AsyncHTTPTransport',transport)
    return state


@pytest.mark.asyncio
async def test_one_post_without_retries_redirects_proxy_private_inputs_or_secret_logs(fake,caplog):
    assert await monthly.call_ai(runtime(),snapshot())=='SYNTHETIC-CONTENT'
    assert len(fake.requests)==len(fake.client_options)==len(fake.transport_options)==1
    method,url,body=fake.requests[0];assert method=='POST' and url=='https://api.example.com/v1/chat/completions'
    assert fake.transport_options==[{'retries':0}]
    options=fake.client_options[0];assert options['follow_redirects'] is False and options['trust_env'] is False
    assert options['timeout'].connect==8 and options['timeout'].read==100
    payload=json.dumps(body['json']);assert 'Confirmed Dish' in payload and 'Confirmed storefront' in payload and 'slot1' in payload
    assert 'PRIVATE-' not in payload and '9.00' not in payload and 'SYNTHETIC-SECRET-KEY' not in payload
    assert body['headers']['Authorization']=='Bearer SYNTHETIC-SECRET-KEY' and fake.closed==2
    assert not caplog.records


@pytest.mark.asyncio
@pytest.mark.parametrize('status,unknown',[(302,False),(400,False),(401,False),(408,True),(429,True),(500,True)])
async def test_provider_status_is_sanitized_single_attempt_and_never_reads_error_body(fake,caplog,status,unknown):
    fake.status=status;fake.chunks=[b'PRIVATE-PROVIDER-ERROR']
    with pytest.raises(monthly.MonthlyAIError) as error:await monthly.call_ai(runtime(),snapshot())
    assert error.value.unknown is unknown and str(error.value)=='monthly_ai_unavailable'
    assert len(fake.requests)==1 and fake.consumed==0 and fake.closed==2 and not caplog.records


@pytest.mark.asyncio
async def test_oversized_stream_stops_before_following_chunk_and_is_not_logged(fake,caplog):
    fake.chunks=[b'x'*65536]*8+[b'PRIVATE-NEVER-CONSUMED']
    with pytest.raises(monthly.MonthlyAIError) as error:await monthly.call_ai(runtime(),snapshot())
    assert error.value.unknown is False and fake.consumed==8 and len(fake.requests)==1 and fake.closed==2 and not caplog.records


@pytest.mark.asyncio
@pytest.mark.parametrize('value',[
    {'choices':[]}, {'choices':[{'message':{'content':'x'}},{'message':{'content':'x'}}]},
    {'choices':[{'finish_reason':'length','message':{'content':'x'}}]},
    {'choices':[{'finish_reason':'stop','message':{'content':None}}]},
    {'choices':[{'finish_reason':'stop','message':{'content':['not text']}}]},
    {'choices':[{'finish_reason':'stop','message':{'content':'x'*60001}}]},
])
async def test_malformed_truncated_multichoice_or_unbounded_content_is_rejected(fake,value):
    fake.chunks=[json.dumps(value).encode()]
    with pytest.raises(monthly.MonthlyAIError):await monthly.call_ai(runtime(),snapshot())
    assert len(fake.requests)==1 and fake.closed==2


@pytest.mark.asyncio
async def test_transport_error_is_unknown_without_retry_or_raw_error(fake,caplog):
    fake.error=monthly.httpx.ConnectError('PRIVATE-SENSITIVE-NETWORK-ERROR')
    with pytest.raises(monthly.MonthlyAIError) as error:await monthly.call_ai(runtime(),snapshot())
    assert error.value.unknown is True and str(error.value)=='monthly_ai_unavailable' and len(fake.requests)==1
    assert not caplog.records


@pytest.mark.asyncio
async def test_absent_resolved_key_cannot_fallback_or_contact_provider(fake):
    value=runtime();value.api_key=''
    with pytest.raises(monthly.MonthlyAIError):await monthly.call_ai(value,snapshot())
    assert fake.requests==[] and fake.client_options==[]


@pytest.mark.asyncio
@pytest.mark.parametrize('url',['https://localhost/v1','https://test.internal/v1','https://test.local/v1','https://single/v1','http://api.example.com/v1','https://127.0.0.1/v1','https://10.0.0.1/v1','https://user:pass@api.example.com/v1','https://api.example.com:8443/v1'])
async def test_runtime_rejects_internal_or_credential_bearing_destinations(monkeypatch,url):
    value=runtime();value.base_url=url
    async def resolve(db):return value
    monkeypatch.setattr(monthly,'resolve_ai_runtime_config',resolve)
    with pytest.raises(Exception) as error:await monthly._runtime(None)
    assert getattr(error.value,'status_code',None)==503


@pytest.mark.asyncio
@pytest.mark.parametrize('key',['','   ',None])
async def test_runtime_public_configuration_requires_actual_resolved_key(monkeypatch,key):
    value=runtime();value.api_key=key
    async def resolve(db):return value
    monkeypatch.setattr(monthly,'resolve_ai_runtime_config',resolve)
    _,public=await monthly._runtime(None)
    assert public['enabled'] is False and public['is_configured'] is False


@pytest.mark.asyncio
@pytest.mark.parametrize('headers',[{'Content-Encoding':'gzip'},{'Content-Encoding':'br'},{'Content-Length':'512001'}])
async def test_encoded_or_advertised_oversize_body_rejected_before_read(fake,headers):
    fake.headers=headers
    with pytest.raises(monthly.MonthlyAIError):await monthly.call_ai(runtime(),snapshot())
    assert fake.consumed==0 and len(fake.requests)==1
    assert fake.requests[0][2]['headers']['Accept-Encoding']=='identity'


@pytest.mark.asyncio
async def test_oversized_confirmed_payload_is_rejected_without_http_or_fact_truncation(fake):
    data=snapshot();data['menu_items'][0]['selling_points']='真实菜单'*20000
    with pytest.raises(Exception) as error:await monthly.call_ai(runtime(),data)
    assert getattr(error.value,'status_code',None)==422 and fake.requests==[]
    assert data['menu_items'][0]['selling_points']=='真实菜单'*20000
