"""Deterministic observations of private Google Ads snapshots; no actions or CRM.

Platform state is separate from performance. CPA is compared only with an
explicit current campaign target, never an invented business threshold. Google
recommends periods with at least 30 conversions for more accurate Target CPA
assessment; this guard is not a promise of statistical significance or profit.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import math
import re
from zoneinfo import ZoneInfo

METRIC_FIELDS = ('impressions', 'clicks', 'cost_micros', 'conversions')
TRACKED = {'CONVERSION_TRACKING_MANAGED_BY_SELF', 'CONVERSION_TRACKING_MANAGED_BY_THIS_MANAGER',
           'CONVERSION_TRACKING_MANAGED_BY_ANOTHER_MANAGER'}
MIN_CPA_CONVERSIONS = 30
_LIMITATIONS = ['当前目标不等于期间平均目标', '近期转化可能有归因延迟', '未核验广告组覆盖目标与各转化动作安装质量']


def _number(value, *, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)): raise ValueError('invalid metric')
    try: number = Decimal(str(value))
    except InvalidOperation: raise ValueError('invalid metric') from None
    if not number.is_finite() or number < 0 or number > 9_000_000_000_000_000: raise ValueError('invalid metric')
    if integer:
        if number != number.to_integral_value(): raise ValueError('invalid integer metric')
        return int(number)
    result = float(number)
    if not math.isfinite(result): raise ValueError('invalid metric')
    return result


def metric_row(raw):
    if not isinstance(raw, dict): raise ValueError('invalid metric')
    # REST omits protobuf default zero values. Only the adapter's complete
    # fixed report may fill an entirely absent campaign row with zero.
    return {'impressions': _number(raw.get('impressions', 0), integer=True),
            'clicks': _number(raw.get('clicks', 0), integer=True),
            'cost_micros': _number(raw.get('costMicros', 0), integer=True),
            'conversions': _number(raw.get('conversions', 0))}


def _zero(): return {'impressions': 0, 'clicks': 0, 'cost_micros': 0, 'conversions': 0.0}


def _sum(days, start, end):
    result = _zero()
    for day, values in days.items():
        if start <= day <= end:
            for key in METRIC_FIELDS:
                result[key] += values[key]
                if result[key] > 9_000_000_000_000_000: raise ValueError('metric sum outside safe range')
    result['conversions'] = float(Decimal(str(result['conversions'])).quantize(Decimal('0.000001')))
    return result


def _enum(value):
    return value if isinstance(value, str) and re.fullmatch(r'[A-Z][A-Z0-9_]{0,79}', value) else 'UNKNOWN'


def _local_time(value):
    if not value: return None
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', value): raise ValueError('invalid campaign datetime')
    try: return datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
    except ValueError: raise ValueError('invalid campaign datetime') from None


def _change(current, previous):
    if previous <= 0: return None
    return round((current - previous) / previous * 100, 2)


def build_ads_health(campaign, monthly, days, *, account_timezone, currency, tracking_status, snapshot_id,
                     observed_at, inventory_complete, metrics_complete):
    if not isinstance(campaign, dict) or not isinstance(days, dict): raise ValueError('invalid health input')
    if observed_at.tzinfo is None: raise ValueError('timezone required')
    local_now = observed_at.astimezone(ZoneInfo(account_timezone)); today = local_now.date()
    first_14 = today - timedelta(days=14); yesterday = today - timedelta(days=1)
    for day in days:
        try: parsed = date.fromisoformat(day)
        except (TypeError, ValueError): raise ValueError('invalid report date') from None
        if not first_14 <= parsed <= yesterday: raise ValueError('report date outside fixed window')
    start = _local_time(campaign.get('startDateTime')); end = _local_time(campaign.get('endDateTime'))
    if start and end and end < start: raise ValueError('invalid campaign period')
    reasons = campaign.get('primaryStatusReasons', [])
    if not isinstance(reasons, list) or len(reasons) > 40: raise ValueError('invalid primary status reasons')
    current = {'status': _enum(campaign.get('status')), 'primary_status': _enum(campaign.get('primaryStatus')),
               'primary_status_reasons': [_enum(reason) for reason in reasons],
               'serving_status': _enum(campaign.get('servingStatus')), 'channel': _enum(campaign.get('advertisingChannelType')),
               'start_date_time': campaign.get('startDateTime') or None, 'end_date_time': campaign.get('endDateTime') or None}
    periods = {'yesterday': {'start': yesterday.isoformat(), 'end': yesterday.isoformat()},
               'last_7_days': {'start': (today - timedelta(days=7)).isoformat(), 'end': yesterday.isoformat()},
               'previous_7_days': {'start': first_14.isoformat(), 'end': (today - timedelta(days=8)).isoformat()},
               'last_30_days': {'start': (today - timedelta(days=30)).isoformat(), 'end': yesterday.isoformat()}}
    metrics = {key: None for key in periods}
    if metrics_complete:
        metrics['last_30_days'] = dict(monthly) if monthly is not None else _zero()
        for key in ('yesterday', 'last_7_days', 'previous_7_days'):
            metrics[key] = _sum(days, periods[key]['start'], periods[key]['end'])
    tracking_status = _enum(tracking_status)
    tracking_state = 'configured' if tracking_status in TRACKED else 'unconfigured' if tracking_status == 'NOT_CONVERSION_TRACKED' else 'unknown'
    target_value = None; target_source = 'unavailable'; strategy = _enum(campaign.get('biddingStrategyType'))
    if strategy == 'TARGET_CPA':
        value = (campaign.get('targetCpa') or {}).get('targetCpaMicros')
        if value is not None and _number(value, integer=True) > 0:
            target_value = _number(value, integer=True); target_source = 'campaign.target_cpa'
    elif strategy == 'MAXIMIZE_CONVERSIONS':
        value = (campaign.get('maximizeConversions') or {}).get('targetCpaMicros')
        if value is not None and _number(value, integer=True) > 0:
            target_value = _number(value, integer=True); target_source = 'campaign.maximize_conversions'
    comparison = {'clicks_change_pct': None, 'cost_change_pct': None, 'conversions_change_pct': None,
                  'note': '变化仅供复核，近期转化可能有归因延迟；前期为零时不计算百分比'}
    if metrics_complete:
        comparison.update({out: _change(metrics['last_7_days'][key], metrics['previous_7_days'][key])
                           for key, out in (('clicks', 'clicks_change_pct'), ('cost_micros', 'cost_change_pct'), ('conversions', 'conversions_change_pct'))})
    assessment = '暂不评价效果'
    if not metrics_complete: assessment = '指标覆盖不完整，暂不评价效果'
    elif tracking_state != 'configured': assessment = '转化追踪未启用或状态不明，暂不评价效果'
    elif target_value is None: assessment = '未取得当前系列的明确 CPA 目标，暂不评价效果'
    elif campaign.get('biddingStrategy'): assessment = '使用组合出价策略，未核验有效目标，暂不评价效果'
    elif metrics['last_7_days']['conversions'] < MIN_CPA_CONVERSIONS: assessment = '近7天少于30次转化，样本有限，暂不评价效果'
    else: assessment = '仅与当前系列目标作观察比较，需复核期间目标变化、广告组覆盖目标和归因延迟'
    health = {'version': 1, 'snapshot_id': snapshot_id, 'bucket': 'unknown', 'reason': '信息不足，暂不评价投放效果',
              'impact': '当前快照不足以作出效果判断', 'next_action': '补齐信息后再观察，查看 Google Ads 原始状态',
              'observed_at': observed_at.astimezone(timezone.utc).isoformat(), 'account_timezone': account_timezone,
              'local_date': today.isoformat(), 'currency': currency, 'current': current, 'metrics': metrics, 'periods': periods,
              'comparison': comparison, 'target': {'cpa_micros': target_value, 'source': target_source, 'assessment': assessment},
              'tracking': {'state': tracking_state, 'status': tracking_status, 'note': '账户追踪状态不代表每个转化动作均已正确安装'},
              'coverage': {'inventory_complete': bool(inventory_complete), 'metrics_complete': bool(metrics_complete)},
              'limitations': list(_LIMITATIONS)}

    def classify(bucket, reason, impact, next_action):
        health.update(bucket=bucket, reason=reason, impact=impact, next_action=next_action)
        return health

    status = current['status']; primary = current['primary_status']; serving = current['serving_status']; reason_set = set(current['primary_status_reasons'])
    if (status in {'PAUSED', 'REMOVED'} or primary in {'PAUSED', 'REMOVED', 'ENDED'} or serving == 'ENDED'
            or reason_set & {'CAMPAIGN_PAUSED', 'CAMPAIGN_REMOVED', 'CAMPAIGN_ENDED', 'CAMPAIGN_GROUP_PAUSED',
                             'CAMPAIGN_GROUP_ALL_GROUP_BUDGETS_ENDED', 'AD_GROUPS_PAUSED', 'AD_GROUP_ADS_PAUSED', 'KEYWORDS_PAUSED', 'ASSET_GROUPS_PAUSED'}
            or end and end < local_now.replace(tzinfo=None)):
        return classify('paused', '已暂停、移除或按计划结束', '这是当前已知的停投状态，不作为投放效果异常', '需要恢复时先在 Google Ads 确认停投原因和原计划')
    if (primary in {'MISCONFIGURED', 'NOT_ELIGIBLE'} or serving == 'SUSPENDED'
            or reason_set & {'BUDGET_MISCONFIGURED', 'BIDDING_STRATEGY_MISCONFIGURED', 'NO_AD_GROUPS', 'NO_AD_GROUP_ADS',
                             'NO_KEYWORDS', 'NO_ASSET_GROUPS', 'NO_MOBILE_APPLICATION_AD_GROUP_CRITERIA',
                             'MISSING_LEAD_FORM_EXTENSION', 'MISSING_CALL_EXTENSION', 'MISSING_LOCATION_TARGETING',
                             'LEAD_FORM_EXTENSION_DISAPPROVED', 'CALL_EXTENSION_DISAPPROVED', 'APP_NOT_RELEASED'}):
        return classify('problem', 'Google 标记配置错误或当前不可投放', '当前广告系列可能无法正常展示', '打开 Google Ads，检查系列状态给出的配置或资格原因')
    if primary == 'LIMITED' or reason_set & {'BUDGET_CONSTRAINED', 'BIDDING_STRATEGY_CONSTRAINED', 'BIDDING_STRATEGY_LIMITED',
                                           'HAS_ADS_DISAPPROVED', 'HAS_ADS_LIMITED_BY_POLICY', 'HAS_ASSET_GROUPS_DISAPPROVED', 'HAS_ASSET_GROUPS_LIMITED_BY_POLICY',
                                           'SEARCH_VOLUME_LIMITED', 'APP_PARTIALLY_RELEASED'}:
        return classify('attention', 'Google 提示投放受限或部分广告受影响', '展示范围或部分广告可能受限制，需逐项核查', '查看 Google Ads 原因明细；预算限制不能直接作为增加预算的依据')
    system_status = _enum(campaign.get('biddingStrategySystemStatus'))
    if (primary in {'LEARNING', 'PENDING'} or serving == 'PENDING' or system_status.startswith('LEARNING_') or system_status == 'MULTIPLE_LEARNING'
            or reason_set & {'BIDDING_STRATEGY_LEARNING', 'CAMPAIGN_PENDING', 'CAMPAIGN_DRAFT', 'MOST_ADS_UNDER_REVIEW',
                             'MOST_ASSET_GROUPS_UNDER_REVIEW', 'LEAD_FORM_EXTENSION_UNDER_REVIEW', 'CALL_EXTENSION_UNDER_REVIEW',
                             'CAMPAIGN_NOT_BOOKED', 'BOOKING_CANCELLED', 'BOOKING_HOLD_EXPIRED', 'BOOKING_HOLD_EXPIRING'}):
        return classify('unknown', '广告处于学习或待投放阶段', '当前数据不适合直接判断效果', '先观察投放状态和转化周期，避免仅据短期波动调整')
    if start and (local_now.replace(tzinfo=None) - start).days < 7:
        return classify('unknown', '广告刚开始或尚未开始，继续观察', '尚未覆盖完整近7天窗口', '先确认计划开始时间，等待完整窗口和转化数据')
    if not metrics_complete:
        return classify('unknown', '指标覆盖不完整，待确认', '缺失数据不能当作零曝光或零转化', '重新同步并核对覆盖范围，再评估效果')
    if status != 'ENABLED' or primary != 'ELIGIBLE' or serving != 'SERVING':
        return classify('unknown', '当前投放状态尚未确认', 'ENABLED 或 ELIGIBLE 单独不代表正在展示或效果良好', '在 Google Ads 核对当前展示状态与原因')
    if reason_set:
        return classify('unknown', 'Google 状态原因待确认', '存在尚未核验的状态原因，不能据此标记正常投放', '打开 Google Ads，核对系列状态原因后再观察')
    if start and start.date() <= today - timedelta(days=7) and metrics['last_7_days']['impressions'] == 0:
        return classify('attention', '近7天未记录曝光，需复核', '完整快照中没有近期展示记录，不代表已确认广告故障', '核对排期、状态与搜索量，不要直接增加预算')
    can_compare_cpa = (tracking_state == 'configured' and target_value is not None
                       and not campaign.get('biddingStrategy')
                       and metrics['last_7_days']['conversions'] >= MIN_CPA_CONVERSIONS)
    if can_compare_cpa:
        actual_cpa = Decimal(metrics['last_7_days']['cost_micros']) / Decimal(str(metrics['last_7_days']['conversions']))
        if actual_cpa > target_value:
            return classify('attention', '近7天转化费用高于当前系列 CPA 目标，需复核', '这是与当前目标的观察比较，不代表已确认投放失败或亏损', '核对期间平均目标、转化延迟及广告组覆盖目标，再决定是否调整')
    if metrics['yesterday']['impressions'] == 0:
        return classify('unknown', '昨日未记录曝光，当前展示待确认', '近7天有数据也不能确认昨日或当前正在展示', '查看 Google Ads 当前展示状态与昨日排期，效果评估另行核对')
    return classify('healthy', 'Google 显示可投放，昨日有展示', '仅表示已观察到正常投放，不代表效果好或盈利', '继续观察展示状态；结合转化追踪、实际目标和业务结果另行评估效果')
