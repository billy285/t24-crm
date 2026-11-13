"""Owner-confirmed company statement matches; never create income or move money."""
import asyncio
import copy
import csv
import hashlib
import io
import itertools
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import select

from models.stripe_history_reconciliation import StripeHistoryAudit as Audit, StripeHistoryInvoiceReview as Review, StripeHistoryPosting as Posting, StripeHistoryPreview as Preview
from services import stripe_history_provider as provider
from services.sales_payment_catalog import STRIPE_ACCOUNT_ID
from services.sales_workflow_locks import lock_sales_workflow
from services.stripe_history_reconciliation import owner

STATEMENT_KIND = "bank_statement_match_preview"
MATCH_KIND = "bank_payout_confirmation_preview"
MAX_CSV_BYTES = 1_048_576
MAX_ROWS = 1000
MAX_PAYOUT_PAGES = 50


def now():
    return datetime.now(timezone.utc)


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def reject(message):
    raise HTTPException(409, message)


def csv_rows(content):
    if not isinstance(content, str) or not content.strip() or len(content.encode("utf-8")) > MAX_CSV_BYTES:
        raise HTTPException(422, "请上传不超过 1 MB、首行为列名的 UTF-8 CSV 公司银行流水")
    try:
        rows = list(itertools.islice(csv.reader(io.StringIO(content.lstrip("\ufeff")), strict=True), MAX_ROWS + 2))
    except (csv.Error, UnicodeError):
        raise HTTPException(422, "CSV 格式无法读取，请使用银行导出的 UTF-8 CSV 流水")
    if len(rows) < 2 or len(rows) > MAX_ROWS + 1 or not 2 <= len(rows[0]) <= 40:
        raise HTTPException(422, "流水需有列名和数据，最多 1000 行、40 列")
    headers = [value.strip() for value in rows[0]]
    if any(not value or len(value) > 80 for value in headers) or len(set(headers)) != len(headers):
        raise HTTPException(422, "CSV 列名不能为空或重复，且每个列名不得超过 80 字")
    for row in rows[1:]:
        if row and (len(row) != len(headers) or any(len(value) > 1000 for value in row)):
            raise HTTPException(422, "流水列数不一致或单项文字过长，请检查 CSV")
    return headers, rows[1:]


async def inspect_statement(db, user, value):
    await owner(db, user)
    headers, rows = csv_rows(value.csv_text)
    return {"headers": headers, "sample": rows[:3], "row_count": len(rows), "currency": "USD", "writes_ledger": False}


def amount_minor(value):
    text = value.strip()
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    if not re.fullmatch(r"-?\$?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d{1,2})?", text) or (negative and text.startswith("-")):
        raise HTTPException(422, "金额列需使用美元格式，如 208.83 或 $1,208.83；不支持小数逗号")
    text = ("-" if negative else "") + text.replace(",", "").replace("$", "")
    try:
        number = Decimal(text)
    except InvalidOperation:
        raise HTTPException(422, "金额列含无法识别的数值；入账为正数、支出为负数")
    if not number.is_finite() or abs(number) > Decimal("1000000000") or number * 100 != (number * 100).to_integral_value():
        raise HTTPException(422, "流水金额需为有效美元金额，最多两位小数")
    return int(number * 100)


async def preview_statement(db, user, value):
    await owner(db, user)
    headers, source = csv_rows(value.csv_text)
    selected = [value.date_column, value.amount_column, value.description_column]
    if value.reference_column:
        selected.append(value.reference_column)
    if len(set(selected)) != len(selected) or any(name not in headers for name in selected):
        raise HTTPException(422, "日期、金额、摘要和流水编号需选择不同的有效列")
    columns = {name: headers.index(name) for name in selected}
    rows = []
    for index, row in enumerate(source, start=2):
        if not row:
            continue
        try:
            day = datetime.strptime(row[columns[value.date_column]].strip(), "%Y-%m-%d" if value.date_format == "ymd" else "%m/%d/%Y").date()
        except ValueError:
            raise HTTPException(422, f"第 {index} 行日期与所选格式不一致")
        amount = amount_minor(row[columns[value.amount_column]])
        if amount <= 0:
            continue
        description = row[columns[value.description_column]].strip()
        reference = row[columns[value.reference_column]].strip() if value.reference_column else ""
        if len(description) > 500 or len(reference) > 180 or day > now().date():
            raise HTTPException(422, f"第 {index} 行日期或流水文字需核对")
        item = {"row_index": index, "date": day.isoformat(), "amount_minor": amount,
            "currency": "USD", "description": description, "reference": reference}
        item["fingerprint"] = digest({"account": value.account_label.casefold(), **{key: item[key] for key in ("date", "amount_minor", "currency", "description", "reference")}})
        rows.append(item)
    if not rows:
        raise HTTPException(422, "未找到正数美元入账行，请核对金额列与日期格式")
    counts = {}
    for row in rows:
        counts[row["fingerprint"]] = counts.get(row["fingerprint"], 0) + 1
    for row in rows:
        row["ambiguous"] = counts[row["fingerprint"]] > 1
    token = secrets.token_urlsafe(32)
    snapshot = {"kind": STATEMENT_KIND, "account_label": value.account_label, "currency": "USD",
        "file_sha256": hashlib.sha256(value.csv_text.encode("utf-8")).hexdigest(), "rows": rows}
    expires = now() + timedelta(hours=24)
    db.add(Preview(token=token, actor_id=int(user.id), snapshot=snapshot, expires_at=expires))
    await db.commit()
    return {"token": token, "expires_at": expires, **snapshot, "writes_ledger": False}


