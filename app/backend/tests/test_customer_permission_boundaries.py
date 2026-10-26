"""Synthetic authorization attacks; no production data or external services."""
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import Base, get_db
from dependencies.auth import get_current_user
from models.customers import Customers
from models.employees import Employees
from models.customer_access_grants import CustomerAccessGrant, CustomerAccessAudit
from models.customer_record_audits import CustomerRecordAudit
from models.operation_logs import Operation_logs
from routers.customers import router, CustomerAccessAssignment
from schemas.auth import UserResponse
from services.customers import CustomersService
from services.customer_scope import ensure_customer_access
from services.customer_permissions import get_customer_permissions, require_customer_finance

def active_grant(**kwargs):
    """Synthetic, deliberately owner-invited fixture; never a legacy default."""
    kwargs.setdefault("invitation_source", "owner_invitation")
    kwargs.setdefault("invitation_status", "active")
    kwargs.setdefault("scopes", {m: "read_write" for m in ("basic", "contacts", "followups", "opportunities", "delivery", "renewals", "deals", "materials")})
    return CustomerAccessGrant(**kwargs)



def user(id=2, role="ops", name="Member"):
    return UserResponse(id=str(id), role=role, name=name, email=f"synthetic-{id}@example.invalid")


@pytest_asyncio.fixture
async def env():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("CREATE TABLE IF NOT EXISTS app_settings (config_key TEXT PRIMARY KEY, value_json TEXT)"))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        employees = [Employees(id=1,user_id="1",name="Owner",role="super_admin",status="active"),
                     Employees(id=2,user_id="2",name="Member",role="ops",status="active"),
                     Employees(id=3,user_id="3",name="Sales",role="sales",status="active",department="A"),
                     Employees(id=4,user_id="4",name="Manager",role="sales_manager",status="active",department="A"),
                     Employees(id=5,user_id="5",name="Admin",role="admin",status="active"),
                     Employees(id=6,user_id="6",name="Finance",role="finance",status="active")]
        db.add_all(employees)
        customer = Customers(id=1,business_name="Synthetic Only",contact_name="Contact",phone="+12125550123",notes="team note",private_notes="owner secret",sales_employee_id=3,sales_person="Sales")
        db.add(customer)
        await db.commit()
        app = FastAPI()
        app.include_router(router)
        async def override_db():
            yield db
        app.dependency_overrides[get_db] = override_db
        identity = {"user":user()}
        app.dependency_overrides[get_current_user] = lambda: identity["user"]
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield db, customer, client, identity
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("employee_id,role,name", [(3,"sales","Sales"),(4,"sales_manager","Manager"),(5,"admin","Admin"),(6,"finance","Finance")])
async def test_explicit_deny_overrides_all_inheritance(env, employee_id, role, name):
    db, customer, _, _ = env
    db.add(active_grant(customer_id=customer.id,employee_id=employee_id,access_level="none"))
    await db.commit()
    actor=user(employee_id,role,name)
    assert await CustomersService(db).get_by_id(customer.id,scope_user=actor) is None
    assert (await CustomersService(db).get_list(scope_user=actor))["total"] == 0
    with pytest.raises(HTTPException) as exc:
        await ensure_customer_access(db, actor, customer.id,write=True)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_only_owner_has_unconditional_access(env):
    db, customer, _, _=env
    for role in ("admin","finance","ops","sales_partner"):
        assert await CustomersService(db).get_by_id(customer.id,scope_user=user(5,role)) is None
    assert await CustomersService(db).get_by_id(customer.id,scope_user=user(1,"super_admin")) is customer
    assert await CustomersService(db).get_by_id(customer.id,scope_user=user(3,"sales","Sales")) is None


