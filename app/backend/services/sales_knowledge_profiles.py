"""Audited knowledge profiles in the existing operation ledger; no schema change.

The article row contains the latest manager draft. Published snapshots in this
ledger keep staff on the last explicitly approved wording while a draft changes.
Callers hold the knowledge write lock and own the commit/rollback boundary.
"""
import json
from copy import deepcopy
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from models.operation_logs import Operation_logs
from models.sales_knowledge_articles import SalesKnowledgeArticles

PROFILE_PREFIX = "sales_knowledge_profile:"
PACK_PREFIX = "sales_knowledge_pack:beautyos:"
KNOWLEDGE_ADVISORY_KEY = int.from_bytes(b"T24KNOWL", "big")
PROFILE_FIELDS = ("product_scope", "phone_answer", "followup_question", "demo_steps", "next_action",
                  "internal_notes", "store_types", "availability", "high_frequency")
BASE_FIELDS = ("category", "title", "customer_question", "standard_answer", "action_steps", "related_links",
               "escalation_rule", "tags", "status", "is_sensitive", "sort_order", "created_by_name",
               "published_by_name", "published_at", "updated_at")


def list_json(value):
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return [str(item).strip() for item in parsed if str(item).strip()] if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        return []


def _iso(value):
    return value.isoformat() if isinstance(value, datetime) else value


def article_base(article):
    result = {"id": article.id}
    for name in BASE_FIELDS:
        value = getattr(article, name)
        result[name] = list_json(value) if name in {"action_steps", "related_links", "tags"} else _iso(value)
    return result


def inferred_scope(article):
    """Classify only explicit legacy product markers, never prices or prose."""
    title = str(article.title or "")
    tags = {value.lower() for value in list_json(article.tags)}
    if title.startswith("付款链接｜") or "代运营" in title or tags & {"代运营", "标准代运营", "managed_service"}:
        return "managed_service"
    if "餐厅" in title or tags & {"餐厅", "restaurant"}:
        return "restaurant"
    if "美业os" in title.lower() or tags & {"美业os", "beautyos"}:
        return "beautyos"
    return "general"


def default_profile(article):
    return {"product_scope": inferred_scope(article), "phone_answer": "", "followup_question": "",
            "demo_steps": [], "next_action": "", "internal_notes": "", "store_types": [],
            "availability": "pending_confirmation", "high_frequency": False}


def _decode(log, article_id):
    try:
        value = json.loads(log.action_detail or "{}")
        def valid_metadata(metadata):
            return (isinstance(metadata, dict) and set(PROFILE_FIELDS) <= set(metadata)
                    and metadata["product_scope"] in {"general", "beautyos", "restaurant", "managed_service"}
                    and metadata["availability"] in {"ready", "requires_setup", "pending_confirmation"}
                    and type(metadata["high_frequency"]) is bool
                    and all(isinstance(metadata[key], str) for key in ("phone_answer", "followup_question", "next_action", "internal_notes"))
                    and all(isinstance(metadata[key], list) and all(isinstance(item, str) for item in metadata[key]) for key in ("demo_steps", "store_types")))
        approved = value.get("published_snapshot")
        valid = (value.get("schema_version") == 1 and value.get("article_id") == article_id
                 and type(value.get("revision")) is int and value["revision"] > 0
                 and valid_metadata(value.get("after")) and isinstance(value.get("snapshot"), dict)
                 and value["snapshot"].get("id") == article_id
                 and (approved is None or (valid_metadata(approved) and approved.get("id") == article_id
                     and approved.get("status") == "published" and set(BASE_FIELDS) <= set(approved))))
        if not valid:
            raise ValueError()
        return value
    except (TypeError, ValueError, AttributeError):
        raise HTTPException(503, "知识卡修订记录暂不可读取，请联系管理员；本次未修改内容")


async def profiles_for_many(db, article_ids):
    ids = sorted(set(int(value) for value in article_ids))
    if not ids:
        return {}
    actions = {f"{PROFILE_PREFIX}{value}": value for value in ids}
    latest = select(func.max(Operation_logs.id).label("id")).where(
        Operation_logs.action_type.in_(actions)).group_by(Operation_logs.action_type).subquery()
    rows = (await db.scalars(select(Operation_logs).join(latest, latest.c.id == Operation_logs.id))).all()
    return {actions[row.action_type]: _decode(row, actions[row.action_type]) for row in rows}


async def profile_for(db, article_id):
    return (await profiles_for_many(db, [article_id])).get(article_id)


def article_data(article, profile=None, *, published_only=False):
    if published_only and article.status != "published":
        approved = (profile or {}).get("published_snapshot")
        return deepcopy(approved) if article.status != "archived" and isinstance(approved, dict) else None
    data = {**article_base(article), **(deepcopy(profile["after"]) if profile else default_profile(article))}
    data.update(revision=profile["revision"] if profile else 0,
                published_revision=profile.get("published_revision", 0) if profile else 0,
                legacy_profile=profile is None, inferred_product_scope=profile is None,
                reviewed_by_name=profile.get("reviewed_by_name") if profile else None,
                reviewed_at=profile.get("reviewed_at") if profile else None)
    return data


