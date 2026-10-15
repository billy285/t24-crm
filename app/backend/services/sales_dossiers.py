"""Dedicated prospect dossiers. Invitations never change legacy lead scope.

All mutations run inside the existing sales workflow transaction. This module
does not commit, schedule calls, change ownership or touch customer ledgers.
"""
from copy import deepcopy
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select, union_all, update

from dependencies.auth import normalize_system_role
from models.employees import Employees
from models.customers import Customers
from models.merchant_pool import MerchantPool
from models.ringcentral_call_records import RingCentralCallRecords
from models.sales_call_activities import SalesCallActivities
from models.sales_call_ai_analyses import SalesCallAiAnalyses
from models.sales_contact_protection import SalesContactProtectionAudit, SalesPhoneSuppression
from models.sales_deal_controls import SalesHandoffChecklists, SalesQuoteRequests
from models.sales_dossiers import (
    SalesDossierGrant, SalesDossierGrantAudit, SalesDossierHandoff,
    SalesDossierSummary, SalesDossierSummaryAudit,
)
from models.sales_intelligence import SalesCoachingTasks, SalesContactDetails, SalesInsightEvents, SalesLeadProfiles
from models.sales_lead_assignment_logs import SalesLeadAssignmentLogs
from models.sales_lead_conversion_logs import SalesLeadConversionLogs
from models.sales_daily_dial_tasks import SalesDailyDialTasks
from models.sales_lead_enrichments import SalesDialAttempt, SalesLeadEnrichment, SalesLeadEnrichmentAudit
from models.sales_leads import SalesLeads
from services.sales_contact_protection import contact_protection_summary, lead_is_blocked
from services.sales_enrichment import enrichment_catalog, enrichment_read_only_reason, get_enrichment
from services.sales_intelligence import iso, summarize_lead, unpack

ACTIVE = {"active", "probation"}
LEAD_ROLES = {"sales", "sales_manager", "admin", "super_admin"}
ADDITIVE_FIELDS = ("latest_conclusion", "objections", "promises")
DERIVED_FIELDS = ("need_summary", "decision_maker", "next_step", "next_action_at")
PROFILE_FIELDS = {"pipeline_key", "stage_key", "milestone", "evidence", "next_step", "next_step_date",
                  "need_summary", "decision_maker", "timezone", "custom_fields", "potential_override", "override_reason"}
ORIGINAL_FIELDS = ("id", "business_name", "phone", "contact_name", "industry", "country", "state", "city",
                   "address", "website", "data_source", "collected_at", "business_status")
HISTORY_MODELS = (SalesDossierSummary, SalesDossierSummaryAudit, SalesDossierGrant, SalesDossierGrantAudit,
    SalesDossierHandoff, SalesLeadEnrichment, SalesLeadEnrichmentAudit, SalesDialAttempt,
    SalesCallActivities, RingCentralCallRecords, SalesContactDetails, SalesLeadProfiles,
    SalesInsightEvents, SalesLeadAssignmentLogs, SalesLeadConversionLogs, SalesDailyDialTasks,
    SalesCallAiAnalyses, SalesQuoteRequests, SalesHandoffChecklists, SalesCoachingTasks)


async def next_sales_lead_id(db):
    """Allocate after the caller acquires lock_sales_workflow, never reuse history IDs.

    Only scalar maximum IDs are read, including orphaned pre-release history.
    This does not expose or modify customer, merchant, suppression or call data.
    """
    columns = [SalesLeads.id, *[model.lead_id for model in HISTORY_MODELS],
               SalesPhoneSuppression.source_lead_id, SalesContactProtectionAudit.lead_id,
               MerchantPool.converted_lead_id, Customers.sales_lead_id]
    maxima = union_all(*[select(func.max(column).label("retained_id")) for column in columns]).subquery()
    highest = (await db.scalar(select(func.max(maxima.c.retained_id)))) or 0
    maximum = (2**31 - 1) if db.get_bind().dialect.name == "postgresql" else (2**63 - 1)
    if highest >= maximum:
        raise HTTPException(409, "商家编号已达到数据库上限，本次未创建，请联系管理员")
    return max(0, int(highest)) + 1