async def preview_record(db, user, token, kind):
    record = await db.get(Preview, token, populate_existing=True)
    if not record or record.actor_id != int(user.id) or utc(record.expires_at) <= now() or not isinstance(record.snapshot, dict) or record.snapshot.get("kind") != kind:
        reject("预览不存在、已过期或用途不符，请重新核对")
    return copy.deepcopy(record.snapshot)


def payout_summary(raw, *, allow_noncredit=False):
    if raw.get("object") != "payout" or raw.get("livemode") is not True or not re.fullmatch(r"po_[A-Za-z0-9_]{1,220}", str(raw.get("id", ""))) or type(raw.get("amount")) is not int or (raw["amount"] <= 0 and not allow_noncredit) or raw.get("currency") != "usd" or type(raw.get("arrival_date")) is not int:
        reject("当前仅支持正式账户的美元银行结算，请保留其他币种人工核对")
    try:
        arrival = datetime.fromtimestamp(raw["arrival_date"], timezone.utc).date().isoformat()
    except (ValueError, OverflowError, OSError):
        reject("Stripe 结算日期无法核验")
    evidence_scope = None
    if raw["amount"] > 0 and raw.get("status") == "paid" and raw.get("type") == "bank_account":
        if raw.get("automatic") is True and raw.get("reconciliation_status") == "completed":
            evidence_scope = "complete_transactions"
        elif raw.get("automatic") is False:
            evidence_scope = "payout_only"
    result = {"id": raw["id"], "amount_minor": raw["amount"], "currency": "USD", "arrival_date": arrival,
        "status": raw.get("status"), "automatic": raw.get("automatic") is True,
        "bank_destination": raw.get("destination") if isinstance(raw.get("destination"), str) else None,
        "eligible": evidence_scope is not None}
    if evidence_scope is not None:
        result["evidence_scope"] = evidence_scope
    return result


async def payouts(db, user, starting_after=None):
    await owner(db, user)
    try:
        rows, more = await asyncio.wait_for(provider.reader().payouts(starting_after), timeout=45)
    except asyncio.TimeoutError:
        raise HTTPException(503, "Stripe 读取暂时超时，请稍后重试；未写入到账匹配或财务账本")
    items = []
    excluded_noncredit_count = 0
    for raw in rows:
        if raw.get("currency") == "usd":
            item = payout_summary(raw, allow_noncredit=True)
            if item["amount_minor"] <= 0:
                excluded_noncredit_count += 1
            else:
                items.append(item)
    return {"items": items, "has_more": more, "next_cursor": rows[-1]["id"] if more and rows else None,
        "excluded_noncredit_count": excluded_noncredit_count, "read_only": True, "bank_deposit_proven": False}


