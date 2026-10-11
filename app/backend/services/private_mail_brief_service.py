"""Single-click, owner-only mail briefs in the independent private database.

No business session, ledger, AIHub setting, mail send or automatic batch exists
here. An external consent gate is checked before fetching or disclosing text.
"""
import asyncio
import hashlib
import json
import re
import secrets
from datetime import timedelta

from cryptography.fernet import InvalidToken
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import and_, exists, inspect, or_, select, text, update

from models.private_workspace import (
    PrivateConnection, PrivateItem, PrivateMailBrief, PrivateMailBriefUsage, PrivateWorkspaceBase, utcnow,
)
from schemas.private_workspace import PrivateMailBriefResponse
from services import private_mail_brief as provider
from services import private_workspace_providers as gmail
from services.private_workspace import (
    _aware, _cipher, connection_for, decrypt_credentials, encrypt_credentials,
    item_response, stored_preferences_for,
)


def _insert(db, model):
    if db.bind.dialect.name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        from sqlalchemy.dialects.postgresql import insert
    return insert(model)


async def migrate_private_mail_brief_budget(connection):
    """Add fixed budget columns ONLY on an already-isolated private schema.

    The factory verifies the private database identity before this hook. This
    additional table inventory guard refuses a business or mixed schema. Old
    nonzero character/request usage with no recorded USD cost is charged the
    entire approved cap, never reset to zero or treated as a free new month.
    """
    def migrate(db):
        tables = set(inspect(db).get_table_names())
        if not tables <= set(PrivateWorkspaceBase.metadata.tables):
            raise RuntimeError('private_budget_schema_mismatch')
        if 'private_mail_brief_usage' in tables:
            columns = {column['name'] for column in inspect(db).get_columns('private_mail_brief_usage')}
            if 'reserved_usd_micros' not in columns:
                db.execute(text('ALTER TABLE private_mail_brief_usage ADD COLUMN reserved_usd_micros BIGINT NOT NULL DEFAULT 0'))
            db.execute(text('UPDATE private_mail_brief_usage SET reserved_usd_micros = :cap '
                            'WHERE (characters <> 0 OR requests <> 0) '
                            'AND (reserved_usd_micros IS NULL OR reserved_usd_micros = 0)'),
                       {'cap': provider.MAX_MONTHLY_BUDGET_MICRO_USD})
        if 'private_mail_briefs' in tables:
            columns = {column['name'] for column in inspect(db).get_columns('private_mail_briefs')}
            additions = {
                'reservation_month': 'VARCHAR(7)',
                'reservation_micro_usd': 'BIGINT NOT NULL DEFAULT 0',
                'reservation_price_policy': 'VARCHAR(80)',
                'reservation_state': "VARCHAR(16) NOT NULL DEFAULT 'none'",
            }
            for name, definition in additions.items():
                if name not in columns:
                    db.execute(text(f'ALTER TABLE private_mail_briefs ADD COLUMN {name} {definition}'))
    await connection.run_sync(migrate)


def _empty(state="unavailable"):
    return PrivateMailBriefResponse(state=state).model_dump(exclude_none=True)


def _encrypt(result, input_hash):
    raw = json.dumps({"input_hash": input_hash, "brief": result}, ensure_ascii=False,
                     separators=(",", ":")).encode()
    if len(raw) > 250000:
        raise provider.MailBriefError("invalid_response")
    return _cipher().encrypt(raw).decode()


def _decrypt(entry, *, body=False):
    try:
        ciphertext = entry.encrypted_content
        if not isinstance(ciphertext, str) or len(ciphertext) > 350000:
            return None
        document = json.loads(_cipher().decrypt(ciphertext.encode()))
        if document.get("input_hash") != entry.input_hash or not entry.input_hash:
            return None
        safe = PrivateMailBriefResponse.model_validate(document["brief"])
        if safe.state != "ready":
            return None
        result = safe.model_dump(exclude_none=True)
        if not body:
            result.pop("original_body", None)
            # Source quotations belong in the selected detail, not list payloads.
            result["source_evidence"] = []
            if result.get("deadline"):
                result["deadline"].pop("evidence", None)
        return result
    except (InvalidToken, ValueError, TypeError, KeyError, AttributeError, ValidationError, HTTPException):
        return None


