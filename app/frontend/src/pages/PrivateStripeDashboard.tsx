import { ArrowUpRight, ChevronDown, ChevronRight, LoaderCircle, RefreshCw, Search } from 'lucide-react';
import {
  PRIVATE_STRIPE_CATEGORY_NAMES, PRIVATE_STRIPE_FILTER_NAMES, PRIVATE_STRIPE_PERIOD_NAMES, PRIVATE_STRIPE_TAB_NAMES,
  createPrivateStripeSelection, privateStripeAmountsComplete, privateStripeClassificationsComplete, privateStripeReportComparison,
  privateStripeReportCurrencies, privateStripeReportCurrencyCode, privateStripeReportDate, privateStripeReportForSelection,
  privateStripeReportMinor, privateStripeReportMoney, privateStripeReportMetricMoney, privateStripeReportRecords, privateStripeReportSourceUrl,
  privateStripeReportStatus, privateStripeReportSubscriptions, privateStripeReportText, privateStripeReportTime, privateStripeSelectedCurrency,
  type PrivateStripeDashboardProps, type PrivateStripeDashboardTab, type PrivateStripePeriodPreset, type PrivateStripeReport,
  type PrivateStripeReportCurrency, type PrivateStripeReportRecord, type PrivateStripeReportSubscription, type PrivateStripeSelection,
} from '@/lib/private-stripe-report';
import './private-stripe-dashboard.css';

