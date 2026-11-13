"""Run directly with the production Python runtime and an isolated SQLite database."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.database import Base
from models.customer_access_grants import CustomerAccessGrant
from models.customers import Customers
from models.employees import Employees
from models.google_business import GoogleBusinessAction, GoogleBusinessBinding, GoogleBusinessConnection
from models.media_operations import MediaOperationTask
from models.meta_business import MetaBusinessBinding
from models.meta_operations import MetaOperationsAction, MetaOperationsBinding
from models.service_progresses import Service_progresses
from models.service_tasks import Service_tasks
from services.service_weekly_evidence import weekly_evidence


async def smoke_weekly_evidence():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    owner = SimpleNamespace(id="1", role="super_admin")
    operator = SimpleNamespace(id="2", role="ops")
    now = datetime(2026, 11, 11, 12, tzinfo=timezone.utc)
    monday = datetime(2026, 11, 8, 16, tzinfo=timezone.utc)  # Beijing Monday at midnight.
    models = [Service_progresses, Service_tasks, Customers, Employees, CustomerAccessGrant, MediaOperationTask,
              GoogleBusinessConnection, GoogleBusinessBinding, GoogleBusinessAction, MetaOperationsAction, MetaOperationsBinding]
    # Tests need the same columns as the live domain. No provider, credentials or existing database is used.
    async with engine.begin() as conn:
        for model in models:
            await conn.run_sync(model.__table__.create)
        from models.google_business import GoogleBusinessGrant
        await conn.run_sync(GoogleBusinessGrant.__table__.create)
    async with async_sessionmaker(engine)() as db:
        for customer in [10, 20]:
            db.add(Customers(id=customer, business_name="Synthetic", phone="000", contact_name="Test"))
        db.add(CustomerAccessGrant(customer_id=10, employee_id=2, access_level="read_only", scopes={"delivery": "read_only"},
                                   invitation_source="owner_invitation", invitation_status="active"))
        for pid, customer, platforms in [(11, 10, '["google_business","facebook","instagram"]'), (12, 10, "instagram"), (21, 20, "google_business")]:
            db.add(Service_progresses(id=pid, customer_id=customer, package_platforms=platforms, service_stage="normal_ops", user_id="1"))
        def service(pid, name, kind, **fields):
            values = dict(service_progress_id=pid, customer_id=10, task_type=kind, task_name=name, platform="google_business",
                          status="completed", completed_at=monday.isoformat(), completion_quality="low_quality", user_id="1")
            db.add(Service_tasks(**(values | fields)))
        for i in range(3):
            service(11, f"第 {i + 1} 份周报", "submit_report")
        service(11, "Google 更新", "publish_content", due_date="2026-11-12", selected_copy_id=1)
        service(11, "下一次发帖", "publish_content", status="pending", due_date="2026-11-12")
        service(12, "月报（周五提交）", "submit_report")
        service(12, "月度周转汇总", "submit_report")
        service(12, "上周周报", "submit_report", due_date="2026-11-07")
        db.add(Service_progresses(id=13, customer_id=10, package_platforms="facebook", service_stage="ended", user_id="1"))
        service(12, "过期周报", "submit_report", completed_at=(monday - timedelta(seconds=1)).isoformat())
        service(12, "未来周报", "submit_report", completed_at=(now + timedelta(days=7)).isoformat())
        service(12, "材料", "other", completion_note="周报已经提到")
        service(12, "错误客户的周报", "submit_report", customer_id=20)
        await db.commit()
        baseline = await weekly_evidence(db, owner, now)
        assert baseline["scope"] == "owner"
        assert baseline["week_start"] == "2026-11-09" and baseline["unassigned"] == 0
        assert baseline["projects"] == {11: {"published": {}, "internal_report": True, "scheduled": {"google_business": 1},
                                             "closed": {"google_business": 1}, "report_scheduled": False}}

        def media(identity, **fields):
            values = dict(id=identity, customer_id=10, customer_name="Test", service_progress_id=11, title="Content",
                          platform="google_business", due_at=monday, timezone="Asia/Shanghai", assignee_id=2, assignee_name="Ops",
                          status="completed", created_by_id=1, client_request_id=str(identity), creation_fingerprint="a",
                          completed_at=monday, proof_url=f"https://posts.example.org/post/{identity}")
            db.add(MediaOperationTask(**(values | fields)))
        media(1, completed_at=monday - timedelta(seconds=1))
        media(2, proof_url="https://posts.example.org/post/1?utm_source=duplicate")
        media(3, proof_material_id=300)
        media(4, proof_material_id=300, proof_url=None)
        media(5, status="ready", proof_url=None)
        media(6, status="ready", proof_url=None)
        media(7, status="ready", proof_url=None)
        media(8, proof_url=None, proof_material_id=None)
        media(9, platform="instagram", service_progress_id=None)
        media(10, customer_id=20, service_progress_id=21)
        media(11, completed_at=now + timedelta(hours=1))
        db.add(GoogleBusinessConnection(id=1, owner_id=1, label="Synthetic Google"))
        db.add(GoogleBusinessBinding(id=1, connection_id=1, customer_id=10, customer_name="A", location_name="locations/1",
                                     title="A", created_by_id=1, request_id="synthetic"))
        for task, kind, state, status in [(3,"post_publish","LIVE","succeeded"),(5,"post_publish","LIVE","succeeded"),
                                         (6,"post_publish","PROCESSING","accepted"),(7,"review_reply","APPROVED","succeeded")]:
            db.add(GoogleBusinessAction(binding_id=1, task_id=task, customer_id=10, kind=kind, request_id=str(task), fingerprint="x",
                                        actor_id=1, actor_name="Test", status=status, provider_state=state, provider_name=f"p/{task}",
                                        confirmed_at=monday))
        db.add(MetaOperationsBinding(id=2, source_binding_id=2, owner_id=1, customer_id=10, customer_name="A", platform="facebook",
                                     external_id="123", page_id="123", asset_name="Test", connection_id=1, credential_id=1,
                                     connection_revision=1, created_at=monday, updated_at=monday))
        for identity, kind, status in [(1,"post","succeeded"),(2,"reply","succeeded"),(3,"post","processing")]:
            db.add(MetaOperationsAction(binding_id=2, owner_id=1, kind=kind, binding_revision=1, connection_revision=1,
                                        draft_id=identity, draft_revision=1, request_id=str(identity), fingerprint="t", preview_hash="t",
                                        submitted_snapshot={}, payload={}, status=status, dispatch_stage="complete", provider_id=str(identity),
                                        message="", created_at=monday, updated_at=monday))
        await db.commit()
        owner_view = await weekly_evidence(db, owner, now)
        assert owner_view["projects"][11]["published"] == {"google_business": 2, "facebook": 1}
        assert owner_view["projects"][21]["published"] == {"google_business": 1}
        assert owner_view["unassigned"] == 1 and owner_view["unresolved_projects"] == [11, 12] and 12 not in owner_view["projects"]
        ops_view = await weekly_evidence(db, operator, now)
        assert ops_view["scope"] == "assigned"
        assert set(ops_view["projects"]) == {11} and ops_view["projects"][11]["published"] == {"google_business": 1}
    await engine.dispose()


def test_weekly_delivery_counts():
    asyncio.run(smoke_weekly_evidence())


if __name__ == "__main__":
    test_weekly_delivery_counts()
    print("WEEKLY_DELIVERY_EVIDENCE_OK")
