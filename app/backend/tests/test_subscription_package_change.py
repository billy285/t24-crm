import json
from datetime import date, datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from models.subscriptions import Subscriptions
from services.subscriptions import SubscriptionsService


@pytest_asyncio.fixture
async def subscription_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(Subscriptions.__table__.create)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_package_change_archives_old_subscription_and_links_replacements(subscription_session):
    old_subscription = Subscriptions(
        customer_id=22,
        customer_name="Crab King",
        package_name="定制套餐",
        package_price=4800,
        billing_cycle="quarterly",
        start_date=datetime(2026, 1, 31, tzinfo=timezone.utc),
        end_date=datetime(2026, 4, 30, tzinfo=timezone.utc),
        auto_renew=False,
        next_payment_date=datetime(2026, 4, 30, tzinfo=timezone.utc),
        status="expired",
    )
    base_package = Subscriptions(
        customer_id=22,
        customer_name="Crab King",
        package_name="基础套餐",
        package_price=3000,
        billing_cycle="monthly",
        start_date=datetime(2026, 7, 1, tzinfo=timezone.utc),
        end_date=datetime(2026, 8, 1, tzinfo=timezone.utc),
        auto_renew=False,
        status="active",
    )
    professional_package = Subscriptions(
        customer_id=22,
        customer_name="Crab King",
        package_name="专业套餐",
        package_price=399,
        billing_cycle="monthly",
        start_date=datetime(2026, 7, 13, tzinfo=timezone.utc),
        end_date=datetime(2026, 8, 13, tzinfo=timezone.utc),
        auto_renew=True,
        status="active",
    )
    subscription_session.add_all([old_subscription, base_package, professional_package])
    await subscription_session.commit()

    archived, replacements = await SubscriptionsService(subscription_session).mark_package_changed(
        old_subscription.id,
        [base_package.id, professional_package.id],
        date(2026, 3, 4),
        "客户调整服务方案",
    )

    assert archived.status == "upgraded"
    assert archived.auto_renew is False
    assert archived.next_payment_date is None
    payload = json.loads(archived.renewal_result)
    assert payload == {
        "type": "package_changed",
        "effective_date": "2026-03-04",
        "replacement_ids": [base_package.id, professional_package.id],
        "replacement_names": ["基础套餐", "专业套餐"],
        "reason": "客户调整服务方案",
    }
    assert {item.id for item in replacements} == {base_package.id, professional_package.id}
    assert base_package.status == "active"
    assert professional_package.status == "active"


@pytest.mark.asyncio
async def test_package_change_rejects_replacement_from_another_customer(subscription_session):
    old_subscription = Subscriptions(
        customer_id=22,
        package_name="定制套餐",
        package_price=4800,
        status="expired",
    )
    wrong_customer_package = Subscriptions(
        customer_id=99,
        package_name="基础套餐",
        package_price=3000,
        status="active",
    )
    subscription_session.add_all([old_subscription, wrong_customer_package])
    await subscription_session.commit()

    with pytest.raises(ValueError, match="同一客户"):
        await SubscriptionsService(subscription_session).mark_package_changed(
            old_subscription.id,
            [wrong_customer_package.id],
            date(2026, 3, 4),
        )

    await subscription_session.refresh(old_subscription)
    assert old_subscription.status == "expired"
    assert old_subscription.renewal_result is None


@pytest.mark.asyncio
async def test_package_change_cannot_archive_the_same_subscription_twice(subscription_session):
    archived_subscription = Subscriptions(
        customer_id=22,
        package_name="旧套餐",
        package_price=4800,
        status="upgraded",
    )
    replacement = Subscriptions(
        customer_id=22,
        package_name="新套餐",
        package_price=3000,
        status="active",
    )
    subscription_session.add_all([archived_subscription, replacement])
    await subscription_session.commit()

    with pytest.raises(ValueError, match="已经归档"):
        await SubscriptionsService(subscription_session).mark_package_changed(
            archived_subscription.id,
            [replacement.id],
            date(2026, 3, 4),
        )

    await subscription_session.refresh(archived_subscription)
    assert archived_subscription.status == "upgraded"
    assert archived_subscription.renewal_result is None
