import { ArrowRight, ArrowUpRight, CheckCircle2, ChevronDown, ChevronRight, Headphones, Info, Target, Users, WalletCards } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useRole } from '@/lib/role-context';
import { getSafeInternalPath } from '@/lib/navigation-state';
import './mobile-owner-dashboard.css';

interface MobileOwnerDashboardProps {
  cockpit: {
    as_of: string;
    period: { month: string };
    finance: {
      USD: {
        profit: number; net_receipts: number; service_revenue: number;
        channel_commission: number; ads_client_funds: number;
      };
      currency_policy: string;
    };
    customers: { active_projects: number; at_risk_projects: number; stopped_this_month: number };
    execution: { overdue_tasks: number; system_tasks: number };
    decisions: { key: string; level: 'critical' | 'high' | 'medium'; title: string; count: number; description: string; link: string }[];
  };
}

const money = (amount: number) => new Intl.NumberFormat('en-US', {
  style: 'currency', currency: 'USD', minimumFractionDigits: 0, maximumFractionDigits: 2,
}).format(amount);

export default function MobileOwnerDashboard({ cockpit }: MobileOwnerDashboardProps) {
  const navigate = useNavigate();
  const { canAccess } = useRole();
  const canOpen = (path: string) => {
    const safePath = getSafeInternalPath(path);
    return Boolean(safePath && canAccess(new URL(safePath, 'https://t24-crm.local').pathname));
  };
  const open = (path: string) => {
    if (canOpen(path)) navigate(getSafeInternalPath(path));
  };
  const monthParts = cockpit.period.month.match(/^(\d{4})-(\d{2})$/);
  const asOf = new Date(cockpit.as_of);
  const asOfLabel = Number.isNaN(asOf.getTime()) ? '' : new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(asOf);
  const financePath = `/finance?tab=monthly_detail&month=${encodeURIComponent(cockpit.period.month)}`;
  const shortcuts = [
    { label: '公司战略', path: '/company-roadmap', icon: Target },
    { label: '客户中心', path: '/customers', icon: Users },
    { label: '财务结算', path: '/finance', icon: WalletCards },
    { label: '销售中心', path: '/sales-workbench', icon: Headphones },
  ].filter(item => canOpen(item.path));
  const usd = cockpit.finance.USD;
  const hasAttention = cockpit.decisions.length > 0;

  return (
    <div className="owner-mobile-dashboard" aria-label="今日经营">
      <div className="owner-mobile-context">
        <span>{monthParts ? `${Number(monthParts[2])} 月经营概况` : `${cockpit.period.month} 经营概况`}</span>
        {monthParts && <span>{monthParts[1]} 年</span>}
      </div>

      <section className={`owner-mobile-attention${hasAttention ? '' : ' owner-mobile-healthy'}`} aria-labelledby="owner-attention-heading">
        <div className="owner-mobile-heading"><h2 id="owner-attention-heading">今天先关注</h2><span>{cockpit.decisions.length} 类事项</span></div>
        {hasAttention ? <>
          <div className="owner-mobile-attention-metrics">
            <div><span>全部任务逾期</span><strong>{cockpit.execution.overdue_tasks} <small>项</small></strong></div>
            <div><span>合作项目风险</span><strong>{cockpit.customers.at_risk_projects} <small>个</small></strong></div>
          </div>
          <details className="owner-mobile-attention-details">
            <summary><span>查看关注事项</span><ArrowUpRight aria-hidden="true" /></summary>
            <div className="owner-mobile-decision-list">
              {cockpit.decisions.map(item => {
                const content = <><span className="owner-mobile-decision-copy"><strong>{item.title}</strong><small>{item.description}</small></span><span className="owner-mobile-decision-count">{item.count}</span><ArrowRight aria-hidden="true" /></>;
                return canOpen(item.link)
                  ? <button key={item.key} type="button" onClick={() => open(item.link)} className={`owner-mobile-decision owner-mobile-decision-${item.level}`}>{content}</button>
                  : <div key={item.key} className={`owner-mobile-decision owner-mobile-decision-${item.level}`}>{content}</div>;
              })}
            </div>
          </details>
        </> : <p className="owner-mobile-no-attention"><CheckCircle2 aria-hidden="true" />当前没有需要推动的异常事项</p>}
      </section>

      <section aria-labelledby="owner-finance-heading">
        <div className="owner-mobile-heading"><h2 id="owner-finance-heading">本月经营</h2><span>USD</span></div>
        <div className="owner-mobile-finance-card">
          <div className="owner-mobile-finance-metrics">
            <div><span>经营利润</span><strong className={usd.profit < 0 ? 'owner-mobile-negative' : undefined}>{money(usd.profit)}</strong></div>
            <div><span>净收款</span><strong>{money(usd.net_receipts)}</strong></div>
          </div>
          <details className="owner-mobile-finance-details">
            <summary><span>查看财务明细</span><ChevronDown aria-hidden="true" /></summary>
            <dl>
              <div><dt>服务收入</dt><dd>{money(usd.service_revenue)}</dd></div>
              <div><dt>已确认渠道佣金</dt><dd>{money(usd.channel_commission || 0)}</dd></div>
              <div><dt>客户投流资金</dt><dd>{money(usd.ads_client_funds)}</dd></div>
            </dl>
            <p>投流资金不计经营收入</p>
            {canOpen(financePath) && <button type="button" onClick={() => open(financePath)} className="owner-mobile-inline">查看本月账目<ArrowRight aria-hidden="true" /></button>}
          </details>
        </div>
      </section>

      <section aria-labelledby="owner-progress-heading">
        <div className="owner-mobile-heading"><h2 id="owner-progress-heading">业务进展</h2></div>
        <div className="owner-mobile-progress-grid">
          <button type="button" onClick={() => open('/customer-lifecycle')} disabled={!canOpen('/customer-lifecycle')} className="owner-mobile-progress-card">
            <span>合作项目</span><strong>{cockpit.customers.active_projects}</strong><small>本月停止 {cockpit.customers.stopped_this_month}</small><ChevronRight aria-hidden="true" />
          </button>
          <button type="button" onClick={() => open('/tasks?source=system')} disabled={!canOpen('/tasks')} className="owner-mobile-progress-card">
            <span>系统推动中任务</span><strong>{cockpit.execution.system_tasks}</strong><small>查看系统任务</small><ChevronRight aria-hidden="true" />
          </button>
        </div>
      </section>

      {shortcuts.length > 0 && <section aria-labelledby="owner-shortcuts-heading">
        <div className="owner-mobile-heading"><h2 id="owner-shortcuts-heading">快捷入口</h2></div>
        <div className="owner-mobile-shortcuts">{shortcuts.map(item => <button key={item.path} type="button" onClick={() => open(item.path)}><span><item.icon aria-hidden="true" /></span><small>{item.label}</small></button>)}</div>
      </section>}

      <details className="owner-mobile-rules">
        <summary><Info aria-hidden="true" /><span>统计口径</span><ChevronDown aria-hidden="true" /></summary>
        <div>{cockpit.finance.currency_policy.split('；').filter(Boolean).map(rule => <p key={rule}>{rule}</p>)}</div>
      </details>
      {asOfLabel && <p className="owner-mobile-asof">数据截至 {asOfLabel} · 北京时间</p>}
    </div>
  );
}
