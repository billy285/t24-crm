"""Manual CNY ledger. No CRM model, financial service, or provider dependency."""
from contextlib import asynccontextmanager
from datetime import date
import hashlib
import json
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import case, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError, OperationalError

from models.private_personal_finance import (
    PersonalAccount, PersonalCategory, PersonalDebt, PersonalEntry, PersonalFinanceAudit,
    PersonalFinanceSettings, PersonalGoal, PersonalPlan, PersonalFinanceReceipt,
)
from schemas.private_personal_finance import EntryCreate, MAX_MINOR


DEFAULT_CATEGORIES = (
    ("expense", "餐饮", "utensils"), ("expense", "交通", "train-front"),
    ("expense", "购物", "shopping-bag"), ("expense", "住房", "house"),
    ("expense", "生活", "coffee"), ("expense", "医疗", "heart-pulse"),
    ("expense", "娱乐", "music"), ("expense", "其他支出", "circle"),
    ("income", "工资", "wallet"), ("income", "奖金", "gift"),
    ("income", "其他收入", "circle"),
)
FIELDS = {
    PersonalCategory: ("id", "name", "kind", "icon", "active", "sort_order"),
    PersonalAccount: ("id", "name", "kind", "currency", "opening_balance_minor", "balance_minor", "active"),
    PersonalDebt: ("id", "name", "direction", "principal_minor", "remaining_minor", "due_date", "installment_minor", "note"),
    PersonalPlan: ("id", "name", "category_id", "amount_minor", "due_date", "status", "paid_entry_id", "actual_minor", "paid_date"),
    PersonalGoal: ("id", "name", "target_minor", "prepared_minor", "target_date", "active"),
    PersonalEntry: ("id", "kind", "amount_minor", "account_id", "to_account_id", "category_id", "debt_id", "plan_id", "counterparty", "entry_date", "note", "status", "client_request_id"),
}


def response(record):
    return {field: (getattr(record, field).isoformat() if isinstance(getattr(record, field), date)
                    else getattr(record, field)) for field in FIELDS[type(record)]}


def payload(value):
    result = value.model_dump(mode="json", exclude_unset=True)
    for field in result:
        if isinstance(getattr(value, field), date):
            result[field] = getattr(value, field)
    result.pop("client_request_id", None)
    return result


def conflict(message):
    raise HTTPException(status_code=409, detail=message)


def audit(db, owner, action, identity, detail=""):
    db.add(PersonalFinanceAudit(owner_id=owner, action=action, target_id=identity, detail=detail))


@asynccontextmanager
async def read_snapshot(db):
    if db.bind.dialect.name == "sqlite":
        await db.execute(text("BEGIN"))
    else:
        await db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
    try:
        yield
    finally:
        await db.rollback()


@asynccontextmanager
async def write(db, owner):
    """Serialize each owner's mutations across processes, not just Python tasks.

    SQLite obtains the writer reservation before the first ledger read. PostgreSQL
    locks the owner's settings row; first creation is protected by its primary key.
    All balance/debt validations and changes live in this same transaction.
    """
    try:
        dialect = db.bind.dialect.name
        if dialect == "sqlite":
            await db.execute(text("BEGIN IMMEDIATE"))
            insert = sqlite_insert
        elif dialect == "postgresql":
            insert = pg_insert
        else:
            raise HTTPException(status_code=503, detail="个人财务存储暂不可用")
        await db.execute(insert(PersonalFinanceSettings).values(owner_id=owner, initialized=False)
                         .on_conflict_do_nothing(index_elements=["owner_id"]))
        settings = (await db.execute(select(PersonalFinanceSettings).where(
            PersonalFinanceSettings.owner_id == owner).with_for_update())).scalar_one()
        yield settings
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        conflict("记录冲突，请刷新后重试")
    except OperationalError:
        await db.rollback()
        raise HTTPException(status_code=503, detail="个人账本正忙，请稍后重试") from None
    except Exception:
        await db.rollback()
        raise