async def payout_evidence(payout_id):
    reader = provider.reader()
    raw = await reader.payout(payout_id)
    summary = payout_summary(raw)
    if not summary["eligible"]:
        reject("仅已汇出的正数银行结算可匹配；自动结算还需明细核对完成，其他结算请人工核对")
    if summary["evidence_scope"] == "payout_only":
        # Stripe cannot attribute Balance Transactions to a manual payout.
        # Match only the bank batch amount; never infer or link its receipts.
        if payout_summary(await reader.payout(payout_id)) != summary:
            reject("读取期间 Stripe 结算状态发生变化，请重新核对")
        return {"account_id": STRIPE_ACCOUNT_ID, "payout": summary, "evidence_scope": "payout_only", "transactions": []}
    transactions = []
    seen = set()
    cursor = None
    for _ in range(MAX_PAYOUT_PAGES):
        rows, more = await reader.payout_transactions(payout_id, cursor)
        if more and not rows:
            reject("Stripe 结算明细不完整，请稍后重试")
        for row in rows:
            key = row.get("id")
            if not re.fullmatch(r"txn_[A-Za-z0-9_]{1,220}", str(key or "")) or key in seen or row.get("currency") != "usd" or row.get("status") != "available" or type(row.get("net")) is not int or row.get("type") == "payout":
                reject("Stripe 结算明细重复或币种、状态需核对")
            seen.add(key)
            transactions.append({"id": key, "net_minor": row["net"], "type": row.get("type"),
                "source": row.get("source") if isinstance(row.get("source"), str) else None})
        if not more:
            break
        cursor = rows[-1]["id"]
    else:
        reject("此批结算明细超出本次读取范围，请人工核对")
    if not transactions or sum(item["net_minor"] for item in transactions) != summary["amount_minor"]:
        reject("Stripe 完整结算明细与结算金额不一致，不能确认到账匹配")
    # A second read catches status/amount changes while reading paginated details.
    if payout_summary(await reader.payout(payout_id)) != summary:
        reject("读取期间 Stripe 结算状态发生变化，请重新核对")
    return {"account_id": STRIPE_ACCOUNT_ID, "payout": summary, "evidence_scope": "complete_transactions", "transactions": sorted(transactions, key=lambda row: row["id"])}


async def read_evidence(payout_id):
    try:
        return await asyncio.wait_for(payout_evidence(payout_id), timeout=45)
    except asyncio.TimeoutError:
        raise HTTPException(503, "Stripe 读取暂时超时，请稍后重新核对；未写入到账匹配或财务账本")


async def audit_rows(db):
    return list((await db.scalars(select(Audit).where(Audit.action.in_(("bank_match_confirmed", "bank_match_voided"))).order_by(Audit.id.desc()))).all())


def active_matches(rows):
    voided = {row.details.get("match_id") for row in rows if row.action == "bank_match_voided"}
    return [row for row in rows if row.action == "bank_match_confirmed" and row.id not in voided]


def match_data(row):
    value = row.details
    return {"id": row.id, "payout_id": value["payout"]["id"], "amount_minor": value["payout"]["amount_minor"],
        "currency": "USD", "account_label": value["account_label"], "bank_date": value["bank_row"]["date"],
        "bank_reference": value["bank_row"]["reference"], "review_ids": value.get("review_ids", []),
        "payment_ids": value.get("payment_ids", []), "confirmed_at": row.created_at, "confirmed_by": row.actor_name,
        "status": "statement_manually_matched", "evidence_scope": value.get("evidence_scope", "unknown"),
        "note": value["note"], "file_sha256": value["file_sha256"]}


async def overview(db, user):
    await owner(db, user)
    rows = active_matches(await audit_rows(db))
    return {"items": [match_data(row) for row in rows[:100]], "total": len(rows), "currency": "USD",
        "bank_connection": "statement_upload", "provider_writes": False, "ledger_writes": False}


async def preview_match(db, user, value):
    await owner(db, user)
    statement = await preview_record(db, user, value.statement_token, STATEMENT_KIND)
    bank_row = next((row for row in statement["rows"] if row["row_index"] == value.row_index), None)
    if not bank_row or bank_row["ambiguous"]:
        reject("此流水行不存在或与其他行重复，请提供可区分的银行流水编号")
    await db.rollback()
    evidence = await read_evidence(value.payout_id)
    payout = evidence["payout"]
    if bank_row["amount_minor"] != payout["amount_minor"] or abs((datetime.fromisoformat(bank_row["date"]) - datetime.fromisoformat(payout["arrival_date"])).days) > 10:
        reject("流水金额或日期与 Stripe 结算不匹配，请人工核对")
    await owner(db, user)
    current = await preview_record(db, user, value.statement_token, STATEMENT_KIND)
    if digest(current) != digest(statement):
        reject("银行流水预览已变化，请重新核对")
    snapshot = {"kind": MATCH_KIND, "statement_token": value.statement_token, "account_label": statement["account_label"],
        "file_sha256": statement["file_sha256"], "bank_row": bank_row, "evidence": evidence, "evidence_fingerprint": digest(evidence)}
    token = secrets.token_urlsafe(32)
    db.add(Preview(token=token, actor_id=int(user.id), snapshot=snapshot, expires_at=now() + timedelta(minutes=10)))
    await db.commit()
    return {"token": token, "payout": payout, "bank_row": bank_row, "transaction_count": len(evidence["transactions"]),
        "evidence_scope": evidence["evidence_scope"], "account_label": statement["account_label"],
        "writes_ledger": False, "requires_owner_confirmation": True}


