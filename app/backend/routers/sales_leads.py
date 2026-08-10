import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_current_user
from models.employees import Employees
from models.sales_leads import SalesLeads
from models.sales_call_activities import SalesCallActivities
from models.sales_call_ai_analyses import SalesCallAiAnalyses
from models.sales_daily_dial_tasks import SalesDailyDialTasks
from models.sales_daily_quotas import SalesDailyQuotas
from models.sales_lead_conversion_logs import SalesLeadConversionLogs
from models.sales_lead_assignment_logs import SalesLeadAssignmentLogs
from models.sales_deal_controls import SalesHandoffChecklists, SalesQuoteRequests
from models.customers import Customers
from models.customer_contacts import Customer_contacts
from models.deals import Deals
from models.service_progresses import Service_progresses
from models.subscriptions import Subscriptions
from models.management_decisions import BusinessLine, CustomerEngagement
from schemas.auth import UserResponse
from schemas.aihub import ChatMessage, GenTxtRequest
from services.ai_config import humanize_ai_error, resolve_ai_runtime_config
from services.aihub import AIHubService
from services.deal_payment_sync import sync_payment_from_deal


router = APIRouter(prefix="/api/v1/sales-leads", tags=["sales-leads"])

ADMIN_ROLES = {"admin", "super_admin"}
LEAD_ROLES = ADMIN_ROLES | {"sales", "sales_manager"}
SALES_EDITABLE_FIELDS = {
    "status",
    "notes",
    "next_follow_up_at",
    "last_contact_at",
    "do_not_contact",
    "do_not_contact_reason",
}
DEFAULT_DAILY_TARGET = 100
MAX_DAILY_TARGET = 300
BUSINESS_TIMEZONE = ZoneInfo("Asia/Shanghai")
CALL_OUTCOMES = {
    "no_answer": "未接通",
    "callback": "待回访",
    "interested": "有意向",
    "appointment": "已预约",
    "not_interested": "无意向",
    "do_not_contact": "禁止再联系",
}

# These are suggestions, not forced schedules. Sales can always select a more
# appropriate time before saving the call result.
FOLLOW_UP_RULES = {
    "no_answer": (1, "未接通：建议下一个工作日回拨"),
    "callback": (1, "待回访：建议在约定时间前再次确认"),
    "interested": (1, "有意向：建议 24 小时内跟进需求或报价"),
    "appointment": (1, "已预约：建议在预约前确认时间与参会人"),
    "not_interested": (None, "无意向：不再自动安排回访"),
    "do_not_contact": (None, "禁止再联系：已从后续拨打任务排除"),
}


def _parse_optional_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=BUSINESS_TIMEZONE)
    except ValueError:
        return None


def _quote_product_type(package_name: Optional[str], selected_platforms: Optional[str]) -> str:
    raw = f"{package_name or ''} {selected_platforms or ''}".lower()
    categories = set()
    if any(value in raw for value in ["点餐", "ordering"]): categories.add("ordering_system")
    if any(value in raw for value in ["广告", "投放", "ads"]): categories.add("ads")
    if any(value in raw for value in ["官网", "网站", "website"]): categories.add("website")
    if any(value in raw for value in ["google", "facebook", "instagram", "yelp", "tiktok", "小红书", "商家管理"]): categories.add("social_media")
    if len(categories) > 1: return "combo"
    return next(iter(categories), "social_media")


def _role(user: UserResponse) -> str:
    return str(user.role or "").strip().lower()


def _employee_id(user: UserResponse) -> int:
    try:
        return int(user.id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=403, detail="当前账号未关联有效员工")


def _ensure_lead_role(user: UserResponse) -> None:
    if _role(user) not in LEAD_ROLES:
        raise HTTPException(status_code=403, detail="无权访问电话销售中心")


def _validate_manual_call_result(payload: "SalesCallResultCreate") -> None:
    notes = (payload.notes or "").strip()
    if payload.outcome == "callback" and not payload.next_follow_up_at:
        raise HTTPException(status_code=400, detail="待回访必须设置下次跟进时间")
    if payload.outcome in {"interested", "appointment"} and (not notes or not payload.next_follow_up_at):
        raise HTTPException(status_code=400, detail="有意向或已预约必须填写跟进内容和下次跟进时间")
    if payload.outcome == "do_not_contact" and not notes:
        raise HTTPException(status_code=400, detail="禁止再联系必须填写商家要求或原因")


class SalesLeadCreate(BaseModel):
    business_name: str = Field(min_length=1, max_length=200)
    contact_name: Optional[str] = None
    phone: str = Field(min_length=3, max_length=60)
    industry: Optional[str] = None
    country: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    address: Optional[str] = None
    website: Optional[str] = None
    source: Optional[str] = None
    status: str = "new"
    assigned_sales_id: Optional[int] = None
    notes: Optional[str] = None

    @field_validator("business_name", "phone")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        return value.strip()


class SalesLeadUpdate(BaseModel):
    business_name: Optional[str] = None
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    industry: Optional[str] = None
    country: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    address: Optional[str] = None
    website: Optional[str] = None
    source: Optional[str] = None
    status: Optional[str] = None
    assigned_sales_id: Optional[int] = None
    is_blacklisted: Optional[bool] = None
    do_not_contact: Optional[bool] = None
    do_not_contact_reason: Optional[str] = None
    notes: Optional[str] = None
    next_follow_up_at: Optional[datetime] = None
    last_contact_at: Optional[datetime] = None


class SalesLeadResponse(BaseModel):
    id: int
    business_name: str
    contact_name: Optional[str] = None
    phone: str
    industry: Optional[str] = None
    country: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    address: Optional[str] = None
    website: Optional[str] = None
    source: Optional[str] = None
    merchant_pool_id: Optional[int] = None
    analysis_snapshot: Optional[str] = None
    status: str
    assigned_sales_id: Optional[int] = None
    assigned_sales_name: Optional[str] = None
    team_manager_id: Optional[int] = None
    is_blacklisted: bool
    do_not_contact: bool
    do_not_contact_reason: Optional[str] = None
    converted_customer_id: Optional[int] = None
    converted_at: Optional[datetime] = None
    notes: Optional[str] = None
    next_follow_up_at: Optional[datetime] = None
    last_contact_at: Optional[datetime] = None
    created_by_id: Optional[int] = None
    created_by_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SalesLeadListResponse(BaseModel):
    items: List[SalesLeadResponse]
    total: int
    skip: int
    limit: int


class SalesAssigneeResponse(BaseModel):
    id: int
    name: str
    role: str
    supervisor: Optional[str] = None


class SalesDailyQuotaUpdate(BaseModel):
    sales_employee_id: int
    target_count: int = Field(ge=1, le=MAX_DAILY_TARGET)
    target_date: Optional[date] = None


class SalesCallResultCreate(BaseModel):
    outcome: str
    notes: Optional[str] = Field(default=None, max_length=4000)
    next_follow_up_at: Optional[datetime] = None

    @field_validator("outcome")
    @classmethod
    def validate_outcome(cls, value: str) -> str:
        if value not in CALL_OUTCOMES:
            raise ValueError("无效的通话结果")
        return value


class SalesCallAiGenerateRequest(BaseModel):
    transcript: str = Field(min_length=10, max_length=30000)
    transcript_source: str = Field(default="manual_transcript", max_length=50)


class SalesCallAiReviewRequest(BaseModel):
    analysis: dict
    needs_manager_intervention: bool = False


class SalesLeadConvertRequest(BaseModel):
    confirmation_notes: str = Field(min_length=3, max_length=1000)
    generate_service_board: bool = False


class RecoveryReasonRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class RecoveryExtensionRequest(RecoveryReasonRequest):
    requested_days: int = Field(default=3, ge=1, le=14)


class RecoveryReassignRequest(RecoveryReasonRequest):
    assigned_sales_id: int
    confirm_protected_transfer: bool = False


class RecoveryBatchRequest(RecoveryReasonRequest):
    lead_ids: list[int] = Field(min_length=1, max_length=200)
    action: str = Field(pattern="^(reclaim|reassign)$")
    assigned_sales_id: Optional[int] = Field(default=None, ge=1)
    confirm_protected_transfer: bool = False


def _parse_json_dict(raw: Optional[str]) -> dict:
    try:
        parsed = json.loads(raw or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _call_ai_fallback(transcript: str, notes: Optional[str]) -> dict:
    compact = " ".join(transcript.split())
    interest = "中"
    if any(word in compact for word in ["报价", "预约", "合作", "预算", "发我"]):
        interest = "高"
    elif any(word in compact for word in ["不需要", "不要", "拒绝", "不用"]):
        interest = "低"
    rejection = "未明确"
    for word in ["没预算", "已有团队", "不需要", "太贵", "没时间"]:
        if word in compact:
            rejection = word
            break
    return {
        "call_summary": compact[:500] or "信息不足：未提供可分析的通话转写。",
        "real_needs": "请销售根据原始转写补充客户真实需求；当前无法可靠判断。",
        "rejection_reason": rejection,
        "interest_level": interest,
        "next_contact_time": None,
        "next_conversation_advice": "围绕客户明确提到的问题进行回访，不要补充通话中未出现的承诺。",
        "recommended_material": "根据客户行业与真实需求，从已审核案例或报价单中人工选择。",
        "needs_manager_intervention": interest == "高" or rejection == "太贵",
        "source_notice": "此为保守模板，依据通话转写和销售备注生成；请人工复核。",
        "sales_notes": notes or "",
    }


def _extract_ai_json(raw: str) -> dict:
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < start:
        return {}
    try:
        value = json.loads(raw[start:end + 1])
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


async def _direct_report_ids(db: AsyncSession, user: UserResponse) -> list[int]:
    result = await db.execute(
        select(Employees.id).where(
            Employees.role == "sales",
            Employees.supervisor == (user.name or ""),
            Employees.status.in_(["active", "probation"]),
        )
    )
    return [int(value) for value in result.scalars().all()]


async def _scope_condition(db: AsyncSession, user: UserResponse):
    role = _role(user)
    if role in ADMIN_ROLES:
        return None

    current_id = _employee_id(user)
    if role == "sales":
        return SalesLeads.assigned_sales_id == current_id

    report_ids = await _direct_report_ids(db, user)
    visible_ids = list({current_id, *report_ids})
    return or_(
        SalesLeads.team_manager_id == current_id,
        SalesLeads.assigned_sales_id.in_(visible_ids),
    )


async def _get_scoped_lead(db: AsyncSession, lead_id: int, user: UserResponse) -> SalesLeads:
    query = select(SalesLeads).where(SalesLeads.id == lead_id)
    scope = await _scope_condition(db, user)
    if scope is not None:
        query = query.where(scope)
    lead = (await db.execute(query)).scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="线索不存在或不在您的权限范围内")
    return lead


