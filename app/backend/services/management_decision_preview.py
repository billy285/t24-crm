from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Iterable, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.customer_lifecycles import CustomerLifecycleCycle
from models.customers import Customers
from models.payments import Payments
from models.subscriptions import Subscriptions


MONEY_QUANTUM = Decimal("0.01")
SUPPORTED_BILLING_CYCLES = {
    "monthly": "monthly",
    "month": "monthly",
    "monthly_payment": "monthly",
    "月付": "monthly",
    "quarterly": "quarterly",
    "quarter": "quarterly",
    "quarterly_payment": "quarterly",
    "季付": "quarterly",
    "annual": "annual",
    "annually": "annual",
    "yearly": "annual",
    "year": "annual",
    "annual_payment": "annual",
    "年付": "annual",
    "one_time": "one_time",
    "one-time": "one_time",
    "一次性": "one_time",
}

RESTAURANT_OS_MARKERS = (
    "restaurant os",
    "restaurant_os",
    "餐饮 os",
    "餐饮os",
    "t24menu",
    "点餐",
    "ordering system",
)
BEAUTY_OS_MARKERS = ("beauty os", "beauty_os", "美业 os", "美业os")
ONE_TIME_MARKERS = ("官网", "网站", "website", "web site", "域名", "domain", "主机", "hosting", "设计")
MANAGED_SERVICE_MARKERS = (
    "代运营",
    "management",
    "social media",
    "google商家",
    "google business",
    "facebook商家",
    "instagram商家",
    "yelp商家",
    "tiktok商家",
    "基础套餐",
    "进阶套餐",
    "专业套餐",
    "定制套餐",
)
AD_FUND_MARKERS = ("投流充值", "广告充值", "代充值", "ads recharge", "ad recharge")


def _money(value: object) -> Decimal:
    try:
        return Decimal(str(value or 0)).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0.00")


def _money_number(value: Decimal) -> float:
    return float(value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP))


def _text(value: object) -> str:
    return str(value or "").strip().lower()


def _warning(code: str, message: str, **context: object) -> dict[str, object]:
    payload: dict[str, object] = {"code": code, "message": message}
    if context:
        payload["context"] = context
    return payload


def _product_hint(product_name: Optional[str]) -> Optional[tuple[str, str, str]]:
    normalized = _text(product_name)
    if any(marker in normalized for marker in RESTAURANT_OS_MARKERS):
        return "os_subscription", "restaurant_os", "restaurant_os_legacy"
    if any(marker in normalized for marker in BEAUTY_OS_MARKERS):
        return "os_subscription", "beauty_os", "beauty_os_legacy"
    if any(marker in normalized for marker in ONE_TIME_MARKERS):
        return "one_time_project", "one_time_project", "one_time_legacy"
    if any(marker in normalized for marker in AD_FUND_MARKERS):
        return "pass_through_principal", "managed_service", "managed_service_legacy"
    if any(marker in normalized for marker in MANAGED_SERVICE_MARKERS):
        return "service_revenue", "managed_service", "managed_service_legacy"
    return None


def _fallback_classification(
    income_type: Optional[str], product_name: Optional[str]
) -> tuple[str, Optional[str], Optional[str], str, list[dict[str, object]]]:
    income = _text(income_type)
    hint = _product_hint(product_name)
    warnings: list[dict[str, object]] = []

    # Explicit OS and one-time product names are more specific than a generic
    # legacy income type. Industry/customer name is intentionally never used.
    if hint and hint[0] in {"os_subscription", "one_time_project"}:
        return *hint, "explicit_product_marker", warnings
    if income == "ordering_fee":
        return "os_subscription", "restaurant_os", "restaurant_os_legacy", "income_type", warnings
    if income == "website_fee":
        return "one_time_project", "one_time_project", "one_time_legacy", "income_type", warnings
    if income == "management_fee":
        return "service_revenue", "managed_service", "managed_service_legacy", "income_type", warnings
    if income == "ads_fee":
        return "pass_through_principal", "managed_service", "managed_service_legacy", "income_type", warnings
    if income == "renewal_fee":
        warnings.append(_warning(
            "renewal_line_inferred",
            "续费记录未明确业务板块，暂按代运营建议分类，需人工确认。",
        ))
        return "service_revenue", "managed_service", "managed_service_legacy", "income_type_inferred", warnings
    if hint:
        return *hint, "explicit_product_marker", warnings
    warnings.append(_warning("unrecognized_income", "无法可靠识别该笔收款所属业务板块，需人工确认。"))
    return "needs_review", None, None, "unrecognized", warnings


def _component(
    classification: str,
    business_line: Optional[str],
    product_code: Optional[str],
    amount: Decimal,
    basis: str,
) -> dict[str, object]:
    return {
        "classification": classification,
        "business_line": business_line,
        "product_code": product_code,
        "amount": _money_number(amount),
        "basis": basis,
        "lifecycle_eligible": classification in {"service_revenue", "os_subscription", "one_time_project"},
    }


