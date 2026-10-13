import { useId, useState } from 'react';
import { AlertCircle, ArrowUpRight, CheckCircle2, ChevronDown, Info } from 'lucide-react';
import './finance-closing-checklist.css';

export type FinanceClosingChecklistItem = {
  key: string;
  label: string;
  help: string;
  // The existing checklist builder infers this field as string.
  level: string;
  count: number;
};

type Props<Item extends FinanceClosingChecklistItem> = {
  checklist: {
    month: string;
    paymentCount: number;
    customerExpenseCount: number;
    subscriptionCount: number;
    blockerCount: number;
    warningCount: number;
    items: Item[];
  };
  onOpenIssue: (item: Item, month: string) => void;
};

/** Presentation only. Counts, issue actions and closing eligibility belong to Finance. */
export default function FinanceClosingChecklist<Item extends FinanceClosingChecklistItem>({ checklist, onOpenIssue }: Props<Item>) {
  const id = useId();
  const [expandedMonth, setExpandedMonth] = useState<string | null>(null);
  const expanded = expandedMonth === checklist.month;
  const passedCategoryCount = checklist.items.filter(item => item.count === 0).length;
  const visibleItems = expanded ? checklist.items : checklist.items.filter(item => item.count > 0);
  const hasBlockers = checklist.blockerCount > 0;
  const hasWarnings = checklist.warningCount > 0;

  return (
    <section className="finance-closing-checklist" aria-labelledby={`${id}-title`}>
      <div className="fcc-header">
        <div className="fcc-heading">
          <h3 id={`${id}-title`}>关账检查</h3>
          <span className="fcc-month">{checklist.month || '未选择月份'}</span>
        </div>
        <button type="button" className="fcc-toggle" aria-expanded={expanded} aria-controls={`${id}-checks`}
          onClick={() => setExpandedMonth(expanded ? null : checklist.month)}>
          {expanded ? '收起检查' : `全部检查（${checklist.items.length}项）`}
          <ChevronDown aria-hidden="true" className={expanded ? 'is-expanded' : ''} />
        </button>
      </div>

      <div className="fcc-summary" aria-label="检查汇总">
        <span className={hasBlockers ? 'fcc-blocker' : ''}>必处理 <strong>{checklist.blockerCount}</strong></span>
        <span className={hasWarnings ? 'fcc-warning' : ''}>提醒 <strong>{checklist.warningCount}</strong></span>
        <span className="fcc-passed-count"><CheckCircle2 aria-hidden="true" />已通过 {passedCategoryCount}/{checklist.items.length} 项检查</span>
      </div>

      <div id={`${id}-checks`} className="fcc-checks">
        {visibleItems.map(item => {
          const hasIssue = item.count > 0;
          const statusClass = hasIssue ? (item.level === 'blocker' ? 'fcc-blocker' : 'fcc-warning') : 'fcc-passed';
          const StatusIcon = hasIssue ? AlertCircle : CheckCircle2;
          return (
            <div key={`${checklist.month}-${item.key}`} className={`fcc-row ${hasIssue ? 'has-issue' : 'is-passed'}`}>
              <StatusIcon aria-hidden="true" className={`fcc-status-icon ${statusClass}`} />
              <div className="fcc-row-content">
                <div className="fcc-row-heading">
                  <span className="fcc-label">{item.label}</span>
                  <span className={`fcc-status ${statusClass}`}>{hasIssue ? `${item.level === 'blocker' ? '必处理' : '提醒'} ${item.count}` : '已通过'}</span>
                  <details className="fcc-help">
                  <summary aria-label={`查看${item.label}说明`}><Info aria-hidden="true" /><span>说明</span></summary>
                  <p>{item.help}</p>
                  </details>
                </div>
              </div>
              {hasIssue && <button type="button" className="fcc-action" aria-label={`处理${item.label}：${item.count}项`}
                onClick={() => onOpenIssue(item, checklist.month)}>去处理<ArrowUpRight aria-hidden="true" /></button>}
            </div>
          );
        })}

        {!hasBlockers && !hasWarnings && !expanded && <p className="fcc-all-clear"><CheckCircle2 aria-hidden="true" />检查全部通过</p>}

        {expanded && <div className="fcc-scope" aria-label="本月检查范围">
          <span>本月收款 <strong>{checklist.paymentCount}</strong> 笔</span>
          <span>客户成本 <strong>{checklist.customerExpenseCount}</strong> 笔</span>
          <span>计划扣款 <strong>{checklist.subscriptionCount}</strong> 笔</span>
        </div>}
      </div>

      {(hasBlockers || hasWarnings) && <p className={`fcc-conclusion ${hasBlockers ? 'fcc-blocker' : 'fcc-muted'}`}>
        {hasBlockers ? '必处理项清零后，才能关账。' : '必处理项已清零，提醒项可由老板确认后关账。'}
      </p>}
    </section>
  );
}
