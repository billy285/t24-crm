"""Allocate customer codes across all intake paths inside the caller's transaction."""
import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from models.customers import Customers
from routers.app_config import DEFAULT_APP_CONFIGS
from services.schema_readiness import tables_available
from services.sales_workflow_locks import SALES_WORKFLOW_ADVISORY_KEY


async def _lock_code_writers(db: AsyncSession) -> None:
    dialect = db.get_bind().dialect.name
    if dialect == "sqlite":
        # Reserve the writer without updating any historical customer.
        await db.execute(text("UPDATE customers SET id = id WHERE 0"))
    elif dialect == "postgresql":
        # Sales conversion already holds this lock. Reusing it avoids lock inversion.
        await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": SALES_WORKFLOW_ADVISORY_KEY})
    elif dialect in {"mysql", "mariadb"}:
        # A stable primary-key row also serializes the first two customers of an empty CRM.
        await db.execute(text("""INSERT INTO app_settings (config_key, value_json)
            VALUES ('_customer_code_lock', 'null') ON DUPLICATE KEY UPDATE config_key = config_key"""))
    else:
        raise HTTPException(503, "当前数据库暂不支持安全分配客户编号")


async def allocate_customer_code(
    db: AsyncSession, *, industry: str | None, requested_code: str | None = None, customer_id: int | None = None,
) -> str:
    await _lock_code_writers(db)
    manual = (requested_code or "").strip()
    if manual:
        query = select(Customers.id).where(func.trim(Customers.customer_code) == manual)
        if customer_id is not None:
            query = query.where(Customers.id != customer_id)
        if (await db.scalar(query.limit(1).with_for_update())) is not None:
            raise HTTPException(409, "该客户编号已被使用，请更换编号或留空自动生成")
        return manual

    defaults = DEFAULT_APP_CONFIGS["customer_code_settings"]
    config = {}
    if await tables_available(db, {"app_settings"}):
        value = await db.scalar(text("SELECT value_json FROM app_settings WHERE config_key = 'customer_code_settings'"))
        try:
            config = json.loads(value) if value else {}
        except (ValueError, TypeError):
            pass
    settings = {**defaults, **(config if isinstance(config, dict) else {})}
    prefix = settings["defaultPrefix"] or defaults["defaultPrefix"]
    if settings["useIndustryPrefix"] and industry:
        for entry in settings["industryPrefixes"] or defaults["industryPrefixes"]:
            if isinstance(entry, dict) and entry.get("industry") == industry and entry.get("prefix"):
                prefix = entry["prefix"]
                break
    separator = settings["separator"]
    year = datetime.now(ZoneInfo("Asia/Shanghai")).year if settings["includeYear"] else ""
    prefix = f"{prefix}{separator}{year}{separator}"
    digits = settings["digitCount"]
    if type(digits) is not int or not 2 <= digits <= 6:
        digits = defaults["digitCount"]
    normalized_code = func.trim(Customers.customer_code)
    statement = select(normalized_code).where(normalized_code.startswith(prefix, autoescape=True)).with_for_update()
    maximum = 0
    for code in await db.scalars(statement):
        # Manual references and old date/UUID sales codes use a different format.
        suffix = code[len(prefix):] if code.startswith(prefix) else ""
        if re.fullmatch(r"[0-9]+", suffix) and len(suffix) < 100:
            maximum = max(maximum, int(suffix))
    return f"{prefix}{maximum + 1:0{digits}d}"
