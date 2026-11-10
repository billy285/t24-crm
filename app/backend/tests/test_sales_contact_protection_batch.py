"""Real isolated SQLite: presentation parity and bounded queue query counts."""
import json
from datetime import datetime, timedelta, timezone
from time import perf_counter

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.database import Base
from models.sales_contact_protection import SalesPhoneSuppression
from models.sales_dossiers import SalesDossierHandoff
from models.sales_lead_enrichments import SalesDialAttempt, SalesLeadEnrichment, SalesLeadEnrichmentAudit
from models.sales_leads import SalesLeads
from services import sales_contact_protection as protection
from services.phone_numbers import phone_match_key

NOW = datetime(2026, 11, 11, 8, tzinfo=timezone.utc)
TABLES = [model.__table__ for model in (SalesLeads, SalesPhoneSuppression, SalesDossierHandoff,
          SalesLeadEnrichment, SalesLeadEnrichmentAudit, SalesDialAttempt)]

class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz else NOW.replace(tzinfo=None)

async def seed(sessions, *, complete_ledger):
    async with sessions() as db:
        for index in range(100):
            number = f'+1212555{index + 1000:04d}'
            kind = index % 10
            if kind == 2:
                number = '+12125559994'  # Explicit release beats legacy history.
            elif kind == 3:
                number = '+12125559991'  # Legacy protected current store number.
            elif kind == 5:
                number = '+12125559995'  # Legacy prior dialed number.
            cooldown = NOW + timedelta(hours=1) if kind == 6 else NOW - timedelta(hours=1) if kind == 7 else None
            db.add(SalesLeads(id=index + 1, business_name=f'Queue {index}', phone=number, country='US',
                assigned_sales_id=11, cooldown_until=cooldown, do_not_contact=index == 10))
            contacts = [{'phone': '+12125559993'}, {'phone': 'invalid'}] if kind == 4 else []
            db.add(SalesLeadEnrichment(lead_id=index + 1, contacts=contacts, updated_by_id=11))
            if kind in (8, 9):
                db.add(SalesDossierHandoff(lead_id=index + 1, to_sales_id=11 if kind == 8 else 12,
                    note='handoff', summary={}, status='pending', created_by_id=1))
        db.add(SalesLeads(id=9999, business_name='Private legacy source never disclosed', phone='+12125559991',
            country='US', do_not_contact=True, assigned_sales_id=12))
        db.add(SalesLeadEnrichment(lead_id=9999, contacts=[{'phone': '+12125559992'}], updated_by_id=12))
        db.add(SalesLeadEnrichmentAudit(lead_id=9999, revision=1, source='manual', changed_fields=['phone'],
            before={'phone': '+12125559993'}, after={'store_phone': '+12125559994'}, actor_id=12))
        db.add(SalesDialAttempt(lead_id=9999, task_id=1, sales_employee_id=12,
            dial_phone='+12125559995', started_at=NOW))
        await db.flush()
        keys = {'+12125559994': False}
        for index in range(100):
            if index % 10 == 1:
                keys[f'+1212555{index + 1000:04d}'] = True
        if complete_ledger:
            for row in (await db.execute(select(SalesLeads).where(SalesLeads.id < 9999))).scalars():
                key = phone_match_key(row.phone, row.country)
                keys.setdefault(key, key in {'+12125559991', '+12125559995'})
            keys['+12125559993'] = True
        for key, blocked in keys.items():
            db.add(SalesPhoneSuppression(phone_key=key, blocked=blocked, reason='synthetic fixture'))
        await db.commit()

