"""Merchant labels persist on the pool record when a lead has one."""

from collections import defaultdict
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import or_, select

from models.sales_labels import SalesLabel, SalesLabelAssignment
from services.merchant_industries import normalize_merchant_industry

INDUSTRIES = {"restaurant": "餐厅", "beauty": "美业"}


def catalog_item(label):
    return {"id": label.id, "name": label.name, "kind": label.kind,
            "industry": label.industry, "archived": label.archived}


def label_applies(label, industry):
    return label.industry == "all" or normalize_merchant_industry(industry) == INDUSTRIES.get(label.industry)


def sales_label_filter(label_id, *, merchant_id=None, lead_id=None, provider_confirmed=None):
    # Separate EXISTS checks keep each match on the (target_id, label_id)
    # indexes even when most of a large pool shares a single source tag.
    matching = []
    catalog_is_not_provider = select(1).select_from(SalesLabel).where(
        SalesLabel.id == label_id, SalesLabel.kind != "provider").exists()
    for column, target in ((SalesLabelAssignment.merchant_id, merchant_id), (SalesLabelAssignment.lead_id, lead_id)):
        if target is None:
            continue
        query = select(1).select_from(SalesLabelAssignment).where(
            SalesLabelAssignment.label_id == label_id, column == target
        ).correlate_except(SalesLabelAssignment)
        if provider_confirmed is not None:
            query = query.where(or_(SalesLabelAssignment.confirmed == provider_confirmed, catalog_is_not_provider))
        matching.append(query.exists())
    if not matching:
        raise ValueError("label filter requires a merchant or lead target")
    return or_(*matching)


async def target_labels(db, merchant_ids=(), lead_ids=()):
    conditions = []
    if merchant_ids:
        conditions.append(SalesLabelAssignment.merchant_id.in_(set(merchant_ids)))
    if lead_ids:
        conditions.append(SalesLabelAssignment.lead_id.in_(set(lead_ids)))
    if not conditions:
        return {}, {}
    rows = (await db.execute(select(SalesLabelAssignment, SalesLabel)
            .join(SalesLabel, SalesLabel.id == SalesLabelAssignment.label_id)
            .where(or_(*conditions)).order_by(SalesLabel.archived, SalesLabel.kind, SalesLabel.name))).all()
    merchants, leads = defaultdict(list), defaultdict(list)
    for assignment, label in rows:
        item = {**catalog_item(label), "confirmed": assignment.confirmed,
                "confirmed_at": assignment.confirmed_at}
        if assignment.merchant_id is not None:
            merchants[assignment.merchant_id].append(item)
        else:
            leads[assignment.lead_id].append(item)
    return merchants, leads


async def lead_labels(db, targets):
    merchants, leads = await target_labels(db, [m for _, m in targets if m is not None], [l for l, _ in targets])
    return {lead: [*merchants.get(merchant, []), *leads.get(lead, [])] for lead, merchant in targets}


async def active_labels(db, ids):
    items = (await db.execute(select(SalesLabel).where(
        SalesLabel.id.in_(ids), SalesLabel.archived.is_(False)).order_by(SalesLabel.id).with_for_update())).scalars().all()
    if len(items) != len(set(ids)):
        raise HTTPException(422, "标签不存在或已停用，请刷新后选择")
    return items


async def add_labels(db, *, merchants=(), leads=(), labels, actor_id=None, provider_confirmed=False, batch_id=None):
    """Add idempotently. An imported observation never resets prior confirmation."""
    merchant_ids = [target.id for target in merchants]
    lead_ids = [target.id for target in leads]
    target = or_(SalesLabelAssignment.merchant_id.in_(merchant_ids), SalesLabelAssignment.lead_id.in_(lead_ids))
    existing = (await db.execute(select(SalesLabelAssignment).where(
        target, SalesLabelAssignment.label_id.in_([label.id for label in labels])))).scalars().all()
    by_target = {(link.merchant_id, link.lead_id, link.label_id): link for link in existing}
    added = 0
    for targets, is_merchant in ((merchants, True), (leads, False)):
        for row in targets:
            for label in labels:
                if not label_applies(label, row.industry):
                    continue
                key = (row.id, None, label.id) if is_merchant else (None, row.id, label.id)
                assignment = by_target.get(key)
                if assignment is None:
                    assignment = SalesLabelAssignment(merchant_id=key[0], lead_id=key[1], label_id=key[2],
                                                      import_batch_id=batch_id)
                    by_target[key] = assignment
                    db.add(assignment)
                    added += 1
                if label.kind == "provider" and provider_confirmed and not assignment.confirmed:
                    assignment.confirmed = True
                    assignment.confirmed_by = actor_id
                    assignment.confirmed_at = datetime.now(timezone.utc)
    return added