async def _resolve_assignee(
    db: AsyncSession, assignee_id: Optional[int], user: UserResponse
) -> tuple[Optional[int], Optional[str], Optional[int]]:
    if assignee_id is None:
        return None, None, _employee_id(user) if _role(user) == "sales_manager" else None

    employee = (
        await db.execute(
            select(Employees).where(
                Employees.id == assignee_id,
                Employees.role == "sales",
                Employees.status.in_(["active", "probation"]),
            )
        )
    ).scalar_one_or_none()
    if not employee:
        raise HTTPException(status_code=400, detail="只能分配给在职电话销售")

    role = _role(user)
    if role == "sales_manager" and employee.supervisor != (user.name or ""):
        raise HTTPException(status_code=403, detail="只能分配给自己的直属销售")

    manager_id = _employee_id(user) if role == "sales_manager" else None
    return int(employee.id), employee.name, manager_id


async def _resolve_workbench_salesperson(
    db: AsyncSession, user: UserResponse, sales_employee_id: Optional[int]
) -> Employees:
    role = _role(user)
    current_id = _employee_id(user)
    target_id = sales_employee_id or (current_id if role == "sales" else None)
    if target_id is None:
        raise HTTPException(status_code=400, detail="请选择需要查看的电话销售")
    if role == "sales" and target_id != current_id:
        raise HTTPException(status_code=403, detail="销售只能查看自己的每日任务")
    employee = (await db.execute(select(Employees).where(Employees.id == target_id, Employees.role == "sales"))).scalar_one_or_none()
    if not employee:
        raise HTTPException(status_code=404, detail="电话销售账号不存在")
    if role == "sales_manager" and employee.supervisor != (user.name or ""):
        raise HTTPException(status_code=403, detail="只能查看直属销售的每日任务")
    return employee


async def _daily_quota(db: AsyncSession, sales_employee_id: int, target_date: date) -> int:
    quota = (await db.execute(
        select(SalesDailyQuotas).where(
            SalesDailyQuotas.sales_employee_id == sales_employee_id,
            SalesDailyQuotas.target_date == target_date,
        )
    )).scalar_one_or_none()
    return int(quota.target_count) if quota else DEFAULT_DAILY_TARGET


async def _ensure_daily_batch(
    db: AsyncSession, sales_employee_id: int, target_date: date, quota: int
) -> None:
    existing = (await db.execute(
        select(SalesDailyDialTasks).where(
            SalesDailyDialTasks.sales_employee_id == sales_employee_id,
            SalesDailyDialTasks.task_date == target_date,
        )
    )).scalars().all()
    if len(existing) >= quota:
        return

    existing_lead_ids = {task.lead_id for task in existing}
    candidates = (await db.execute(
        select(SalesLeads)
        .where(
            SalesLeads.assigned_sales_id == sales_employee_id,
            SalesLeads.is_blacklisted.is_(False),
            SalesLeads.do_not_contact.is_(False),
            SalesLeads.status.notin_(["lost", "blocked"]),
        )
    )).scalars().all()

    # A future callback must not occupy today's quota. New leads can still fill
    # the remaining slots so each salesperson has a usable fixed batch.
    due_candidates = [
        lead for lead in candidates
        if not lead.next_follow_up_at or (_business_date(lead.next_follow_up_at) or target_date) <= target_date
    ]

    priority_order = {"appointment": 0, "interested": 1, "follow_up": 2, "contacted": 3, "new": 4}
    due_candidates.sort(key=lambda lead: (
        priority_order.get(lead.status, 9),
        lead.next_follow_up_at is None,
        lead.next_follow_up_at.isoformat() if lead.next_follow_up_at else "9999-12-31T23:59:59",
        lead.id,
    ))
    for lead in due_candidates:
        if len(existing_lead_ids) >= quota:
            break
        if lead.id in existing_lead_ids:
            continue
        db.add(SalesDailyDialTasks(
            sales_employee_id=sales_employee_id,
            task_date=target_date,
            lead_id=lead.id,
            status="pending",
        ))
        existing_lead_ids.add(lead.id)
    await db.commit()


def _lead_status_from_outcome(outcome: str) -> str:
    return {
        "no_answer": "contacted",
        "callback": "follow_up",
        "interested": "interested",
        "appointment": "appointment",
        "not_interested": "lost",
        "do_not_contact": "blocked",
    }[outcome]


def _suggest_follow_up(outcome: str, now: datetime) -> tuple[Optional[datetime], str]:
    days, label = FOLLOW_UP_RULES[outcome]
    return (now + timedelta(days=days) if days is not None else None), label


def _workbench_priority(lead: SalesLeads, target_date: date) -> tuple[str, str]:
    follow_up_date = _business_date(lead.next_follow_up_at)
    if lead.status == "appointment":
        return "urgent", "优先确认预约时间"
    if lead.status == "interested":
        return "high", "优先跟进报价或需求"
    if lead.status == "follow_up" and follow_up_date and follow_up_date <= target_date:
        return "high", "今天应回访"
    if lead.status == "contacted":
        return "normal", "完成本次回拨"
    return "normal", "首次联系并记录结果"


PROTECTED_LEAD_STATUSES = {"interested", "appointment"}
RECOVERY_GRACE_HOURS = 48
OVERDUE_FOLLOW_UP_DAYS = 3


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _recovery_state(
    lead: SalesLeads,
    now: datetime,
    latest_activity: Optional[SalesCallActivities],
    protection_until: Optional[datetime],
) -> tuple[str, str, Optional[datetime]]:
    """Return a transparent recovery state without silently changing ownership."""
    if lead.converted_customer_id or lead.status in {"won", "lost", "blocked"} or lead.do_not_contact or lead.is_blacklisted:
        return "excluded", "已成交、无意向或受保护线索不会进入回收流程", None
    if lead.status in PROTECTED_LEAD_STATUSES:
        return "protected", "有意向或已预约，需主管填写原因后才可转交", None
    protection_until = _as_utc(protection_until)
    if protection_until and protection_until > now:
        return "extended", "销售延期已获主管批准，暂不回收", protection_until

    if latest_activity is None:
        assigned_at = _as_utc(lead.updated_at or lead.created_at)
        if assigned_at:
            deadline = assigned_at + timedelta(hours=RECOVERY_GRACE_HOURS)
            if deadline <= now:
                return "recoverable", "分配后 48 小时未开始处理，可由主管回收", deadline
            return "watch", "尚未拨打，达到 48 小时后将进入可回收名单", deadline
        return "watch", "尚未开始处理", None

    follow_up_at = _as_utc(lead.next_follow_up_at)
    if follow_up_at and follow_up_at + timedelta(days=OVERDUE_FOLLOW_UP_DAYS) <= now:
        return "recoverable", "已超过约定回访时间 3 天，可由主管回收", follow_up_at
    if follow_up_at:
        return "active", "已设置下次回访，归属受保护", follow_up_at
    return "active", "已有通话记录，归属受保护", None


async def _append_assignment_log(
    db: AsyncSession,
    lead: SalesLeads,
    action: str,
    user: UserResponse,
    *,
    from_employee_id: Optional[int] = None,
    from_employee_name: Optional[str] = None,
    to_employee_id: Optional[int] = None,
    to_employee_name: Optional[str] = None,
    reason: Optional[str] = None,
    effective_until: Optional[datetime] = None,
) -> SalesLeadAssignmentLogs:
    log = SalesLeadAssignmentLogs(
        lead_id=lead.id,
        action=action,
        from_sales_employee_id=from_employee_id,
        from_sales_employee_name=from_employee_name,
        to_sales_employee_id=to_employee_id,
        to_sales_employee_name=to_employee_name,
        reason=reason,
        effective_until=effective_until,
        operated_by_id=_employee_id(user),
        operated_by_name=user.name,
    )
    db.add(log)
    return log


