"""Private storage and sync orchestration; never writes to the CRM database."""
import asyncio
import base64
import hashlib
import importlib
import json
import os
import re
import secrets
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from sqlalchemy import and_, case, false, func, or_, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from core.config import settings
from dependencies.private_workspace import configured_owner_ids, valid_private_owner
from models.private_workspace import (
    PrivateConnection, PrivateItem, PrivatePreferences, PrivateSyncRun, PrivateWorkspaceBase, utcnow,
)
from services.private_mail_relevance import BUCKETS, BUCKET_PRIORITY, classify_mail, gmail_preferences


SOURCE_IDS = ("gmail", "google_ads", "bofa", "stripe", "manual")
DEFAULT_PRIVATE_URL = "sqlite+aiosqlite:///./private-data/workspace.db"
_storage = None
_storage_lock = asyncio.Lock()
_SENSITIVE_KEY = re.compile(r"secret|token|credential|authorization|password|cookie|raw|body", re.I)
_SECRET_VALUE = re.compile(r"(?:[sr]k_(?:live|test)_\w+|ya29\.[\w.-]+|Bearer\s+\S+)", re.I)
_SOURCE_HOSTS = {
    "gmail": {"mail.google.com"},
    "bofa": {"mail.google.com", "www.bankofamerica.com", "secure.bankofamerica.com"},
    "google_ads": {"ads.google.com"},
    "stripe": {"dashboard.stripe.com"},
}


def providers():
    return importlib.import_module("services.private_workspace_providers")


def _provider_setup_message(source_id, error, fallback):
    # Expose only fixed setup guidance for this adapter. Never return provider
    # response bodies or arbitrary exception/public_message text.
    provider_error = importlib.import_module("services.private_workspace_providers").ProviderError
    messages = {
        "ads_project_not_approved": "Google Cloud 项目尚未获准读取正式广告账户，请在 Google Ads API 概览申请 Explorer 或更高访问级别后重新连接",
        "ads_account_changed": "广告账户配置与已授权账户不一致，请重新连接",
    }
    return messages.get(error.code, fallback) if source_id == "google_ads" and isinstance(error, provider_error) else fallback


def require_source(source_id: str, *, external=False) -> str:
    if source_id not in SOURCE_IDS or (external and source_id == "manual"):
        raise HTTPException(status_code=404, detail="未找到此来源")
    return source_id


def _sqlite_path(url):
    database = str(url.database or "")
    if database.startswith("file:"):
        database = database[5:].split("?", 1)[0]
    return Path(database).expanduser().resolve()


def resolve_private_database_url():
    try:
        private_url = make_url(os.getenv("PRIVATE_WORKSPACE_DATABASE_URL") or DEFAULT_PRIVATE_URL)
        business_url = make_url(settings.database_url)
    except Exception:
        raise HTTPException(status_code=503, detail="私人数据库配置无效") from None
    private_backend = private_url.get_backend_name()
    business_backend = business_url.get_backend_name()
    if private_backend not in {"sqlite", "postgresql"}:
        raise HTTPException(status_code=503, detail="私人数据库仅支持 SQLite 或 PostgreSQL")
    if private_backend == "sqlite":
        if not private_url.database or private_url.database == ":memory:" or private_url.query or str(private_url.database).startswith("file:"):
            raise HTTPException(status_code=503, detail="私人数据库需要独立的磁盘文件")
        private_path = _sqlite_path(private_url)
        if business_backend == "sqlite":
            business_path = _sqlite_path(business_url)
            same_file = private_path == business_path
            if private_path.exists() and business_path.exists():
                same_file = same_file or os.path.samefile(private_path, business_path)
            if same_file:
                raise HTTPException(status_code=503, detail="私人数据库不能使用客户管理系统数据库")
        return private_url.set(drivername="sqlite+aiosqlite", database=str(private_path))
    private_identity = ((private_url.host or "localhost").lower(), private_url.port or 5432, private_url.database)
    business_identity = ((business_url.host or "localhost").lower(), business_url.port or 5432, business_url.database)
    if business_backend == "postgresql" and private_identity == business_identity:
        raise HTTPException(status_code=503, detail="私人数据库不能使用客户管理系统数据库")
    # Query parameters can otherwise switch the effective PostgreSQL host/database.
    if any(key in private_url.query for key in ("host", "hostaddr", "port", "dbname", "database", "service")):
        raise HTTPException(status_code=503, detail="私人数据库不能使用连接目标覆盖参数")
    return private_url.set(drivername="postgresql+asyncpg")


def _prepare_private_sqlite_file(path: Path):
    parent = path.parent
    if not parent.exists():
        parent.mkdir(mode=0o700, parents=True)
        parent.chmod(0o700)
    # Never chmod an existing shared/business directory to make the configuration work.
    if not parent.is_dir() or stat.S_IMODE(parent.stat().st_mode) & 0o077:
        raise HTTPException(status_code=503, detail="私人数据库目录需要独立配置为仅本人可访问")
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise HTTPException(status_code=503, detail="私人数据库文件配置无效")
    descriptor = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    os.close(descriptor)
    path.chmod(0o600)


