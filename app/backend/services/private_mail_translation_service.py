"""Owner-only mail translations, encrypted cache and atomic monthly reservations.

All tables and sessions in this module are in the independent private database.
Mail is data: neither provider responses nor mail text can choose a destination.
"""
import asyncio
import hashlib
import json
import secrets
from datetime import timedelta

from cryptography.fernet import InvalidToken
from fastapi import HTTPException
from sqlalchemy import and_, exists, or_, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from models.private_workspace import PrivateConnection, PrivateItem, PrivateMailTranslation, PrivateTranslationUsage, utcnow
from services import private_mail_translation as translator
from services import private_workspace_providers as gmail
from services.private_workspace import _aware, _cipher, connection_for, decrypt_credentials, encrypt_credentials


def _insert(db, model):
    if db.bind.dialect.name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        from sqlalchemy.dialects.postgresql import insert
    return insert(model)


def _empty(state="unavailable"):
    return {"state": state, "title_zh": None, "summary_zh": None,
            "body_available": False, "truncated": False}


def _encrypt(value):
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    if len(raw) > 1_500_000:
        raise translator.TranslationError("invalid_response")
    return _cipher().encrypt(raw).decode()


def _decrypt(value, *, body=False):
    try:
        if not isinstance(value, str) or len(value) > 2_100_000:
            return None
        result = json.loads(_cipher().decrypt(value.encode()))
        if not isinstance(result, dict) or result.get("state") != "ready":
            return None
        # Explicitly permit fields; encrypted data is still untrusted data.
        safe = _empty("ready")
        for field, limit in (("title_zh", 12000), ("summary_zh", 10000), ("updated_at", 80)):
            text = result.get(field)
            if text is not None and (not isinstance(text, str) or len(text) > limit):
                return None
            safe[field] = text
        safe["truncated"] = result.get("truncated") is True
        if body:
            for field, limit in (("body_zh", 300000), ("body_original", 50000)):
                text = result.get(field)
                if text is not None and (not isinstance(text, str) or len(text) > limit):
                    return None
                safe[field] = text
            safe["body_available"] = result.get("body_available") is True
        return safe
    except (InvalidToken, ValueError, TypeError, HTTPException):
        return None


async def owned_mail(db, owner_id, item_id):
    row = (await db.execute(select(PrivateItem).where(
        PrivateItem.id == item_id, PrivateItem.owner_id == owner_id,
    ).execution_options(populate_existing=True))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "未找到此私人邮件")
    if row.source_id != "gmail":
        raise HTTPException(409, "仅支持翻译 Gmail 邮件")
    return row


def _context(connection, row, mode):
    if not connection or connection.status != "connected" or not connection.encrypted_credentials:
        raise gmail.ProviderError("authorization_expired")
    metadata = connection.metadata_json or {}
    mailbox = metadata.get("account_label")
    if not isinstance(mailbox, str) or metadata.get("read_only_adapter") is not True:
        raise gmail.ProviderError("authorization_expired")
    gmail._check_gmail_account(mailbox)
    plan = translator.prepare_mail_translation(row.title, row.summary or "")
    identity = translator.translation_cache_key(str(row.owner_id), mailbox, connection.generation,
                                                row.external_id, plan.source_hash)
    key = hashlib.sha256(f"{connection.id}:{identity}:{mode}".encode()).hexdigest()
    return {"key": key, "owner_id": row.owner_id, "item_id": row.id,
            "generation": connection.generation, "connection_id": connection.id,
            "source_hash": plan.source_hash, "plan": plan,
            "credentials": connection.encrypted_credentials, "metadata": dict(metadata),
            "title": row.title, "summary": row.summary, "message_id": row.external_id}


