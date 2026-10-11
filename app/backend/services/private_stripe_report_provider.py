"""Read-only, account-bound Stripe cash activity for private income reports.

Amounts and dates come from balance transactions, in settlement currency minor
units. Charge/refund/invoice reads establish eligibility and association; an
invoice marked paid, a subscription price, or a payout is never income evidence.
No provider response, credential, or arbitrary provider URL leaves this adapter.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from services.private_workspace_providers import (
    ProviderError, _Client, _currency, _date, _integer, _stripe_identity,
    _stripe_key, _stripe_livemode, _stripe_mode, _stripe_resource_id,
    _stripe_resource_mode, _text, stripe_expected_identity,
)

# This version retains the documented invoice.charge/invoice.subscription and
# charge.invoice fields. Only report requests are pinned.
# https://docs.stripe.com/api/invoices/object?api-version=2024-06-20
# https://docs.stripe.com/api/charges/object?api-version=2024-06-20
STRIPE_REPORT_API_VERSION = '2024-06-20'
PAGE_SIZE = 100
MAX_BALANCE_TRANSACTIONS = 2000
MAX_SUBSCRIPTIONS = 500
MAX_ATTENTION_INVOICES = 500
MAX_PERIOD_OBSERVATIONS = 500

_PARTIAL_ERRORS = {'access_denied', 'sync_limit', 'upstream_timeout', 'rate_limited', 'upstream_unavailable'}
_BUDGET_ERRORS = {'sync_limit', 'upstream_timeout'}
_WARNING_MESSAGES = {
    'record_limit': '已达到读取记录上限，报告只包含已读取的记录',
    'access_denied': '读取权限不足，部分关联或待处理信息待确认',
    'sync_limit': '已达到安全请求上限，部分信息待确认',
    'upstream_timeout': '读取超时，部分信息待确认',
    'rate_limited': 'Stripe 暂时限制请求，部分信息待确认',
    'upstream_unavailable': 'Stripe 暂时不可用，部分信息待确认',
    'source_expansion_denied': '关联对象展开权限不足，已改为独立读取关联信息',
    'unverified_source': '部分收款或退款的来源状态未能确认',
    'unverified_invoice': '部分收入无法确认订阅关联，已保留为未分类',
    'incomplete_invoice_lines': '订阅关联金额可能包含一次性附加项，未拆分纯订阅收入',
    'incomplete_subscription_items': '部分订阅的价格明细未完整读取',
    'partial_capture_unreconciled': '部分扣款涉及预授权额度释放，收款和退款金额待核对；原资金流水已保留',
}
_SUBSCRIPTION_STATUSES = {'incomplete', 'incomplete_expired', 'trialing', 'active', 'past_due', 'canceled', 'unpaid', 'paused'}
_INVOICE_STATUSES = {'draft', 'open', 'paid', 'uncollectible', 'void'}
_REFUND_STATUSES = {'pending', 'requires_action', 'succeeded', 'failed', 'canceled'}
# Unknown transaction types must not silently become an excluded adjustment
# while the report claims income coverage. Extend this only after reviewing the
# documented financial effect for the pinned report API.
# https://docs.stripe.com/api/balance_transactions/object?api-version=2024-06-20
_BALANCE_TYPES = {
    'adjustment', 'advance', 'advance_funding', 'anticipation_repayment', 'application_fee',
    'application_fee_refund', 'charge', 'climate_order_purchase', 'climate_order_refund',
    'connect_collection_transfer', 'contribution', 'fee_credit_funding', 'issuing_authorization_hold',
    'issuing_authorization_release', 'issuing_dispute', 'issuing_transaction', 'obligation_outbound',
    'obligation_reversal_inbound', 'payment', 'payment_failure_refund', 'payment_network_reserve_hold',
    'payment_network_reserve_release', 'payment_refund', 'payment_reversal', 'payment_unreconciled',
    'payout', 'payout_cancel', 'payout_failure', 'refund', 'refund_failure', 'reserve_transaction',
    'reserved_funds', 'stripe_fee', 'stripe_fx_fee', 'tax_fee', 'topup', 'topup_reversal', 'transfer',
    'transfer_cancel', 'transfer_failure', 'transfer_refund',
}


def _fail() -> None:
    raise ProviderError('invalid_response')


def _dict(value: object) -> dict:
    if not isinstance(value, dict): _fail()
    return value


def _identifier(value: object, prefix: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(re.escape(prefix) + r'[A-Za-z0-9]{1,120}', value): _fail()
    return value


def _reference(value: object, prefix: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None: return None
    return _identifier(value.get('id') if isinstance(value, dict) else value, prefix)


def _charge_reference(value: object, *, nullable: bool = False) -> str | None:
    if nullable and value is None: return None
    return _stripe_resource_id(value.get('id') if isinstance(value, dict) else value, 'payment', 'ch_')


def _timestamp(value: object, *, nullable: bool = False) -> int | None:
    if nullable and value is None: return None
    result = _integer(value)
    _date(result)
    return result


def _boolean(value: object) -> bool:
    if type(value) is not bool: _fail()
    return value


def _list_response(response: dict, resource: str) -> tuple[list[dict], bool]:
    if response.get('object') != 'list' or type(response.get('has_more')) is not bool: _fail()
    rows = response.get('data')
    if not isinstance(rows, list) or len(rows) > PAGE_SIZE or any(not isinstance(row, dict) for row in rows): _fail()
    if response['has_more'] and not rows: _fail()
    # URL is optional on synthetic/older responses, but never accept a different
    # endpoint's list as evidence for the requested resource.
    if 'url' in response and response['url'] != '/v1/' + resource: _fail()
    return rows, response['has_more']


def _resource_id(row: dict, resource: str) -> str:
    if resource == 'charges': return _stripe_resource_id(row.get('id'), 'payment', 'ch_')
    if resource == 'refunds': return _stripe_resource_id(row.get('id'), 'refund', 're_')
    if resource == 'disputes': return _stripe_resource_id(row.get('id'), 'dispute', 'dp_')
    return _identifier(row.get('id'), {'balance_transactions': 'txn_', 'subscriptions': 'sub_', 'invoices': 'in_', 'payouts': 'po_'}[resource])


def _customer(value: object, *, nullable: bool = False) -> tuple[str | None, str]:
    identity = _reference(value, 'cus_', nullable=nullable)
    label = _text(value.get('name') or value.get('email'), 200) if isinstance(value, dict) else ''
    return identity, label or identity or ''


def _timezone() -> str:
    value = os.getenv('PRIVATE_WORKSPACE_STRIPE_REPORT_TIMEZONE', 'UTC').strip()
    if not value or len(value) > 80: raise ProviderError('not_configured')
    try: ZoneInfo(value)
    except (ValueError, ZoneInfoNotFoundError): raise ProviderError('not_configured') from None
    return value


class _ReportReader:
    def __init__(self, client: _Client, headers: dict, mode: str):
        self.client, self.headers, self.mode = client, headers, mode
        self.warnings: dict[tuple[str, str], dict] = {}
        self.cache: dict[tuple[str, str], dict | None] = {}
        self.blocked: dict[str, str] = {}
        self.budget_exhausted: str | None = None
        self.expanded_sources = True

    def warn(self, code: str, resource: str) -> None:
        self.warnings[(code, resource)] = {'code': code, 'resource': resource, 'message': _WARNING_MESSAGES[code]}

    async def read(self, resource: str, parameters: dict | None = None, identity: str | None = None) -> dict:
        if self.budget_exhausted: raise ProviderError(self.budget_exhausted)
        return await self.client.request('GET', 'https://api.stripe.com/v1/' + resource + ('/' + identity if identity else ''),
                                         headers=self.headers, params=parameters or {})

    def partial(self, error: ProviderError, resource: str) -> None:
        if error.code not in _PARTIAL_ERRORS: raise error
        self.warn(error.code, resource)
        if error.code in _BUDGET_ERRORS: self.budget_exhausted = error.code

    async def pages(self, resource: str, parameters: dict, maximum: int, *, required: bool = False) -> tuple[list[dict], dict]:
        rows: list[dict] = []; seen: set[str] = set(); cursor = None; pages = 0
        complete = False; reason = None
        while len(rows) < maximum:
            request = {**parameters, 'limit': min(PAGE_SIZE, maximum - len(rows))}
            if cursor: request['starting_after'] = cursor
            if resource == 'balance_transactions' and self.expanded_sources: request['expand[]'] = 'data.source'
            try:
                try: result = await self.read(resource, request)
                except ProviderError as error:
                    if resource != 'balance_transactions' or not self.expanded_sources or error.code != 'access_denied': raise
                    # A restricted key can read transactions while not being
                    # allowed to expand every polymorphic source. Retry raw data.
                    self.expanded_sources = False; self.warn('source_expansion_denied', resource)
                    request.pop('expand[]', None)
                    result = await self.read(resource, request)
            except ProviderError as error:
                # Missing the primary monetary source cannot produce a report
                # showing a misleading zero. A later page failure is partial.
                if required and not rows: raise
                self.partial(error, resource); reason = error.code; break
            batch, has_more = _list_response(result, resource)
            if len(batch) > request['limit']: _fail()
            pages += 1
            for row in batch:
                identity = _resource_id(row, resource)
                if identity in seen: _fail()
                seen.add(identity); rows.append(row)
            if not has_more: complete = True; break
            cursor = _resource_id(batch[-1], resource)
        if not complete and not reason:
            reason = 'record_limit'; self.warn(reason, resource)
        return rows, {'complete': complete, 'count': len(rows), 'pages': pages, 'reason': reason, 'record_limit': maximum}

    async def optional(self, resource: str, identity: str, expanded: object = None) -> dict | None:
        cache_key = (resource, identity)
        if isinstance(expanded, dict):
            if _resource_id(expanded, resource) != identity: _fail()
            # Every expanded occurrence is independently validated by callers;
            # do not let a cached object hide a conflicting mode or backlink.
            self.cache[cache_key] = expanded
            return expanded
        if cache_key in self.cache: return self.cache[cache_key]
        if resource in self.blocked:
            self.warn(self.blocked[resource], resource); return None
        try: result = await self.read(resource, identity=identity)
        except ProviderError as error:
            self.partial(error, resource); self.blocked[resource] = error.code; self.cache[cache_key] = None
            return None
        if _resource_id(result, resource) != identity: _fail()
        self.cache[cache_key] = result
        return result

    def dashboard(self, path: str, identity: str) -> str:
        return 'https://dashboard.stripe.com/' + ('test/' if self.mode == 'test' else '') + path + '/' + identity


def _balance_transaction(row: dict, start: int, end: int) -> dict:
    if row.get('object') != 'balance_transaction': _fail()
    identity = _resource_id(row, 'balance_transactions')
    created = _timestamp(row.get('created'))
    if not start <= created < end: _fail()
    amount = _integer(row.get('amount'), negative=True)
    fee = _integer(row.get('fee'), negative=True)
    net = _integer(row.get('net'), negative=True)
    if net != amount - fee: _fail()
    type_value, category = row.get('type'), row.get('reporting_category')
    if (type_value not in _BALANCE_TYPES
            or not isinstance(category, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,79}', category)
            or row.get('status') not in {'available', 'pending'}): _fail()
    source = row.get('source')
    source_id = source.get('id') if isinstance(source, dict) else source
    if source_id is not None and (not isinstance(source_id, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{1,127}', source_id)): _fail()
    kind = 'payment' if type_value in {'charge', 'payment'} else 'refund' if type_value in {'refund', 'payment_refund'} else 'other_balance_activity'
    # Stripe also uses a positive payment_refund when a failed local-method
    # refund is returned to the balance. It is a reversal, not a customer refund.
    # https://docs.stripe.com/reports/balance-transaction-types
    if type_value == 'payment_refund' and amount >= 0: kind = 'other_balance_activity'
    if kind == 'payment':
        _charge_reference(source_id)
        if amount < 0: _fail()
    if kind == 'refund':
        _stripe_resource_id(source_id, 'refund', 're_')
        if amount > 0: _fail()
    return {'id': identity, 'type': type_value, 'reporting_category': category, 'created': created,
            'currency': _currency(row.get('currency')), 'amount': amount, 'fee': fee, 'net': net,
            'status': row['status'], 'source_id': source_id, 'kind': kind,
            'income_eligible': kind in {'payment', 'refund'}, 'source_verified': False,
            'classification': 'unclassified', 'classification_label': '未分类',
            'charge_id': None, 'invoice_id': None, 'subscription_id': None,
            'source_currency': None, 'source_amount_minor': None, 'charge_created': None,
            'source_status': None, 'customer_id': None, 'customer_label': '',
            'description': _text(row.get('description'), 300), 'source_url': None,
            'includes_one_time_items': None, 'invoice_lines_complete': None}


def _validate_charge(charge: dict, mode: str) -> dict:
    _stripe_resource_mode(charge, mode, 'payment')
    identity = _resource_id(charge, 'charges')
    amount = _integer(charge.get('amount')); captured_amount = _integer(charge.get('amount_captured'))
    captured, paid = _boolean(charge.get('captured')), _boolean(charge.get('paid'))
    if captured_amount > amount or captured_amount > 0 and not paid: _fail()
    status = charge.get('status')
    if status not in {'succeeded', 'pending', 'failed'}: _fail()
    # Missing an explicit nullable association is not evidence of a one-off sale.
    if 'invoice' not in charge or 'balance_transaction' not in charge: _fail()
    invoice_id = _reference(charge['invoice'], 'in_', nullable=True)
    balance_id = _reference(charge['balance_transaction'], 'txn_', nullable=True)
    customer_id, label = _customer(charge.get('customer'), nullable=True)
    details = charge.get('billing_details')
    if details is not None:
        details = _dict(details); label = _text(details.get('name') or details.get('email'), 200) or label
    payment_intent = _reference(charge.get('payment_intent'), 'pi_', nullable=True)
    return {'id': identity, 'currency': _currency(charge.get('currency')), 'amount': amount,
            'amount_captured': captured_amount, 'captured': captured, 'paid': paid, 'status': status,
            'invoice_id': invoice_id, 'balance_transaction': balance_id, 'customer_id': customer_id,
            'customer_label': label, 'created': _timestamp(charge.get('created')), 'payment_intent': payment_intent,
            'eligible': paid and captured_amount > 0 and status == 'succeeded'}


def _validate_invoice(invoice: dict, mode: str) -> dict:
    if invoice.get('object') != 'invoice': _fail()
    _stripe_livemode(invoice, mode)
    identity = _resource_id(invoice, 'invoices')
    if 'subscription' not in invoice or 'charge' not in invoice: _fail()
    status = invoice.get('status')
    if status not in _INVOICE_STATUSES: _fail()
    paid = _boolean(invoice.get('paid'))
    if paid != (status == 'paid'): _fail()
    customer_id, label = _customer(invoice.get('customer'))
    label = _text(invoice.get('customer_name') or invoice.get('customer_email'), 200) or label
    return {'id': identity, 'charge_id': _charge_reference(invoice['charge'], nullable=True),
            'subscription_id': _reference(invoice['subscription'], 'sub_', nullable=True),
            'currency': _currency(invoice.get('currency')), 'status': status, 'paid': paid,
            'customer_id': customer_id, 'customer_label': label,
            'amount_remaining_minor': _integer(invoice.get('amount_remaining')),
            'created': _timestamp(invoice.get('created')), 'due_date': _timestamp(invoice.get('due_date'), nullable=True)}


def _invoice_composition(invoice: dict, mode: str, subscription_id: str | None) -> tuple[bool | None, bool]:
    lines = invoice.get('lines')
    if not isinstance(lines, dict) or lines.get('object') != 'list' or type(lines.get('has_more')) is not bool: _fail()
    rows = lines.get('data')
    if not isinstance(rows, list) or len(rows) > PAGE_SIZE: _fail()
    seen = set(); has_one_time = False
    for value in rows:
        line = _dict(value)
        if line.get('object') != 'line_item': _fail()
        _stripe_livemode(line, mode)
        line_id = line.get('id')
        if not isinstance(line_id, str) or not re.fullmatch(r'il_(?:tmp_)?[A-Za-z0-9]{1,120}', line_id) or line_id in seen: _fail()
        seen.add(line_id)
        _integer(line.get('amount'), negative=True)
        if _currency(line.get('currency')) != _currency(invoice.get('currency')): _fail()
        if line.get('invoice') is not None and _reference(line['invoice'], 'in_') != invoice['id']: _fail()
        if line.get('type') not in {'invoiceitem', 'subscription'} or 'subscription' not in line: _fail()
        linked = _reference(line['subscription'], 'sub_', nullable=True)
        if linked and linked != subscription_id: _fail()
        if line['type'] == 'subscription' and linked is None: _fail()
        if line['type'] == 'invoiceitem' and linked is None: has_one_time = True
    complete = not lines['has_more']
    return True if has_one_time else False if complete else None, complete


async def _association(reader: _ReportReader, transaction: dict, charge_row: dict, *, is_payment: bool) -> None:
    charge = _validate_charge(charge_row, reader.mode)
    transaction.update(charge_id=charge['id'], charge_created=charge['created'], customer_id=charge['customer_id'],
                       customer_label=charge['customer_label'], invoice_id=charge['invoice_id'])
    transaction['source_url'] = reader.dashboard('payments', charge['payment_intent'] or charge['id'])
    if is_payment:
        if charge['balance_transaction'] != transaction['id']: _fail()
        transaction.update(source_currency=charge['currency'], source_amount_minor=charge['amount_captured'], source_status=charge['status'])
        transaction['income_eligible'] = charge['eligible']
        if charge['eligible'] and charge['amount_captured'] < charge['amount']:
            # Legacy separate authorization/capture can post the full authorized
            # charge plus a refund of the uncaptured portion. A source Charge's
            # captured total alone does not identify the period/FX allocation of
            # that pair. Preserve actual BT amounts but exclude this unresolved
            # authorization pair from confirmed receipts/customer refunds.
            # https://docs.stripe.com/reports/balance-transaction-types
            if transaction['currency'] != charge['currency'] or transaction['amount'] == charge['amount']:
                transaction.update(income_eligible=None, source_verified=False,
                                   exclusion_reason='authorization_capture_unreconciled')
                reader.warn('partial_capture_unreconciled', 'charges')
            elif transaction['amount'] != charge['amount_captured']: _fail()
        elif charge['eligible'] and transaction['currency'] == charge['currency'] and transaction['amount'] != charge['amount_captured']:
            _fail()
    if not charge['eligible']:
        transaction['income_eligible'] = False
        transaction['exclusion_reason'] = 'payment_not_captured_or_successful'
        return
    invoice_id = charge['invoice_id']
    if not invoice_id:
        transaction.update(classification='one_time', classification_label='一次性收入')
        return
    invoice_row = await reader.optional('invoices', invoice_id, charge_row.get('invoice'))
    if invoice_row is None:
        reader.warn('unverified_invoice', 'invoices'); return
    invoice = _validate_invoice(invoice_row, reader.mode)
    # invoice.charge is the *latest* charge, so a different backlink cannot be
    # asserted as the same payment just because its description looks similar.
    if (invoice['charge_id'] != charge['id'] or invoice['customer_id'] != charge['customer_id']
            or invoice['currency'] != charge['currency'] or not invoice['paid']): _fail()
    mixed, lines_complete = _invoice_composition(invoice_row, reader.mode, invoice['subscription_id'])
    transaction.update(subscription_id=invoice['subscription_id'], customer_label=invoice['customer_label'],
                       includes_one_time_items=mixed, invoice_lines_complete=lines_complete)
    if invoice['subscription_id']:
        transaction.update(classification='subscription', classification_label='订阅关联收入（可能含一次性附加项）')
        if not lines_complete: reader.warn('incomplete_invoice_lines', 'invoices')
    else:
        transaction.update(classification='one_time', classification_label='一次性收入')


async def _hydrate(reader: _ReportReader, row: dict, transaction: dict) -> None:
    source = row.get('source'); source_id = transaction['source_id']
    if transaction['kind'] == 'payment':
        charge = await reader.optional('charges', source_id, source)
        if charge is None:
            transaction['income_eligible'] = None
            reader.warn('unverified_source', 'charges'); return
        transaction['source_verified'] = True
        await _association(reader, transaction, charge, is_payment=True)
    elif transaction['kind'] == 'refund':
        refund = await reader.optional('refunds', source_id, source)
        if refund is None:
            transaction['income_eligible'] = None
            reader.warn('unverified_source', 'refunds'); return
        _stripe_resource_mode(refund, reader.mode, 'refund')
        if _resource_id(refund, 'refunds') != source_id: _fail()
        if 'balance_transaction' not in refund: _fail()
        if _reference(refund['balance_transaction'], 'txn_', nullable=True) != transaction['id']: _fail()
        status = refund.get('status')
        if status not in _REFUND_STATUSES: _fail()
        amount = _integer(refund.get('amount')); currency = _currency(refund.get('currency'))
        if currency == transaction['currency'] and amount != -transaction['amount']: _fail()
        charge_id = _charge_reference(refund.get('charge'))
        transaction.update(source_status=status, source_currency=currency, source_amount_minor=amount,
                           charge_id=charge_id, source_verified=True, income_eligible=status == 'succeeded')
        if status != 'succeeded':
            transaction['exclusion_reason'] = 'refund_not_successful'; return
        charge = await reader.optional('charges', charge_id, refund.get('charge'))
        if charge is None:
            transaction['income_eligible'] = None; transaction['source_verified'] = False
            reader.warn('unverified_source', 'charges'); return
        await _association(reader, transaction, charge, is_payment=False)
        validated_charge = _validate_charge(charge, reader.mode)
        if currency != validated_charge['currency'] or amount > validated_charge['amount']: _fail()
        if refund.get('reason') == 'expired_uncaptured_charge':
            transaction.update(income_eligible=False, exclusion_reason='uncaptured_authorization_release',
                               classification='unclassified', classification_label='未扣款预授权额度释放')
        elif validated_charge['eligible'] and validated_charge['amount_captured'] < validated_charge['amount']:
            # The documented uncaptured-release refund can exceed captured
            # funds, and a smaller release can look numerically like a real
            # customer refund. Without verified release linkage, neither is
            # allowed to masquerade as a confirmed customer refund.
            transaction.update(income_eligible=None, source_verified=False,
                               exclusion_reason='authorization_capture_unreconciled')
            reader.warn('partial_capture_unreconciled', 'refunds')
        elif validated_charge['eligible'] and amount > validated_charge['amount_captured']: _fail()
    else:
        # Transfers, failed-payment reversals, fee adjustments and payouts retain
        # their balance effect, separate from collected income.
        if source_id and re.fullmatch(r'po_[A-Za-z0-9]{1,120}', source_id): transaction['source_url'] = reader.dashboard('payouts', source_id)
        elif source_id and re.fullmatch(r'(?:dp|du)_[A-Za-z0-9]{1,120}', source_id): transaction['source_url'] = reader.dashboard('disputes', source_id)
        else: transaction['source_url'] = reader.dashboard('balance/history', transaction['id'])
        transaction['income_eligible'] = False


def _subscription(reader: _ReportReader, row: dict) -> dict:
    if row.get('object') != 'subscription': _fail()
    _stripe_livemode(row, reader.mode)
    identity = _resource_id(row, 'subscriptions'); status = row.get('status')
    if status not in _SUBSCRIPTION_STATUSES: _fail()
    currency = _currency(row.get('currency')); customer_id, customer_label = _customer(row.get('customer'))
    source_items = _dict(row.get('items'))
    if source_items.get('object') != 'list' or type(source_items.get('has_more')) is not bool: _fail()
    if not isinstance(source_items.get('data'), list) or len(source_items['data']) > PAGE_SIZE: _fail()
    items = []; seen = set()
    for value in source_items['data']:
        item = _dict(value); item_id = _identifier(item.get('id'), 'si_')
        if item.get('object') != 'subscription_item' or item_id in seen or _reference(item.get('subscription'), 'sub_') != identity: _fail()
        seen.add(item_id); price = _dict(item.get('price'))
        if price.get('object') != 'price' or price.get('type') != 'recurring': _fail()
        _stripe_livemode(price, reader.mode)
        price_id = _identifier(price.get('id'), 'price_')
        recurring = _dict(price.get('recurring'))
        if recurring.get('interval') not in {'day', 'week', 'month', 'year'}: _fail()
        interval_count = _integer(recurring.get('interval_count'))
        if not interval_count: _fail()
        price_currency = _currency(price.get('currency'))
        if price_currency != currency: _fail()
        # Metered/tiered prices legitimately have a null unit_amount. Retain
        # that fact; never invent monthly revenue from the subscription price.
        unit_amount = price.get('unit_amount')
        if unit_amount is not None: unit_amount = _integer(unit_amount)
        quantity = item.get('quantity')
        if quantity is not None: quantity = _integer(quantity)
        items.append({'id': item_id, 'price_id': price_id, 'product_id': _reference(price.get('product'), 'prod_'),
                      'nickname': _text(price.get('nickname'), 200), 'quantity': quantity,
                      'unit_amount_minor': unit_amount, 'currency': price_currency,
                      'interval': recurring['interval'], 'interval_count': interval_count})
    if source_items['has_more']: reader.warn('incomplete_subscription_items', 'subscriptions')
    return {'id': identity, 'status': status, 'currency': currency, 'customer_id': customer_id, 'customer_label': customer_label,
            'created': _timestamp(row.get('created')), 'current_period_end': _timestamp(row.get('current_period_end')),
            'cancel_at_period_end': _boolean(row.get('cancel_at_period_end')), 'items': items,
            'items_complete': not source_items['has_more'], 'source_url': reader.dashboard('subscriptions', identity)}


def _observation(reader: _ReportReader, row: dict, resource: str, start: int, end: int) -> dict:
    kind = 'payout' if resource == 'payouts' else 'dispute'
    _stripe_resource_mode(row, reader.mode, kind)
    identity = _resource_id(row, resource); created = _timestamp(row.get('created'))
    if not start <= created < end: _fail()
    status = row.get('status')
    statuses = {'pending', 'in_transit', 'paid', 'failed', 'canceled'} if kind == 'payout' else {
        'warning_needs_response', 'warning_under_review', 'warning_closed', 'needs_response', 'under_review', 'won', 'lost', 'prevented'}
    if status not in statuses: _fail()
    evidence_details = row.get('evidence_details') or {}
    if not isinstance(evidence_details, dict): _fail()
    return {'id': identity, 'kind': kind, 'created': created, 'status': status,
            'amount_minor': _integer(row.get('amount'), negative=kind == 'payout'), 'currency': _currency(row.get('currency')),
            'due_date': _timestamp(evidence_details.get('due_by'), nullable=True) if kind == 'dispute' else None,
            'arrival_date': _timestamp(row.get('arrival_date'), nullable=True) if kind == 'payout' else None,
            'source_url': reader.dashboard(resource, identity), 'date_basis': 'resource_created', 'is_income': False}


async def fetch_report(credentials: dict, metadata: dict, start: int, end: int, *, transport: httpx.AsyncBaseTransport | None = None) -> dict:
    """Read a [start, end) UTC range. Partial reads never claim full totals.

    Current subscriptions/open invoice attention use observation time, separately
    from dated cash transactions and dated payout/dispute inspection records.
    """
    if not isinstance(credentials, dict) or not isinstance(metadata, dict): raise ProviderError('invalid_credentials')
    if type(start) is not int or type(end) is not int or start < 0 or end <= start: raise ProviderError('invalid_response')
    _timestamp(start); _timestamp(end)
    reporting_timezone = _timezone()
    key = _stripe_key(credentials.get('api_key')); mode = _stripe_mode(key)
    expected, expected_mode = stripe_expected_identity()
    if (credentials.get('stripe_account_id') != expected or credentials.get('mode') != expected_mode
            or metadata.get('stripe_account_id') != expected or metadata.get('mode') != expected_mode):
        raise ProviderError('stripe_account_changed')
    headers = {'Authorization': 'Bearer ' + key, 'Stripe-Version': STRIPE_REPORT_API_VERSION}
    try:
        async with _Client(transport) as client:
            identity, balances = await _stripe_identity(client, headers, mode)
            identity['mode'] = mode
            reader = _ReportReader(client, headers, mode)
            range_parameters = {'created[gte]': start, 'created[lt]': end}
            source_transactions, bt_coverage = await reader.pages('balance_transactions', range_parameters, MAX_BALANCE_TRANSACTIONS, required=True)
            transactions = []
            for row in source_transactions:
                # Documented balance transactions omit livemode. If a response
                # supplies it, require agreement with the verified key/balance.
                if 'livemode' in row: _stripe_livemode(row, mode)
                transactions.append(_balance_transaction(row, start, end))
            subscription_rows, subscription_coverage = await reader.pages('subscriptions', {}, MAX_SUBSCRIPTIONS)
            subscriptions = [_subscription(reader, row) for row in subscription_rows]
            invoice_rows, invoice_coverage = await reader.pages('invoices', {'status': 'open'}, MAX_ATTENTION_INVOICES)
            attention = []
            for row in invoice_rows:
                invoice = _validate_invoice(row, mode)
                if invoice['status'] != 'open': _fail()
                attention.append({**invoice, 'kind': 'invoice', 'source_url': reader.dashboard('invoices', invoice['id']), 'date_basis': 'current_status', 'is_income': False})
            payout_rows, payout_coverage = await reader.pages('payouts', range_parameters, MAX_PERIOD_OBSERVATIONS)
            payouts = [_observation(reader, row, 'payouts', start, end) for row in payout_rows]
            dispute_rows, dispute_coverage = await reader.pages('disputes', range_parameters, MAX_PERIOD_OBSERVATIONS)
            disputes = [_observation(reader, row, 'disputes', start, end) for row in dispute_rows]
            attention.extend(row for row in disputes if row['status'] in {'needs_response', 'warning_needs_response'})
            attention.extend(row for row in payouts if row['status'] in {'failed', 'canceled'})
            for subscription in subscriptions:
                if subscription['status'] in {'past_due', 'unpaid', 'incomplete', 'paused'} or subscription['cancel_at_period_end']:
                    reason = ('订阅已设置到期取消，请核对后续安排' if subscription['cancel_at_period_end']
                              else '订阅付款异常，请核对续费状态')
                    attention.append({**subscription, 'kind': 'subscription', 'date_basis': 'current_status', 'is_income': False, 'reason': reason})
            for row, transaction in zip(source_transactions, transactions): await _hydrate(reader, row, transaction)
            monetary = [row for row in transactions if row['kind'] in {'payment', 'refund'}]
            sources_complete = all(row['source_verified'] for row in monetary)
            classification_complete = all(row['classification'] != 'unclassified' for row in monetary if row['income_eligible'])
            subscription_coverage['items_complete'] = all(row['items_complete'] for row in subscriptions)
            subscription_coverage['scope'] = 'current_non_canceled'
            invoice_coverage['scope'] = 'current_open_invoices'
            payout_coverage['date_basis'] = dispute_coverage['date_basis'] = 'resource_created'
            coverage = {'amounts_complete': bt_coverage['complete'] and sources_complete,
                        'source_verification_complete': sources_complete,
                        'classifications_complete': bt_coverage['complete'] and sources_complete and classification_complete,
                        'subscriptions_complete': subscription_coverage['complete'] and subscription_coverage['items_complete'],
                        'invoices_attention_complete': invoice_coverage['complete'],
                        'payouts_complete': payout_coverage['complete'], 'disputes_complete': dispute_coverage['complete'],
                        'balance_transactions': bt_coverage, 'subscriptions': subscription_coverage,
                        'invoices': invoice_coverage, 'payouts': payout_coverage, 'disputes': dispute_coverage,
                        'warnings': list(reader.warnings.values())}
            return {'schema_version': 1, 'api_version': STRIPE_REPORT_API_VERSION, 'identity': identity, 'balances': balances,
                    'period': {'start': start, 'end': end, 'start_utc': _date(start), 'end_utc': _date(end),
                               'timezone': reporting_timezone, 'end_exclusive': True, 'date_basis': 'balance_transaction_created'},
                    'transactions': transactions, 'subscriptions': subscriptions, 'attention': attention,
                    'payouts': payouts, 'disputes': disputes, 'coverage': coverage,
                    'observed_at': datetime.now(timezone.utc).isoformat(), 'read_only': True}
    except (TypeError, ValueError, KeyError, AttributeError, OverflowError):
        raise ProviderError('invalid_response') from None