async def owned(db, model, owner, identity):
    record = (await db.execute(select(model).where(model.owner_id == owner, model.id == str(identity)))).scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="未找到这条个人记录")
    return record


async def state(db, owner):
    settings = await db.get(PersonalFinanceSettings, owner)
    result = {"initialized": bool(settings and settings.initialized), "currency": "CNY",
              "budget_minor": settings.budget_minor if settings else None}
    for name, model in (("categories", PersonalCategory), ("accounts", PersonalAccount),
                        ("debts", PersonalDebt), ("plans", PersonalPlan), ("goals", PersonalGoal)):
        order = (model.kind, model.sort_order, model.created_at) if model is PersonalCategory else (model.created_at,)
        records = (await db.execute(select(model).where(model.owner_id == owner).order_by(*order))).scalars()
        result[name] = [response(record) for record in records]
    usage = {}
    for model in (PersonalEntry, PersonalPlan):
        for identity, count in (await db.execute(select(model.category_id, func.count()).where(
                model.owner_id == owner, model.category_id.is_not(None)).group_by(model.category_id))).all():
            usage[identity] = usage.get(identity, 0) + count
    for item in result["categories"]:
        item["entry_count"] = usage.get(item["id"], 0)
        item["used"] = bool(item["entry_count"])
    return result


async def bootstrap(db, owner, value=None):
    async with write(db, owner) as settings:
        existing = await create_replay(db, owner, "bootstrap", value) if value else None
        if not settings.initialized:
            for position, (kind, name, icon) in enumerate(DEFAULT_CATEGORIES):
                existing = (await db.execute(select(PersonalCategory.id).where(
                    PersonalCategory.owner_id == owner, PersonalCategory.kind == kind,
                    PersonalCategory.normalized_name == name.casefold()))).first()
                if not existing:
                    db.add(PersonalCategory(owner_id=owner, name=name, normalized_name=name.casefold(),
                                            kind=kind, icon=icon, sort_order=position))
            existing_account = (await db.execute(select(PersonalAccount.id).where(PersonalAccount.owner_id == owner).limit(1))).first()
            if not existing_account:
                db.add(PersonalAccount(owner_id=owner, name="现金", kind="cash", opening_balance_minor=0, balance_minor=0))
            settings.initialized = True
            audit(db, owner, "bootstrap", owner)
        if value and existing is None:
            create_receipt(db, owner, "bootstrap", value, {"initialized": True})
    return await state(db, owner)


async def category(db, owner, category_id, kind, *, active=True):
    value = await owned(db, PersonalCategory, owner, category_id)
    if value.kind != kind:
        conflict("分类类型与记账类型不一致")
    if active and not value.active:
        conflict("分类已停用，请选择其他分类")
    return value


async def category_used(db, owner, identity):
    for model in (PersonalEntry, PersonalPlan):
        if (await db.execute(select(model.id).where(model.owner_id == owner, model.category_id == identity).limit(1))).first():
            return True
    return False


async def create_replay(db, owner, kind, value):
    if not value.client_request_id:
        return None
    receipt = (await db.execute(select(PersonalFinanceReceipt).where(PersonalFinanceReceipt.owner_id == owner,
        PersonalFinanceReceipt.client_request_id == str(value.client_request_id)))).scalar_one_or_none()
    digest = fingerprint(value.model_dump(mode="json"))
    if receipt:
        if receipt.resource_kind != kind or receipt.request_hash != digest:
            conflict("此提交编号已用于不同内容，请刷新后重试")
        return receipt.result
    if (await db.execute(select(PersonalEntry.id).where(PersonalEntry.owner_id == owner,
            PersonalEntry.client_request_id == str(value.client_request_id)).limit(1))).first():
        conflict("此提交编号已用于其他记账内容，请刷新后重试")
    return None


def create_receipt(db, owner, kind, value, result):
    if value.client_request_id:
        db.add(PersonalFinanceReceipt(owner_id=owner, client_request_id=str(value.client_request_id),
               resource_kind=kind, request_hash=fingerprint(value.model_dump(mode="json")), result=result))