async def private_session_factory():
    global _storage
    url = resolve_private_database_url()
    identity = url.render_as_string(hide_password=False)
    async with _storage_lock:
        if _storage and _storage[0] == identity:
            return _storage[2]
        if _storage:
            await _storage[1].dispose()
            _storage = None
        if url.get_backend_name() == "sqlite":
            _prepare_private_sqlite_file(Path(url.database))
        engine = create_async_engine(url, poolclass=NullPool, echo=False)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(PrivateWorkspaceBase.metadata.create_all)
        except Exception:
            await engine.dispose()
            raise HTTPException(status_code=503, detail="私人数据库暂不可用") from None
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        _storage = (identity, engine, sessions)
        return sessions


async def get_private_db():
    sessions = await private_session_factory()
    async with sessions() as private_db:
        yield private_db


async def close_private_workspace_storage():
    global _storage
    async with _storage_lock:
        if _storage:
            await _storage[1].dispose()
            _storage = None


def encryption_configured() -> bool:
    value = (os.environ.get("PRIVATE_WORKSPACE_ENCRYPTION_KEY") or "").strip()
    return len(value) >= 32 and "replace-with" not in value.lower() and value.lower() not in {"x" * len(value), "change-me"}


def _cipher():
    if not encryption_configured():
        raise HTTPException(status_code=503, detail="私人空间凭据加密尚未配置")
    value = os.environ["PRIVATE_WORKSPACE_ENCRYPTION_KEY"].strip()
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(value.encode()).digest()))


def encrypt_credentials(credentials: dict) -> str:
    if not isinstance(credentials, dict) or not credentials:
        raise HTTPException(status_code=502, detail="来源没有返回有效授权")
    encoded = json.dumps(credentials, separators=(",", ":")).encode()
    if len(encoded) > 65536:
        raise HTTPException(status_code=502, detail="来源授权格式无效")
    return _cipher().encrypt(encoded).decode()


def decrypt_credentials(value: str) -> dict:
    try:
        result = json.loads(_cipher().decrypt(value.encode()))
    except (InvalidToken, ValueError, TypeError):
        raise HTTPException(status_code=503, detail="私人来源授权无法读取，请重新授权") from None
    if not isinstance(result, dict):
        raise HTTPException(status_code=503, detail="私人来源授权无效")
    return result


def safe_json(value, *, depth=0):
    if depth > 5:
        return None
    if isinstance(value, dict):
        return {str(key)[:80]: safe_json(item, depth=depth + 1) for key, item in list(value.items())[:50]
                if not _SENSITIVE_KEY.search(str(key))}
    if isinstance(value, list):
        return [safe_json(item, depth=depth + 1) for item in value[:50]]
    if isinstance(value, str):
        return _SECRET_VALUE.sub("[已隐藏]", value)[:1800]
    return value if value is None or isinstance(value, (bool, int, float)) else str(value)[:100]


def safe_source_url(source_id: str, value):
    if not value or source_id == "manual":
        return None
    try:
        parsed = urlsplit(str(value))
        if parsed.scheme != "https" or parsed.hostname not in _SOURCE_HOSTS.get(source_id, set()) or parsed.username or parsed.password or parsed.port not in {None, 443}:
            return None
        if _SENSITIVE_KEY.search(parsed.query) or _SECRET_VALUE.search(str(value)):
            return None
        return str(value)[:1800]
    except ValueError:
        return None


def safe_authorization_url(value):
    try:
        parsed = urlsplit(str(value))
        if parsed.scheme != "https" or parsed.hostname != "accounts.google.com" or parsed.username or parsed.password or parsed.port not in {None, 443} or parsed.fragment:
            raise ValueError()
        if parsed.path not in {"/o/oauth2/v2/auth", "/o/oauth2/auth"}:
            raise ValueError()
        parameters = dict(parse_qsl(parsed.query))
        if parameters.get("response_type") != "code" or not parameters.get("state"):
            raise ValueError()
        return str(value)
    except (ValueError, TypeError):
        raise HTTPException(status_code=502, detail="来源授权地址无效") from None


def _aware(value):
    if value is None or value == "":
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime):
        raise ValueError("invalid datetime")
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def item_response(row, stored_preferences=None):
    result = {
        "id": row.id, "source_id": row.source_id, "kind": row.kind,
        "title": row.local_title if row.local_title is not None else row.title,
        "summary": row.local_summary if row.local_summary is not None else row.summary,
        "status": row.status, "priority": row.priority, "amount_minor": row.amount_minor,
        "currency": row.currency, "occurred_at": _aware(row.occurred_at), "due_at": _aware(row.due_at),
        "source_url": safe_source_url(row.source_id, row.source_url), "evidence": safe_json(row.evidence),
        "action_status": row.action_status, "snoozed_until": _aware(row.snoozed_until),
    }
    if row.source_id == "gmail":
        # Local notes cannot turn untrusted provider metadata into confirmed facts.
        relevance = classify_mail({"id": row.id, "title": row.title, "summary": row.summary,
                                   "evidence": row.evidence}, stored_preferences)
        result["mail_relevance"] = relevance
        result["priority"] = BUCKET_PRIORITY[relevance["bucket"]]
    return result