async def _load_recovery_snapshot(
    db: AsyncSession, user: UserResponse
) -> list[dict]:
    query = select(SalesLeads).where(SalesLeads.assigned_sales_id.is_not(None))
    scope = await _scope_condition(db, user)
    if scope is not None:
        query = query.where(scope)
    leads = (await db.execute(query.order_by(SalesLeads.updated_at.asc(), SalesLeads.id.asc()))).scalars().all()
    if not leads:
        return []

    lead_ids = [lead.id for lead in leads]
    activities = (await db.execute(
        select(SalesCallActivities)
        .where(SalesCallActivities.lead_id.in_(lead_ids))
        .order_by(SalesCallActivities.lead_id.asc(), SalesCallActivities.called_at.desc(), SalesCallActivities.id.desc())
    )).scalars().all()
    latest_activities: dict[int, SalesCallActivities] = {}
    for activity in activities:
        latest_activities.setdefault(activity.lead_id, activity)

    logs = (await db.execute(
        select(SalesLeadAssignmentLogs)
        .where(SalesLeadAssignmentLogs.lead_id.in_(lead_ids))
        .order_by(SalesLeadAssignmentLogs.lead_id.asc(), SalesLeadAssignmentLogs.created_at.desc(), SalesLeadAssignmentLogs.id.desc())
    )).scalars().all()
    extension_until: dict[int, datetime] = {}
    latest_extension_requests: dict[int, SalesLeadAssignmentLogs] = {}
    latest_extension_approvals: dict[int, SalesLeadAssignmentLogs] = {}
    for log in logs:
        if log.action == "extension_approved" and log.effective_until and log.lead_id not in extension_until:
            extension_until[log.lead_id] = log.effective_until
        if log.action == "extension_approved" and log.lead_id not in latest_extension_approvals:
            latest_extension_approvals[log.lead_id] = log
        if log.action == "extension_requested" and log.lead_id not in latest_extension_requests:
            latest_extension_requests[log.lead_id] = log

    now = datetime.now(timezone.utc)
    snapshot = []
    for lead in leads:
        state, message, deadline = _recovery_state(
            lead, now, latest_activities.get(lead.id), extension_until.get(lead.id)
        )
        request = latest_extension_requests.get(lead.id)
        approval = latest_extension_approvals.get(lead.id)
        if request and approval and request.created_at <= approval.created_at:
            request = None
        snapshot.append({
            "lead_id": lead.id,
            "business_name": lead.business_name,
            "assigned_sales_id": lead.assigned_sales_id,
            "assigned_sales_name": lead.assigned_sales_name,
            "status": lead.status,
            "state": state,
            "message": message,
            "deadline": deadline,
            "last_contact_at": lead.last_contact_at,
            "next_follow_up_at": lead.next_follow_up_at,
            "extension_request": None if not request else {
                "id": request.id,
                "reason": request.reason,
                "requested_until": request.effective_until,
                "requested_by": request.operated_by_name,
                "created_at": request.created_at,
            },
        })
    return snapshot