async def active_actor(db, user):
    try:
        actor_id = int(user.id)
    except (ValueError, TypeError):
        raise HTTPException(403, "仅在职销售员工可访问商家档案")
    actor = (await db.scalars(select(Employees).where(Employees.id == actor_id)
                             .execution_options(populate_existing=True))).one_or_none()
    if not actor or actor.status not in ACTIVE or normalize_system_role(actor.role) not in LEAD_ROLES:
        raise HTTPException(403, "仅在职销售员工可访问商家档案")
    # Database role is authoritative even when a test/development JWT is stale.
    if normalize_system_role(user.role) != normalize_system_role(actor.role):
        raise HTTPException(403, "账号权限已变更，请重新登录")
    return actor


async def inherited_access(db, actor, lead):
    role = normalize_system_role(actor.role)
    if role in {"admin", "super_admin"} or lead.assigned_sales_id == actor.id:
        return True
    if role == "sales_manager":
        if lead.team_manager_id == actor.id:
            return True
        return bool((await db.scalars(select(Employees.id).where(
            Employees.id == lead.assigned_sales_id, Employees.role == "sales",
            Employees.status.in_(ACTIVE), Employees.supervisor == actor.name))).first())
    return False


async def authorize_dossier(db, lead_id, user):
    actor = await active_actor(db, user)
    lead = (await db.scalars(select(SalesLeads).where(SalesLeads.id == lead_id)
                            .execution_options(populate_existing=True))).one_or_none()
    if not lead:
        raise HTTPException(404, "商家档案不存在或不在您的权限范围内")
    inherited = await inherited_access(db, actor, lead)
    grant = (await db.scalars(select(SalesDossierGrant).where(
        SalesDossierGrant.lead_id == lead_id, SalesDossierGrant.employee_id == actor.id,
        SalesDossierGrant.status == "active").execution_options(populate_existing=True))).one_or_none()
    # Invitations apply to sales only; a later role change revokes this path immediately.
    if normalize_system_role(actor.role) != "sales":
        grant = None
    if not inherited and grant is None:
        raise HTTPException(404, "商家档案不存在或不在您的权限范围内")
    owner = normalize_system_role(actor.role) == "super_admin"
    editable = bool(inherited or (grant and grant.access == "collaborate"))
    editable = editable and enrichment_read_only_reason(lead) is None
    role_manager = normalize_system_role(actor.role) in {"admin", "super_admin", "sales_manager"}
    return lead, actor, {
        "can_edit": editable, "can_edit_summary": editable,
        "can_invite": owner, "can_transfer": bool(inherited and role_manager),
        "can_ack": False, "can_review": bool(inherited and role_manager),
        "can_edit_profile": bool(inherited), "can_release_protection": owner,
    }


def require_permission(permissions, key):
    if not permissions.get(key):
        raise HTTPException(403, "当前档案权限不允许此操作")


async def ensure_dossier_deletable(db, lead):
    """Keep identity-bearing history attached; SQLite can reuse a deleted lead ID.

    A phone-only suppression ledger deliberately does not prevent deleting a
    never-used lead. It remains durable and independent of the prospect ID.
    """
    if lead.converted_customer_id or lead.converted_at or lead.merchant_pool_id:
        raise HTTPException(409, "此商家已有来源或转化关联，请使用既有状态归档，保留资料及历史记录")
    for model in HISTORY_MODELS:
        if (await db.scalars(select(model.lead_id).where(model.lead_id == lead.id).limit(1))).first() is not None:
            raise HTTPException(409, "此商家已有协作或跟进历史，请使用既有状态归档，保留资料及历史记录")