async def lock_knowledge(db, article_ids=()):
    """Acquire before knowledge reads; serialize writes across server processes."""
    try:
        with db.no_autoflush:
            dialect = db.get_bind().dialect.name
            if dialect == "sqlite":
                await db.execute(text("UPDATE sales_knowledge_articles SET id = id WHERE 0"))
            else:
                if dialect == "postgresql":
                    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": KNOWLEDGE_ADVISORY_KEY})
                if article_ids:
                    await db.execute(select(SalesKnowledgeArticles).where(SalesKnowledgeArticles.id.in_(sorted(set(article_ids))))
                                     .order_by(SalesKnowledgeArticles.id).with_for_update().execution_options(populate_existing=True))
    except DBAPIError as error:
        code = getattr(error.orig, "sqlite_errorcode", None)
        state = getattr(error.orig, "sqlstate", None) or getattr(error.orig, "pgcode", None)
        if ((isinstance(code, int) and (code & 255) in {5, 6}) or state in {"40P01", "55P03", "40001"}
                or "database is locked" in str(error.orig).lower()):
            await db.rollback()
            raise HTTPException(409, "知识库正在被其他人更新，请重新读取后再保存；本次未写入") from error
        raise


def check_revision(profile, expected_revision):
    revision = profile["revision"] if profile else 0
    if expected_revision != revision and not (revision == 0 and expected_revision is None):
        raise HTTPException(409, "知识卡已被更新，请重新读取最新版本后再保存；本次输入未写入")


def metadata_from_payload(payload, article, previous=None):
    metadata = deepcopy(previous["after"]) if previous else default_profile(article)
    for field in PROFILE_FIELDS:
        if field in payload.model_fields_set:
            metadata[field] = deepcopy(getattr(payload, field))
    return metadata


async def append_profile(db, article, metadata, actor, *, action, previous=None, before_snapshot=None, publish=False):
    now = datetime.now(timezone.utc)
    revision = previous["revision"] + 1 if previous else 1
    published_snapshot = deepcopy((previous or {}).get("published_snapshot"))
    published_revision = (previous or {}).get("published_revision", 0)
    reviewed_by_name = (previous or {}).get("reviewed_by_name")
    reviewed_at = (previous or {}).get("reviewed_at")
    if not previous and before_snapshot and before_snapshot.get("status") == "published":
        # A pre-existing published card remains the approved version until the
        # manager explicitly publishes the first audited revision.
        published_snapshot = deepcopy(before_snapshot)
    state = {"schema_version": 1, "article_id": article.id, "revision": revision,
             "after": deepcopy(metadata), "snapshot": {**article_base(article), **deepcopy(metadata)},
             "before": deepcopy(previous.get("snapshot")) if previous else before_snapshot,
             "action": action, "actor": {"id": int(actor.id), "name": actor.name}, "created_at": now.isoformat(),
             "published_snapshot": published_snapshot, "published_revision": published_revision,
             "reviewed_by_name": reviewed_by_name, "reviewed_at": reviewed_at}
    if publish:
        state.update(published_revision=revision, reviewed_by_name=actor.name, reviewed_at=now.isoformat())
        state["published_snapshot"] = article_data(article, state)
    db.add(Operation_logs(user_id=str(actor.id), action_type=f"{PROFILE_PREFIX}{article.id}",
                          action_detail=json.dumps(state, ensure_ascii=False), operator_name=actor.name, created_at=now))
    await db.flush()
    return state


async def pack_mappings(db):
    rows = (await db.scalars(select(Operation_logs).where(Operation_logs.action_type.startswith(PACK_PREFIX, autoescape=True))
                             .order_by(Operation_logs.id.desc()))).all()
    result = {}
    for row in rows:
        key = row.action_type[len(PACK_PREFIX):]
        if key in result:
            continue
        try:
            value = json.loads(row.action_detail or "{}")
            if value.get("key") != key or type(value.get("article_id")) is not int:
                raise ValueError()
        except (TypeError, ValueError, AttributeError):
            raise HTTPException(503, "知识库标准卡导入记录暂不可读取，请联系管理员")
        result[key] = value
    return result


def add_pack_mapping(db, item, article, actor, *, version, manifest_hash):
    now = datetime.now(timezone.utc)
    value = {"key": item["key"], "article_id": article.id, "version": version, "manifest_hash": manifest_hash,
             "actor": {"id": int(actor.id), "name": actor.name}, "created_at": now.isoformat()}
    db.add(Operation_logs(user_id=str(actor.id), action_type=PACK_PREFIX + item["key"],
                          action_detail=json.dumps(value, ensure_ascii=False), operator_name=actor.name, created_at=now))
