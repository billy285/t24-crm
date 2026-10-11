import { useMemo, useState } from 'react';
import { ArrowUpRight, ChevronRight, LoaderCircle, RefreshCw, Search } from 'lucide-react';
import { privateSourceActionAvailability, verifiedPrivateSourceUrl, type PrivateAdsBucket, type PrivateAdsHealth, type PrivateItem, type PrivateSource } from '@/lib/private-workspace-api';
import { ADS_BUCKET_NAMES, ADS_BUCKETS, privateAdsActualCpa, privateAdsReasons, privateAdsConversions, privateAdsMetric, privateAdsMoney, privateAdsNumber, privateAdsObservation, privateAdsPeriod, privateAdsStatus, privateAdsTime } from '@/lib/private-ads';

type AdsRow = { item: PrivateItem; observation: ReturnType<typeof privateAdsObservation> };
export type PrivateAdsNavigation = { query: string; choice: { snapshot: string; bucket: 'all' | PrivateAdsBucket } };
type Props = {
  source?: PrivateSource;
  now: number;
  accountLabel: string;
  items: PrivateItem[];
  total: number;
  loading: boolean;
  error: string;
  busy: boolean;
  syncing: boolean;
  onSelect: (item: PrivateItem) => void;
  onManage: () => void;
  onSync: () => void;
  onRetry: () => void;
  initialNavigation?: PrivateAdsNavigation;
  onNavigationChange?: (navigation: PrivateAdsNavigation) => void;
};
function Badge({ bucket }: { bucket: PrivateAdsBucket }) {
  return <span className={`pw-ads-badge pw-ads-badge-${bucket}`}>{ADS_BUCKET_NAMES[bucket]}</span>;
}
function Row({ row, onSelect }: { row: AdsRow; onSelect: Props['onSelect'] }) {
  const health = row.observation.health;
  const metric = privateAdsMetric(health?.metrics?.last_7_days);
  return <button type="button" className="pw-ads-row" onClick={() => onSelect(row.item)}>
    <span className="pw-ads-row-copy"><span className="pw-ads-row-title"><strong>{row.item.title}</strong><Badge bucket={row.observation.bucket} /></span><span className="pw-ads-row-reason">{row.observation.reason}</span><span className="pw-ads-row-metrics"><span>近7日费用 <b>{privateAdsMoney(metric?.cost_micros, health?.currency)}</b></span><span>近7日转化 <b>{privateAdsConversions(health, metric)}</b></span></span></span><ChevronRight aria-hidden="true" />
  </button>;
}