async def summary_for(db, lead):
    row = (await db.scalars(select(SalesDossierSummary).where(SalesDossierSummary.lead_id == lead.id)
                           .execution_options(populate_existing=True))).one_or_none()
    enrichment = (await db.scalars(select(SalesLeadEnrichment).where(SalesLeadEnrichment.lead_id == lead.id)
                                  .execution_options(populate_existing=True))).one_or_none()
    profile = (await db.scalars(select(SalesLeadProfiles).where(SalesLeadProfiles.lead_id == lead.id)
                               .execution_options(populate_existing=True))).one_or_none()
    profile_data = unpack(profile.payload_json) if profile else {}
    stored = row.payload if row else {}
    return {
        "revision": row.revision if row else 0,
        **{key: str(stored.get(key) or "") for key in ADDITIVE_FIELDS},
        "need_summary": str((enrichment.need_summary if enrichment else profile_data.get("need_summary")) or ""),
        "decision_maker": str(profile_data.get("decision_maker") or ""),
        "next_step": str(profile_data.get("next_step") or ""),
        "next_action_at": iso(lead.next_follow_up_at),
        "updated_by_name": row.updated_by_name if row else None,
        "updated_at": iso(row.updated_at) if row else None,
    }


async def save_summary(db, lead, payload, actor):
    before = await summary_for(db, lead)
    if payload.expected_revision != before["revision"]:
        raise HTTPException(409, "档案摘要已被更新，请刷新后再保存")
    supplied = payload.model_fields_set
    for key in DERIVED_FIELDS:
        if key in supplied:
            value = getattr(payload, key)
            value = iso(value) if key == "next_action_at" else value
            if value != before[key]:
                raise HTTPException(422, "需求、决策人和下一步以当前资料、商机和回访安排为准，请从对应入口修改")
    data = {key: getattr(payload, key) for key in ADDITIVE_FIELDS}
    now = datetime.now(timezone.utc)
    revision = before["revision"] + 1
    if before["revision"]:
        result = await db.execute(update(SalesDossierSummary).where(
            SalesDossierSummary.lead_id == lead.id, SalesDossierSummary.revision == before["revision"])
            .values(revision=revision, payload=data, updated_by_id=actor.id,
                    updated_by_name=actor.name, updated_at=now))
        if result.rowcount != 1:
            raise HTTPException(409, "档案摘要已被更新，请刷新后再保存")
    else:
        db.add(SalesDossierSummary(lead_id=lead.id, revision=revision, payload=data,
            updated_by_id=actor.id, updated_by_name=actor.name, updated_at=now))
    db.add(SalesDossierSummaryAudit(lead_id=lead.id, revision=revision,
        before={key: before[key] for key in ADDITIVE_FIELDS}, after=deepcopy(data),
        actor_id=actor.id, actor_name=actor.name, created_at=now))
    await db.flush()


async def invite_sales(db, lead, actor, payload):
    employee = (await db.scalars(select(Employees).where(Employees.id == payload.employee_id)
                                .execution_options(populate_existing=True))).one_or_none()
    if not employee or employee.role != "sales" or employee.status not in ACTIVE:
        raise HTTPException(422, "请选择在职销售员工")
    if employee.id == lead.assigned_sales_id:
        raise HTTPException(422, "当前主负责人已可访问，无需重复邀请")
    row = (await db.scalars(select(SalesDossierGrant).where(
        SalesDossierGrant.lead_id == lead.id, SalesDossierGrant.employee_id == employee.id)
        .execution_options(populate_existing=True))).one_or_none()
    if payload.expected_revision is not None and payload.expected_revision != (row.revision if row else 0):
        raise HTTPException(409, "邀请权限已更新，请刷新后重试")
    now = datetime.now(timezone.utc)
    if row is None:
        row = SalesDossierGrant(lead_id=lead.id, employee_id=employee.id, revision=0)
        db.add(row)
    row.revision += 1
    row.access, row.status = payload.access, "active"
    row.invited_by_id, row.invited_by_name, row.invited_at = actor.id, actor.name, now
    row.revoked_by_id = row.revoked_by_name = row.revoked_at = None
    db.add(SalesDossierGrantAudit(lead_id=lead.id, employee_id=employee.id,
        revision=row.revision, action="invited", access=row.access,
        actor_id=actor.id, actor_name=actor.name, created_at=now))
    await db.flush()