@pytest.mark.asyncio
@pytest.mark.parametrize('complete_ledger', [True, False], ids=['seeded-ledger', 'legacy-missing-ledger'])
async def test_batch_matches_every_single_summary_with_fixed_sql_batches(tmp_path, monkeypatch, complete_ledger):
    monkeypatch.setattr(protection, 'datetime', FrozenDatetime)
    engine = create_async_engine('sqlite+aiosqlite:///' + str(tmp_path / 'batch.sqlite'))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    statements = []
    @event.listens_for(engine.sync_engine, 'before_cursor_execute')
    def count_query(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=TABLES))
        await seed(sessions, complete_ledger=complete_ledger)
        async with sessions() as db:
            leads = (await db.execute(select(SalesLeads).where(SalesLeads.id < 9999).order_by(SalesLeads.id))).scalars().all()
            statements.clear()
            started = perf_counter()
            expected = {lead.id: await protection.contact_protection_summary(db, lead) for lead in leads}
            old_ms, old_count = (perf_counter() - started) * 1000, len(statements)
            assert all(sql.lstrip().upper().startswith('SELECT') for sql in statements)
        async with sessions() as db:
            leads = (await db.execute(select(SalesLeads).where(SalesLeads.id < 9999).order_by(SalesLeads.id))).scalars().all()
            statements.clear()
            started = perf_counter()
            actual = await protection.contact_protection_summaries(db, leads)
            batch_ms, batch_count = (perf_counter() - started) * 1000, len(statements)
            assert actual == expected
            assert len(actual) == 100 and 9999 not in actual
            assert batch_count == (3 if complete_ledger else 7)
            assert old_count >= (200 if complete_ledger else 600)
            assert all(sql.lstrip().upper().startswith('SELECT') for sql in statements)
            assert not actual[9]['can_contact'] and '交接' in actual[9]['reason']
            assert actual[10]['can_contact']  # Pending handoff targets a different salesperson.
            assert actual[3]['can_contact'] and actual[3]['protected_phones'] == []
            assert actual[7]['cooldown_until'] == NOW + timedelta(hours=1)
            assert actual[8]['can_contact']
            assert 'Private legacy' not in json.dumps(actual, default=str)
            print(json.dumps({'fixture': '100 scoped queue leads', 'complete_ledger': complete_ledger,
                'old_queries': old_count, 'batch_queries': batch_count,
                'old_ms': round(old_ms, 2), 'batch_ms': round(batch_ms, 2), 'all_100_summaries_equal': True}))
        # The count is fixed for 1/10/100 scoped leads, not merely one lucky
        # 100-row case; repeated queue IDs cannot multiply reads or results.
        for size in (1, 10, 100):
            async with sessions() as db:
                leads = (await db.execute(select(SalesLeads).where(SalesLeads.id < 9999)
                    .order_by(SalesLeads.id).limit(size))).scalars().all()
                statements.clear()
                repeated = await protection.contact_protection_summaries(db, leads + leads)
                assert repeated == {lead.id: expected[lead.id] for lead in leads}
                assert len(statements) == batch_count
    finally:
        await engine.dispose()

@pytest.mark.asyncio
async def test_empty_queue_performs_no_database_queries():
    class NoDatabaseCalls:
        def __getattr__(self, name):
            raise AssertionError('Empty queue must not read: ' + name)
    assert await protection.contact_protection_summaries(NoDatabaseCalls(), []) == {}


@pytest.mark.asyncio
async def test_missing_profiles_empty_phones_utc_expiry_and_country_history_match(tmp_path, monkeypatch):
    monkeypatch.setattr(protection, 'datetime', FrozenDatetime)
    engine = create_async_engine('sqlite+aiosqlite:///' + str(tmp_path / 'edge.sqlite'))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=TABLES))
        async with sessions() as db:
            db.add_all([
                SalesLeads(id=1, business_name='No phone/profile/assignee', phone='', country=None),
                SalesLeads(id=2, business_name='Expired exactly now', phone='+12125550102', country='US',
                    assigned_sales_id=11, cooldown_until=NOW),
                SalesLeads(id=3, business_name='UK historical contact', phone='+12125550103', country='US', assigned_sales_id=11),
                SalesLeads(id=4, business_name='Own blacklist', phone='+12125550104', country='US', is_blacklisted=True),
                SalesLeads(id=5, business_name='Own blocked status', phone='+12125550105', country='US', status='blocked'),
                SalesLeads(id=99, business_name='Private historical UK source', phone='+12125550999', country='US', do_not_contact=True),
                SalesLeadEnrichment(lead_id=3, contacts=[{'phone': '+442079460018'}], updated_by_id=11),
                SalesLeadEnrichmentAudit(lead_id=99, revision=1, source='manual', changed_fields=['phone'],
                    before={'country': 'GB', 'phone': '020 7946 0018'}, after={}, actor_id=12),
                SalesDossierHandoff(lead_id=2, to_sales_id=11, note='completed', summary={}, status='acknowledged', created_by_id=1),
                SalesDossierHandoff(lead_id=3, to_sales_id=11, note='pending', summary={}, status='pending', created_by_id=1),
                SalesPhoneSuppression(phone_key='+12125550104', blocked=False, reason='Own flag still applies'),
            ])
            await db.commit()
        async with sessions() as db:
            leads = (await db.execute(select(SalesLeads).where(SalesLeads.id < 99))).scalars().all()
            expected = {lead.id: await protection.contact_protection_summary(db, lead) for lead in leads}
        async with sessions() as db:
            leads = (await db.execute(select(SalesLeads).where(SalesLeads.id < 99))).scalars().all()
            actual = await protection.contact_protection_summaries(db, leads)
            assert actual == expected
            assert actual[1]['can_contact'] and actual[1]['cooldown_until'] is None
            assert actual[2]['can_contact'] and actual[2]['cooldown_until'] == NOW
            assert actual[3]['reason'] == protection.PROTECTION_NOTICE  # Suppression precedes handoff.
            assert actual[3]['protected_phones'] == ['+442079460018']
            assert not actual[4]['can_contact'] and actual[4]['protected_phones'] == []
            assert not actual[5]['can_contact']
    finally:
        await engine.dispose()