async def connection_for(private_db, owner_id: str, source_id: str, *, create=False):
    require_source(source_id)
    row = (await private_db.execute(select(PrivateConnection).where(
        PrivateConnection.owner_id == owner_id, PrivateConnection.source_id == source_id,
    ).execution_options(populate_existing=True))).scalar_one_or_none()
    if not row and create:
        if private_db.bind.dialect.name == "sqlite":
            from sqlalchemy.dialects.sqlite import insert
        else:
            from sqlalchemy.dialects.postgresql import insert
        await private_db.execute(insert(PrivateConnection).values(
            id=str(uuid4()), owner_id=owner_id, source_id=source_id,
        ).on_conflict_do_nothing(index_elements=["owner_id", "source_id"]))
        row = (await private_db.execute(select(PrivateConnection).where(
            PrivateConnection.owner_id == owner_id, PrivateConnection.source_id == source_id,
        ).execution_options(populate_existing=True))).scalar_one()
    return row


def source_metadata(connection):
    stored = (connection.metadata_json or {}) if connection else {}
    allowed = {"coverage", "partial", "sync_window", "record_limit", "record_limit_per_resource",
               "resources", "mode", "bank_data_verification", "read_only_adapter", "api_version", "importance_source", "account_label", "ads_customer_id", "ads_snapshot"}
    result = safe_json({key: value for key, value in stored.items() if key in allowed})
    # Bounded records are never presented as account-level financial totals.
    result["aggregated_totals"] = False
    result["payouts_are_income"] = False
    return result


def source_response(descriptor, connection=None):
    source_id = descriptor["id"]
    missing = [str(value) for value in descriptor.get("missing_configuration", []) if re.fullmatch(r"[A-Z0-9_]+", str(value))]
    if source_id != "manual" and not encryption_configured():
        missing.append("PRIVATE_WORKSPACE_ENCRYPTION_KEY")
    source_status = "connected" if source_id == "manual" else "not_configured" if missing else "disconnected"
    if connection:
        source_status = connection.status
        if connection.error and source_status == "connected":
            source_status = "error"
        if missing and source_status not in {"connected", "connecting", "error"}:
            source_status = "not_configured"
    return {
        "id": source_id, "name": str(descriptor.get("name") or source_id),
        "status": source_status, "capabilities": [str(value) for value in descriptor.get("capabilities", [])],
        "missing_configuration": sorted(set(missing)), "last_sync": _aware(connection.last_sync) if connection else None,
        "error": connection.error if connection else None, "metadata": source_metadata(connection),
    }


def source_descriptors():
    descriptors = {row["id"]: row for row in providers().describe_sources() if row.get("id") in SOURCE_IDS}
    descriptors["manual"] = {"id": "manual", "name": "我的待办", "capabilities": ["local_tasks"], "missing_configuration": []}
    return [descriptors[source_id] for source_id in SOURCE_IDS if source_id in descriptors]


async def current_ads_condition(private_db, owner_id, *, focus_time=None):
    """Keep retained historical campaigns out of the current snapshot before SQL limits."""
    connection = await connection_for(private_db, owner_id, "google_ads")
    metadata = (connection.metadata_json or {}) if connection else {}
    snapshot = metadata.get("ads_snapshot")
    customer_id = metadata.get("ads_customer_id")
    membership = []
    if customer_id:
        membership.append(PrivateItem.evidence["customer_id"].as_string() == str(customer_id))
    if isinstance(snapshot, dict) and snapshot.get("id") and customer_id:
        membership.append(PrivateItem.evidence["ads_snapshot_id"].as_string() == str(snapshot["id"]))
    elif snapshot is not None or focus_time is not None:
        # Legacy rows remain readable, but cannot generate a health alert.
        return false()
    if focus_time is not None:
        try:
            observed = _aware(snapshot.get("observed_at"))
        except (ValueError, TypeError):
            return false()
        last_sync = _aware(connection.last_sync) if connection else None
        if (not connection or connection.status != "connected" or connection.error or not observed or not last_sync
                or snapshot.get("metrics_complete") is not True
                or not timedelta(0) <= focus_time - observed <= timedelta(hours=24)
                or not timedelta(0) <= focus_time - last_sync <= timedelta(hours=24)):
            return false()
        membership.append(PrivateItem.evidence["ads_health"]["bucket"].as_string().in_(["problem", "attention"]))
    return and_(*membership) if membership else PrivateItem.source_id == "google_ads"