async def confirm_match(db, user, value):
    await owner(db, user)
    rows = await audit_rows(db)
    previous = next((row for row in rows if row.action == "bank_match_confirmed" and row.details.get("preview_token") == value.token), None)
    if previous:
        if previous.actor_id != int(user.id):
            reject("此确认预览属于另一操作人，请使用自己的银行流水预览")
        if previous not in active_matches(rows):
            reject("此匹配已撤回，请重新预览后核对")
        return {"item": match_data(previous), "idempotent_replay": True, "ledger_writes": False}
    snapshot = await preview_record(db, user, value.token, MATCH_KIND)
    await db.rollback()
    evidence = await read_evidence(snapshot["evidence"]["payout"]["id"])
    if digest(evidence) != snapshot["evidence_fingerprint"]:
        reject("Stripe 结算依据已变化，请重新预览")
    await lock_sales_workflow(db)
    await owner(db, user)
    current = await preview_record(db, user, value.token, MATCH_KIND)
    if digest(current) != digest(snapshot):
        reject("确认依据已变化，请重新预览")
    rows = await audit_rows(db)
    active = active_matches(rows)
    for item in active:
        details = item.details
        if details.get("preview_token") == value.token:
            result = match_data(item)
            await db.rollback()
            return {"item": result, "idempotent_replay": True, "ledger_writes": False}
        same_line = details.get("file_sha256") == snapshot["file_sha256"] and details["bank_row"]["row_index"] == snapshot["bank_row"]["row_index"]
        if details["payout"]["id"] == evidence["payout"]["id"] or same_line or details["bank_row"]["fingerprint"] == snapshot["bank_row"]["fingerprint"]:
            reject("此结算批次或银行流水已有匹配记录，请核对原记录")
    balances = {row["id"] for row in evidence["transactions"]}
    linked = []
    if evidence["evidence_scope"] == "complete_transactions":
        posted = (await db.execute(select(Review, Posting).join(Posting, Posting.review_id == Review.id).where(
            Review.account_id == STRIPE_ACCOUNT_ID, Review.livemode.is_(True)))).all()
        by_balance = {item["id"]: item for item in evidence["transactions"]}
        for review, posting in posted:
            transaction = by_balance.get(review.snapshot.get("balance_transaction_id"))
            if (transaction and not review.needs_refresh and not review.snapshot.get("issues")
                    and review.fingerprint == posting.fingerprint
                    and review.snapshot.get("stripe_charge_id") == posting.stripe_charge_id == transaction["source"]
                    and transaction["type"] in {"charge", "payment"} and transaction["net_minor"] > 0
                    and review.snapshot.get("net_minor") == transaction["net_minor"]):
                linked.append((review.id, posting.payment_id))
    details = {"preview_token": value.token, "account_id": STRIPE_ACCOUNT_ID, "payout": evidence["payout"],
        "evidence_fingerprint": digest(evidence), "evidence_scope": evidence["evidence_scope"],
        "transaction_ids": sorted(balances), "account_label": snapshot["account_label"],
        "file_sha256": snapshot["file_sha256"], "bank_row": snapshot["bank_row"], "note": value.note,
        "review_ids": sorted(review for review, _ in linked), "payment_ids": sorted(payment for _, payment in linked)}
    audit = Audit(actor_id=int(user.id), actor_name=user.name, action="bank_match_confirmed", details=details)
    db.add(audit)
    await db.flush()
    result = match_data(audit)
    await db.commit()
    return {"item": result, "idempotent_replay": False, "ledger_writes": False}


async def void_match(db, user, match_id, value):
    await lock_sales_workflow(db)
    await owner(db, user)
    rows = await audit_rows(db)
    row = next((row for row in rows if row.id == match_id and row.action == "bank_match_confirmed"), None)
    if not row:
        raise HTTPException(404, "匹配记录不存在")
    if row not in active_matches(rows):
        return {"id": row.id, "status": "voided", "idempotent_replay": True, "ledger_writes": False}
    db.add(Audit(actor_id=int(user.id), actor_name=user.name, action="bank_match_voided", details={"match_id": row.id, "note": value.note}))
    await db.commit()
    return {"id": row.id, "status": "voided", "idempotent_replay": False, "ledger_writes": False}