async def create_category(db, owner, value):
    async with write(db, owner):
        existing = await create_replay(db, owner, "category", value)
        if existing is not None:
            return existing
        row = PersonalCategory(owner_id=owner, **payload(value), normalized_name=value.name.casefold())
        db.add(row)
        await db.flush()
        audit(db, owner, "category_create", row.id)
        create_receipt(db, owner, "category", value, response(row))
    return response(row)


async def patch_category(db, owner, identity, value):
    async with write(db, owner):
        row = await owned(db, PersonalCategory, owner, identity)
        if value.kind is not None and value.kind != row.kind and await category_used(db, owner, row.id):
            conflict("已使用的分类不能更改收支类型，可以停用")
        for key, item in payload(value).items():
            setattr(row, key, item)
        row.normalized_name = row.name.casefold()
        audit(db, owner, "category_update", row.id)
    return response(row)


async def delete_category(db, owner, identity):
    async with write(db, owner):
        row = await owned(db, PersonalCategory, owner, identity)
        if await category_used(db, owner, row.id):
            conflict("已使用的分类不能删除，可以停用并保留历史")
        await db.delete(row)
        audit(db, owner, "category_delete", str(identity))
    return {"deleted": True}


async def reorder_categories(db, owner, value):
    async with write(db, owner):
        rows = (await db.execute(select(PersonalCategory).where(
            PersonalCategory.owner_id == owner, PersonalCategory.kind == value.kind))).scalars().all()
        identities = [str(identity) for identity in value.category_ids]
        if set(identities) != {row.id for row in rows}:
            conflict("分类列表已变更，请刷新后重新排序")
        positions = {identity: position for position, identity in enumerate(identities)}
        for row in rows:
            row.sort_order = positions[row.id]
        audit(db, owner, "category_reorder", value.kind)
    return {"categories": [response(row) for row in sorted(rows, key=lambda row: row.sort_order)]}


async def create_account(db, owner, value):
    async with write(db, owner):
        existing = await create_replay(db, owner, "account", value)
        if existing is not None:
            return existing
        row = PersonalAccount(owner_id=owner, **payload(value), balance_minor=value.opening_balance_minor)
        db.add(row)
        await db.flush()
        audit(db, owner, "account_create", row.id)
        create_receipt(db, owner, "account", value, response(row))
    return response(row)


async def patch_account(db, owner, identity, value):
    async with write(db, owner):
        row = await owned(db, PersonalAccount, owner, identity)
        data = payload(value)
        if "opening_balance_minor" in data and data["opening_balance_minor"] != row.opening_balance_minor:
            used = (await db.execute(select(PersonalEntry.id).where(PersonalEntry.owner_id == owner,
                (PersonalEntry.account_id == row.id) | (PersonalEntry.to_account_id == row.id)).limit(1))).first()
            if used:
                conflict("已有记账记录的账户不能更改期初余额")
            row.balance_minor = data["opening_balance_minor"]
        for key, item in data.items():
            setattr(row, key, item)
        audit(db, owner, "account_update", row.id)
    return response(row)


async def create_debt(db, owner, value):
    async with write(db, owner):
        existing = await create_replay(db, owner, "debt", value)
        if existing is not None:
            return existing
        if value.installment_minor and value.installment_minor > value.principal_minor:
            conflict("每期金额不能超过本金")
        row = PersonalDebt(owner_id=owner, **payload(value), remaining_minor=value.principal_minor)
        db.add(row)
        await db.flush()
        audit(db, owner, "debt_opening", row.id)
        create_receipt(db, owner, "debt", value, response(row))
    return response(row)


async def patch_debt(db, owner, identity, value):
    async with write(db, owner):
        row = await owned(db, PersonalDebt, owner, identity)
        if value.installment_minor and value.installment_minor > row.principal_minor:
            conflict("每期金额不能超过本金")
        for key, item in payload(value).items():
            setattr(row, key, item)
        audit(db, owner, "debt_update", row.id)
    return response(row)


