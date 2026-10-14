"""Owner invitation attacks and migration invariants, entirely synthetic."""
import importlib.util
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text, create_engine, inspect
from alembic.migration import MigrationContext
from alembic.operations import Operations

from models.customer_access_grants import CustomerAccessGrant, CustomerAccessAudit
from models.customers import Customers
from models.employees import Employees
from services.customers import CustomersService
from services.customer_permissions import MODULES, get_customer_permissions
from services.customer_scope import ensure_customer_access
from test_customer_permission_boundaries import env, user

ACCESS = "/api/v1/entities/customers/1/access"


async def owner_invite(client, identity, *members):
    identity["user"] = user(1, "super_admin", "Owner")
    response = await client.put(ACCESS, json={"members": list(members)})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("id,role,name", [(3,"sales","Sales"),(4,"sales_manager","Manager"),(5,"admin","Admin"),(6,"finance","Finance"),(2,"ops","Member")])
async def test_owner_department_and_roles_never_grant_implicit_access(env,id,role,name):
    db, customer, client, identity = env
    actor = user(id,role,name)
    assert await CustomersService(db).get_by_id(1,scope_user=actor) is None
    assert (await CustomersService(db).get_list(scope_user=actor))["total"] == 0
    permissions = await get_customer_permissions(db, actor, 1)
    assert permissions["access_level"] == "none" and permissions["finance_access"] == "none"
    assert not any(value["read"] for value in permissions["modules"].values())
    identity["user"] = actor
    assert (await client.get("/api/v1/entities/customers/1")).status_code == 404


@pytest.mark.asyncio
async def test_legacy_even_owner_named_grant_waits_and_retains_original_configuration(env):
    db, customer, client, identity = env
    legacy = CustomerAccessGrant(customer_id=1,employee_id=3,access_level="read_write",
        scopes={name:"read_write" for name in MODULES},finance_access="profit",can_export=True,
        granted_by_id="1",granted_by_name="Owner")
    db.add(legacy)
    await db.commit()
    original = (legacy.access_level, dict(legacy.scopes), legacy.finance_access, legacy.can_export)
    result = await owner_invite(client,identity,{"employee_id":2})
    assert [row["employee_id"] for row in result["members"]] == [2]
    assert [row["employee_id"] for row in result["pending_legacy_members"]] == [3]
    assert result["owner"]["employee_id"] == 1
    assert (legacy.access_level,dict(legacy.scopes),legacy.finance_access,legacy.can_export) == original
    assert (legacy.invitation_source,legacy.invitation_status) == ("legacy","pending_review")
    assert await CustomersService(db).get_by_id(1,scope_user=user(3,"sales","Sales")) is None


@pytest.mark.asyncio
async def test_default_invitation_opens_only_basic_and_deals_and_records_owner(env):
    db, customer, client, identity = env
    result = await owner_invite(client,identity,{"employee_id":2})
    member = result["members"][0]
    assert member["invitation_source"] == "owner_invitation" and member["invitation_status"] == "active"
    assert member["invited_by_id"] == "1" and member["invited_at"]
    permissions = await get_customer_permissions(db,user(),1)
    assert {name for name,value in permissions["modules"].items() if value["read"]} == {"basic","deals"}
    assert not any(value["write"] for value in permissions["modules"].values())
    assert permissions["finance_access"] == "none"
    assert not any(permissions[name] for name in ("can_delete","can_export","can_reassign","reveal_secrets"))
    for module in set(MODULES)-{"basic","deals"}:
        with pytest.raises(HTTPException) as exc:
            await ensure_customer_access(db,user(),1,module=module)
        assert exc.value.status_code == 403
    audit = (await db.execute(select(CustomerAccessAudit))).scalar_one()
    assert audit.actor_id == "1" and audit.after[0]["invitation_status"] == "active"


@pytest.mark.asyncio
async def test_missing_scope_is_never_inherited_from_read_write(env):
    db,_,client,identity=env
    await owner_invite(client,identity,{"employee_id":2,"access_level":"read_write","scopes":{"basic":"read_write"}})
    permissions = await get_customer_permissions(db,user(),1)
    assert permissions["modules"]["basic"]["write"] is True
    assert all(not v["read"] for k,v in permissions["modules"].items() if k != "basic")
    assert await CustomersService(db).get_by_id(1,scope_user=user(),module="deals") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("module", ["deals", "renewals"])
async def test_payment_sensitive_modules_remain_read_only_even_if_scope_requests_write(env,module):
    db,_,client,identity=env
    await owner_invite(client,identity,{"employee_id":5,"access_level":"read_write","scopes":{module:"read_write"}})
    actor=user(5,"admin")
    assert (await get_customer_permissions(db,actor,1))["modules"][module] == {"read":True,"write":False}
    assert await CustomersService(db).get_by_id(1,scope_user=actor,module=module,write=True) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("extra", [{"finance_access":"profit"},{"invitation_source":"owner_invitation"},{"invitation_status":"active"},{"invited_by_id":"1"}])
