"""Idempotent post-deal handoff orchestration.

The deal and its mirrored payment are committed by the deals endpoint first.
This service makes the remaining customer/subscription/service-board work safe
to retry without introducing a generic workflow engine or new schema.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.customers import Customers
from models.deals import Deals
from models.service_progresses import Service_progresses
from models.service_tasks import Service_tasks
from models.subscriptions import Subscriptions


BUSINESS_TIMEZONE = ZoneInfo("Asia/Shanghai")

# Production currently runs one Uvicorn worker, so a process-local lock closes
# the SQLite read-then-insert race for double clicks and overlapping retries.
# A future multi-worker deployment still needs database unique constraints on
# the deal linkage; that intentionally remains migration work, not startup
# schema repair.
_FINALIZE_LOCKS: dict[int, asyncio.Lock] = {}


def deal_finalize_lock(deal_id: int) -> asyncio.Lock:
    return _FINALIZE_LOCKS.setdefault(int(deal_id), asyncio.Lock())

PLATFORM_LABELS = {
    "google_business": "Google商家",
    "facebook": "Facebook",
    "instagram": "Instagram",
    "yelp": "Yelp",
    "tiktok": "TikTok",
    "xiaohongshu": "小红书",
    "x": "X",
}

COMMON_ONBOARDING_STEPS = (
    ("建立客户服务群", "setup_group", None, 0, "high", "成交后前期交接：拉客户联系人、销售、运营负责人进入服务群。"),
    ("发送运营说明与素材清单", "confirm_service", None, 1, "high", "向客户说明服务范围、每周更新节奏、周总结规则，并一次性发送素材/权限清单。"),
)

PLATFORM_ONBOARDING_STEPS = {
    "google_business": (
        ("Google商家 权限对接", "bind_google", 2, "high", "确认 Google Business Profile 管理权限、账号归属、验证码或邀请流程。"),
        ("Google商家 基础信息完善", "update_info", 3, "medium", "完善名称、地址、电话、营业时间、服务项目、菜单、图片等基础资料。"),
        ("Google商家 正式运营启动", "publish_content", 5, "medium", "进入正式运营节奏：每周更新 3 次，并纳入每周总结汇报。"),
    ),
    "facebook": (
        ("Facebook 权限对接", "open_facebook", 2, "high", "确认 Facebook Page / Business Suite 权限、主页管理员和资产归属。"),
        ("Facebook 主页资料完善", "update_info", 3, "medium", "完善主页简介、联系方式、营业时间、菜单/服务、头像封面和行动按钮。"),
        ("Facebook 正式运营启动", "publish_content", 5, "medium", "进入正式运营节奏：每周更新 3 次，并纳入每周总结汇报。"),
    ),
    "instagram": (
        ("Instagram 权限对接", "open_instagram", 2, "high", "确认 Instagram 账号登录方式、授权方式，以及是否已与 Facebook 主页关联。"),
        ("Instagram 主页资料完善", "update_info", 3, "medium", "完善头像、简介、联系方式、营业地址、链接和精选展示。"),
        ("Instagram 正式运营启动", "publish_content", 5, "medium", "进入正式运营节奏：每周更新 3 次，并纳入每周总结汇报。"),
    ),
    "yelp": (
        ("Yelp 权限对接", "other", 2, "high", "确认 Yelp 商家页认领、管理员权限、登录方式和店铺归属。"),
        ("Yelp 基础信息完善", "update_info", 3, "medium", "完善地址、电话、营业时间、分类、服务项目、菜单/图片等资料。"),
        ("Yelp 正式运营启动", "publish_content", 5, "medium", "进入正式运营节奏：每周更新 3 次，并纳入每周总结汇报。"),
    ),
    "tiktok": (
        ("TikTok 账号/权限对接", "other", 2, "high", "确认 TikTok 账号登录方式、企业资料、管理员权限和素材授权。"),
        ("TikTok 主页资料完善", "update_info", 3, "medium", "完善头像、简介、联系方式、链接、店铺定位和内容方向。"),
        ("TikTok 正式运营启动", "publish_content", 5, "medium", "进入正式运营节奏：每周更新 3 次，并纳入每周总结汇报。"),
    ),
    "xiaohongshu": (
        ("小红书 账号/权限对接", "other", 2, "high", "确认小红书账号登录方式、店铺/品牌信息、管理员权限和素材授权。"),
        ("小红书 店铺资料完善", "update_info", 3, "medium", "完善头像、简介、店铺定位、服务项目、联系方式和内容方向。"),
        ("小红书 正式运营启动", "publish_content", 5, "medium", "进入正式运营节奏：每周更新 3 次，并纳入每周总结汇报。"),
    ),
    "x": (
        ("X 账号/权限对接", "other", 2, "high", "确认 X 账号登录方式、管理员权限、品牌资料和素材授权。"),
        ("X 主页资料完善", "update_info", 3, "medium", "完善头像、简介、联系方式、链接、品牌语气和内容方向。"),
        ("X 正式运营启动", "publish_content", 5, "medium", "进入正式运营节奏：每周更新 3 次，并纳入每周总结汇报。"),
    ),
}


def _step(
    status: str,
    message: str,
    *,
    resource_id: int | None = None,
    created_count: int = 0,
    retryable: bool = False,
) -> dict[str, Any]:
    return {
        "status": status,
        "message": message,
        "resource_id": resource_id,
        "created_count": created_count,
        "retryable": retryable,
    }


def _normalize(value: str | None) -> str:
    return "".join((value or "").lower().split())


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _platforms(deal: Deals) -> list[str]:
    return list(dict.fromkeys(
        item.strip()
        for item in (deal.package_platforms or "").split(",")
        if item.strip() in PLATFORM_ONBOARDING_STEPS
    ))


def _onboarding_steps(platforms: list[str]) -> list[tuple[str, str, str | None, int, str, str]]:
    if not platforms:
        return []
    result = list(COMMON_ONBOARDING_STEPS)
    for platform in platforms:
        result.extend(
            (name, task_type, platform, offset, priority, notes)
            for name, task_type, offset, priority, notes in PLATFORM_ONBOARDING_STEPS[platform]
        )
    result.append((
        "首周运营总结汇报",
        "submit_report",
        None,
        7,
        "medium",
        "前期运营启动后，整理首周执行情况、素材使用情况、卡点和下周计划。",
    ))
    return result


async def load_deal_for_finalize(db: AsyncSession, deal_id: int) -> Deals:
    result = await db.execute(
        select(Deals).where(Deals.id == deal_id).with_for_update()
    )
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deals not found")
    return deal


async def finalize_subscription_and_customer(
    db: AsyncSession,
    deal: Deals,
    *,
    ensure_subscription: bool,
    auto_renew: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    customer = await db.get(Customers, deal.customer_id)
    if not customer:
        raise HTTPException(status_code=409, detail="成交关联客户不存在，无法完成交接")

    subscription_step = _step("skipped", "本次成交不需要建立订阅")
    if ensure_subscription:
        if not deal.service_start_date or not deal.service_end_date:
            raise HTTPException(status_code=422, detail="建立订阅需要服务开始和结束日期")

        subscriptions = list((await db.scalars(
            select(Subscriptions)
            .where(Subscriptions.deal_id == deal.id)
            .order_by(Subscriptions.id.asc())
            .limit(2)
        )).all())
        subscription = subscriptions[0] if subscriptions else None
        reused_legacy = False
        if subscription is None:
            legacy = list((await db.scalars(
                select(Subscriptions)
                .where(
                    Subscriptions.deal_id.is_(None),
                    Subscriptions.customer_id == deal.customer_id,
                    Subscriptions.package_name == (deal.package_name or ""),
                    Subscriptions.start_date == deal.service_start_date,
                    Subscriptions.end_date == deal.service_end_date,
                )
                .order_by(Subscriptions.id.asc())
                .limit(1)
            )).all())
            subscription = legacy[0] if legacy else None
            reused_legacy = subscription is not None

        now = datetime.now(BUSINESS_TIMEZONE)
        payload = {
            "deal_id": deal.id,
            "customer_id": deal.customer_id,
            "customer_name": customer.business_name,
            "engagement_id": deal.engagement_id,
            "business_line_id": deal.business_line_id,
            "product_id": deal.product_id,
            "product_plan_id": deal.product_plan_id,
            "package_name": deal.package_name or "未命名套餐",
            "package_price": float(deal.deal_amount or 0),
            "selected_platforms": deal.package_platforms,
            "billing_cycle": deal.billing_cycle,
            "start_date": deal.service_start_date,
            "end_date": deal.service_end_date,
            "auto_renew": auto_renew,
            "renewal_person": customer.sales_person or deal.sales_name,
            "next_payment_date": deal.service_end_date if auto_renew else None,
            "status": "active",
            "renewal_result": "stripe_subscription_created" if auto_renew else "manual_subscription_created",
            "updated_at": now,
        }
        if subscription is None:
            subscription = Subscriptions(created_at=now, **payload)
            db.add(subscription)
            message = "已建立订阅"
        else:
            for key, value in payload.items():
                setattr(subscription, key, value)
            if len(subscriptions) > 1:
                message = f"已复用订阅 #{subscription.id}；检测到重复订阅，请人工核对"
            elif reused_legacy:
                message = "已复用并关联原有订阅"
            else:
                message = "订阅已存在并完成核对"
        await db.flush()
        subscription_step = _step(
            "failed" if len(subscriptions) > 1 else "completed",
            message,
            resource_id=subscription.id,
            retryable=False,
        )

    if customer.status != "closed":
        customer.status = "closed"
        customer.updated_at = datetime.now(BUSINESS_TIMEZONE)
        customer_message = "客户状态已更新为已成交"
    else:
        customer_message = "客户已是成交状态"
    await db.flush()
    customer_step = _step("completed", customer_message, resource_id=customer.id)
    return subscription_step, customer_step


async def ensure_service_board(
    db: AsyncSession,
    deal: Deals,
    *,
    actor_id: str,
    actor_name: str,
) -> dict[str, Any]:
    customer = await db.get(Customers, deal.customer_id)
    if not customer:
        raise HTTPException(status_code=409, detail="成交关联客户不存在，无法生成服务看板")

    platforms = _platforms(deal)
    steps = _onboarding_steps(platforms)
    if not steps:
        raise HTTPException(status_code=422, detail="未配置可识别的合作平台，无法生成服务看板")

    marker = f"成交记录 #{deal.id}"
    progresses = list((await db.scalars(
        select(Service_progresses)
        .where(Service_progresses.customer_id == deal.customer_id)
        .order_by(Service_progresses.id.asc())
    )).all())
    progress = next((row for row in progresses if marker in (row.notes or "")), None)
    if progress is None:
        package_key = _normalize(deal.package_name)
        progress = next((
            row for row in progresses
            if (
                row.service_stage != "ended"
                and _normalize(row.package_name) == package_key
                and "成交记录 #" not in (row.notes or "")
            )
        ), None)

    now = datetime.now(BUSINESS_TIMEZONE)
    platform_text = ",".join(platforms)
    if progress is None:
        progress = Service_progresses(
            customer_id=customer.id,
            customer_name=customer.business_name,
            service_type=deal.product_type or "social_media",
            service_stage="deal_handover",
            progress_percent=10,
            sales_person=customer.sales_person or deal.sales_name,
            ops_person="",
            design_person="",
            package_name=deal.package_name or "",
            package_platforms=platform_text,
            industry=customer.industry or "",
            country=customer.country or "",
            state=customer.state or "",
            city=customer.city or "",
            service_start_date=_iso(deal.service_start_date or deal.deal_date),
            service_end_date=_iso(deal.service_end_date),
            last_update_time=now.isoformat(),
            last_update_person=actor_name,
            last_work_summary="成交后按交接要求生成前期运营流程",
            issue_status="none",
            issue_description="",
            issue_owner="",
            issue_resolved=True,
            notes=f"由{marker}生成前期工作看板。",
            user_id=actor_id,
            created_at=now.isoformat(),
        )
        db.add(progress)
        await db.flush()
        progress_created = True
    else:
        progress.package_name = deal.package_name or progress.package_name
        progress.package_platforms = platform_text or progress.package_platforms
        progress.service_start_date = _iso(deal.service_start_date or deal.deal_date) or progress.service_start_date
        progress.service_end_date = _iso(deal.service_end_date) or progress.service_end_date
        progress.last_update_time = now.isoformat()
        progress.last_update_person = actor_name
        progress.last_work_summary = "成交后同步核对并补齐前期运营流程"
        if marker not in (progress.notes or ""):
            progress.notes = f"{(progress.notes or '').strip()} 由{marker}关联。".strip()
        await db.flush()
        progress_created = False

    existing_tasks = list((await db.scalars(
        select(Service_tasks)
        .where(Service_tasks.service_progress_id == progress.id)
        .order_by(Service_tasks.id.asc())
    )).all())
    existing_keys = {(_normalize(row.task_name), row.platform or "") for row in existing_tasks}
    today = now.date()
    platform_names = "、".join(PLATFORM_LABELS.get(item, item) for item in platforms)
    created_count = 0
    for task_name, task_type, platform, offset, priority, notes in steps:
        key = (_normalize(task_name), platform or "")
        if key in existing_keys:
            continue
        db.add(Service_tasks(
            service_progress_id=progress.id,
            customer_id=customer.id,
            customer_name=customer.business_name,
            task_name=task_name,
            task_type=task_type,
            platform=platform,
            assignee_name=progress.ops_person or None,
            priority=priority,
            status="pending",
            due_date=(today + timedelta(days=offset)).isoformat(),
            notes=f"{notes} 合作平台：{platform_names}。",
            user_id=actor_id,
            created_at=now.isoformat(),
        ))
        existing_keys.add(key)
        created_count += 1
    await db.flush()

    if progress_created:
        message = f"已生成服务看板和 {created_count} 个前期任务"
    elif created_count:
        message = f"服务看板已存在，已补齐 {created_count} 个前期任务"
    else:
        message = "服务看板及前期任务已完整"
    return _step("completed", message, resource_id=progress.id, created_count=created_count)