@pytest.mark.asyncio
async def test_owner_and_department_can_be_downgraded_to_read_only(env):
    db,customer,_,_=env
    for employee_id in (3,4):
        db.add(active_grant(customer_id=customer.id,employee_id=employee_id,access_level="read_only"))
    await db.commit()
    for employee_id,role,name in ((3,"sales","Sales"),(4,"sales_manager","Manager")):
        actor=user(employee_id,role,name)
        assert await ensure_customer_access(db,actor,customer.id)
        with pytest.raises(HTTPException) as exc:
            await ensure_customer_access(db,actor,customer.id,write=True)
        assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_module_boundaries_and_finance_are_independent(env):
    db,customer,_,_=env
    db.add(active_grant(customer_id=1,employee_id=2,access_level="read_write",scopes={"basic":"read_only","followups":"read_write","materials":"none"},finance_access="status"))
    await db.commit()
    await ensure_customer_access(db,user(),1,write=True,module="followups")
    for module,write in (("basic",True),("materials",False)):
        with pytest.raises(HTTPException):
            await ensure_customer_access(db,user(),1,write=write,module=module)
    await require_customer_finance(db,user(),1,level="status")
    with pytest.raises(HTTPException):
        await require_customer_finance(db,user(),1,level="receipts")
    permissions = await get_customer_permissions(db,user(),1)
    assert permissions["modules"]["basic"] == {"read":True,"write":False}
    assert permissions["modules"]["followups"]["write"] is True
    assert permissions["can_export"] is False
    assert permissions["can_delete"] is False
    assert permissions["reveal_secrets"] is False


@pytest.mark.asyncio
async def test_sharing_cannot_read_private_notes_or_manage_access(env):
    db,customer,client,identity=env
    db.add(active_grant(customer_id=1,employee_id=2,access_level="read_write"))
    await db.commit()
    response=await client.get("/api/v1/entities/customers/1")
    assert response.status_code == 200, response.text
    assert "owner secret" not in response.text
    assert "private_notes" not in response.json()
    for path in ("private-note","access","access/history","record-audits"):
        response=await client.get("/api/v1/entities/customers/1/"+path)
        assert response.status_code == 403
    identity["user"] = user(5,"admin")
    response=await client.put("/api/v1/entities/customers/1/access",json={"members":[]})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_owner_saves_denial_with_atomic_before_after_audit(env):
    db,customer,client,identity=env
    identity["user"]=user(1,"super_admin","Owner")
    path="/api/v1/entities/customers/1/access"
    response=await client.put(path,json={"members":[{"employee_id":3,"access_level":"none"}]})
    assert response.status_code == 200, response.text
    assert response.json()["members"] == []
    sales=(await db.execute(select(CustomerAccessGrant).where(CustomerAccessGrant.employee_id==3))).scalar_one()
    assert sales.invitation_status == "revoked" and sales.access_level == "none"
    history=(await client.get(path+"/history")).json()["items"]
    assert len(history)==1 and history[0]["before"]==[]
    assert history[0]["after"][0]["access_level"]=="none"
    assert history[0]["actor_id"]=="1"
    denied=await client.put(path,json={"members":[{"employee_id":1,"access_level":"none"}]})
    assert denied.status_code==400
    assert len((await client.get(path+"/history")).json()["items"])==1


@pytest.mark.asyncio
async def test_preview_does_not_change_access_or_return_customer_secrets(env):
    db,customer,client,identity=env
    identity["user"]=user(1,"super_admin")
    response=await client.post("/api/v1/entities/customers/1/access/preview",json={"employee_id":2,"access_level":"read_only","finance_access":"none"})
    assert response.status_code==200,response.text
    assert "Synthetic Only" not in response.text and "owner secret" not in response.text
    assert response.json()["effective_permissions"]["modules"]["basic"]["write"] is False
    assert (await db.execute(select(CustomerAccessGrant))).scalars().all()==[]
    assert (await db.execute(select(CustomerAccessAudit))).scalars().all()==[]


@pytest.mark.asyncio
async def test_private_note_owner_edit_and_public_field_exclusion(env):
    db,customer,client,identity=env
    identity["user"]=user(1,"super_admin")
    response=await client.put("/api/v1/entities/customers/1/private-note",json={"private_notes":"new private contents"})
    assert response.status_code==200,response.text
    assert (await client.get("/api/v1/entities/customers/1/private-note")).json()["private_notes"]=="new private contents"
    assert "new private contents" not in (await client.get("/api/v1/entities/customers/1")).text
    assert "new private contents" not in (await client.get("/api/v1/entities/customers/1/record-audits")).text


@pytest.mark.asyncio
async def test_hidden_basic_returns_only_customer_shell(env):
    db,customer,client,_=env
    db.add(active_grant(customer_id=1,employee_id=2,access_level="read_only",scopes={"basic":"none","delivery":"read_only"}))
    await db.commit()
    response=await client.get("/api/v1/entities/customers/1")
    assert response.status_code==200,response.text
    assert response.json()["business_name"]=="Synthetic Only"
    assert response.json()["phone"]=="" and response.json()["notes"] is None
    assert "Contact" not in response.text
    probe = await CustomersService(db).get_list(scope_user=user(),query_dict={"phone":"+12125550123"})
    assert probe["total"] == 0