async def revoke_sales(db, lead, actor, employee_id, expected_revision=None):
    row = (await db.scalars(select(SalesDossierGrant).where(
        SalesDossierGrant.lead_id == lead.id, SalesDossierGrant.employee_id == employee_id)
        .execution_options(populate_existing=True))).one_or_none()
    if row is None:
        raise HTTPException(404, "此销售尚未被邀请")
    if expected_revision is not None and row.revision != expected_revision:
        raise HTTPException(409, "邀请权限已更新，请刷新后重试")
    if row.status == "revoked":
        return
    now = datetime.now(timezone.utc)
    row.status, row.revision = "revoked", row.revision + 1
    row.revoked_by_id, row.revoked_by_name, row.revoked_at = actor.id, actor.name, now
    db.add(SalesDossierGrantAudit(lead_id=lead.id, employee_id=employee_id,
        revision=row.revision, action="revoked", access=row.access,
        actor_id=actor.id, actor_name=actor.name, created_at=now))
    await db.flush()


async def record_handoff(db, lead, user, *, from_sales_id, from_sales_name, note, reason=None):
    """Existing validated reassignment calls this before its same transaction commits."""
    if lead.assigned_sales_id == from_sales_id or not lead.assigned_sales_id:
        return None
    actor = await active_actor(db, user)
    if normalize_system_role(actor.role) not in {"admin", "super_admin", "sales_manager"}:
        raise HTTPException(403, "仅主管和管理员可交接")
    if not await inherited_access(db, actor, lead):
        raise HTTPException(403, "目标主负责人不在可管理范围内")
    target = await db.get(Employees, lead.assigned_sales_id)
    if not target or target.role != "sales" or target.status not in ACTIVE:
        raise HTTPException(422, "交接目标必须是在职销售")
    note = str(note or "").strip()
    if not 3 <= len(note) <= 2000:
        raise HTTPException(422, "请填写 3 至 2000 字的交接说明")
    return await _append_handoff(db, lead, from_sales_id, from_sales_name, target, note, actor.id, actor.name,
                                 str(reason or note).strip()[:2000])


async def record_system_handoff(db, lead, *, from_sales_id, from_sales_name, note):
    """Internal cycle hook only; never exposed as a route or user actor override."""
    if not from_sales_id or not lead.assigned_sales_id or from_sales_id == lead.assigned_sales_id:
        return None
    target = await db.get(Employees, lead.assigned_sales_id)
    if not target or target.role != "sales" or target.status not in ACTIVE:
        raise HTTPException(422, "交接目标必须是在职销售")
    return await _append_handoff(db, lead, from_sales_id, from_sales_name, target,
                                 str(note or "系统按既有规则轮转负责人")[:2000], 0, "系统轮转", str(note or "系统轮转")[:2000])


async def _append_handoff(db, lead, from_sales_id, from_sales_name, target, note, actor_id, actor_name, reason):
    await db.execute(update(SalesDossierHandoff).where(SalesDossierHandoff.lead_id == lead.id,
        SalesDossierHandoff.status == "pending").values(status="superseded"))
    row = SalesDossierHandoff(lead_id=lead.id, from_sales_id=from_sales_id,
        from_sales_name=from_sales_name, to_sales_id=target.id, to_sales_name=target.name,
        note=note, reason=reason, summary=deepcopy(await summary_for(db, lead)), status="pending",
        created_by_id=actor_id, created_by_name=actor_name, created_at=datetime.now(timezone.utc))
    db.add(row)
    await db.flush()
    return row


async def acknowledge_handoff(db, lead, actor, handoff_id, note):
    row = (await db.scalars(select(SalesDossierHandoff).where(
        SalesDossierHandoff.id == handoff_id, SalesDossierHandoff.lead_id == lead.id)
        .execution_options(populate_existing=True))).one_or_none()
    if row is None:
        raise HTTPException(404, "交接记录不存在")
    if actor.id != lead.assigned_sales_id or actor.id != row.to_sales_id:
        raise HTTPException(403, "仅当前接手销售本人可确认交接")
    if row.status != "pending":
        raise HTTPException(409, "此交接已确认或已被新的交接替代")
    row.status = "acknowledged"
    row.acknowledged_by_id, row.acknowledged_by_name = actor.id, actor.name
    row.acknowledged_at, row.ack_note = datetime.now(timezone.utc), note
    await db.flush()


