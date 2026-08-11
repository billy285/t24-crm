import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.mask_crypto import encrypt_text
from dependencies.auth import get_current_user
from models.employees import Employees
from models.payroll import PayrollAuditLogs, PayrollItems, PayrollSheets
from schemas.auth import UserResponse


router = APIRouter(prefix="/api/v1/payroll", tags=["payroll"])
PAYROLL_ROLES = {"admin", "super_admin", "finance"}
ADMIN_ROLES = {"admin", "super_admin"}
PAYMENT_METHODS = {"alipay", "bank_card", "wechat", "cash", "other"}
PAYMENT_STATUS_ORDER = ("pending", "partial", "supplemental", "failed", "returned", "paid")
PAYMENT_STATUSES = set(PAYMENT_STATUS_ORDER)


class PayrollItemInput(BaseModel):
    employee_id: Optional[int] = None
    employee_name: str = Field(min_length=1, max_length=200)
    employee_code: Optional[str] = None
    department: Optional[str] = None
    hire_date: Optional[str] = None
    payment_method: str = "alipay"
    payment_account: Optional[str] = Field(default=None, max_length=500)
    base_salary: float = Field(default=0, ge=0)
    fixed_performance: float = Field(default=0, ge=0)
    commission: float = Field(default=0, ge=0)
    bonus: float = Field(default=0, ge=0)
    allowance: float = Field(default=0, ge=0)
    reimbursement: float = Field(default=0, ge=0)
    absence_deduction: float = Field(default=0, ge=0)
    performance_deduction: float = Field(default=0, ge=0)
    salary_advance_deduction: float = Field(default=0, ge=0)
    other_deduction: float = Field(default=0, ge=0)
    payment_status: str = "pending"
    payment_date: Optional[str] = None
    payment_reference: Optional[str] = None
    receipt_url: Optional[str] = None
    notes: Optional[str] = Field(default=None, max_length=4000)

    @field_validator("payment_method")
    @classmethod
    def validate_method(cls, value: str) -> str:
        if value not in PAYMENT_METHODS:
            raise ValueError("无效的发放方式")
        return value

    @field_validator("payment_status")
    @classmethod
    def validate_payment_status(cls, value: str) -> str:
        if value not in PAYMENT_STATUSES:
            raise ValueError("无效的发放状态")
        return value


class PayrollTransition(BaseModel):
    action: str
    reason: Optional[str] = Field(default=None, max_length=1000)


def _ensure_role(user: UserResponse) -> str:
    role = str(user.role or "").lower()
    if role not in PAYROLL_ROLES:
        raise HTTPException(status_code=403, detail="无权访问工资表")
    return role


def _valid_month(month: str) -> str:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise HTTPException(status_code=400, detail="工资月份格式应为 YYYY-MM")
    return month


def _actor(user: UserResponse) -> str:
    return user.name or user.email or str(user.id)


def _amounts(item: PayrollItems) -> tuple[float, float, float]:
    additions = sum(float(getattr(item, name) or 0) for name in ("base_salary", "fixed_performance", "commission", "bonus", "allowance", "reimbursement"))
    deductions = sum(float(getattr(item, name) or 0) for name in ("absence_deduction", "performance_deduction", "salary_advance_deduction", "other_deduction"))
    return additions, deductions, additions - deductions


def _item_payload(item: PayrollItems) -> dict:
    additions, deductions, net = _amounts(item)
    masked = f"•••• {item.payment_account_last4}" if item.payment_account_last4 else None
    return {
        "id": item.id, "sheet_id": item.sheet_id, "employee_id": item.employee_id,
        "employee_code": item.employee_code, "employee_name": item.employee_name,
        "department": item.department, "hire_date": item.hire_date,
        "payment_method": item.payment_method, "payment_account_masked": masked,
        "base_salary": item.base_salary, "fixed_performance": item.fixed_performance,
        "commission": item.commission, "bonus": item.bonus, "allowance": item.allowance,
        "reimbursement": item.reimbursement, "absence_deduction": item.absence_deduction,
        "performance_deduction": item.performance_deduction,
        "salary_advance_deduction": item.salary_advance_deduction, "other_deduction": item.other_deduction,
        "payment_status": item.payment_status, "payment_date": item.payment_date,
        "payment_reference": item.payment_reference, "receipt_url": item.receipt_url, "notes": item.notes,
        "gross_amount": round(additions, 2), "deduction_amount": round(deductions, 2), "net_amount": round(net, 2),
    }