async def owned_mail(db, owner_id, item_id):
    row = (await db.execute(select(PrivateItem).where(
        PrivateItem.id == item_id, PrivateItem.owner_id == owner_id,
    ).execution_options(populate_existing=True))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "未找到此私人邮件")
    if row.source_id != "gmail":
        raise HTTPException(409, "仅支持整理 Gmail 邮件")
    return row


def _context(connection, row):
    if not connection or connection.status != "connected" or not connection.encrypted_credentials:
        raise gmail.ProviderError("authorization_expired")
    metadata = connection.metadata_json or {}
    mailbox = metadata.get("account_label")
    if not isinstance(mailbox, str) or metadata.get("read_only_adapter") is not True:
        raise gmail.ProviderError("authorization_expired")
    gmail._check_gmail_account(mailbox)
    # Gmail message IDs identify immutable content. Use the original imported
    # fields, never owner's editable title/summary, to find a prior full brief.
    plan = provider.prepare_mail_brief(row.title, (row.summary or "")[:1000])
    model = provider.model_identifier()
    identity = provider.brief_cache_key(str(row.owner_id), mailbox, connection.generation,
                                       row.external_id, plan.source_hash, model)
    key = hashlib.sha256(f"{connection.id}:{identity}:body".encode()).hexdigest()
    return {"key": key, "owner_id": row.owner_id, "item_id": row.id,
            "connection_id": connection.id, "generation": connection.generation,
            "source_hash": plan.source_hash, "model": model, "plan": plan,
            "credentials": connection.encrypted_credentials, "metadata": dict(metadata),
            "title": row.title, "summary": row.summary, "message_id": row.external_id}


def _live_context(context):
    # Immutable scalars also work after rollback expires SQLAlchemy instances.
    return and_(exists(select(PrivateConnection.id).where(
        PrivateConnection.id == context["connection_id"], PrivateConnection.owner_id == context["owner_id"],
        PrivateConnection.source_id == "gmail", PrivateConnection.generation == context["generation"],
        PrivateConnection.status == "connected", PrivateConnection.encrypted_credentials.is_not(None),
        PrivateConnection.metadata_json["account_label"].as_string() == context["metadata"]["account_label"],
        PrivateConnection.metadata_json["read_only_adapter"].as_boolean().is_(True),
    )), exists(select(PrivateItem.id).where(
        PrivateItem.id == context["item_id"], PrivateItem.owner_id == context["owner_id"],
        PrivateItem.source_id == "gmail", PrivateItem.external_id == context["message_id"],
        PrivateItem.title == context["title"], PrivateItem.summary == context["summary"],
    )))


async def _claim(db, context):
    token = secrets.token_hex(24)
    now = utcnow()
    values = {"cache_key": context["key"], "owner_id": context["owner_id"],
              "connection_id": context["connection_id"], "generation": context["generation"],
              "item_id": context["item_id"], "source_hash": context["source_hash"], "model": context["model"],
              "state": "pending", "lease_token": token, "lease_until": now + timedelta(seconds=120)}
    await db.execute(_insert(db, PrivateMailBrief).values(**values).on_conflict_do_nothing(index_elements=["cache_key"]))
    entry = (await db.execute(select(PrivateMailBrief).where(
        PrivateMailBrief.cache_key == context["key"], PrivateMailBrief.owner_id == context["owner_id"],
    ).execution_options(populate_existing=True))).scalar_one()
    if entry.state == "ready":
        cached = _decrypt(entry, body=True)
        if cached:
            await db.commit()
            return None, cached, None
        entry.state, entry.lease_until = "failed", None
        await db.flush()
    if entry.lease_token == token:
        await db.commit()
        return token, None, None
    if entry.lease_until and _aware(entry.lease_until) > now:
        state, code = entry.state, entry.error_code
        await db.commit()
        return None, _empty(state), code
    changed = await db.execute(update(PrivateMailBrief).where(
        PrivateMailBrief.cache_key == context["key"], PrivateMailBrief.state != "ready",
        or_(PrivateMailBrief.lease_until.is_(None), PrivateMailBrief.lease_until <= now),
    ).values(state="pending", lease_token=token, lease_until=values["lease_until"], error_code=None))
    await db.commit()
    return (token, None, None) if changed.rowcount else (None, _empty("pending"), None)


