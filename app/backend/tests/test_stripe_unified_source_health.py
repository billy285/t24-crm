"""Explicit new-sale bridge and worker observations; isolated SQLite/fake provider only."""
import asyncio
import copy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from backend.tests.test_stripe_history_reconciliation import history_api, sale_api, bind, sync, headers, API, START
from backend.tests.test_stripe_auto_posting import future_invoice, save
from models.deals import Deals
from models.payments import Payments
from models.sales_deal_handoffs import SalesDealHandoff
from models.sales_deal_payments import SalesPaymentRequest, SalesReceiptEvidence, SalesStripeObservation
from models.stripe_auto_posting import StripeAutoPostingPolicy as Policy, StripeAutoPostingJob as Job
from models.stripe_history_reconciliation import StripeHistoryBinding as Binding, StripeHistoryPosting as Posting, StripeHistoryPreview as Preview
from models.subscriptions import Subscriptions
from services import stripe_auto_posting as auto, stripe_history_reconciliation as history
from services.sales_payment_catalog import approved_link

AUTO = API + '/auto-posting'


async def seed_source(sessions):
    plan = {'id': 1, 'business_line_id': 1, 'product_id': 1, 'name': 'Synthetic Frozen Service',
        'plan_code': 't24-managed-basic-stripe-auto-monthly-202610', 'standard_price': 198,
        'default_currency': 'USD', 'default_billing_cycle': 'monthly', 'required_collection_method': 'stripe_auto'}
    paid = datetime.fromtimestamp(START + 100, timezone.utc)
    async with sessions() as db:
        subscription = await db.get(Subscriptions, 100)
        subscription.deal_id = 900
        db.add(Deals(id=900, customer_id=100, engagement_id=100, business_line_id=1, product_id=1,
            product_plan_id=1, product_type='managed_service', package_name='Synthetic Frozen Service', deal_amount=198, is_paid=True))
        db.add(Payments(id=900, customer_id=100, customer_name='Synthetic History100', source_deal_id=900,
            engagement_id=100, business_line_id=1, product_id=1, product_name='Synthetic Frozen Service',
            income_type='management_fee',
            amount_due=198, amount_paid=198, outstanding_amount=0, currency='USD', payment_date=paid,
            payment_method='stripe', payment_mode='subscription_auto', transaction_reference='in_history100', user_id='1'))
        db.add(SalesDealHandoff(id=900, lead_id=900, customer_id=100, engagement_id=100, deal_id=900, subscription_id=100,
            idempotency_key='synthetic-unified-source900', payload_digest='a'*64, catalog_token='b'*64,
            plan_snapshot=plan, source_snapshot={}, amount=198, currency='USD', collection_method='stripe_auto',
            operations_owner_employee_id=13, operations_owner_name='Synthetic Ops', operations_status='pending',
            payment_status='paid', payment_id=900, payment_confirmed_by_id=1, payment_confirmed_at=paid,
            registered_by_id=1, registered_by_name='Synthetic Owner'))
        await db.flush()
        db.add(SalesPaymentRequest(id=900, handoff_id=900, reference='t24_'+'s'*43, link_snapshot=approved_link(plan), created_by_id=1))
        await db.flush()
        db.add(SalesStripeObservation(id=900, request_id=900, session_id='cs_synthetic900', subscription_id='sub_history100',
            invoice_id='in_history100', payment_intent_id='pi_history100', status='paid_observed', match_issues=[],
            service_minor=19800, tax_minor=1733, gross_minor=21533, currency='USD', paid_at=paid, latest_event_at=paid))
        await db.flush()
        db.add(SalesReceiptEvidence(id=900, handoff_id=900, observation_id=900, transaction_reference_digest='c'*64,
            service_minor=19800, tax_minor=1733, gross_minor=21533, fee_minor=650, net_minor=20883,
            currency='USD', payment_date='2026-10-01', verified_by_id=1, verified_by_name='Synthetic Owner'))
        await db.commit()


def preview_payload(**changes):
    return {'crm_subscription_id': 100, 'stripe_subscription_id': 'sub_history100', 'sync_from': '2026-09-01',
        'income_type': 'management_fee', 'source_handoff_id': 900, **changes}


async def new_binding(client):
    preview = await client.post(API+'/bindings/preview', headers=headers(1), json=preview_payload())
    assert preview.status_code == 200, preview.text
    data = preview.json()
    result = await client.post(API+'/bindings', headers=headers(1), json={'token':data['token'], 'owner_verified':True,
        'accepted_warning_codes':[row['code'] for row in data['warnings']]})
    assert result.status_code == 200, result.text
    return result.json()['binding']


