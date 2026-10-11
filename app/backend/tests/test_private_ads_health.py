"""Synthetic private Ads observations: no credentials, live requests or money writes."""
from datetime import datetime, timezone

import pytest

from services.private_ads_health import build_ads_health, metric_row
from services.private_workspace import safe_json


NOW = datetime(2026, 10, 11, 5, 0, tzinfo=timezone.utc)  # Oct 10 in the advertiser's time zone.


def campaign(**changes):
    return {'id': '123', 'status': 'ENABLED', 'primaryStatus': 'ELIGIBLE', 'servingStatus': 'SERVING',
            'primaryStatusReasons': [], 'advertisingChannelType': 'SEARCH',
            'startDateTime': '2026-08-01 00:00:00', **changes}


def metrics(impressions=100, clicks=10, cost=10_000_000, conversions=1.5):
    return metric_row({'impressions': impressions, 'clicks': clicks, 'costMicros': cost, 'conversions': conversions})


def health(value=None, days=None, **changes):
    arguments = {'account_timezone': 'America/Los_Angeles', 'currency': 'USD',
                 'tracking_status': 'CONVERSION_TRACKING_MANAGED_BY_SELF', 'snapshot_id': 'synthetic-snapshot',
                 'observed_at': NOW, 'inventory_complete': True, 'metrics_complete': True}
    arguments.update(changes)
    return build_ads_health(campaign() if value is None else value, metrics(),
                            {'2026-10-09': metrics()} if days is None else days, **arguments)


@pytest.mark.parametrize('value', [campaign(status='PAUSED'), campaign(status='REMOVED'),
    campaign(primaryStatus='ENDED'), campaign(servingStatus='ENDED'),
    campaign(endDateTime='2026-10-09 23:59:59'), campaign(primaryStatusReasons=['AD_GROUPS_PAUSED'])])
def test_planned_or_user_paused_campaign_is_expected_inactive_not_a_fault(value):
    result = health(value, metrics_complete=False)
    assert result['bucket'] == 'paused' and '不作为投放效果异常' in result['impact']
    assert result['metrics']['last_7_days'] is None


@pytest.mark.parametrize('value', [campaign(primaryStatus='MISCONFIGURED'), campaign(primaryStatus='NOT_ELIGIBLE'),
    campaign(servingStatus='SUSPENDED'), campaign(primaryStatusReasons=['BUDGET_MISCONFIGURED']),
    campaign(primaryStatusReasons=['BIDDING_STRATEGY_MISCONFIGURED']), campaign(primaryStatusReasons=['NO_KEYWORDS'])])
def test_explicit_platform_fault_survives_incomplete_metrics_and_inventory(value):
    result = health(value, inventory_complete=False, metrics_complete=False)
    assert result['bucket'] == 'problem' and result['metrics']['yesterday'] is None
    assert result['coverage'] == {'inventory_complete': False, 'metrics_complete': False}
    assert '可能' in result['impact'] and 'Google Ads' in result['next_action']


@pytest.mark.parametrize('reason', ['BUDGET_CONSTRAINED', 'BIDDING_STRATEGY_CONSTRAINED', 'HAS_ADS_DISAPPROVED',
                                  'HAS_ADS_LIMITED_BY_POLICY', 'SEARCH_VOLUME_LIMITED'])
def test_platform_limit_is_attention_with_no_automatic_budget_recommendation(reason):
    result = health(campaign(primaryStatusReasons=[reason]))
    assert result['bucket'] == 'attention' and '不能直接作为增加预算' in result['next_action']


@pytest.mark.parametrize('value', [campaign(primaryStatus='LEARNING'), campaign(primaryStatus='PENDING'),
    campaign(biddingStrategySystemStatus='LEARNING_NEW'), campaign(primaryStatusReasons=['MOST_ADS_UNDER_REVIEW']),
    campaign(startDateTime='2026-10-08 00:00:00'), campaign(startDateTime='2026-10-12 00:00:00')])
