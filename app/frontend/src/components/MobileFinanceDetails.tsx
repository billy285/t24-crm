import { useEffect, useLayoutEffect, useMemo, useRef, type ReactNode } from 'react';
import { useSessionViewState } from '@/hooks/use-session-view-state';
import { useRole } from '@/lib/role-context';
import { BarChart, Bar, XAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts';
import { ArrowLeft, CalendarDays, ChevronDown, ChevronRight, Search } from 'lucide-react';
import { getFinanceNavigationItem } from '@/lib/finance-navigation';
import './mobile-finance-details.css';

export const mobileFinanceDetailTabs = ['monthly_detail', 'customer_profit', 'refunds', 'ad_funds', 'customer_expense', 'company_expense', 'charts'] as const;
export type MobileFinanceDetailTab = typeof mobileFinanceDetailTabs[number];
export const isMobileFinanceDetailTab = (tab: string): tab is MobileFinanceDetailTab => (
  (mobileFinanceDetailTabs as readonly string[]).includes(tab)
);
type DateMode = 'all' | 'today' | 'this_month' | 'last_month' | 'custom';
type Currency = 'USD' | 'CNY';

export interface MobileFinanceDateFilterProps {
  mode: DateMode;
  start: string;
  end: string;
  onModeChange: (mode: DateMode) => void;
  onMonthChange: (month: string) => void;
}

export function MobileFinanceDateFilter({ mode, start, end, onModeChange, onMonthChange }: MobileFinanceDateFilterProps) {
  const month = mode === 'custom' && start && end && start.slice(0, 7) === end.slice(0, 7) ? start.slice(0, 7) : '';
  return (
    <div className="mobile-finance-date-filter" aria-label="账目时间筛选">
      <div className="mfd-date-shortcuts">
        {([['this_month', '本月'], ['last_month', '上月'], ['all', '全部']] as const).map(([value, label]) => (
          <button key={value} type="button" aria-pressed={mode === value} onClick={() => onModeChange(value)}>{label}</button>
        ))}
      </div>
      <label className="mfd-month">
        <CalendarDays aria-hidden="true" /><span>{month || '选月份'}</span>
        <input aria-label="账目月份" type="month" value={month} onClick={event => {
          // Keep the native month control for mobile browsers and keyboard users.
          try { event.currentTarget.showPicker?.(); } catch { /* The native control remains available. */ }
        }} onChange={event => { if (event.target.value) onMonthChange(event.target.value); }} />
      </label>
    </div>
  );
}

export interface MobileFinanceRecordAction {
  kind: MobileFinanceDetailTab | 'ad_funds_unsettled';
  record: any;
}

interface MobileFinanceDetailsProps {
  tab: MobileFinanceDetailTab;
  dateFilter: MobileFinanceDateFilterProps;
  periodLabel: string;
  loading: boolean;
  error?: string | null;
  hasLoaded: boolean;
  lastUpdated?: Date | null;
  onRetry: () => void;
  calculationNote?: string;
  calculationWarning?: string;
  data: {
    monthlyRows: any[];
    monthlyTotals: any;
    customerProfitRows: any[];
    profitWarningRows: any[];
    refunds: any[];
    settlements: any[];
    unsettled: any[];
    customerExpenses: any[];
    companyExpenses: any[];
    customerExpenseTotalUsd: number;
    legacyAdFundExpenseCount: number;
    companyExpenseTotals: { USD: number; CNY: number };
    summaryFinance: any;
    monthlyTrend: any[];
    chartPeriodLabel: string;
    incomeByType: any[];
    productRevenue: any[];
    customerRevenue: any[];
    payMethods: any[];
    payModes: any[];
    chartCompanyExpenses: any[];
    chartCompanyExpenseTotals: { USD: number; CNY: number };
    customerMap: Record<string, any>;
    customerExpenseLabels: Record<string, string>;
    companyExpenseLabels: Record<string, string>;
  };
  formatMoney: (amount: number, currency: Currency) => string;
  customerExpenseCurrency: (record: any) => Currency;
  companyExpenseCurrency: (record: any) => Currency;
  actions?: ReactNode;
  renderRecordActions?: (context: MobileFinanceRecordAction) => ReactNode;
}

type Field = { label: string; value: string; wide?: boolean };
type RecordCard = MobileFinanceRecordAction & {
  id: string;
  section: string;
  title: string;
  subtitle: string;
  badge?: string;
  tone?: 'warning' | 'positive';
  primary: Field;
  secondary?: Field;
  fields: Field[];
};

const detailViewDefaults = { query: '', visibleLimit: 20, currency: 'all', category: 'all', status: 'all', chartView: 'trend', expandedIds: [] as string[], selectedMonthlyId: '', monthlyGroups: ['receipts'], monthlyListScroll: 0 };
const present = (value: unknown) => value !== undefined && value !== null && String(value).trim() !== '';
const text = (value: unknown, fallback = '未填写') => present(value) ? String(value) : fallback;
const shortDate = (value: unknown) => present(value) ? String(value).slice(0, 10) : '日期待补充';
const finiteAmount = (value: unknown): number | null => present(value) && Number.isFinite(Number(value)) ? Number(value) : null;
const currencyOf = (value: unknown, fallback: Currency = 'USD'): Currency => value === 'CNY' ? 'CNY' : value === 'USD' ? 'USD' : fallback;

export default function MobileFinanceDetails(props: MobileFinanceDetailsProps) {
  const { tab, dateFilter, periodLabel, loading, error, hasLoaded, lastUpdated, onRetry, calculationNote, calculationWarning, data, formatMoney, customerExpenseCurrency, companyExpenseCurrency, actions, renderRecordActions } = props;
  const { employee } = useRole();
  const [view, setView] = useSessionViewState(`t24:finance-detail-view:${employee?.id || 'guest'}:${tab}`, detailViewDefaults);
  const { query, visibleLimit, currency, category, status, chartView, expandedIds, selectedMonthlyId, monthlyGroups, monthlyListScroll } = view;
  const sectionRef = useRef<HTMLElement>(null);
  const monthlyBackRef = useRef<HTMLButtonElement>(null);
  const monthlyListTriggerRef = useRef<HTMLButtonElement | null>(null);
  const monthlyReturnIdRef = useRef('');
  const monthlyNavigationRef = useRef<'detail' | 'list' | null>(null);
  const setQuery = (value: string) => setView('query', value);
  const setVisibleLimit = (value: number | ((current: number) => number)) => setView('visibleLimit', value);
  const money = (value: unknown, currency: Currency = 'USD') => {
    const amount = finiteAmount(value);
    return amount === null ? '待补充' : formatMoney(amount, currency);
  };
  const amountField = (label: string, value: unknown, currency: Currency = 'USD'): Field => ({ label: `${label} · ${currency}`, value: money(value, currency) });
  const field = (label: string, value: unknown, wide = false): Field => ({ label, value: text(value), wide });
  const percent = (value: unknown) => finiteAmount(value) === null ? '待补充' : `${Number((Number(value) * 100).toFixed(6))}%`;
  const monthlyPercent = (value: unknown) => {
    const amount = finiteAmount(value);
    if (amount === null) return '待补充';
    const display = Number((amount * 100).toFixed(6)).toString();
    return `${display.includes('.') ? display : `${display}.0`}%`;
  };
  const customerName = (row: any) => row.customer_name || data.customerMap[row.customer_id]?.business_name || '未关联客户';

  useEffect(() => { setVisibleLimit(20); }, [query, tab, periodLabel, currency, category, status, chartView]);

  // Presentation only: rows and monetary totals are supplied by Finance's
  // existing calculations. Never derive a new profit or combine currencies here.
  const records = useMemo((): RecordCard[] => {
    if (tab === 'monthly_detail') return data.monthlyRows.map(row => ({
      id: `month-${row.month}`, kind: tab, record: row, section: '月度账目', title: text(row.month, '月份待补充'),
      subtitle: '美元账目', badge: row.is_closed ? '已关账' : '未关账', tone: row.profit < 0 ? 'warning' : undefined,
      primary: amountField('经营利润', row.profit), secondary: amountField('服务收入', row.revenue_gross),
      fields: [field('月份', row.month), field('关账状态', row.is_closed ? '已关账' : '未关账'),
        amountField('总收款', row.gross_receipts), amountField('退款', row.refund_amount), amountField('净收款', row.net_receipts),
        amountField('服务收入', row.revenue_gross), amountField('管理费收入', row.management_revenue), amountField('投流客户资金', row.ads_recharge_revenue),
        amountField('确认投流差价', row.recognized_ad_spread), amountField('广告实支', row.actual_ad_spend), amountField('投流结余', row.ad_closing_balance),
        field('管理费扣点率', monthlyPercent(row.management_rate)), amountField('管理费扣点', row.management_deduction_amount),
        amountField('Stripe 手续费', row.stripe_platform_fee), amountField('总扣点', row.deduction_amount), amountField('客户成本', row.customer_cost),
        amountField('运营支出', row.operating_cost_usd), amountField('渠道佣金', row.channel_commission_usd), amountField('总成本', row.cost), amountField('经营利润', row.profit)],
    }));
    if (tab === 'customer_profit') return data.customerProfitRows.map((row, index) => ({
      id: `profit-${row.customerId || index}`, kind: tab, record: row, section: '客户利润', title: text(row.customerName, '未关联客户'),
      subtitle: `${row.paymentCount} 笔收款 · ${row.latestPaymentDate || '日期待补充'}`, badge: row.warningLabel,
      tone: row.warningLevel === 'healthy' ? 'positive' : 'warning', primary: amountField('客户利润', row.profit), secondary: amountField('服务收入', row.revenue),
      fields: [field('客户编号', row.customerId), field('最近收款', row.latestPaymentDate), field('收款笔数', row.paymentCount),
        amountField('服务收入', row.revenue), amountField('管理费收入', row.managementRevenue), amountField('投流客户资金', row.adsRevenue), amountField('其他收入', row.otherRevenue),
        amountField('Stripe 手续费', row.stripeFee), amountField('管理费扣点', row.managementDeduction), amountField('渠道佣金', row.channelCommissionUsd), amountField('扣点 / 费用 / 佣金', row.totalFee),
        amountField('客户成本', row.customerCostUsd), amountField('客户成本', row.customerCostCny, 'CNY'), amountField('客户利润', row.profit), field('利润率', percent(row.profitRate)),
        amountField('欠款', row.outstanding), field('利润状态', row.warningLabel), field('说明', row.warningReason, true)],
    }));
    if (tab === 'refunds') return data.refunds.map((row, index) => {
      const currency = currencyOf(row.currency);
      const status = ({ completed: '已完成', pending: '处理中', failed: '失败' } as Record<string, string>)[row.status] || text(row.status, '状态待补充');
      return {
        id: `refund-${row.id || index}`, kind: tab, record: row, section: '退款记录', title: customerName(row),
        subtitle: shortDate(row.refund_date), badge: status, tone: row.status === 'completed' ? 'positive' : 'warning',
        primary: amountField('退款金额', row.refund_amount, currency), secondary: amountField('手续费退回', row.stripe_fee_refunded_amount, currency),
        fields: [field('退款编号', row.id), field('关联收款编号', row.payment_id), field('客户编号', row.customer_id), field('退款日期', shortDate(row.refund_date)),
          field('币种', row.currency || `${currency}（历史默认）`), field('状态', status), amountField('退款金额', row.refund_amount, currency), amountField('手续费退回', row.stripe_fee_refunded_amount, currency),
          field('退款原因', row.reason, true), field('退款凭证', row.provider_refund_id, true), field('备注', row.notes, true), field('创建时间', row.created_at)],
      };
    });
    if (tab === 'ad_funds') return [
      ...data.unsettled.map((row, index): RecordCard => ({
        id: `unsettled-${row.customer_id}-${row.year_month}-${row.currency}-${index}`, kind: 'ad_funds_unsettled', record: row,
        section: '待月结', title: customerName(row), subtitle: text(row.year_month, '月份待补充'), badge: '待月结', tone: 'warning',
        primary: amountField('待核对资金', row.funds_received, currencyOf(row.currency)),
        fields: [field('客户编号', row.customer_id), field('月份', row.year_month), field('币种', row.currency), amountField('待核对资金', row.funds_received, currencyOf(row.currency))],
      })),
      ...data.settlements.map((row, index): RecordCard => {
        const currency = currencyOf(row.currency);
        const status = row.status === 'closed' ? '已结算' : row.status === 'draft' ? '草稿' : text(row.status, '状态待补充');
        return {
          id: `settlement-${row.id || index}`, kind: tab, record: row, section: '月结记录', title: customerName(row), subtitle: text(row.year_month, '月份待补充'),
          badge: status, tone: row.status === 'closed' ? 'positive' : 'warning', primary: amountField('结余', row.closing_balance, currency), secondary: amountField('广告实支', row.actual_ad_spend, currency),
          fields: [field('月结编号', row.id), field('客户编号', row.customer_id), field('月份', row.year_month), field('币种', row.currency || `${currency}（历史默认）`), field('状态', status),
            amountField('期初结转', row.opening_balance, currency), amountField('本月净充值', row.funds_received, currency), amountField('广告实支', row.actual_ad_spend, currency),
            amountField('退客户', row.customer_refund_amount, currency), amountField('确认差价', row.recognized_spread_amount, currency), amountField('调整金额', row.adjustment_amount, currency), amountField('结余', row.closing_balance, currency),
            field('备注', row.notes, true), field('创建时间', row.created_at), field('更新时间', row.updated_at)],
        };
      }),
    ];
    if (tab === 'customer_expense' || tab === 'company_expense') {
      const company = tab === 'company_expense';
      return (company ? data.companyExpenses : data.customerExpenses).map((row, index) => {
        const currency = company ? companyExpenseCurrency(row) : customerExpenseCurrency(row);
        const category = company ? data.companyExpenseLabels[row.category] || row.category_name || row.category : data.customerExpenseLabels[row.expense_type] || row.expense_type;
        const legacy = !company && row.expense_type === 'ads_fee';
        return {
          id: `expense-${tab}-${row.id || index}`, kind: tab, record: row, section: company ? '运营支出记录' : '客户支出记录',
          title: company ? text(category, '类型待补充') : customerName(row), subtitle: `${text(row.expense_month, '月份待补充')} · ${company ? shortDate(row.expense_date) : text(category, '类型待补充')}`,
          badge: legacy ? '历史投流记录' : undefined, primary: amountField('支出金额', row.amount, currency),
          fields: [field('支出编号', row.id), ...(!company ? [field('客户编号', row.customer_id)] : []), field('费用类型', category),
            amountField('金额', row.amount, currency), field('币种', row.currency || `${currency}（历史默认）`), field('月份', row.expense_month),
            field('支出日期', shortDate(company ? row.expense_date : row.payment_date || row.expense_date)), field('备注', row.notes, true),
            field('创建时间', row.created_at), field('更新时间', row.updated_at), ...(legacy ? [field('计入口径', '历史归档，不重复计入利润', true)] : [])],
        };
      });
    }
    const chartRows: RecordCard[] = data.monthlyTrend.map(row => ({
      id: `trend-${row.key}`, kind: tab, record: row, section: `美元经营趋势 · ${data.chartPeriodLabel}`, title: row.key, subtitle: '经营趋势 · USD',
      tone: row.profitUsd < 0 ? 'warning' : undefined, primary: amountField('经营利润', row.profitUsd), secondary: amountField('服务收入', row.income),
      fields: [amountField('服务收入', row.income), amountField('客户支出', row.customerExp), amountField('Stripe 手续费', row.stripeFee),
        amountField('运营支出', row.companyExpUsd), amountField('渠道佣金', row.channelCommissionUsd), amountField('经营利润', row.profitUsd)],
    }));
    const series = [
      { section: '净收款结构', rows: data.incomeByType, key: 'value' },
      { section: '单一产品净收款', rows: data.productRevenue, key: 'value' },
      { section: '收款模式', rows: data.payModes, key: 'amount' },
      { section: '收款渠道', rows: data.payMethods, key: 'amount' },
      { section: '客户净收款 · 前 10 名', rows: data.customerRevenue, key: 'value' },
      { section: '运营支出分类', rows: data.chartCompanyExpenses, key: 'amount' },
    ];
    series.forEach(({ section, rows, key }) => rows.forEach((row, index) => {
      const currency = currencyOf(row.currency);
      chartRows.push({
        id: `${section}-${row.name}-${index}`, kind: tab, record: row, section, title: text(row.name, '未分类'), subtitle: present(row.count) ? `${row.count} 笔 · ${currency}` : currency,
        primary: amountField(section === '运营支出分类' ? '支出金额' : '净收款', row[key], currency),
        fields: [field('分类', section), field('名称', row.name), amountField('金额', row[key], currency), ...(present(row.count) ? [field('笔数', row.count)] : [])],
      });
    }));
    return chartRows;
  }, [tab, data, formatMoney, customerExpenseCurrency, companyExpenseCurrency]);

  const missingAmounts = records.filter(row => row.primary.value === '待补充' || row.secondary?.value === '待补充').length;
  const summaries: Field[] = tab === 'monthly_detail'
    ? [amountField('服务收入', data.monthlyTotals.revenue), amountField('经营利润', data.monthlyTotals.profit)]
    : tab === 'customer_profit'
      ? [field('客户', `${data.customerProfitRows.length} 位`), field('需要复盘', `${data.profitWarningRows.length} 位`)]
      : tab === 'refunds'
        ? [field('已完成', `${data.refunds.filter(row => row.status === 'completed').length} 笔`), field('处理中 / 其他', `${data.refunds.filter(row => row.status !== 'completed').length} 笔`)]
        : tab === 'ad_funds'
          ? [amountField('已结算广告实支', data.summaryFinance.actualAdSpend), amountField('已结算结余', data.summaryFinance.adClosingBalance)]
          : tab === 'customer_expense'
            ? [amountField('非投流客户成本', data.customerExpenseTotalUsd), field('支出记录', `${data.customerExpenses.length} 笔`)]
            : tab === 'company_expense'
              ? [amountField('运营支出', data.companyExpenseTotals.USD), amountField('运营支出', data.companyExpenseTotals.CNY, 'CNY')]
              : [amountField('运营支出', data.chartCompanyExpenseTotals.USD), amountField('运营支出', data.chartCompanyExpenseTotals.CNY, 'CNY')];

  const words = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  const filteredRecords = records.filter(row => {
    const haystack = [row.title, row.subtitle, row.badge, row.section, row.primary.value, row.secondary?.value, ...row.fields.flatMap(item => [item.label, item.value])].join(' ').toLocaleLowerCase();
    const recordCurrency = row.kind === 'company_expense' ? companyExpenseCurrency(row.record) : row.kind === 'customer_expense' ? customerExpenseCurrency(row.record) : currencyOf(row.record.currency);
    const recordCategory = row.fields.find(item => item.label === '费用类型')?.value;
    const recordStatus = row.kind === 'ad_funds_unsettled' ? 'unsettled' : row.record.status;
    const chartMatches = tab !== 'charts' || query || (chartView === 'trend' ? row.section.startsWith('美元经营趋势') : chartView === 'expense' ? row.section === '运营支出分类' : !row.section.startsWith('美元经营趋势') && row.section !== '运营支出分类');
    return words.every(word => haystack.includes(word)) && (currency === 'all' || recordCurrency === currency) && (category === 'all' || recordCategory === category) && (status === 'all' || recordStatus === status) && Boolean(chartMatches);
  });
  const expenseCategories = [...new Set(records.map(row => row.fields.find(item => item.label === '费用类型')?.value).filter(Boolean))];
  const shownRecords = filteredRecords.slice(0, visibleLimit);
  const pending = !hasLoaded;
  const selectedMonthlyRecord = tab === 'monthly_detail' && hasLoaded
    ? records.find(row => row.id === selectedMonthlyId)
    : undefined;
  const monthlyFieldGroups = selectedMonthlyRecord ? [
    { id: 'receipts', label: '收款明细', fields: selectedMonthlyRecord.fields.slice(2, 5) },
    { id: 'income', label: '服务与管理费收入', fields: selectedMonthlyRecord.fields.slice(5, 7) },
    { id: 'ads', label: '投流收支与差价', fields: selectedMonthlyRecord.fields.slice(7, 11) },
    { id: 'deductions', label: '扣点与手续费', fields: selectedMonthlyRecord.fields.slice(11, 15) },
    { id: 'costs', label: '成本明细', fields: selectedMonthlyRecord.fields.slice(15, 19) },
  ] : [];
  const scrollContainer = () => {
    let parent = sectionRef.current?.parentElement;
    while (parent) {
      if (/(auto|scroll)/.test(getComputedStyle(parent).overflowY)) return parent;
      parent = parent.parentElement;
    }
    return document.scrollingElement as HTMLElement | null;
  };
  const openMonthlyRecord = (row: RecordCard, trigger: HTMLButtonElement) => {
    monthlyListTriggerRef.current = trigger;
    setView('monthlyListScroll', scrollContainer()?.scrollTop || 0);
    monthlyNavigationRef.current = 'detail';
    setView('selectedMonthlyId', row.id);
  };
  const returnToMonthlyList = () => {
    monthlyReturnIdRef.current = selectedMonthlyId;
    monthlyNavigationRef.current = 'list';
    setView('selectedMonthlyId', '');
  };

  useLayoutEffect(() => {
    if (selectedMonthlyRecord) {
      scrollContainer()?.scrollTo({ top: 0, behavior: 'auto' });
      monthlyBackRef.current?.focus({ preventScroll: true });
    } else if (monthlyNavigationRef.current === 'list') {
      scrollContainer()?.scrollTo({ top: monthlyListScroll, behavior: 'auto' });
      const trigger = monthlyListTriggerRef.current || Array.from(sectionRef.current?.querySelectorAll<HTMLButtonElement>('.mfd-monthly-record') || [])
        .find(button => button.dataset.recordId === monthlyReturnIdRef.current);
      trigger?.focus({ preventScroll: true });
    }
    monthlyNavigationRef.current = null;
  }, [selectedMonthlyRecord?.id]);

  useEffect(() => {
    if (tab === 'monthly_detail' && hasLoaded && !loading && selectedMonthlyId && !selectedMonthlyRecord) {
      setView('selectedMonthlyId', '');
    }
  }, [tab, hasLoaded, loading, selectedMonthlyId, selectedMonthlyRecord?.id]);

  return (
    <section ref={sectionRef} className={`mobile-finance-details${tab === 'monthly_detail' ? ' mfd-monthly' : ''}`} aria-label="手机财务明细">
      <div hidden={Boolean(selectedMonthlyRecord)}>
        <header className="mfd-header"><div><h1>{getFinanceNavigationItem(tab).label}</h1><p>{periodLabel}</p></div>{actions && <div className="mfd-actions">{actions}</div>}</header>
        <MobileFinanceDateFilter {...dateFilter} />
      </div>
      {error && <div className="mfd-alert" role="alert"><strong>{hasLoaded ? '读取失败，当前显示上次同步数据' : '数据暂时无法加载'}</strong><p>{error}</p>{hasLoaded && lastUpdated && <p>上次同步：{lastUpdated.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) + '（北京时间）'}</p>}<button type="button" disabled={loading} onClick={onRetry}>重新加载</button></div>}
      {pending && !error ? <div className="mfd-empty" role="status">正在读取财务明细…</div> : !pending && <>
        {calculationWarning && <p className="mfd-data-notice" role="status">{calculationWarning}</p>}
        {missingAmounts > 0 && <p className="mfd-data-notice" role="status">{missingAmounts} 条记录的金额待补充，当前汇总需核对。</p>}
        {selectedMonthlyRecord && <div className="mfd-monthly-detail" role="region" aria-label={`${selectedMonthlyRecord.title}月度账目详情`} data-record-kind="monthly_detail" data-record-id={selectedMonthlyRecord.id}>
          <button ref={monthlyBackRef} type="button" className="mfd-monthly-back" onClick={returnToMonthlyList}><ArrowLeft aria-hidden="true" />返回按月明细</button>
          <dl className="mfd-monthly-meta">
            <div><dt>{selectedMonthlyRecord.fields[0].label}</dt><dd><h1>{selectedMonthlyRecord.fields[0].value}</h1></dd></div>
            <div><dt>{selectedMonthlyRecord.fields[1].label}</dt><dd><span className={`mfd-badge ${selectedMonthlyRecord.record.is_closed ? 'positive' : ''}`}>{selectedMonthlyRecord.fields[1].value}</span></dd></div>
          </dl>
          <p className="mfd-monthly-caption">{selectedMonthlyRecord.subtitle} · USD</p>
          <section className="mfd-monthly-overview" aria-label="月度经营摘要">
            <dl><div><dt>{selectedMonthlyRecord.primary.label}</dt><dd className={selectedMonthlyRecord.tone === 'warning' ? 'mfd-warning-amount' : ''}>{selectedMonthlyRecord.primary.value}</dd></div></dl>
            <div className="mfd-monthly-secondary">
              {[selectedMonthlyRecord.fields[5], selectedMonthlyRecord.fields[4]].map(item => <div key={item.label}><span>{item.label}</span><strong>{item.value}</strong></div>)}
            </div>
          </section>
          <div className="mfd-monthly-groups" aria-label="完整财务明细">
            {monthlyFieldGroups.map((group, index) => <details className="mfd-monthly-group" key={`${selectedMonthlyRecord.id}-${group.id}`} open={monthlyGroups.includes(group.id)} onToggle={event => {
              const open = event.currentTarget.open;
              setView('monthlyGroups', ids => open ? ids.includes(group.id) ? ids : [...ids, group.id] : ids.filter(id => id !== group.id));
            }}>
              <summary><span><span className="mfd-group-number" aria-hidden="true">{String(index + 1).padStart(2, '0')}</span>{group.label}</span><span>{group.fields.length} 项<ChevronDown aria-hidden="true" /></span></summary>
              <dl>{group.fields.map(item => <div key={item.label} className={['净收款 · USD', '总扣点 · USD', '总成本 · USD'].includes(item.label) ? 'mfd-monthly-subtotal' : ''}><dt>{item.label}</dt><dd>{item.value}</dd></div>)}</dl>
            </details>)}
          </div>
          {renderRecordActions && <div className="mfd-monthly-detail-actions mfd-actions">{renderRecordActions({ kind: selectedMonthlyRecord.kind, record: selectedMonthlyRecord.record })}</div>}
          {calculationNote && <details className="mfd-basis"><summary>口径说明<ChevronDown aria-hidden="true" /></summary><p>{calculationNote}</p></details>}
        </div>}
        <div hidden={Boolean(selectedMonthlyRecord)}>
        <div className="mfd-summaries" aria-label="当前范围概要">{summaries.map(item => <div className="mfd-summary" key={item.label}><span>{item.label}</span><strong>{missingAmounts > 0 && / · (USD|CNY)$/.test(item.label) ? '待核对' : item.value}</strong></div>)}</div>
        {tab === 'charts' && <><div className="mfd-segments" aria-label="分析分组">{[['trend', '经营趋势'], ['income', '收入结构'], ['expense', '支出结构']].map(([key, label]) => <button type="button" key={key} aria-pressed={chartView === key} onClick={() => setView('chartView', key)}>{label}</button>)}</div>{chartView === 'trend' && <div className="mfd-trend" aria-label="美元经营利润趋势"><h2>经营利润 · USD</h2><ResponsiveContainer width="100%" height={168}><BarChart data={data.monthlyTrend}><XAxis dataKey="key" tick={{ fontSize: 12 }} /><Tooltip formatter={(value: number) => [formatMoney(value, 'USD'), '经营利润']} /><Bar dataKey="profitUsd" radius={[4, 4, 0, 0]}>{data.monthlyTrend.map(row => <Cell key={row.key} fill={row.profitUsd < 0 ? '#b45309' : '#2563eb'} />)}</Bar></BarChart></ResponsiveContainer></div>}</>}
        {(['customer_expense', 'company_expense', 'refunds', 'ad_funds'].includes(tab)) && <div className="mfd-filters"><select aria-label="明细币种" value={currency} onChange={event => setView('currency', event.target.value)}><option value="all">全部币种</option><option value="USD">USD · 美元</option><option value="CNY">CNY · 人民币</option></select>{expenseCategories.length > 0 && <select aria-label="费用类型筛选" value={category} onChange={event => setView('category', event.target.value)}><option value="all">全部费用类型</option>{expenseCategories.map(value => <option key={value} value={value}>{value}</option>)}</select>}{(tab === 'refunds' || tab === 'ad_funds') && <select aria-label="明细状态" value={status} onChange={event => setView('status', event.target.value)}><option value="all">全部状态</option>{(tab === 'refunds' ? [['completed', '已完成'], ['pending', '处理中'], ['failed', '失败']] : [['unsettled', '待月结'], ['draft', '草稿'], ['closed', '已结算']]).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select>}</div>}
        <label className="mfd-search"><Search aria-hidden="true" /><input type="search" aria-label="搜索当前明细" placeholder="搜索当前明细" value={query} onChange={event => setQuery(event.target.value)} /></label>
        <div className="mfd-list-meta" role="status"><span>{query ? `找到 ${filteredRecords.length} 条` : `共 ${records.length} 条`}</span><span>已显示 {shownRecords.length} 条</span></div>
        {shownRecords.length === 0 ? <div className="mfd-empty"><p>{query || currency !== 'all' || category !== 'all' || status !== 'all' ? '没有匹配的明细' : '当前时间范围暂无明细'}</p>{(currency !== 'all' || category !== 'all' || status !== 'all') && <button type="button" onClick={() => { setView('currency', 'all'); setView('category', 'all'); setView('status', 'all'); }}>清除明细筛选</button>}{query && <button type="button" onClick={() => setQuery('')}>清除搜索</button>}{dateFilter.mode !== 'all' && <button type="button" onClick={() => dateFilter.onModeChange('all')}>查看全部时间</button>}</div> : <div className="mfd-records">{shownRecords.map((row, index) => <div key={row.id}>
          {(index === 0 || row.section !== shownRecords[index - 1].section) && <h2 className="mfd-section-title">{row.section}</h2>}
          {row.kind === 'monthly_detail' ? <button type="button" className="mfd-record mfd-monthly-record" data-record-kind={row.kind} data-record-id={row.id} aria-label={`打开${row.title}明细`} onClick={event => openMonthlyRecord(row, event.currentTarget)}>
            <div className="mfd-monthly-record-head"><h3>{row.title}</h3><div><span className="mfd-monthly-currency">USD</span>{row.badge && <span className={`mfd-badge ${row.record.is_closed ? 'positive' : ''}`}>{row.badge}</span>}<ChevronRight aria-hidden="true" /></div></div>
            <div className="mfd-monthly-record-amounts">{[row.primary, row.secondary].filter((item): item is Field => Boolean(item)).map(item => <div key={item.label}><span>{item.label}</span><strong className={row.tone === 'warning' && item === row.primary ? 'mfd-warning-amount' : ''}>{item.value}</strong></div>)}</div>
          </button> : <details open={expandedIds.includes(row.id)} onToggle={event => { const open = event.currentTarget.open; setView('expandedIds', ids => open ? ids.includes(row.id) ? ids : [...ids, row.id] : ids.filter(id => id !== row.id)); }} className="mfd-record" data-record-kind={row.kind} data-record-id={row.id}>
            <summary aria-label={`展开${row.title}明细`}>
              <div className="mfd-record-head"><div><h3>{row.title}</h3><p>{row.subtitle}</p></div><ChevronDown aria-hidden="true" /></div>
              {row.badge && <span className={`mfd-badge ${row.tone || ''}`}>{row.badge}</span>}
              <div className="mfd-card-amounts"><div><span>{row.primary.label}</span><strong className={row.tone === 'warning' ? 'mfd-warning-amount' : ''}>{row.primary.value}</strong></div>{row.secondary && <div><span>{row.secondary.label}</span><strong>{row.secondary.value}</strong></div>}</div>
            </summary>
            <div className="mfd-record-body"><dl>{row.fields.map((item, fieldIndex) => <div className={item.wide ? 'mfd-field-wide' : ''} key={`${item.label}-${fieldIndex}`}><dt>{item.label}</dt><dd>{item.value}</dd></div>)}</dl>{renderRecordActions && <div className="mfd-actions">{renderRecordActions({ kind: row.kind, record: row.record })}</div>}</div>
          </details>}
        </div>)}</div>}
        {filteredRecords.length > visibleLimit && <button type="button" className="mfd-load-more" onClick={() => setVisibleLimit(limit => limit + 20)}>加载更多<span>还有 {filteredRecords.length - shownRecords.length} 条</span></button>}
        {calculationNote && <details className="mfd-basis"><summary>口径说明<ChevronDown aria-hidden="true" /></summary><p>{calculationNote}</p></details>}
        </div>
      </>}
    </section>
  );
}