def handoff_data(row):
    return {"id": row.id, "from_sales_id": row.from_sales_id, "from_sales_name": row.from_sales_name,
        "to_sales_id": row.to_sales_id, "to_sales_name": row.to_sales_name,
        "from_employee_id": row.from_sales_id, "to_employee_id": row.to_sales_id,
        "from_name": row.from_sales_name, "to_name": row.to_sales_name,
        "note": row.note, "reason": row.reason, "summary": row.summary, "status": row.status,
        "created_by_name": row.created_by_name, "created_at": iso(row.created_at),
        "acknowledged_by_name": row.acknowledged_by_name,
        "acknowledged_at": iso(row.acknowledged_at), "ack_note": row.ack_note}


async def dossier_data(db, lead, actor, permissions):
    # Only these sales-domain models are queried. No customer or financial joins.
    from routers.sales_intelligence import settings_for
    config, version = await settings_for(db)
    async def rows(model):
        return list((await db.scalars(select(model).where(model.lead_id == lead.id))).all())
    activities = await rows(SalesCallActivities)
    calls = await rows(RingCentralCallRecords)
    details = await rows(SalesContactDetails)
    events = await rows(SalesInsightEvents)
    profile = await db.get(SalesLeadProfiles, lead.id)
    insight = summarize_lead(lead, activities, calls, {row.activity_id: row for row in details}, profile, events, config)
    insight["converted_customer_id"] = None
    insight["profile"] = {key: value for key, value in insight["profile"].items() if key in PROFILE_FIELDS}
    for entry in insight["timeline"]:
        # Event payloads are untyped historical JSON; never return their raw contents.
        if entry["kind"] != "contact":
            entry.pop("details", None)
    logs = await rows(SalesLeadAssignmentLogs)
    insight["assignments"] = [{"id": row.id, "from": row.from_sales_employee_name,
        "to": row.to_sales_employee_name, "reason": row.reason, "at": iso(row.created_at)}
        for row in sorted(logs, key=lambda item: item.id, reverse=True)]
    insight.update(config=config, rules_version=version, can_review=permissions["can_review"])
    original = await db.get(MerchantPool, lead.merchant_pool_id) if lead.merchant_pool_id else None
    original_data = {key: getattr(original, key) for key in ORIGINAL_FIELDS} if original else None
    protection = await contact_protection_summary(db, lead)
    if actor.id != lead.assigned_sales_id:
        protection["can_contact"] = False
        if not protection.get("reason"):
            protection["reason"] = "仅当前主负责人可按计划联系；协作邀请不包含拨打权限"
    if lead.converted_customer_id or lead.converted_at or lead.status == "converted":
        protection.update(can_contact=False, reason="此商家已转为正式客户，请在已授权的客户流程中处理")
    grants = list((await db.scalars(select(SalesDossierGrant).where(SalesDossierGrant.lead_id == lead.id)
                                  .order_by(SalesDossierGrant.id))).all())
    employees = {item.id: item for item in (await db.scalars(select(Employees).where(
        Employees.id.in_([row.employee_id for row in grants])))).all()}
    grant_data = [{"id": row.id, "employee_id": row.employee_id,
        "employee_name": employees[row.employee_id].name if row.employee_id in employees else "已移除员工",
        "access": row.access, "status": row.status, "revision": row.revision,
        "employee_active": bool(row.employee_id in employees and employees[row.employee_id].status in ACTIVE
                                and employees[row.employee_id].role == "sales"),
        "invited_by_name": row.invited_by_name, "invited_at": iso(row.invited_at), "revoked_at": iso(row.revoked_at)}
        for row in grants if permissions["can_invite"] or (row.employee_id == actor.id and row.status == "active")]
    handoffs = sorted(await rows(SalesDossierHandoff), key=lambda row: row.id, reverse=True)
    permissions = {**permissions,
        "can_release_protection": bool(permissions["can_release_protection"]
            and (lead_is_blocked(lead) or protection.get("protected_phones"))),
        "can_ack": any(row.status == "pending" and row.to_sales_id == actor.id
        and lead.assigned_sales_id == actor.id for row in handoffs)}
    candidates = []
    if permissions["can_invite"] or permissions["can_transfer"]:
        candidate_query = select(Employees).where(Employees.role == "sales", Employees.status.in_(ACTIVE))
        if lead.assigned_sales_id is not None:
            candidate_query = candidate_query.where(Employees.id != lead.assigned_sales_id)
        if normalize_system_role(actor.role) == "sales_manager":
            candidate_query = candidate_query.where(Employees.supervisor == actor.name)
        candidates = [{"id": item.id, "name": item.name} for item in (await db.scalars(
            candidate_query.order_by(Employees.name, Employees.id))).all()]
    enrichment = await get_enrichment(db, lead)
    enrichment["can_edit"] = permissions["can_edit"]
    if not permissions["can_edit"] and not enrichment.get("read_only_reason"):
        enrichment["read_only_reason"] = "此档案为只读协作权限"
    audits = (await db.scalars(select(SalesLeadEnrichmentAudit).where(SalesLeadEnrichmentAudit.lead_id == lead.id)
        .order_by(SalesLeadEnrichmentAudit.revision.desc()).limit(20))).all()
    summaries = (await db.scalars(select(SalesDossierSummaryAudit).where(SalesDossierSummaryAudit.lead_id == lead.id)
        .order_by(SalesDossierSummaryAudit.revision.desc()).limit(20))).all()
    enrichment_history = [{"id": row.id, "revision": row.revision, "source": row.source,
        "changed_fields": row.changed_fields, "before": safe_enrichment_snapshot(row.before),
        "after": safe_enrichment_snapshot(row.after), "actor_name": row.actor_name,
        "created_at": iso(row.created_at)} for row in audits]
    changes = [{**item, "kind": "enrichment", "at": item["created_at"]} for item in enrichment_history]
    changes += [{"id": row.id, "kind": "summary", "revision": row.revision,
        "before": {key: (row.before or {}).get(key, "") for key in ADDITIVE_FIELDS},
        "after": {key: (row.after or {}).get(key, "") for key in ADDITIVE_FIELDS},
        "changed_fields": [key for key in ADDITIVE_FIELDS if (row.before or {}).get(key) != (row.after or {}).get(key)],
        "actor_name": row.actor_name, "created_at": iso(row.created_at), "at": iso(row.created_at)} for row in summaries]
    changes.sort(key=lambda item: (item["at"] or "", item["id"]), reverse=True)
    return {"insight": insight, "enrichment": enrichment, "summary": await summary_for(db, lead),
        "protection": protection, "original": original_data, "permissions": permissions,
        "grants": grant_data, "handoffs": [handoff_data(row) for row in handoffs], "candidates": candidates,
        "catalog": await enrichment_catalog(db), "enrichment_history": enrichment_history, "changes": changes}