async def reserve_usage(db, owner_id, count, *, reservation_micro_usd, price_policy, context=None, token=None):
    """Reserve character, request and USD limits in one conditional UPDATE."""
    character_limit, request_limit = provider.monthly_limit(), provider.monthly_request_limit()
    budget = provider.monthly_budget_micro_usd()
    if type(count) is not int or not 0 <= count <= provider.MAX_INPUT_CHARACTERS:
        raise provider.MailBriefError("invalid_input")
    model = provider.model_identifier()
    required = provider._price_micro_usd(provider.MODEL_PRICES[model]['context_tokens'], provider.MAX_OUTPUT_TOKENS, model)
    if (type(reservation_micro_usd) is not int or reservation_micro_usd != required
            or price_policy != provider.PRICE_POLICY):
        raise provider.MailBriefError('budget_not_reserved')
    if context is not None and (context['owner_id'] != owner_id or not isinstance(token, str)):
        raise provider.MailBriefError('invalid_input')
    now = utcnow()
    month = now.strftime("%Y-%m")
    if context is not None:
        context['reservation_month'] = month
    await db.execute(_insert(db, PrivateMailBriefUsage).values(
        owner_id=owner_id, month=month, characters=0, requests=0, reserved_usd_micros=0)
                     .on_conflict_do_nothing(index_elements=["owner_id", "month"]))
    # Defense in depth for rows seeded by old code after the schema hook.
    await db.execute(update(PrivateMailBriefUsage).where(
        PrivateMailBriefUsage.owner_id == owner_id, PrivateMailBriefUsage.month == month,
        or_(PrivateMailBriefUsage.characters != 0, PrivateMailBriefUsage.requests != 0),
        or_(PrivateMailBriefUsage.reserved_usd_micros == 0, PrivateMailBriefUsage.reserved_usd_micros.is_(None)),
    ).values(reserved_usd_micros=provider.MAX_MONTHLY_BUDGET_MICRO_USD))
    predicates = [
        PrivateMailBriefUsage.owner_id == owner_id, PrivateMailBriefUsage.month == month,
        PrivateMailBriefUsage.characters >= 0, PrivateMailBriefUsage.requests >= 0,
        PrivateMailBriefUsage.reserved_usd_micros >= 0,
        PrivateMailBriefUsage.characters + count <= character_limit,
        PrivateMailBriefUsage.requests + 1 <= request_limit,
        PrivateMailBriefUsage.reserved_usd_micros + reservation_micro_usd <= budget,
    ]
    if context is not None:
        predicates.extend([_live_context(context), exists(select(PrivateMailBrief.cache_key).where(
            PrivateMailBrief.cache_key == context['key'], PrivateMailBrief.owner_id == owner_id,
            PrivateMailBrief.lease_token == token, PrivateMailBrief.state == 'pending',
            PrivateMailBrief.lease_until > now,
        ))])
    changed = await db.execute(update(PrivateMailBriefUsage).where(
        *predicates,
    ).values(characters=PrivateMailBriefUsage.characters + count, requests=PrivateMailBriefUsage.requests + 1,
             reserved_usd_micros=PrivateMailBriefUsage.reserved_usd_micros + reservation_micro_usd))
    if changed.rowcount and context is not None:
        receipt = await db.execute(update(PrivateMailBrief).where(
            PrivateMailBrief.cache_key == context['key'], PrivateMailBrief.owner_id == owner_id,
            PrivateMailBrief.lease_token == token, PrivateMailBrief.state == 'pending',
            PrivateMailBrief.lease_until > now,
        ).values(reservation_month=month, reservation_micro_usd=reservation_micro_usd,
                 reservation_price_policy=price_policy, reservation_state='held'))
        if not receipt.rowcount:
            await db.rollback()
            return False
    await db.commit()
    return bool(changed.rowcount)


