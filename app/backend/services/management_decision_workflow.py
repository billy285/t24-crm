from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, time, timezone
from typing import Any, Iterable, Optional
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.customers import Customers
from models.management_decisions import (
    BILLING_CYCLES,
    COLLECTION_METHODS,
    ENGAGEMENT_STATUSES,
    BusinessLine,
    ClassificationReviewDecision,
    CustomerEngagement,
    EngagementLifecycleEvent,
    EngagementSourceLink,
    ProductCatalog,
)
from models.payments import Payments
from models.subscriptions import Subscriptions
from services.management_decision_preview import build_classification_preview


ACTIVE_PROJECT_STATUSES = {"pending_setup", "trial", "active_paid", "at_risk", "paused", "pending_stop", "reactivated"}
DEFAULT_PRODUCTS = {
    "managed_service": ("managed_service_legacy", "代运营历史套餐", "recurring"),
    "restaurant_os": ("restaurant_os_legacy", "餐饮 OS", "recurring"),
    "beauty_os": ("beauty_os_legacy", "美业 OS", "recurring"),
    "one_time_project": ("one_time_legacy", "一次性项目", "one_time"),
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def review_key(customer_id: int) -> str:
    return f"customer:{customer_id}:classification"


def _engagement_payload(
    engagement: CustomerEngagement,
    line: BusinessLine,
    product: ProductCatalog,
    customer: Customers,
) -> dict[str, Any]:
    return {
        "id": engagement.id,
        "engagement_code": engagement.engagement_code,
        "customer_id": engagement.customer_id,
        "customer_name": customer.business_name,
        "customer_code": customer.customer_code,
        "business_line": {"code": line.code, "name": line.name},
        "product": {"code": product.code, "name": product.name},
        "package_name": engagement.package_name or product.name,
        "status": engagement.status,
        "billing_cycle": engagement.billing_cycle,
        "collection_method": engagement.collection_method,
        "currency": engagement.currency,
        "owner_employee_id": engagement.owner_employee_id,
        "sales_employee_id": engagement.sales_employee_id,
        "trial_started_at": engagement.trial_started_at,
        "paid_started_at": engagement.paid_started_at,
        "paused_at": engagement.paused_at,
        "stopped_at": engagement.stopped_at,
        "stop_reason_code": engagement.stop_reason_code,
        "stop_note": engagement.stop_note,
        "industry": customer.industry,
        "sales_person": customer.sales_person,
        "created_at": engagement.created_at,
        "updated_at": engagement.updated_at,
    }


async def _all_preview_items(db: AsyncSession, start_date: date) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    first = await build_classification_preview(db, start_date=start_date, page=1, page_size=100)
    items = list(first["items"])
    summaries = [first["summary"]]
    page = 2
    while len(items) < int(first["total"]):
        next_page = await build_classification_preview(db, start_date=start_date, page=page, page_size=100)
        items.extend(next_page["items"])
        summaries.append(next_page["summary"])
        if not next_page["items"]:
            break
        page += 1
    component_counts: Counter[str] = Counter()
    warning_counts: Counter[str] = Counter()
    for summary in summaries:
        component_counts.update(summary.get("components", {}))
        warning_counts.update(summary.get("warning_counts", {}))
    return items, {
        "customers": len(items),
        "payments": sum(int(summary.get("payments", 0)) for summary in summaries),
        "subscriptions": sum(int(summary.get("subscriptions", 0)) for summary in summaries),
        "components": dict(sorted(component_counts.items())),
        "warning_counts": dict(sorted(warning_counts.items())),
    }


def _warning_rows(item: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for warning in item.get("warnings", []):
        rows.append({**warning, "scope": "lifecycle", "source_id": None})
    for payment in item.get("payments", []):
        for warning in payment.get("warnings", []):
            rows.append({**warning, "scope": "payment", "source_id": payment["payment_id"]})
    for subscription in item.get("subscriptions", []):
        for warning in subscription.get("warnings", []):
            rows.append({**warning, "scope": "subscription", "source_id": subscription["subscription_id"]})
    return rows


def _suggestions(item: dict[str, Any]) -> list[dict[str, Any]]:
    suggestions: dict[str, dict[str, Any]] = {}

    def ensure(line: str, product_code: Optional[str] = None) -> dict[str, Any]:
        default_code, default_name, _kind = DEFAULT_PRODUCTS[line]
        row = suggestions.setdefault(line, {
            "business_line": line,
            "product_code": product_code or default_code,
            "product_name": default_name,
            "paid_started_at": None,
            "billing_cycle": None,
            "currency": "USD",
            "source_payment_ids": [],
            "source_subscription_ids": [],
            "basis": [],
        })
        if product_code and row["product_code"] == default_code:
            row["product_code"] = product_code
        return row

    for payment in item.get("payments", []):
        for component in payment.get("components", []):
            line = component.get("business_line")
            if line not in DEFAULT_PRODUCTS:
                continue
            row = ensure(line, component.get("product_code"))
            row["source_payment_ids"].append(payment["payment_id"])
            row["basis"].append(component.get("basis"))
            payment_date = payment.get("payment_date")
            if payment_date and (not row["paid_started_at"] or payment_date < row["paid_started_at"]):
                row["paid_started_at"] = payment_date
            row["billing_cycle"] = row["billing_cycle"] or payment.get("normalized_billing_cycle")
            row["currency"] = payment.get("currency") or row["currency"]

    for subscription in item.get("subscriptions", []):
        line = subscription.get("business_line")
        if line not in DEFAULT_PRODUCTS:
            continue
        row = ensure(line, subscription.get("product_code"))
        row["source_subscription_ids"].append(subscription["subscription_id"])
        row["basis"].append(subscription.get("basis"))
        start_at = subscription.get("start_date")
        if start_at and (not row["paid_started_at"] or start_at < row["paid_started_at"]):
            row["paid_started_at"] = start_at
        row["billing_cycle"] = row["billing_cycle"] or subscription.get("normalized_billing_cycle")

    for line, candidate in item.get("lifecycle_candidates", {}).items():
        if line not in DEFAULT_PRODUCTS:
            continue
        row = ensure(line)
        if candidate.get("payment_id") not in row["source_payment_ids"]:
            row["source_payment_ids"].append(candidate["payment_id"])
        if candidate.get("payment_date") and (
            not row["paid_started_at"] or candidate["payment_date"] < row["paid_started_at"]
        ):
            row["paid_started_at"] = candidate["payment_date"]

    for row in suggestions.values():
        row["source_payment_ids"] = sorted(set(row["source_payment_ids"]))
        row["source_subscription_ids"] = sorted(set(row["source_subscription_ids"]))
        row["basis"] = sorted({value for value in row["basis"] if value})
    return sorted(suggestions.values(), key=lambda row: row["business_line"])


async def build_classification_review_queue(db: AsyncSession, start_date: date) -> dict[str, Any]:
    preview_items, preview_summary = await _all_preview_items(db, start_date)
    decisions = (await db.execute(select(ClassificationReviewDecision))).scalars().all()
    decision_by_customer = {row.customer_id: row for row in decisions}
    project_rows = (await db.execute(
        select(CustomerEngagement, BusinessLine, ProductCatalog, Customers)
        .join(BusinessLine, BusinessLine.id == CustomerEngagement.business_line_id)
        .join(ProductCatalog, ProductCatalog.id == CustomerEngagement.product_id)
        .join(Customers, Customers.id == CustomerEngagement.customer_id)
        .order_by(CustomerEngagement.updated_at.desc(), CustomerEngagement.id.desc())
    )).all()
    projects_by_customer: dict[int, list[dict[str, Any]]] = defaultdict(list)
    project_by_id: dict[int, dict[str, Any]] = {}
    projects: list[dict[str, Any]] = []
    for engagement, line, product, customer in project_rows:
        payload = _engagement_payload(engagement, line, product, customer)
        projects.append(payload)
        project_by_id[int(engagement.id)] = payload
        projects_by_customer[engagement.customer_id].append(payload)

    subscription_links = (await db.execute(
        select(EngagementSourceLink).where(EngagementSourceLink.source_type == "subscription")
    )).scalars().all()
    subscription_ids = {int(row.source_id) for row in subscription_links if int(row.engagement_id) in project_by_id}
    subscriptions = (await db.execute(
        select(Subscriptions).where(Subscriptions.id.in_(subscription_ids))
    )).scalars().all() if subscription_ids else []
    subscription_by_id = {int(row.id): row for row in subscriptions}
    subscriptions_by_project: dict[int, list[Subscriptions]] = defaultdict(list)
    for link in subscription_links:
        subscription = subscription_by_id.get(int(link.source_id))
        if subscription and int(link.engagement_id) in project_by_id:
            subscriptions_by_project[int(link.engagement_id)].append(subscription)

    queue: list[dict[str, Any]] = []
    warning_counts: Counter[str] = Counter()
    for item in preview_items:
        customer_id = int(item["customer_id"])
        decision = decision_by_customer.get(customer_id)
        warnings = _warning_rows(item)
        warning_counts.update(row["code"] for row in warnings)
        queue.append({
            "review_key": review_key(customer_id),
            "customer_id": customer_id,
            "customer_code": item.get("customer_code"),
            "customer_name": item.get("customer_name"),
            "industry": item.get("industry"),
            "review_status": decision.decision if decision else "pending",
            "review_note": decision.note if decision else None,
            "reviewed_by_name": decision.reviewed_by_name if decision else None,
            "reviewed_at": decision.reviewed_at if decision else None,
            "customer_lifecycle": item.get("current_legacy_lifecycle"),
            "warnings": warnings,
            "suggestions": _suggestions(item),
            "projects": projects_by_customer.get(customer_id, []),
        })

    review_counts = Counter(row["review_status"] for row in queue)
    project_line_counts = Counter(row["business_line"]["code"] for row in projects)
    project_status_counts = Counter(row["status"] for row in projects)
    multi_project_customers = sum(1 for rows in projects_by_customer.values() if len(rows) > 1)
    lifecycle_by_customer = {
        int(row["customer_id"]): (row.get("customer_lifecycle") or {}).get("status")
        for row in queue
    }
    today = utcnow()
    line_metrics: dict[str, dict[str, Any]] = {}
    for line_code, default in DEFAULT_PRODUCTS.items():
        line_projects = [row for row in projects if row["business_line"]["code"] == line_code]
        stopped = [row for row in line_projects if row["status"] in {"stopped", "completed"}]
        active = [row for row in line_projects if row["status"] in ACTIVE_PROJECT_STATUSES]
        durations = []
        for row in line_projects:
            started = ensure_aware(row.get("paid_started_at"))
            if not started:
                continue
            ended = ensure_aware(row.get("stopped_at")) or today
            durations.append(max(0.0, (ended - started).days / 30.44))
        line_metrics[line_code] = {
            "name": default[1],
            "project_count": len(line_projects),
            "customer_count": len({row["customer_id"] for row in line_projects}),
            "active_count": len(active),
            "stopped_count": len(stopped),
            "at_risk_count": sum(1 for row in line_projects if row["status"] in {"at_risk", "pending_stop"}),
            "average_months": round(sum(durations) / len(durations), 1) if durations else None,
            "churn_rate": round(len(stopped) / len(line_projects), 4) if line_projects else None,
            "duration_sample_count": len(durations),
        }

    anomalies: list[dict[str, Any]] = []
    for item in queue:
        customer_projects = item["projects"]
        if item["review_status"] != "confirmed" and not customer_projects:
            anomalies.append({
                "code": "historical_classification_pending",
                "severity": "warning",
                "customer_id": item["customer_id"],
                "customer_name": item["customer_name"],
                "message": "历史客户尚未确认业务项目",
            })
    for project in projects:
        if project["status"] == "active_paid" and not project.get("paid_started_at"):
            anomalies.append({
                "code": "active_project_missing_paid_start",
                "severity": "high",
                "customer_id": project["customer_id"],
                "customer_name": project["customer_name"],
                "project_id": project["id"],
                "message": f"{project['business_line']['name']}已标记付费合作，但缺少首次有效收款日期",
            })
        if project["status"] in ACTIVE_PROJECT_STATUSES and not project.get("owner_employee_id"):
            anomalies.append({
                "code": "active_project_missing_owner",
                "severity": "warning",
                "customer_id": project["customer_id"],
                "customer_name": project["customer_name"],
                "project_id": project["id"],
                "message": f"{project['business_line']['name']}尚未指定项目负责人",
            })
        if lifecycle_by_customer.get(project["customer_id"]) == "stopped" and project["status"] in ACTIVE_PROJECT_STATUSES:
            anomalies.append({
                "code": "customer_project_status_mismatch",
                "severity": "high",
                "customer_id": project["customer_id"],
                "customer_name": project["customer_name"],
                "project_id": project["id"],
                "message": f"客户整体已停止，但{project['business_line']['name']}仍为合作状态",
            })

        status = project["status"]
        created_at = ensure_aware(project.get("created_at"))
        updated_at = ensure_aware(project.get("updated_at")) or created_at
        age_days = (today - created_at).days if created_at else 0
        unchanged_days = (today - updated_at).days if updated_at else age_days
        risk_message = None
        suggested_action = None
        if status == "pending_setup" and age_days >= 14:
            risk_message = f"{project['business_line']['name']}已待开通 {age_days} 天，请确认上线障碍或重新安排负责人"
            suggested_action = "核对交付进度；确认后再人工调整项目状态"
        elif status == "trial":
            trial_started_at = ensure_aware(project.get("trial_started_at")) or created_at
            trial_days = (today - trial_started_at).days if trial_started_at else 0
            if trial_days >= 30:
                risk_message = f"{project['business_line']['name']}已试用 {trial_days} 天，请确认是否转为付费或结束试用"
                suggested_action = "核对收款和客户意向；系统不会自动停止"
        elif status == "pending_stop" and unchanged_days >= 7:
            risk_message = f"{project['business_line']['name']}已待停止 {unchanged_days} 天，尚未完成最终确认"
            suggested_action = "核对停止日期和原因后由管理员确认"
        elif status == "paused" and unchanged_days >= 30:
            risk_message = f"{project['business_line']['name']}已暂停 {unchanged_days} 天，请确认恢复或正式停止"
            suggested_action = "联系客户复核；系统不会根据时长自动停止"
        elif status == "at_risk":
            risk_message = f"{project['business_line']['name']}当前已标记为有流失风险"
            suggested_action = "补充风险原因、跟进负责人和下一次确认日期"

        linked_subscriptions = subscriptions_by_project.get(int(project["id"]), [])
        if status in ACTIVE_PROJECT_STATUSES and linked_subscriptions:
            latest_subscription = max(
                linked_subscriptions,
                key=lambda row: ensure_aware(row.next_payment_date) or ensure_aware(row.end_date) or datetime.min.replace(tzinfo=timezone.utc),
            )
            due_at = ensure_aware(latest_subscription.next_payment_date) or ensure_aware(latest_subscription.end_date)
            overdue_days = (today - due_at).days if due_at else 0
            if overdue_days >= 7:
                risk_message = f"{project['business_line']['name']}关联订阅计划日期已过 {overdue_days} 天，请核对是否已收款或更新续费日期"
                suggested_action = "核对最新收款；系统只提醒，不会自动停止项目"

        if risk_message:
            anomalies.append({
                "code": "automatic_project_risk_reminder",
                "category": "risk",
                "severity": "warning",
                "customer_id": project["customer_id"],
                "customer_name": project["customer_name"],
                "project_id": project["id"],
                "message": risk_message,
                "suggested_action": suggested_action,
            })

        if (
            project["business_line"]["code"] != "one_time_project"
            and status in {"active_paid", "reactivated", "at_risk", "pending_stop"}
            and (not project.get("billing_cycle") or not project.get("collection_method"))
        ):
            missing = "收费周期和收款方式" if not project.get("billing_cycle") and not project.get("collection_method") else (
                "收费周期" if not project.get("billing_cycle") else "收款方式"
            )
            anomalies.append({
                "code": "active_project_missing_billing_config",
                "category": "data_quality",
                "severity": "warning",
                "customer_id": project["customer_id"],
                "customer_name": project["customer_name"],
                "project_id": project["id"],
                "message": f"{project['business_line']['name']}缺少{missing}，无法可靠判断续费风险",
                "suggested_action": "在客户管理中补齐项目收费信息",
            })

    combination_counts: Counter[str] = Counter()
    for customer_projects in projects_by_customer.values():
        line_names = sorted({row["business_line"]["name"] for row in customer_projects})
        if len(line_names) > 1:
            combination_counts[" + ".join(line_names)] += 1

    recommendations: list[dict[str, str]] = []
    confirmed_projects = len(projects)
    if confirmed_projects < 10:
        recommendations.append({"level": "observe", "title": "样本仍不足", "message": "先完成历史客户项目确认，再用生命周期结果决定招聘或增加开发投入。"})
    for line_code, metric in line_metrics.items():
        if metric["project_count"] >= 5 and (metric["churn_rate"] or 0) >= 0.3:
            recommendations.append({"level": "risk", "title": f"{metric['name']}流失偏高", "message": "优先复盘停止原因和交付质量，暂不建议只靠增加销售扩大规模。"})
        elif metric["active_count"] >= 10 and (metric["churn_rate"] or 0) < 0.2:
            recommendations.append({"level": "growth", "title": f"{metric['name']}具备投入信号", "message": "可结合利润与交付产能评估增加销售或运营人员。"})
    if not recommendations:
        recommendations.append({"level": "observe", "title": "继续积累真实项目数据", "message": "当前先确保每个项目的首次收款日期、负责人和停止原因完整。"})
    return {
        "start_date": start_date,
        "summary": {
            **preview_summary,
            "review_counts": dict(sorted(review_counts.items())),
            "warning_counts": dict(sorted(warning_counts.items())),
            "project_count": len(projects),
            "active_project_count": sum(1 for row in projects if row["status"] in ACTIVE_PROJECT_STATUSES),
            "at_risk_project_count": sum(1 for row in projects if row["status"] in {"at_risk", "pending_stop"}),
            "multi_project_customers": multi_project_customers,
            "project_line_counts": dict(sorted(project_line_counts.items())),
            "project_status_counts": dict(sorted(project_status_counts.items())),
            "anomaly_count": len(anomalies),
            "high_anomaly_count": sum(1 for row in anomalies if row["severity"] == "high"),
            "risk_reminder_count": sum(1 for row in anomalies if row.get("category") == "risk"),
            "line_metrics": line_metrics,
            "multi_project_combinations": dict(combination_counts.most_common()),
        },
        "items": queue,
        "projects": projects,
        "anomalies": anomalies,
        "recommendations": recommendations,
        "write_enabled": True,
        "phase": "review_and_project_management",
    }


async def _validate_sources(
    db: AsyncSession,
    customer_id: int,
    payment_ids: Iterable[int],
    subscription_ids: Iterable[int],
) -> tuple[list[int], list[int]]:
    wanted_payments = sorted({int(value) for value in payment_ids})
    wanted_subscriptions = sorted({int(value) for value in subscription_ids})
    if wanted_payments:
        actual = set((await db.execute(
            select(Payments.id).where(Payments.id.in_(wanted_payments), Payments.customer_id == customer_id)
        )).scalars().all())
        if actual != set(wanted_payments):
            raise ValueError("部分收款记录不存在或不属于该客户")
    if wanted_subscriptions:
        actual = set((await db.execute(
            select(Subscriptions.id).where(
                Subscriptions.id.in_(wanted_subscriptions), Subscriptions.customer_id == customer_id
            )
        )).scalars().all())
        if actual != set(wanted_subscriptions):
            raise ValueError("部分订阅记录不存在或不属于该客户")
    return wanted_payments, wanted_subscriptions


async def save_customer_classification_review(
    db: AsyncSession,
    *,
    customer_id: int,
    decision: str,
    projects: list[dict[str, Any]],
    note: Optional[str],
    actor_id: str,
    actor_name: str,
    commit: bool = True,
) -> dict[str, Any]:
    customer = (await db.execute(select(Customers).where(Customers.id == customer_id))).scalar_one_or_none()
    if not customer:
        raise ValueError("客户不存在")
    if decision not in {"confirmed", "needs_follow_up"}:
        raise ValueError("审核结果无效")
    if decision == "confirmed" and not projects:
        raise ValueError("确认分类时至少需要保留一个项目")

    now = utcnow()
    saved_projects: list[dict[str, Any]] = []
    for project in projects:
        line_code = str(project.get("business_line_code") or "").strip()
        line = (await db.execute(select(BusinessLine).where(
            BusinessLine.code == line_code, BusinessLine.is_active.is_(True)
        ))).scalar_one_or_none()
        if not line:
            raise ValueError(f"业务板块不存在：{line_code}")
        status = str(project.get("status") or "active_paid")
        if status not in ENGAGEMENT_STATUSES:
            raise ValueError("项目状态无效")
        billing_cycle = project.get("billing_cycle") or None
        if billing_cycle and billing_cycle not in BILLING_CYCLES:
            raise ValueError("收费周期无效")
        collection_method = project.get("collection_method") or None
        if collection_method and collection_method not in COLLECTION_METHODS:
            raise ValueError("收款方式无效")
        currency = str(project.get("currency") or "USD").upper()
        if len(currency) != 3:
            raise ValueError("币种必须是3位代码")

        default_code, default_name, default_kind = DEFAULT_PRODUCTS[line_code]
        product_code = str(project.get("product_code") or default_code).strip()
        product_name = str(project.get("product_name") or default_name).strip()
        product = (await db.execute(select(ProductCatalog).where(ProductCatalog.code == product_code))).scalar_one_or_none()
        if product and product.business_line_id != line.id:
            raise ValueError("产品编码已属于其他业务板块")
        if not product:
            product = ProductCatalog(
                business_line_id=line.id,
                code=product_code,
                name=product_name,
                billing_kind=default_kind,
                default_currency=currency,
                is_active=True,
            )
            db.add(product)
            await db.flush()

        engagement_id = project.get("engagement_id")
        engagement = None
        if engagement_id:
            engagement = (await db.execute(select(CustomerEngagement).where(
                CustomerEngagement.id == int(engagement_id), CustomerEngagement.customer_id == customer_id
            ))).scalar_one_or_none()
            if not engagement:
                raise ValueError("要更新的项目不存在或不属于该客户")
        if not engagement:
            engagement = (await db.execute(select(CustomerEngagement).where(
                CustomerEngagement.customer_id == customer_id,
                CustomerEngagement.business_line_id == line.id,
                CustomerEngagement.product_id == product.id,
            ).order_by(CustomerEngagement.id.desc()))).scalars().first()
        previous_status = engagement.status if engagement else None
        if not engagement:
            engagement = CustomerEngagement(
                customer_id=customer_id,
                business_line_id=line.id,
                product_id=product.id,
                engagement_code=f"ENG-{customer_id:06d}-{line_code[:8].upper()}-{uuid4().hex[:8].upper()}",
            )
            db.add(engagement)
            await db.flush()

        paid_started_at = ensure_aware(project.get("paid_started_at"))
        stopped_at = ensure_aware(project.get("stopped_at"))
        if status in {"active_paid", "reactivated"} and not paid_started_at:
            raise ValueError("付费合作中的项目必须填写第一笔有效收款日期")
        if status in {"stopped", "completed"} and not stopped_at:
            raise ValueError("已停止或已完成项目必须填写结束日期")
        if paid_started_at and stopped_at and stopped_at < paid_started_at:
            raise ValueError("项目结束日期不能早于开始日期")
        engagement.business_line_id = line.id
        engagement.product_id = product.id
        engagement.status = status
        engagement.package_name = str(project.get("package_name") or product_name).strip() or product.name
        engagement.billing_cycle = billing_cycle
        engagement.collection_method = collection_method
        engagement.currency = currency
        engagement.owner_employee_id = project.get("owner_employee_id")
        engagement.sales_employee_id = project.get("sales_employee_id")
        engagement.paid_started_at = paid_started_at
        engagement.stopped_at = stopped_at
        engagement.stop_reason_code = project.get("stop_reason_code") or None
        engagement.stop_note = project.get("stop_note") or None
        if status == "paused":
            engagement.paused_at = stopped_at or now
        elif status in {"active_paid", "reactivated", "at_risk", "pending_stop", "trial", "pending_setup"}:
            engagement.paused_at = None
            engagement.stopped_at = None
        await db.flush()

        payment_ids, subscription_ids = await _validate_sources(
            db,
            customer_id,
            project.get("source_payment_ids") or [],
            project.get("source_subscription_ids") or [],
        )
        for source_type, source_ids in (("payment", payment_ids), ("subscription", subscription_ids)):
            for source_id in source_ids:
                link_role = f"business_line:{line_code}"
                link = (await db.execute(select(EngagementSourceLink).where(
                    EngagementSourceLink.source_type == source_type,
                    EngagementSourceLink.source_id == source_id,
                    EngagementSourceLink.link_role == link_role,
                ))).scalar_one_or_none()
                if not link:
                    link = EngagementSourceLink(
                        engagement_id=engagement.id,
                        source_type=source_type,
                        source_id=source_id,
                        link_role=link_role,
                    )
                    db.add(link)
                link.engagement_id = engagement.id
                link.confidence = "confirmed"
                link.linked_by_id = actor_id
                link.linked_by_name = actor_name
                link.linked_at = now
                link.note = note

        event_key = f"classification-confirm:{review_key(customer_id)}:{engagement.id}"
        event = (await db.execute(select(EngagementLifecycleEvent).where(
            EngagementLifecycleEvent.idempotency_key == event_key
        ))).scalar_one_or_none()
        if not event:
            db.add(EngagementLifecycleEvent(
                engagement_id=engagement.id,
                event_type="classification_confirmed",
                effective_at=paid_started_at or now,
                idempotency_key=event_key,
                actor_id=actor_id,
                actor_name=actor_name,
                note=note or "管理员确认历史分类并建立独立项目",
            ))
        if previous_status and previous_status != status:
            db.add(EngagementLifecycleEvent(
                engagement_id=engagement.id,
                event_type="status_changed",
                effective_at=stopped_at or paid_started_at or now,
                reason_code=engagement.stop_reason_code,
                actor_id=actor_id,
                actor_name=actor_name,
                note=f"{previous_status} -> {status}" + (f"；{note}" if note else ""),
            ))
        saved_projects.append({
            "id": engagement.id,
            "business_line": line_code,
            "package_name": engagement.package_name,
            "status": engagement.status,
        })

    decision_row = (await db.execute(select(ClassificationReviewDecision).where(
        ClassificationReviewDecision.review_key == review_key(customer_id)
    ))).scalar_one_or_none()
    if not decision_row:
        decision_row = ClassificationReviewDecision(review_key=review_key(customer_id), customer_id=customer_id)
        db.add(decision_row)
    decision_row.decision = decision
    decision_row.note = note
    decision_row.reviewed_by_id = actor_id
    decision_row.reviewed_by_name = actor_name
    decision_row.reviewed_at = now
    if commit:
        await db.commit()
    else:
        await db.flush()
    return {"customer_id": customer_id, "decision": decision, "projects": saved_projects}


async def update_customer_engagement(
    db: AsyncSession,
    *,
    engagement_id: int,
    status: str,
    effective_at: datetime,
    reason_code: Optional[str],
    note: Optional[str],
    actor_id: str,
    actor_name: str,
) -> dict[str, Any]:
    if status not in ENGAGEMENT_STATUSES:
        raise ValueError("项目状态无效")
    engagement = (await db.execute(select(CustomerEngagement).where(
        CustomerEngagement.id == engagement_id
    ))).scalar_one_or_none()
    if not engagement:
        raise ValueError("项目不存在")
    effective_at = ensure_aware(effective_at) or utcnow()
    previous_status = engagement.status
    engagement.status = status
    if status == "paused":
        engagement.paused_at = effective_at
    elif status in {"stopped", "completed"}:
        engagement.stopped_at = effective_at
        engagement.stop_reason_code = reason_code
        engagement.stop_note = note
    else:
        engagement.paused_at = None
        engagement.stopped_at = None
        engagement.stop_reason_code = None
        engagement.stop_note = None
    db.add(EngagementLifecycleEvent(
        engagement_id=engagement.id,
        event_type="status_changed",
        effective_at=effective_at,
        reason_code=reason_code,
        actor_id=actor_id,
        actor_name=actor_name,
        note=f"{previous_status} -> {status}" + (f"；{note}" if note else ""),
    ))
    await db.commit()
    return {"id": engagement.id, "customer_id": engagement.customer_id, "status": engagement.status}
