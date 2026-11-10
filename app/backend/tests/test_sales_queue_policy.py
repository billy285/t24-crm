from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from services.sales_queue_policy import contact_queue_context, queue_sort_key
from backend.tests.test_sales_lead_isolation import _auth_headers, sales_app_client


def lead(id=1, **changes):
    return SimpleNamespace(**{**dict(id=id, business_name='Synthetic Salon', country='US', state='CA', city='Los Angeles',
        address=None, website=None, contact_name=None, next_follow_up_at=None, status='new'), **changes})


def test_due_promise_precedes_in_window_and_unknown_has_no_invented_clock():
    now = datetime(2026, 11, 10, 15, tzinfo=timezone.utc)
    west = lead(1)
    east = lead(2, state='NY', city='New York')
    due = lead(3, next_follow_up_at=datetime(2026, 11, 10, 14), status='follow_up')
    unknown = lead(4, state='TN', city=None)
    contexts = {l.id: contact_queue_context(l, now=now) for l in [west, east, due, unknown]}
    assert contexts[east.id]['in_contact_window'] is True
    assert contexts[west.id]['in_contact_window'] is False
    assert contexts[unknown.id]['local_time'] is None
    assert contexts[unknown.id]['in_contact_window'] is None
    assert [l.id for l in sorted([unknown, west, east, due], key=lambda l: queue_sort_key(l, contexts[l.id]))] == [3, 2, 1, 4]
    assert queue_sort_key(east, contexts[east.id], completed=True) > queue_sort_key(unknown, contexts[unknown.id])


def test_arizona_dst_and_configured_hours_and_confirmed_override():
    now = datetime(2026, 7, 1, 16, tzinfo=timezone.utc)
    az = contact_queue_context(lead(state='AZ', city='Phoenix'), now=now, start=9, end=17)
    denver = contact_queue_context(lead(state='CO', city='Denver'), now=now, start=9, end=17)
    assert az['local_time'].startswith('2026-07-01T09:00')
    assert denver['local_time'].startswith('2026-07-01T10:00')
    assert az['in_contact_window'] is True
    overridden = contact_queue_context(lead(state='TN', city=None), now=now, profile={'timezone':'America/New_York'})
    assert overridden['timezone_basis'] == 'confirmed_profile'


def test_placeholder_street_does_not_increase_profile_completeness():
    now = datetime(2026, 11, 10, 19, tzinfo=timezone.utc)
    placeholder = lead(1, business_name='店名待核验｜美甲招聘联系点', address='街道地址待核验（中文招聘来源）')
    complete = lead(2, address='100 Synthetic Street')
    assert queue_sort_key(complete, contact_queue_context(complete, now=now)) < queue_sort_key(placeholder, contact_queue_context(placeholder, now=now))


@pytest.mark.asyncio
async def test_quota_fills_suitable_local_time_first_without_reassigning_other_sales(sales_app_client, monkeypatch):
    from services import sales_lead_cycle
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            value = cls(2026, 11, 10, 15, tzinfo=timezone.utc)
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)
    monkeypatch.setattr(sales_lead_cycle, 'datetime', Clock)
    admin = _auth_headers('admin', 1, 'Admin')
    sales = _auth_headers('sales', 11, 'Sales A')
    ids = []
    for i, (state, city, employee) in enumerate([('CA','Los Angeles',11),('NY','New York',11),('NY','New York',12)]):
        response = await sales_app_client.post('/api/v1/sales-leads', headers=admin, json={
            'business_name': f'Synthetic Queue {i}', 'phone': f'+1212555700{i}',
            'country':'US', 'state':state, 'city':city, 'assigned_sales_id':employee})
        assert response.status_code == 201, response.text
        ids.append(response.json()['id'])
    result = await sales_app_client.put('/api/v1/sales-leads/workbench/quota', headers=admin,
        json={'sales_employee_id':11,'target_count':1})
    assert result.status_code == 200
    result = await sales_app_client.post('/api/v1/sales-leads/workbench/prepare?target_date=2026-11-10', headers=sales)
    assert result.status_code == 200, result.text
    result = await sales_app_client.get('/api/v1/sales-leads/workbench/today?target_date=2026-11-10', headers=sales)
    assert result.status_code == 200
    assert [item['lead']['id'] for item in result.json()['items']] == [ids[1]]
    assert result.json()['queue_policy']['contact_start'] == 10
    assert result.json()['items'][0]['contact_queue']['timezone_group'] == 'eastern'