async def _claim(db, row, context, mode):
    token = secrets.token_hex(24)
    now = utcnow()
    values = {"cache_key": context["key"], "owner_id": row.owner_id,
              "connection_id": context["connection_id"], "generation": context["generation"],
              "item_id": row.id, "source_hash": context["source_hash"], "mode": mode,
              "state": "pending", "lease_token": token, "lease_until": now + timedelta(seconds=120)}
    await db.execute(_insert(db, PrivateMailTranslation).values(**values).on_conflict_do_nothing(index_elements=["cache_key"]))
    entry = (await db.execute(select(PrivateMailTranslation).where(
        PrivateMailTranslation.cache_key == context["key"], PrivateMailTranslation.owner_id == row.owner_id,
    ).execution_options(populate_existing=True))).scalar_one()
    if entry.state == "ready":
        cached = _decrypt(entry.encrypted_content, body=mode == "body")
        if cached:
            await db.commit()
            return None, cached, None
        # Corrupt/unreadable ciphertext is never displayed. Allow a fresh fetch.
        entry.state = "failed"
        entry.lease_until = None
        await db.flush()
    if entry.lease_token == token:
        await db.commit()
        return token, None, None
    if entry.lease_until and _aware(entry.lease_until) > now:
        state, code = entry.state, entry.error_code
        await db.commit()
        return None, _empty(state), code
    changed = await db.execute(update(PrivateMailTranslation).where(
        PrivateMailTranslation.cache_key == context["key"],
        PrivateMailTranslation.state != "ready",
        or_(PrivateMailTranslation.lease_until.is_(None), PrivateMailTranslation.lease_until <= now),
    ).values(state="pending", lease_token=token, lease_until=values["lease_until"], error_code=None))
    await db.commit()
    return (token, None, None) if changed.rowcount else (None, _empty("pending"), None)


async def reserve_characters(db, owner_id, count):
    """Conditional UPDATE is the spending gate across processes and requests."""
    limit = translator.monthly_limit()
    if type(count) is not int or count < 0:
        raise translator.TranslationError("invalid_input")
    month = utcnow().strftime("%Y-%m")
    await db.execute(_insert(db, PrivateTranslationUsage).values(owner_id=owner_id, month=month, characters=0)
                     .on_conflict_do_nothing(index_elements=["owner_id", "month"]))
    changed = await db.execute(update(PrivateTranslationUsage).where(
        PrivateTranslationUsage.owner_id == owner_id, PrivateTranslationUsage.month == month,
        PrivateTranslationUsage.characters + count <= limit,
    ).values(characters=PrivateTranslationUsage.characters + count))
    await db.commit()
    return bool(changed.rowcount)


def _live_connection(owner_id, context):
    return exists(select(PrivateConnection.id).where(
        PrivateConnection.id == context["connection_id"], PrivateConnection.owner_id == owner_id,
        PrivateConnection.source_id == "gmail", PrivateConnection.generation == context["generation"],
        PrivateConnection.status == "connected", PrivateConnection.encrypted_credentials.is_not(None),
        PrivateConnection.metadata_json["account_label"].as_string() == context["metadata"]["account_label"],
    ))


def _live_context(row, context):
    # Use the immutable request snapshot, including after a DB rollback has
    # expired ORM instances. Never trigger implicit async lazy loading here.
    return and_(_live_connection(context["owner_id"], context),
                exists(select(PrivateItem.id).where(PrivateItem.id == context["item_id"], PrivateItem.owner_id == context["owner_id"],
                                                    PrivateItem.title == context["title"],
                                                    PrivateItem.summary == context["summary"])))


async def _finish(db, row, context, token, result=None, code=None):
    conditions = [PrivateMailTranslation.cache_key == context["key"],
                  PrivateMailTranslation.owner_id == context["owner_id"], PrivateMailTranslation.lease_token == token,
                  _live_context(row, context)]
    changed = await db.execute(update(PrivateMailTranslation).where(*conditions).values(
        state="ready" if result else "failed", encrypted_content=_encrypt(result) if result else None,
        error_code=code, lease_token=None, lease_until=None if result else utcnow() + timedelta(seconds=30),
    ))
    await db.commit()
    return bool(changed.rowcount)


def _public_error(exc):
    code = getattr(exc, "code", "upstream_unavailable")
    if code in {"authorization_expired", "access_denied"} and isinstance(exc, gmail.ProviderError):
        return "authorization_expired"
    if code == "quota_exceeded":
        return "limit_reached"
    if code == "not_configured":
        return "not_configured"
    return "upstream_unavailable"