def test_learning_new_or_future_campaign_waits_even_with_high_observed_cpa(value):
    value.update(biddingStrategyType='TARGET_CPA', targetCpa={'targetCpaMicros': 1})
    result = health(value, days={'2026-10-09': metrics(conversions=35)})
    assert result['bucket'] == 'unknown'


@pytest.mark.parametrize('value', [campaign(primaryStatus='UNKNOWN'), campaign(servingStatus='NONE'),
                                  campaign(status='UNKNOWN'), campaign(primaryStatusReasons=['UNKNOWN'])])
def test_eligible_or_enabled_alone_does_not_prove_current_delivery(value):
    assert health(value)['bucket'] == 'unknown'


@pytest.mark.parametrize('tracking,value,assessment', [
    ('NOT_CONVERSION_TRACKED', campaign(), '追踪'),
    ('UNKNOWN', campaign(), '追踪'),
    ('CONVERSION_TRACKING_MANAGED_BY_SELF', campaign(), '明确 CPA 目标'),
    ('CONVERSION_TRACKING_MANAGED_BY_SELF', campaign(biddingStrategyType='TARGET_CPA', targetCpa={'targetCpaMicros': 1}), '少于30'),
    ('CONVERSION_TRACKING_MANAGED_BY_SELF', campaign(biddingStrategyType='TARGET_CPA', targetCpa={'targetCpaMicros': 1},
                                                   biddingStrategy='customers/123/biddingStrategies/456'), '组合出价'),
])
def test_normal_delivery_and_effect_assessment_are_separate(tracking, value, assessment):
    result = health(value, tracking_status=tracking)
    assert result['bucket'] == 'healthy' and '昨日有展示' in result['reason']
    assert '不代表效果好或盈利' in result['impact']
    assert assessment in result['target']['assessment']


def test_inventory_truncation_alone_does_not_deny_complete_item_delivery():
    result = health(inventory_complete=False)
    assert result['bucket'] == 'healthy' and result['coverage']['inventory_complete'] is False


def test_missing_metrics_are_never_zero_filled_or_called_healthy():
    result = health(metrics_complete=False)
    assert result['bucket'] == 'unknown'
    assert all(value is None for value in result['metrics'].values())
    assert '缺失数据不能当作零' in result['impact']


def test_zero_yesterday_with_earlier_delivery_remains_unconfirmed():
    result = health(days={'2026-10-08': metrics()})
    assert result['bucket'] == 'unknown' and result['metrics']['last_7_days']['impressions'] > 0
    assert '昨日未记录曝光' in result['reason']


def test_old_campaign_with_no_exposure_requests_review_without_claiming_fault():
    result = health(days={})
    assert result['bucket'] == 'attention' and '近7天未记录曝光' in result['reason']
    assert '不代表已确认广告故障' in result['impact']


@pytest.mark.parametrize('target_structure,source', [
    ({'biddingStrategyType': 'TARGET_CPA', 'targetCpa': {'targetCpaMicros': '1000000'}}, 'campaign.target_cpa'),
    ({'biddingStrategyType': 'MAXIMIZE_CONVERSIONS', 'maximizeConversions': {'targetCpaMicros': '1000000'}}, 'campaign.maximize_conversions')])
def test_cpa_uses_explicit_current_target_with_enough_conversions_only_as_review(target_structure, source):
    result = health(campaign(**target_structure), days={'2026-10-09': metrics(cost=60_000_000, conversions=30)})
    assert result['bucket'] == 'attention' and 'CPA 目标' in result['reason']
    assert '不代表已确认投放失败或亏损' in result['impact']
    assert result['target']['source'] == source and result['target']['cpa_micros'] == 1_000_000
    assert '归因延迟' in result['target']['assessment'] and '当前目标不等于期间平均目标' in result['limitations']