async def test_invitation_payload_cannot_smuggle_finance_or_provenance(env,extra):
    db,_,client,identity=env
    identity["user"]=user(1,"super_admin")
    response=await client.put(ACCESS,json={"members":[{"employee_id":2,**extra}]})
    assert response.status_code==422,response.text
    assert (await db.execute(select(CustomerAccessGrant))).scalars().all()==[]


@pytest.mark.asyncio
async def test_finance_separate_decision_preserved_in_preview_and_regular_edit_then_cleared_on_revoke(env):
    db,_,client,identity=env
    await owner_invite(client,identity,{"employee_id":2})
    response=await client.put(ACCESS+"/2/finance",json={"finance_access":"receipts"})
    assert response.status_code==200,response.text
    preview=await client.post(ACCESS+"/preview",json={"employee_id":2,"scopes":{"basic":"read_only"}})
    assert preview.json()["effective_permissions"]["finance_access"]=="receipts"
    await owner_invite(client,identity,{"employee_id":2,"scopes":{"basic":"read_only"}})
    assert (await get_customer_permissions(db,user(),1))["finance_access"]=="receipts"
    await owner_invite(client,identity)
    grant=(await db.execute(select(CustomerAccessGrant))).scalar_one()
    assert grant.invitation_status=="revoked" and grant.finance_access=="none"
    assert await CustomersService(db).get_by_id(1,scope_user=user()) is None
    await owner_invite(client,identity,{"employee_id":2})
    assert (await get_customer_permissions(db,user(),1))["finance_access"]=="none"


@pytest.mark.asyncio
async def test_pending_legacy_finance_never_survives_confirmation(env):
    db,_,client,identity=env
    db.add(CustomerAccessGrant(customer_id=1,employee_id=2,access_level="read_write",finance_access="profit"))
    await db.commit()
    identity["user"]=user(1,"super_admin")
    assert (await client.put(ACCESS+"/2/finance",json={"finance_access":"profit"})).status_code==409
    preview=await client.post(ACCESS+"/preview",json={"employee_id":2})
    assert preview.json()["effective_permissions"]["finance_access"]=="none"
    await owner_invite(client,identity,{"employee_id":2})
    assert (await get_customer_permissions(db,user(),1))["finance_access"]=="none"


@pytest.mark.asyncio
async def test_non_owner_cannot_invite_preview_or_grant_finance(env):
    _,_,client,identity=env
    await owner_invite(client,identity,{"employee_id":5,"access_level":"read_write","scopes":{"basic":"read_write"}})
    identity["user"]=user(5,"admin")
    assert (await client.put(ACCESS,json={"members":[{"employee_id":2}]})).status_code==403
    assert (await client.post(ACCESS+"/preview",json={"employee_id":2})).status_code==403
    assert (await client.put(ACCESS+"/5/finance",json={"finance_access":"profit"})).status_code==403


@pytest.mark.asyncio
async def test_batch_invite_and_revoke_never_falls_back_to_customer_ownership(env):
    db,_,client,identity=env
    identity["user"]=user(1,"super_admin")
    path="/api/v1/entities/customers/access/bulk-update"
    body={"customer_ids":[1],"operation":"upsert","members":[{"employee_id":3}]}
    assert (await client.post(path,json=body)).status_code==200
    actor=user(3,"sales","Sales")
    assert await CustomersService(db).get_by_id(1,scope_user=actor)
    body["operation"]="remove"
    assert (await client.post(path,json=body)).status_code==200
    assert await CustomersService(db).get_by_id(1,scope_user=actor) is None
    assert (await db.get(Customers,1)).sales_employee_id==3
    assert (await db.execute(select(CustomerAccessGrant))).scalar_one().invitation_status=="revoked"


@pytest.mark.asyncio
async def test_creation_and_reassignment_never_generate_access_grants(env,monkeypatch):
    import routers.customers as customer_router
    db,_,client,identity=env
    async def no_external_commission(*args,**kwargs):
        pass
    monkeypatch.setattr(customer_router,"_auto_assign_created_customer",no_external_commission)
    identity["user"]=user(1,"super_admin")
    created=await client.post("/api/v1/entities/customers",json={"business_name":"New synthetic","contact_name":"New","phone":"+12125550124","sales_employee_id":3})
    assert created.status_code==201,created.text
    changed=await client.put("/api/v1/entities/customers/1",json={"sales_employee_id":2})
    assert changed.status_code==200,changed.text
    assert (await db.execute(select(CustomerAccessGrant))).scalars().all()==[]
    assert await CustomersService(db).get_by_id(created.json()["id"],scope_user=user(3,"sales","Sales")) is None


