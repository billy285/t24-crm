import { useEffect, useState } from 'react';
import { salesApi, type LeadInsight } from '@/lib/sales-intelligence';

export function useSalesContactWindow(leadId?: number | null) {
  const [context, setContext] = useState<{ timezone?: string; start?: number; end?: number; failed?: boolean }>({});
  useEffect(() => {
    let current = true;
    setContext({});
    if (leadId) salesApi<LeadInsight>(`/leads/${leadId}`).then(data => {
      if (current) setContext({ timezone: data.profile?.timezone, start: data.config?.default_contact_start, end: data.config?.default_contact_end });
    }).catch(() => { if (current) setContext({ failed: true }); });
    return () => { current = false; };
  }, [leadId]);
  return context;
}

export default function SalesLocalTime({ timezone, start, end, failed }: { timezone?: string; start?: number; end?: number; failed?: boolean }) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => { const timer = window.setInterval(() => setNow(new Date()), 60000); return () => window.clearInterval(timer); }, []);
  if (!timezone) return <p className="sales-local-time">{failed ? '当地时间暂不可用' : '当地时区待确认'}</p>;
  try {
    const format = new Intl.DateTimeFormat('zh-CN', { timeZone: timezone, weekday: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
    const hour = Number(new Intl.DateTimeFormat('en-US', { timeZone: timezone, hour: 'numeric', hourCycle: 'h23' }).format(now));
    const knownWindow = Number.isFinite(start) && Number.isFinite(end);
    return <p className="sales-local-time">当地 {format.format(now)}{knownWindow && <span> · {hour >= start! && hour < end! ? '建议联系时段内' : '按客户约定联系'}</span>}</p>;
  } catch { return <p className="sales-local-time">当地时区待确认</p>; }
}