async def translate_item(db, owner_id, item_id, *, mode="body"):
    if mode not in {"preview", "body"}:
        raise HTTPException(422, "翻译模式无效")
    row = await owned_mail(db, owner_id, item_id)
    enabled = translator.configured()
    response = {"configured": enabled, "item_id": row.id, "translation": _empty()}
    connection = await connection_for(db, owner_id, "gmail")
    try:
        context = _context(connection, row, mode)
    except (gmail.ProviderError, translator.TranslationError) as exc:
        return {**response, "code": _public_error(exc)}
    if not enabled:
        return {**response, "code": "not_configured"}
    token, cached, code = await _claim(db, row, context, mode)
    if cached:
        if not (await db.execute(select(_live_context(row, context)))).scalar_one():
            return {**response, "code": "authorization_expired"}
        return {**response, "translation": cached, **({"code": code} if code else {})}
    try:
        async with asyncio.timeout(55):
            plan = context["plan"]
            content = None
            if mode == "body":
                content = await gmail.fetch_mail_content(decrypt_credentials(context["credentials"]),
                                                        context["metadata"], context["message_id"])
                if content.get("credentials"):
                    # Do not overwrite a concurrent sync's newer refresh token.
                    await db.execute(update(PrivateConnection).where(
                        PrivateConnection.id == context["connection_id"], PrivateConnection.owner_id == owner_id,
                        PrivateConnection.generation == context["generation"], PrivateConnection.status == "connected",
                        PrivateConnection.encrypted_credentials == context["credentials"],
                    ).values(encrypted_credentials=encrypt_credentials(content["credentials"])))
                    await db.commit()
                plan = translator.prepare_mail_translation(content["title"], content["summary"],
                    content["body"] if content["has_body"] else None, body_truncated=content["truncated"])
            # Check connection again immediately before any external disclosure.
            live = (await db.execute(select(_live_context(row, context)))).scalar_one()
            if not live:
                raise gmail.ProviderError("authorization_expired")
            if not await reserve_characters(db, owner_id, plan.character_count):
                await _finish(db, row, context, token, code="limit_reached")
                return {**response, "translation": _empty("failed"), "code": "limit_reached"}
            translated = await translator.translate_mail(plan)
            result = {"state": "ready", "title_zh": translated["title"], "summary_zh": translated["summary"],
                      "body_available": bool(content and content["has_body"]),
                      "truncated": translated["body_truncated"], "updated_at": translated["translated_at"]}
            if mode == "body":
                result.update(body_zh=translated["body"], body_original=content["body"] if content["has_body"] else None)
            if not await _finish(db, row, context, token, result=result):
                return {**response, "code": "authorization_expired"}
            return {**response, "translation": result}
    except (translator.TranslationError, gmail.ProviderError, HTTPException, TimeoutError) as exc:
        code = _public_error(exc)
        await db.rollback()
        await _finish(db, row, context, token, code=code)
        return {**response, "translation": _empty("failed"), "code": code}


async def translate_batch(db, owner_id, item_ids):
    if not 1 <= len(item_ids) <= 10:
        raise HTTPException(422, "每次最多翻译 10 封邮件摘要")
    # Authorize the complete request before any translation or spending.
    ids = list(dict.fromkeys(item_ids))
    for item_id in ids:
        await owned_mail(db, owner_id, item_id)
    enabled = translator.configured()
    await db.commit()
    if not enabled:
        return {"configured": False, "code": "not_configured", "items": []}
    sessions = async_sessionmaker(db.bind, expire_on_commit=False)

    async def one(item_id):
        async with sessions() as session:
            return await translate_item(session, owner_id, item_id, mode="preview")

    # Maximum ten independent requests, each with its own short DB transactions.
    results = await asyncio.gather(*(one(item_id) for item_id in ids))
    codes = [entry["code"] for entry in results if entry.get("code")]
    return {"configured": enabled, "items": results, **({"code": codes[0]} if codes else {})}


async def attach_cached_previews(db, owner_id, items):
    ids = [item["id"] for item in items if item["source_id"] == "gmail"]
    if not ids:
        return items
    connection = await connection_for(db, owner_id, "gmail")
    rows = (await db.execute(select(PrivateItem).where(PrivateItem.owner_id == owner_id, PrivateItem.id.in_(ids)))).scalars().all()
    keys = {}
    cache_conditions = []
    for row in rows:
        try:
            context = _context(connection, row, "preview")
            keys[context["key"]] = row.id
            cache_conditions.append(and_(PrivateMailTranslation.cache_key == context["key"], _live_context(row, context)))
        except (gmail.ProviderError, translator.TranslationError):
            continue
    if not keys:
        return items
    entries = (await db.execute(select(PrivateMailTranslation).where(
        PrivateMailTranslation.owner_id == owner_id, PrivateMailTranslation.cache_key.in_(keys),
        PrivateMailTranslation.state == "ready", PrivateMailTranslation.mode == "preview",
        or_(*cache_conditions),
    ))).scalars().all()
    by_id = {keys[entry.cache_key]: _decrypt(entry.encrypted_content) for entry in entries}
    for item in items:
        if by_id.get(item["id"]):
            item["mail_translation"] = by_id[item["id"]]
    return items