def _settlement(entry, billing):
    """Validate the receipt independently of provider output; return a refund."""
    if (not isinstance(billing, dict) or billing.get('usage_verified') is not True
            or billing.get('price_policy') != provider.PRICE_POLICY
            or entry.reservation_state != 'held' or entry.reservation_price_policy != provider.PRICE_POLICY
            or not isinstance(entry.reservation_month, str)
            or re.fullmatch(r'[0-9]{4}-(?:0[1-9]|1[0-2])', entry.reservation_month) is None): return None
    amount = entry.reservation_micro_usd
    if (type(amount) is not int or not 1 <= amount <= provider.MAX_MONTHLY_BUDGET_MICRO_USD
            or type(billing.get('reservation_micro_usd')) is not int
            or billing['reservation_micro_usd'] != amount): return None
    model = entry.model
    policy = provider.MODEL_PRICES.get(model)
    input_tokens = billing.get('input_tokens'); output_tokens = billing.get('output_tokens')
    if (not policy or type(input_tokens) is not int or not 1 <= input_tokens <= policy['context_tokens']
            or type(output_tokens) is not int or not 1 <= output_tokens <= provider.MAX_OUTPUT_TOKENS): return None
    cost = provider._price_micro_usd(input_tokens, output_tokens, model)
    if type(billing.get('settlement_micro_usd')) is not int or billing['settlement_micro_usd'] != cost or cost > amount:
        return None
    return amount - cost


async def _finish(db, context, token, result=None, input_hash=None, code=None, billing=None):
    refund = None; entry = None
    if result:
        entry = (await db.execute(select(PrivateMailBrief).where(
            PrivateMailBrief.cache_key == context['key'], PrivateMailBrief.owner_id == context['owner_id'],
            PrivateMailBrief.lease_token == token,
        ).execution_options(populate_existing=True))).scalar_one_or_none()
        if entry:
            refund = _settlement(entry, billing)
    values = dict(state="ready" if result else "failed", input_hash=input_hash,
                  encrypted_content=_encrypt(result, input_hash) if result else None,
                  error_code=code, lease_token=None,
                  lease_until=None if result else utcnow() + timedelta(seconds=30))
    if refund is not None:
        values['reservation_state'] = 'settled'
    changed = await db.execute(update(PrivateMailBrief).where(
        PrivateMailBrief.cache_key == context["key"], PrivateMailBrief.owner_id == context["owner_id"],
        PrivateMailBrief.lease_token == token, _live_context(context),
    ).values(**values))
    if changed.rowcount and refund is not None:
        settled = await db.execute(update(PrivateMailBriefUsage).where(
            PrivateMailBriefUsage.owner_id == context['owner_id'], PrivateMailBriefUsage.month == entry.reservation_month,
            PrivateMailBriefUsage.reserved_usd_micros >= refund, PrivateMailBriefUsage.requests >= 1,
        ).values(reserved_usd_micros=PrivateMailBriefUsage.reserved_usd_micros - refund))
        if not settled.rowcount:
            await db.rollback()
            return False
    await db.commit()
    return bool(changed.rowcount)


async def budget_snapshot(db, owner_id):
    """Safe owner-only monetary DTO, never provider payloads or credentials."""
    month = utcnow().strftime('%Y-%m')
    try:
        limit = provider.monthly_budget_micro_usd()
    except provider.MailBriefError:
        return {'configured': False, 'month': month, 'limit_usd': '0.00',
                'reserved_usd': '0.00', 'remaining_usd': '0.00'}
    row = (await db.execute(select(PrivateMailBriefUsage).where(
        PrivateMailBriefUsage.owner_id == owner_id, PrivateMailBriefUsage.month == month,
    ))).scalar_one_or_none()
    reserved = row.reserved_usd_micros if row else 0
    if row and reserved == 0 and (row.characters != 0 or row.requests != 0):
        # A legacy unpriced row is not a fresh free allowance even before the
        # next reservation/migration. This read-only DTO stays conservative.
        reserved = provider.MAX_MONTHLY_BUDGET_MICRO_USD
    if type(reserved) is not int or reserved < 0:
        return {'configured': False, 'month': month, 'limit_usd': '0.00',
                'reserved_usd': '0.00', 'remaining_usd': '0.00'}
    def dollars(micros, *, round_up=False):
        cents = (micros + 9999) // 10000 if round_up else micros // 10000
        return f'{cents // 100}.{cents % 100:02d}'
    return {'configured': provider.configured(), 'month': month,
            'limit_usd': dollars(limit), 'reserved_usd': dollars(reserved, round_up=True),
            'remaining_usd': dollars(max(0, limit - reserved))}