@pytest.mark.asyncio
async def test_explicit_new_source_is_discovered_but_never_defaults_to_auto_or_changes_old_receipt(history_api):
    client,sessions,fake = history_api
    await seed_source(sessions)
    listed = (await client.get(API+'/crm-services', headers=headers(1))).json()['items']
    item = next(row for row in listed if row['crm_subscription_id']==100)
    assert item['source_ready'] is True and item['binding_source']=='sales_handoff'
    assert item['source_handoff_id']==900 and item['stripe_subscription_id']=='sub_history100'
    assert item['source_income_type']=='management_fee'
    assert fake.calls==[]
    legacy = preview_payload();legacy.pop('source_handoff_id')
    assert (await client.post(API+'/bindings/preview',headers=headers(1),json=legacy)).status_code==409
    binding = await new_binding(client)
    assert binding['binding_source']=='sales_handoff' and binding['source_handoff_id']==900
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Policy))==0
        assert await db.scalar(select(func.count()).select_from(Job))==0
        assert await db.scalar(select(func.count()).select_from(Payments))==1
        assert (await db.get(Payments,900)).amount_paid==198
        assert await history.binding_context_matches(db,await db.get(Binding,binding['id']))
    assert (await client.post(API+'/bindings/preview',headers=headers(1),json=preview_payload())).status_code==409


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['unpaid','wrong_customer','wrong_project','wrong_plan','wrong_subscription','wrong_link','manual_receipt','foreign_payment','foreign_payment_business_line','foreign_payment_product','missing_income','multiple_observations','wrong_remote_price'])
async def test_new_source_requires_complete_unique_verified_same_customer_chain(history_api,change):
    client,sessions,fake = history_api
    await seed_source(sessions)
    async with sessions() as db:
        handoff=await db.get(SalesDealHandoff,900)
        if change=='unpaid':handoff.payment_status='pending'
        if change=='wrong_customer':handoff.customer_id=101
        if change=='wrong_project':handoff.engagement_id=101
        if change=='wrong_plan':handoff.plan_snapshot={**handoff.plan_snapshot,'id':999}
        if change=='wrong_subscription':(await db.get(SalesStripeObservation,900)).subscription_id='sub_other'
        if change=='wrong_link':(await db.get(SalesPaymentRequest,900)).link_snapshot={}
        if change=='manual_receipt':(await db.get(SalesReceiptEvidence,900)).observation_id=None
        if change=='foreign_payment':(await db.get(Payments,900)).customer_id=101
        if change=='foreign_payment_business_line':(await db.get(Payments,900)).business_line_id=None
        if change=='foreign_payment_product':(await db.get(Payments,900)).product_id=None
        if change=='missing_income':(await db.get(Payments,900)).income_type=None
        if change=='multiple_observations':db.add(SalesStripeObservation(id=901,request_id=900,session_id='cs_second',subscription_id='sub_history100',status='paid_observed',match_issues=[],latest_event_at=datetime.now(timezone.utc)))
        await db.commit()
    if change=='wrong_remote_price':fake.subscription_rows['sub_history100']['items']['data'][0]['price']['unit_amount']=19900
    response=await client.post(API+'/bindings/preview',headers=headers(1),json=preview_payload())
    assert response.status_code==409,response.text
    async with sessions() as db:assert await db.scalar(select(func.count()).select_from(Binding))==0


@pytest.mark.asyncio
async def test_new_source_cannot_reclassify_income_and_does_not_reveal_or_call_provider_for_nonowner(history_api):
    client,sessions,fake=history_api
    await seed_source(sessions)
    for actor in (11,13,15,17):
        assert (await client.post(API+'/bindings/preview',headers=headers(actor),json=preview_payload())).status_code==403
    assert fake.calls==[]
    assert (await client.post(API+'/bindings/preview',headers=headers(1),json=preview_payload(income_type='website_fee'))).status_code==409
    assert fake.calls==[]


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation', ['bank_kind', 'other_kind', 'missing_keys', 'wrong_field_type', 'bad_date'])
async def test_binding_tokens_cannot_reuse_bank_or_malformed_previews(history_api, mutation):
    client,sessions,fake=history_api
    response=await client.post(API+'/bindings/preview',headers=headers(1),json={
        'crm_subscription_id':100,'stripe_subscription_id':'sub_history100','sync_from':'2026-09-01','income_type':'management_fee'})
    assert response.status_code==200,response.text
    data=response.json()
    async with sessions() as db:
        preview=await db.get(Preview,data['token'])
        snapshot=copy.deepcopy(preview.snapshot)
        assert snapshot['kind']=='subscription_binding_preview'
        if mutation=='bank_kind':snapshot['kind']='bank_statement_match_preview'
        if mutation=='other_kind':snapshot['kind']='some_other_owner_preview'
        if mutation=='missing_keys':snapshot={'sync_from':'2026-09-01'}
        if mutation=='wrong_field_type':snapshot['income_type']=[]
        if mutation=='bad_date':snapshot['sync_from']='not-a-date'
        preview.snapshot=snapshot
        await db.commit()
    fake.calls.clear()
    result=await client.post(API+'/bindings',headers=headers(1),json={'token':data['token'],'owner_verified':True,
        'accepted_warning_codes':[row['code'] for row in data['warnings']]})
    assert result.status_code==409,result.text
    assert fake.calls==[]
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Binding))==0
        assert (await db.get(Preview,data['token'])).binding_id is None


