import type { ReactNode } from 'react';
import { ChevronDown, SlidersHorizontal, X } from 'lucide-react';
import { Input } from './ui/input';

export type WorkspaceActiveFilter = { key: string; label: string; onClear: () => void };

type Props = {
  scopeControls: ReactNode;
  merchantLabel: string;
  platformLabel: string;
  currentMonth: string;
  month: string | null;
  dates: { from: string; to: string };
  busy: boolean;
  advancedOpen: boolean;
  onAdvanced: (value: boolean) => void;
  onMonth: (month: string) => void;
  filters: WorkspaceActiveFilter[];
  children: ReactNode;
};

export default function MediaWorkspaceToolbar({
  scopeControls, merchantLabel, platformLabel, currentMonth, month, dates,
  busy, advancedOpen, onAdvanced, onMonth, filters, children,
}: Props) {
  const period = month
    ? month === currentMonth ? '本月' : month
    : `${dates.from || '待选开始日期'} 至 ${dates.to || '待选结束日期'}`;
  const summary = [merchantLabel, platformLabel, period, ...filters.map(filter => filter.label)].join(' · ');
  return (
    <section className="mwr-toolbar" aria-label="当前运营范围与筛选" data-expanded={advancedOpen}>
      <button
        type="button" className="mwr-mobile-scope" disabled={busy}
        aria-label={`运营筛选，${summary}`} title={summary}
        aria-expanded={advancedOpen} aria-controls="mwr-scope-controls"
        onClick={() => onAdvanced(!advancedOpen)}
      >
        <SlidersHorizontal size={16} aria-hidden="true" />
        <span className="mwr-mobile-scope-values">
          <span>{merchantLabel}</span><i aria-hidden="true">·</i>
          <span>{platformLabel}</span><i aria-hidden="true">·</i>
          <span>{period}</span>
        </span>
        <strong><span>{filters[0]?.label || '筛选'}</span>{filters.length > 1 && <b>+{filters.length - 1}</b>}</strong>
        <ChevronDown size={14} aria-hidden="true" />
      </button>
      <div id="mwr-scope-controls" className="mwr-scope-controls">
        <div className="mwr-toolbar-main">
          <div className="mwr-scope-fields">{scopeControls}</div>
          <label className="mwr-month">
            <span>工作月份</span>
            <Input aria-label="运营工作月份" type="month" value={month || ''} disabled={busy}
              onChange={event => { if (/^20\d{2}-(0[1-9]|1[0-2])$/.test(event.target.value)) onMonth(event.target.value); }} />
          </label>
          <button
            type="button" className="mwr-advanced-toggle" aria-label="更多运营筛选" disabled={busy}
            aria-expanded={advancedOpen} aria-controls="mwr-advanced-filters"
            onClick={() => onAdvanced(!advancedOpen)}
          >
            <SlidersHorizontal size={15}/><span>更多筛选{filters.length > 0 && <b>{filters.length}</b>}</span><ChevronDown size={13}/>
          </button>
        </div>
        {!month && <p className="mwr-custom-range">自定义期间：{dates.from} — {dates.to} · 按北京时间统计</p>}
        {filters.length > 0 && <div className="mwr-active-filters" aria-label="当前生效筛选">
          {filters.map(filter => <button key={filter.key} type="button" disabled={busy} onClick={filter.onClear} aria-label={`清除筛选：${filter.label}`}>
            <span>{filter.label}</span><X size={12}/>
          </button>)}
        </div>}
        {advancedOpen && <div id="mwr-advanced-filters" className="mwr-advanced-body">
          {children}<p className="mwr-filter-note">筛选只改变查看范围，商家归属、权限和发布安排不变。</p>
        </div>}
      </div>
    </section>
  );
}