async def create_plan(db, owner, value):
    async with write(db, owner):
        existing = await create_replay(db, owner, "plan", value)
        if existing is not None:
            return existing
        await category(db, owner, value.category_id, "expense")
        row = PersonalPlan(owner_id=owner, **payload(value))
        db.add(row)
        await db.flush()
        audit(db, owner, "plan_create", row.id)
        create_receipt(db, owner, "plan", value, response(row))
    return response(row)


async def patch_plan(db, owner, identity, value):
    async with write(db, owner):
        row = await owned(db, PersonalPlan, owner, identity)
        if row.status == "paid":
            conflict("已付款计划不能改写，金额错误请先作废原记账")
        if value.category_id and str(value.category_id) != row.category_id:
            await category(db, owner, value.category_id, "expense")
        for key, item in payload(value).items():
            setattr(row, key, item)
        audit(db, owner, "plan_update", row.id)
    return response(row)


async def create_goal(db, owner, value):
    async with write(db, owner):
        existing = await create_replay(db, owner, "goal", value)
        if existing is not None:
            return existing
        if value.prepared_minor > value.target_minor:
            conflict("已安排金额不能超过目标")
        row = PersonalGoal(owner_id=owner, **payload(value))
        db.add(row)
        await db.flush()
        audit(db, owner, "goal_create", row.id)
        create_receipt(db, owner, "goal", value, response(row))
    return response(row)


async def patch_goal(db, owner, identity, value):
    async with write(db, owner):
        row = await owned(db, PersonalGoal, owner, identity)
        data = payload(value)
        if data.get("prepared_minor", row.prepared_minor) > data.get("target_minor", row.target_minor):
            conflict("已安排金额不能超过目标")
        for key, item in data.items():
            setattr(row, key, item)
        audit(db, owner, "goal_update", row.id)
    return response(row)


async def patch_budget(db, owner, value):
    async with write(db, owner) as settings:
        settings.budget_minor = value.budget_minor
        audit(db, owner, "budget_update", owner)
    return {"budget_minor": value.budget_minor}


