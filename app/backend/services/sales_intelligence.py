"""Explainable, read-only aggregation. Provider facts never come from manual outcomes."""

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")
POSITIVE = {"interested", "appointment"}
NEGATIVE = {"not_interested", "not_now", "existing_provider"}
LABELS = {
    "no_answer": "未接通",
    "callback": "待回访",
    "interested": "有意向",
    "appointment": "已预约",
    "not_interested": "无意向",
    "not_now": "暂时不需要",
    "existing_provider": "已有服务商",
    "do_not_contact": "禁止再联系",
}
POTENTIAL_LABELS = {
    "priority": "优先推进",
    "nurture": "持续培育",
    "unknown": "待判断",
    "low_fit": "低匹配",
    "blocked": "禁止联系",
    "won": "已转客户",
}


def unpack(raw):
    try:
        return json.loads(raw or "{}")
    except (ValueError, TypeError):
        return {}


def stamp(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def iso(value):
    return stamp(value).isoformat() if value else None


def default_config():
    stages = [
        ("needs", "确认需求", "记录真实需求及决策人", "qualified"),
        ("scheduled", "预约演示", "确认参与人、时间和下一步", "scheduled"),
        ("demo", "完成演示", "实际沟通已发生，记录客户反馈", "demo"),
        ("quoted", "已报价", "使用已审批报价，记录反馈", "quoted"),
        ("decision", "等待决策", "确认决策人、主要顾虑及决策时间", "decision"),
        ("won", "成交确认", "既有成交审核已完成收款确认", "won"),
        ("handoff", "完成交接", "已转正式客户且交接负责人明确", "handoff"),
        ("nurture", "暂缓培育", "记录暂缓原因及回访时间", "nurture"),
        ("lost", "失单", "记录明确失单原因", "lost"),
    ]
    return {
        "pipelines": [
            {
                "key": key,
                "label": label,
                "stages": [
                    {
                        "key": s[0],
                        "label": (
                            "方案沟通完成"
                            if key == "managed" and s[0] == "demo"
                            else s[1]
                        ),
                        "evidence": s[2],
                        "milestone": s[3],
                        "stale_days": 7,
                    }
                    for s in stages
                ],
            }
            for key, label in [("system", "系统销售"), ("managed", "代运营销售")]
        ],
        "custom_fields": [
            {"key": "current_system", "label": "现用系统", "required_milestones": []},
            {
                "key": "contract_expiry",
                "label": "现有合同到期时间",
                "required_milestones": [],
            },
        ],
        "weights": {"results": 40, "pipeline": 25, "execution": 20, "quality": 15},
        "repeated_rejection_count": 3,
        "unconnected_attempts": 5,
        "interest_stale_days": 14,
        "default_contact_start": 10,
        "default_contact_end": 18,
    }


def canonical_calls(rows):
    grouped = defaultdict(list)
    for row in rows:
        if (row.direction or "").lower() != "outbound" or row.sync_status != "verified":
            continue
        identity = (
            row.telephony_session_id
            or row.ringcentral_session_id
            or row.ringcentral_call_id
            or row.provider_key
        )
        grouped[(row.ringcentral_account_id or "", identity)].append(row)
    result = []
    for key, parts in grouped.items():
        first = min(parts, key=lambda r: (stamp(r.started_at or r.created_at), r.id))
        activity_ids = {r.activity_id for r in parts if r.activity_id}
        result.append(
            {
                "key": str(key),
                "id": first.id,
                "lead_id": first.lead_id,
                "started_at": iso(first.started_at or first.created_at),
                "connected": any(r.connected for r in parts),
                "duration_seconds": max((r.duration_seconds or 0) for r in parts),
                "result": next(
                    (r.provider_result for r in parts if r.connected),
                    first.provider_result,
                ),
                "activity_ids": activity_ids,
                "call_ids": {
                    r.ringcentral_call_id for r in parts if r.ringcentral_call_id
                },
                "session_ids": {
                    v
                    for r in parts
                    for v in (r.ringcentral_session_id, r.telephony_session_id)
                    if v
                },
                "sales_employee_id": first.sales_employee_id,
                "salesperson": first.sales_employee_name,
                "synced_at": max((iso(r.synced_at) or "" for r in parts), default="")
                or None,
            }
        )
    result.sort(key=lambda r: (r["started_at"], r["id"]))
    for index, row in enumerate(result, 1):
        row["ordinal"] = index
    return result


def summarize_lead(
    lead, activities, provider_rows, details, profile, events, config, now=None
):
    now = stamp(now or datetime.now(timezone.utc))
    activities = sorted(activities, key=lambda a: (stamp(a.called_at), a.id))
    calls = canonical_calls(provider_rows)
    by_activity = {aid: call for call in calls for aid in call["activity_ids"]}
    for a in activities:
        if a.id not in by_activity:
            matching = [
                c
                for c in calls
                if (a.ringcentral_call_id and a.ringcentral_call_id in c["call_ids"])
                or (
                    a.ringcentral_session_id
                    and a.ringcentral_session_id in c["session_ids"]
                )
            ]
            if len(matching) == 1:
                by_activity[a.id] = matching[0]
    counts = Counter(a.outcome for a in activities)
    first_interest = next((a for a in activities if a.outcome in POSITIVE), None)
    first_appointment = next(
        (a for a in activities if a.outcome == "appointment"), None
    )
    substantive = [a for a in activities if a.outcome != "no_answer"]
    latest = substantive[-1] if substantive else None
    latest_positive = next(
        (a for a in reversed(activities) if a.outcome in POSITIVE), None
    )
    all_mapped = {a.id for a in activities if a.id in by_activity}
    mapped_outcomes = defaultdict(list)
    for a in activities:
        if a.id in by_activity:
            mapped_outcomes[by_activity[a.id]["key"]].append(a)
    connected = [c for c in calls if c["connected"]]
    rejection_calls = sum(
        bool(mapped_outcomes[c["key"]])
        and mapped_outcomes[c["key"]][-1].outcome in NEGATIVE
        for c in connected
    )
    classified_calls = sum(bool(mapped_outcomes[c["key"]]) for c in connected)
    unknown_connected = len(connected) - classified_calls
    first_call = by_activity.get(first_interest.id) if first_interest else None
    qualified = [
        d
        for d in details.values()
        if d.reached_person == "decision_maker" and (d.need_summary or "").strip()
    ]
    reasons = Counter(
        d.rejection_reason for d in details.values() if d.rejection_reason
    )
    p = unpack(profile.payload_json) if profile else {}
    potential = "unknown"
    rationale = ["尚无足够的需求与决策人证据"]
    if lead.is_blacklisted or lead.do_not_contact:
        potential = "blocked"
        rationale = [lead.do_not_contact_reason or "现有联系保护规则禁止继续联系"]
    elif lead.converted_customer_id:
        potential = "won"
        rationale = ["已通过既有审核转入正式客户"]
    elif p.get("potential_override"):
        potential = p["potential_override"]
        rationale = ["主管复核：" + p.get("override_reason", "")]
    elif p.get("milestone") == "lost":
        potential = "low_fit"
        rationale = ["已记录失单：" + p.get("evidence", "")]
    elif p.get("milestone") == "nurture":
        potential = "nurture"
        rationale = ["已记录暂缓培育：" + p.get("evidence", "")]
    elif latest and latest.outcome in POSITIVE:
        age = (now - stamp(latest.called_at)).days
        potential = "priority" if age <= config["interest_stale_days"] else "nurture"
        rationale = [f"最近明确结果为{LABELS[latest.outcome]}，距今 {max(0,age)} 天"]
    elif latest and latest.outcome in NEGATIVE:
        potential = "nurture"
        rationale = ["最近明确结果为" + LABELS[latest.outcome] + "，需核对时机与原因"]
    elif p.get("need_summary") and p.get("decision_maker"):
        potential = "priority"
        rationale = ["已补充明确需求及决策人，需验证下一步"]
    elif len(calls) >= config["unconnected_attempts"] and not connected:
        rationale = [f"已同步 {len(calls)} 次拨打仍未接通，尚不能判断意向"]
    negative_count = sum(counts[k] for k in NEGATIVE)
    if negative_count >= config["repeated_rejection_count"]:
        rationale.append(f"累计 {negative_count} 条拒绝／暂缓记录，建议复核原因")
    following = iso(lead.next_follow_up_at)
    active = potential not in {"won", "blocked", "low_fit"}
    overdue = bool(active and following and stamp(following) < now)
    no_next = bool(potential == "priority" and not following)
    turned = bool(
        latest
        and latest.outcome in POSITIVE
        and any(
            a.outcome in NEGATIVE and stamp(a.called_at) < stamp(latest.called_at)
            for a in activities
        )
    )
    timeline = []
    for a in activities:
        c = by_activity.get(a.id)
        d = details.get(a.id)
        timeline.append(
            {
                "id": f"activity-{a.id}",
                "activity_id": a.id,
                "kind": "contact",
                "at": iso(a.called_at),
                "outcome": a.outcome,
                "label": LABELS.get(a.outcome, a.outcome),
                "notes": a.notes,
                "salesperson": a.sales_employee_name,
                "source": "provider_linked" if c else "manual",
                "official_ordinal": c["ordinal"] if c else None,
                "connected": c["connected"] if c else None,
                "duration_seconds": c["duration_seconds"] if c else None,
                "next_follow_up_at": iso(a.next_follow_up_at),
                "details": (
                    {
                        "reached_person": d.reached_person,
                        "rejection_reason": d.rejection_reason,
                        "need_summary": d.need_summary,
                        "next_step": d.next_step,
                    }
                    if d
                    else None
                ),
            }
        )
    linked_keys = {c["key"] for c in by_activity.values()}
    for c in calls:
        if c["key"] not in linked_keys:
            timeline.append(
                {
                    "id": f"call-{c['id']}",
                    "kind": "provider",
                    "at": c["started_at"],
                    "label": "已接通 · 待补结果" if c["connected"] else "未接通",
                    "source": "provider",
                    "connected": c["connected"],
                    "official_ordinal": c["ordinal"],
                    "duration_seconds": c["duration_seconds"],
                    "salesperson": c["salesperson"],
                }
            )
    for e in events:
        timeline.append(
            {
                "id": f"event-{e.id}",
                "kind": e.kind,
                "at": iso(e.created_at),
                "label": "商机／分类更新",
                "salesperson": e.actor_name,
                "source": "review",
                "details": unpack(e.payload_json),
            }
        )
    timeline.sort(key=lambda e: (e["at"] or "", e["id"]), reverse=True)
    first_observed = min(
        [stamp(a.called_at) for a in activities]
        + [stamp(c["started_at"]) for c in calls],
        default=None,
    )
    per_rep = {}
    for a in activities:
        rep = per_rep.setdefault(
            a.sales_employee_id,
            {
                "employee_id": a.sales_employee_id,
                "name": a.sales_employee_name,
                "records": 0,
                "positive": 0,
                "calls": 0,
            },
        )
        rep["records"] += 1
        rep["positive"] += int(a.outcome in POSITIVE)
    for c in calls:
        rep = per_rep.setdefault(
            c["sales_employee_id"],
            {
                "employee_id": c["sales_employee_id"],
                "name": c["salesperson"],
                "records": 0,
                "positive": 0,
                "calls": 0,
            },
        )
        rep["calls"] += 1
    return {
        "id": lead.id,
        "business_name": lead.business_name,
        "phone": lead.phone,
        "source": lead.source or "未标注",
        "industry": lead.industry or "未标注",
        "city": lead.city,
        "state": lead.state,
        "owner_id": lead.assigned_sales_id,
        "owner": lead.assigned_sales_name or "待分配",
        "merchant_pool_id": lead.merchant_pool_id,
        "converted_customer_id": lead.converted_customer_id,
        "potential": potential,
        "potential_label": POTENTIAL_LABELS[potential],
        "rationale": rationale,
        "status": lead.status,
        "calls": len(calls),
        "connected": len(connected),
        "not_connected": len(calls) - len(connected),
        "pending_calls": sum(r.sync_status != "verified" for r in provider_rows),
        "manual_records": len(activities) - len(all_mapped),
        "records": len(activities),
        "linked_records": len(all_mapped),
        "decision_conversations": len(qualified),
        "outcomes": dict(counts),
        "rejection_reasons": dict(reasons),
        "connected_rejections": rejection_calls,
        "connected_without_result": unknown_connected,
        "all_connected_rejected": bool(
            connected and not unknown_connected and rejection_calls == len(connected)
        ),
        "first_interest_at": iso(first_interest.called_at) if first_interest else None,
        "first_interest_record_number": next(
            (i for i, a in enumerate(activities, 1) if a == first_interest), None
        ),
        "first_interest_call_number": first_call["ordinal"] if first_call else None,
        "days_to_interest": (
            max(0, (stamp(first_interest.called_at) - first_observed).days)
            if first_interest and first_observed
            else None
        ),
        "first_appointment_at": (
            iso(first_appointment.called_at) if first_appointment else None
        ),
        "last_contact_at": max(
            [iso(a.called_at) for a in activities] + [c["started_at"] for c in calls],
            default=None,
        ),
        "last_synced_at": max(
            [c["synced_at"] for c in calls if c["synced_at"]], default=None
        ),
        "next_follow_up_at": following,
        "overdue": overdue,
        "no_next_step": no_next,
        "turned_positive": turned,
        "profile": p,
        "revision": profile.revision if profile else 0,
        "timeline": timeline,
        "contributors": list(per_rep.values()),
    }