@router.get("/assignees", response_model=List[SalesAssigneeResponse])
async def list_sales_assignees(
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_lead_role(current_user)
    role = _role(current_user)
    if role == "sales":
        return []

    query = select(Employees).where(
        Employees.role == "sales",
        Employees.status.in_(["active", "probation"]),
    )
    if role == "sales_manager":
        query = query.where(Employees.supervisor == (current_user.name or ""))
    result = await db.execute(query.order_by(Employees.name.asc()))
    return result.scalars().all()


@router.get("/stats")
async def get_sales_lead_stats(
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_lead_role(current_user)
    query = select(
        func.count(SalesLeads.id),
        func.count(SalesLeads.id).filter(SalesLeads.assigned_sales_id.is_not(None)),
        func.count(SalesLeads.id).filter(SalesLeads.assigned_sales_id.is_(None)),
        func.count(SalesLeads.id).filter(SalesLeads.is_blacklisted.is_(True)),
        func.count(SalesLeads.id).filter(SalesLeads.do_not_contact.is_(True)),
    )
    scope = await _scope_condition(db, current_user)
    if scope is not None:
        query = query.where(scope)
    row = (await db.execute(query)).one()
    return {
        "total": row[0] or 0,
        "assigned": row[1] or 0,
        "unassigned": row[2] or 0,
        "blacklisted": row[3] or 0,
        "do_not_contact": row[4] or 0,
    }


@router.get("", response_model=SalesLeadListResponse)
async def list_sales_leads(
    search: Optional[str] = None,
    lead_status: Optional[str] = Query(None, alias="status"),
    contact_rule: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=200),
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_lead_role(current_user)
    query = select(SalesLeads)
    count_query = select(func.count(SalesLeads.id))
    conditions = []
    scope = await _scope_condition(db, current_user)
    if scope is not None:
        conditions.append(scope)
    if search:
        term = f"%{search.strip()}%"
        conditions.append(
            or_(
                SalesLeads.business_name.ilike(term),
                SalesLeads.contact_name.ilike(term),
                SalesLeads.phone.ilike(term),
                SalesLeads.city.ilike(term),
            )
        )
    if lead_status:
        conditions.append(SalesLeads.status == lead_status)
    if contact_rule == "blacklisted":
        conditions.append(SalesLeads.is_blacklisted.is_(True))
    elif contact_rule == "do_not_contact":
        conditions.append(SalesLeads.do_not_contact.is_(True))
    elif contact_rule == "contactable":
        conditions.extend([
            SalesLeads.is_blacklisted.is_(False),
            SalesLeads.do_not_contact.is_(False),
        ])
    if conditions:
        query = query.where(*conditions)
        count_query = count_query.where(*conditions)
    total = (await db.execute(count_query)).scalar() or 0
    items = (
        await db.execute(query.order_by(SalesLeads.id.desc()).offset(skip).limit(limit))
    ).scalars().all()
    return {"items": items, "total": total, "skip": skip, "limit": limit}


@router.get("/workbench/today")
async def get_daily_call_workbench(
    sales_employee_id: Optional[int] = None,
    target_date: Optional[date] = None,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a fixed daily calling batch. Finished batches never refill automatically."""
    _ensure_lead_role(current_user)
    target_date = target_date or datetime.now(BUSINESS_TIMEZONE).date()
    salesperson = await _resolve_workbench_salesperson(db, current_user, sales_employee_id)
    quota = await _daily_quota(db, salesperson.id, target_date)
    await _ensure_daily_batch(db, salesperson.id, target_date, quota)
    tasks = (await db.execute(
        select(SalesDailyDialTasks, SalesLeads)
        .join(SalesLeads, SalesLeads.id == SalesDailyDialTasks.lead_id)
        .where(
            SalesDailyDialTasks.sales_employee_id == salesperson.id,
            SalesDailyDialTasks.task_date == target_date,
        )
        .order_by(SalesDailyDialTasks.status.asc(), SalesLeads.next_follow_up_at.is_(None), SalesLeads.next_follow_up_at.asc(), SalesDailyDialTasks.id.asc())
    )).all()
    items = []
    categories = {"unfinished": 0, "callback": 0, "interested": 0, "appointment": 0}
    for task, lead in tasks:
        if task.status != "completed":
            categories["unfinished"] += 1
        if lead.status == "follow_up":
            categories["callback"] += 1
        elif lead.status == "interested":
            categories["interested"] += 1
        elif lead.status == "appointment":
            categories["appointment"] += 1
        priority, next_action_label = _workbench_priority(lead, target_date)
        items.append({
            "task_id": task.id,
            "task_status": task.status,
            "completed_at": task.completed_at,
            "priority": priority,
            "next_action_label": next_action_label,
            "lead": SalesLeadResponse.model_validate(lead).model_dump(mode="json"),
        })
    completed = sum(1 for task, _lead in tasks if task.status == "completed")
    activities = (await db.execute(
        select(SalesCallActivities).where(SalesCallActivities.sales_employee_id == salesperson.id)
    )).scalars().all()
    day_activities = [item for item in activities if _business_date(item.called_at) == target_date]
    connected = sum(item.outcome != "no_answer" for item in day_activities)
    interested = sum(item.outcome in {"interested", "appointment"} for item in day_activities)
    appointments = sum(item.outcome == "appointment" for item in day_activities)
    due_callbacks = sum(
        lead.status == "follow_up"
        and (_business_date(lead.next_follow_up_at) or target_date) <= target_date
        for _task, lead in tasks
    )
    return {
        "target_date": target_date,
        "salesperson": {"id": salesperson.id, "name": salesperson.name},
        "quota": quota,
        "assigned_count": len(items),
        "completed_count": completed,
        "remaining_count": max(len(items) - completed, 0),
        "is_target_complete": completed >= quota or (len(items) > 0 and completed >= len(items)),
        "categories": categories,
        "performance": {
            "attempted": len(day_activities),
            "connected": connected,
            "interested": interested,
            "appointments": appointments,
            "callbacks_due": due_callbacks,
            "connection_rate": round(connected / max(len(day_activities), 1) * 100, 1),
        },
        "items": items,
    }


@router.get("/workbench/quota")
async def get_daily_call_quota(
    sales_employee_id: Optional[int] = None,
    target_date: Optional[date] = None,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_lead_role(current_user)
    target_date = target_date or datetime.now(BUSINESS_TIMEZONE).date()
    salesperson = await _resolve_workbench_salesperson(db, current_user, sales_employee_id)
    return {"sales_employee_id": salesperson.id, "target_date": target_date, "target_count": await _daily_quota(db, salesperson.id, target_date)}


@router.put("/workbench/quota")
async def update_daily_call_quota(
    payload: SalesDailyQuotaUpdate,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_lead_role(current_user)
    if _role(current_user) not in ADMIN_ROLES | {"sales_manager"}:
        raise HTTPException(status_code=403, detail="只有主管或管理员可以调整每日任务数量")
    target_date = payload.target_date or datetime.now(BUSINESS_TIMEZONE).date()
    salesperson = await _resolve_workbench_salesperson(db, current_user, payload.sales_employee_id)
    quota = (await db.execute(
        select(SalesDailyQuotas).where(
            SalesDailyQuotas.sales_employee_id == salesperson.id,
            SalesDailyQuotas.target_date == target_date,
        )
    )).scalar_one_or_none()
    if quota is None:
        quota = SalesDailyQuotas(sales_employee_id=salesperson.id, target_date=target_date)
        db.add(quota)
    quota.target_count = payload.target_count
    quota.updated_by_id = _employee_id(current_user)
    quota.updated_by_name = current_user.name
    await db.commit()
    return {"sales_employee_id": salesperson.id, "target_date": target_date, "target_count": quota.target_count}


@router.get("/workbench/tasks/{task_id}/analysis")
async def get_daily_task_analysis(
    task_id: int,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_lead_role(current_user)
    task, lead = (await db.execute(
        select(SalesDailyDialTasks, SalesLeads)
        .join(SalesLeads, SalesLeads.id == SalesDailyDialTasks.lead_id)
        .where(SalesDailyDialTasks.id == task_id)
    )).one_or_none() or (None, None)
    if not task or not lead:
        raise HTTPException(status_code=404, detail="每日任务不存在")
    await _resolve_workbench_salesperson(db, current_user, task.sales_employee_id)
    if not lead.analysis_snapshot:
        return {"available": False, "message": "信息不足：该线索尚未附带经主管确认的商家分析资料。"}
    try:
        return {"available": True, "analysis": json.loads(lead.analysis_snapshot)}
    except json.JSONDecodeError:
        return {"available": False, "message": "商家分析资料格式异常，请由主管重新生成后转入线索库。"}


@router.get("/recovery/overview")
async def get_lead_recovery_overview(
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_lead_role(current_user)
    if _role(current_user) == "sales":
        raise HTTPException(status_code=403, detail="销售只能查看自己的回收提醒")
    items = await _load_recovery_snapshot(db, current_user)
    return {
        "items": items,
        "summary": {
            "recoverable": sum(item["state"] == "recoverable" for item in items),
            "watch": sum(item["state"] == "watch" for item in items),
            "protected": sum(item["state"] == "protected" for item in items),
            "extended": sum(item["state"] == "extended" for item in items),
            "extension_requests": sum(item["extension_request"] is not None for item in items),
        },
    }


@router.get("/recovery/my-alerts")
async def get_my_recovery_alerts(
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_lead_role(current_user)
    if _role(current_user) != "sales":
        raise HTTPException(status_code=403, detail="该提醒仅面向电话销售账号")
    items = await _load_recovery_snapshot(db, current_user)
    return {"items": [item for item in items if item["state"] in {"watch", "recoverable"}]}


@router.post("/recovery/batch")
async def batch_update_lead_recovery(
    payload: RecoveryBatchRequest,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_lead_role(current_user)
    if _role(current_user) not in ADMIN_ROLES | {"sales_manager"}:
        raise HTTPException(status_code=403, detail="只有销售主管或系统管理员可以批量处理线索归属")
    lead_ids = list(dict.fromkeys(payload.lead_ids))
    leads = [await _get_scoped_lead(db, lead_id, current_user) for lead_id in lead_ids]
    snapshot = {item["lead_id"]: item for item in await _load_recovery_snapshot(db, current_user)}
    target = None
    if payload.action == "reassign":
        if not payload.assigned_sales_id:
            raise HTTPException(status_code=400, detail="批量重新分配必须选择目标销售")
        target = (await db.execute(select(Employees).where(
            Employees.id == payload.assigned_sales_id,
            Employees.role == "sales",
            Employees.status.in_(["active", "probation"]),
        ))).scalar_one_or_none()
        if not target:
            raise HTTPException(status_code=400, detail="只能重新分配给在职电话销售")
        if _role(current_user) == "sales_manager" and target.supervisor != (current_user.name or ""):
            raise HTTPException(status_code=403, detail="只能重新分配给直属销售")

    invalid = []
    for lead in leads:
        item = snapshot.get(lead.id)
        state = item["state"] if item else "unassigned"
        if payload.action == "reclaim" and state != "recoverable":
            invalid.append(f"{lead.business_name}（{state}）")
        if payload.action == "reassign" and state == "protected" and not payload.confirm_protected_transfer:
            invalid.append(f"{lead.business_name}（受保护）")
    if invalid:
        raise HTTPException(status_code=400, detail=f"以下线索不符合本次批量操作：{'、'.join(invalid[:8])}")

    for lead in leads:
        old_id, old_name = lead.assigned_sales_id, lead.assigned_sales_name
        if payload.action == "reclaim":
            lead.assigned_sales_id = None
            lead.assigned_sales_name = None
            await _append_assignment_log(
                db, lead, "reclaimed", current_user,
                from_employee_id=old_id, from_employee_name=old_name, reason=payload.reason.strip(),
            )
        else:
            lead.assigned_sales_id = target.id
            lead.assigned_sales_name = target.name
            if _role(current_user) == "sales_manager":
                lead.team_manager_id = _employee_id(current_user)
            await _append_assignment_log(
                db, lead, "reassigned", current_user,
                from_employee_id=old_id, from_employee_name=old_name,
                to_employee_id=target.id, to_employee_name=target.name, reason=payload.reason.strip(),
            )
    await db.commit()
    verb = "回收至待分配" if payload.action == "reclaim" else f"重新分配给 {target.name}"
    return {"message": f"已将 {len(leads)} 条线索{verb}", "updated": len(leads)}


@router.post("/{lead_id}/recovery/request-extension")
async def request_lead_recovery_extension(
    lead_id: int,
    payload: RecoveryExtensionRequest,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_lead_role(current_user)
    if _role(current_user) != "sales":
        raise HTTPException(status_code=403, detail="只有当前销售可以申请延期")
    lead = await _get_scoped_lead(db, lead_id, current_user)
    if lead.assigned_sales_id != _employee_id(current_user):
        raise HTTPException(status_code=403, detail="只能为本人负责的线索申请延期")
    snapshot = {item["lead_id"]: item for item in await _load_recovery_snapshot(db, current_user)}.get(lead.id)
    if not snapshot or snapshot["state"] not in {"watch", "recoverable"}:
        raise HTTPException(status_code=400, detail="该线索当前不需要申请回收延期")
    requested_until = datetime.now(timezone.utc) + timedelta(days=payload.requested_days)
    await _append_assignment_log(
        db, lead, "extension_requested", current_user,
        from_employee_id=lead.assigned_sales_id, from_employee_name=lead.assigned_sales_name,
        to_employee_id=lead.assigned_sales_id, to_employee_name=lead.assigned_sales_name,
        reason=payload.reason.strip(), effective_until=requested_until,
    )
    await db.commit()
    return {"message": "延期申请已提交，主管确认前线索不会被自动转交", "requested_until": requested_until}


@router.post("/{lead_id}/recovery/approve-extension")
async def approve_lead_recovery_extension(
    lead_id: int,
    payload: RecoveryReasonRequest,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_lead_role(current_user)
    if _role(current_user) not in ADMIN_ROLES | {"sales_manager"}:
        raise HTTPException(status_code=403, detail="只有销售主管或系统管理员可以批准延期")
    lead = await _get_scoped_lead(db, lead_id, current_user)
    request = (await db.execute(
        select(SalesLeadAssignmentLogs)
        .where(
            SalesLeadAssignmentLogs.lead_id == lead.id,
            SalesLeadAssignmentLogs.action == "extension_requested",
        )
        .order_by(SalesLeadAssignmentLogs.created_at.desc(), SalesLeadAssignmentLogs.id.desc())
    )).scalars().first()
    if not request or not request.effective_until:
        raise HTTPException(status_code=400, detail="未找到待批准的延期申请")
    await _append_assignment_log(
        db, lead, "extension_approved", current_user,
        from_employee_id=lead.assigned_sales_id, from_employee_name=lead.assigned_sales_name,
        to_employee_id=lead.assigned_sales_id, to_employee_name=lead.assigned_sales_name,
        reason=payload.reason.strip(), effective_until=request.effective_until,
    )
    await db.commit()
    return {"message": "已批准延期，保护期内不会进入回收名单", "effective_until": request.effective_until}


@router.post("/{lead_id}/recovery/reclaim")
async def reclaim_sales_lead(
    lead_id: int,
    payload: RecoveryReasonRequest,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_lead_role(current_user)
    if _role(current_user) not in ADMIN_ROLES | {"sales_manager"}:
        raise HTTPException(status_code=403, detail="只有销售主管或系统管理员可以回收线索")
    lead = await _get_scoped_lead(db, lead_id, current_user)
    snapshot = {item["lead_id"]: item for item in await _load_recovery_snapshot(db, current_user)}.get(lead.id)
    if not snapshot or snapshot["state"] != "recoverable":
        raise HTTPException(status_code=400, detail="该线索当前不符合自动回收条件；有意向或已预约线索请使用转交并填写原因")
    old_id, old_name = lead.assigned_sales_id, lead.assigned_sales_name
    lead.assigned_sales_id = None
    lead.assigned_sales_name = None
    await _append_assignment_log(
        db, lead, "reclaimed", current_user,
        from_employee_id=old_id, from_employee_name=old_name,
        reason=payload.reason.strip(),
    )
    await db.commit()
    return {"message": "线索已回收至主管待分配队列", "lead_id": lead.id}


@router.post("/{lead_id}/recovery/reassign")
async def reassign_sales_lead(
    lead_id: int,
    payload: RecoveryReassignRequest,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_lead_role(current_user)
    if _role(current_user) not in ADMIN_ROLES | {"sales_manager"}:
        raise HTTPException(status_code=403, detail="只有销售主管或系统管理员可以转交线索")
    lead = await _get_scoped_lead(db, lead_id, current_user)
    snapshot = {item["lead_id"]: item for item in await _load_recovery_snapshot(db, current_user)}.get(lead.id)
    if snapshot and snapshot["state"] == "protected" and not payload.confirm_protected_transfer:
        raise HTTPException(status_code=400, detail="有意向或已预约线索受保护，请确认填写转交原因后再执行")
    target = (await db.execute(
        select(Employees).where(
            Employees.id == payload.assigned_sales_id,
            Employees.role == "sales",
            Employees.status.in_(["active", "probation"]),
        )
    )).scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=400, detail="只能转交给在职电话销售")
    if _role(current_user) == "sales_manager" and target.supervisor != (current_user.name or ""):
        raise HTTPException(status_code=403, detail="只能转交给直属销售")
    old_id, old_name = lead.assigned_sales_id, lead.assigned_sales_name
    lead.assigned_sales_id = target.id
    lead.assigned_sales_name = target.name
    if _role(current_user) == "sales_manager":
        lead.team_manager_id = _employee_id(current_user)
    await _append_assignment_log(
        db, lead, "reassigned", current_user,
        from_employee_id=old_id, from_employee_name=old_name,
        to_employee_id=target.id, to_employee_name=target.name,
        reason=payload.reason.strip(),
    )
    await db.commit()
    return {"message": "线索已转交，原负责人及原因已保留在操作日志中", "lead_id": lead.id, "assigned_sales_name": target.name}


@router.get("/{lead_id}/call-history")
async def get_sales_call_history(
    lead_id: int,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_lead_role(current_user)
    await _get_scoped_lead(db, lead_id, current_user)
    rows = (await db.execute(
        select(SalesCallActivities)
        .where(SalesCallActivities.lead_id == lead_id)
        .order_by(SalesCallActivities.called_at.desc(), SalesCallActivities.id.desc())
    )).scalars().all()
    return [{
        "id": row.id, "outcome": row.outcome, "outcome_label": CALL_OUTCOMES.get(row.outcome, row.outcome),
        "notes": row.notes, "next_follow_up_at": row.next_follow_up_at, "called_at": row.called_at,
        "sales_employee_id": row.sales_employee_id, "sales_employee_name": row.sales_employee_name,
    } for row in rows]


async def _get_scoped_activity(db: AsyncSession, activity_id: int, user: UserResponse) -> SalesCallActivities:
    activity = (await db.execute(select(SalesCallActivities).where(SalesCallActivities.id == activity_id))).scalar_one_or_none()
    if not activity:
        raise HTTPException(status_code=404, detail="通话记录不存在")
    await _get_scoped_lead(db, activity.lead_id, user)
    return activity


@router.post("/call-activities/{activity_id}/ai-analysis")
async def generate_call_ai_analysis(
    activity_id: int,
    payload: SalesCallAiGenerateRequest,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a reviewable post-call analysis from an ASR transcript or a verified manual transcript."""
    _ensure_lead_role(current_user)
    activity = await _get_scoped_activity(db, activity_id, current_user)
    lead = await _get_scoped_lead(db, activity.lead_id, current_user)
    transcript = payload.transcript.strip()
    analysis = _call_ai_fallback(transcript, activity.notes)
    provider = None
    model = None
    try:
        runtime = await resolve_ai_runtime_config(db)
        if runtime.enabled:
            prompt = f"""
你是电话销售质检助手。只能根据给出的通话转写和销售备注填写 JSON，禁止猜测。
返回字段：call_summary、real_needs、rejection_reason、interest_level（高/中/低/未知）、next_contact_time（ISO 时间或 null）、next_conversation_advice、recommended_material、needs_manager_intervention（布尔）、source_notice。
商家：{lead.business_name}。销售备注：{activity.notes or '无'}。
通话转写：{transcript}
"""
            result = await AIHubService(api_key=runtime.api_key, base_url=runtime.base_url).gentxt(GenTxtRequest(
                model=runtime.model,
                temperature=0.1,
                max_tokens=1200,
                messages=[ChatMessage(role="user", content=prompt)],
            ))
            proposed = _extract_ai_json(result.content)
            if proposed:
                analysis.update({key: value for key, value in proposed.items() if key in analysis})
                analysis["source_notice"] = "由 AI 根据本次通话转写生成，必须由销售人工复核后使用。"
                provider, model = runtime.provider, result.model
    except Exception as exc:
        analysis["source_notice"] = f"AI 调用未完成，已保存可编辑保守模板：{humanize_ai_error(exc)}"

    row = SalesCallAiAnalyses(
        call_activity_id=activity.id,
        lead_id=lead.id,
        transcript=transcript,
        transcript_source=payload.transcript_source,
        original_analysis_json=json.dumps(analysis, ensure_ascii=False),
        needs_manager_intervention=bool(analysis.get("needs_manager_intervention")),
        ai_provider=provider,
        ai_model=model,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "analysis": analysis, "editable": True, "used_ai": bool(provider)}


@router.get("/call-activities/{activity_id}/ai-analysis")
async def get_call_ai_analysis(
    activity_id: int,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_lead_role(current_user)
    await _get_scoped_activity(db, activity_id, current_user)
    row = (await db.execute(
        select(SalesCallAiAnalyses)
        .where(SalesCallAiAnalyses.call_activity_id == activity_id)
        .order_by(SalesCallAiAnalyses.id.desc())
    )).scalars().first()
    if not row:
        return {"available": False, "message": "尚未收到录音转写或手动转写，暂不能生成通话后分析。"}
    return {
        "available": True,
        "id": row.id,
        "analysis": _parse_json_dict(row.reviewed_analysis_json) or _parse_json_dict(row.original_analysis_json),
        "original_analysis": _parse_json_dict(row.original_analysis_json),
        "transcript_source": row.transcript_source,
        "reviewed_at": row.reviewed_at,
        "needs_manager_intervention": row.needs_manager_intervention,
    }


@router.put("/call-ai-analyses/{analysis_id}")
async def review_call_ai_analysis(
    analysis_id: int,
    payload: SalesCallAiReviewRequest,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_lead_role(current_user)
    row = (await db.execute(select(SalesCallAiAnalyses).where(SalesCallAiAnalyses.id == analysis_id))).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="通话 AI 分析不存在")
    await _get_scoped_lead(db, row.lead_id, current_user)
    row.reviewed_analysis_json = json.dumps(payload.analysis, ensure_ascii=False)
    row.needs_manager_intervention = payload.needs_manager_intervention
    row.reviewed_by_id = _employee_id(current_user)
    row.reviewed_by_name = current_user.name
    row.reviewed_at = datetime.now(timezone.utc)
    await db.commit()
    return {"message": "AI 分析修订已保存，原始 AI 结果和本次修订均已保留", "id": row.id}


def _normalize_identity(value: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def _business_date(value: Optional[datetime]) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    # SQLite strips timezone metadata from timezone-aware UTC columns. Restore UTC
    # before converting to the business timezone so activity counts do not reset
    # incorrectly during the eight hours after China midnight.
    normalized = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return normalized.astimezone(BUSINESS_TIMEZONE).date()


async def _find_customer_duplicates(db: AsyncSession, lead: SalesLeads) -> list[dict]:
    customers = (await db.execute(select(Customers))).scalars().all()
    matches = []
    phone = _normalize_identity(lead.phone)
    website = _normalize_identity(lead.website)
    business = _normalize_identity(lead.business_name)
    address = _normalize_identity(lead.address)
    for customer in customers:
        reasons = []
        if phone and phone == _normalize_identity(customer.phone): reasons.append("电话相同")
        if website and website == _normalize_identity(customer.website): reasons.append("官网相同")
        if business and address and business == _normalize_identity(customer.business_name) and address == _normalize_identity(customer.address): reasons.append("商家名称和地址相同")
        if reasons:
            matches.append({"customer_id": customer.id, "customer_code": customer.customer_code, "business_name": customer.business_name, "reasons": reasons})
    return matches


@router.post("/{lead_id}/convert-to-customer")
async def convert_sales_lead_to_customer(
    lead_id: int,
    payload: SalesLeadConvertRequest,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_lead_role(current_user)
    if _role(current_user) not in ADMIN_ROLES | {"sales_manager"}:
        raise HTTPException(status_code=403, detail="只有销售主管或系统管理员可以确认合作并转为正式客户")
    lead = await _get_scoped_lead(db, lead_id, current_user)
    if lead.converted_customer_id:
        raise HTTPException(status_code=409, detail=f"该线索已转为正式客户 #{lead.converted_customer_id}")
    if not lead.contact_name:
        raise HTTPException(status_code=400, detail="转入前请补全联系人姓名")
    quotes = (await db.execute(
        select(SalesQuoteRequests).where(SalesQuoteRequests.lead_id == lead.id).order_by(SalesQuoteRequests.created_at.desc())
    )).scalars().all()
    approved_quote = next((quote for quote in quotes if quote.status == "approved"), None)
    handoff = (await db.execute(
        select(SalesHandoffChecklists).where(SalesHandoffChecklists.lead_id == lead.id)
    )).scalar_one_or_none()
    blockers = []
    if not approved_quote:
        blockers.append("需要一张已审批的报价单")
    if not handoff:
        blockers.append("尚未填写成交交接清单")
    elif approved_quote:
        if handoff.quote_id != approved_quote.id: blockers.append("交接清单需要关联当前已审批报价")
        if not (handoff.customer_goal or "").strip(): blockers.append("请填写客户目标")
        if not (handoff.key_contacts or "").strip(): blockers.append("请填写关键联系人或对接方式")
        if not handoff.operations_owner_employee_id and not (handoff.operations_owner or "").strip(): blockers.append("请选择运营对接负责人")
        if not handoff.operations_group_created: blockers.append("请确认已建立运营对接群")
        payment_status = handoff.payment_status or ("paid" if handoff.finance_payment_confirmed else "pending")
        if payment_status != "paid": blockers.append("等待财务确认全额收款")
        service_start = handoff.service_start_date or approved_quote.service_start_date
        service_end = handoff.service_end_date or approved_quote.service_end_date
        if approved_quote.billing_cycle != "one_time" and (not service_start or not service_end):
            blockers.append("周期性服务必须填写服务开始和结束日期")
    if blockers:
        raise HTTPException(status_code=400, detail={"message": "成交审核尚未完成", "blockers": blockers})
    duplicates = await _find_customer_duplicates(db, lead)
    if duplicates:
        raise HTTPException(status_code=409, detail={"message": "发现可能重复的正式客户，请确认后不要重复转入", "duplicates": duplicates})

    day_code = datetime.now(BUSINESS_TIMEZONE).strftime("%Y%m%d")
    count = (await db.execute(select(func.count(Customers.id)).where(Customers.customer_code.like(f"C{day_code}-%")))).scalar_one()
    customer_code = f"C{day_code}-{int(count) + 1:04d}"
    customer = Customers(
        customer_code=customer_code,
        sales_lead_id=lead.id,
        business_name=lead.business_name,
        contact_name=lead.contact_name,
        phone=lead.phone,
        address=lead.address,
        city=lead.city,
        state=lead.state,
        country=lead.country,
        industry=lead.industry,
        website=lead.website,
        source=lead.source,
        sales_person=lead.assigned_sales_name,
        sales_employee_id=lead.assigned_sales_id,
        status="已合作",
        notes=f"由电话销售线索 #{lead.id} 转入。确认说明：{payload.confirmation_notes}",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(customer)
    await db.flush()
    db.add(Customer_contacts(customer_id=customer.id, contact_name=lead.contact_name, contact_phone=lead.phone, contact_role="销售线索联系人", notes="由电话销售中心转入"))
    service_start = _parse_optional_datetime(handoff.service_start_date or approved_quote.service_start_date)
    service_end = _parse_optional_datetime(handoff.service_end_date or approved_quote.service_end_date)
    payment_date = _parse_optional_datetime(handoff.payment_date) or handoff.payment_confirmed_at or datetime.now(timezone.utc)
    product_type = _quote_product_type(approved_quote.package_name, approved_quote.selected_platforms)
    billing_cycle = approved_quote.billing_cycle or ("monthly" if approved_quote.billing_mode == "subscription" else "one_time")
    if approved_quote.business_line_id:
        business_line = await db.get(BusinessLine, approved_quote.business_line_id)
        if business_line:
            product_type = business_line.code
    collaborator_ids = []
    try:
        collaborator_ids = [int(item) for item in json.loads(handoff.collaborator_employee_ids or "[]")]
    except (TypeError, ValueError):
        collaborator_ids = []
    engagement = None
    if approved_quote.business_line_id and approved_quote.product_id:
        engagement = CustomerEngagement(
            customer_id=customer.id,
            business_line_id=approved_quote.business_line_id,
            product_id=approved_quote.product_id,
            product_plan_id=approved_quote.product_plan_id,
            engagement_code=f"ENG-{datetime.now(timezone.utc):%Y%m%d}-{uuid4().hex[:8].upper()}",
            package_name=approved_quote.package_name,
            status="active_paid",
            owner_employee_id=handoff.operations_owner_employee_id,
            sales_employee_id=lead.assigned_sales_id,
            billing_cycle=billing_cycle,
            collection_method=(
                "stripe_auto" if approved_quote.billing_mode == "subscription"
                else approved_quote.payment_method if approved_quote.payment_method in {"check", "zelle", "bank_transfer"}
                else "other"
            ),
            currency=approved_quote.currency or "USD",
            selected_platforms=approved_quote.selected_platforms,
            service_scope_json=json.dumps({"collaborator_employee_ids": collaborator_ids}, ensure_ascii=False),
            paid_started_at=payment_date,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(engagement)
        await db.flush()
    deal = Deals(
        engagement_id=engagement.id if engagement else None,
        business_line_id=approved_quote.business_line_id,
        product_id=approved_quote.product_id,
        product_plan_id=approved_quote.product_plan_id,
        customer_id=customer.id, customer_name=customer.business_name,
        sales_employee_id=lead.assigned_sales_id, sales_name=lead.assigned_sales_name,
        product_type=product_type, package_name=approved_quote.package_name,
        package_platforms=approved_quote.selected_platforms, billing_cycle=billing_cycle,
        deal_amount=float(approved_quote.final_amount or 0), is_paid=True,
        service_start_date=service_start, service_end_date=service_end,
        needs_group=not handoff.operations_group_created, is_handed_over=True, is_transferred_ops=True,
        notes=f"由电话销售成交审核自动生成；报价单 #{approved_quote.id}。{handoff.special_commitments or ''}".strip(),
        deal_date=payment_date, created_at=datetime.now(timezone.utc),
    )
    db.add(deal)
    await db.flush()
    payment = await sync_payment_from_deal(
        db, deal, commit=False,
        amount_paid_override=float(handoff.amount_received or approved_quote.final_amount or 0),
        payment_method_override=approved_quote.payment_method,
        payment_mode_override="subscription_auto" if approved_quote.billing_mode == "subscription" else "manual_collection",
        currency_override=approved_quote.currency or "USD",
        transaction_reference_override=handoff.payment_reference,
        payment_date_override=payment_date,
    )
    payment.engagement_id = engagement.id if engagement else None
    payment.business_line_id = approved_quote.business_line_id
    payment.product_id = approved_quote.product_id
    payment.billing_cycle = billing_cycle
    payment.coverage_start = service_start
    payment.coverage_end = service_end
    subscription = None
    if billing_cycle != "one_time":
        subscription = Subscriptions(
            customer_id=customer.id, customer_name=customer.business_name, deal_id=deal.id,
            engagement_id=engagement.id if engagement else None,
            business_line_id=approved_quote.business_line_id,
            product_id=approved_quote.product_id,
            product_plan_id=approved_quote.product_plan_id,
            package_name=approved_quote.package_name, package_price=float(approved_quote.final_amount or 0),
            list_price_snapshot=float(approved_quote.list_amount or 0), pricing_source="approved_quote",
            selected_platforms=approved_quote.selected_platforms,
            service_scope_json=json.dumps({"collaborator_employee_ids": collaborator_ids}, ensure_ascii=False),
            billing_cycle=billing_cycle, start_date=service_start, end_date=service_end,
            auto_renew=approved_quote.billing_mode == "subscription",
            renewal_person=lead.assigned_sales_name, last_payment_date=payment_date,
            next_payment_date=service_end, status="active", renewal_result="initial_contract_approved",
            created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        )
        db.add(subscription)
        await db.flush()
    handoff.generated_deal_id = deal.id
    service_progress = None
    generate_service_board = bool(handoff.generate_service_board)
    if generate_service_board:
        service_progress = Service_progresses(
            customer_id=customer.id, customer_name=customer.business_name, service_type=product_type, service_stage="deal_handover",
            progress_percent=10, sales_person=lead.assigned_sales_name, industry=lead.industry, country=lead.country,
            state=lead.state, city=lead.city, last_update_time=datetime.now(BUSINESS_TIMEZONE).strftime("%Y-%m-%d %H:%M"),
            package_name=approved_quote.package_name, package_platforms=approved_quote.selected_platforms,
            service_start_date=service_start.isoformat() if service_start else None, service_end_date=service_end.isoformat() if service_end else None,
            last_update_person=current_user.name, last_work_summary="报价、收款和成交交接已完成，进入运营交接阶段。",
            issue_status="无", user_id=str(current_user.id), created_at=datetime.now(BUSINESS_TIMEZONE).isoformat(),
        )
        db.add(service_progress)
        await db.flush()
    snapshot = {key: getattr(lead, key) for key in ["business_name", "contact_name", "phone", "industry", "country", "state", "city", "address", "website", "source", "assigned_sales_id", "assigned_sales_name", "notes"]}
    snapshot["approved_quote"] = {
        "id": approved_quote.id, "package_name": approved_quote.package_name, "selected_platforms": approved_quote.selected_platforms,
        "currency": approved_quote.currency, "final_amount": approved_quote.final_amount, "payment_method": approved_quote.payment_method,
        "billing_mode": approved_quote.billing_mode, "billing_cycle": billing_cycle,
        "business_line_id": approved_quote.business_line_id, "product_id": approved_quote.product_id,
        "product_plan_id": approved_quote.product_plan_id,
        "service_start_date": approved_quote.service_start_date, "service_end_date": approved_quote.service_end_date,
    }
    snapshot["handoff"] = {
        "customer_goal": handoff.customer_goal, "key_contacts": handoff.key_contacts, "operations_owner": handoff.operations_owner,
        "operations_owner_employee_id": handoff.operations_owner_employee_id,
        "collaborator_employee_ids": collaborator_ids,
        "operations_group_created": handoff.operations_group_created, "finance_payment_confirmed": handoff.finance_payment_confirmed,
        "payment_status": handoff.payment_status, "amount_received": handoff.amount_received,
        "payment_date": handoff.payment_date, "payment_reference": handoff.payment_reference,
        "special_commitments": handoff.special_commitments,
    }
    db.add(SalesLeadConversionLogs(
        lead_id=lead.id, customer_id=customer.id, generated_customer_code=customer_code,
        duplicate_check_json=json.dumps({"checked": True, "matches": []}, ensure_ascii=False),
        lead_snapshot_json=json.dumps(snapshot, ensure_ascii=False, default=str), generate_service_board=generate_service_board,
        service_progress_id=service_progress.id if service_progress else None, converted_by_id=_employee_id(current_user), converted_by_name=current_user.name,
    ))
    lead.converted_customer_id = customer.id
    lead.converted_at = datetime.now(timezone.utc)
    lead.converted_by_id = _employee_id(current_user)
    lead.converted_by_name = current_user.name
    lead.status = "won"
    await db.commit()
    return {
        "message": "已转为正式客户，并自动生成成交、收款和订阅信息。",
        "customer_id": customer.id, "customer_code": customer_code, "deal_id": deal.id,
        "payment_id": payment.id, "engagement_id": engagement.id if engagement else None,
        "subscription_id": subscription.id if subscription else None,
        "service_progress_id": service_progress.id if service_progress else None,
    }


@router.get("/dashboard/management")
async def sales_management_dashboard(
    target_date: Optional[date] = None,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_lead_role(current_user)
    if _role(current_user) == "sales":
        raise HTTPException(status_code=403, detail="销售主管或系统管理员可以查看管理驾驶舱")
    target_date = target_date or datetime.now(BUSINESS_TIMEZONE).date()
    scope = await _scope_condition(db, current_user)
    lead_query = select(SalesLeads)
    if scope is not None: lead_query = lead_query.where(scope)
    leads = (await db.execute(lead_query)).scalars().all()
    lead_ids = [lead.id for lead in leads]
    tasks = [] if not lead_ids else (await db.execute(select(SalesDailyDialTasks).where(SalesDailyDialTasks.task_date == target_date, SalesDailyDialTasks.lead_id.in_(lead_ids)))).scalars().all()
    activities = [] if not lead_ids else (await db.execute(select(SalesCallActivities).where(SalesCallActivities.lead_id.in_(lead_ids)))).scalars().all()
    today_activities = [item for item in activities if _business_date(item.called_at) == target_date]
    completed = sum(item.status == "completed" for item in tasks)
    connected = sum(item.outcome != "no_answer" for item in today_activities)
    interested = sum(item.outcome in {"interested", "appointment"} for item in today_activities)
    appointments = sum(item.outcome == "appointment" for item in today_activities)
    # Conversion logs are the audit source of truth. Some legacy SQLite rows do not
    # preserve timezone metadata on the lead row, so counting logs avoids under-reporting.
    conversion_logs = [] if not lead_ids else (await db.execute(
        select(SalesLeadConversionLogs).where(SalesLeadConversionLogs.lead_id.in_(lead_ids))
    )).scalars().all()
    converted = len(conversion_logs)
    quotes = [] if not lead_ids else (await db.execute(
        select(SalesQuoteRequests).where(SalesQuoteRequests.lead_id.in_(lead_ids))
    )).scalars().all()
    handoffs = [] if not lead_ids else (await db.execute(
        select(SalesHandoffChecklists).where(SalesHandoffChecklists.lead_id.in_(lead_ids))
    )).scalars().all()
    stale_before = target_date - timedelta(days=1)
    active_follow_up_statuses = {"follow_up", "interested", "appointment"}
    high_intent_stale = sum(
        lead.status in {"interested", "appointment"}
        and (lead.last_contact_at is None or (_business_date(lead.last_contact_at) or target_date) <= stale_before)
        for lead in leads
    )
    overdue_followups = sum(
        lead.status in active_follow_up_statuses
        and lead.next_follow_up_at is not None
        and (_business_date(lead.next_follow_up_at) or target_date) < target_date
        for lead in leads
    )
    due_followups = sum(
        lead.status in active_follow_up_statuses
        and _business_date(lead.next_follow_up_at) == target_date
        for lead in leads
    )
    pending_quotes = [quote for quote in quotes if quote.status == "submitted"]
    approved_quotes = [quote for quote in quotes if quote.status == "approved"]
    unpaid_handoffs = [
        handoff for handoff in handoffs
        if handoff.generated_deal_id is None and (handoff.payment_status or "pending") != "paid"
    ]
    confirmed_received_amount = round(sum(
        float(handoff.amount_received or 0)
        for handoff in handoffs
        if (handoff.payment_status or "pending") in {"deposit_paid", "paid"}
    ), 2)
    denominator = max(len(today_activities), 1)
    people = {}
    for item in today_activities:
        name = item.sales_employee_name or "未命名销售"
        stat = people.setdefault(name, {"salesperson": name, "calls": 0, "connected": 0, "interested": 0, "appointments": 0})
        stat["calls"] += 1; stat["connected"] += int(item.outcome != "no_answer"); stat["interested"] += int(item.outcome in {"interested", "appointment"}); stat["appointments"] += int(item.outcome == "appointment")
    sources = {}
    for lead in leads:
        label = lead.source or "未标注来源"
        entry = sources.setdefault(label, {"source": label, "total": 0, "usable": 0})
        entry["total"] += 1
        entry["usable"] += int(bool(lead.phone and lead.business_name and (lead.city or lead.address)))
    return {"target_date": target_date, "metrics": {
        "assigned": len(tasks), "completed": completed, "completion_rate": round(completed / max(len(tasks), 1) * 100, 1),
        "calls": len(today_activities), "connected": connected, "connection_rate": round(connected / denominator * 100, 1),
        "interested": interested, "interest_rate": round(interested / denominator * 100, 1),
        "appointments": appointments, "appointment_rate": round(appointments / denominator * 100, 1),
        "converted": converted, "conversion_rate": round(converted / max(len(leads), 1) * 100, 1),
    }, "owner_attention": {
        "high_intent_stale": high_intent_stale,
        "due_followups": due_followups,
        "overdue_followups": overdue_followups,
        "pending_quotes": len(pending_quotes),
        "unpaid_handoffs": len(unpaid_handoffs),
    }, "deal_pipeline": {
        "pending_quotes": len(pending_quotes),
        "approved_quotes": len(approved_quotes),
        "approved_quote_amount": round(sum(float(quote.final_amount or 0) for quote in approved_quotes), 2),
        "confirmed_received_amount": confirmed_received_amount,
        "unpaid_handoffs": len(unpaid_handoffs),
    }, "source_quality": [{**item, "quality_rate": round(item["usable"] / max(item["total"], 1) * 100, 1)} for item in sources.values()], "salespeople": list(people.values())}


def _performance_suggestions(metrics: dict) -> list[str]:
    suggestions: list[str] = []
    if metrics["assigned"] and metrics["completion_rate"] < 80:
        suggestions.append("优先完成已分配任务，减少当天遗留任务。")
    if metrics["calls"] >= 10 and metrics["connection_rate"] < 20:
        suggestions.append("接通率偏低，可调整拨打时段并优先复核号码质量。")
    if metrics["connected"] >= 8 and metrics["interest_rate"] < 10:
        suggestions.append("已有效接通但意向偏低，建议复盘开场话术和切入问题。")
    if metrics["interested"] >= 2 and metrics["appointments"] == 0:
        suggestions.append("已有意向商家，下一步应明确预约时间或报价确认动作。")
    if metrics["overdue_followups"]:
        suggestions.append("存在逾期回访，请先处理约定时间已过的商家。")
    if metrics["calls"] >= 5 and metrics["note_quality_rate"] < 70:
        suggestions.append("通话备注完整度不足，请记录需求、异议和明确的下一步。")
    if not suggestions:
        suggestions.append("执行与跟进节奏稳定，可继续保持并关注高意向线索推进。")
    return suggestions[:3]


@router.get("/dashboard/performance")
async def sales_performance_dashboard(
    days: int = Query(default=30, ge=1, le=90),
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Explainable pre-sales performance score; never reads formal customer finance data."""
    _ensure_lead_role(current_user)
    today = datetime.now(BUSINESS_TIMEZONE).date()
    start_date = today - timedelta(days=days - 1)
    role = _role(current_user)
    if role == "sales":
        salesperson_ids = [_employee_id(current_user)]
    elif role == "sales_manager":
        salesperson_ids = await _direct_report_ids(db, current_user)
    else:
        salesperson_ids = [int(value) for value in (await db.execute(
            select(Employees.id).where(
                Employees.role == "sales",
                Employees.status.in_(["active", "probation"]),
            )
        )).scalars().all()]

    if not salesperson_ids:
        return {"period": {"days": days, "start_date": start_date, "end_date": today}, "items": []}

    employees = (await db.execute(select(Employees).where(Employees.id.in_(salesperson_ids)))).scalars().all()
    names = {employee.id: employee.name for employee in employees}
    tasks = (await db.execute(
        select(SalesDailyDialTasks).where(
            SalesDailyDialTasks.sales_employee_id.in_(salesperson_ids),
            SalesDailyDialTasks.task_date >= start_date,
            SalesDailyDialTasks.task_date <= today,
        )
    )).scalars().all()
    activities = (await db.execute(
        select(SalesCallActivities).where(SalesCallActivities.sales_employee_id.in_(salesperson_ids))
    )).scalars().all()
    activities = [item for item in activities if start_date <= (_business_date(item.called_at) or today) <= today]

    lead_rows = (await db.execute(
        select(SalesLeads).where(SalesLeads.assigned_sales_id.in_(salesperson_ids))
    )).scalars().all()
    overdue_by_sales = {sales_id: 0 for sales_id in salesperson_ids}
    for lead in lead_rows:
        follow_up_day = _business_date(lead.next_follow_up_at)
        if lead.status == "follow_up" and follow_up_day and follow_up_day < today:
            overdue_by_sales[lead.assigned_sales_id] = overdue_by_sales.get(lead.assigned_sales_id, 0) + 1

    conversion_logs = (await db.execute(select(SalesLeadConversionLogs))).scalars().all()
    conversions_by_sales = {sales_id: 0 for sales_id in salesperson_ids}
    for log in conversion_logs:
        log_day = _business_date(log.created_at)
        if not log_day or not start_date <= log_day <= today:
            continue
        snapshot = _parse_json_dict(log.lead_snapshot_json)
        sales_id = snapshot.get("assigned_sales_id")
        if sales_id in conversions_by_sales:
            conversions_by_sales[sales_id] += 1

    items = []
    for sales_id in salesperson_ids:
        employee_tasks = [item for item in tasks if item.sales_employee_id == sales_id]
        employee_activities = [item for item in activities if item.sales_employee_id == sales_id]
        assigned = len(employee_tasks)
        completed = sum(item.status == "completed" for item in employee_tasks)
        calls = len(employee_activities)
        connected = sum(item.outcome != "no_answer" for item in employee_activities)
        interested = sum(item.outcome in {"interested", "appointment"} for item in employee_activities)
        appointments = sum(item.outcome == "appointment" for item in employee_activities)
        documented = sum(bool((item.notes or "").strip()) and len((item.notes or "").strip()) >= 12 for item in employee_activities)
        compliant = sum(
            item.outcome == "no_answer"
            or (item.outcome in {"callback", "interested", "appointment"} and bool(item.next_follow_up_at) and bool((item.notes or "").strip()))
            or (item.outcome in {"not_interested", "do_not_contact"} and bool((item.notes or "").strip()))
            for item in employee_activities
        )
        completion_rate = round(completed / max(assigned, 1) * 100, 1)
        connection_rate = round(connected / max(calls, 1) * 100, 1)
        interest_rate = round(interested / max(connected, 1) * 100, 1)
        note_quality_rate = round(documented / max(calls, 1) * 100, 1)
        overdue_followups = overdue_by_sales.get(sales_id, 0)
        conversions = conversions_by_sales.get(sales_id, 0)

        execution_score = min(25, completion_rate * 0.25)
        discipline_score = max(0, 20 - min(20, overdue_followups * 5))
        opportunity_score = min(8, connection_rate * 0.08) + min(8, interest_rate * 0.08) + min(4, appointments * 2)
        result_score = min(10, appointments * 5) + min(15, conversions * 15)
        compliance_rate = round(compliant / max(calls, 1) * 100, 1)
        documentation_score = min(7, note_quality_rate * 0.07) + min(3, compliance_rate * 0.03)
        total_score = round(execution_score + discipline_score + opportunity_score + result_score + documentation_score, 1)
        confidence = "数据不足" if calls < 10 else ("参考可靠" if calls >= 30 else "可参考")
        metrics = {
            "assigned": assigned, "completed": completed, "calls": calls, "connected": connected,
            "interested": interested, "appointments": appointments, "conversions": conversions,
            "completion_rate": completion_rate, "connection_rate": connection_rate,
            "interest_rate": interest_rate, "note_quality_rate": note_quality_rate,
            "overdue_followups": overdue_followups, "compliance_rate": compliance_rate,
        }
        items.append({
            "sales_employee_id": sales_id,
            "salesperson": names.get(sales_id, "未命名销售"),
            "score": total_score,
            "confidence": confidence,
            "score_breakdown": {
                "execution": round(execution_score, 1), "discipline": round(discipline_score, 1),
                "opportunity": round(opportunity_score, 1), "results": round(result_score, 1),
                "documentation": round(documentation_score, 1),
            },
            "metrics": metrics,
            "suggestions": _performance_suggestions(metrics),
        })
    items.sort(key=lambda item: (-item["score"], -item["metrics"]["conversions"], -item["metrics"]["appointments"], item["salesperson"]))
    for index, item in enumerate(items, start=1):
        item["rank"] = index
    return {"period": {"days": days, "start_date": start_date, "end_date": today}, "items": items}


@router.post("/workbench/tasks/{task_id}/result")
async def record_daily_call_result(
    task_id: int,
    payload: SalesCallResultCreate,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_lead_role(current_user)
    _validate_manual_call_result(payload)
    task = (await db.execute(select(SalesDailyDialTasks).where(SalesDailyDialTasks.id == task_id))).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="每日任务不存在")
    await _resolve_workbench_salesperson(db, current_user, task.sales_employee_id)
    if task.status == "completed":
        raise HTTPException(status_code=400, detail="该任务今日已完成；如需补充请在历史记录中由主管处理")
    lead = await _get_scoped_lead(db, task.lead_id, current_user)
    if lead.is_blacklisted or lead.do_not_contact:
        raise HTTPException(status_code=400, detail="该商家已被保护，禁止拨打")

    now = datetime.now(timezone.utc)
    suggested_follow_up_at, next_action_label = _suggest_follow_up(payload.outcome, now)
    next_follow_up_at = payload.next_follow_up_at or suggested_follow_up_at
    activity = SalesCallActivities(
        lead_id=lead.id,
        sales_employee_id=task.sales_employee_id,
        sales_employee_name=(await db.execute(select(Employees.name).where(Employees.id == task.sales_employee_id))).scalar_one_or_none(),
        outcome=payload.outcome,
        notes=payload.notes,
        next_follow_up_at=next_follow_up_at,
        called_at=now,
    )
    db.add(activity)
    await db.flush()
    lead.status = _lead_status_from_outcome(payload.outcome)
    lead.last_contact_at = now
    lead.next_follow_up_at = next_follow_up_at
    if payload.notes:
        lead.notes = payload.notes
    if payload.outcome == "do_not_contact":
        lead.do_not_contact = True
        lead.do_not_contact_reason = payload.notes or "商家在通话中明确要求不再联系"
    task.status = "completed"
    task.completed_activity_id = activity.id
    task.completed_at = now
    await db.commit()
    return {
        "message": "通话结果已记录",
        "task_id": task.id,
        "lead_id": lead.id,
        "status": lead.status,
        "next_follow_up_at": next_follow_up_at,
        "next_action_label": next_action_label,
        "used_suggested_follow_up": payload.next_follow_up_at is None and suggested_follow_up_at is not None,
    }


@router.post("/{lead_id}/follow-up")
async def record_supplemental_follow_up(
    lead_id: int,
    payload: SalesCallResultCreate,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record another valid call without reopening or inflating a completed daily task."""
    _ensure_lead_role(current_user)
    _validate_manual_call_result(payload)
    lead = await _get_scoped_lead(db, lead_id, current_user)
    if _role(current_user) == "sales" and lead.assigned_sales_id != _employee_id(current_user):
        raise HTTPException(status_code=403, detail="只能追加本人负责线索的跟进")
    if lead.is_blacklisted or lead.do_not_contact:
        raise HTTPException(status_code=400, detail="该商家已被保护，禁止继续联系")
    if lead.status not in {"contacted", "follow_up", "interested", "appointment"}:
        raise HTTPException(status_code=400, detail="请先通过每日任务完成首次联系，再追加跟进")

    now = datetime.now(timezone.utc)
    suggested_follow_up_at, next_action_label = _suggest_follow_up(payload.outcome, now)
    next_follow_up_at = payload.next_follow_up_at or suggested_follow_up_at
    db.add(SalesCallActivities(
        lead_id=lead.id,
        sales_employee_id=_employee_id(current_user),
        sales_employee_name=current_user.name,
        outcome=payload.outcome,
        notes=payload.notes,
        next_follow_up_at=next_follow_up_at,
        called_at=now,
    ))
    lead.status = _lead_status_from_outcome(payload.outcome)
    lead.last_contact_at = now
    lead.next_follow_up_at = next_follow_up_at
    if payload.notes:
        lead.notes = payload.notes
    if payload.outcome == "do_not_contact":
        lead.do_not_contact = True
        lead.do_not_contact_reason = payload.notes or "商家在追加跟进中明确要求不再联系"
    await db.commit()
    return {
        "message": "追加跟进已记录并加入时间线，不会覆盖历史记录，也不会重复增加今日任务完成数",
        "lead_id": lead.id,
        "status": lead.status,
        "next_follow_up_at": next_follow_up_at,
        "next_action_label": next_action_label,
        "used_suggested_follow_up": payload.next_follow_up_at is None and suggested_follow_up_at is not None,
    }


@router.post("/workbench/tasks/{task_id}/dial-started")
async def record_ringcentral_dial_started(
    task_id: int,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record the local RingCentral deep-link action before API syncing is configured."""
    _ensure_lead_role(current_user)
    task = (await db.execute(select(SalesDailyDialTasks).where(SalesDailyDialTasks.id == task_id))).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="每日任务不存在")
    await _resolve_workbench_salesperson(db, current_user, task.sales_employee_id)
    if task.status == "completed":
        raise HTTPException(status_code=400, detail="该任务今日已完成")
    lead = await _get_scoped_lead(db, task.lead_id, current_user)
    if lead.is_blacklisted or lead.do_not_contact:
        raise HTTPException(status_code=400, detail="该商家已被保护，禁止拨打")
    task.dial_started_at = datetime.now(timezone.utc)
    await db.commit()
    return {"task_id": task.id, "dial_started_at": task.dial_started_at, "phone": lead.phone}


@router.get("/{lead_id}", response_model=SalesLeadResponse)
async def get_sales_lead(
    lead_id: int,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_lead_role(current_user)
    return await _get_scoped_lead(db, lead_id, current_user)


@router.post("", response_model=SalesLeadResponse, status_code=status.HTTP_201_CREATED)
async def create_sales_lead(
    payload: SalesLeadCreate,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_lead_role(current_user)
    if _role(current_user) not in ADMIN_ROLES | {"sales_manager"}:
        raise HTTPException(status_code=403, detail="销售人员不能创建或导入线索")

    comparable_phone = re.sub(r"[^0-9+]", "", payload.phone)
    existing = await db.execute(select(SalesLeads.id, SalesLeads.phone))
    for existing_id, existing_phone in existing.all():
        if re.sub(r"[^0-9+]", "", existing_phone or "") == comparable_phone:
            raise HTTPException(status_code=409, detail=f"该电话号码已存在于线索库（编号 {existing_id}）")

    assigned_id, assigned_name, manager_id = await _resolve_assignee(
        db, payload.assigned_sales_id, current_user
    )
    current_id = _employee_id(current_user)
    lead = SalesLeads(
        **payload.model_dump(exclude={"assigned_sales_id"}),
        assigned_sales_id=assigned_id,
        assigned_sales_name=assigned_name,
        team_manager_id=manager_id,
        created_by_id=current_id,
        created_by_name=current_user.name,
    )
    db.add(lead)
    await db.commit()
    await db.refresh(lead)
    return lead


@router.put("/{lead_id}", response_model=SalesLeadResponse)
async def update_sales_lead(
    lead_id: int,
    payload: SalesLeadUpdate,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_lead_role(current_user)
    lead = await _get_scoped_lead(db, lead_id, current_user)
    role = _role(current_user)
    updates = payload.model_dump(exclude_unset=True)

    if role == "sales":
        forbidden = set(updates) - SALES_EDITABLE_FIELDS
        if forbidden:
            raise HTTPException(status_code=403, detail="销售只能更新跟进状态、备注和禁止联系标记")
    elif "assigned_sales_id" in updates:
        assigned_id, assigned_name, manager_id = await _resolve_assignee(
            db, updates.pop("assigned_sales_id"), current_user
        )
        updates["assigned_sales_id"] = assigned_id
        updates["assigned_sales_name"] = assigned_name
        if role == "sales_manager":
            updates["team_manager_id"] = manager_id

    if updates.get("is_blacklisted") or updates.get("do_not_contact"):
        updates["status"] = "blocked"

    for key, value in updates.items():
        if hasattr(lead, key):
            setattr(lead, key, value)
    lead.updated_at = datetime.now().astimezone()
    await db.commit()
    await db.refresh(lead)
    return lead


@router.delete("/{lead_id}")
async def delete_sales_lead(
    lead_id: int,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_lead_role(current_user)
    if _role(current_user) not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="仅管理员可以删除线索")
    lead = await _get_scoped_lead(db, lead_id, current_user)
    await db.delete(lead)
    await db.commit()
    return {"message": "线索已删除", "id": lead_id}