def fingerprint(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


async def replay(db, owner, request_id, request_hash):
    if (await db.execute(select(PersonalFinanceReceipt.id).where(PersonalFinanceReceipt.owner_id == owner,
            PersonalFinanceReceipt.client_request_id == str(request_id)).limit(1))).first():
        conflict("此提交编号已用于其他内容，请刷新后重试")
    row = (await db.execute(select(PersonalEntry).where(PersonalEntry.owner_id == owner,
                    PersonalEntry.client_request_id == str(request_id)))).scalar_one_or_none()
    if row and row.request_hash != request_hash:
        conflict("此提交编号已用于不同记账内容，请刷新后重试")
    return row


async def request_status(db, owner, request_id):
    receipt = (await db.execute(select(PersonalFinanceReceipt).where(PersonalFinanceReceipt.owner_id == owner,
        PersonalFinanceReceipt.client_request_id == str(request_id)))).scalar_one_or_none()
    if receipt:
        return {"found": True, "resource_kind": receipt.resource_kind, "resource_id": receipt.result.get("id")}
    entry = (await db.execute(select(PersonalEntry.id, PersonalEntry.plan_id).where(PersonalEntry.owner_id == owner,
        PersonalEntry.client_request_id == str(request_id)))).one_or_none()
    if entry:
        return {"found": True, "resource_kind": "plan_payment" if entry.plan_id else "entry", "entry_id": entry.id}
    return {"found": False}


async def apply_effect(db, owner, row, factor, *, fresh=False):
    account = await owned(db, PersonalAccount, owner, row.account_id)
    if factor == 1 and not account.active:
        conflict("账户已停用，请先恢复账户")
    direction = 1 if row.kind in {"income", "borrow", "collect"} else -1
    next_balance = account.balance_minor + direction * row.amount_minor * factor
    if not 0 <= next_balance <= MAX_MINOR:
        conflict("账户余额不足或超出可记账范围")
    account.balance_minor = next_balance
    if row.kind == "transfer":
        target = await owned(db, PersonalAccount, owner, row.to_account_id)
        if factor == 1 and not target.active:
            conflict("转入账户已停用")
        next_target = target.balance_minor + row.amount_minor * factor
        if not 0 <= next_target <= MAX_MINOR:
            conflict("转入账户余额不足或超出可记账范围")
        target.balance_minor = next_target
    if row.debt_id:
        debt = await owned(db, PersonalDebt, owner, row.debt_id)
        expected = "payable" if row.kind in {"borrow", "repay"} else "receivable"
        if debt.direction != expected:
            conflict("借还方向与欠款不一致")
        if row.kind in {"borrow", "lend"}:
            debt.principal_minor += row.amount_minor * factor
            debt.remaining_minor += row.amount_minor * factor
        else:
            debt.remaining_minor -= row.amount_minor * factor
        if not 0 <= debt.remaining_minor <= debt.principal_minor <= MAX_MINOR:
            conflict("金额超过待借还本金，或已有后续借还记录")
    if row.plan_id:
        plan = await owned(db, PersonalPlan, owner, row.plan_id)
        if factor == 1:
            if plan.status != "pending" or plan.paid_entry_id:
                conflict("计划已付款或取消，不能重复入账")
            plan.status, plan.paid_entry_id = "paid", row.id
            plan.category_id = row.category_id
            plan.actual_minor, plan.paid_date = row.amount_minor, row.entry_date
        else:
            if plan.paid_entry_id != row.id:
                conflict("计划关联记录已变更，请刷新后重试")
            plan.status, plan.paid_entry_id, plan.actual_minor, plan.paid_date = "pending", None, None, None


async def insert_entry(db, owner, value, request_hash, *, plan=None):
    existing = await replay(db, owner, value.client_request_id, request_hash)
    if existing:
        return existing
    if value.kind in {"expense", "income"}:
        await category(db, owner, value.category_id, value.kind)
    data = value.model_dump(mode="json")
    data["entry_date"] = value.entry_date
    if value.kind in {"borrow", "lend"} and not value.debt_id:
        debt = PersonalDebt(id=str(uuid4()), owner_id=owner, name=value.counterparty,
                            direction="payable" if value.kind == "borrow" else "receivable",
                            principal_minor=0, remaining_minor=0, note=value.note)
        db.add(debt)
        await db.flush()
        data["debt_id"] = debt.id
    row = PersonalEntry(id=str(uuid4()), owner_id=owner, **data, request_hash=request_hash,
                        plan_id=plan.id if plan else None, status="active")
    db.add(row)
    # Flush identifiers before apply_effect; the owner lock already excludes
    # another writer, so a failed balance check rolls the entire insertion back.
    await db.flush()
    await apply_effect(db, owner, row, 1, fresh=True)
    audit(db, owner, "entry_create", row.id)
    return row


async def create_entry(db, owner, value):
    request_hash = fingerprint(value.model_dump(mode="json"))
    async with write(db, owner):
        row = await insert_entry(db, owner, value, request_hash)
    return {"entry": response(row)}


async def pay_plan(db, owner, identity, value):
    request_hash = fingerprint({"plan_id": str(identity), **value.model_dump(mode="json")})
    async with write(db, owner):
        row = await replay(db, owner, value.client_request_id, request_hash)
        if not row:
            plan = await owned(db, PersonalPlan, owner, identity)
            if plan.status != "pending" or plan.paid_entry_id:
                conflict("此计划已付款或取消，不能重复入账")
            entry = EntryCreate(kind="expense", category_id=plan.category_id, **value.model_dump())
            row = await insert_entry(db, owner, entry, request_hash, plan=plan)
    return {"entry": response(row)}


async def entry_status(db, owner, identity, target):
    async with write(db, owner):
        row = await owned(db, PersonalEntry, owner, identity)
        if row.status != target:
            await apply_effect(db, owner, row, 1 if target == "active" else -1)
            row.status = target
            audit(db, owner, "entry_restore" if target == "active" else "entry_void", row.id)
    return {"entry": response(row)}


async def patch_entry(db, owner, identity, value):
    async with write(db, owner):
        row = await owned(db, PersonalEntry, owner, identity)
        if value.category_id and str(value.category_id) != row.category_id:
            if row.kind not in {"expense", "income"}:
                conflict("借还本金和转账不能设为收支分类")
            await category(db, owner, value.category_id, row.kind)
        for key, item in payload(value).items():
            setattr(row, key, value.entry_date if key == "entry_date" else item)
        if row.plan_id and row.status == "active":
            plan = await owned(db, PersonalPlan, owner, row.plan_id)
            plan.paid_date = row.entry_date
            plan.category_id = row.category_id
        audit(db, owner, "entry_metadata", row.id)
    return {"entry": response(row)}


def validate_range(start, end):
    if not date(2000, 1, 1) <= start <= end <= date(2100, 12, 31) or (end - start).days > 3660:
        raise HTTPException(status_code=422, detail="请选择有效日期范围，最长十年")


async def list_entries(db, owner, start, end, category_id, kind, status, page, page_size):
    validate_range(start, end)
    filters = [PersonalEntry.owner_id == owner, PersonalEntry.entry_date >= start, PersonalEntry.entry_date <= end]
    if status != "all":
        filters.append(PersonalEntry.status == status)
    if category_id:
        await owned(db, PersonalCategory, owner, category_id)
        filters.append(PersonalEntry.category_id == str(category_id))
    if kind:
        filters.append(PersonalEntry.kind == kind)
    total = (await db.execute(select(func.count()).select_from(PersonalEntry).where(*filters))).scalar_one()
    records = (await db.execute(select(PersonalEntry).where(*filters).order_by(
        PersonalEntry.entry_date.desc(), PersonalEntry.created_at.desc(), PersonalEntry.id)
        .offset((page - 1) * page_size).limit(page_size))).scalars()
    return {"items": [response(row) for row in records], "total": total, "page": page, "page_size": page_size}


async def report(db, owner, start, end):
    validate_range(start, end)
    filters = [PersonalEntry.owner_id == owner, PersonalEntry.entry_date >= start,
               PersonalEntry.entry_date <= end, PersonalEntry.status == "active"]
    totals = dict((await db.execute(select(PersonalEntry.kind, func.sum(PersonalEntry.amount_minor))
                                   .where(*filters).group_by(PersonalEntry.kind))).all())
    income, expense = int(totals.get("income", 0)), int(totals.get("expense", 0))
    grouped = (await db.execute(select(PersonalEntry.category_id, PersonalCategory.name, PersonalCategory.kind,
        func.sum(PersonalEntry.amount_minor), func.count()).join(PersonalCategory,
        (PersonalEntry.category_id == PersonalCategory.id) & (PersonalCategory.owner_id == owner))
        .where(*filters, PersonalEntry.kind.in_(["income", "expense"]))
        .group_by(PersonalEntry.category_id, PersonalCategory.name, PersonalCategory.kind))).all()
    trends = (await db.execute(select(PersonalEntry.entry_date,
        func.sum(case((PersonalEntry.kind == "income", PersonalEntry.amount_minor), else_=0)),
        func.sum(case((PersonalEntry.kind == "expense", PersonalEntry.amount_minor), else_=0)))
        .where(*filters, PersonalEntry.kind.in_(["income", "expense"]))
        .group_by(PersonalEntry.entry_date).order_by(PersonalEntry.entry_date))).all()
    return {"currency": "CNY", "start_date": start.isoformat(), "end_date": end.isoformat(),
            "income_minor": income, "expense_minor": expense, "net_minor": income - expense,
            "movements": {name + "_minor": int(totals.get(name, 0)) for name in ("borrow", "lend", "repay", "collect", "transfer")},
            "category_totals": [{"category_id": row[0], "name": row[1], "kind": row[2],
                                 "total_minor": int(row[3]), "count": int(row[4])} for row in grouped],
            "trend": [{"date": row[0].isoformat(), "income_minor": int(row[1]), "expense_minor": int(row[2])} for row in trends]}
