import { useState } from 'react';
import {
  ArrowDownLeft, ArrowRight, ArrowUpRight, CalendarClock, CheckCircle2,
  ChevronDown, ChevronRight, Clock, CreditCard, HandCoins, Receipt,
  ScanLine, ShieldCheck, TrendingUp,
} from 'lucide-react';
import './finance-owner-overview.css';

type HealthItem = { key: string; label: string; count: number; help: string; tab: string };
type CustomerProfit = {
  customerId?: string | number; customerName: string; revenue: number;
  customerCostUsd: number; totalFee: number; profit: number;
  warningLevel: string; warningLabel: string;
};
type Props<T extends CustomerProfit> = {
  periodLabel: string;
  basisLabel: string;
  audited: boolean;
  currentMonth: string;
  monthClosed: boolean;
  summary: {
    profit: number; profitRate: number; revenue: number; cost: number; otherCost: number;
    deduction: number; stripeFee: number; commission: number; grossReceipts: number;
    refunds: number; netReceipts: number; adFunds: number; companyCostCny: number;
  };
  receivables: { count: number; amount: number };
  subscriptions: {
    pendingCount: number; pendingAmount: number; attentionCount: number;
    expiringCount: number; activeCount: number;
    d7: { count: number; amount: number }; d30: { count: number; amount: number };
  };
  healthItems: HealthItem[];
  healthIssueCount: number;
  profitWarningCount: number;
  profitWarningRate: number;
  customers: T[];
  formatMoney: (value: number) => string;
  formatRmb: (value: number) => string;
  onNavigate: (tab: string) => void;
  onPendingSubscriptions: () => void;
  onHealthIssue: (key: string, tab: string, count: number) => void;
  onCustomer: (row: T) => void;
  onCommissions: () => void;
};