export default function PrivateAdsDashboard({ source, now, accountLabel, items, total, loading, error, busy, syncing, onSelect, onManage, onSync, onRetry, initialNavigation, onNavigationChange }: Props) {
  const [query, setQuery] = useState(initialNavigation?.query || '');
  const [choice, setChoice] = useState<PrivateAdsNavigation['choice']>(initialNavigation?.choice || { snapshot: '', bucket: 'all' });
  function changeQuery(next: string) { setQuery(next); onNavigationChange?.({ query: next, choice }); }
  function changeBucket(next: PrivateAdsNavigation['choice']) { setQuery(''); setChoice(next); onNavigationChange?.({ query: '', choice: next }); }
  const snapshot = source?.metadata?.ads_snapshot;
  const rows = useMemo(() => items.filter(item => item.source_id === 'google_ads').map(item => ({ item, observation: privateAdsObservation(item, source, now) })), [items, source, now]);
  const counts = Object.fromEntries(ADS_BUCKETS.map(bucket => [bucket, rows.filter(row => row.observation.bucket === bucket).length])) as Record<PrivateAdsBucket, number>;
  const snapshotKey = snapshot?.id || rows.map(row => row.item.id).join('|');
  const defaultBucket = (['problem', 'attention', 'healthy', 'unknown', 'paused'] as PrivateAdsBucket[]).find(value => counts[value] > 0) || 'all';
  const desiredBucket = choice.snapshot === snapshotKey ? choice.bucket : defaultBucket;
  const bucket = desiredBucket !== 'all' && !counts[desiredBucket] ? defaultBucket : desiredBucket;
  const filtered = rows.filter(row => (query.trim() || bucket === 'all' || row.observation.bucket === bucket) && `${row.item.title} ${row.observation.reason} ${row.observation.impact} ${row.observation.nextAction}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  const priority = [...rows.filter(row => row.observation.bucket === 'problem'), ...rows.filter(row => row.observation.bucket === 'attention')].slice(0, 3);
  const partial = Boolean(source?.metadata?.partial || snapshot?.inventory_complete === false || total > rows.length);
  const canSync = source && privateSourceActionAvailability(source).canSync;
  const unreliable = rows.some(row => !row.observation.verified);
  return <div className="pw-ads-dashboard">
    <div className="pw-ads-source"><div><p className="pw-ads-account"><span className="pw-account-label">{accountLabel ? `广告账户：${accountLabel}` : '广告账户尚未连接'}</span></p><span>检查时间（本机）：{privateAdsTime(snapshot?.observed_at)}</span></div><div className="pw-ads-source-actions">{canSync && <button type="button" className="pw-button" disabled={busy} onClick={onSync}><RefreshCw aria-hidden="true" />{syncing ? '正在同步…' : '同步'}</button>}<button type="button" className="pw-text-button" disabled={busy} onClick={onManage}>{source?.status === 'connected' ? '管理接入' : '连接广告账户'}<ChevronRight aria-hidden="true" /></button></div></div>
    {source?.error && <p className="pw-ads-coverage pw-ads-coverage-warning" role="alert">广告同步需要检查，当前不判断投放是否正常。请同步重试或管理接入。</p>}
    {loading ? <div className="pw-load" role="status"><LoaderCircle aria-hidden="true" />正在读取广告检查…</div> : error ? <div className="pw-load pw-error" role="alert"><p>{error}</p><button type="button" className="pw-button" onClick={onRetry}>重新读取</button></div> : <>
      <div className="pw-ads-summary" aria-label="已同步广告检查概况"><div><span>需处理</span><strong>{counts.problem + counts.attention}</strong><small>{counts.problem ? `${counts.problem} 项异常停投` : counts.attention ? '有事项需要复核' : !rows.length || counts.unknown === rows.length ? '待完成检查' : '当前已查记录未见待处理问题'}</small></div><div><span>正常投放</span><strong>{counts.healthy}</strong><small>已查投放项未见异常</small></div><div><span>暂停结束</span><strong>{counts.paused}</strong><small>与投放异常分开查看</small></div></div>
      <p className={`pw-ads-coverage ${unreliable || partial ? 'pw-ads-coverage-warning' : ''}`}>{!rows.length ? '尚无可判断的广告检查数据。' : `当前显示 ${rows.length} 条已同步广告系列${partial ? '，仅包含部分广告系列' : ''}。`}{unreliable && ' 部分记录待观察，请检查同步与数据依据。'}{partial && ' 分类数量不代表完整账户。'}</p>
      {priority.length > 0 && <section className="pw-ads-priority"><div className="pw-section-heading"><h2>优先处理<small>{counts.problem + counts.attention > 3 ? '先看这 3 项' : `${counts.problem + counts.attention} 项`}</small></h2></div><div className="pw-ads-priority-grid">{priority.map(row => <article key={row.item.id}><div className="pw-ads-priority-title"><strong>{row.item.title}</strong><Badge bucket={row.observation.bucket} /></div><dl><div><dt>问题</dt><dd>{row.observation.reason}</dd></div><div><dt>影响</dt><dd>{row.observation.impact}</dd></div><div><dt>下一步</dt><dd>{row.observation.nextAction}</dd></div></dl><button type="button" className="pw-text-button" onClick={() => onSelect(row.item)}>查看检查<ArrowUpRight aria-hidden="true" /></button></article>)}</div></section>}
      <section className="pw-ads-records"><div className="pw-ads-toolbar"><div className="pw-ads-filters" aria-label="广告投放分类"><button type="button" aria-pressed={!query.trim() && bucket === 'all'} onClick={() => { changeBucket({ snapshot: snapshotKey, bucket: 'all' }); }}>全部<small>{rows.length}</small></button>{ADS_BUCKETS.filter(value => counts[value] > 0).map(value => <button key={value} type="button" aria-pressed={!query.trim() && bucket === value} onClick={() => { changeBucket({ snapshot: snapshotKey, bucket: value }); }}>{ADS_BUCKET_NAMES[value]}<small>{counts[value]}</small></button>)}</div><label className="pw-ads-search"><Search aria-hidden="true" /><input aria-label="搜索已同步广告系列" placeholder="搜索广告系列" value={query} onChange={event => changeQuery(event.target.value)} /></label></div>
        {filtered.length ? <div className="pw-list pw-ads-list">{filtered.map(row => <Row key={row.item.id} row={row} onSelect={onSelect} />)}</div> : <div className="pw-ads-empty"><h3>{query.trim() ? '没有找到匹配的广告系列' : '暂无广告检查记录'}</h3><p>{query.trim() ? '搜索范围是当前已同步记录。' : source?.status === 'connected' ? '同步后查看真实投放状态与指标。' : '连接广告账户后显示真实数据。'}</p>{query.trim() && <button type="button" className="pw-text-button" onClick={() => changeQuery('')}>清除搜索</button>}</div>}
      </section>
    </>}
  </div>;
}

function MetricGroup({ health, period }: { health: PrivateAdsHealth; period: 'yesterday' | 'last_7_days' }) {
  const metric = privateAdsMetric(health.metrics?.[period]);
  return <section className="pw-ads-detail-metrics"><h3>{period === 'yesterday' ? '昨日' : '近7日'}<small>{privateAdsPeriod(health.periods?.[period])}</small></h3><dl><div><dt>曝光</dt><dd>{privateAdsNumber(metric?.impressions)}</dd></div><div><dt>点击</dt><dd>{privateAdsNumber(metric?.clicks)}</dd></div><div><dt>费用 · {health.currency}</dt><dd>{privateAdsMoney(metric?.cost_micros, health.currency)}</dd></div><div><dt>转化</dt><dd>{privateAdsConversions(health, metric)}</dd></div></dl></section>;
}
function changeLabel(value: unknown): string { return typeof value === 'number' && Number.isFinite(value) ? `${value > 0 ? '+' : ''}${value.toFixed(1)}%` : '待确认'; }

export function PrivateAdsDetail({ item, source, now }: { item: PrivateItem; source?: PrivateSource; now: number }) {
  const observation = privateAdsObservation(item, source, now);
  const health = observation.health;
  const url = verifiedPrivateSourceUrl('google_ads', item.source_url);
  return <div className="pw-detail-body pw-ads-detail"><div className="pw-ads-detail-meta"><Badge bucket={observation.bucket} /><span>检查时间（本机） {privateAdsTime(health?.observed_at)}</span></div><section className="pw-ads-detail-decision"><h3>{observation.reason}</h3>{privateAdsReasons(health).length > 0 && <p className="pw-ads-actual-reasons">{privateAdsReasons(health).join(' · ')}</p>}<dl><div><dt>影响</dt><dd>{observation.impact}</dd></div><div><dt>下一步</dt><dd>{observation.nextAction}</dd></div></dl></section>
    {health && <><div className="pw-ads-detail-periods"><MetricGroup health={health} period="yesterday" /><MetricGroup health={health} period="last_7_days" /></div><section className="pw-ads-detail-assessment"><h3>效果判断</h3><dl><div><dt>近7日实际 CPA</dt><dd>{privateAdsActualCpa(health)}</dd></div></dl><p>{health.target?.assessment || '当前依据不足，暂不评价效果。'}</p>{health.target?.cpa_micros != null && <dl><div><dt>当前目标 CPA</dt><dd>{privateAdsMoney(health.target.cpa_micros, health.currency)}</dd></div></dl>}{health.tracking?.state !== 'configured' && <p>转化追踪{health.tracking?.state === 'unconfigured' ? '未配置' : '待确认'}，不以零转化判断效果差。</p>}</section><details className="pw-ads-detail-origin"><summary>对比与检查依据<ChevronRight aria-hidden="true" /></summary><dl><div><dt>平台状态</dt><dd>{privateAdsStatus(health.current?.status)}</dd></div><div><dt>点击变化</dt><dd>{changeLabel(health.comparison?.clicks_change_pct)}</dd></div><div><dt>费用变化</dt><dd>{changeLabel(health.comparison?.cost_change_pct)}</dd></div><div><dt>转化变化</dt><dd>{health.tracking?.state === 'configured' ? changeLabel(health.comparison?.conversions_change_pct) : '待确认'}</dd></div></dl><p>近7日与前7日对比；{health.comparison?.note || '变化只供复核，不代表效果结论。'}</p>{health.tracking?.note && <p>{health.tracking.note}</p>}{health.account_timezone && <p>指标日期按广告账户时区：{health.account_timezone}</p>}<p>正常投放仅指已查项未见异常，不代表投放效果优秀。</p>{Array.isArray(health.limitations) && health.limitations.filter(value => typeof value === 'string').slice(0, 10).map((value, index) => <p key={index}>{value}</p>)}</details></>}
    {url && <a className="pw-button pw-button-primary pw-source-link" href={url} target="_blank" rel="noopener noreferrer">在 Google Ads 核实<ArrowUpRight aria-hidden="true" /></a>}<p className="pw-detail-footnote">这里提供只读检查与建议。</p>
  </div>;
}
