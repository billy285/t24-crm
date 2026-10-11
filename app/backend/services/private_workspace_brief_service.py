"""Owner-only local brief and explicit-click explanation, in the private DB.

No CRM financial reads/writes, connector sync, mail body fetch or automatic AI
calls. Platform facts remain deterministic; AI only adds separate review prose.
"""
import asyncio
import hashlib
import json
import re
import secrets
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from cryptography.fernet import InvalidToken
from fastapi import HTTPException
from sqlalchemy import String, and_, case, cast, exists, false, func, or_, select, update

from models.private_workspace import PrivateConnection, PrivateItem, PrivatePreferences, PrivateWorkspaceBrief, PrivateMailBriefUsage, utcnow
from services import private_mail_brief as shared
from services import private_mail_brief_service as mail
from services import private_workspace_brief_provider as provider
from services.private_workspace import (_aware, _cipher, current_stripe_condition, item_response,
    stored_preferences_for, stripe_connection_identity)

SOURCES = ('gmail', 'google_ads', 'stripe', 'bofa_bank', 'bofa', 'manual')
LABELS = {'gmail': '重要邮件', 'google_ads': '广告观察', 'stripe': 'Stripe 事件',
          'bofa_bank': '银行账户', 'bofa': '银行邮件提醒', 'manual': '我的待办'}
MAX_ROWS = 1000
RULE_VERSION = 'owner-brief-rules-v2'
LIMITATIONS = ['仅汇总独立私人工作空间，不读取或改动客户财务。',
               '邮件与银行提醒尚未核验；同步记录不代表全部账户活动。',
               'Stripe 按来源创建时间统计已同步事件；提现不计新增收入，争议和退款变化可能来自更早的记录。',
               '真实银行仅显示本地同步状态与流水条数；余额、金额及交易描述未纳入 AI 整理。',
               '广告采用账户原时区的昨日或近七个完整日期指标；可投放不等于效果良好或盈利。']


def _iso(value): return _aware(value).isoformat() if value else None


def _json(value): return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)


def _state(connection, source, now):
    if source == 'manual': return 'ready'
    if not connection or not connection.last_sync: return 'missing'
    identity = None
    if source == 'stripe':
        identity = stripe_connection_identity(connection)
    elif source == 'bofa_bank':
        from services.private_bank_service import bank_connection_identity
        identity = bank_connection_identity(connection)
    if source in {'stripe', 'bofa_bank'} and connection.status == 'connected' and not identity:
        return 'unsupported'
    age = now - _aware(connection.last_sync)
    if connection.status != 'connected' or connection.error or not timedelta(0) <= age <= timedelta(hours=24): return 'stale'
    if identity and not timedelta(0) <= now - identity['observed_at'] <= timedelta(hours=24): return 'stale'
    meta = connection.metadata_json or {}
    if source == 'google_ads':
        snapshot = meta.get('ads_snapshot')
        if not isinstance(snapshot, dict) or not snapshot.get('id'): return 'unsupported'
        observed = snapshot.get('observed_at')
        try: observed = _aware(datetime.fromisoformat(observed))
        except (ValueError, TypeError): return 'unsupported'
        if not timedelta(0) <= now - observed <= timedelta(hours=24): return 'stale'
        if not snapshot.get('inventory_complete') or not snapshot.get('metrics_complete'): return 'partial'
        return 'ready'
    if source == 'bofa_bank':
        snapshot = meta['bank_snapshot']
        return 'ready' if all(snapshot.get(key) is True for key in
                             ('accounts_complete', 'pagination_complete', 'transactions_complete')) else 'partial'
    # Email and Stripe synchronization always has bounded source coverage.
    return 'partial'


def _open(row, now):
    return row.action_status == 'open' or row.action_status == 'snoozed' and row.snoozed_until and _aware(row.snoozed_until) <= now


def _issue(row, score, summary, next_action, source_time=None):
    return {'id': 'item:' + row.id, 'source_id': row.source_id, 'item_id': row.id,
            'title': (row.local_title or row.title)[:240], 'summary': summary[:600],
            'next_action': next_action[:600], 'priority': 'urgent' if score <= 1 else 'high' if score <= 4 else 'normal',
            'observed_at': _iso(source_time or row.occurred_at), 'task_title': ('核对：' + (row.local_title or row.title))[:240],
            '_score': score, '_due': _aware(row.due_at) if row.source_id == 'manual' or row.kind == 'dispute' else None}


