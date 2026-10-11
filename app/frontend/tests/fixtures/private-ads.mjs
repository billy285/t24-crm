// Synthetic UI fixtures only. No live advertiser or merchant data.
export function adsFixture(bucket = 'healthy', index = 1, override = {}) {
  const observed_at = new Date().toISOString();
  const metric = { impressions: 700, clicks: 70, cost_micros: 35000000, conversions: 10.5 };
  const health = {
    version: 1, snapshot_id: 'synthetic-snapshot', bucket, observed_at, account_timezone: 'America/Los_Angeles', local_date: '2026-10-11', currency: 'USD',
    reason: { problem: 'Google 标记广告配置错误', attention: 'Google 标记预算受限', healthy: 'Google 显示可投放，昨日有展示', paused: '广告系列已主动暂停', unknown: '广告系列处于学习阶段' }[bucket],
    impact: bucket === 'problem' ? '当前可能无法正常展示' : '不代表效果好或盈利',
    next_action: bucket === 'problem' ? '检查预算配置原因' : '打开 Google Ads 核实当前设置',
    current: { status: bucket === 'paused' ? 'PAUSED' : 'ENABLED', primary_status: bucket === 'problem' ? 'MISCONFIGURED' : 'ELIGIBLE', primary_status_reasons: bucket === 'problem' ? ['BUDGET_MISCONFIGURED'] : [], serving_status: bucket === 'paused' ? 'NONE' : 'SERVING', channel: 'SEARCH', start_date_time: '2026-09-01 00:00:00', end_date_time: null },
    metrics: { yesterday: { ...metric, impressions: 100, clicks: 10, cost_micros: 5000000, conversions: 1.5 }, last_7_days: metric, previous_7_days: metric, last_30_days: metric },
    periods: { yesterday: { start: '2026-10-10', end: '2026-10-10' }, last_7_days: { start: '2026-10-04', end: '2026-10-10' }, previous_7_days: { start: '2026-09-27', end: '2026-10-03' }, last_30_days: { start: '2026-09-11', end: '2026-10-10' } },
    comparison: { clicks_change_pct: -22.2, cost_change_pct: -12.5, conversions_change_pct: -16.7, note: '变化仅供复核，近期转化可能有归因延迟' },
    target: { cpa_micros: 10000000, source: 'campaign.target_cpa', assessment: '近7日样本不足，暂不评价效果' },
    tracking: { state: 'configured', status: 'CONVERSION_TRACKING_MANAGED_BY_SELF', note: '未核验每个转化动作安装质量' },
    coverage: { inventory_complete: true, metrics_complete: true }, limitations: ['当前目标不等于期间平均目标'], ...override,
  };
  const source = { id: 'google_ads', name: 'Google Ads', status: 'connected', capabilities: ['read_campaign_metrics'], missing_configuration: [], last_sync: observed_at, error: null, metadata: { account_label: '合成广告账户', ads_customer_id: '1234567890', ads_snapshot: { id: 'synthetic-snapshot', observed_at, account_timezone: 'America/Los_Angeles', inventory_count: 5, inventory_complete: true, metrics_complete: true, record_limit: 100 } } };
  const item = { id: `synthetic-ads-${index}`, source_id: 'google_ads', kind: 'campaign', title: `合成广告系列 ${index}`, summary: '旧摘要不可作为健康判断', status: 'ENABLED', priority: 'high', amount_minor: null, currency: 'USD', occurred_at: observed_at, due_at: null, source_url: 'https://ads.google.com/aw/overview', evidence: { ads_snapshot_id: 'synthetic-snapshot', ads_health: health }, action_status: 'open', snoozed_until: null };
  return { source, item, health };
}
