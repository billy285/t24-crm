"""Owner-only endpoints for the isolated, manual CNY personal ledger."""
from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies.private_workspace import PrivateOwner, require_private_owner
from schemas.private_personal_finance import (
    AccountCreate, AccountPatch, BootstrapInput, BudgetPatch, CategoryCreate, CategoryPatch, CategoryReorder, DebtCreate,
    DebtPatch, EntryCreate, EntryKind, EntryPatch, GoalCreate, GoalPatch, PlanCreate, PlanPatch, PlanPay,
)
from services import private_personal_finance as service
from services.private_workspace import get_private_db


async def no_store(response: Response):
    response.headers.update({"Cache-Control": "no-store", "Pragma": "no-cache"})


router = APIRouter(prefix="/api/v1/private-workspace/personal-finance", tags=["private-personal-finance"],
                   dependencies=[Depends(no_store), Depends(require_private_owner)])


@router.get("/state")
async def state(owner: PrivateOwner = Depends(require_private_owner), db: AsyncSession = Depends(get_private_db)):
    async with service.read_snapshot(db):
        return await service.state(db, owner.employee_id)


@router.post("/bootstrap")
async def bootstrap(value: BootstrapInput, owner: PrivateOwner = Depends(require_private_owner), db: AsyncSession = Depends(get_private_db)):
    return await service.bootstrap(db, owner.employee_id, value)


@router.post("/categories", status_code=201)
async def create_category(value: CategoryCreate, owner: PrivateOwner = Depends(require_private_owner), db: AsyncSession = Depends(get_private_db)):
    return await service.create_category(db, owner.employee_id, value)


@router.patch("/categories/{identity}")
async def patch_category(identity: UUID, value: CategoryPatch, owner: PrivateOwner = Depends(require_private_owner), db: AsyncSession = Depends(get_private_db)):
    return await service.patch_category(db, owner.employee_id, identity, value)


@router.post("/categories/reorder")
async def reorder_categories(value: CategoryReorder, owner: PrivateOwner = Depends(require_private_owner), db: AsyncSession = Depends(get_private_db)):
    return await service.reorder_categories(db, owner.employee_id, value)


@router.delete("/categories/{identity}")
async def delete_category(identity: UUID, owner: PrivateOwner = Depends(require_private_owner), db: AsyncSession = Depends(get_private_db)):
    return await service.delete_category(db, owner.employee_id, identity)


@router.post("/accounts", status_code=201)
async def create_account(value: AccountCreate, owner: PrivateOwner = Depends(require_private_owner), db: AsyncSession = Depends(get_private_db)):
    return await service.create_account(db, owner.employee_id, value)


@router.patch("/accounts/{identity}")
async def patch_account(identity: UUID, value: AccountPatch, owner: PrivateOwner = Depends(require_private_owner), db: AsyncSession = Depends(get_private_db)):
    return await service.patch_account(db, owner.employee_id, identity, value)


@router.post("/debts", status_code=201)
async def create_debt(value: DebtCreate, owner: PrivateOwner = Depends(require_private_owner), db: AsyncSession = Depends(get_private_db)):
    return await service.create_debt(db, owner.employee_id, value)


@router.patch("/debts/{identity}")
async def patch_debt(identity: UUID, value: DebtPatch, owner: PrivateOwner = Depends(require_private_owner), db: AsyncSession = Depends(get_private_db)):
    return await service.patch_debt(db, owner.employee_id, identity, value)


@router.post("/plans", status_code=201)
async def create_plan(value: PlanCreate, owner: PrivateOwner = Depends(require_private_owner), db: AsyncSession = Depends(get_private_db)):
    return await service.create_plan(db, owner.employee_id, value)


@router.patch("/plans/{identity}")
async def patch_plan(identity: UUID, value: PlanPatch, owner: PrivateOwner = Depends(require_private_owner), db: AsyncSession = Depends(get_private_db)):
    return await service.patch_plan(db, owner.employee_id, identity, value)


@router.post("/plans/{identity}/pay")
async def pay_plan(identity: UUID, value: PlanPay, owner: PrivateOwner = Depends(require_private_owner), db: AsyncSession = Depends(get_private_db)):
    return await service.pay_plan(db, owner.employee_id, identity, value)


@router.post("/goals", status_code=201)
async def create_goal(value: GoalCreate, owner: PrivateOwner = Depends(require_private_owner), db: AsyncSession = Depends(get_private_db)):
    return await service.create_goal(db, owner.employee_id, value)


@router.patch("/goals/{identity}")
async def patch_goal(identity: UUID, value: GoalPatch, owner: PrivateOwner = Depends(require_private_owner), db: AsyncSession = Depends(get_private_db)):
    return await service.patch_goal(db, owner.employee_id, identity, value)


@router.patch("/budget")
async def budget(value: BudgetPatch, owner: PrivateOwner = Depends(require_private_owner), db: AsyncSession = Depends(get_private_db)):
    return await service.patch_budget(db, owner.employee_id, value)


@router.post("/entries", status_code=201)
async def create_entry(value: EntryCreate, owner: PrivateOwner = Depends(require_private_owner), db: AsyncSession = Depends(get_private_db)):
    return await service.create_entry(db, owner.employee_id, value)


@router.get("/entries")
async def entries(start_date: date, end_date: date, category_id: UUID | None = None,
                  kind: EntryKind | None = None, status: Literal["all", "active", "void"] = "active",
                  page: int = Query(default=1, ge=1, le=100000), page_size: int = Query(default=30, ge=1, le=100),
                  owner: PrivateOwner = Depends(require_private_owner), db: AsyncSession = Depends(get_private_db)):
    async with service.read_snapshot(db):
        return await service.list_entries(db, owner.employee_id, start_date, end_date, category_id, kind, status, page, page_size)


@router.patch("/entries/{identity}")
async def patch_entry(identity: UUID, value: EntryPatch, owner: PrivateOwner = Depends(require_private_owner), db: AsyncSession = Depends(get_private_db)):
    return await service.patch_entry(db, owner.employee_id, identity, value)


@router.post("/entries/{identity}/void")
async def void_entry(identity: UUID, owner: PrivateOwner = Depends(require_private_owner), db: AsyncSession = Depends(get_private_db)):
    return await service.entry_status(db, owner.employee_id, identity, "void")


@router.post("/entries/{identity}/restore")
async def restore_entry(identity: UUID, owner: PrivateOwner = Depends(require_private_owner), db: AsyncSession = Depends(get_private_db)):
    return await service.entry_status(db, owner.employee_id, identity, "active")


@router.get("/report")
async def report(start_date: date, end_date: date, owner: PrivateOwner = Depends(require_private_owner), db: AsyncSession = Depends(get_private_db)):
    async with service.read_snapshot(db):
        return await service.report(db, owner.employee_id, start_date, end_date)


@router.get("/requests/{client_request_id}")
async def request_status(client_request_id: UUID, owner: PrivateOwner = Depends(require_private_owner), db: AsyncSession = Depends(get_private_db)):
    async with service.read_snapshot(db):
        return await service.request_status(db, owner.employee_id, client_request_id)