def _ads_member(row, connection):
    metadata = (connection.metadata_json or {}) if connection else {}
    snapshot = metadata.get('ads_snapshot') or {}
    evidence = row.evidence or {}; health = evidence.get('ads_health')
    return (isinstance(snapshot, dict) and snapshot.get('id') and metadata.get('ads_customer_id')
            and evidence.get('ads_snapshot_id') == snapshot['id']
            and str(evidence.get('customer_id')) == str(metadata['ads_customer_id'])
            and isinstance(health, dict) and health.get('snapshot_id') == snapshot['id'])


async def _revision(db, owner):
    items = (await db.execute(select(func.count(), func.max(PrivateItem.updated_at)).where(PrivateItem.owner_id == owner))).one()
    connections = (await db.execute(select(func.count(), func.max(PrivateConnection.updated_at)).where(PrivateConnection.owner_id == owner))).one()
    preference = (await db.execute(select(PrivatePreferences.updated_at, cast(PrivatePreferences.preferences_json, String))
        .where(PrivatePreferences.owner_id == owner))).one_or_none()
    identities = (await db.execute(select(PrivateConnection.id, PrivateConnection.source_id, PrivateConnection.generation,
        PrivateConnection.status, PrivateConnection.error, PrivateConnection.last_sync,
        cast(PrivateConnection.metadata_json, String)).where(PrivateConnection.owner_id == owner)
        .order_by(PrivateConnection.id))).all()
    return {'items_count': items[0], 'items_updated': items[1], 'connections_count': connections[0],
            'connections_updated': connections[1], 'preferences_updated': preference[0] if preference else None,
            'preferences_text': preference[1] if preference else None,
            'connection_identities': [tuple(row) for row in identities]}


def _live(owner, revision):
    conditions = []
    for model, prefix in ((PrivateItem, 'items'), (PrivateConnection, 'connections')):
        conditions.append(select(func.count()).where(model.owner_id == owner).scalar_subquery() == revision[prefix + '_count'])
        newest = select(func.max(model.updated_at)).where(model.owner_id == owner).scalar_subquery()
        value = revision[prefix + '_updated']
        conditions.append(newest.is_(None) if value is None else newest == value)
    updated = revision['preferences_updated']
    preference = select(PrivatePreferences.updated_at).where(PrivatePreferences.owner_id == owner).scalar_subquery()
    conditions.append(preference.is_(None) if updated is None else preference == updated)
    if revision['preferences_text'] is not None:
        conditions.append(exists(select(PrivatePreferences.owner_id).where(PrivatePreferences.owner_id == owner,
            cast(PrivatePreferences.preferences_json, String) == revision['preferences_text'])))
    for identity, source, generation, status, error, last_sync, metadata_text in revision['connection_identities']:
        conditions.append(exists(select(PrivateConnection.id).where(PrivateConnection.id == identity,
            PrivateConnection.owner_id == owner, PrivateConnection.source_id == source,
            PrivateConnection.generation == generation, PrivateConnection.status == status,
            PrivateConnection.error.is_(None) if error is None else PrivateConnection.error == error,
            PrivateConnection.last_sync.is_(None) if last_sync is None else PrivateConnection.last_sync == last_sync,
            cast(PrivateConnection.metadata_json, String) == metadata_text)))
    return and_(*conditions)


