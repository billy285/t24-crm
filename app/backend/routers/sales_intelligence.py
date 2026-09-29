import json
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from calendar import monthrange
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db
from dependencies.auth import get_current_user
from schemas.auth import UserResponse
from schemas.sales_intelligence import (
    ConfigPublish,
    OperatingConfig,
    ProfileUpdate,
    TargetCreate,
    CoachingCreate,
    CoachingComplete,
    SavedViewCreate,
)
from models.sales_intelligence import (
    SalesOperatingSettings,
    SalesLeadProfiles,
    SalesContactDetails,
    SalesInsightEvents,
    SalesMonthlyTargets,
    SalesCoachingTasks,
    SalesSavedViews,
)
from models.sales_leads import SalesLeads
from models.sales_call_activities import SalesCallActivities
from models.ringcentral_call_records import RingCentralCallRecords
from models.sales_lead_assignment_logs import SalesLeadAssignmentLogs
from models.sales_lead_conversion_logs import SalesLeadConversionLogs
from models.sales_deal_controls import SalesQuoteRequests, SalesHandoffChecklists
from models.employees import Employees
from models.merchant_pool import MerchantPool
from routers.sales_leads import (
    _ensure_lead_role,
    _scope_condition,
    _get_scoped_lead,
    _direct_report_ids,
    _employee_id,
    _role,
    ADMIN_ROLES,
)
from services.sales_intelligence import (
    default_config,
    summarize_lead,
    unpack,
    stamp,
    iso,
    canonical_calls,
    TZ,
    POTENTIAL_LABELS,
)

router = APIRouter(prefix="/api/v1/sales-intelligence", tags=["sales-intelligence"])


def pack(value):
    return json.dumps(value, ensure_ascii=False, default=str)


def month_now():
    return datetime.now(TZ).strftime("%Y-%m")


def manager(user):
    _ensure_lead_role(user)
    if _role(user) not in ADMIN_ROLES | {"sales_manager"}:
        raise HTTPException(403, "仅主管和管理员可操作")


def valid_month(value):
    try:
        parsed = date.fromisoformat(value + "-01")
        if parsed.strftime("%Y-%m") != value:
            raise ValueError()
        return parsed
    except (ValueError, TypeError):
        raise HTTPException(422, "月份格式应为 YYYY-MM")


async def settings_for(db, month=None):
    month = month or month_now()
    valid_month(month)
    row = (
        await db.scalars(
            select(SalesOperatingSettings)
            .where(SalesOperatingSettings.effective_month <= month)
            .order_by(SalesOperatingSettings.effective_month.desc())
            .limit(1)
        )
    ).first()
    return (
        (unpack(row.payload_json)["config"], row.id) if row else (default_config(), 0)
    )


async def staff_ids(db, user):
    _ensure_lead_role(user)
    if _role(user) == "sales":
        return [_employee_id(user)]
    if _role(user) == "sales_manager":
        return await _direct_report_ids(db, user)
    return list(
        (await db.scalars(select(Employees.id).where(Employees.role == "sales"))).all()
    )


async def check_staff(db, user, employee_id):
    manager(user)
    if employee_id not in await staff_ids(db, user):
        raise HTTPException(403, "员工不在可管理范围内")
    employee = await db.get(Employees, employee_id)
    if not employee or employee.status not in {"active", "probation"}:
        raise HTTPException(422, "请选择在职销售")
    return employee


async def load_bundle(db, user, lead_id=None):
    _ensure_lead_role(user)
    scope = await _scope_condition(db, user)
    query = select(SalesLeads)
    if scope is not None:
        query = query.where(scope)
    if lead_id is not None:
        query = query.where(SalesLeads.id == lead_id)
    leads = list((await db.scalars(query)).all())
    if lead_id is not None and not leads:
        raise HTTPException(404, "线索不存在或不在权限范围内")
    ids_query = query.with_only_columns(SalesLeads.id)
    result = {"leads": leads}
    for key, model in [
        ("activities", SalesCallActivities),
        ("calls", RingCentralCallRecords),
        ("details", SalesContactDetails),
        ("profiles", SalesLeadProfiles),
        ("events", SalesInsightEvents),
    ]:
        result[key] = list(
            (await db.scalars(select(model).where(model.lead_id.in_(ids_query)))).all()
        )
    return result


