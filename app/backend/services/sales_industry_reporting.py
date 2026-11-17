"""Summarize saved CRM outcomes and verified outgoing calls in an authorized report scope."""
from collections import Counter, defaultdict

from services.merchant_industries import normalize_merchant_industry


def industry_breakdown(activities, provider_calls, industry_by_lead):
    recorded = defaultdict(set)
    interested = defaultdict(set)
    crm_records = Counter()
    outgoing = Counter()
    connected = Counter()

    for activity in activities:
        industry = normalize_merchant_industry(industry_by_lead.get(activity.lead_id)) or "待分类"
        recorded[industry].add(activity.lead_id)
        crm_records[industry] += 1
        if activity.outcome in {"interested", "appointment"}:
            interested[industry].add(activity.lead_id)

    unmatched = 0
    unmatched_connected = 0
    undated = 0
    for call in provider_calls:
        if call.started_at is None:
            undated += 1
            continue
        if call.lead_id not in industry_by_lead:
            unmatched += 1
            unmatched_connected += int(bool(call.connected))
            continue
        industry = normalize_merchant_industry(industry_by_lead[call.lead_id]) or "待分类"
        outgoing[industry] += 1
        connected[industry] += int(bool(call.connected))

    named = set(crm_records) | set(outgoing)
    industries = ["餐厅", "美业", *sorted(named - {"餐厅", "美业", "待分类"}), "待分类"]
    return {
        "industries": [
            {
                "industry": industry, "recorded_merchants": len(recorded[industry]),
                "crm_records": crm_records[industry], "interested_merchants": len(interested[industry]),
                "provider_calls": outgoing[industry], "connected": connected[industry],
            }
            for industry in industries
        ],
        "unmatched_provider_calls": unmatched,
        "unmatched_connected": unmatched_connected,
        "undated_provider_calls": undated,
    }