async def _reservation_failure_code(db, owner_id, month, amount):
    # This only explains a refusal. The conditional UPDATE is the budget gate.
    row = (await db.execute(select(PrivateMailBriefUsage).where(
        PrivateMailBriefUsage.owner_id == owner_id, PrivateMailBriefUsage.month == month,
    ))).scalar_one_or_none()
    held = row.reserved_usd_micros if row else 0
    if type(held) is not int or held < 0 or held + amount > provider.monthly_budget_micro_usd():
        return 'budget_exhausted'
    return 'limit_reached'


def _public_error(exc):
    code = getattr(exc, "code", "upstream_unavailable")
    if isinstance(exc, gmail.ProviderError) and code in {"authorization_expired", "access_denied"}:
        return "authorization_expired"
    if code == "quota_exceeded":
        return "limit_reached"
    if code == "not_configured":
        return code
    if code == 'budget_month_changed':
        return code
    return "upstream_unavailable"


def _importance(row, preferences):
    bucket = item_response(row, preferences).get("mail_relevance", {}).get("bucket")
    return {"urgent": "urgent", "today": "today", "digest": "read", "low": "read"}.get(bucket, "uncertain")


def _result(brief, plan, importance):
    evidence = list(dict.fromkeys([*brief["source_evidence"],
                                  *(point["evidence"] for point in brief["key_points"]),
                                  *([brief["action_evidence"]] if brief["action_evidence"] else [])]))[:12]
    deadline = ({"at": None, "text": brief["deadline_text"], "confirmed": False,
                 "evidence": brief["deadline_evidence"]} if brief["deadline_text"] else None)
    return PrivateMailBriefResponse(state="ready", title_zh=brief["title_zh"], summary_zh=brief["summary_zh"],
        key_points=[point["text_zh"] for point in brief["key_points"]], relevance=brief["why_it_matters"],
        next_action=brief["action_hint"], needs_action=brief["needs_action"], deadline=deadline,
        importance=importance, source_scope="body" if plan.body else "preview", source_evidence=evidence,
        original_body=plan.body, truncated=plan.partial,
        evidence_limited=brief.get("evidence_limited") is True,
        updated_at=brief["generated_at"]).model_dump(exclude_none=True)