async def _snapshot(db, owner, period):
    if period not in {'today', 'last7days'}: raise HTTPException(422, '简报日期范围无效')
    revision_before = await _revision(db, owner)
    now = _aware(utcnow()); local = now.astimezone(ZoneInfo('Asia/Shanghai'))
    start = local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=6 if period == 'last7days' else 0)
    window = {'start': start.isoformat(), 'end': local.date().isoformat(), 'timezone': 'Asia/Shanghai'}
    connections = (await db.execute(select(PrivateConnection).where(PrivateConnection.owner_id == owner)
                                    .execution_options(populate_existing=True))).scalars().all()
    by_source = {row.source_id: row for row in connections}
    rows = []; clipped_sources = set()
    for source in SOURCES:
        conditions = [PrivateItem.owner_id == owner, PrivateItem.source_id == source]
        if source == 'google_ads':
            metadata = (by_source[source].metadata_json or {}) if source in by_source else {}
            ads = metadata.get('ads_snapshot')
            if isinstance(ads, dict) and ads.get('id') and metadata.get('ads_customer_id'):
                conditions.extend([PrivateItem.evidence['ads_snapshot_id'].as_string() == str(ads['id']),
                                   PrivateItem.evidence['customer_id'].as_string() == str(metadata['ads_customer_id'])])
            else: conditions.append(false())
        elif source == 'stripe':
            conditions.append(await current_stripe_condition(db, owner))
        elif source == 'bofa_bank':
            from services.private_bank_service import current_bank_condition
            conditions.extend([await current_bank_condition(db, owner), PrivateItem.kind == 'bank_transaction',
                               PrivateItem.status.in_(['posted', 'pending'])])
        important = case((and_(PrivateItem.kind == 'dispute', PrivateItem.status.in_(['needs_response', 'warning_needs_response'])), 0),
                         (PrivateItem.priority == 'urgent', 1), (PrivateItem.priority == 'high', 2), else_=3)
        source_rows = (await db.execute(select(PrivateItem).where(*conditions).order_by(important,
            PrivateItem.occurred_at.desc(), PrivateItem.updated_at.desc(), PrivateItem.id)
            .limit(MAX_ROWS + 1).execution_options(populate_existing=True))).scalars().all()
        if len(source_rows) > MAX_ROWS: clipped_sources.add(source)
        rows.extend(source_rows[:MAX_ROWS])
    preferences = await stored_preferences_for(db, owner)
    sources = []; candidates = []; computed_mail = []
    for source in SOURCES:
        connection = by_source.get(source); state = _state(connection, source, now)
        if source in clipped_sources and state == 'ready': state = 'partial'
        source_rows = [row for row in rows if row.source_id == source]
        period_rows = [row for row in source_rows if row.occurred_at and start <= _aware(row.occurred_at).astimezone(ZoneInfo('Asia/Shanghai')) <= local]
        facts = []; source_summary = ''
        if source == 'gmail':
            computed = [item_response(row, preferences) for row in period_rows]
            computed_mail.extend(computed)
            buckets = Counter(item['mail_relevance']['bucket'] for item in computed)
            facts = [f'同期已同步邮件 {len(computed)} 封', f'规则标记优先关注 {buckets["urgent"]} 封，今日处理 {buckets["today"]} 封']
            source_summary = '依据已导入邮件元数据和关注规则；不自动读取正文，发件人尚未核验。'
            for row, item in zip(period_rows, computed):
                if _open(row, now) and item['mail_relevance']['bucket'] in {'urgent', 'today'}:
                    bucket = item['mail_relevance']['bucket']
                    candidates.append(_issue(row, 5 if bucket == 'urgent' else 7,
                        '关注规则标记的待处理邮件；邮件内容和发件人仍需本人核对。', '查看原始邮件，确认是否需要回复或处理。'))
        elif source == 'google_ads':
            current = [row for row in source_rows if _ads_member(row, connection)]
            counts = Counter((row.evidence or {})['ads_health'].get('bucket', 'unknown') for row in current)
            facts = [f'当前快照广告系列 {len(current)} 个',
                     f'需检查 {counts["problem"]} 个，需关注 {counts["attention"]} 个，已暂停 {counts["paused"]} 个，状态待确认 {counts["unknown"]} 个']
            if state == 'partial': facts.append('快照覆盖不完整，状态数量仅限已加载系列，需在原始来源复核。')
            if state == 'stale': facts.append('以上为过期快照，不代表当前投放状态。')
            source_summary = '按最新广告快照和已有投放规则观察；广告费用按币种独立显示，不作为收入。'
            totals = defaultdict(lambda: {'clicks': 0, 'cost_micros': 0}); period_key = 'yesterday' if period == 'today' else 'last_7_days'
            metric_periods = set()
            for row in current:
                health = row.evidence['ads_health']; bucket = health.get('bucket', 'unknown')
                metrics = (health.get('metrics') or {}).get(period_key)
                coverage = health.get('coverage') or {}; currency = health.get('currency')
                if (state == 'ready' and coverage.get('metrics_complete') is True and isinstance(metrics, dict)
                        and isinstance(currency, str) and re.fullmatch('[A-Z]{3}', currency)
                        and type(metrics.get('clicks')) is int and type(metrics.get('cost_micros')) is int
                        and 0 <= metrics['clicks'] <= 9_000_000_000_000_000 and 0 <= metrics['cost_micros'] <= 9_000_000_000_000_000):
                    totals[currency]['clicks'] += metrics['clicks']; totals[currency]['cost_micros'] += metrics['cost_micros']
                    metric_period = (health.get('periods') or {}).get(period_key) or {}
                    metric_periods.add((metric_period.get('start'), metric_period.get('end'), health.get('account_timezone')))
                if state == 'ready' and bucket in {'problem', 'attention'}:
                    candidates.append(_issue(row, 2 if bucket == 'problem' else 4,
                        '广告平台提示当前不可投放或配置需检查。' if bucket == 'problem' else '广告平台提示投放受限；不能仅据此增加预算。',
                        '打开 Google Ads 核对系列状态和原因，调整前先确认原计划。', connection.last_sync))
            if state == 'partial':
                candidates.append({'id': 'source:google_ads', 'source_id': 'google_ads', 'title': '广告快照需要复核',
                    'summary': '广告快照覆盖不完整，平台状态与指标需在原始来源复核。',
                    'next_action': '重新同步并核对 Google Ads 原始状态；缺失指标不能当作零。',
                    'priority': 'normal', 'observed_at': _iso(connection.last_sync), 'task_title': '复核广告快照覆盖范围',
                    '_score': 7, '_due': None})
            if len(metric_periods) == 1:
                first, last, tz = next(iter(metric_periods)); facts.append(f'指标日期 {first} 至 {last}，广告账户时区 {tz}')
                for currency, values in sorted(totals.items()):
                    facts.append(f'已覆盖系列点击 {values["clicks"]} 次，广告费用 {Decimal(values["cost_micros"]) / Decimal(1000000):.2f} {currency}')
            elif totals:
                facts.append('广告指标窗口不同，不合并费用与点击。')
        elif source == 'stripe':
            kinds = Counter(row.kind for row in period_rows)
            facts = [f'同期已同步事件 {len(period_rows)} 条', f'付款 {kinds["payment"]} 条，退款 {kinds["refund"]} 条，争议 {kinds["dispute"]} 条，提现 {kinds["payout"]} 条']
            currencies = Counter(row.currency for row in period_rows if isinstance(row.currency, str) and re.fullmatch('[A-Z]{3}', row.currency))
            facts.extend(f'{currency} 事件 {count} 条' for currency, count in sorted(currencies.items()))
            source_summary = '只统计已同步事件，不代表全账户流水、余额、收入或利润；提现不等于银行到账。'
            if state == 'unsupported': facts = ['Stripe 账户、环境或同步快照身份无法核实；历史事件不参与简报。']
            for row in source_rows:
                if state not in {'ready', 'partial'}: continue
                if row.kind == 'dispute' and row.status in {'needs_response', 'warning_needs_response'}:
                    candidates.append(_issue(row, 0 if row.due_at and _aware(row.due_at) <= now + timedelta(days=2) else 1,
                        'Stripe 争议最后记录状态要求回应；请在平台核对当前状态和证据截止时间。', '打开 Stripe 核对争议与提交要求，手动处理。'))
                elif row in period_rows and row.kind in {'payment', 'refund', 'payout'} and row.status in {'failed', 'canceled'}:
                    candidates.append(_issue(row, 3, 'Stripe 最后记录状态提示款项处理失败或取消，需核对当前状态。', '打开 Stripe 检查失败原因；不要直接重复付款。'))
        elif source == 'bofa':
            facts = [f'同期已同步银行邮件提醒 {len(period_rows)} 封', '资金变动与实际入账均未核验。']
            source_summary = '来源为银行相关邮件提醒，尚未直连银行账户；不能据此确认到账。'
            for row in period_rows:
                if _open(row, now): candidates.append(_issue(row, 8, '银行相关邮件提醒尚未核验，不代表真实资金已经变动。', '在银行官方账户核对实际流水，先标记已阅。'))
        elif source == 'bofa_bank':
            source_summary = '仅展示本人银行连接与本地流水状态；需在银行官方账户核实，不据此判断收入或资金到账。'
            if state in {'ready', 'partial', 'stale'} and source_rows:
                kinds = Counter(row.status for row in source_rows if row.kind == 'bank_transaction')
                facts = [f'当前本地已入账 {kinds["posted"]} 条，待入账 {kinds["pending"]} 条',
                         '以上为同步记录条数，不是收支金额或经营收入。']
            elif state in {'ready', 'partial'}:
                facts = ['当前绑定的本地流水暂无记录；平台数据覆盖范围仍需核实。']
            if state == 'partial': facts.append('银行历史流水仍在准备，未加载记录不视为零。')
            if state == 'stale': facts.append('银行同步状态已过期或同步失败；当前流水需重新核实。')
            if state == 'unsupported': facts = ['银行连接或同步快照身份无法核实；历史流水不参与简报。']
        else:
            pending = [row for row in source_rows if _open(row, now)]
            overdue = [row for row in pending if row.due_at and _aware(row.due_at) < now]
            facts = [f'当前未完成待办 {len(pending)} 项，已过期 {len(overdue)} 项']
            source_summary = '当前私人待办状态；操作只影响独立私人工作空间。'
            for row in pending:
                if row in overdue or row.priority in {'urgent', 'high'} or row.due_at and _aware(row.due_at) <= now + timedelta(days=1):
                    candidates.append(_issue(row, 5 if row in overdue else 6, '私人待办已经到期或被本人标记为重要。', '确认下一步，处理后再手动标记完成。'))
        if source in clipped_sources: facts.append(f'仅加载该来源最多 {MAX_ROWS} 条本地记录，未覆盖部分待确认。')
        if state == 'missing': facts = ['尚未取得已连接来源的同步快照；不将缺失数据视为零。']
        sources.append({'source_id': source, 'status': connection.status if connection else 'connected' if source == 'manual' else 'disconnected',
            'last_sync': _iso(connection.last_sync) if connection else None, 'data_state': state,
            'summary': source_summary, 'facts': facts})
    # Cached mail titles are local reads only. No bodies or automatic requests.
    await mail.attach_cached_previews(db, owner, computed_mail)
    titles = {item['id']: item.get('mail_brief', {}).get('title_zh') for item in computed_mail}
    for issue in candidates:
        if issue['source_id'] == 'gmail' and titles.get(issue['item_id']): issue['title'] = titles[issue['item_id']][:240]
    far = datetime.max.replace(tzinfo=timezone.utc)
    candidates.sort(key=lambda item: (item['_score'], item['_due'] or far, item['observed_at'] or '', item['id']))
    issues = [{key: value for key, value in issue.items() if not key.startswith('_')} for issue in candidates[:3]]
    limits = [*LIMITATIONS, *(['部分来源超过本地加载上限，各来源分别限量，汇总范围有限。'] if clipped_sources else [])]
    revision = await _revision(db, owner)
    if revision != revision_before: raise HTTPException(409, '工作空间数据正在更新，请重新获取简报')
    valid_until = [local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)]
    for connection in connections:
        if _state(connection, connection.source_id, now) in {'ready', 'partial'}:
            if connection.last_sync: valid_until.append(_aware(connection.last_sync) + timedelta(hours=24))
            if connection.source_id in {'google_ads', 'stripe', 'bofa_bank'}:
                key = {'google_ads': 'ads_snapshot', 'stripe': 'stripe_snapshot', 'bofa_bank': 'bank_snapshot'}[connection.source_id]
                observed = (connection.metadata_json or {}).get(key, {}).get('observed_at')
                try: valid_until.append(_aware(datetime.fromisoformat(observed)) + timedelta(hours=24))
                except (ValueError, TypeError): pass
    revision['valid_until'] = min(valid_until).astimezone(timezone.utc)
    identity = {'owner': owner, 'period': period, 'window': window, 'sources': sources, 'issues': issues,
                'revisions': revision, 'connections': [(row.source_id, row.generation, _iso(row.last_sync)) for row in connections],
                'rules': RULE_VERSION, 'provider': provider.VERSION, 'price_policy': shared.PRICE_POLICY}
    digest = hashlib.sha256(_json(identity).encode()).hexdigest()
    return {'snapshot_id': digest, 'period': period, 'generated_at': now.isoformat(), 'window': window,
            'issues': issues, 'sources': sources, 'limitations': limits,
            'capabilities': {'configured': provider.configured(), **({} if provider.configured() else {'code': 'not_configured'})},
            'budget': await mail.budget_snapshot(db, owner)}, revision