@pytest.mark.asyncio
async def test_edit_does_not_implicitly_allow_delete_export_or_reassignment(env):
    db,customer,client,identity=env
    db.add(active_grant(customer_id=1,employee_id=5,access_level="read_write"))
    await db.commit()
    identity["user"]=user(5,"admin")
    assert (await client.delete("/api/v1/entities/customers/1")).status_code==403
    assert (await client.post("/api/v1/entities/customers/access/export",json={"ids":[1]})).status_code==403
    response=await client.put("/api/v1/entities/customers/1",json={"sales_employee_id":5})
    assert response.status_code==403,response.text
    assert customer.sales_employee_id==3


@pytest.mark.asyncio
@pytest.mark.parametrize("configuration", [{"commission_partner_id": 99}, {"commission_effective_from":"2026-10-14"}, {"projects":[{"business_line_code":"website"}]}])
async def test_regular_admin_cannot_configure_financial_project_or_commission_sources(env, configuration):
    db,_,client,identity=env
    identity["user"]=user(5,"admin")
    response=await client.post("/api/v1/entities/customers/with-projects",json={"customer":{"business_name":"Attempt","contact_name":"Contact","phone":"+12125550123"},**configuration})
    assert response.status_code==403,response.text
    assert len((await db.execute(select(Customers))).scalars().all())==1


@pytest.mark.asyncio
async def test_export_checks_all_ids_and_records_server_audit(env):
    db,customer,client,identity=env
    db.add(active_grant(customer_id=1,employee_id=5,access_level="read_only",can_export=True))
    await db.commit()
    identity["user"]=user(5,"admin")
    assert (await client.post("/api/v1/entities/customers/access/export",json={"ids":[1,999]})).status_code==404
    response=await client.post("/api/v1/entities/customers/access/export",json={"ids":[1]})
    assert response.status_code==200,response.text
    assert "owner secret" not in response.text
    logs=(await db.execute(select(Operation_logs).where(Operation_logs.action_type=="export_data"))).scalars().all()
    assert len(logs)==1 and logs[0].user_id=="5"


@pytest.mark.asyncio
async def test_finance_clerk_cannot_export_customer_database_even_with_old_export_grant(env):
    db,_,client,identity=env
    db.add(active_grant(customer_id=1,employee_id=6,access_level="read_only",can_export=True))
    await db.commit()
    identity["user"]=user(6,"finance")
    assert (await client.post("/api/v1/entities/customers/access/export",json={"ids":[1]})).status_code==403
    assert not (await db.scalars(select(Operation_logs).where(Operation_logs.action_type=="export_data"))).all()


def test_new_assignment_defaults_to_read_only_without_finance_or_dangerous_actions():
    grant=CustomerAccessAssignment(employee_id=2)
    assert grant.access_level=="read_only" and grant.finance_access=="none"
    assert not any((grant.can_export,grant.can_delete,grant.can_reassign))


@pytest.mark.asyncio
async def test_private_notes_not_queryable_side_channel(env):
    db,_,_,_=env
    with pytest.raises(ValueError):
        await CustomersService(db).get_list(scope_user=user(1,"super_admin"),query_dict={"private_notes":"owner secret"})
    with pytest.raises(ValueError):
        await CustomersService(db).get_list(scope_user=user(1,"super_admin"),sort="private_notes")


@pytest.mark.asyncio
async def test_permission_audit_failure_rolls_back_the_authorization(env, monkeypatch):
    import routers.customers as customer_router
    db,customer,client,identity=env
    db.add(active_grant(customer_id=1,employee_id=3,access_level="read_only"))
    await db.commit()
    identity["user"]=user(1,"super_admin")
    async def fail_audit(*args, **kwargs):
        raise RuntimeError("synthetic audit write failure")
    monkeypatch.setattr(customer_router, "_audit_grants", fail_audit)
    with pytest.raises(RuntimeError, match="synthetic audit"):
        await client.put("/api/v1/entities/customers/1/access",json={"members":[{"employee_id":3,"access_level":"read_write"}]})
    grant=(await db.execute(select(CustomerAccessGrant).where(CustomerAccessGrant.employee_id==3))).scalar_one()
    assert grant.access_level=="read_only"
    assert (await db.execute(select(CustomerAccessAudit))).scalars().all()==[]