export default function FinanceOwnerOverview<T extends CustomerProfit>({
  periodLabel, basisLabel, audited, currentMonth, monthClosed, summary,
  receivables, subscriptions, healthItems, healthIssueCount, profitWarningCount,
  profitWarningRate, customers, formatMoney: money, formatRmb,
  onNavigate, onPendingSubscriptions, onHealthIssue, onCustomer, onCommissions,
}: Props<T>) {
  const [showAllTasks, setShowAllTasks] = useState(false);
  const [healthExpanded, setHealthExpanded] = useState(false);
  const issues = healthItems.filter(item => item.count > 0);
  const tasks = [
    { key: 'pending', label: '确认订阅扣款', count: subscriptions.pendingCount, unit: '笔',
      description: `待确认金额 ${money(subscriptions.pendingAmount)}`, icon: CreditCard,
      tone: 'blue', action: onPendingSubscriptions },
    { key: 'receivables', label: '跟进应收欠款', count: receivables.count, unit: '笔',
      description: `应收未收 ${money(receivables.amount)}`, icon: HandCoins,
      tone: 'amber', action: () => onNavigate('receivables') },
    { key: 'renewal', label: '7 天内续费风险', count: subscriptions.d7.count, unit: '个',
      description: `涉及金额 ${money(subscriptions.d7.amount)}`, icon: Clock,
      tone: 'amber', action: () => onNavigate('subscriptions') },
    { key: 'health', label: '数据待核对', count: healthIssueCount, unit: '项',
      description: issues.length ? issues.map(item => `${item.label} ${item.count}`).join(' · ') : '关键财务数据口径正常',
      icon: ScanLine, tone: 'neutral', action: () => setHealthExpanded(value => !value) },
    { key: 'profit', label: '客户利润预警', count: profitWarningCount, unit: '个',
      description: `亏损或利润率低于 ${(profitWarningRate * 100).toFixed(0)}% 的客户`, icon: ShieldCheck,
      tone: 'amber', action: () => onNavigate('customer_profit') },
  ];
  const pendingTasks = tasks.filter(task => task.count > 0);
  const visibleTasks = showAllTasks ? tasks : pendingTasks;
  // A composition bar is meaningful only when these independently computed
  // accounting values reconcile. Never force an accounting adjustment into a chart.
  const canShowComposition = summary.netReceipts > 0 && summary.revenue >= 0 && summary.adFunds >= 0
    && Math.abs(summary.netReceipts - summary.revenue - summary.adFunds) < 0.02;

  return (
    <div className="finance-owner-overview" data-testid="finance-owner-overview">
      <div className="fo-context">
        <div><h3>{periodLabel}经营</h3><span className="fo-divider" /><span>USD</span><span className={audited ? 'fo-basis' : 'fo-basis fo-basis-warning'} role="status">{basisLabel}</span></div>
        <button type="button" className="fo-close-link" onClick={() => onNavigate('monthly_detail')}>
          <span className={monthClosed ? 'fo-status is-closed' : 'fo-status'}>本月关账 {currentMonth} · {monthClosed ? '已关账' : '未关账'}</span><ChevronRight aria-hidden="true" />
        </button>
      </div>

      <section className="fo-metrics" aria-label="经营关键指标">
        <article className="fo-metric fo-metric-profit">
          <div className="fo-metric-label"><span>{periodLabel}经营利润</span><TrendingUp aria-hidden="true" /></div>
          <p className={`fo-metric-value ${summary.profit < 0 ? 'fo-loss-on-dark' : ''}`}>{money(summary.profit)}</p>
          <div className="fo-metric-foot"><span className={`fo-margin ${summary.profit < 0 ? 'is-loss' : ''}`}>{(summary.profitRate * 100).toFixed(1)}%</span>经营利润率</div>
        </article>
        <article className="fo-metric">
          <div className="fo-metric-label"><span>{periodLabel}服务收入</span><ArrowDownLeft aria-hidden="true" /></div>
          <p className="fo-metric-value">{money(summary.revenue)}</p>
          <p className="fo-metric-foot">投流充值作为客户资金单独核算</p>
        </article>
        <article className="fo-metric">
          <div className="fo-metric-label"><span>审计总成本</span><Receipt aria-hidden="true" /></div>
          <p className="fo-metric-value">{money(summary.cost)}</p>
          <p className="fo-metric-foot">其他成本 {money(summary.otherCost)}</p>
        </article>
        <article className="fo-metric">
          <div className="fo-metric-label"><span>扣点与 Stripe</span><CreditCard aria-hidden="true" /></div>
          <p className="fo-metric-value">{money(summary.deduction + summary.stripeFee)}</p>
          <p className="fo-metric-foot">扣点 {money(summary.deduction)} · 手续费 {money(summary.stripeFee)}{summary.stripeFee < 0 ? '（含返还）' : ''}</p>
        </article>
      </section>

      <div className="fo-main-grid">
        <section className="fo-panel" aria-labelledby="fo-cash-title">
          <div className="fo-panel-heading"><h3 id="fo-cash-title">现金与收入</h3><button type="button" className="fo-text-link" onClick={() => onNavigate('income')}>查看收入明细<ArrowUpRight aria-hidden="true" /></button></div>
          <div className="fo-cash-body">
            <div className="fo-cash-total"><div><p className="fo-caption">{periodLabel}净实收现金</p><p className="fo-cash-value">{money(summary.netReceipts)}</p></div><button type="button" className="fo-refund" onClick={() => onNavigate('refunds')}><span>退款</span><strong>{money(summary.refunds)}</strong></button></div>
            <p className="fo-caption fo-gross">总收款 {money(summary.grossReceipts)} · 按实际资金日期归属</p>
            {canShowComposition ? (
              <div className="fo-cash-bar" role="img" aria-label={`净实收现金中，服务收入 ${money(summary.revenue)}，投流充值 ${money(summary.adFunds)}`}>
                <span style={{ flexGrow: summary.revenue }} /><span style={{ flexGrow: summary.adFunds }} />
              </div>
            ) : <div className="fo-cash-rule" />}
            <div className="fo-cash-row"><span><i className="fo-dot" aria-hidden="true" />服务收入</span><strong>{money(summary.revenue)}</strong></div>
            <div className="fo-cash-row"><span><i className="fo-dot fo-dot-ad" aria-hidden="true" />投流充值<small>客户资金</small></span><strong>{money(summary.adFunds)}</strong></div>
            <div className="fo-cash-footer">
              <button type="button" onClick={() => onNavigate('receivables')}><span className="fo-caption">应收未收 · {receivables.count} 笔</span><strong className={receivables.amount > 0 ? 'fo-warning-value' : ''}>{money(receivables.amount)}</strong></button>
              <button type="button" onClick={onCommissions}><span className="fo-caption">渠道佣金</span><strong>{money(summary.commission)}</strong></button>
              {summary.companyCostCny !== 0 ? <button type="button" onClick={() => onNavigate('company_expense')}><span className="fo-caption">人民币运营支出 · 单独核算</span><strong>{formatRmb(summary.companyCostCny)}</strong></button> : null}
            </div>
          </div>
        </section>

        <section className="fo-panel" aria-labelledby="fo-tasks-title">
          <div className="fo-panel-heading"><h3 id="fo-tasks-title">待处理事项 <span className="fo-task-count" aria-live="polite">{visibleTasks.length} 类</span></h3><div className="fo-task-switch" role="group" aria-label="事项显示范围"><button type="button" aria-pressed={!showAllTasks} onClick={() => setShowAllTasks(false)}>待处理</button><button type="button" aria-pressed={showAllTasks} onClick={() => setShowAllTasks(true)}>全部</button></div></div>
          <div className="fo-task-list">
            {visibleTasks.map(task => (
              <div className="fo-task-group" key={task.key}>
                <button type="button" className="fo-task" onClick={task.action} aria-expanded={task.key === 'health' ? healthExpanded : undefined} aria-controls={task.key === 'health' ? 'fo-health-issues' : undefined}>
                  <span className={`fo-task-icon fo-tone-${task.count > 0 ? task.tone : 'neutral'}`}><task.icon aria-hidden="true" /></span>
                  <span className="fo-task-copy"><span className="fo-task-name">{task.label}<span className="fo-count">{task.count} {task.unit}</span></span><span className="fo-task-description">{task.description}</span></span>
                  {task.key === 'health' && healthExpanded ? <ChevronDown aria-hidden="true" /> : <ChevronRight aria-hidden="true" />}
                </button>
                {task.key === 'health' ? <div id="fo-health-issues" className="fo-health-issues" hidden={!healthExpanded}>
                  {issues.length ? issues.map(item => <button key={item.key} type="button" onClick={() => onHealthIssue(item.key, item.tab, item.count)}><span><strong>{item.label}</strong><span>{item.help}</span></span><b>{item.count}</b><ChevronRight aria-hidden="true" /></button>) : <p>暂无需要核对的数据问题。</p>}
                </div> : null}
              </div>
            ))}
            {visibleTasks.length === 0 ? <div className="fo-tasks-empty"><CheckCircle2 aria-hidden="true" /><p>当前没有待处理事项</p><span>可切换“全部”查看各项状态。</span></div> : null}
          </div>
          {!showAllTasks && (receivables.count === 0 || profitWarningCount === 0) ? <div className="fo-quiet-status"><CheckCircle2 aria-hidden="true" /><span>{[receivables.count === 0 ? '无应收欠款' : '', profitWarningCount === 0 ? '无客户利润预警' : ''].filter(Boolean).join(' · ')}</span></div> : null}
        </section>
      </div>

      <section className="fo-panel fo-renewal" aria-label="未来 30 天续费预测">
        <div className="fo-renewal-title"><span className="fo-renewal-icon"><CalendarClock aria-hidden="true" /></span><div><h3>未来 30 天续费预测</h3><p className="fo-caption">{subscriptions.d30.count} 个套餐 · 预计金额，尚未计入实收</p></div></div>
        <div><p className="fo-renewal-value">{money(subscriptions.d30.amount)}</p><p className="fo-caption">活跃订阅 {subscriptions.activeCount} · 需处理提醒 {subscriptions.attentionCount}</p><p className="fo-caption">待确认 {subscriptions.pendingCount} · 到期 {subscriptions.expiringCount}</p></div>
        <button type="button" className="fo-button" onClick={() => onNavigate('subscriptions')}>查看续费计划<ArrowRight aria-hidden="true" /></button>
      </section>

      <section className="fo-panel" aria-labelledby="fo-customers-title">
        <div className="fo-panel-heading fo-customer-heading"><div><h3 id="fo-customers-title">客户利润 <span className="fo-top-label">TOP 5</span></h3><p className="fo-caption">{periodLabel}客户表现 · 共 {customers.length} 个客户</p></div><button type="button" className="fo-text-link" onClick={() => onNavigate('customer_profit')}>客户利润分析<ArrowUpRight aria-hidden="true" /></button></div>
        {customers.length > 0 ? <div className="fo-table-wrap"><table><thead><tr><th scope="col">客户</th><th scope="col">收入</th><th scope="col">成本</th><th scope="col">利润</th><th scope="col"><span className="sr-only">操作</span></th></tr></thead><tbody>
          {customers.slice(0, 5).map((row, index) => <tr key={`${row.customerId || row.customerName}-${index}`}><td><button type="button" className="fo-customer-link" onClick={() => onCustomer(row)}><span className="fo-rank">{String(index + 1).padStart(2, '0')}</span><span>{row.customerName}{row.warningLevel !== 'healthy' ? <small className={row.warningLevel === 'loss' ? 'fo-loss-label' : 'fo-warning-label'}>{row.warningLabel}</small> : null}</span></button></td><td>{money(row.revenue)}</td><td className="fo-cost-value">{money(row.customerCostUsd + row.totalFee)}</td><td className={row.profit >= 0 ? 'fo-profit-value' : 'fo-negative-value'}>{money(row.profit)}</td><td><button type="button" className="fo-row-detail" aria-label={`查看 ${row.customerName} 利润明细`} onClick={() => onCustomer(row)}><ChevronRight aria-hidden="true" /></button></td></tr>)}
        </tbody></table></div> : <p className="fo-empty">当前账目时间内暂无客户利润数据</p>}
        <div className="fo-table-note">客户级分摊用于经营排查，与公司审计总利润口径不同。</div>
      </section>

      <details className="fo-accounting"><summary><ChevronRight aria-hidden="true" />财务计算口径</summary><div><p>收入按「收款日期」进入月份；服务覆盖期只影响续费和服务周期。</p><p>管理费按当月扣点率计算；投流充值属于客户资金，只有月结确认差价才计入收入。</p><p>Stripe 订阅按实收金额计算 2.9% + $0.30/笔；手动收款不算 Stripe 手续费。净手续费包含明确记录的手续费返还。</p><p>客户成本进入单客利润；运营支出进入老板总览利润，人民币支出单独统计不混算。</p></div></details>
    </div>
  );
}
