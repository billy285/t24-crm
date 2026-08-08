from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any, Iterable

from services.commissions import eligible_service_amount


ACTIVE_COOPERATION_STATUSES = {"pending_setup", "trial", "active_paid", "at_risk", "paused", "pending_stop", "reactivated"}
STOPPED_COOPERATION_STATUSES = {"stopped", "completed"}
RENEWAL_ATTENTION_STATUSES = {"expiring_soon", "renewal_pending", "expired", "not_configured"}
MANUAL_RENEWAL_STATUSES = {"paused", "lost", "renewed", "upgraded", "stopped"}


def _as_date(value: date | datetime | None) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    return value


def _timestamp(value: date | datetime | None) -> float:
    if value is None:
        return 0
    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)
    elif value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def _latest(rows: Iterable[Any], *fields: str) -> Any | None:
    values = list(rows)
    if not values:
        return None
    return max(values, key=lambda row: tuple(_timestamp(getattr(row, field, None)) for field in fields) + (int(getattr(row, "id", 0) or 0),))


def _normalized(value: str | None) -> str:
    return "".join(str(value or "").lower().split())


def _matching_payments(payments: list[Any], engagement: Any | None, subscription: Any | None, customer_engagement_count: int) -> list[Any]:
    service_payments = [row for row in payments if float(getattr(row, "amount_paid", 0) or 0) > 0 and eligible_service_amount(row) > 0]
    if engagement is not None:
        exact = [row for row in service_payments if getattr(row, "engagement_id", None) == engagement.id]
        if exact:
            return exact
        package_name = _normalized(getattr(engagement, "package_name", None))
        if package_name:
            named = [row for row in service_payments if not getattr(row, "engagement_id", None) and _normalized(getattr(row, "product_name", None)) == package_name]
            if named:
                return named
        return service_payments if customer_engagement_count == 1 else []

    if subscription is not None:
        package_name = _normalized(getattr(subscription, "package_name", None))
        if package_name:
            return [row for row in service_payments if not getattr(row, "engagement_id", None) and _normalized(getattr(row, "product_name", None)) == package_name]
    return service_payments if customer_engagement_count <= 1 else []


def _matching_subscriptions(subscriptions: list[Any], engagement: Any | None, customer_engagement_count: int) -> list[Any]:
    if engagement is None:
        return subscriptions
    exact = [row for row in subscriptions if getattr(row, "engagement_id", None) == engagement.id]
    if exact:
        return exact
    package_name = _normalized(getattr(engagement, "package_name", None))
    named = [
        row for row in subscriptions
        if not getattr(row, "engagement_id", None)
        and package_name
        and _normalized(getattr(row, "package_name", None)) == package_name
    ]
    if named:
        return named
    return subscriptions if customer_engagement_count == 1 else []


def _cooperation_status(engagement: Any | None, subscription: Any | None) -> str:
    if engagement is not None:
        return str(getattr(engagement, "status", None) or "unknown")
    subscription_status = str(getattr(subscription, "status", None) or "")
    if subscription_status in {"stopped", "lost", "upgraded"}:
        return "stopped"
    if subscription_status == "paused":
        return "paused"
    if subscription is not None:
        return "active_paid"
    return "unknown"


def _renewal_status(
    cooperation_status: str,
    subscription: Any | None,
    payments: list[Any],
    *,
    as_of: date,
    warning_days: int,
    renewal_applicable: bool,
) -> tuple[str, date | None, date | None]:
    if cooperation_status in STOPPED_COOPERATION_STATUSES:
        return "stopped", None, None

    latest_receipt = _latest(payments, "payment_date", "created_at")
    last_receipt_at = _as_date(getattr(latest_receipt, "payment_date", None) or getattr(latest_receipt, "created_at", None)) if latest_receipt else None
    paid_through_values = [_as_date(getattr(row, "coverage_end", None)) for row in payments]
    paid_through_at = max((value for value in paid_through_values if value), default=None)

    if not renewal_applicable:
        return "not_applicable", None, last_receipt_at

    if subscription is None:
        return "not_configured", paid_through_at, last_receipt_at

    last_receipt_at = last_receipt_at or _as_date(getattr(subscription, "last_payment_date", None))

    status = str(getattr(subscription, "status", None) or "")
    if status in MANUAL_RENEWAL_STATUSES:
        return status, paid_through_at or _as_date(getattr(subscription, "end_date", None)), last_receipt_at
    if status == "renewal_pending":
        due_at = _as_date(getattr(subscription, "next_payment_date", None) or getattr(subscription, "end_date", None))
        return "renewal_pending", due_at, last_receipt_at

    due_candidates = [
        _as_date(getattr(subscription, "next_payment_date", None)),
        _as_date(getattr(subscription, "end_date", None)),
        paid_through_at,
    ]
    due_at = max((value for value in due_candidates if value), default=None)
    if due_at is None:
        return status or "active", None, last_receipt_at

    days = (due_at - as_of).days
    if bool(getattr(subscription, "auto_renew", False)) and days <= 0:
        return "renewal_pending", due_at, last_receipt_at
    if days <= 0:
        return "expired", due_at, last_receipt_at
    if days <= warning_days:
        return "expiring_soon", due_at, last_receipt_at
    return "active", due_at, last_receipt_at