def _key(owner, snapshot):
    return hashlib.sha256(_json([owner, snapshot['snapshot_id'], shared.model_identifier(), provider.VERSION, shared.PRICE_POLICY]).encode()).hexdigest()


def _cache(entry, snapshot):
    try:
        document = json.loads(_cipher().decrypt(entry.encrypted_content.encode()))
        if document['snapshot_id'] != snapshot['snapshot_id']: return None
        return {**provider.validate(document['output'], snapshot), 'updated_at': _iso(entry.updated_at)}
    except (InvalidToken, ValueError, TypeError, KeyError, AttributeError, HTTPException, shared.MailBriefError): return None


async def snapshot(db, owner, period='today'):
    result, _ = await _snapshot(db, owner, period)
    result['ai'] = {'state': 'unavailable', 'summary': '', 'issue_notes': []}
    if provider.configured():
        row = (await db.execute(select(PrivateWorkspaceBrief).where(PrivateWorkspaceBrief.cache_key == _key(owner, result),
            PrivateWorkspaceBrief.owner_id == owner, PrivateWorkspaceBrief.state == 'ready'))).scalar_one_or_none()
        if row:
            cached = _cache(row, result)
            if cached: result['ai'] = {**cached, 'updated_at': _iso(row.updated_at)}
    return result