@pytest.mark.asyncio
async def test_inactive_member_rule_can_be_preserved_or_denied_but_not_upgraded(env):
    db,_,client,identity=env
    employee=await db.get(Employees,2)
    employee.status="inactive"
    db.add(active_grant(customer_id=1,employee_id=2,access_level="read_only"))
    await db.commit()
    identity["user"]=user(1,"super_admin")
    path="/api/v1/entities/customers/1/access"
    kept=await client.put(path,json={"members":[{"employee_id":2,"access_level":"read_only"}]})
    assert kept.status_code==400,kept.text
    blocked=await client.put(path,json={"members":[{"employee_id":2,"access_level":"read_write"}]})
    assert blocked.status_code==400
    denied=await client.put(path,json={"members":[{"employee_id":2,"access_level":"none"}]})
    assert denied.status_code==200,denied.text


@pytest.mark.asyncio
async def test_fresh_database_role_read_neither_creates_table_nor_rolls_back_pending_changes(env):
    db,customer,_,_=env
    await db.execute(text("DROP TABLE app_settings"))
    await db.commit()
    customer.notes="pending team note"
    permissions=await get_customer_permissions(db,user(1,"super_admin"),1)
    assert permissions["can_manage_access"] is True
    assert customer.notes=="pending team note"
    exists=(await db.execute(text("SELECT COUNT(*) FROM sqlite_master WHERE name='app_settings'"))).scalar_one()
    assert exists==0
    await db.rollback()


def test_additive_migration_preserves_legacy_grants_and_financial_records():
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect
    path=Path(__file__).parents[1]/"alembic/versions/c4a8f2d6e714_customer_permission_boundaries.py"
    spec=importlib.util.spec_from_file_location("customer_permissions_migration_test",path)
    migration=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine=create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE customers (id INTEGER PRIMARY KEY, notes TEXT)"))
        conn.execute(text("INSERT INTO customers VALUES (1,'historical team note')"))
        conn.execute(text("CREATE TABLE employees (id INTEGER PRIMARY KEY)"))
        conn.execute(text("INSERT INTO employees VALUES (3),(4)"))
        conn.execute(text("CREATE TABLE customer_access_grants (id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE, employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE, access_level VARCHAR(20) NOT NULL DEFAULT 'read_write', CONSTRAINT uq_customer_access_grant UNIQUE (customer_id,employee_id))"))
        conn.execute(text("CREATE INDEX ix_customer_access_grants_employee_id ON customer_access_grants(employee_id)"))
        conn.execute(text("INSERT INTO customer_access_grants VALUES (1,1,3,'read_write')"))
        conn.execute(text("CREATE TABLE customer_materials (id INTEGER PRIMARY KEY, content TEXT)"))
        conn.execute(text("INSERT INTO customer_materials VALUES (1,'historical material')"))
        conn.execute(text("CREATE TABLE payments (id INTEGER PRIMARY KEY, amount TEXT)"))
        conn.execute(text("INSERT INTO payments VALUES (1,'1234.56')"))
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        row=conn.execute(text("SELECT access_level,scopes,finance_access,can_export,can_delete,can_reassign FROM customer_access_grants")).one()
        assert tuple(row)==('read_write','{}','none',0,0,0)
        assert conn.execute(text("SELECT notes,private_notes FROM customers")).one()==('historical team note',None)
        assert conn.execute(text("SELECT content,visibility FROM customer_materials")).one()==('historical material','team')
        assert conn.execute(text("SELECT * FROM payments")).one()==(1,'1234.56')
        conn.execute(text("INSERT INTO customer_access_grants (id,customer_id,employee_id) VALUES (2,1,4)"))
        assert conn.execute(text("SELECT access_level FROM customer_access_grants WHERE id=2")).scalar_one()=='read_only'
        assert {'customer_access_audits','customer_record_audits'} <= set(inspect(conn).get_table_names())
        assert len(inspect(conn).get_foreign_keys("customer_access_grants"))==2
        assert {index["name"] for index in inspect(conn).get_indexes("customer_access_grants")}=={"ix_customer_access_grants_employee_id"}
        assert inspect(conn).get_unique_constraints("customer_access_grants")[0]["name"]=="uq_customer_access_grant"
    engine.dispose()