async def list_items(private_db, owner_id: str, *, source_id=None, kind=None, action_status=None, limit=100, mail_bucket=None):
    if mail_bucket:
        if mail_bucket not in BUCKETS or source_id not in {None, "gmail"}:
            raise HTTPException(status_code=422, detail="邮件分组仅用于 Gmail")
        source_id = "gmail"
    conditions = [PrivateItem.owner_id == owner_id]
    if source_id:
        require_source(source_id)
        conditions.append(PrivateItem.source_id == source_id)
    if kind:
        conditions.append(PrivateItem.kind == kind)
    if action_status:
        conditions.append(PrivateItem.action_status == action_status)
    else:
        # A local task's archive state must not hide a currently running campaign.
        conditions.append(or_(PrivateItem.source_id == "google_ads", PrivateItem.action_status != "archived"))
    if source_id in {None, "google_ads"}:
        current_ads = await current_ads_condition(private_db, owner_id)
        conditions.append(or_(PrivateItem.source_id != "google_ads", current_ads))
    if source_id == "gmail":
        stored = await stored_preferences_for(private_db, owner_id)
        rows = (await private_db.execute(select(PrivateItem).where(*conditions).order_by(
            func.coalesce(PrivateItem.occurred_at, PrivateItem.created_at).desc(), PrivateItem.id,
        ))).scalars().all()
        computed = [item_response(row, stored) for row in rows]
        counts = {bucket: sum(item["mail_relevance"]["bucket"] == bucket for item in computed) for bucket in BUCKETS}
        computed.sort(key=lambda item: BUCKETS.index(item["mail_relevance"]["bucket"]))
        if mail_bucket:
            computed = [item for item in computed if item["mail_relevance"]["bucket"] == mail_bucket]
        from services.private_mail_brief_service import attach_cached_previews as attach_briefs
        from services.private_mail_translation_service import attach_cached_previews
        await attach_briefs(private_db, owner_id, computed[:limit])
        return {"items": await attach_cached_previews(private_db, owner_id, computed[:limit]),
                "total": len(computed), "mail_counts": counts}
    total = (await private_db.execute(select(func.count()).select_from(PrivateItem).where(*conditions))).scalar_one()
    stored = await stored_preferences_for(private_db, owner_id)
    rows = (await private_db.execute(select(PrivateItem).where(*conditions).order_by(
        PrivateItem.created_at.desc(), PrivateItem.id,
    ).limit(limit))).scalars().all()
    from services.private_mail_translation_service import attach_cached_previews
    from services.private_mail_brief_service import attach_cached_previews as attach_briefs
    computed = await attach_briefs(private_db, owner_id, [item_response(row, stored) for row in rows])
    return {"items": await attach_cached_previews(private_db, owner_id, computed), "total": total}


async def overview_items(private_db, owner_id: str, *, reference_time=None):
    now = _aware(reference_time) or utcnow()
    actionable = or_(
        PrivateItem.action_status == "open",
        and_(PrivateItem.action_status == "snoozed", PrivateItem.snoozed_until.is_not(None),
             PrivateItem.snoozed_until <= now),
    )
    priority_order = case((PrivateItem.priority == "urgent", 0), (PrivateItem.priority == "high", 1),
                          (PrivateItem.priority == "normal", 2), else_=3)
    current_ads = await current_ads_condition(private_db, owner_id, focus_time=now)
    # Arrival dates on ordinary payouts do not turn them into work to be done.
    work = (await private_db.execute(select(PrivateItem).where(
        PrivateItem.owner_id == owner_id, actionable, PrivateItem.source_id.notin_(["bofa", "gmail"]),
        or_(PrivateItem.source_id != "google_ads", current_ads),
        or_(PrivateItem.source_id == "manual", PrivateItem.priority.in_(["high", "urgent"])),
    ).order_by(priority_order, case((PrivateItem.due_at.is_(None), 1), else_=0),
               PrivateItem.due_at.asc(), PrivateItem.created_at.asc(), PrivateItem.id).limit(100))).scalars().all()
    stored = await stored_preferences_for(private_db, owner_id)
    gmail = (await private_db.execute(select(PrivateItem).where(
        PrivateItem.owner_id == owner_id, PrivateItem.source_id == "gmail", actionable,
    ).order_by(PrivateItem.occurred_at.desc(), PrivateItem.id))).scalars().all()
    focus = [item_response(row, stored) for row in [*work, *gmail]]
    focus = [item for item in focus if item.get("mail_relevance", {}).get("bucket", "today") in {"urgent", "today"}]
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    focus.sort(key=lambda item: ({"urgent": 0, "high": 1, "normal": 2, "low": 3}[item["priority"]],
                                 item["due_at"] is None, item["due_at"] or epoch,
                                 item["occurred_at"] or epoch, item["id"]))
    # Bank emails remain an independently labelled, unverified reminder stream.
    bank = (await private_db.execute(select(PrivateItem).where(
        PrivateItem.owner_id == owner_id, PrivateItem.source_id == "bofa", actionable,
    ).order_by(case((PrivateItem.occurred_at.is_(None), 1), else_=0), PrivateItem.occurred_at.desc(),
               PrivateItem.created_at.desc(), PrivateItem.id).limit(10))).scalars().all()
    return focus[:100] + [item_response(row) for row in bank]