def classify_payment(payment: Payments) -> dict[str, object]:
    amount_paid = _money(payment.amount_paid)
    management_amount = max(_money(payment.management_amount), Decimal("0.00"))
    ads_amount = max(_money(payment.ads_recharge_amount), Decimal("0.00"))
    warnings: list[dict[str, object]] = []
    components: list[dict[str, object]] = []

    income = _text(payment.income_type)
    if amount_paid <= 0:
        warnings.append(_warning("non_positive_payment", "非正数收款不参与生命周期起点识别。"))
    elif income == "management_ads_mixed" and not (management_amount > 0 and ads_amount > 0):
        warnings.append(_warning(
            "mixed_split_incomplete",
            "混合收款必须同时填写管理费与投流充值金额。",
        ))
        if management_amount + ads_amount > amount_paid + MONEY_QUANTUM:
            warnings.append(_warning(
                "components_exceed_paid",
                "管理费与投流充值拆分合计超过实收金额，需核对原始记录。",
                component_total=_money_number(management_amount + ads_amount),
                amount_paid=_money_number(amount_paid),
            ))
        components.append(_component("needs_review", None, None, amount_paid, "mixed_split_incomplete"))
    else:
        if management_amount > 0:
            components.append(_component(
                "service_revenue",
                "managed_service",
                "managed_service_legacy",
                management_amount,
                "explicit_management_amount",
            ))
        if ads_amount > 0:
            components.append(_component(
                "pass_through_principal",
                "managed_service",
                "managed_service_legacy",
                ads_amount,
                "explicit_ads_recharge_amount",
            ))

        explicit_total = management_amount + ads_amount
        if explicit_total > amount_paid + MONEY_QUANTUM:
            warnings.append(_warning(
                "components_exceed_paid",
                "管理费与投流充值拆分合计超过实收金额，需核对原始记录。",
                component_total=_money_number(explicit_total),
                amount_paid=_money_number(amount_paid),
            ))
        elif explicit_total < amount_paid:
            residual = amount_paid - explicit_total
            classification, line, product_code, basis, fallback_warnings = _fallback_classification(
                payment.income_type, payment.product_name
            )
            warnings.extend(fallback_warnings)
            if income == "management_ads_mixed":
                classification, line, product_code, basis = "needs_review", None, None, "unclassified_residual"
                warnings.append(_warning(
                    "unclassified_residual",
                    "混合收款拆分后仍有未归类余额，需人工确认。",
                    residual=_money_number(residual),
                ))
            components.append(_component(classification, line, product_code, residual, basis))

    normalized_cycle = SUPPORTED_BILLING_CYCLES.get(_text(payment.billing_cycle)) if payment.billing_cycle else None
    if payment.billing_cycle and not normalized_cycle:
        warnings.append(_warning(
            "unsupported_billing_cycle",
            "收费周期无法标准化，需确认月付、季付、年付或一次性。",
            billing_cycle=payment.billing_cycle,
        ))
    if not _text(payment.currency):
        warnings.append(_warning("missing_currency", "收款缺少币种，禁止与其他币种合并统计。"))
    if payment.coverage_start and payment.coverage_end and payment.coverage_end < payment.coverage_start:
        warnings.append(_warning("invalid_coverage_range", "服务结束日期早于开始日期。"))

    return {
        "payment_id": payment.id,
        "customer_id": payment.customer_id,
        "payment_date": payment.payment_date,
        "product_name": payment.product_name,
        "income_type": payment.income_type,
        "amount_paid": _money_number(amount_paid),
        "currency": payment.currency,
        "billing_cycle": payment.billing_cycle,
        "normalized_billing_cycle": normalized_cycle,
        "payment_method": payment.payment_method,
        "stripe_fee_amount": _money_number(_money(payment.stripe_fee_amount)),
        "components": components,
        "warnings": warnings,
        "lifecycle_eligible": any(bool(item["lifecycle_eligible"]) for item in components),
    }