async def _audit(db: AsyncSession, sheet: PayrollSheets, user: UserResponse, action: str, item: Optional[PayrollItems] = None, reason: Optional[str] = None) -> None:
    db.add(PayrollAuditLogs(
        sheet_id=sheet.id, item_id=item.id if item else None, action=action,
        actor_id=str(user.id), actor_name=_actor(user), actor_role=str(user.role), reason=reason,
        snapshot_json=json.dumps(_item_payload(item), ensure_ascii=False) if item else json.dumps({"month": sheet.month, "status": sheet.status}, ensure_ascii=False),
    ))


async def _get_or_create_sheet(db: AsyncSession, month: str) -> PayrollSheets:
    sheet = (await db.execute(select(PayrollSheets).where(PayrollSheets.month == month))).scalar_one_or_none()
    if not sheet:
        sheet = PayrollSheets(month=month, status="draft", currency="CNY")
        db.add(sheet)
        await db.flush()
    return sheet


async def _migrate_legacy_once(db: AsyncSession, user: UserResponse) -> None:
    existing = (await db.execute(select(func.count(PayrollSheets.id)))).scalar_one()
    if existing:
        return
    try:
        row = (await db.execute(text("SELECT value_json FROM app_settings WHERE config_key = 'payroll_sheets_v1'"))).first()
    except Exception:
        return
    if not row:
        return
    try:
        sheets = (json.loads(row[0]) or {}).get("sheets", [])
    except Exception:
        return
    for legacy_sheet in sheets:
        month = str(legacy_sheet.get("month") or "")
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
            continue
        status = legacy_sheet.get("status") if legacy_sheet.get("status") in {"draft", "confirmed", "paid"} else "draft"
        sheet = PayrollSheets(month=month, status=status, currency="CNY")
        db.add(sheet)
        await db.flush()
        for old in legacy_sheet.get("rows", []):
            account = str(old.get("alipay") or "").strip()
            item = PayrollItems(
                sheet_id=sheet.id, employee_name=str(old.get("name") or "未命名员工"), department=old.get("department"), hire_date=old.get("entryDate"),
                payment_method="alipay", payment_account_encrypted=encrypt_text(account) if account else None,
                payment_account_last4=account[-4:] if account else None,
                base_salary=old.get("baseSalary") or 0, fixed_performance=old.get("fixedPerformance") or 0,
                commission=old.get("commission") or 0, allowance=old.get("allowance") or 0,
                absence_deduction=old.get("absenceDeduction") or 0,
                performance_deduction=(old.get("performanceDeduction") or 0) + (old.get("fullAttendanceDeduction") or 0),
                other_deduction=old.get("otherDeduction") or 0, notes=old.get("notes"), payment_status="paid" if status == "paid" else "pending",
            )
            db.add(item)
        await _audit(db, sheet, user, "legacy_import", reason="从旧工资表配置自动迁移")
    await db.commit()