async def summaries(db, user, lead_id=None):
    config, version = await settings_for(db)
    b = await load_bundle(db, user, lead_id)
    groups = {}
    for key in ("activities", "calls", "details", "events"):
        groups[key] = defaultdict(list)
        for item in b[key]:
            groups[key][item.lead_id].append(item)
    profiles = {p.lead_id: p for p in b["profiles"]}
    return (
        [
            summarize_lead(
                l,
                groups["activities"][l.id],
                groups["calls"][l.id],
                {d.activity_id: d for d in groups["details"][l.id]},
                profiles.get(l.id),
                groups["events"][l.id],
                config,
            )
            for l in b["leads"]
        ],
        config,
        version,
    )


@router.get("/settings")
async def get_settings(
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_lead_role(current_user)
    config, version = await settings_for(db)
    history = (
        await db.scalars(
            select(SalesOperatingSettings).order_by(
                SalesOperatingSettings.effective_month.desc()
            )
        )
    ).all()
    return {
        "config": config,
        "version": version,
        "defaults": default_config(),
        "can_publish": _role(current_user) in ADMIN_ROLES,
        "history": [
            {
                "id": r.id,
                "effective_month": r.effective_month,
                "by": r.created_by_name,
                "created_at": iso(r.created_at),
                **unpack(r.payload_json),
            }
            for r in history
        ],
    }


@router.post("/settings/preview")
async def preview_settings(
    payload: OperatingConfig,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    manager(current_user)
    b = await load_bundle(db, current_user)
    old, _ = await settings_for(db)
    new = payload.model_dump()
    # Evaluate the same authoritative evidence twice; never persist a preview.
    groups = {
        key: defaultdict(list) for key in ("activities", "calls", "details", "events")
    }
    for key, group in groups.items():
        for row in b[key]:
            group[row.lead_id].append(row)
    profiles = {p.lead_id: p for p in b["profiles"]}
    changes = []
    for l in b["leads"]:
        args = (
            l,
            groups["activities"][l.id],
            groups["calls"][l.id],
            {d.activity_id: d for d in groups["details"][l.id]},
            profiles.get(l.id),
            groups["events"][l.id],
        )
        a = summarize_lead(*args, old)
        z = summarize_lead(*args, new)
        if a["potential"] != z["potential"] or a["rationale"] != z["rationale"]:
            changes.append(
                {
                    "id": l.id,
                    "name": l.business_name,
                    "before": a["potential_label"],
                    "after": z["potential_label"],
                    "reason": z["rationale"],
                }
            )
    return {
        "total": len(b["leads"]),
        "changed": len(changes),
        "items": changes[:100],
        "weights_before": old["weights"],
        "weights_after": new["weights"],
    }


@router.post("/settings", status_code=201)
async def publish_settings(
    payload: ConfigPublish,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if _role(current_user) not in ADMIN_ROLES:
        raise HTTPException(403, "仅管理员可发布全局销售规则")
    valid_month(payload.effective_month)
    if payload.effective_month < month_now():
        raise HTTPException(422, "不能追溯修改已结束月份的规则")
    row = SalesOperatingSettings(
        effective_month=payload.effective_month,
        payload_json=pack(
            {"config": payload.config.model_dump(), "reason": payload.reason}
        ),
        created_by_id=_employee_id(current_user),
        created_by_name=current_user.name,
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            409, "该月份已有规则版本，请选择下一个月份，历史版本保持不变"
        )
    return {"id": row.id, "message": "规则已发布，按生效月份启用"}


@router.get("/leads")
async def list_insights(
    search: str = "",
    potential: str = "",
    source: str = "",
    industry: str = "",
    owner: int | None = None,
    min_calls: int = Query(0, ge=0),
    signal: str = "",
    stage: str = "",
    sort: str = "attention",
    skip: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
    lead_ids: list[int] | None = Query(None, max_length=100),
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    items, _, version = await summaries(db, current_user)
    facets = {
        "owners": [
            {"value": str(key), "label": name}
            for key, name in sorted(
                {(i["owner_id"], i["owner"]) for i in items if i["owner_id"]}
            )
        ],
        "sources": sorted({i["source"] for i in items}),
        "industries": sorted({i["industry"] for i in items}),
        "stages": sorted(
            {i["profile"].get("stage_label", "未建立商机") for i in items}
        ),
    }
    if lead_ids is not None:
        requested_ids = set(lead_ids)
        items = [i for i in items if i["id"] in requested_ids]
    if search:
        items = [
            i
            for i in items
            if search.lower() in (i["business_name"] + " " + i["phone"]).lower()
        ]
    if potential:
        items = [i for i in items if i["potential"] == potential]
    if source:
        items = [i for i in items if i["source"] == source]
    if industry:
        items = [i for i in items if i["industry"] == industry]
    if owner is not None:
        items = [i for i in items if i["owner_id"] == owner]
    items = [i for i in items if i["calls"] >= min_calls]
    if stage:
        items = [
            i
            for i in items
            if i["profile"].get("stage_key") == stage
            or i["profile"].get("stage_label", "未建立商机") == stage
        ]
    if signal == "all_rejected":
        items = [i for i in items if i["all_connected_rejected"]]
    elif signal == "unreached":
        items = [i for i in items if i["calls"] and not i["connected"]]
    elif signal in {"connected", "manual_records", "pending_calls"}:
        items = [i for i in items if i[signal]]
    elif signal in {"turned_positive", "overdue", "no_next_step"}:
        items = [i for i in items if i[signal]]
    elif signal:
        raise HTTPException(422, "未知的联系信号")
    if sort == "calls":
        items.sort(key=lambda i: (-i["calls"], i["id"]))
    elif sort == "recent":
        items.sort(key=lambda i: (i["last_contact_at"] or "", i["id"]), reverse=True)
    else:
        items.sort(
            key=lambda i: (
                not i["overdue"],
                not i["no_next_step"],
                i["potential"] != "priority",
                i["id"],
            )
        )
    return {
        "total": len(items),
        "items": [
            {k: v for k, v in i.items() if k not in {"timeline", "contributors"}}
            for i in items[skip : skip + limit]
        ],
        "rules_version": version,
        "facets": facets,
    }


@router.get("/overview")
async def overview(
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    manager(current_user)
    items, config, version = await summaries(db, current_user)
    groups = []
    for field in ("source", "industry"):
        grouped = defaultdict(list)
        for i in items:
            grouped[i[field]].append(i)
        for key, rows in grouped.items():
            interested = sum(bool(i["first_interest_at"]) for i in rows)
            groups.append(
                {
                    "dimension": field,
                    "label": key,
                    "leads": len(rows),
                    "calls": sum(i["calls"] for i in rows),
                    "interested": interested,
                    "converted": sum(bool(i["converted_customer_id"]) for i in rows),
                    "interest_rate": round(interested / len(rows) * 100, 1),
                }
            )
    alerts = []
    for i in items:
        if i["potential"] in {"blocked", "won"}:
            continue
        reason = (
            "跟进已逾期"
            if i["overdue"]
            else "有意向但没有下次跟进" if i["no_next_step"] else ""
        )
        p = i["profile"]
        stage_stamp = p.get("stage_entered_at")
        if (
            not reason
            and stage_stamp
            and (datetime.now(timezone.utc) - stamp(stage_stamp)).days
            >= p.get("stale_days", 7)
            and p.get("milestone") not in {"lost", "nurture", "won", "handoff"}
        ):
            reason = "商机停留时间较长，需确认下一步"
        if reason:
            alerts.append(
                {
                    "id": i["id"],
                    "name": i["business_name"],
                    "owner": i["owner"],
                    "reason": reason,
                    "next_step": p.get("next_step"),
                }
            )
    return {
        "total": len(items),
        "counts": dict(Counter(i["potential"] for i in items)),
        "calls": sum(i["calls"] for i in items),
        "connected": sum(i["connected"] for i in items),
        "manual_records": sum(i["manual_records"] for i in items),
        "pending_calls": sum(i["pending_calls"] for i in items),
        "rules_version": version,
        "groups": groups,
        "alerts": alerts,
        "stages": dict(
            Counter(i["profile"].get("stage_label", "未建立商机") for i in items)
        ),
        "sources": sorted({i["source"] for i in items}),
        "industries": sorted({i["industry"] for i in items}),
        "coverage_notice": "累计统计基于系统内已保留记录；未同步的历史通话无法补推。来源和行业按当前归类汇总，非同龄线索转化实验。",
    }


@router.get("/leads/{lead_id}")
async def get_profile(
    lead_id: int,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    items, config, version = await summaries(db, current_user, lead_id)
    item = items[0]
    assignments = (
        await db.scalars(
            select(SalesLeadAssignmentLogs)
            .where(SalesLeadAssignmentLogs.lead_id == lead_id)
            .order_by(SalesLeadAssignmentLogs.created_at.desc())
        )
    ).all()
    item["assignments"] = [
        {
            "id": x.id,
            "from": x.from_sales_employee_name,
            "to": x.to_sales_employee_name,
            "reason": x.reason,
            "at": iso(x.created_at),
        }
        for x in assignments
    ]
    item["config"] = config
    item["rules_version"] = version
    item["can_review"] = _role(current_user) in ADMIN_ROLES | {"sales_manager"}
    if item["merchant_pool_id"]:
        merchant = await db.get(MerchantPool, item["merchant_pool_id"])
        item["origin"] = (
            {"id": merchant.id, "created_at": iso(merchant.created_at)}
            if merchant
            else None
        )
    return item


@router.put("/leads/{lead_id}")
async def update_profile(
    lead_id: int,
    payload: ProfileUpdate,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_lead_role(current_user)
    lead = await _get_scoped_lead(db, lead_id, current_user)
    old = await db.get(SalesLeadProfiles, lead_id)
    before = unpack(old.payload_json) if old else {}
    if (old.revision if old else 0) != payload.revision:
        raise HTTPException(409, "档案已被更新，请刷新后再保存")
    if _role(current_user) == "sales" and (
        payload.potential_override != before.get("potential_override", "")
        or payload.override_reason != before.get("override_reason", "")
    ):
        raise HTTPException(403, "潜力复核由主管或管理员完成")
    if payload.potential_override and len(payload.override_reason.strip()) < 3:
        raise HTTPException(422, "请填写潜力复核依据")
    config, version = await settings_for(db)
    pipeline = next(
        (x for x in config["pipelines"] if x["key"] == payload.pipeline_key), None
    )
    stage = (
        next((x for x in pipeline["stages"] if x["key"] == payload.stage_key), None)
        if pipeline
        else None
    )
    if not stage:
        raise HTTPException(422, "请选择当前生效流程和阶段")
    milestone = stage["milestone"]
    if lead.do_not_contact or lead.is_blacklisted:
        if milestone not in {"lost", "nurture"}:
            raise HTTPException(422, "禁止联系的商家只能记录失单或暂缓说明")
    if (
        milestone in {"qualified", "scheduled", "demo", "quoted", "decision"}
        and not payload.need_summary.strip()
    ):
        raise HTTPException(422, "请先记录客户真实需求")
    if (
        milestone in {"scheduled", "demo", "decision"}
        and not payload.decision_maker.strip()
    ):
        raise HTTPException(422, "请记录参与人或决策人")
    if milestone in {
        "qualified",
        "scheduled",
        "demo",
        "quoted",
        "decision",
        "nurture",
    } and (not payload.next_step.strip() or not payload.next_step_date):
        raise HTTPException(422, "请填写下一步和约定日期")
    if milestone in {"quoted", "decision", "won", "handoff"}:
        quote = (
            await db.scalars(
                select(SalesQuoteRequests).where(
                    SalesQuoteRequests.lead_id == lead_id,
                    SalesQuoteRequests.status == "approved",
                )
            )
        ).first()
        if not quote:
            raise HTTPException(422, "请先在成交审核中完成报价审批")
    if milestone in {"won", "handoff"}:
        handoff = (
            await db.scalars(
                select(SalesHandoffChecklists).where(
                    SalesHandoffChecklists.lead_id == lead_id
                )
            )
        ).first()
        if (
            not handoff
            or not handoff.finance_payment_confirmed
            or handoff.payment_status != "paid"
        ):
            raise HTTPException(422, "成交必须沿用既有审核中的全额收款确认")
        if milestone == "handoff" and (
            not lead.converted_customer_id or not handoff.operations_owner_employee_id
        ):
            raise HTTPException(422, "请先转入正式客户并确认交接负责人")
    valid_fields = {x["key"]: x for x in config["custom_fields"]}
    if set(payload.custom_fields) - set(valid_fields):
        raise HTTPException(422, "包含未配置的自定义字段")
    for key, field in valid_fields.items():
        if (
            milestone in field.get("required_milestones", [])
            and not payload.custom_fields.get(key, "").strip()
        ):
            raise HTTPException(422, f"请填写{field['label']}")
    now = datetime.now(timezone.utc)
    # One follow-up deadline drives both the operating overview and the existing workbench.
    if payload.next_step_date:
        lead.next_follow_up_at = datetime.combine(
            payload.next_step_date, datetime.max.time().replace(microsecond=0), TZ
        ).astimezone(timezone.utc)
    data = payload.model_dump(exclude={"revision"})
    data.update(
        {
            "milestone": milestone,
            "stage_label": stage["label"],
            "stale_days": stage["stale_days"],
            "rules_version": version,
            "stage_entered_at": (
                before.get("stage_entered_at")
                if before.get("stage_key") == payload.stage_key
                and before.get("pipeline_key") == payload.pipeline_key
                else iso(now)
            ),
        }
    )
    if old:
        changed = await db.execute(
            update(SalesLeadProfiles)
            .where(
                SalesLeadProfiles.lead_id == lead_id,
                SalesLeadProfiles.revision == payload.revision,
            )
            .values(
                payload_json=pack(data), revision=payload.revision + 1, updated_at=now
            )
        )
        if changed.rowcount != 1:
            raise HTTPException(409, "档案已更新，请刷新")
    else:
        db.add(
            SalesLeadProfiles(
                lead_id=lead_id, revision=1, payload_json=pack(data), updated_at=now
            )
        )
    db.add(
        SalesInsightEvents(
            lead_id=lead_id,
            kind="profile",
            actor_id=_employee_id(current_user),
            actor_name=current_user.name,
            owner_id=lead.assigned_sales_id,
            payload_json=pack({"before": before, "after": data}),
            created_at=now,
        )
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "档案已更新，请刷新")
    return {"revision": payload.revision + 1, "message": "商机与复核记录已保存"}


@router.get("/pool/{pool_id}")
async def pool_insight(
    pool_id: int,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    manager(current_user)
    scope = await _scope_condition(db, current_user)
    q = select(SalesLeads.id).where(SalesLeads.merchant_pool_id == pool_id)
    if scope is not None:
        q = q.where(scope)
    ids = list((await db.scalars(q)).all())
    return {
        "lead_ids": ids,
        "message": "尚无可见销售联系记录" if not ids else "已关联累计联系档案",
    }


@router.get("/views")
async def views(
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_lead_role(current_user)
    rows = (
        await db.scalars(
            select(SalesSavedViews)
            .where(SalesSavedViews.employee_id == _employee_id(current_user))
            .order_by(SalesSavedViews.id)
        )
    ).all()
    return [
        {"id": r.id, "name": r.name, "filters": unpack(r.payload_json)} for r in rows
    ]


@router.post("/views", status_code=201)
async def save_view(
    payload: SavedViewCreate,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_lead_role(current_user)
    row = (
        await db.scalars(
            select(SalesSavedViews).where(
                SalesSavedViews.employee_id == _employee_id(current_user),
                SalesSavedViews.name == payload.name,
            )
        )
    ).first()
    if row:
        row.payload_json = pack(payload.filters)
    else:
        if len(await views(current_user, db)) >= 30:
            raise HTTPException(422, "最多保存 30 个常用视图")
        row = SalesSavedViews(
            employee_id=_employee_id(current_user),
            name=payload.name,
            payload_json=pack(payload.filters),
        )
        db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "同名视图刚刚更新，请刷新")
    return {"id": row.id, "message": "已保存个人视图"}


@router.post("/targets", status_code=201)
async def set_target(
    payload: TargetCreate,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    employee = await check_staff(db, current_user, payload.employee_id)
    valid_month(payload.month)
    if payload.month < month_now():
        raise HTTPException(422, "已结束月份的目标不可修改")
    previous = (
        await db.scalars(
            select(SalesMonthlyTargets)
            .where(
                SalesMonthlyTargets.employee_id == payload.employee_id,
                SalesMonthlyTargets.month == payload.month,
            )
            .order_by(SalesMonthlyTargets.revision.desc())
            .limit(1)
        )
    ).first()
    if (previous.revision if previous else 0) != payload.previous_revision:
        raise HTTPException(409, "目标已更新，请刷新后重试")
    manager_id = (
        _employee_id(current_user) if _role(current_user) == "sales_manager" else None
    )
    if manager_id is None and employee.supervisor:
        managers = (
            await db.scalars(
                select(Employees).where(
                    Employees.name == employee.supervisor,
                    Employees.role == "sales_manager",
                )
            )
        ).all()
        if len(managers) == 1:
            manager_id = managers[0].id
    row = SalesMonthlyTargets(
        employee_id=employee.id,
        employee_name=employee.name,
        manager_id=manager_id,
        month=payload.month,
        revision=payload.previous_revision + 1,
        payload_json=pack(payload.model_dump()),
        created_by_id=_employee_id(current_user),
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "目标已更新，请刷新")
    return {"id": row.id, "revision": row.revision, "message": "目标已保存，旧版本保留"}


@router.get("/team")
async def team(
    month: str | None = None,
    evidence_employee: int | None = None,
    metric: str = "calls",
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_lead_role(current_user)
    month = month or month_now()
    start = valid_month(month)
    end = start.replace(day=monthrange(start.year, start.month)[1])
    config, version = await settings_for(db, month)
    ids = await staff_ids(db, current_user)
    # Current reporting scope is authoritative. Historical snapshots never grant access to a former employee.
    targets = (
        await db.scalars(
            select(SalesMonthlyTargets)
            .where(SalesMonthlyTargets.month == month)
            .order_by(SalesMonthlyTargets.revision.desc())
        )
    ).all()
    if _role(current_user) == "sales_manager" and month < month_now():
        ids = [
            i
            for i in ids
            if any(
                t.employee_id == i and t.manager_id == _employee_id(current_user)
                for t in targets
            )
        ]
    targets = [
        t
        for t in targets
        if t.employee_id in ids
        and (
            _role(current_user) != "sales_manager"
            or t.manager_id == _employee_id(current_user)
        )
    ]
    chosen = {}
    for t in targets:
        chosen.setdefault(t.employee_id, t)
    employees = (await db.scalars(select(Employees).where(Employees.id.in_(ids)))).all()
    utc_start = datetime.combine(start, datetime.min.time(), TZ).astimezone(
        timezone.utc
    )
    utc_end = datetime.combine(end, datetime.max.time(), TZ).astimezone(timezone.utc)
    activities = (
        await db.scalars(
            select(SalesCallActivities).where(
                SalesCallActivities.sales_employee_id.in_(ids),
                SalesCallActivities.called_at >= utc_start,
                SalesCallActivities.called_at <= utc_end,
            )
        )
    ).all()
    detail_rows = (
        await db.scalars(
            select(SalesContactDetails).where(
                SalesContactDetails.activity_id.in_([a.id for a in activities])
            )
        )
    ).all()
    details = {d.activity_id: d for d in detail_rows}
    calls = (
        await db.scalars(
            select(RingCentralCallRecords).where(
                RingCentralCallRecords.sales_employee_id.in_(ids),
                RingCentralCallRecords.started_at >= utc_start,
                RingCentralCallRecords.started_at <= utc_end,
            )
        )
    ).all()
    events = (
        await db.scalars(
            select(SalesInsightEvents).where(
                SalesInsightEvents.owner_id.in_(ids),
                SalesInsightEvents.created_at >= utc_start,
                SalesInsightEvents.created_at <= utc_end,
            )
        )
    ).all()
    logs = (
        await db.scalars(
            select(SalesLeadConversionLogs).where(
                SalesLeadConversionLogs.created_at >= utc_start,
                SalesLeadConversionLogs.created_at <= utc_end,
            )
        )
    ).all()
    paid = set(
        (
            await db.scalars(
                select(SalesHandoffChecklists.lead_id).where(
                    SalesHandoffChecklists.finance_payment_confirmed.is_(True),
                    SalesHandoffChecklists.payment_status == "paid",
                )
            )
        ).all()
    )
    if evidence_employee is not None and evidence_employee not in ids:
        raise HTTPException(403, "员工不在可查看范围内")
    if evidence_employee is not None and metric not in {
        "calls",
        "qualified",
        "demos",
        "wins",
        "quality",
    }:
        raise HTTPException(422, "未知的指标")
    rows = []
    for e in employees:
        a = [r for r in activities if r.sales_employee_id == e.id]
        c = canonical_calls([r for r in calls if r.sales_employee_id == e.id])
        own_events = [r for r in events if r.owner_id == e.id]
        qualified = {
            r.lead_id
            for r in a
            if r.id in details
            and details[r.id].reached_person == "decision_maker"
            and (details[r.id].need_summary or "").strip()
        }
        demos = {
            r.lead_id
            for r in own_events
            if unpack(r.payload_json).get("after", {}).get("milestone") == "demo"
            and unpack(r.payload_json).get("before", {}).get("milestone") != "demo"
        }
        wins = {
            r.lead_id
            for r in logs
            if unpack(r.lead_snapshot_json).get("assigned_sales_id") == e.id
            and r.lead_id in paid
        }
        complete = sum(
            r.id in details
            and bool((details[r.id].need_summary or "").strip())
            and bool((details[r.id].next_step or "").strip())
            for r in a
            if r.outcome != "no_answer"
        )
        conversations = sum(r.outcome != "no_answer" for r in a)
        quality = round(complete / conversations * 100, 1) if conversations else None
        target = chosen.get(e.id)
        t = unpack(target.payload_json) if target else None
        weights = dict(config["weights"])
        if t and t["role_template"] == "development":
            weights["pipeline"] += weights["results"]
            weights["results"] = 0
        if t and t["role_template"] == "closer":
            weights["results"] += weights["execution"]
            weights["execution"] = 0
        score = None
        breakdown = {}
        if t and conversations >= 10 and (len(c) > 0 or weights["execution"] == 0):
            progress = {
                "results": min(1, len(wins) / t["wins"]),
                "pipeline": (
                    min(1, len(qualified) / t["qualified"])
                    + min(1, len(demos) / t["demos"])
                )
                / 2,
                "execution": min(1, len(c) / t["calls"]),
                "quality": quality / 100,
            }
            breakdown = {k: round(weights[k] * progress[k], 1) for k in weights}
            score = round(sum(breakdown.values()), 1)
        if evidence_employee == e.id:
            scoped = select(SalesLeads)
            scope = await _scope_condition(db, current_user)
            if scope is not None:
                scoped = scoped.where(scope)
            visible = {
                lead.id: lead.business_name for lead in (await db.scalars(scoped)).all()
            }
            evidence = []

            def item(lead_id, at, detail):
                return {
                    "lead_id": lead_id if lead_id in visible else None,
                    "name": visible.get(lead_id, "未关联商家或已移出当前负责范围"),
                    "at": iso(at),
                    "detail": detail,
                }

            if metric == "calls":
                evidence = [
                    item(
                        r["lead_id"],
                        r["started_at"],
                        f"官方通话 · {'接通' if r['connected'] else '未接通'} · {r['duration_seconds']} 秒",
                    )
                    for r in c
                ]
            elif metric == "qualified":
                for lead_id in qualified:
                    r = next(
                        r
                        for r in a
                        if r.lead_id == lead_id
                        and r.id in details
                        and details[r.id].reached_person == "decision_maker"
                        and (details[r.id].need_summary or "").strip()
                    )
                    evidence.append(
                        item(
                            lead_id,
                            r.called_at,
                            "决策人沟通：" + details[r.id].need_summary,
                        )
                    )
            elif metric == "demos":
                for lead_id in demos:
                    r = next(
                        r
                        for r in own_events
                        if r.lead_id == lead_id
                        and unpack(r.payload_json).get("after", {}).get("milestone")
                        == "demo"
                    )
                    evidence.append(
                        item(
                            lead_id,
                            r.created_at,
                            unpack(r.payload_json)["after"].get("evidence", ""),
                        )
                    )
            elif metric == "wins":
                evidence = [
                    item(r.lead_id, r.created_at, "已转客户且既有全额收款确认有效")
                    for r in logs
                    if r.lead_id in wins
                ]
            else:
                evidence = [
                    item(
                        r.lead_id,
                        r.called_at,
                        (
                            "需求与下一步完整"
                            if r.id in details
                            and (details[r.id].need_summary or "").strip()
                            and (details[r.id].next_step or "").strip()
                            else "需求或下一步尚未补齐"
                        ),
                    )
                    for r in a
                    if r.outcome != "no_answer"
                ]
            # Counts remain attributable to the original seller; transferred lead content stays scoped.
            for record in evidence:
                if record["lead_id"] is None:
                    record["detail"] = "历史工作量保留，商家详情当前不可见"
            return {
                "items": sorted(evidence, key=lambda x: x["at"] or "", reverse=True),
                "month": month,
                "employee": e.name,
                "metric": metric,
            }
        rows.append(
            {
                "employee_id": e.id,
                "name": e.name,
                "calls": len(c),
                "connected": sum(ca["connected"] for ca in c),
                "records": len(a),
                "qualified": len(qualified),
                "demos": len(demos),
                "wins": len(wins),
                "quality": quality,
                "quality_sample": conversations,
                "score": score,
                "breakdown": breakdown,
                "weights": weights,
                "target": t,
                "target_revision": target.revision if target else 0,
            }
        )
    return {
        "month": month,
        "items": rows,
        "rules_version": version,
        "target_history": [
            {
                "id": r.id,
                "employee_id": r.employee_id,
                "revision": r.revision,
                "at": iso(r.created_at),
                "values": unpack(r.payload_json),
            }
            for r in targets
        ],
        "notice": "管理参考，不自动影响工资。真实拨打按已同步通话去重；有效商机按决策人及需求记录去重；演示需记录实际完成；成交须转客户且既有收款确认仍有效。资料不足 10 条非未接通结果或缺少目标时不评分。主管历史月份仅显示当前团队中留有本主管目标快照的员工；老板可查看全部员工。",
    }


@router.get("/coaching")
async def coaching(
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_lead_role(current_user)
    q = select(SalesCoachingTasks).order_by(
        SalesCoachingTasks.due_date, SalesCoachingTasks.id.desc()
    )
    if _role(current_user) == "sales":
        q = q.where(SalesCoachingTasks.employee_id == _employee_id(current_user))
    elif _role(current_user) == "sales_manager":
        q = q.where(SalesCoachingTasks.manager_id == _employee_id(current_user))
    rows = (await db.scalars(q)).all()
    names = dict((await db.execute(select(Employees.id, Employees.name))).all())
    return [
        {
            "id": r.id,
            "employee_id": r.employee_id,
            "employee": names.get(r.employee_id),
            "lead_id": r.lead_id,
            "action": r.action,
            "due_date": r.due_date,
            "status": r.status,
            "revision": r.revision,
            "completion_note": r.completion_note,
        }
        for r in rows
    ]


@router.post("/coaching", status_code=201)
async def create_coaching(
    payload: CoachingCreate,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await check_staff(db, current_user, payload.employee_id)
    if payload.lead_id:
        await _get_scoped_lead(db, payload.lead_id, current_user)
    if payload.due_date < datetime.now(TZ).date():
        raise HTTPException(422, "复查日期不能早于今天")
    row = SalesCoachingTasks(
        **payload.model_dump(), manager_id=_employee_id(current_user)
    )
    db.add(row)
    await db.commit()
    return {"id": row.id, "message": "辅导行动已创建"}


@router.put("/coaching/{task_id}")
async def complete_coaching(
    task_id: int,
    payload: CoachingComplete,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_lead_role(current_user)
    row = await db.get(SalesCoachingTasks, task_id)
    if not row or (
        _role(current_user) not in ADMIN_ROLES
        and (
            _employee_id(current_user)
            != (row.employee_id if _role(current_user) == "sales" else row.manager_id)
        )
    ):
        raise HTTPException(404, "辅导行动不存在")
    changed = await db.execute(
        update(SalesCoachingTasks)
        .where(
            SalesCoachingTasks.id == task_id,
            SalesCoachingTasks.revision == payload.revision,
            SalesCoachingTasks.status == "open",
        )
        .values(
            status="done",
            revision=payload.revision + 1,
            completion_note=payload.completion_note,
            completed_at=datetime.now(timezone.utc),
        )
    )
    if changed.rowcount != 1:
        raise HTTPException(409, "行动已更新，请刷新")
    await db.commit()
    return {"message": "复查结果已保存"}