@pytest.mark.asyncio
async def test_complete_legacy_binding_preview_without_kind_remains_usable(history_api):
    client,sessions,_=history_api
    data=(await client.post(API+'/bindings/preview',headers=headers(1),json={
        'crm_subscription_id':100,'stripe_subscription_id':'sub_history100','sync_from':'2026-09-01','income_type':'management_fee'})).json()
    async with sessions() as db:
        preview=await db.get(Preview,data['token'])
        preview.snapshot={key:value for key,value in preview.snapshot.items() if key not in {'kind','source_origin'}}
        await db.commit()
    result=await client.post(API+'/bindings',headers=headers(1),json={'token':data['token'],'owner_verified':True,
        'accepted_warning_codes':[row['code'] for row in data['warnings']]})
    assert result.status_code==200,result.text
    assert result.json()['binding']['binding_source']=='history'


@pytest.mark.asyncio
async def test_source_changes_between_preview_confirm_and_after_binding_never_keep_authority(history_api):
    client,sessions,_=history_api
    await seed_source(sessions)
    data=(await client.post(API+'/bindings/preview',headers=headers(1),json=preview_payload())).json()
    async with sessions() as db:(await db.get(SalesStripeObservation,900)).match_issues=['scope_changed'];await db.commit()
    assert (await client.post(API+'/bindings',headers=headers(1),json={'token':data['token'],'owner_verified':True,'accepted_warning_codes':[]})).status_code==409
    async with sessions() as db:(await db.get(SalesStripeObservation,900)).match_issues=[];await db.commit()
    binding=await new_binding(client)
    async with sessions() as db:
        (await db.get(SalesReceiptEvidence,900)).observation_id=None;await db.commit()
        assert not await history.binding_context_matches(db,await db.get(Binding,binding['id']))


@pytest.mark.asyncio
async def test_new_source_reuses_three_service_trial_explicit_authorization_cutoff_and_once_only_post(history_api,monkeypatch):
    client,sessions,fake=history_api
    await seed_source(sessions)
    clock=[datetime(2026,10,21,3,tzinfo=timezone.utc)]
    monkeypatch.setattr(auto,'now',lambda:clock[0]);monkeypatch.setattr(history,'now',lambda:clock[0])
    bindings=[await new_binding(client),await bind(client,101),await bind(client,102)]
    for binding in bindings:await sync(client,binding)
    trial=await client.post(AUTO+'/trials',headers=headers(1),json={'binding_ids':[b['id'] for b in bindings],'owner_verified':True})
    assert trial.status_code==200 and trial.json()['passed'],trial.text
    policy=next(row for row in trial.json()['items'] if row['binding_id']==bindings[0]['id'])
    assert (await client.patch(AUTO+f"/bindings/{policy['binding_id']}",headers=headers(1),json={'enabled':True,'revision':policy['revision'],'owner_verified':True,'owner_note':'Synthetic explicit one-service authorization'})).status_code==200
    assert (await auto.run_batch(sessions))['processed']==0
    clock[0]+=timedelta(days=2)
    enabled=next(row for row in (await client.get(AUTO,headers=headers(1))).json()['items'] if row['binding_id']==bindings[0]['id'])
    assert enabled['enabled'] is True and enabled['trial']['validation_state']=='expired'
    raw=future_invoice(clock,unique='unified_next');fake.invoice_rows[raw['id']]=raw
    review_id=await save(sessions,bindings[0]['id'],raw)
    await auto.run_batch(sessions);await auto.run_batch(sessions)
    async with sessions() as db:
        assert (await db.get(Job,review_id)).status=='auto_posted'
        assert await db.scalar(select(func.count()).select_from(Posting))==1
        assert await db.scalar(select(func.count()).select_from(Payments))==2
        assert await db.scalar(select(func.count()).select_from(Policy).where(Policy.enabled.is_(True)))==1
        (await db.get(SalesReceiptEvidence,900)).observation_id=None
        await db.commit()
    drifted=future_invoice(clock,unique='unified_drifted');fake.invoice_rows[drifted['id']]=drifted
    drifted_id=await save(sessions,bindings[0]['id'],drifted)
    await auto.run_batch(sessions)
    async with sessions() as db:
        job=await db.get(Job,drifted_id)
        assert job.status=='manual_required' and job.reason_code=='validation_required' and '变化' in job.reason
        assert await db.scalar(select(func.count()).select_from(Payments))==2


