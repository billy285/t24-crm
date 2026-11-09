import { useEffect, useRef, useState } from 'react';
import { salesApi, type LeadInsight } from '@/lib/sales-intelligence';
import { contactTimezoneBasisLabel, resolveContactTimezone, type ContactTimezone } from '@/lib/contact-timezone';
import { useAutoRefresh } from '@/lib/use-auto-refresh';

export function useSalesContactWindow(leadId?: number | null) {
  const [context, setContext] = useState<ContactTimezone & { start?: number; end?: number; failed?: boolean }>({});
  const refresh = useRef<() => Promise<void>>(async () => {});
  useEffect(() => {
    let current = true;
    let requestSequence = 0;
    const load = async () => {
      if (!leadId) return;
      const request = ++requestSequence;
      try {
        const data = await salesApi<LeadInsight>(`/leads/${leadId}`);
        if (current && request === requestSequence) setContext({ ...resolveContactTimezone(data.profile?.timezone, data.contact_timezone), start: data.config?.default_contact_start, end: data.config?.default_contact_end });
      } catch { if (current && request === requestSequence) setContext({ failed: true }); }
    };
    setContext({});
    refresh.current = load;
    void load();
    return () => { current = false; };
  }, [leadId]);
  useAutoRefresh(() => refresh.current(), { enabled: Boolean(leadId) });
  return context;
}

export default function SalesLocalTime({ timezone, timezone_basis, timezone_needs_confirmation, start, end, failed }: ContactTimezone & { start?: number; end?: number; failed?: boolean }) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => { const timer = window.setInterval(() => setNow(new Date()), 60000); return () => window.clearInterval(timer); }, []);
  if (!timezone) return <p className="sales-local-time">{failed ? '当地时间暂不可用' : '当地时区待确认'}</p>;
  try {
    const format = new Intl.DateTimeFormat('zh-CN', { timeZone: timezone, weekday: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
    const hour = Number(new Intl.DateTimeFormat('en-US', { timeZone: timezone, hour: 'numeric', hourCycle: 'h23' }).format(now));
    const knownWindow = Number.isFinite(start) && Number.isFinite(end);
    return <p className="sales-local-time" title={timezone}>当地 {format.format(now)}{timezone_basis && <span> · {contactTimezoneBasisLabel({ timezone_basis })}{timezone_needs_confirmation && timezone_basis !== 'unknown' ? '（待确认）' : ''}</span>}{knownWindow && <span> · {hour >= start! && hour < end! ? '建议联系时段内' : '按客户约定联系'}</span>}</p>;
  } catch { return <p className="sales-local-time">当地时区待确认</p>; }
}