@pytest.mark.parametrize('tracking,value,count', [
    ('NOT_CONVERSION_TRACKED', campaign(biddingStrategyType='TARGET_CPA', targetCpa={'targetCpaMicros': 1}), 35),
    ('CONVERSION_TRACKING_MANAGED_BY_SELF', campaign(), 35),
    ('CONVERSION_TRACKING_MANAGED_BY_SELF', campaign(biddingStrategyType='TARGET_CPA', targetCpa={'targetCpaMicros': 1},
                                                   biddingStrategy='customers/123/biddingStrategies/456'), 35),
    ('CONVERSION_TRACKING_MANAGED_BY_SELF', campaign(biddingStrategyType='TARGET_CPA', targetCpa={'targetCpaMicros': 1}), 29.999),
])
def test_unsafe_cpa_comparison_does_not_turn_normal_delivery_into_an_effect_problem(tracking, value, count):
    result = health(value, days={'2026-10-09': metrics(cost=99_000_000, conversions=count)}, tracking_status=tracking)
    assert result['bucket'] == 'healthy' and '暂不评价效果' in result['target']['assessment']


def test_fractional_conversions_exact_cost_and_zero_baseline_are_preserved():
    result = health(days={'2026-10-09': metrics(cost=1000501, conversions='1.25'),
                         '2026-10-08': metrics(cost=2000002, conversions='0.125')})
    assert result['metrics']['last_7_days']['conversions'] == 1.375
    assert result['metrics']['last_7_days']['cost_micros'] == 3000503
    assert result['comparison']['cost_change_pct'] is None
    assert result['comparison']['conversions_change_pct'] is None


def test_nonzero_prior_comparison_is_observation_with_no_percentage_threshold():
    result = health(days={'2026-10-09': metrics(clicks=15, cost=3_000_000, conversions=3),
                         '2026-10-01': metrics(clicks=10, cost=1_000_000, conversions=2)})
    assert result['comparison']['clicks_change_pct'] == 50.0
    assert result['comparison']['cost_change_pct'] == 200.0
    assert result['comparison']['conversions_change_pct'] == 50.0
    assert result['bucket'] == 'healthy'


@pytest.mark.parametrize('raw', [{'costMicros': '1.5'}, {'costMicros': True}, {'costMicros': -1},
                                {'costMicros': 'NaN'}, {'conversions': 'Infinity'}, {'conversions': -0.5},
                                {'impressions': 9_000_000_000_000_001}])
def test_invalid_metrics_are_rejected(raw):
    with pytest.raises(ValueError): metric_row(raw)


def test_periods_use_advertiser_timezone_and_exclude_today():
    result = health()
    assert result['local_date'] == '2026-10-10'
    assert result['periods']['yesterday'] == {'start': '2026-10-09', 'end': '2026-10-09'}
    assert result['periods']['last_7_days'] == {'start': '2026-10-03', 'end': '2026-10-09'}
    assert result['periods']['previous_7_days'] == {'start': '2026-09-26', 'end': '2026-10-02'}
    assert result['periods']['last_30_days'] == {'start': '2026-09-10', 'end': '2026-10-09'}


@pytest.mark.parametrize('day', ['2026-10-10', '2026-09-25', '2026-09-31', 'malformed'])
def test_invalid_or_outside_window_daily_dates_are_rejected(day):
    with pytest.raises(ValueError): health(days={day: metrics()})


@pytest.mark.parametrize('value', [campaign(startDateTime='2026-02-30 00:00:00'),
                                 campaign(endDateTime='2026-07-01 00:00:00')])
def test_invalid_campaign_schedule_is_not_used_for_a_health_claim(value):
    with pytest.raises(ValueError): health(value)


def test_full_health_contract_survives_private_persistence_sanitization():
    result = health(campaign(primaryStatusReasons=['HAS_ADS_LIMITED_BY_POLICY'], biddingStrategyType='TARGET_CPA',
                             targetCpa={'targetCpaMicros': 1_000_000}))
    evidence = {'customer_id': '1234567890', 'campaign_id': '123', 'ads_snapshot_id': 'synthetic-snapshot', 'ads_health': result,
                'accounting_effect': 'none'}
    assert safe_json(evidence) == evidence
    assert safe_json(evidence)['ads_health']['metrics']['yesterday']['conversions'] == 1.5
    assert safe_json(evidence)['ads_health']['periods']['last_7_days']['start'] == '2026-10-03'
    assert safe_json(evidence)['ads_health']['current']['primary_status_reasons'] == ['HAS_ADS_LIMITED_BY_POLICY']