def _commission_impact(attribution: Any, cooperation_status: str, renewal_status: str) -> str:
    if not bool(getattr(attribution, "is_active", False)):
        return "历史归属，仅保留历史分润"
    if cooperation_status in STOPPED_COOPERATION_STATUSES or renewal_status in {"stopped", "lost", "upgraded"}:
        return "停止后不再新增续费分润"
    if renewal_status == "not_configured":
        return "需补齐订阅资料后自动判断"
    if renewal_status == "not_applicable":
        return "一次性项目，无续费分润"
    if renewal_status in {"expiring_soon", "renewal_pending", "expired"}:
        return "续费实收后自动计提"
    return "服务实收后自动计提续费分润"


def build_partner_customer_status_rows(
    *,
    attributions: list[Any],
    customer_map: dict[int, Any],
    engagements: list[Any],
    subscriptions: list[Any],
    payments: list[Any],
    business_line_map: dict[int, str] | None = None,
    business_line_recurring_map: dict[int, bool] | None = None,
    product_map: dict[int, str] | None = None,
    as_of: date | None = None,
    warning_days: int = 7,
) -> list[dict[str, Any]]:
    """Build partner-safe status rows without returning payment amounts or internal notes."""
    as_of = as_of or datetime.now(timezone.utc).date()
    business_line_map = business_line_map or {}
    business_line_recurring_map = business_line_recurring_map or {}
    product_map = product_map or {}
    engagements_by_customer: dict[int, list[Any]] = defaultdict(list)
    subscriptions_by_customer: dict[int, list[Any]] = defaultdict(list)
    payments_by_customer: dict[int, list[Any]] = defaultdict(list)
    for row in engagements:
        engagements_by_customer[row.customer_id].append(row)
    for row in subscriptions:
        subscriptions_by_customer[row.customer_id].append(row)
    for row in payments:
        payments_by_customer[row.customer_id].append(row)

    output: list[dict[str, Any]] = []
    for attribution in attributions:
        customer = customer_map.get(attribution.customer_id)
        customer_engagements = engagements_by_customer.get(attribution.customer_id, [])
        engagement_map = {row.id: row for row in customer_engagements}
        selected_engagements: list[Any | None]
        if attribution.engagement_id:
            selected_engagements = [engagement_map.get(attribution.engagement_id)]
        elif attribution.is_active and customer_engagements:
            selected_engagements = sorted(customer_engagements, key=lambda row: (row.id or 0))
        else:
            selected_engagements = [None]

        for position, engagement in enumerate(selected_engagements):
            missing_explicit_engagement = bool(attribution.engagement_id and engagement is None)
            project_subscriptions = [] if missing_explicit_engagement else _matching_subscriptions(
                subscriptions_by_customer.get(attribution.customer_id, []), engagement, len(customer_engagements),
            )
            subscription = _latest(project_subscriptions, "end_date", "next_payment_date", "updated_at", "created_at")
            project_payments = [] if missing_explicit_engagement else _matching_payments(
                payments_by_customer.get(attribution.customer_id, []), engagement, subscription, len(customer_engagements),
            )
            cooperation_status = _cooperation_status(engagement, subscription)
            renewal_applicable = (
                str(getattr(engagement, "billing_cycle", None) or "") != "one_time"
                and business_line_recurring_map.get(getattr(engagement, "business_line_id", None), True)
            )
            renewal_status, next_due_at, last_receipt_at = _renewal_status(
                cooperation_status,
                subscription,
                project_payments,
                as_of=as_of,
                warning_days=warning_days,
                renewal_applicable=renewal_applicable,
            )
            if not attribution.is_active:
                cooperation_status = "historical"
                renewal_status = "historical"
                next_due_at = None
                last_receipt_at = None

            engagement_name = getattr(engagement, "package_name", None) if engagement else None
            if not engagement_name and subscription is not None:
                engagement_name = getattr(subscription, "package_name", None)
            output.append({
                "row_key": f"{attribution.id}:{getattr(engagement, 'id', None) or getattr(subscription, 'id', None) or position}",
                "attribution_id": attribution.id,
                "customer_id": attribution.customer_id,
                "customer_code": getattr(customer, "customer_code", None),
                "customer_name": getattr(customer, "business_name", None) or f"客户 #{attribution.customer_id}",
                "engagement_id": getattr(engagement, "id", None) or attribution.engagement_id,
                "engagement_name": engagement_name,
                "business_line_name": business_line_map.get(getattr(engagement, "business_line_id", None)),
                "product_name": product_map.get(getattr(engagement, "product_id", None)),
                "cooperation_status": cooperation_status,
                "renewal_status": renewal_status,
                "next_due_at": next_due_at,
                "last_receipt_at": last_receipt_at,
                "commission_impact": _commission_impact(attribution, cooperation_status, renewal_status),
                "effective_from": attribution.effective_from,
                "effective_to": attribution.effective_to,
                "is_active": attribution.is_active,
            })
    return output


def partner_status_summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    current_rows = [row for row in rows if row["is_active"]]
    rows_by_customer: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in current_rows:
        rows_by_customer[row["customer_id"]].append(row)
    active_ids = {
        customer_id for customer_id, customer_rows in rows_by_customer.items()
        if any(row["cooperation_status"] in ACTIVE_COOPERATION_STATUSES for row in customer_rows)
    }
    attention_ids = {row["customer_id"] for row in current_rows if row["renewal_status"] in RENEWAL_ATTENTION_STATUSES}
    stopped_ids = {
        customer_id for customer_id, customer_rows in rows_by_customer.items()
        if customer_rows and all(row["cooperation_status"] in STOPPED_COOPERATION_STATUSES for row in customer_rows)
    }
    return {
        "cooperation_customer_count": len(active_ids),
        "renewal_attention_count": len(attention_ids),
        "stopped_customer_count": len(stopped_ids),
    }