@pytest.mark.asyncio
async def test_basic_sharing_does_not_expose_historical_notes_or_queries(env):
    db,customer,client,identity=env
    customer.interested_packages="website"
    customer.interested_packages_snapshot='{"website":{"label":"Website service","price":499,"internal_profit":321},"secret_fee":"financial-internal"}'
    customer.selected_platforms='{"label":"Google","advertising_budget":777}'
    await db.commit()
    await owner_invite(client,identity,{"employee_id":2,"access_level":"read_write","scopes":{"basic":"read_write"}})
    identity["user"]=user()
    response=await client.get("/api/v1/entities/customers/1")
    assert response.status_code==200 and response.json()["notes"] is None
    assert response.json()["phone"]=="+12125550123"
    assert "team note" not in response.text and "owner secret" not in response.text
    assert "Website service" in response.json()["interested_packages_snapshot"]
    assert "internal_profit" not in response.text and "499" not in response.text and "777" not in response.text
    assert "financial-internal" not in response.text
    for query,sort in (({"notes":"team note"},None),(None,"-notes"),(None,"interested_packages_snapshot"),(None,"selected_platforms")):
        with pytest.raises(HTTPException) as exc:
            await CustomersService(db).get_list(scope_user=user(),query_dict=query,sort=sort)
        assert exc.value.status_code==403
    assert (await client.put("/api/v1/entities/customers/1",json={"notes":"overwrite"})).status_code==403
    assert (await db.get(Customers,1)).notes=="team note"


@pytest.mark.asyncio
async def test_shared_project_status_does_not_reveal_payment_state_or_notes(env):
    from models.management_decisions import BusinessLine, ProductCatalog, CustomerEngagement
    db,_,client,identity=env
    db.add(BusinessLine(id=901,code="synthetic",name="Synthetic service"))
    db.add(ProductCatalog(id=901,business_line_id=901,code="synthetic",name="Synthetic product",billing_kind="recurring"))
    db.add(CustomerEngagement(id=901,customer_id=1,business_line_id=901,product_id=901,
        engagement_code="synthetic",status="active_paid",billing_cycle="monthly",collection_method="stripe",
        stop_note="Financial secret",service_scope_json='{"cost":999}'))
    await db.commit()
    await owner_invite(client,identity,{"employee_id":2,"scopes":{"delivery":"read_only"}})
    identity["user"]=user()
    response=await client.get("/api/v1/entities/customers/1/projects")
    assert response.status_code==200,response.text
    item=response.json()["items"][0]
    assert item["status"]=="active" and item["billing_cycle"]=="monthly"
    assert not {"paid_started_at","currency","collection_method","stop_reason_code","stop_note","service_scope_json"} & item.keys()
    assert "paid" not in response.text and "Financial secret" not in response.text


def test_invitation_migration_only_adds_inactive_columns_and_preserves_old_rows():
    path=Path(__file__).parents[1]/"alembic/versions/d5b9a3e7f815_customer_owner_invitations.py"
    spec=importlib.util.spec_from_file_location("owner_invitation_migration_test",path)
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    engine=create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE customer_access_grants(id INTEGER PRIMARY KEY,customer_id INTEGER,employee_id INTEGER,access_level TEXT,scopes JSON,finance_access TEXT,granted_by_id TEXT,UNIQUE(customer_id,employee_id))"))
        connection.execute(text("INSERT INTO customer_access_grants VALUES(1,1,2,'read_write','{\"basic\":\"read_write\"}','profit','1'),(2,1,3,'none','{}','none','1')"))
        connection.execute(text("CREATE TABLE payments(id INTEGER PRIMARY KEY, amount REAL)"))
        connection.execute(text("INSERT INTO payments VALUES(1,123.45)"))
        old_columns=[row["name"] for row in inspect(connection).get_columns("customer_access_grants")]
        before=connection.execute(text("SELECT * FROM customer_access_grants")).all()
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        assert connection.execute(text("SELECT "+','.join(old_columns)+" FROM customer_access_grants")).all()==before
        assert connection.execute(text("SELECT invitation_source,invitation_status,invited_at,invited_by_id,invited_by_name FROM customer_access_grants")).all()==[("legacy","pending_review",None,None,None)]*2
        assert connection.execute(text("SELECT * FROM payments")).all()==[(1,123.45)]
        assert inspect(connection).get_unique_constraints("customer_access_grants")[0]["column_names"]==["customer_id","employee_id"]
        with pytest.raises(RuntimeError,match="forward migration"):
            migration.downgrade()
    engine.dispose()