async def workspace_overview(private_db, owner_id: str):
    connections = (await private_db.execute(select(PrivateConnection).where(PrivateConnection.owner_id == owner_id))).scalars().all()
    by_source = {row.source_id: row for row in connections}
    sources = [source_response(descriptor, by_source.get(descriptor["id"])) for descriptor in source_descriptors()]
    balances = []
    for connection in connections:
        if connection.status == "connected":
            for value in (connection.metadata_json or {}).get("balances", []):
                balances.append({"source_id": connection.source_id, "currency": value["currency"],
                                 "available_minor": value["available_minor"], "pending_minor": value["pending_minor"]})
    times = [_aware(row.last_sync) for row in connections if row.last_sync]
    from services.private_mail_translation_service import attach_cached_previews
    from services.private_mail_brief_service import attach_cached_previews as attach_briefs
    computed = await attach_briefs(private_db, owner_id, await overview_items(private_db, owner_id))
    return {"sources": sources, "items": await attach_cached_previews(private_db, owner_id, computed),
            "balances": balances, "last_sync": max(times) if times else None}


async def _source_after(private_db, owner_id, source_id):
    descriptor = next(row for row in source_descriptors() if row["id"] == source_id)
    return source_response(descriptor, await connection_for(private_db, owner_id, source_id))


async def connect_source(private_db, owner_id: str, source_id: str):
    require_source(source_id, external=True)
    descriptor = next(row for row in source_descriptors() if row["id"] == source_id)
    if source_response(descriptor)["missing_configuration"]:
        raise HTTPException(status_code=503, detail="此来源尚未完成服务器配置")
    state = secrets.token_urlsafe(32)
    try:
        result = await asyncio.wait_for(providers().begin_connect(source_id, state), timeout=45)
        authorization_url = safe_authorization_url(result["authorization_url"]) if result.get("authorization_url") else None
        if authorization_url and dict(parse_qsl(urlsplit(authorization_url).query)).get("state") != state:
            raise HTTPException(status_code=502, detail="来源授权请求不匹配")
        encrypted = encrypt_credentials(result["credentials"]) if result.get("credentials") else None
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=502, detail="来源连接未成功，请检查配置或重新授权") from None
    if not authorization_url and not encrypted:
        raise HTTPException(status_code=502, detail="来源没有返回有效连接")
    connection = await connection_for(private_db, owner_id, source_id, create=True)
    changes = {"generation": PrivateConnection.generation + 1, "sync_lease_until": None,
               "error": None, "status": "connecting" if authorization_url else "connected"}
    if encrypted:
        changes["encrypted_credentials"] = encrypted
    if authorization_url:
        changes.update(oauth_state_hash=hashlib.sha256(state.encode()).hexdigest(),
                       oauth_expires_at=utcnow() + timedelta(minutes=10), oauth_used_at=None)
    else:
        changes.update(oauth_state_hash=None, oauth_expires_at=None, oauth_used_at=None)
    changes["metadata_json"] = safe_json(result.get("metadata") or {})
    await private_db.execute(update(PrivateConnection).where(PrivateConnection.id == connection.id).values(
        **changes).execution_options(synchronize_session=False))
    await private_db.commit()
    return {"source": await _source_after(private_db, owner_id, source_id),
            "authorization_url": authorization_url, "requires_redirect": bool(authorization_url)}


async def complete_oauth(private_db, business_db, source_id: str, state: str, code: str | None, error: str | None):
    require_source(source_id, external=True)
    digest = hashlib.sha256(state.encode()).hexdigest()
    connection = (await private_db.execute(select(PrivateConnection).where(
        PrivateConnection.source_id == source_id, PrivateConnection.oauth_state_hash == digest,
    ))).scalar_one_or_none()
    now = utcnow()
    if not connection or connection.oauth_used_at or not connection.oauth_expires_at or _aware(connection.oauth_expires_at) <= now:
        raise HTTPException(status_code=400, detail="授权请求已失效，请从私人工作空间重新连接")
    if not await valid_private_owner(connection.owner_id, business_db):
        raise HTTPException(status_code=403, detail="私人空间账号授权已失效")
    claimed = await private_db.execute(update(PrivateConnection).where(
        PrivateConnection.id == connection.id, PrivateConnection.oauth_state_hash == digest,
        PrivateConnection.oauth_used_at.is_(None), PrivateConnection.oauth_expires_at > now,
    ).values(oauth_used_at=now).execution_options(synchronize_session=False))
    if claimed.rowcount != 1:
        await private_db.rollback()
        raise HTTPException(status_code=400, detail="授权请求已使用")
    owner_id, connection_id, generation = connection.owner_id, connection.id, connection.generation
    await private_db.commit()  # Single-use is persisted before any external code exchange.
    if error or not code:
        await private_db.execute(update(PrivateConnection).where(
            PrivateConnection.id == connection_id, PrivateConnection.generation == generation,
        ).values(status="disconnected", encrypted_credentials=None, error="授权未完成"))
        await private_db.commit()
        return False
    try:
        result = await asyncio.wait_for(providers().complete_connect(source_id, code), timeout=45)
        encrypted = encrypt_credentials(result["credentials"])
    except Exception as error:
        safe_error = _provider_setup_message(source_id, error, "授权未完成，请重新连接")
        await private_db.execute(update(PrivateConnection).where(
            PrivateConnection.id == connection_id, PrivateConnection.generation == generation,
        ).values(status="disconnected", encrypted_credentials=None, error=safe_error))
        await private_db.commit()
        return False
    # Re-check current employee status after the external round-trip.
    if not await valid_private_owner(owner_id, business_db):
        raise HTTPException(status_code=403, detail="私人空间账号授权已失效")
    updated = await private_db.execute(update(PrivateConnection).where(
        PrivateConnection.id == connection_id, PrivateConnection.generation == generation,
        PrivateConnection.oauth_state_hash == digest,
    ).values(status="connected", encrypted_credentials=encrypted,
             metadata_json=safe_json(result.get("metadata") or {}), error=None))
    await private_db.commit()
    return updated.rowcount == 1