async def brief_item(db, owner_id, item_id, *, mode="body"):
    if mode != "body":
        raise HTTPException(422, "整理模式无效")
    row = await owned_mail(db, owner_id, item_id)
    enabled = provider.configured()
    response = {"configured": enabled, "item_id": row.id, "brief": _empty()}
    if not enabled:
        return {**response, "code": "not_configured"}
    connection = await connection_for(db, owner_id, "gmail")
    try:
        context = _context(connection, row)
    except (gmail.ProviderError, provider.MailBriefError) as exc:
        return {**response, "code": _public_error(exc)}
    importance = _importance(row, await stored_preferences_for(db, owner_id))
    token, cached, code = await _claim(db, context)
    if cached:
        if not (await db.execute(select(_live_context(context)))).scalar_one():
            return {**response, "code": "authorization_expired"}
        cached["importance"] = importance
        return {**response, "brief": cached, **({"code": code} if code else {})}
    try:
        async with asyncio.timeout(55):
            content = await gmail.fetch_mail_content(decrypt_credentials(context["credentials"]),
                                                    context["metadata"], context["message_id"])
            if content.get("credentials"):
                await db.execute(update(PrivateConnection).where(
                    PrivateConnection.id == context["connection_id"], PrivateConnection.owner_id == owner_id,
                    PrivateConnection.generation == context["generation"], PrivateConnection.status == "connected",
                    PrivateConnection.encrypted_credentials == context["credentials"],
                ).values(encrypted_credentials=encrypt_credentials(content["credentials"])))
                await db.commit()
            plan = provider.prepare_mail_brief(content["title"], content["summary"],
                content["body"] if content["has_body"] else None, body_truncated=content["truncated"])
            # The provider rechecks enabled + consent itself immediately before
            # HTTP. Do not reserve any usage on a stale connection/source.
            if not (await db.execute(select(_live_context(context)))).scalar_one():
                raise gmail.ProviderError("authorization_expired")
            if not provider.configured():
                raise provider.MailBriefError("not_configured")
            reservation = provider.preflight_reservation(plan)
            if not await reserve_usage(db, owner_id, plan.character_count,
                                       reservation_micro_usd=reservation['reservation_micro_usd'],
                                       price_policy=reservation['price_policy'], context=context, token=token):
                code = await _reservation_failure_code(db, owner_id, context['reservation_month'],
                                                       reservation['reservation_micro_usd'])
                await _finish(db, context, token, code=code)
                return {**response, "brief": _empty("failed"), "code": code}
            # End the prior transaction BEFORE the final authorization check.
            # Do not yield for a separate commit after checking and before
            # entering the provider. In-flight HTTP cannot be recalled later.
            await db.commit()
            now = utcnow()
            current_claim = exists(select(PrivateMailBrief.cache_key).where(
                PrivateMailBrief.cache_key == context['key'], PrivateMailBrief.owner_id == owner_id,
                PrivateMailBrief.lease_token == token, PrivateMailBrief.state == 'pending',
                PrivateMailBrief.lease_until > now, PrivateMailBrief.reservation_state == 'held',
                PrivateMailBrief.reservation_month == context['reservation_month'],
                PrivateMailBrief.reservation_micro_usd == reservation['reservation_micro_usd'],
                PrivateMailBrief.reservation_price_policy == reservation['price_policy'],
            ))
            if not (await db.execute(select(and_(_live_context(context), current_claim)))).scalar_one():
                raise gmail.ProviderError("authorization_expired")
            if utcnow().strftime('%Y-%m') != context['reservation_month']:
                raise provider.MailBriefError('budget_month_changed')
            brief = await provider.brief_mail(plan,
                reserved_micro_usd=reservation['reservation_micro_usd'], price_policy=reservation['price_policy'])
            result = _result(brief, plan, importance)
            if not await _finish(db, context, token, result=result, input_hash=plan.source_hash, billing=brief.get('billing')):
                return {**response, "code": "authorization_expired"}
            return {**response, "brief": result}
    except (provider.MailBriefError, gmail.ProviderError, HTTPException, TimeoutError, ValidationError) as exc:
        code = _public_error(exc)
        await db.rollback()
        await _finish(db, context, token, code=code)
        return {**response, "brief": _empty("failed"), "code": code}


async def attach_cached_previews(db, owner_id, items):
    # Off, unconsented or missing credentials never causes network or cache work.
    if not provider.configured():
        return items
    ids = [item["id"] for item in items if item["source_id"] == "gmail"]
    if not ids:
        return items
    connection = await connection_for(db, owner_id, "gmail")
    rows = (await db.execute(select(PrivateItem).where(
        PrivateItem.owner_id == owner_id, PrivateItem.id.in_(ids), PrivateItem.source_id == "gmail",
    ).execution_options(populate_existing=True))).scalars().all()
    keys, cache_conditions = {}, []
    preferences = await stored_preferences_for(db, owner_id)
    for row in rows:
        try:
            context = _context(connection, row)
            keys[context["key"]] = (row.id, _importance(row, preferences))
            cache_conditions.append(and_(PrivateMailBrief.cache_key == context["key"], _live_context(context)))
        except (gmail.ProviderError, provider.MailBriefError):
            continue
    if not keys:
        return items
    entries = (await db.execute(select(PrivateMailBrief).where(
        PrivateMailBrief.owner_id == owner_id, PrivateMailBrief.cache_key.in_(keys),
        PrivateMailBrief.state == "ready", or_(*cache_conditions),
    ))).scalars().all()
    by_id = {}
    for entry in entries:
        brief = _decrypt(entry)
        if brief:
            item_id, importance = keys[entry.cache_key]
            brief["importance"] = importance
            by_id[item_id] = brief
    for item in items:
        if item["id"] in by_id:
            item["mail_brief"] = by_id[item["id"]]
    return items