def test_old_trial_is_only_reenable_gate_and_health_does_not_invent_worker_state(monkeypatch):
    binding=SimpleNamespace(account_id='acct',livemode=True,stripe_subscription_id='sub',stripe_customer_id='cus',crm_snapshot={},price_snapshot={},income_type='management_fee',sync_from='2026-01-01')
    clock=datetime(2026,11,13,tzinfo=timezone.utc)
    policy=SimpleNamespace(trial={'passed':True,'checked_at':(clock-timedelta(days=3)).isoformat(),'scope_fingerprint':auto.scope(binding),'invoice_count':1,'reasons':[]})
    monkeypatch.setattr(auto,'now',lambda:clock)
    trial=auto.trial_data(policy,binding)
    assert trial['passed'] is False and trial['validation_state']=='expired' and trial['reenable_required'] is True
    assert policy.trial['passed'] is True
    monkeypatch.setattr(auto,'_WORKER_TASK',None);monkeypatch.setenv('STRIPE_AUTO_POSTING_ENABLED','true');monkeypatch.delenv('IS_LAMBDA',raising=False)
    assert auto.worker_health()['worker_state']=='not_started'
    monkeypatch.setenv('STRIPE_AUTO_POSTING_ENABLED','false');assert auto.worker_health()['worker_state']=='disabled'
    monkeypatch.setenv('STRIPE_AUTO_POSTING_ENABLED','true');monkeypatch.setenv('IS_LAMBDA','true');assert auto.worker_health()['worker_state']=='unsupported'


@pytest.mark.asyncio
async def test_worker_health_reports_real_current_process_start_heartbeat_and_stop(monkeypatch):
    monkeypatch.setattr(auto,'_WORKER_TASK',None);monkeypatch.setattr(auto,'_WORKER_RUNTIME',dict.fromkeys(['started_at','last_heartbeat_at','last_batch_completed_at','last_batch_error']))
    monkeypatch.setenv('STRIPE_AUTO_POSTING_ENABLED','true');monkeypatch.delenv('IS_LAMBDA',raising=False)
    monkeypatch.setattr(auto,'STARTUP_DELAY_SECONDS',0);monkeypatch.setattr(auto,'POLL_SECONDS',0.001)
    async def batch():return {'processed':0,'enabled':True}
    monkeypatch.setattr(auto,'run_batch',batch)
    task=auto.start_auto_posting()
    assert task is auto.start_auto_posting()
    try:
        for _ in range(50):
            if auto.worker_health()['last_batch_completed_at']:break
            await asyncio.sleep(0.001)
        value=auto.worker_health()
        assert value['worker_state']=='running' and value['current_process_only'] is True
        assert value['heartbeat_state']=='current' and value['heartbeat_stale_after_seconds']==180
        assert value['started_at'] and value['last_heartbeat_at'] and value['last_batch_completed_at']
        assert value['last_auto_posted_at'] is None
    finally:await auto.stop_auto_posting(task)
    assert auto.worker_health()['worker_state']=='stopped'


def test_worker_heartbeat_is_observation_not_a_claim_that_all_services_succeeded(monkeypatch):
    clock=datetime(2026,11,13,tzinfo=timezone.utc)
    class Task:
        def done(self):return False
        def cancelled(self):return False
    monkeypatch.setattr(auto,'_WORKER_TASK',Task());monkeypatch.setattr(auto,'now',lambda:clock)
    monkeypatch.setenv('STRIPE_AUTO_POSTING_ENABLED','true');monkeypatch.delenv('IS_LAMBDA',raising=False)
    monkeypatch.setattr(auto,'_WORKER_RUNTIME',{'started_at':clock-timedelta(hours=1),'last_heartbeat_at':clock-timedelta(minutes=10),'last_batch_completed_at':None,'last_batch_error':'batch_failed'})
    result=auto.worker_health()
    assert result['worker_state']=='running' and result['heartbeat_state']=='stale'
    assert result['last_auto_posted_at'] is None and result['last_batch_error']=='batch_failed'
