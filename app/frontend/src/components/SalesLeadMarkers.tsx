import { useState } from 'react';
import { Flag, Star } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { invokeWithAuth } from '@/lib/tokenStore';
import './sales-lead-markers.css';

type LeadMarkers = { starred: boolean; priority: boolean };

export default function SalesLeadMarkers({
  leadId,
  starred = false,
  priority = false,
  canManage = false,
  onChanged,
}: {
  leadId: number;
  starred?: boolean;
  priority?: boolean;
  canManage?: boolean;
  onChanged: (markers: LeadMarkers) => void | Promise<unknown>;
}) {
  const [busy, setBusy] = useState(false);

  async function toggle(key: keyof LeadMarkers, value: boolean) {
    setBusy(true);
    try {
      const { data } = await invokeWithAuth({
        url: `/api/v1/sales-leads/${leadId}/markers`,
        method: 'PUT',
        data: { [key]: value },
      });
      await onChanged(data);
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      toast.error(typeof detail === 'string' ? detail : '标记未保存，请重试');
    } finally {
      setBusy(false);
    }
  }

  return <span className="sales-lead-markers">
    <Button type="button" variant="ghost" className="sales-lead-marker" aria-label="我的星标" title={starred ? '取消我的星标' : '加入我的星标'} aria-pressed={starred} disabled={busy} onClick={() => void toggle('starred', !starred)}>
      <Star size={16} fill={starred ? 'currentColor' : 'none'} aria-hidden="true" />
    </Button>
    {canManage ? <Button type="button" variant="ghost" className="sales-lead-marker" aria-label="团队重点单" title={priority ? '取消团队重点' : '标记为团队重点单'} aria-pressed={priority} disabled={busy} onClick={() => void toggle('priority', !priority)}>
      <Flag size={16} fill={priority ? 'currentColor' : 'none'} aria-hidden="true" />
    </Button> : priority && <span className="sales-lead-priority-label"><Flag size={14} aria-hidden="true" />重点单</span>}
  </span>;
}