@router.get("")
async def get_payroll(month: str = Query(...), current_user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    _ensure_role(current_user)
    month = _valid_month(month)
    await _migrate_legacy_once(db, current_user)
    sheet = await _get_or_create_sheet(db, month)
    await db.commit()
    rows = (await db.execute(select(PayrollItems).where(PayrollItems.sheet_id == sheet.id).order_by(PayrollItems.id))).scalars().all()
    items = [_item_payload(row) for row in rows]
    return {"sheet": {"id": sheet.id, "month": sheet.month, "status": sheet.status, "currency": sheet.currency, "updated_at": sheet.updated_at, "reopen_reason": sheet.reopen_reason}, "items": items, "totals": {"gross": round(sum(i["gross_amount"] for i in items), 2), "deductions": round(sum(i["deduction_amount"] for i in items), 2), "net": round(sum(i["net_amount"] for i in items), 2)}}


@router.get("/summary")
async def get_payroll_summary(current_user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    _ensure_role(current_user)
    rows = (await db.execute(select(PayrollSheets).order_by(PayrollSheets.month.desc()).limit(12))).scalars().all()
    return {"items": [{"month": row.month, "status": row.status, "currency": row.currency} for row in rows], "pending_count": sum(row.status != "paid" for row in rows)}


@router.get("/employees")
async def get_payroll_employees(current_user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    _ensure_role(current_user)
    rows = (await db.execute(select(Employees).where(Employees.status.in_(["active", "probation"])).order_by(Employees.name))).scalars().all()
    return [{"id": row.id, "name": row.name, "employee_code": row.employee_code, "department": row.department, "hire_date": row.hire_date} for row in rows]


@router.get("/reports")
async def get_payroll_reports(
    year: int = Query(..., ge=2020, le=2100),
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return read-only payroll analysis without posting anything to Finance."""
    _ensure_role(current_user)
    sheets = (
        await db.execute(
            select(PayrollSheets)
            .where(PayrollSheets.month.like(f"{year}-%"))
            .order_by(PayrollSheets.month)
        )
    ).scalars().all()
    sheet_by_id = {row.id: row for row in sheets}
    items = []
    if sheet_by_id:
        items = (
            await db.execute(
                select(PayrollItems)
                .where(PayrollItems.sheet_id.in_(sheet_by_id))
                .order_by(PayrollItems.sheet_id, PayrollItems.employee_name)
            )
        ).scalars().all()

    def empty_bucket() -> dict:
        return {
            "gross": 0.0,
            "fixed": 0.0,
            "variable": 0.0,
            "deductions": 0.0,
            "net": 0.0,
            "paid_amount": 0.0,
            "pending_amount": 0.0,
            "employee_keys": set(),
        }

    monthly = {
        f"{year}-{number:02d}": {
            "month": f"{year}-{number:02d}",
            "status": "none",
            **empty_bucket(),
        }
        for number in range(1, 13)
    }
    for sheet in sheets:
        monthly[sheet.month]["status"] = sheet.status

    departments = defaultdict(empty_bucket)
    employees: dict[str, dict] = {}
    payment_statuses = {
        status: {"status": status, "count": 0, "amount": 0.0}
        for status in PAYMENT_STATUS_ORDER
    }
    total = empty_bucket()

    for item in items:
        sheet = sheet_by_id[item.sheet_id]
        employee_key = f"id:{item.employee_id}" if item.employee_id else f"legacy:{item.employee_code or ''}:{item.employee_name}"
        department = item.department or "未设置部门"
        gross, deductions, net = _amounts(item)
        fixed = float(item.base_salary or 0) + float(item.fixed_performance or 0)
        variable = sum(float(getattr(item, name) or 0) for name in ("commission", "bonus", "allowance", "reimbursement"))
        paid_amount = net if item.payment_status == "paid" else 0.0
        pending_amount = 0.0 if item.payment_status == "paid" else net

        for bucket in (monthly[sheet.month], departments[department], total):
            bucket["gross"] += gross
            bucket["fixed"] += fixed
            bucket["variable"] += variable
            bucket["deductions"] += deductions
            bucket["net"] += net
            bucket["paid_amount"] += paid_amount
            bucket["pending_amount"] += pending_amount
            bucket["employee_keys"].add(employee_key)

        payment_bucket = payment_statuses[item.payment_status]
        payment_bucket["count"] += 1
        payment_bucket["amount"] += net

        employee = employees.setdefault(
            employee_key,
            {
                "employee_id": item.employee_id,
                "employee_code": item.employee_code,
                "employee_name": item.employee_name,
                "department": department,
                "months": set(),
                "base_salary": 0.0,
                "fixed_performance": 0.0,
                "commission": 0.0,
                "bonus": 0.0,
                "allowance": 0.0,
                "reimbursement": 0.0,
                "gross": 0.0,
                "deductions": 0.0,
                "net": 0.0,
                "paid_amount": 0.0,
                "pending_amount": 0.0,
                "latest_month": "",
                "latest_payment_status": "pending",
            },
        )
        employee["months"].add(sheet.month)
        for field in ("base_salary", "fixed_performance", "commission", "bonus", "allowance", "reimbursement"):
            employee[field] += float(getattr(item, field) or 0)
        employee["gross"] += gross
        employee["deductions"] += deductions
        employee["net"] += net
        employee["paid_amount"] += paid_amount
        employee["pending_amount"] += pending_amount
        if sheet.month >= employee["latest_month"]:
            employee["latest_month"] = sheet.month
            employee["latest_payment_status"] = item.payment_status

    def finish_bucket(bucket: dict) -> dict:
        result = {
            key: round(float(bucket[key]), 2)
            for key in ("gross", "fixed", "variable", "deductions", "net", "paid_amount", "pending_amount")
        }
        result["headcount"] = len(bucket["employee_keys"])
        return result

    monthly_rows = []
    for month_key in sorted(monthly):
        bucket = monthly[month_key]
        monthly_rows.append({"month": month_key, "status": bucket["status"], **finish_bucket(bucket)})

    department_rows = [
        {"department": name, **finish_bucket(bucket)}
        for name, bucket in departments.items()
    ]
    department_rows.sort(key=lambda row: (-row["net"], row["department"]))

    employee_rows = []
    for employee in employees.values():
        employee_rows.append({
            **{key: employee[key] for key in ("employee_id", "employee_code", "employee_name", "department", "latest_month", "latest_payment_status")},
            "months": len(employee["months"]),
            **{
                key: round(float(employee[key]), 2)
                for key in ("base_salary", "fixed_performance", "commission", "bonus", "allowance", "reimbursement", "gross", "deductions", "net", "paid_amount", "pending_amount")
            },
        })
    employee_rows.sort(key=lambda row: (row["employee_name"], row["employee_code"] or ""))

    total_result = finish_bucket(total)
    active_months = sum(row["headcount"] > 0 for row in monthly_rows)
    total_result.update({
        "active_months": active_months,
        "average_monthly": round(total_result["net"] / active_months, 2) if active_months else 0,
        "average_per_employee": round(total_result["net"] / total_result["headcount"], 2) if total_result["headcount"] else 0,
        "variable_ratio": round(total_result["variable"] / total_result["gross"] * 100, 1) if total_result["gross"] else 0,
    })

    return {
        "year": year,
        "currency": "CNY",
        "independent_accounting": True,
        "generated_at": datetime.now(timezone.utc),
        "has_data": bool(items),
        "totals": total_result,
        "monthly": monthly_rows,
        "departments": department_rows,
        "employees": employee_rows,
        "payment_statuses": [
            {**row, "amount": round(float(row["amount"]), 2)}
            for row in payment_statuses.values()
            if row["count"]
        ],
    }


@router.post("/{month}/items")
async def create_payroll_item(month: str, payload: PayrollItemInput, current_user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    _ensure_role(current_user); month = _valid_month(month)
    sheet = await _get_or_create_sheet(db, month)
    if sheet.status == "paid": raise HTTPException(status_code=409, detail="已发放工资表已锁定，请由管理员填写原因后重新打开")
    values = payload.model_dump(exclude={"payment_account"})
    if payload.employee_id:
        employee = (await db.execute(select(Employees).where(Employees.id == payload.employee_id))).scalar_one_or_none()
        if not employee: raise HTTPException(status_code=404, detail="员工不存在")
        values.update(employee_name=employee.name, employee_code=employee.employee_code, department=employee.department, hire_date=employee.hire_date)
    account = (payload.payment_account or "").strip()
    item = PayrollItems(sheet_id=sheet.id, **values, payment_account_encrypted=encrypt_text(account) if account else None, payment_account_last4=account[-4:] if account else None)
    db.add(item)
    try:
        await db.flush()
    except Exception:
        await db.rollback(); raise HTTPException(status_code=409, detail="该员工已在本月工资表中")
    await _audit(db, sheet, current_user, "item_created", item)
    await db.commit(); await db.refresh(item)
    return _item_payload(item)


@router.put("/{month}/items/{item_id}")
async def update_payroll_item(month: str, item_id: int, payload: PayrollItemInput, current_user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    _ensure_role(current_user); month = _valid_month(month)
    sheet = (await db.execute(select(PayrollSheets).where(PayrollSheets.month == month))).scalar_one_or_none()
    if not sheet: raise HTTPException(status_code=404, detail="工资表不存在")
    if sheet.status == "paid": raise HTTPException(status_code=409, detail="已发放工资表已锁定，请由管理员填写原因后重新打开")
    item = (await db.execute(select(PayrollItems).where(PayrollItems.id == item_id, PayrollItems.sheet_id == sheet.id))).scalar_one_or_none()
    if not item: raise HTTPException(status_code=404, detail="工资明细不存在")
    values = payload.model_dump(exclude={"payment_account"})
    if payload.employee_id:
        employee = (await db.execute(select(Employees).where(Employees.id == payload.employee_id))).scalar_one_or_none()
        if not employee: raise HTTPException(status_code=404, detail="员工不存在")
        values.update(employee_name=employee.name, employee_code=employee.employee_code, department=employee.department, hire_date=employee.hire_date)
    for key, value in values.items(): setattr(item, key, value)
    account = (payload.payment_account or "").strip()
    if account:
        item.payment_account_encrypted = encrypt_text(account); item.payment_account_last4 = account[-4:]
    await _audit(db, sheet, current_user, "item_updated", item)
    await db.commit(); await db.refresh(item)
    return _item_payload(item)


@router.delete("/{month}/items/{item_id}")
async def delete_payroll_item(month: str, item_id: int, current_user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    _ensure_role(current_user); month = _valid_month(month)
    sheet = (await db.execute(select(PayrollSheets).where(PayrollSheets.month == month))).scalar_one_or_none()
    if not sheet: raise HTTPException(status_code=404, detail="工资表不存在")
    if sheet.status != "draft": raise HTTPException(status_code=409, detail="只有草稿工资表可以删除明细")
    item = (await db.execute(select(PayrollItems).where(PayrollItems.id == item_id, PayrollItems.sheet_id == sheet.id))).scalar_one_or_none()
    if not item: raise HTTPException(status_code=404, detail="工资明细不存在")
    await _audit(db, sheet, current_user, "item_deleted", item); await db.delete(item); await db.commit()
    return {"message": "工资明细已删除"}


@router.post("/{month}/transition")
async def transition_payroll(month: str, payload: PayrollTransition, current_user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    role = _ensure_role(current_user); month = _valid_month(month)
    sheet = (await db.execute(select(PayrollSheets).where(PayrollSheets.month == month))).scalar_one_or_none()
    if not sheet: raise HTTPException(status_code=404, detail="工资表不存在")
    now = datetime.now(timezone.utc); actor = _actor(current_user)
    if payload.action == "confirm":
        if role not in ADMIN_ROLES: raise HTTPException(status_code=403, detail="工资表必须由管理员确认")
        if sheet.status != "draft": raise HTTPException(status_code=409, detail="只有草稿可以确认")
        count = (await db.execute(select(func.count(PayrollItems.id)).where(PayrollItems.sheet_id == sheet.id))).scalar_one()
        if not count: raise HTTPException(status_code=409, detail="工资表没有员工明细")
        sheet.status = "confirmed"; sheet.confirmed_at = now; sheet.confirmed_by = actor
    elif payload.action == "mark_paid":
        if sheet.status != "confirmed": raise HTTPException(status_code=409, detail="工资表需要先由管理员确认")
        pending = (await db.execute(select(func.count(PayrollItems.id)).where(PayrollItems.sheet_id == sheet.id, PayrollItems.payment_status != "paid"))).scalar_one()
        if pending: raise HTTPException(status_code=409, detail=f"还有 {pending} 条工资明细未标记为已发放")
        sheet.status = "paid"; sheet.paid_at = now; sheet.paid_by = actor
    elif payload.action == "reopen":
        if role not in ADMIN_ROLES: raise HTTPException(status_code=403, detail="只有管理员可以重新打开")
        if sheet.status != "paid": raise HTTPException(status_code=409, detail="只有已发放工资表可以重新打开")
        if not (payload.reason or "").strip(): raise HTTPException(status_code=400, detail="重新打开必须填写原因")
        sheet.status = "confirmed"; sheet.reopened_at = now; sheet.reopened_by = actor; sheet.reopen_reason = payload.reason.strip()
    else:
        raise HTTPException(status_code=400, detail="无效的流程操作")
    await _audit(db, sheet, current_user, payload.action, reason=payload.reason); await db.commit()
    return {"month": sheet.month, "status": sheet.status, "message": "工资表状态已更新"}


@router.get("/{month}/audit")
async def get_payroll_audit(month: str, current_user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    _ensure_role(current_user); month = _valid_month(month)
    sheet = (await db.execute(select(PayrollSheets).where(PayrollSheets.month == month))).scalar_one_or_none()
    if not sheet: return []
    logs = (await db.execute(select(PayrollAuditLogs).where(PayrollAuditLogs.sheet_id == sheet.id).order_by(PayrollAuditLogs.id.desc()).limit(100))).scalars().all()
    return [{"id": row.id, "action": row.action, "actor_name": row.actor_name, "actor_role": row.actor_role, "reason": row.reason, "created_at": row.created_at} for row in logs]