async def disconnect_source(private_db, owner_id: str, source_id: str):
    require_source(source_id, external=True)
    connection = await connection_for(private_db, owner_id, source_id, create=True)
    await private_db.execute(update(PrivateConnection).where(PrivateConnection.id == connection.id).values(
        generation=PrivateConnection.generation + 1, status="disconnected", encrypted_credentials=None,
        metadata_json={}, oauth_state_hash=None, oauth_expires_at=None, oauth_used_at=None,
        sync_lease_until=None, error=None,
    ).execution_options(synchronize_session=False))
    await private_db.commit()
    return {"source": await _source_after(private_db, owner_id, source_id)}


def _provider_item(owner_id: str, source_id: str, value: dict):
    external_id = str(value.get("external_id") or "")
    if not external_id or len(external_id) > 512:
        raise ValueError("provider item must have a stable ID")
    amount = value.get("amount_minor")
    if amount is not None and (type(amount) is not int or abs(amount) > 9_000_000_000_000_000):
        raise ValueError("invalid integer amount")
    currency = str(value.get("currency") or "").upper() or None
    if currency and not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("invalid currency")
    if amount is not None and not currency:
        raise ValueError("amount must have currency")
    priority = value.get("priority") or "normal"
    if priority not in {"low", "normal", "high", "urgent"}:
        priority = "normal"
    evidence = safe_json(value.get("evidence") or {})
    if not isinstance(evidence, dict):
        raise ValueError("invalid evidence")
    return {
        "owner_id": owner_id, "source_id": source_id, "external_id": external_id,
        "kind": str(value.get("kind") or "notice")[:48],
        "title": _SECRET_VALUE.sub("[已隐藏]", str(value.get("title") or "新事项"))[:240],
        "summary": _SECRET_VALUE.sub("[已隐藏]", str(value.get("summary") or ""))[:6000],
        "status": _SECRET_VALUE.sub("[已隐藏]", str(value.get("status") or "unknown"))[:64], "priority": priority,
        "amount_minor": amount, "currency": currency,
        "occurred_at": _aware(value.get("occurred_at")), "due_at": _aware(value.get("due_at")),
        "source_url": safe_source_url(source_id, value.get("source_url")), "evidence": evidence,
        "updated_at": utcnow(),
    }


async def persist_provider_batch(private_db, owner_id: str, source_id: str, batch: dict):
    values = batch.get("items") or []
    if not isinstance(values, list) or len(values) > 2000:
        raise ValueError("invalid provider batch")
    # A single update can include the same object multiple times; latest occurrence wins.
    normalized = {row["external_id"]: row for row in (_provider_item(owner_id, source_id, value) for value in values)}
    if source_id == "gmail":
        stored = await stored_preferences_for(private_db, owner_id)
        # Existing row IDs key feedback, so resyncs preserve the owner's choices.
        existing_ids = dict((await private_db.execute(select(PrivateItem.external_id, PrivateItem.id).where(
            PrivateItem.owner_id == owner_id, PrivateItem.source_id == "gmail",
        ))).all())
        for value in normalized.values():
            relevance = classify_mail({**value, "id": existing_ids.get(value["external_id"])}, stored)
            value["priority"] = BUCKET_PRIORITY[relevance["bucket"]]
    existing = set((await private_db.execute(select(PrivateItem.external_id).where(
        PrivateItem.owner_id == owner_id, PrivateItem.source_id == source_id,
    ))).scalars().all())
    dialect = private_db.bind.dialect.name
    if dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    elif dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        raise ValueError("unsupported private database")
    for value in normalized.values():
        statement = insert(PrivateItem).values(id=str(uuid4()), **value)
        # Local overrides and action status are never overwritten by a provider.
        statement = statement.on_conflict_do_update(
            index_elements=["owner_id", "source_id", "external_id"],
            set_={key: value[key] for key in value if key not in {"owner_id", "source_id", "external_id"}},
        )
        await private_db.execute(statement)
    balances = []
    for value in batch.get("balances") or []:
        currency = str(value.get("currency") or "").upper()
        amounts = (value.get("available_minor"), value.get("pending_minor"))
        if not re.fullmatch(r"[A-Z]{3}", currency) or any(type(amount) is not int or abs(amount) > 9_000_000_000_000_000 for amount in amounts):
            raise ValueError("invalid balance")
        balances.append({"currency": currency, "available_minor": amounts[0], "pending_minor": amounts[1]})
    if source_id != "stripe" and balances:
        raise ValueError("only Stripe supplies confirmed balance snapshots")
    return {"created": sum(key not in existing for key in normalized),
            "updated": sum(key in existing for key in normalized)}, balances