def safe_enrichment_snapshot(snapshot):
    fields = {"business_name", "industry", "city", "state", "country", "address", "website", "store_phone",
              "contacts", "preferred_contact_id", "interest_product_ids", "need_summary", "best_contact_time", "verification"}
    safe = {key: value for key, value in (snapshot or {}).items() if key in fields}
    if "contacts" in safe:
        safe["contacts"] = [{key: value for key, value in contact.items()
            if key in {"id", "name", "role", "phone", "email", "wechat", "verification"}}
            for contact in safe["contacts"] if isinstance(contact, dict)]
    return safe


async def shared_dossiers(db, user):
    actor = await active_actor(db, user)
    if normalize_system_role(actor.role) != "sales":
        return {"items": [], "total": 0}
    rows = (await db.execute(select(SalesLeads, SalesDossierGrant.access).join(SalesDossierGrant,
        SalesDossierGrant.lead_id == SalesLeads.id).where(SalesDossierGrant.employee_id == actor.id,
        SalesDossierGrant.status == "active").order_by(SalesLeads.business_name, SalesLeads.id))).all()
    items = [{"id": lead.id, "business_name": lead.business_name, "industry": lead.industry,
        "state": lead.state, "owner_name": lead.assigned_sales_name or "待分配", "access": access,
        "last_contact_at": iso(lead.last_contact_at), "next_follow_up_at": iso(lead.next_follow_up_at)}
        for lead, access in rows]
    return {"items": items, "total": len(items)}