export type { PrivateStripeDashboardProps } from '@/lib/private-stripe-report';
const TABS: PrivateStripeDashboardTab[] = ['overview', 'subscriptions', 'records', 'funds'];
const PRESETS: PrivateStripePeriodPreset[] = ['month', 'quarter', 'year', 'custom'];
const KIND_NAMES: Record<PrivateStripeReportRecord['kind'], string> = { payment: '收款', refund: '退款', dispute: '争议', payout: '提现', adjustment: '其他资金变动' };
const DETAIL_NAMES: Record<string, string> = {
  provider_id: 'Stripe 记录', charge_id: '付款参考', payment_intent_id: '付款参考', invoice_id: '账单参考', subscription_id: '订阅参考',
  description: '来源说明', payment_method: '付款方式', payment_state: '收款状态', amount_captured_minor: '已收款', amount_refunded_minor: '已退款',
  amount_authorized_minor: '已授权', captured_minor: '已收款', refunded_minor: '已退款', fee_minor: '手续费', net_minor: '来源净额',
  failure_message: '失败原因', failure_code: '来源失败代码', due_at: '回应截止', reason: '来源原因', balance_transaction_id: '资金流水参考',
  accounting_effect: '账目关系', funds_movement: '资金流向', provider_status: 'Stripe 原始状态', arrival_date: '预计到达日', reporting_category: '来源资金分类',
  统计依据: '统计依据', 分类依据: '分类依据', 手续费: '手续费', 资金净变动: '资金净变动', 来源编号: '来源编号', 流水编号: '流水编号', 原支付币种: '原支付币种', 收款核对: '收款核对', 预计到账: '预计到账', 资金性质: '资金性质',
};
function SourceLink({ url, label = '在 Stripe 核对' }: { url: string | null | undefined; label?: string }) {
  const safe = privateStripeReportSourceUrl(url);
  return safe ? <a className="ps-text-button" href={safe} target="_blank" rel="noopener noreferrer">{label}<ArrowUpRight aria-hidden="true" /></a> : null;
}
function QuietEmpty({ title, note }: { title: string; note?: string }) {
  return <div className="ps-empty"><h3>{title}</h3>{note && <p>{note}</p>}</div>;
}
function SearchField({ selection, change, label }: { selection: PrivateStripeSelection; change: (patch: Partial<PrivateStripeSelection>) => void; label: string }) {
  return <label className="ps-search"><Search aria-hidden="true" /><input aria-label={label} placeholder={label} value={selection.search} onChange={event => change({ search: event.target.value, expanded_record_id: null, expanded_subscription_id: null })} /></label>;
}
function RecordDetail({ record, timezone }: { record: PrivateStripeReportRecord; timezone: string }) {
  const fields = record.details && typeof record.details === 'object' ? Object.entries(record.details).filter(([key, value]) => key in DETAIL_NAMES && (value === null || ['string', 'number'].includes(typeof value))).slice(0, 12) : [];
  return <div className="ps-inline-detail" id={`stripe-record-${record.id}`}><dl>
    <div><dt>Stripe 状态</dt><dd>{privateStripeReportStatus(record.status, record.kind)}</dd></div>
    <div><dt>客户</dt><dd>{privateStripeReportText(record.customer_label, 180) || '客户待确认'}</dd></div>
    <div><dt>记录时间</dt><dd>{privateStripeReportTime(record.occurred_at, timezone)} · {timezone}</dd></div>
    {record.category && <div><dt>收款分类</dt><dd>{PRIVATE_STRIPE_CATEGORY_NAMES[record.category] || '待分类收款'}</dd></div>}
    {record.subscription_id && <div><dt>关联订阅</dt><dd>{privateStripeReportText(record.subscription_id, 200)}</dd></div>}
    {record.invoice_id && <div><dt>关联账单</dt><dd>{privateStripeReportText(record.invoice_id, 200)}</dd></div>}
    {fields.map(([key, value]) => <div key={key}><dt>{DETAIL_NAMES[key]}</dt><dd>{key.endsWith('_minor') ? privateStripeReportMoney(value, record.currency) : key === 'accounting_effect' && value === 'none' ? '独立个人记录' : privateStripeReportText(typeof value === 'number' ? String(value) : value, 400) || '待确认'}</dd></div>)}
  </dl>{record.kind === 'payout' && <p>提现是 Stripe 向银行的资金划转，不计入收入。实际到账请核对银行流水。</p>}{record.kind === 'adjustment' && <p>来源资金调整单独保留，不归为订阅或单次收款。</p>}{record.kind === 'dispute' && <p>争议金额单独列示，处理结果以 Stripe 记录为准。</p>}<SourceLink url={record.source_url} /></div>;
}
function Records({ rows, selection, change, timezone }: { rows: PrivateStripeReportRecord[]; selection: PrivateStripeSelection; change: (patch: Partial<PrivateStripeSelection>) => void; timezone: string }) {
  return <div className="ps-records">{rows.map(record => {
    const expanded = selection.expanded_record_id === record.id;
    return <article key={record.id} className={`ps-record${expanded ? ' is-expanded' : ''}`}><button className="ps-record-button" type="button" aria-expanded={expanded} aria-controls={`stripe-record-${record.id}`} onClick={() => change({ expanded_record_id: expanded ? null : record.id })}>
      <span className="ps-record-copy"><strong>{privateStripeReportText(record.title, 220) || privateStripeReportText(record.customer_label, 180) || KIND_NAMES[record.kind]}</strong><span>{record.kind === 'payment' && record.category ? PRIVATE_STRIPE_CATEGORY_NAMES[record.category] || '待分类收款' : KIND_NAMES[record.kind]}<i aria-hidden="true">·</i>{privateStripeReportStatus(record.status, record.kind)}</span></span>
      <span className="ps-record-value"><strong>{privateStripeReportMoney(record.amount_minor, record.currency)}</strong><time dateTime={record.occurred_at || undefined}>{privateStripeReportTime(record.occurred_at, timezone, true)}</time></span><ChevronDown aria-hidden="true" />
    </button>{expanded && <RecordDetail record={record} timezone={timezone} />}</article>;
  })}</div>;
}
function Trend({ row, partial }: { row: PrivateStripeReportCurrency; partial: boolean }) {
  const points = (Array.isArray(row.trend) ? row.trend : []).filter(point => point && privateStripeReportDate(point.date));
  const verified = points.length > 0 && points.every(point => [point.subscription_minor, point.one_time_minor, point.unclassified_minor].every(value => privateStripeReportMinor(value) && value >= 0));
  // Summing the three server-provided segments determines bar geometry only.
  // The dashboard never derives financial totals or comparisons from records.
  const maximum = verified ? Math.max(...points.map(point => point.subscription_minor! + point.one_time_minor! + point.unclassified_minor!)) : 0;
  const width = 720, chartHeight = 140, gap = points.length > 20 ? 3 : 7, slot = width / Math.max(1, points.length), barWidth = Math.max(1, slot - gap);
  const hasUnclassified = points.some(point => privateStripeReportMinor(point.unclassified_minor) && point.unclassified_minor > 0);
  return <section className="ps-panel ps-trend"><div className="ps-section-heading"><h2>收款趋势</h2><span>{partial ? '已读取记录' : '已收款'} · {row.currency}</span></div>
    {partial && maximum === 0 ? <QuietEmpty title="趋势数据待确认" /> : !partial && row.gross_minor === 0 && points.length === 0 ? <QuietEmpty title="期间未有已收款" /> : verified ? <><div className="ps-chart" role="img" aria-label={`${row.currency} 收款趋势${partial ? '，数据范围不完整' : ''}${maximum === 0 ? '，期间未有已收款' : ''}`}><svg viewBox="0 0 720 176" preserveAspectRatio="none" aria-hidden="true">
      {[0, 1, 2].map(index => <line key={index} x1="0" x2="720" y1={12 + index * 70} y2={12 + index * 70} className="ps-chart-grid" />)}
      {points.map((point, index) => {
        let bottom = 152;
        return <g key={point.date}>{(['subscription_minor', 'one_time_minor', 'unclassified_minor'] as const).map((key, segment) => { const height = maximum > 0 ? point[key]! / maximum * chartHeight : 0; bottom -= height; return <rect key={key} x={index * slot + gap / 2} y={bottom} width={barWidth} height={height} rx="2" className={`ps-chart-segment ps-chart-segment-${segment}`} />; })}</g>;
      })}
    </svg>{maximum === 0 && <span className="ps-chart-zero">期间未有已收款</span>}</div><div className="ps-chart-dates"><span>{points[0].date.slice(5).replace('-', '/')}</span>{points.length > 2 && <span>{points[Math.floor(points.length / 2)].date.slice(5).replace('-', '/')}</span>}<span>{points[points.length - 1].date.slice(5).replace('-', '/')}</span></div><div className="ps-chart-legend"><span><i className="ps-chart-key ps-chart-key-0" />订阅</span><span><i className="ps-chart-key ps-chart-key-1" />单次</span>{hasUnclassified && <span><i className="ps-chart-key ps-chart-key-2" />待分类</span>}</div></> : <QuietEmpty title="趋势数据待确认" note="数据准备完成后显示所选期间的收款变化。" />}
  </section>;
}
function Overview({ report, row, selection, change }: { report: PrivateStripeReport; row: PrivateStripeReportCurrency | null; selection: PrivateStripeSelection; change: (patch: Partial<PrivateStripeSelection>) => void }) {
  const completeAmounts = privateStripeAmountsComplete(report), completeClassifications = privateStripeClassificationsComplete(report);
  const recent = privateStripeReportRecords(report, { ...selection, filter: 'all', search: '' }).slice(0, 5);
  const attention = (Array.isArray(report.attention) ? report.attention : []).filter(item => item && privateStripeReportText(item.title, 220)).slice(0, 3);
  const narrative = !completeAmounts && row?.gross_minor === 0 ? [] : (Array.isArray(row?.summary) ? row.summary : []).filter(value => privateStripeReportText(value)).slice(0, 3);
  return <div className="ps-overview"><section className="ps-income"><div className="ps-income-title"><div><span>{report.period.label || PRIVATE_STRIPE_PERIOD_NAMES[selection.preset]} · {completeAmounts ? '已收款' : '已读取收款'}</span><h2>成功收款</h2></div>{row && <span className="ps-currency-tag">{row.currency}</span>}</div><strong className="ps-income-amount">{row ? privateStripeReportMetricMoney(row.gross_minor, row.currency, completeAmounts) : '待确认'}</strong>
    {row && <p className="ps-comparison">{privateStripeReportComparison(report, row)}</p>}
    {row && <><dl className="ps-income-split"><div><dt>{completeClassifications ? '订阅相关收款' : '已识别订阅相关收款'}</dt><dd>{privateStripeReportMetricMoney(row.subscription_minor, row.currency, completeAmounts && completeClassifications)}</dd></div><div><dt>{completeClassifications ? '单次收款' : '已识别单次收款'}</dt><dd>{privateStripeReportMetricMoney(row.one_time_minor, row.currency, completeAmounts && completeClassifications)}</dd></div>{(!completeClassifications || row.unclassified_minor !== 0) && <div><dt>待分类收款</dt><dd>{privateStripeReportMetricMoney(row.unclassified_minor, row.currency, completeAmounts && completeClassifications)}</dd></div>}</dl>
      <div className="ps-income-adjustments"><h3>退款与费用</h3><dl><div><dt>成功退款</dt><dd>{privateStripeReportMetricMoney(row.refunds_minor, row.currency, completeAmounts)}</dd></div><div><dt>Stripe 费用</dt><dd>{privateStripeReportMetricMoney(row.fees_minor, row.currency, completeAmounts)}</dd></div><div><dt>收款扣退款</dt><dd>{privateStripeReportMetricMoney(row.net_receipts_minor, row.currency, completeAmounts)}<small>未扣费用</small></dd></div></dl></div></>}
    <div className="ps-income-footer"><details className="ps-income-evidence"><summary>收款解读<ChevronRight aria-hidden="true" /></summary><div className="ps-narrative" aria-label="所选期间中文收款解读">{narrative.length ? narrative.map((line, index) => <p key={index}>{privateStripeReportText(line, 600)}</p>) : <p>所选期间的收款解读待确认。</p>}</div><p>收款扣退款未扣 Stripe 费用；提现不计入收款。</p></details><button type="button" className="ps-text-button" onClick={() => change({ tab: 'funds', search: '' })}>查看当前余额<ChevronRight aria-hidden="true" /></button></div>
  </section>
    {(row || attention.length > 0) && <div className={`ps-insight-grid${row && attention.length ? ' has-attention' : ''}`}>{row && <Trend row={row} partial={!completeAmounts} />}{attention.length > 0 && <section className="ps-panel ps-attention"><div className="ps-section-heading"><h2>当前需处理</h2><span>{attention.length} 项</span></div>{attention.map(item => <article key={item.id}><strong>{privateStripeReportText(item.title, 220)}</strong><p>{privateStripeReportText(item.reason, 500) || '打开来源核对详情。'}</p><SourceLink url={item.source_url} label="核对来源" /></article>)}</section>}</div>}
    <section className="ps-recent"><div className="ps-section-heading"><h2>最近流水</h2><button type="button" className="ps-text-button" onClick={() => change({ tab: 'records', filter: 'all', search: '' })}>查看全部<ChevronRight aria-hidden="true" /></button></div>{recent.length ? <Records rows={recent} selection={selection} change={change} timezone={report.period.timezone} /> : <QuietEmpty title={completeAmounts && report.coverage?.disputes_complete === true ? '所选期间暂无收款、退款或争议记录' : '所选期间的流水待确认'} />}</section>
  </div>;
}
function SubscriptionRow({ subscription, selection, change, timezone }: { subscription: PrivateStripeReportSubscription; selection: PrivateStripeSelection; change: (patch: Partial<PrivateStripeSelection>) => void; timezone: string }) {
  const expanded = selection.expanded_subscription_id === subscription.id;
  const plans = (Array.isArray(subscription.plans) ? subscription.plans : []).filter(plan => plan && privateStripeReportText(plan.label, 200)).slice(0, 10);
  const planInterval = (plan: typeof plans[number]) => { const interval = ({ day: '天', week: '周', month: '月', year: '年' } as Record<string, string>)[plan.interval]; return interval && Number.isSafeInteger(plan.interval_count) && plan.interval_count > 0 ? `每${plan.interval_count === 1 ? '' : plan.interval_count}${interval}` : '周期待确认'; };
  return <article className={`ps-record${expanded ? ' is-expanded' : ''}`}><button type="button" className="ps-record-button" aria-expanded={expanded} aria-controls={`stripe-subscription-${subscription.id}`} onClick={() => change({ expanded_subscription_id: expanded ? null : subscription.id })}>
    <span className="ps-record-copy"><strong>{privateStripeReportText(subscription.customer_label, 200) || '客户待确认'}</strong><span>{privateStripeReportStatus(subscription.status, 'subscription')}{subscription.cancel_at_period_end === true && <><i aria-hidden="true">·</i>周期结束后取消</>}</span></span><span className="ps-record-value">{privateStripeReportMinor(subscription.amount_minor) ? <><strong>{privateStripeReportMoney(subscription.amount_minor, subscription.currency)}</strong><span>来源订阅金额</span></> : subscription.period_end ? <><strong>{privateStripeReportTime(subscription.period_end, timezone, true)}</strong><span>周期截止</span></> : <><strong>待确认</strong><span>周期截止</span></>}</span><ChevronDown aria-hidden="true" />
  </button>{expanded && <div className="ps-inline-detail" id={`stripe-subscription-${subscription.id}`}><dl><div><dt>订阅参考</dt><dd>{privateStripeReportText(subscription.id, 200)}</dd></div><div><dt>来源状态</dt><dd>{privateStripeReportStatus(subscription.status, 'subscription')}</dd></div>{subscription.period_end && <div><dt>周期截止</dt><dd>{privateStripeReportTime(subscription.period_end, timezone)} · {timezone}</dd></div>}<div><dt>下次付款</dt><dd>{subscription.next_payment_at ? `${privateStripeReportTime(subscription.next_payment_at, timezone)} · ${timezone}` : '待确认'}</dd></div>{plans.map((plan, index) => <div key={index}><dt>标准价格</dt><dd>{privateStripeReportText(plan.label, 200)} · {privateStripeReportMoney(plan.amount_minor, plan.currency)} / {planInterval(plan)}{Number.isSafeInteger(plan.quantity) && plan.quantity > 1 ? ` · 数量 ${plan.quantity}` : ''}</dd></div>)}</dl><p>{plans.length ? '标准价格不代表下次账单金额；折扣、税费与用量以 Stripe 账单为准。' : '来源订阅金额与下次付款供核对，实际收款以期间已收款记录为准。'}</p>{plans.length > 0 && <p>实际收款以期间已收款记录为准。</p>}<SourceLink url={subscription.source_url} /></div>}</article>;
}
function Funds({ report, selection, change }: { report: PrivateStripeReport; selection: PrivateStripeSelection; change: (patch: Partial<PrivateStripeSelection>) => void }) {
  const currency = privateStripeSelectedCurrency(report, selection)?.currency || selection.currency;
  const balances = (Array.isArray(report.balances) ? report.balances : []).filter(row => row && privateStripeReportCurrencyCode(row.currency) && row.currency === currency);
  const records = privateStripeReportRecords(report, { ...selection, filter: 'all' }, true);
  return <div className="ps-funds"><section><div className="ps-section-heading"><h2>当前 Stripe 余额</h2><span>当前快照 · 独立于统计期间</span></div>{balances.length ? <div className="ps-balance-grid">{balances.map((balance, index) => <article className="ps-panel ps-balance" key={`${balance.currency}-${index}`}><div className="ps-section-heading"><strong className="ps-currency-tag">{balance.currency}</strong><time dateTime={balance.observed_at || undefined}>读取 {privateStripeReportTime(balance.observed_at, report.period.timezone)}</time></div><dl><div><dt>可用余额</dt><dd>{privateStripeReportMoney(balance.available_minor, balance.currency)}</dd></div><div><dt>待结算余额</dt><dd>{privateStripeReportMoney(balance.pending_minor, balance.currency)}</dd></div></dl></article>)}</div> : <QuietEmpty title="当前余额待确认" note="账户余额读取完成后分别显示可用与待结算资金。" />}</section>
    <section><div className="ps-section-heading"><h2>提现与资金变动</h2><span>{report.period.label} · 不计入收款</span></div><SearchField selection={selection} change={change} label="搜索资金记录" />{records.length ? <Records rows={records} selection={selection} change={change} timezone={report.period.timezone} /> : <QuietEmpty title={selection.search.trim() ? '没有匹配的资金记录' : report.coverage?.funds_complete === true ? '所选期间暂无提现或其他资金变动' : '所选期间的资金记录待确认'} note={selection.search.trim() ? '搜索范围为当前已读取的资金记录。' : undefined} />}</section>
  </div>;
}
export default function PrivateStripeDashboard({ report: incomingReport, selection, loading, error = '', busy = false, connectionLabel = '', connected = false, canManageConnection = true, onChangeSelection, onRetry, onManageConnection }: PrivateStripeDashboardProps) {
  const report = privateStripeReportForSelection(incomingReport, selection);
  const row = privateStripeSelectedCurrency(report, selection);
  const currencies = [...new Set([...privateStripeReportCurrencies(report).map(value => value.currency), ...(Array.isArray(report?.balances) ? report.balances : []).map(value => value?.currency), ...(Array.isArray(report?.subscriptions) ? report.subscriptions : []).map(value => value?.currency), selection.currency].filter(privateStripeReportCurrencyCode))];
  const activeCurrency = selection.currency || row?.currency || currencies[0] || '';
  const change = (patch: Partial<PrivateStripeSelection>) => onChangeSelection({ ...selection, ...patch });
  const changePreset = (preset: PrivateStripePeriodPreset) => { const defaults = createPrivateStripeSelection(); change({ preset, ...(preset === 'custom' ? { start_date: selection.start_date || report?.period.start_date || defaults.start_date, end_date: selection.end_date || report?.period.end_date || defaults.end_date } : {}), expanded_record_id: null, expanded_subscription_id: null }); };
  const customDatesValid = selection.preset !== 'custom' || privateStripeReportDate(selection.start_date) && privateStripeReportDate(selection.end_date) && selection.start_date <= selection.end_date;
  const reasons = (Array.isArray(report?.coverage?.reasons) ? report.coverage.reasons : []).filter(value => privateStripeReportText(value)).slice(0, 8);
  const partial = report && (report.state === 'partial' || report.coverage?.complete !== true);
  const subscriptions = privateStripeReportSubscriptions(report, { ...selection, currency: activeCurrency });
  const records = privateStripeReportRecords(report, { ...selection, currency: activeCurrency });
  const recordCoverageComplete = privateStripeAmountsComplete(report) && (selection.filter === 'dispute' || selection.filter === 'all' ? report?.coverage?.disputes_complete === true : ['subscription', 'one_time', 'unclassified'].includes(selection.filter) ? privateStripeClassificationsComplete(report) : true);
  const secondaryNotice = !report ? '' : selection.tab === 'subscriptions' && report.coverage?.subscriptions_complete !== true ? '订阅读取尚未完整，当前仅显示已读取记录。' : selection.tab === 'funds' && report.coverage?.funds_complete !== true ? '资金记录读取尚未完整，当前仅显示已读取记录。' : selection.tab === 'records' && ['all', 'dispute'].includes(selection.filter) && report.coverage?.disputes_complete !== true ? '争议读取尚未完整，当前仅显示已读取记录。' : selection.tab === 'overview' && report.coverage?.attention_complete !== true ? '当前处理项尚未读取完整，请核对 Stripe 来源。' : '';
  const accountReference = privateStripeReportText(connectionLabel, 240) || privateStripeReportText(report?.account_label, 120);
  const accountName = [privateStripeReportText(report?.account_label, 120), privateStripeReportText(connectionLabel, 240)].map(label => label.replace(/\s*·\s*acct_[A-Za-z0-9]+$/, '').trim()).find(label => label && !/^acct_[A-Za-z0-9]+$/.test(label)) || 'Stripe 收款账户';
  return <div className="ps-dashboard"><header className="ps-account-line"><div><span className="ps-account-name">{accountName}</span><span>{report?.generated_at ? `只读 · 读取 ${privateStripeReportTime(report.generated_at, report.period.timezone)}` : connected ? '已连接 · 只读' : '接入状态待确认'}</span></div><button className="ps-text-button" type="button" disabled={busy || !canManageConnection} onClick={onManageConnection}>{connected ? '管理接入' : '连接 Stripe'}<ChevronRight aria-hidden="true" /></button></header>
    {report?.mode === 'test' && <p className="ps-notice ps-test" role="status">测试模式 · 以下为 Stripe 测试数据</p>}
    <div className="ps-tabs" role="tablist" aria-label="Stripe 财务视图">{TABS.map(tab => <button type="button" role="tab" key={tab} aria-selected={selection.tab === tab} aria-controls="stripe-dashboard-panel" id={`stripe-tab-${tab}`} onClick={() => change({ tab })}>{PRIVATE_STRIPE_TAB_NAMES[tab]}</button>)}</div>
    <div className="ps-period-toolbar"><label className="ps-period-selector"><span>统计期间</span><select aria-label="收款统计期间" value={selection.preset} onChange={event => changePreset(event.target.value as PrivateStripePeriodPreset)}>{PRESETS.map(preset => <option key={preset} value={preset}>{PRIVATE_STRIPE_PERIOD_NAMES[preset]}</option>)}</select></label><div className="ps-period-actions">{currencies.length > 0 && <label className="ps-currency"><span className="ps-visually-hidden">分别查看币种</span><select aria-label="分别查看币种" value={activeCurrency} onChange={event => change({ currency: event.target.value, expanded_record_id: null, expanded_subscription_id: null })}>{currencies.map(currency => <option key={currency} value={currency}>{currency}</option>)}</select></label>}<button className="ps-icon-button" type="button" aria-label="重新读取所选期间" title="重新读取" aria-busy={loading || undefined} disabled={busy || loading || !customDatesValid} onClick={onRetry}><RefreshCw aria-hidden="true" /></button></div></div>
    {selection.preset === 'custom' && <div className="ps-custom-period"><label><span>开始日期</span><input type="date" aria-label="收款开始日期" value={selection.start_date} max={selection.end_date || undefined} onChange={event => change({ start_date: event.target.value, expanded_record_id: null })} /></label><span aria-hidden="true">—</span><label><span>结束日期</span><input type="date" aria-label="收款结束日期" value={selection.end_date} min={selection.start_date || undefined} onChange={event => change({ end_date: event.target.value, expanded_record_id: null })} /></label></div>}
    {report && !loading && !error && <div className="ps-period-caption"><span>{report.period.start_date} — {report.period.end_date}</span><span>按 {report.period.timezone || '待确认时区'}</span></div>}
    <div id="stripe-dashboard-panel" role="tabpanel" aria-labelledby={`stripe-tab-${selection.tab}`}>
      {!customDatesValid ? <QuietEmpty title="请选择有效的开始与结束日期" note="结束日期应在开始日期当天或之后。" /> : loading ? <div className="ps-load" role="status"><LoaderCircle aria-hidden="true" /><p>正在读取所选期间…</p></div> : error ? <div className="ps-load ps-load-error" role="alert"><h3>收款数据读取失败</h3><p>{privateStripeReportText(error, 500)}</p><button className="ps-button" type="button" disabled={busy} onClick={onRetry}>重新读取</button></div> : !report || report.state === 'unavailable' ? <div className="ps-load"><h3>所选期间数据待确认</h3><p>{reasons[0] || (connected ? '读取完成后显示收款、订阅和资金记录。' : '连接 Stripe 后查看真实收款记录。')}</p><button className="ps-button" type="button" disabled={busy} onClick={onRetry}>重新读取</button></div> : <>
        {partial && <div className="ps-notice" role="status"><strong>数据范围尚未完整</strong><span>仅显示已读取记录，完整期间结论待确认。</span></div>}
        {secondaryNotice && <p className="ps-view-notice" role="status">{secondaryNotice}</p>}
        {selection.tab === 'overview' && <Overview report={report} row={row} selection={{ ...selection, currency: activeCurrency }} change={change} />}
        {selection.tab === 'subscriptions' && <section className="ps-subscriptions"><div className="ps-section-heading"><h2>订阅</h2><span>当前状态 · 实际收款见总览</span></div><SearchField selection={selection} change={change} label="搜索订阅客户" />{subscriptions.length ? <div className="ps-records">{subscriptions.map(subscription => <SubscriptionRow key={subscription.id} subscription={subscription} selection={selection} change={change} timezone={report.period.timezone} />)}</div> : <QuietEmpty title={selection.search.trim() ? '没有匹配的订阅' : report.coverage?.subscriptions_complete === true ? '当前没有可查看的订阅' : '订阅数据待确认'} note={selection.search.trim() ? '搜索范围为当前已读取的订阅。' : undefined} />}</section>}
        {selection.tab === 'records' && <section className="ps-all-records"><div className="ps-record-toolbar"><label className="ps-record-filter"><span className="ps-visually-hidden">收款流水分类</span><select aria-label="收款流水分类" value={selection.filter} onChange={event => change({ filter: event.target.value as PrivateStripeSelection['filter'], expanded_record_id: null })}>{Object.entries(PRIVATE_STRIPE_FILTER_NAMES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><SearchField selection={selection} change={change} label="搜索客户或流水" /></div>{records.length ? <Records rows={records} selection={selection} change={change} timezone={report.period.timezone} /> : <QuietEmpty title={selection.search.trim() ? '没有匹配的流水' : recordCoverageComplete ? '所选期间暂无此类流水' : '所选期间的流水待确认'} note={selection.search.trim() ? '搜索范围为当前所选期间与币种。' : undefined} />}</section>}
        {selection.tab === 'funds' && <Funds report={report} selection={{ ...selection, currency: activeCurrency }} change={change} />}
        <details className="ps-coverage"><summary>来源依据与统计口径<ChevronRight aria-hidden="true" /></summary>{accountReference && <p>Stripe 账户参考：{accountReference}</p>}<p>已收款按期间实际捕获的付款统计，订阅根据付款与账单的关联依据分类。缺少关联依据的收款保留为待分类。订阅列表按当前状态显示，实际收款以期间流水为准。</p><p>成功退款按退款发生日期列示，收款扣退款未扣 Stripe 费用。Stripe 费用包含资金流水中的处理费用，以及独立的 Stripe 服务与汇兑费用；此处不计算经营利润。</p><p>余额按读取时点显示，与所选收款期间分开。提现不计入收入，银行实际到账需另行核对。提现与其他资金变动独立查看，各币种分别显示。此处为独立私人只读报表，不写入 CRM 财务。日期按 {report.period.timezone || '待确认时区'}；读取时间 {privateStripeReportTime(report.generated_at, report.period.timezone)}。</p>{reasons.map((reason, index) => <p key={index}>{privateStripeReportText(reason, 600)}</p>)}</details>
      </>}
    </div>
  </div>;
}