async def sync_source(private_db, owner_id: str, source_id: str, *, timeout_seconds=45):
    require_source(source_id, external=True)
    connection = await connection_for(private_db, owner_id, source_id)
    if not connection or connection.status != "connected" or not connection.encrypted_credentials:
        raise HTTPException(status_code=409, detail="请先连接此来源")
    connection_id, generation = connection.id, connection.generation
    credentials = decrypt_credentials(connection.encrypted_credentials)
    metadata = dict(connection.metadata_json or {})
    timeout_seconds = max(5, min(90, timeout_seconds))
    now = utcnow()
    claimed = await private_db.execute(update(PrivateConnection).where(
        PrivateConnection.id == connection_id, PrivateConnection.generation == generation,
        PrivateConnection.status == "connected",
        or_(PrivateConnection.sync_lease_until.is_(None), PrivateConnection.sync_lease_until < now),
    ).values(sync_lease_until=now + timedelta(seconds=timeout_seconds + 60), last_attempt_at=now)
      .execution_options(synchronize_session=False))
    if claimed.rowcount != 1:
        await private_db.rollback()
        raise HTTPException(status_code=409, detail="此来源正在同步，请稍后查看")
    run = PrivateSyncRun(owner_id=owner_id, source_id=source_id)
    private_db.add(run)
    await private_db.commit()
    run_id = run.id
    try:
        batch = await asyncio.wait_for(providers().fetch_source(source_id, credentials, metadata), timeout=timeout_seconds)
        # This guarded write also obtains the SQLite write lock before item upserts.
        still_current = await private_db.execute(update(PrivateConnection).where(
            PrivateConnection.id == connection_id, PrivateConnection.generation == generation,
            PrivateConnection.status == "connected",
        ).values(sync_lease_until=None))
        if still_current.rowcount != 1:
            raise HTTPException(status_code=409, detail="来源授权已改变，请重新同步")
        counts, balances = await persist_provider_batch(private_db, owner_id, source_id, batch)
        batch_metadata = safe_json(batch.get("metadata") or metadata)
        if not isinstance(batch_metadata, dict):
            raise ValueError("invalid provider metadata")
        # Synchronization cannot replace the identity/scope established during
        # authorization, or claim a new identity from a fetched snapshot.
        for key in ("account_label", "ads_customer_id", "connection_mode", "scope"):
            if key in metadata:
                batch_metadata[key] = safe_json(metadata[key])
            else:
                batch_metadata.pop(key, None)
        for key in ("read_only_adapter", "mode"):
            if key in metadata:
                batch_metadata[key] = safe_json(metadata[key])
        changed = {"last_sync": utcnow(), "error": None,
                   "metadata_json": {**batch_metadata, "balances": balances}}
        if batch.get("credentials"):
            changed["encrypted_credentials"] = encrypt_credentials(batch["credentials"])
        await private_db.execute(update(PrivateConnection).where(
            PrivateConnection.id == connection_id, PrivateConnection.generation == generation,
        ).values(**changed))
        await private_db.execute(update(PrivateSyncRun).where(PrivateSyncRun.id == run_id).values(
            status="succeeded", completed_at=utcnow(), created_count=counts["created"], updated_count=counts["updated"],
        ))
        await private_db.commit()
    except Exception as error:
        await private_db.rollback()
        safe_error = _provider_setup_message(source_id, error, "同步未成功，请检查来源授权后重试")
        await private_db.execute(update(PrivateConnection).where(
            PrivateConnection.id == connection_id, PrivateConnection.generation == generation,
        ).values(sync_lease_until=None, error=safe_error))
        await private_db.execute(update(PrivateSyncRun).where(PrivateSyncRun.id == run_id).values(
            status="failed", completed_at=utcnow(), error=safe_error,
        ))
        await private_db.commit()
        raise HTTPException(status_code=502, detail=safe_error) from None
    return {"source": await _source_after(private_db, owner_id, source_id), "counts": counts}


async def stored_preferences_for(private_db, owner_id: str):
    row = await private_db.get(PrivatePreferences, owner_id)
    return dict(row.preferences_json or {}) if row and isinstance(row.preferences_json, dict) else {}