async def _claim(db, owner, data):
    key = _key(owner, data); token = secrets.token_hex(24); now = utcnow()
    await db.execute(mail._insert(db, PrivateWorkspaceBrief).values(cache_key=key, owner_id=owner,
        snapshot_id=data['snapshot_id'], model=shared.model_identifier(), state='pending', lease_token=token,
        lease_until=now + timedelta(seconds=120)).on_conflict_do_nothing(index_elements=['cache_key']))
    entry = (await db.execute(select(PrivateWorkspaceBrief).where(PrivateWorkspaceBrief.cache_key == key,
        PrivateWorkspaceBrief.owner_id == owner).execution_options(populate_existing=True))).scalar_one()
    if entry.state == 'ready':
        cached = _cache(entry, data)
        if cached:
            await db.commit(); return key, None, cached, None
    if entry.lease_token == token:
        await db.commit(); return key, token, None, None
    if entry.lease_until and _aware(entry.lease_until) > now:
        await db.commit(); return key, None, {'state': entry.state, 'summary': '', 'issue_notes': []}, entry.error_code
    changed = await db.execute(update(PrivateWorkspaceBrief).where(PrivateWorkspaceBrief.cache_key == key,
        PrivateWorkspaceBrief.owner_id == owner, or_(PrivateWorkspaceBrief.lease_until.is_(None), PrivateWorkspaceBrief.lease_until <= now))
        .values(state='pending', lease_token=token, lease_until=now + timedelta(seconds=120), error_code=None))
    await db.commit()
    return key, token if changed.rowcount else None, None if changed.rowcount else {'state': 'pending', 'summary': '', 'issue_notes': []}, None


