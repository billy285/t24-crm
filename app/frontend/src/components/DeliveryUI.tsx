import type { CSSProperties, ReactNode } from 'react';
import { ArrowUpRight, ClipboardCheck } from 'lucide-react';
import './delivery-center.css';

export type DeliveryMetricItem = {
  key: string;
  label: string;
  value: ReactNode;
  note: string;
  tone?: 'blue' | 'rose' | 'amber' | 'green';
  active?: boolean;
  onClick?: () => void;
  testId?: string;
};

export function DeliveryMetrics({ items, label = '工作概览' }: { items: DeliveryMetricItem[]; label?: string }) {
  return <section className="dc-metrics" aria-label={label} style={{ '--dc-metric-count': items.length } as CSSProperties}>
    {items.map(item => {
      const content = <><span className="dc-metric-label"><i className={`dc-dot dc-${item.tone || 'blue'}`} />{item.label}{item.onClick && <ArrowUpRight size={13} />}</span><strong data-testid={item.testId}>{item.value}</strong><small>{item.note}</small></>;
      return item.onClick
        ? <button key={item.key} type="button" aria-pressed={item.active} className={`dc-metric ${item.active ? 'is-active' : ''}`} onClick={item.onClick}>{content}</button>
        : <article key={item.key} className="dc-metric">{content}</article>;
    })}
  </section>;
}

export function DeliveryEmpty({ title, description, children }: { title: string; description: string; children?: ReactNode }) {
  return <div className="dc-empty"><span><ClipboardCheck size={23} /></span><h3>{title}</h3><p>{description}</p>{children}</div>;
}
