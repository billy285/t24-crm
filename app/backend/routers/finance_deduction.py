import csv
import io
import logging
from datetime import datetime, date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from pydantic import BaseModel, Field, validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from core.database import get_db
from dependencies.auth import get_current_user
from schemas.auth import UserResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/deductions-monthly", tags=["finance-deductions"])

# ---- Schemas ----
class MonthlyDeductionRateBase(BaseModel):
    year_month: str = Field(..., description="YYYY-MM")
    rate: float = Field(..., ge=0.0, le=1.0, description="0.15 means 15%")

    @validator("year_month")
    def validate_year_month(cls, v: str):
        try:
            datetime.strptime(v + "-01", "%Y-%m-%d")
        except Exception:
            raise ValueError("year_month must be YYYY-MM")
        return v

class MonthlyDeductionRateCreate(MonthlyDeductionRateBase):
    pass

class MonthlyDeductionRateUpdate(BaseModel):
    rate: float = Field(..., ge=0.0, le=1.0)

class MonthlyDeductionRateResponse(BaseModel):
    year_month: str
    rate: float
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class DefaultDeductionResponse(BaseModel):
    rate: float

class ImportResult(BaseModel):
    total: int
    inserted: int
    updated: int
    skipped: int


# ---- Table helpers ----
CREATE_RATES_SQL = """
CREATE TABLE IF NOT EXISTS monthly_deduction_rates (
  id SERIAL PRIMARY KEY,
  year_month DATE UNIQUE NOT NULL,
  rate NUMERIC(5,4) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

CREATE_DEFAULT_SQL = """
CREATE TABLE IF NOT EXISTS monthly_deduction_defaults (
  id SERIAL PRIMARY KEY,
  rate NUMERIC(5,4) NOT NULL DEFAULT 0.15,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

CREATE_AUDIT_SQL = """
CREATE TABLE IF NOT EXISTS monthly_deduction_audits (
  id SERIAL PRIMARY KEY,
  action TEXT NOT NULL,
  actor_id BIGINT,
  before_json JSONB,
  after_json JSONB,
  at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

def ym_to_date(ym: str) -> str:
    return f"{ym}-01"

def date_to_ym(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"

async def ensure_tables(session: AsyncSession):
    await session.execute(text(CREATE_RATES_SQL))
    await session.execute(text(CREATE_DEFAULT_SQL))
    await session.execute(text(CREATE_AUDIT_SQL))

def is_admin_user(u: UserResponse) -> bool:
    # Assume UserResponse has role or is_admin
    try:
        if getattr(u, "is_admin", False):
            return True
        role = getattr(u, "role", None) or getattr(u, "user_role", None)
        return str(role).lower() in ("admin", "super_admin")
    except Exception:
        return False

async def write_audit(session: AsyncSession, action: str, actor_id: Optional[int], before: Optional[dict], after: Optional[dict]):
    try:
        before_json = before and str(before).replace("'", '"') or "null"
        after_json = after and str(after).replace("'", '"') or "null"
    except Exception:
        before_json = "null"
        after_json = "null"
    await session.execute(
        text("INSERT INTO monthly_deduction_audits (action, actor_id, before_json, after_json) VALUES (:a, :uid, CAST(:b AS JSONB), CAST(:c AS JSONB))"),
        {"a": action, "uid": actor_id, "b": before_json, "c": after_json},
    )

# ---- CRUD ----
@router.get("/", response_model=List[MonthlyDeductionRateResponse])
async def list_deductions(
    start: Optional[str] = Query(None, description="YYYY-MM"),
    end: Optional[str] = Query(None, description="YYYY-MM"),
    db: AsyncSession = Depends(get_db),
):
    await ensure_tables(db)
    where = ""
    params = {}
    if start:
        where += " AND year_month >= :start"
        params["start"] = ym_to_date(start)
    if end:
        where += " AND year_month <= :end"
        params["end"] = ym_to_date(end)
    sql = text(f"SELECT year_month, rate, created_at, updated_at FROM monthly_deduction_rates WHERE 1=1 {where} ORDER BY year_month ASC")
    res = await db.execute(sql, params)
    rows = res.mappings().all()
    result: List[MonthlyDeductionRateResponse] = []
    for r in rows:
        ym = r["year_month"]
        if isinstance(ym, date):
            ym_str = date_to_ym(ym)
        else:
            ym_str = str(ym)[:7]
        result.append(MonthlyDeductionRateResponse(
            year_month=ym_str,
            rate=float(r["rate"]),
            created_at=r.get("created_at"),
            updated_at=r.get("updated_at"),
        ))
    return result


@router.get("/{ym}", response_model=MonthlyDeductionRateResponse)
async def get_deduction(ym: str, db: AsyncSession = Depends(get_db)):
    await ensure_tables(db)
    res = await db.execute(text("SELECT year_month, rate, created_at, updated_at FROM monthly_deduction_rates WHERE year_month = :ym"), {"ym": ym_to_date(ym)})
    r = res.mappings().first()
    if not r:
        raise HTTPException(status_code=404, detail="Not found")
    ym_str = date_to_ym(r["year_month"]) if isinstance(r["year_month"], date) else str(r["year_month"])[:7]
    return MonthlyDeductionRateResponse(year_month=ym_str, rate=float(r["rate"]), created_at=r.get("created_at"), updated_at=r.get("updated_at"))


@router.post("/", response_model=MonthlyDeductionRateResponse)
async def create_deduction(
    payload: MonthlyDeductionRateCreate,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await ensure_tables(db)
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Admin only")
    before = None
    try:
        res = await db.execute(text("""
            INSERT INTO monthly_deduction_rates (year_month, rate)
            VALUES (:ym, :rate)
            ON CONFLICT (year_month) DO UPDATE SET rate = EXCLUDED.rate, updated_at = NOW()
            RETURNING year_month, rate, created_at, updated_at
        """), {"ym": ym_to_date(payload.year_month), "rate": payload.rate})
        row = res.mappings().first()
        after = {"year_month": payload.year_month, "rate": payload.rate}
        await write_audit(db, "create_or_upsert", getattr(current_user, "id", None), before, after)
        await db.commit()
        return MonthlyDeductionRateResponse(
            year_month=date_to_ym(row["year_month"]) if isinstance(row["year_month"], date) else str(row["year_month"])[:7],
            rate=float(row["rate"]),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )
    except Exception as e:
        await db.rollback()
        logger.error(f"Create deduction failed: {e}")
        raise HTTPException(status_code=500, detail="Create failed")


@router.put("/{ym}", response_model=MonthlyDeductionRateResponse)
async def update_deduction(
    ym: str,
    payload: MonthlyDeductionRateUpdate,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await ensure_tables(db)
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Admin only")
    # before
    res0 = await db.execute(text("SELECT year_month, rate FROM monthly_deduction_rates WHERE year_month = :ym"), {"ym": ym_to_date(ym)})
    before_row = res0.mappings().first()
    before = {"year_month": ym, "rate": float(before_row["rate"])} if before_row else None

    res = await db.execute(text("""
        UPDATE monthly_deduction_rates SET rate = :rate, updated_at = NOW()
        WHERE year_month = :ym
        RETURNING year_month, rate, created_at, updated_at
    """), {"rate": payload.rate, "ym": ym_to_date(ym)})
    row = res.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    after = {"year_month": ym, "rate": float(row["rate"])}
    await write_audit(db, "update", getattr(current_user, "id", None), before, after)
    await db.commit()
    return MonthlyDeductionRateResponse(
        year_month=date_to_ym(row["year_month"]) if isinstance(row["year_month"], date) else str(row["year_month"])[:7],
        rate=float(row["rate"]),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


@router.delete("/{ym}")
async def delete_deduction(
    ym: str,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await ensure_tables(db)
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Admin only")
    res0 = await db.execute(text("SELECT year_month, rate FROM monthly_deduction_rates WHERE year_month = :ym"), {"ym": ym_to_date(ym)})
    before_row = res0.mappings().first()
    before = {"year_month": ym, "rate": float(before_row["rate"])} if before_row else None
    await db.execute(text("DELETE FROM monthly_deduction_rates WHERE year_month = :ym"), {"ym": ym_to_date(ym)})
    await write_audit(db, "delete", getattr(current_user, "id", None), before, None)
    await db.commit()
    return {"success": True}


# ---- Default rate ----
@router.get("/default", response_model=DefaultDeductionResponse)
async def get_default_deduction(db: AsyncSession = Depends(get_db)):
    await ensure_tables(db)
    res = await db.execute(text("SELECT rate FROM monthly_deduction_defaults ORDER BY id DESC LIMIT 1"))
    row = res.fetchone()
    rate = float(row[0]) if row else 0.15
    return DefaultDeductionResponse(rate=rate)


@router.put("/default", response_model=DefaultDeductionResponse)
async def update_default_deduction(
    payload: DefaultDeductionResponse,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await ensure_tables(db)
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Admin only")
    if payload.rate < 0 or payload.rate > 1:
        raise HTTPException(status_code=400, detail="Rate must be in [0,1]")
    # before
    res0 = await db.execute(text("SELECT rate FROM monthly_deduction_defaults ORDER BY id DESC LIMIT 1"))
    before_row = res0.fetchone()
    before = {"rate": float(before_row[0])} if before_row else None
    try:
        res = await db.execute(text("INSERT INTO monthly_deduction_defaults (rate) VALUES (:r) RETURNING rate"), {"r": payload.rate})
        row = res.fetchone()
        await write_audit(db, "default_update", getattr(current_user, "id", None), before, {"rate": float(row[0])})
        await db.commit()
        return DefaultDeductionResponse(rate=float(row[0]))
    except Exception:
        await db.rollback()
        raise


# ---- CSV import ----
@router.post("/import", response_model=ImportResult)
async def import_monthly_deductions(
    file: UploadFile = File(...),
    overwrite: bool = Form(False),
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await ensure_tables(db)
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Admin only")

    content = await file.read()
    text_stream = io.StringIO(content.decode("utf-8-sig"))
    reader = csv.DictReader(text_stream)
    total = inserted = updated = skipped = 0
    for row in reader:
        total += 1
        ym = (row.get("year_month") or "").strip()[:7]
        try:
            datetime.strptime(ym + "-01", "%Y-%m-%d")
        except Exception:
            skipped += 1
            continue
        try:
            rate = float(row.get("rate"))
        except Exception:
            skipped += 1
            continue

        # upsert logic depending on overwrite
        existing = await db.execute(text("SELECT rate FROM monthly_deduction_rates WHERE year_month=:ym"), {"ym": ym_to_date(ym)})
        ex = existing.fetchone()
        if ex:
            if overwrite:
                await db.execute(text("UPDATE monthly_deduction_rates SET rate=:r, updated_at=NOW() WHERE year_month=:ym"), {"r": rate, "ym": ym_to_date(ym)})
                updated += 1
                await write_audit(db, "import_update", getattr(current_user, "id", None), {"year_month": ym, "rate": float(ex[0])}, {"year_month": ym, "rate": rate})
            else:
                skipped += 1
        else:
            await db.execute(text("INSERT INTO monthly_deduction_rates (year_month, rate) VALUES (:ym, :r)"), {"ym": ym_to_date(ym), "r": rate})
            inserted += 1
            await write_audit(db, "import_create", getattr(current_user, "id", None), None, {"year_month": ym, "rate": rate})

    try:
        await db.commit()
        return ImportResult(total=total, inserted=inserted, updated=updated, skipped=skipped)
    except Exception:
        await db.rollback()
        raise
