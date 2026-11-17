import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { invokeWithAuth } from '@/lib/tokenStore';
import { workbenchIndustryLabels, type WorkbenchIndustry } from '@/pages/sales-workbench-industry';

const zones = { eastern: '东部', central: '中部', mountain: '山地', pacific: '西部' } as const;
export type CallRegion = keyof typeof zones;
export type ClaimChoice = { region: CallRegion | ''; windowOnly: boolean; size: number };
type Stock = { industry: string; total: number; in_window: number; contact_start: number; contact_end: number;
  zones: { group: CallRegion; total: number; in_window: number; local_times: string[] }[] };

type Props = {
  industry: Exclude<WorkbenchIndustry, 'all'>; choice: ClaimChoice; pending: number; disabled: boolean;
  submitting: boolean; revision: number; onChange: (value: ClaimChoice) => void; onClaim: () => void;
};

export default function SalesIndustryClaim({ industry, choice, pending, disabled, submitting, revision, onChange, onClaim }: Props) {
  const [stock, setStock] = useState<Stock | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let current = true;
    let busy = false;
    const read = async () => {
      if (!current || busy) return;
      busy = true;
      try {
        const { data } = await invokeWithAuth({ url: '/api/v1/sales-leads/workbench/industry-stock?industry=' + industry, method: 'GET' });
        if (data?.industry !== industry || !Array.isArray(data.zones) || !Object.keys(zones).every(group =>
            data.zones.some((row: Stock['zones'][number]) => row.group === group && typeof row.total === 'number' &&
              typeof row.in_window === 'number' && Array.isArray(row.local_times)))) throw new Error('库存尚未返回');
        if (current) { setStock(data); setUnavailable(false); }
      } catch {
        if (current) { setStock(null); setUnavailable(true); }
      } finally { busy = false; }
    };
    void read();
    const timer = window.setInterval(() => { if (!document.hidden) void read(); }, 60_000);
    return () => { current = false; window.clearInterval(timer); };
  }, [industry, refresh, revision]);
  const selected = stock && (choice.region ? stock.zones.find(zone => zone.group === choice.region) : stock);
  const available = selected?.[choice.windowOnly ? 'in_window' : 'total'];
  const windowLabel = stock && [stock.contact_start, stock.contact_end].map(hour => String(hour).padStart(2, '0') + ':00').join('–');
  return <section className="sw-claim" aria-label="按当地时间领取名单">
    <div className="sw-claim-regions" role="group" aria-label="领取时区">
      <button type="button" aria-pressed={!choice.region} disabled={disabled} onClick={() => onChange({ ...choice, region: '' })}>
        全部时区</button>
      {(Object.keys(zones) as CallRegion[]).map(group => {
        const entry = stock?.zones.find(item => item.group === group);
        return <button key={group} type="button" aria-label={zones[group]} aria-pressed={choice.region === group}
          disabled={disabled} onClick={() => onChange({ ...choice, region: group })}>
          <strong>{zones[group]}</strong>{entry && <><time>{entry.local_times.join(' / ')}</time>
          <span>{entry[choice.windowOnly ? 'in_window' : 'total'].toLocaleString()} 家</span></>}</button>;
      })}
    </div>
    <div className="sw-claim-settings">
      <label><input type="checkbox" checked={choice.windowOnly} disabled={disabled}
        onChange={event => onChange({ ...choice, windowOnly: event.target.checked })} />
        仅限当地可联系时段{windowLabel && <span>{windowLabel}</span>}</label>
      <label>首拨名单补至 <select value={choice.size} disabled={disabled} aria-label="首拨名单目标数量"
        onChange={event => onChange({ ...choice, size: Number(event.target.value) })}>
        {[1, 5, 10].map(size => <option value={size} key={size}>{size} 家</option>)}</select></label>
    </div>
    <div className="sw-claim-action">
      <span role="status">{unavailable ? '库存暂时无法读取' : available == null ? '正在读取库存…' :
        '可领取 ' + available.toLocaleString() + ' 家'} · 当前队列待拨 {pending} 家</span>
      {unavailable && <Button type="button" size="sm" variant="ghost" onClick={() => setRefresh(v => v + 1)}>重试</Button>}
      <Button type="button" size="sm" disabled={disabled || !available} onClick={onClaim}>
        {submitting ? '正在领取…' : '领取' + workbenchIndustryLabels[industry] + '名单'}</Button>
    </div>
  </section>;
}