async def _finish(db, context, token, *, ai=None, billing=None, code=None):
    if ai and _aware(utcnow()) >= context['valid_until']:
        return False
    entry = (await db.execute(select(PrivateWorkspaceBrief).where(PrivateWorkspaceBrief.cache_key == context['key'],
        PrivateWorkspaceBrief.owner_id == context['owner_id'], PrivateWorkspaceBrief.lease_token == token)
        .execution_options(populate_existing=True))).scalar_one_or_none()
    refund = mail._settlement(entry, billing) if entry and ai else None
    encrypted = None
    if ai:
        # Store source refs needed by the strict validator; never store a
        # second copy of any connector raw data or mail body.
        output = {'summary': ai['summary'], 'issue_notes': ai['issue_notes'], 'source_refs': ai['source_refs']}
        encrypted = _cipher().encrypt(_json({'snapshot_id': context['snapshot_id'], 'output': output}).encode()).decode()
    values = dict(state='ready' if ai else 'failed', encrypted_content=encrypted, error_code=code,
        lease_token=None, lease_until=None if ai else utcnow() + timedelta(seconds=30))
    if refund is not None: values['reservation_state'] = 'settled'
    changed = await db.execute(update(PrivateWorkspaceBrief).where(PrivateWorkspaceBrief.cache_key == context['key'],
        PrivateWorkspaceBrief.owner_id == context['owner_id'], PrivateWorkspaceBrief.lease_token == token,
        _live(context['owner_id'], context['revision'])).values(**values))
    if changed.rowcount and refund is not None:
        settled = await db.execute(update(PrivateMailBriefUsage).where(PrivateMailBriefUsage.owner_id == context['owner_id'],
            PrivateMailBriefUsage.month == entry.reservation_month, PrivateMailBriefUsage.reserved_usd_micros >= refund,
            PrivateMailBriefUsage.requests >= 1).values(reserved_usd_micros=PrivateMailBriefUsage.reserved_usd_micros - refund))
        if not settled.rowcount: await db.rollback(); return False
    await db.commit(); return bool(changed.rowcount)