def classify_subscription(subscription: Subscriptions) -> dict[str, object]:
    warnings: list[dict[str, object]] = []
    hint = _product_hint(subscription.package_name)
    normalized_cycle = SUPPORTED_BILLING_CYCLES.get(_text(subscription.billing_cycle)) if subscription.billing_cycle else None

    if hint and hint[0] == "os_subscription":
        classification, line, product_code = hint
        basis = "explicit_package_marker"
    elif hint and hint[0] == "one_time_project":
        classification, line, product_code = hint
        basis = "explicit_package_marker"
    elif hint and hint[0] == "pass_through_principal":
        classification, line, product_code = "needs_review", None, None
        basis = "ad_fund_subscription_ambiguous"
        warnings.append(_warning(
            "subscription_ad_fund_ambiguous",
            "疑似投流代充值套餐，不能据此自动开始代运营生命周期。",
        ))
    else:
        classification, line, product_code = "service_revenue", "managed_service", "managed_service_legacy"
        basis = "legacy_subscription_default"
        if not hint:
            warnings.append(_warning(
                "subscription_line_inferred",
                "历史订阅未明确业务板块，暂按代运营建议分类，需人工确认。",
            ))

    if subscription.billing_cycle and not normalized_cycle:
        warnings.append(_warning(
            "unsupported_billing_cycle",
            "订阅收费周期无法标准化。",
            billing_cycle=subscription.billing_cycle,
        ))
    if subscription.start_date and subscription.end_date and subscription.end_date < subscription.start_date:
        warnings.append(_warning("invalid_subscription_range", "订阅结束日期早于开始日期。"))

    return {
        "subscription_id": subscription.id,
        "customer_id": subscription.customer_id,
        "package_name": subscription.package_name,
        "package_price": _money_number(_money(subscription.package_price)),
        "billing_cycle": subscription.billing_cycle,
        "normalized_billing_cycle": normalized_cycle,
        "start_date": subscription.start_date,
        "end_date": subscription.end_date,
        "status": subscription.status,
        "classification": classification,
        "business_line": line,
        "product_code": product_code,
        "basis": basis,
        "lifecycle_eligible": classification in {"service_revenue", "os_subscription", "one_time_project"},
        "warnings": warnings,
    }


def _component_for_business_line(payment: dict[str, object], business_line: str) -> Optional[dict[str, object]]:
    for component in payment["components"]:  # type: ignore[index]
        if component["business_line"] == business_line and component["lifecycle_eligible"]:
            return component
    return None


def _first_candidate(payments: Iterable[dict[str, object]], business_line: str) -> Optional[dict[str, object]]:
    eligible = [
        payment
        for payment in payments
        if payment["payment_date"] is not None and _component_for_business_line(payment, business_line)
    ]
    if not eligible:
        return None
    first = min(eligible, key=lambda item: (item["payment_date"], item["payment_id"]))
    component = _component_for_business_line(first, business_line)
    return {
        "payment_id": first["payment_id"],
        "payment_date": first["payment_date"],
        "business_line": business_line,
        "classification": component["classification"] if component else None,
        "amount": component["amount"] if component else None,
        "currency": first["currency"],
    }


def _legacy_lifecycle_review(
    cycle: Optional[CustomerLifecycleCycle],
    payments: list[dict[str, object]],
    managed_candidate: Optional[dict[str, object]],
) -> tuple[Optional[dict[str, object]], list[dict[str, object]]]:
    if cycle is None:
        return None, []
    review_warnings: list[dict[str, object]] = []
    payment_by_id = {item["payment_id"]: item for item in payments}
    current_payment = payment_by_id.get(cycle.first_payment_id)
    lifecycle = {
        "cycle_id": cycle.id,
        "first_payment_id": cycle.first_payment_id,
        "started_at": cycle.started_at,
        "status": cycle.status,
        "start_locked": bool(cycle.start_locked),
    }

    if current_payment:
        current_classes = {item["classification"] for item in current_payment["components"]}
        if current_classes == {"pass_through_principal"}:
            review_warnings.append(_warning(
                "lifecycle_started_by_pass_through",
                "当前客户生命周期由纯投流充值开始；建议改用第一笔有效代运营服务费。",
                current_payment_id=cycle.first_payment_id,
                suggested_payment_id=managed_candidate["payment_id"] if managed_candidate else None,
            ))
        elif not _component_for_business_line(current_payment, "managed_service"):
            review_warnings.append(_warning(
                "lifecycle_started_by_non_service_payment",
                "当前客户生命周期起点不是可确认的代运营服务费。",
                current_payment_id=cycle.first_payment_id,
                suggested_payment_id=managed_candidate["payment_id"] if managed_candidate else None,
            ))
    elif cycle.first_payment_id is not None:
        review_warnings.append(_warning(
            "lifecycle_payment_outside_preview",
            "当前生命周期起点收款不在本次预览范围内或记录不存在。",
            current_payment_id=cycle.first_payment_id,
        ))

    if managed_candidate is None:
        review_warnings.append(_warning(
            "lifecycle_start_needs_review",
            "存在旧生命周期，但未找到可确认的代运营服务费起点。",
            current_payment_id=cycle.first_payment_id,
        ))
    elif cycle.first_payment_id != managed_candidate["payment_id"]:
        if not any(item["code"] == "lifecycle_started_by_pass_through" for item in review_warnings):
            review_warnings.append(_warning(
                "lifecycle_start_differs",
                "当前生命周期起点与只读分类建议不一致，需管理员核对。",
                current_payment_id=cycle.first_payment_id,
                suggested_payment_id=managed_candidate["payment_id"],
            ))
    return lifecycle, review_warnings


