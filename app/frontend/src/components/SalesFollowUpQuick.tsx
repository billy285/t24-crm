import { Button } from '@/components/ui/button';
import { formatBusinessDateTimeInput, parseBusinessDateTimeInput } from '@/lib/business-date';

export default function SalesFollowUpQuick({ value, onChange, timezone }: { value: string; onChange: (value: string) => void; timezone?: string }) {
  let local = '';
  try {
    if (timezone && value) local = new Intl.DateTimeFormat('zh-CN', { timeZone: timezone, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(parseBusinessDateTimeInput(value)));
  } catch { /* Unknown timezones never change an agreed callback. */ }
  return <div className="sales-followup-quick"><div>{[{ label: '1小时后', hours: 1 }, { label: '明天同一时间', hours: 24 }, { label: '3天后', hours: 72 }].map(item => <Button key={item.label} type="button" size="sm" variant="ghost" onClick={() => onChange(formatBusinessDateTimeInput(new Date(Date.now() + item.hours * 3600000).toISOString()))}>{item.label}</Button>)}</div>{local && <small>商家当地 {local}</small>}</div>;
}