async def explain(db, owner, period, snapshot_id):
    data, revision = await _snapshot(db, owner, period)
    data['ai'] = {'state': 'unavailable', 'summary': '', 'issue_notes': []}
    if data['snapshot_id'] != snapshot_id:
        data['ai']['code'] = 'snapshot_changed'; return data
    if not provider.configured(): data['ai']['code'] = 'not_configured'; return data
    key, token, cached, code = await _claim(db, owner, data)
    if cached:
        if (not (await db.execute(select(_live(owner, revision)))).scalar_one()
                or _aware(utcnow()) >= revision['valid_until']):
            data['ai']['code'] = 'snapshot_changed'; return data
        data['ai'] = {**cached, **({'code': code} if code else {})}; return data
    context = {'owner_id': owner, 'key': key, 'snapshot_id': snapshot_id, 'revision': revision,
               'valid_until': revision['valid_until']}

    async def operation():
        reservation = provider.reservation(data)
        if not await mail.reserve_usage(db, owner, reservation['characters'],
                reservation_micro_usd=reservation['reservation_micro_usd'], price_policy=reservation['price_policy'],
                context=context, token=token, receipt_model=PrivateWorkspaceBrief, live_condition=_live(owner, revision)):
            code = await mail._reservation_failure_code(db, owner, context['reservation_month'], reservation['reservation_micro_usd'])
            await _finish(db, context, token, code=code)
            data['ai'] = {'state': 'failed', 'summary': '', 'issue_notes': [], 'code': code}; return data
        await db.commit()
        now = utcnow()
        claimed = exists(select(PrivateWorkspaceBrief.cache_key).where(PrivateWorkspaceBrief.cache_key == key,
            PrivateWorkspaceBrief.owner_id == owner, PrivateWorkspaceBrief.lease_token == token,
            PrivateWorkspaceBrief.state == 'pending', PrivateWorkspaceBrief.lease_until > now,
            PrivateWorkspaceBrief.reservation_state == 'held', PrivateWorkspaceBrief.reservation_month == context['reservation_month'],
            PrivateWorkspaceBrief.reservation_micro_usd == reservation['reservation_micro_usd'],
            PrivateWorkspaceBrief.reservation_price_policy == reservation['price_policy']))
        if not (await db.execute(select(and_(_live(owner, revision), claimed)))).scalar_one():
            raise shared.MailBriefError('snapshot_changed')
        if utcnow().strftime('%Y-%m') != context['reservation_month']: raise shared.MailBriefError('budget_month_changed')
        if _aware(utcnow()) >= context['valid_until']: raise shared.MailBriefError('snapshot_changed')
        ai = await provider.explain(data, reserved_micro_usd=reservation['reservation_micro_usd'], price_policy=reservation['price_policy'])
        public = {key: value for key, value in ai.items() if key != 'billing'}
        if not await _finish(db, context, token, ai=public, billing=ai.get('billing')):
            data['ai']['code'] = 'snapshot_changed'; return data
        data['ai'] = public; data['budget'] = await mail.budget_snapshot(db, owner); return data

    try:
        return await asyncio.wait_for(operation(), timeout=55)
    except (shared.MailBriefError, asyncio.TimeoutError, TimeoutError, HTTPException) as error:
        await db.rollback(); code = mail._public_error(error)
        await _finish(db, context, token, code=code)
        data['ai'] = {'state': 'failed', 'summary': '', 'issue_notes': [], 'code': code}
        data['budget'] = await mail.budget_snapshot(db, owner); return data