async def build_classification_preview(
    db: AsyncSession,
    *,
    customer_id: Optional[int] = None,
    start_date: date = date(2026, 1, 1),
    page: int = 1,
    page_size: int = 50,
) -> dict[str, object]:
    start_at = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
    payment_scope = [Payments.amount_paid > 0, Payments.payment_date >= start_at]
    if customer_id:
        payment_scope.append(Payments.customer_id == customer_id)

    customer_ids_query = select(Payments.customer_id).where(*payment_scope).distinct()
    total_customers = (
        await db.execute(select(func.count()).select_from(customer_ids_query.subquery()))
    ).scalar_one()
    page_customer_ids = list((await db.execute(
        customer_ids_query
        .order_by(Payments.customer_id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )).scalars().all())

    if not page_customer_ids:
        return {
            "mode": "dry_run",
            "write_enabled": False,
            "start_date": start_date,
            "items": [],
            "summary": {
                "customers": 0,
                "payments": 0,
                "subscriptions": 0,
                "components": {},
                "warning_counts": {},
            },
            "total": total_customers,
            "page": page,
            "page_size": page_size,
        }

    customers = (await db.execute(
        select(Customers).where(Customers.id.in_(page_customer_ids))
    )).scalars().all()
    payments = (await db.execute(
        select(Payments)
        .where(Payments.customer_id.in_(page_customer_ids), Payments.amount_paid > 0, Payments.payment_date >= start_at)
        .order_by(Payments.customer_id.asc(), Payments.payment_date.asc(), Payments.id.asc())
    )).scalars().all()
    subscriptions = (await db.execute(
        select(Subscriptions)
        .where(
            Subscriptions.customer_id.in_(page_customer_ids),
            or_(Subscriptions.end_date.is_(None), Subscriptions.end_date >= start_at),
        )
        .order_by(Subscriptions.customer_id.asc(), Subscriptions.start_date.asc(), Subscriptions.id.asc())
    )).scalars().all()
    cycles = (await db.execute(
        select(CustomerLifecycleCycle).where(
            CustomerLifecycleCycle.customer_id.in_(page_customer_ids),
            CustomerLifecycleCycle.cycle_number == 1,
        )
    )).scalars().all()

    customer_by_id = {row.id: row for row in customers}
    cycle_by_customer = {row.customer_id: row for row in cycles}
    payments_by_customer: dict[int, list[Payments]] = defaultdict(list)
    subscriptions_by_customer: dict[int, list[Subscriptions]] = defaultdict(list)
    for row in payments:
        payments_by_customer[row.customer_id].append(row)
    for row in subscriptions:
        subscriptions_by_customer[row.customer_id].append(row)

    component_counts: Counter[str] = Counter()
    warning_counts: Counter[str] = Counter()
    items: list[dict[str, object]] = []
    for selected_customer_id in page_customer_ids:
        customer = customer_by_id.get(selected_customer_id)
        classified_payments = [classify_payment(row) for row in payments_by_customer[selected_customer_id]]
        classified_subscriptions = [classify_subscription(row) for row in subscriptions_by_customer[selected_customer_id]]
        candidates = {
            line: candidate
            for line in ("managed_service", "restaurant_os", "beauty_os", "one_time_project")
            if (candidate := _first_candidate(classified_payments, line)) is not None
        }
        lifecycle, lifecycle_warnings = _legacy_lifecycle_review(
            cycle_by_customer.get(selected_customer_id),
            classified_payments,
            candidates.get("managed_service"),
        )

        for payment in classified_payments:
            component_counts.update(component["classification"] for component in payment["components"])
            warning_counts.update(warning["code"] for warning in payment["warnings"])
        for subscription in classified_subscriptions:
            warning_counts.update(warning["code"] for warning in subscription["warnings"])
        warning_counts.update(warning["code"] for warning in lifecycle_warnings)

        items.append({
            "customer_id": selected_customer_id,
            "customer_code": customer.customer_code if customer else None,
            "customer_name": customer.business_name if customer else None,
            "industry": customer.industry if customer else None,
            "payments": classified_payments,
            "subscriptions": classified_subscriptions,
            "lifecycle_candidates": candidates,
            "current_legacy_lifecycle": lifecycle,
            "warnings": lifecycle_warnings,
        })

    return {
        "mode": "dry_run",
        "write_enabled": False,
        "start_date": start_date,
        "items": items,
        "summary": {
            "customers": len(items),
            "payments": len(payments),
            "subscriptions": len(subscriptions),
            "components": dict(sorted(component_counts.items())),
            "warning_counts": dict(sorted(warning_counts.items())),
        },
        "total": total_customers,
        "page": page,
        "page_size": page_size,
    }
