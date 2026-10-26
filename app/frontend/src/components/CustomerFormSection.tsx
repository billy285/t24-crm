import { useState, type ReactNode } from 'react';
import { ChevronDown } from 'lucide-react';

type CustomerFormSectionProps = {
  id: string;
  title: string;
  description: string;
  filled: boolean;
  defaultOpen?: boolean;
  forceOpen?: boolean;
  statusLabel?: string;
  children: ReactNode;
};

// A presentation-only disclosure: children stay mounted and retain every
// original value, handler and permission gate. Project rows stay visible.
export default function CustomerFormSection({ id, title, description, filled, defaultOpen = false, forceOpen = false, statusLabel, children }: CustomerFormSectionProps) {
  const [expanded, setExpanded] = useState(defaultOpen);
  return <details
    id={id}
    className="crm-form-optional"
    open={forceOpen || expanded}
    data-force-open={forceOpen || undefined}
    onToggle={event => {
      if (forceOpen) {
        if (!event.currentTarget.open) event.currentTarget.open = true;
        return;
      }
      setExpanded(event.currentTarget.open);
    }}
  >
    <summary aria-disabled={forceOpen || undefined} onClick={event => { if (forceOpen) event.preventDefault(); }}>
      <span className="crm-form-optional-heading"><strong>{title}<small>选填</small></strong><span>{description}</span></span>
      <span className={`crm-form-optional-status${filled ? ' is-filled' : ''}`}>{statusLabel || (filled ? '已填' : '未填')}</span>
      {!forceOpen && <ChevronDown aria-hidden="true" className="crm-form-optional-chevron" />}
    </summary>
    <div className="crm-form-optional-content">{children}</div>
  </details>;
}