async def preferences_for(private_db, owner_id: str):
    stored = await stored_preferences_for(private_db, owner_id)
    try:
        interval = int(stored.get("sync_interval_seconds", 900))
    except (TypeError, ValueError):
        interval = 900
    return {"sync_interval_seconds": max(300, min(86400, interval)), "gmail": gmail_preferences(stored)}


async def _locked_preferences_row(private_db, owner_id):
    if private_db.bind.dialect.name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        from sqlalchemy.dialects.postgresql import insert
    # INSERT takes SQLite's write lock; FOR UPDATE serializes Postgres JSON merges.
    await private_db.execute(insert(PrivatePreferences).values(owner_id=owner_id, preferences_json={})
                             .on_conflict_do_nothing(index_elements=["owner_id"]))
    return (await private_db.execute(select(PrivatePreferences).where(PrivatePreferences.owner_id == owner_id)
                                    .with_for_update().execution_options(populate_existing=True))).scalar_one()


async def _reclassify_gmail(private_db, owner_id, stored):
    rows = (await private_db.execute(select(PrivateItem).where(
        PrivateItem.owner_id == owner_id, PrivateItem.source_id == "gmail",
    ))).scalars().all()
    for item in rows:
        item.priority = item_response(item, stored)["priority"]


async def update_private_preferences(private_db, owner_id, changes):
    row = await _locked_preferences_row(private_db, owner_id)
    stored = dict(row.preferences_json or {})
    if "sync_interval_seconds" in changes:
        stored["sync_interval_seconds"] = changes["sync_interval_seconds"]
    if "gmail" in changes:
        stored["gmail"] = {**gmail_preferences(stored), **changes["gmail"]}
    row.preferences_json = stored
    await _reclassify_gmail(private_db, owner_id, stored)
    await private_db.commit()
    return await preferences_for(private_db, owner_id)


async def set_mail_feedback(private_db, owner_id, item_id, feedback, *, apply_to_sender=False):
    row = (await private_db.execute(select(PrivateItem).where(
        PrivateItem.id == item_id, PrivateItem.owner_id == owner_id,
    ))).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="未找到此私人邮件")
    if row.source_id != "gmail":
        raise HTTPException(status_code=409, detail="仅 Gmail 邮件支持关注反馈")
    preference_row = await _locked_preferences_row(private_db, owner_id)
    stored = dict(preference_row.preferences_json or {})
    prior = stored.get("gmail_feedback", {})
    prior = prior if isinstance(prior, dict) else {}
    items = dict(prior.get("items", {})) if isinstance(prior.get("items"), dict) else {}
    senders = dict(prior.get("senders", {})) if isinstance(prior.get("senders"), dict) else {}
    if feedback is None:
        items.pop(row.id, None)
    else:
        if row.id not in items and len(items) >= 1000:
            raise HTTPException(status_code=409, detail="邮件反馈已达上限，请先清除不再需要的反馈")
        items[row.id] = feedback
    if apply_to_sender:
        address = item_response(row, stored)["mail_relevance"]["sender_address"]
        if not address:
            raise HTTPException(status_code=422, detail="无法安全识别发件邮箱，请仅设置这封邮件")
        if feedback is None:
            senders.pop(address, None)
        else:
            if address not in senders and len(senders) >= 100:
                raise HTTPException(status_code=409, detail="发件人反馈已达上限，请先清除不再需要的反馈")
            senders[address] = feedback
    stored["gmail_feedback"] = {"items": items, "senders": senders}
    preference_row.preferences_json = stored
    await _reclassify_gmail(private_db, owner_id, stored)
    await private_db.commit()
    return {"item": item_response(row, stored)}


async def sync_due_sources(business_db, private_db, *, now=None):
    reference = _aware(now) or utcnow()
    result = {"attempted": 0, "succeeded": 0, "failed": 0, "skipped": 0}
    for owner_id in sorted(configured_owner_ids()):
        if not await valid_private_owner(owner_id, business_db):
            result["skipped"] += 1
            continue
        interval = (await preferences_for(private_db, owner_id))["sync_interval_seconds"]
        connections = (await private_db.execute(select(PrivateConnection).where(
            PrivateConnection.owner_id == owner_id, PrivateConnection.status == "connected",
            PrivateConnection.encrypted_credentials.is_not(None),
        ))).scalars().all()
        targets = [(row.source_id, _aware(row.last_sync), _aware(row.last_attempt_at)) for row in connections]
        for source_id, last_sync, last_attempt in targets:
            latest = max((value for value in (last_sync, last_attempt) if value), default=None)
            if source_id == "manual" or (latest and (reference - latest).total_seconds() < interval):
                result["skipped"] += 1
                continue
            # A role/allowlist change while processing an earlier source also applies here.
            if not await valid_private_owner(owner_id, business_db):
                result["skipped"] += 1
                continue
            result["attempted"] += 1
            try:
                await sync_source(private_db, owner_id, source_id)
                result["succeeded"] += 1
            except Exception:
                await private_db.rollback()
                result["failed"] += 1
    return result
