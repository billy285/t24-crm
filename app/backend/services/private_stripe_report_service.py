"""Deterministic Stripe cash reports, isolated from CRM accounting and AI spend."""
import asyncio
import calendar
import hashlib
import json
import os
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import delete, select, update

from models.private_workspace import PrivateConnection, PrivateStripeReport
from services import private_workspace as core
from services import private_workspace_providers as providers

VERSION = 'stripe-cash-report-v1'
CACHE_SECONDS = 600
MAX_REPORT_BYTES = 4_000_000
_locks = {}


def reporting_timezone():
    name = (os.environ.get('PRIVATE_WORKSPACE_STRIPE_REPORT_TIMEZONE') or 'UTC').strip()
    try:
        if not name or len(name) > 80:
            raise ValueError()
        return name, ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(503, 'Stripe 统计时区尚未正确配置') from None


def _month_shift(value, months):
    year, month = divmod(value.year * 12 + value.month - 1 + months, 12)
    return value.replace(year=year, month=month + 1,
                         day=min(value.day, calendar.monthrange(year, month + 1)[1]))


def resolve_period(preset='month', start_date=None, end_date=None, *, now=None):
    name, tz = reporting_timezone()
    reference = (now or datetime.now(timezone.utc)).astimezone(tz)
    today = reference.date()
    if preset not in {'month', 'quarter', 'year', 'custom'}:
        raise HTTPException(422, '请选择有效的统计期间')
    if preset == 'custom':
        try:
            first = date.fromisoformat(start_date)
            last = date.fromisoformat(end_date)
            if first.isoformat() != start_date or last.isoformat() != end_date:
                raise ValueError()
        except (TypeError, ValueError):
            raise HTTPException(422, '请选择有效的开始和结束日期') from None
        if first < date(2010, 1, 1) or first > last or last > today or (last - first).days >= 366:
            raise HTTPException(422, '日期范围应在过去，且最多为 366 天')
    else:
        if start_date is not None or end_date is not None:
            raise HTTPException(422, '预设期间不接受自定义日期')
        first = today.replace(day=1, month=1 if preset == 'year' else
                              ((today.month - 1) // 3) * 3 + 1 if preset == 'quarter' else today.month)
        last = today
    start = datetime.combine(first, time.min, tz)
    end = min(datetime.combine(last + timedelta(days=1), time.min, tz), reference)
    if end <= start:
        # First second of a period is a legitimate empty interval, not yesterday.
        end = start
    if preset == 'custom':
        previous_start = start - timedelta(days=(last - first).days + 1)
        previous_limit = start
    else:
        previous_start = _month_shift(start, -{'month': 1, 'quarter': 3, 'year': 12}[preset])
        previous_limit = start
    # Compare elapsed local calendar time, capped to the preceding period.
    previous_end = min(previous_start + (end - start), previous_limit)
    return {'preset': preset, 'start': int(start.timestamp()), 'end': int(end.timestamp()),
            'previous_start': int(previous_start.timestamp()), 'previous_end': int(previous_end.timestamp()),
            'start_date': first.isoformat(), 'end_date': last.isoformat(), 'timezone': name,
            'label': f'{first.isoformat()} — {last.isoformat()}', 'comparison_label': '与上期同等时段比较',
            'reference_date': today.isoformat()}


def _minor(value):
    if type(value) is not int or abs(value) > 9_000_000_000_000_000:
        raise ValueError('invalid report amount')
    return value


def _display(value, limit=240):
    return core._SECRET_VALUE.sub('[已隐藏]', str(value or ''))[:limit]


def _iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if type(value) is int else None


def _money(amount, currency):
    # Only the display formatter uses decimals; calculations remain integer.
    if currency in {'BHD', 'IQD', 'JOD', 'KWD', 'LYD', 'OMR', 'TND'}:
        return f'{currency} 金额单位待确认'
    zero = {'BIF', 'CLP', 'DJF', 'GNF', 'JPY', 'KMF', 'KRW', 'MGA', 'PYG', 'RWF', 'VND', 'VUV', 'XAF', 'XOF', 'XPF'}
    digits = 0 if currency in zero else 2
    sign = '-' if amount < 0 else ''
    absolute = abs(amount)
    whole, fraction = divmod(absolute, 10 ** digits)
    return f'{currency} {sign}{whole:,}' + (f'.{fraction:02d}' if digits else '')


def build_report(batch, window):
    identity = batch['identity']
    coverage = batch.get('coverage') or {}
    amounts_complete = coverage.get('amounts_complete') is True
    classifications_complete = coverage.get('classifications_complete') is True
    tz = ZoneInfo(window['timezone'])
    current = defaultdict(lambda: {'gross_minor': 0, 'subscription_minor': 0, 'one_time_minor': 0,
                                   'unclassified_minor': 0, 'refunds_minor': 0, 'fees_minor': 0, 'count': 0})
    previous = defaultdict(int)
    trends = defaultdict(lambda: defaultdict(lambda: {'subscription_minor': 0, 'one_time_minor': 0, 'unclassified_minor': 0}))
    records = []
    seen = set()
    for event in batch.get('transactions', []):
        event_id = event['id']
        if event_id in seen:
            raise ValueError('duplicate balance transaction')
        seen.add(event_id)
        created = event['created']
        if type(created) is not int:
            raise ValueError('invalid activity date')
        currency = event['currency'].upper()
        if len(currency) != 3 or not currency.isalpha() or not currency.isascii():
            raise ValueError('invalid report currency')
        amount, fee, net = (_minor(event[name]) for name in ('amount', 'fee', 'net'))
        if amount - fee != net:
            raise ValueError('invalid balance transaction net')
        kind = event['kind'] if event.get('income_eligible') is True else 'other_balance_activity'
        category = event.get('classification', 'unclassified')
        if category not in {'subscription', 'one_time', 'unclassified'}:
            raise ValueError('invalid payment classification')
        if window['previous_start'] <= created < window['previous_end'] and kind == 'payment':
            if amount <= 0:
                raise ValueError('invalid payment')
            previous[currency] += amount
        if not window['start'] <= created < window['end']:
            continue
        bucket = current[currency]
        if kind == 'payment':
            if amount <= 0:
                raise ValueError('invalid payment')
            bucket['gross_minor'] += amount
            bucket[category + '_minor'] += amount
            bucket['count'] += 1
            local_day = datetime.fromtimestamp(created, tz).date()
            if (date.fromisoformat(window['end_date']) - date.fromisoformat(window['start_date'])).days > 62:
                local_day = max(date.fromisoformat(window['start_date']), local_day.replace(day=1))
            day = local_day.isoformat()
            trends[currency][day][category + '_minor'] += amount
        elif kind == 'refund':
            if amount >= 0:
                raise ValueError('invalid refund')
            bucket['refunds_minor'] += -amount
        bucket['fees_minor'] += fee
        if event['type'] in {'stripe_fee', 'stripe_fx_fee'}:
            # Standalone Stripe service/FX debits live in amount, unlike the
            # fee field of a payment transaction. Positive reversals offset them.
            bucket['fees_minor'] -= amount
        records.append({'id': event_id, 'kind': kind if kind in {'payment', 'refund'} else 'adjustment',
                        'title': _display(event.get('description') or event.get('customer_label') or
                                          {'payment': 'Stripe 收款', 'refund': 'Stripe 退款'}.get(kind, '资金调整')),
                        'customer_label': _display(event.get('customer_label')),
                        'status': _display(event.get('source_status') or event['type']),
                        'occurred_at': _iso(created), 'amount_minor': amount, 'currency': currency,
                        'category': category if kind in {'payment', 'refund'} else None,
                        'subscription_id': event.get('subscription_id'), 'invoice_id': event.get('invoice_id'),
                        'source_url': core.safe_source_url('stripe', event.get('source_url')),
                        'details': {'统计依据': 'Stripe 资金流水发生时间',
                                    '分类依据': _display(event.get('classification_label'), 400),
                                    '手续费': _money(fee, currency), '资金净变动': _money(net, currency),
                                    '来源编号': _display(event.get('source_id')), '流水编号': event_id,
                                    '原支付币种': _display(event.get('source_currency')) or None,
                                    '收款核对': '已核对' if event.get('income_eligible') is True else '不计入收款与退款合计'}})
    currencies = []
    known_balance_currencies = {row['currency'].upper() for row in batch.get('balances', [])} if amounts_complete else set()
    for currency in sorted(set(current) | set(previous) | known_balance_currencies):
        values = current[currency]
        gross = _minor(values['gross_minor'])
        prior = _minor(previous[currency])
        net_receipts = _minor(gross - values['refunds_minor'])
        for value in values.values():
            _minor(value)
        pct = round((gross - prior) * 100 / prior, 1) if amounts_complete and prior else None
        prefix = '本期' if amounts_complete else '已读取范围内'
        summary = ([f'{prefix}成功收款 {_money(gross, currency)}，共 {values["count"]} 笔。']
                   if amounts_complete or gross else ['成功收款合计仍待确认。'])
        categories = [('subscription_minor', '订阅相关收款'), ('one_time_minor', '单次收款')]
        segments = [f'{label} {_money(values[key], currency)}' for key, label in categories
                    if values[key] or (amounts_complete and classifications_complete)]
        if segments:
            summary.append(('已确认关联：' if not classifications_complete else '') + '；'.join(segments) + '。')
        if values['unclassified_minor']:
            summary.append(f'{_money(values["unclassified_minor"], currency)} 的收款类型仍待确认。')
        if amounts_complete and prior:
            summary.append(f'较上期同等时段{"增加" if pct >= 0 else "减少"} {abs(pct):.1f}%。')
        elif not amounts_complete:
            summary.append('历史读取尚未完整，暂不比较增长。')
        first_day = date.fromisoformat(window['start_date'])
        last_day = date.fromisoformat(window['end_date'])
        tick = first_day
        while tick <= last_day:
            trends[currency][tick.isoformat()]
            if (last_day - first_day).days > 62:
                tick = _month_shift(tick.replace(day=1), 1)
            else:
                tick += timedelta(days=1)
        currencies.append({'currency': currency, **values, 'net_receipts_minor': net_receipts,
                           'summary': summary, 'comparison': {'gross_minor': prior if amounts_complete else None,
                            'change_pct': pct, 'complete': amounts_complete},
                           'trend': [{'date': day, **amounts} for day, amounts in sorted(trends[currency].items())]})
    subscriptions = []
    for sub in batch.get('subscriptions', []):
        # Fixed recurring invoice schedules are inspectable, not realized receipts.
        subscriptions.append({'id': sub['id'], 'customer_label': _display(sub.get('customer_label') or sub.get('customer_id')),
                              'status': _display(sub['status']), 'currency': sub.get('currency'),
                              'next_payment_at': None, 'amount_minor': None,
                              'source_url': core.safe_source_url('stripe', sub.get('source_url')),
                              'period_end': _iso(sub.get('current_period_end')),
                              'cancel_at_period_end': sub.get('cancel_at_period_end') is True,
                              'plans': [{'label': _display(item.get('nickname') or item.get('price_id')),
                                         'amount_minor': item.get('unit_amount_minor'), 'currency': sub.get('currency'),
                                         'quantity': item.get('quantity'), 'interval': item.get('interval'),
                                         'interval_count': item.get('interval_count')} for item in sub.get('items', [])]})
    attention_names = {'invoice': '账单尚未结清，请核对付款状态', 'subscription': '订阅付款异常，请核对续费状态',
                       'dispute': '争议需要回应，请打开 Stripe 核对期限', 'payout': '提现未完成，请核对失败原因和银行账户'}
    attention = [{'id': row['id'], 'title': _display(row.get('customer_label') or
                    {'dispute': '争议需要回应', 'payout': '提现需要处理', 'subscription': '订阅需要处理'}.get(row.get('kind'), '账单待处理')),
                  'reason': _display(row.get('reason') or attention_names.get(row.get('kind'), '请核对来源状态'), 400),
                  'source_url': core.safe_source_url('stripe', row.get('source_url'))} for row in batch.get('attention', [])]
    # Payouts/disputes use provider status, never add to successful receipts.
    for row in [*batch.get('payouts', []), *batch.get('disputes', [])]:
        if window['start'] <= row.get('created', -1) < window['end']:
            records.append({'id': row['id'], 'kind': row['kind'], 'title': _display(row.get('description') or row.get('customer_label') or
                             ('Stripe 提现' if row['kind'] == 'payout' else 'Stripe 争议')),
                            'customer_label': _display(row.get('customer_label')), 'status': _display(row['status']),
                            'occurred_at': _iso(row['created']), 'amount_minor': _minor(row['amount_minor']), 'currency': row['currency'],
                            'category': None, 'subscription_id': None, 'invoice_id': None,
                            'source_url': core.safe_source_url('stripe', row.get('source_url')),
                            'details': {'统计依据': '来源记录创建时间', '资金性质': '不计入成功收款',
                                        '预计到账': _iso(row.get('arrival_date'))}})
            if row['kind'] == 'dispute' and row['status'] in {'needs_response', 'warning_needs_response'} and not any(item['id'] == row['id'] for item in attention):
                attention.append({'id': row['id'], 'title': '争议需要回应', 'reason': '请打开 Stripe 核对回应期限和材料',
                                  'source_url': core.safe_source_url('stripe', row.get('source_url'))})
    warnings = coverage.get('warnings') or []
    reasons = [_display(value.get('message') if isinstance(value, dict) else value, 400) for value in warnings]
    if not classifications_complete and not reasons:
        reasons.append('订阅关联尚未完整，无法确定的收款单列待分类。')
    return {'state': 'ready' if amounts_complete and classifications_complete else 'partial',
            'snapshot_id': hashlib.sha256(json.dumps({'ids': sorted(seen), 'window': window,
                 'observed_at': batch['observed_at'], 'version': VERSION}, sort_keys=True).encode()).hexdigest(),
            'generated_at': batch['observed_at'], 'account_label': _display(identity.get('account_label')),
            'mode': identity['mode'], 'period': {key: window[key] for key in
                ('preset', 'label', 'start_date', 'end_date', 'timezone', 'comparison_label')},
            'coverage': {'complete': amounts_complete and classifications_complete,
                         'amounts_complete': amounts_complete, 'classifications_complete': classifications_complete,
                         'subscriptions_complete': coverage.get('subscriptions_complete') is True,
                         'attention_complete': all(coverage.get(key) is True for key in
                             ('invoices_attention_complete', 'subscriptions_complete', 'payouts_complete', 'disputes_complete')),
                         'payouts_complete': coverage.get('payouts_complete') is True,
                         'disputes_complete': coverage.get('disputes_complete') is True,
                         'funds_complete': amounts_complete and coverage.get('payouts_complete') is True and coverage.get('disputes_complete') is True,
                         'reasons': reasons, 'date_basis': 'balance_transaction_created', 'end_exclusive': True},
            'currencies': currencies, 'records': sorted(records, key=lambda row: (row['occurred_at'] or '', row['id']), reverse=True),
            'subscriptions': subscriptions, 'attention': attention,
            'balances': [{**row, 'observed_at': batch['observed_at']} for row in batch.get('balances', [])]}


async def _authorized(validator):
    if validator is None or not await validator():
        raise HTTPException(403, '登录或私人空间权限已改变，请重新进入')


async def _connection(private_db, owner_id):
    await private_db.rollback()
    row = (await private_db.execute(select(PrivateConnection).where(
        PrivateConnection.owner_id == owner_id, PrivateConnection.source_id == 'stripe'
    ).execution_options(populate_existing=True))).scalar_one_or_none()
    identity = core.stripe_connection_identity(row, require_snapshot=False)
    if not identity or not row.encrypted_credentials:
        raise HTTPException(503, '请先连接私人 Stripe 账户')
    credentials = core.decrypt_credentials(row.encrypted_credentials)
    try:
        key = providers._stripe_key(credentials.get('api_key'))
        mode = providers._stripe_mode(key)
        if (credentials.get('stripe_account_id') != identity['account_id'] or
                credentials.get('mode') != identity['mode'] or mode != identity['mode']):
            raise providers.ProviderError('stripe_account_changed')
    except providers.ProviderError:
        raise HTTPException(503, 'Stripe 账户或授权绑定已改变，请重新连接') from None
    context = {'id': row.id, 'generation': row.generation, 'account_id': identity['account_id'],
               'mode': identity['mode'], 'credential_hash': hashlib.sha256(row.encrypted_credentials.encode()).hexdigest()}
    return context, credentials, dict(row.metadata_json or {})


async def report(private_db, owner_id, payload, *, owner_validator=None, now=None):
    await _authorized(owner_validator)
    window = resolve_period(payload.period, payload.start_date, payload.end_date, now=now)
    context, credentials, metadata = await _connection(private_db, owner_id)
    key_context = {'owner_id': owner_id, **context, 'version': VERSION,
                   'range': {key: window[key] for key in ('preset', 'start_date', 'end_date', 'timezone', 'reference_date')}}
    cache_key = hashlib.sha256(json.dumps(key_context, sort_keys=True).encode()).hexdigest()
    lock_key = (owner_id, context['id'])
    if lock_key not in _locks and len(_locks) >= 256:
        raise HTTPException(429, '查询较多，请稍后再试')
    lock = _locks.setdefault(lock_key, asyncio.Lock())
    async with lock:
        current_context, credentials, metadata = await _connection(private_db, owner_id)
        if current_context != context:
            raise HTTPException(409, 'Stripe 连接已改变，请重新查询')
        reference = now or datetime.now(timezone.utc)
        cached = (await private_db.execute(select(PrivateStripeReport).where(
            PrivateStripeReport.cache_key == cache_key, PrivateStripeReport.owner_id == owner_id,
            PrivateStripeReport.connection_id == context['id'], PrivateStripeReport.generation == context['generation']
        ))).scalar_one_or_none()
        if cached and core._aware(cached.expires_at) > reference and (
                not payload.refresh or (reference - core._aware(cached.created_at)).total_seconds() < 60):
            try:
                decoded = core._cipher().decrypt(cached.encrypted_report.encode())
                if len(decoded) > MAX_REPORT_BYTES:
                    raise ValueError()
                value = json.loads(decoded)
                if not isinstance(value, dict) or value.get('cache_context') != key_context:
                    raise ValueError()
                result = value['report']
            except Exception:
                raise HTTPException(503, '私人统计缓存暂不可读取，请稍后重试') from None
            await _authorized(owner_validator)
            latest, _, _ = await _connection(private_db, owner_id)
            if latest != context:
                raise HTTPException(409, 'Stripe 连接已改变，请重新查询')
            return result
        if cached:
            private_db.expunge(cached)
        await private_db.rollback()
        from services.private_stripe_report_provider import fetch_report
        try:
            batch = await asyncio.wait_for(fetch_report(credentials, metadata, window['previous_start'], window['end']), timeout=55)
        except providers.ProviderError as exc:
            message = '统计暂不可读取，请稍后重试'
            if exc.code == 'access_denied':
                message = 'Stripe 统计需要资金流水、账单和订阅的只读权限，请在管理接入中核对'
            raise HTTPException(503, message) from None
        except (asyncio.TimeoutError, ValueError, TypeError, KeyError):
            raise HTTPException(503, '本次统计未完成，请稍后重试') from None
        await _authorized(owner_validator)
        latest, _, _ = await _connection(private_db, owner_id)
        if latest != context:
            raise HTTPException(409, 'Stripe 连接已改变，本次统计未保存')
        if (batch.get('identity', {}).get('stripe_account_id') != context['account_id'] or
                batch.get('identity', {}).get('mode') != context['mode']):
            raise HTTPException(503, 'Stripe 来源账户与私人空间不一致')
        try:
            result = build_report(batch, window)
            encoded = json.dumps({'cache_context': key_context, 'report': result}, ensure_ascii=False,
                                 separators=(',', ':'), allow_nan=False).encode()
            if len(encoded) > MAX_REPORT_BYTES:
                raise ValueError()
        except (ValueError, TypeError, KeyError, OverflowError):
            raise HTTPException(503, '统计数据尚未通过核对，请重新查询') from None
        await _authorized(owner_validator)
        # Lock the current private connection through cache commit. A concurrent
        # disconnect cannot interleave after binding verification and persistence.
        # Compare ciphertext itself: encryption is randomized, not reproducible.
        bound = (await private_db.execute(select(PrivateConnection.encrypted_credentials).where(
            PrivateConnection.owner_id == owner_id, PrivateConnection.id == context['id']))).scalar_one_or_none()
        if not bound or hashlib.sha256(bound.encode()).hexdigest() != context['credential_hash']:
            raise HTTPException(409, 'Stripe 连接已改变，本次统计未保存')
        guarded = await private_db.execute(update(PrivateConnection).where(
            PrivateConnection.owner_id == owner_id, PrivateConnection.id == context['id'],
            PrivateConnection.generation == context['generation'], PrivateConnection.status == 'connected',
            PrivateConnection.encrypted_credentials == bound
        ).values(generation=PrivateConnection.generation))
        if guarded.rowcount != 1:
            await private_db.rollback()
            raise HTTPException(409, 'Stripe 连接已改变，本次统计未保存')
        await private_db.execute(delete(PrivateStripeReport).where(
            PrivateStripeReport.owner_id == owner_id, PrivateStripeReport.expires_at < reference))
        await private_db.merge(PrivateStripeReport(cache_key=cache_key, owner_id=owner_id,
            connection_id=context['id'], generation=context['generation'],
            encrypted_report=core._cipher().encrypt(encoded).decode(),
            created_at=reference, expires_at=reference + timedelta(seconds=CACHE_SECONDS)))
        await private_db.commit()
        await _authorized(owner_validator)
        latest, _, _ = await _connection(private_db, owner_id)
        if latest != context:
            raise HTTPException(409, 'Stripe 连接已改变，请重新查询')
        return result
