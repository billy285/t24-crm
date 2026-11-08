import { useCallback, useEffect, useState } from 'react';
import { AlertCircle, ChevronDown, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useRole } from '@/lib/role-context';
import { invokeWithAuth } from '@/lib/tokenStore';
import './sales-phone-connections.css';

type PhoneConnection = {
  employee_id: number;
  employee_name: string;
  extension_number?: string | null;
  connected: boolean;
  needs_reconnect?: boolean;
  realtime_sync_enabled?: boolean;
  binding_conflict?: boolean;
  last_synced_at?: string | null;
  last_event_at?: string | null;
  last_error?: string | null;
  message?: string;
};

function syncTime(value?: string | null) {
  if (!value) return '尚无成功同步记录';
  const date = new Date(/(Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : `${value.replace(' ', 'T')}Z`);
  if (Number.isNaN(date.getTime())) return '同步时间待确认';
  return new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(date) + '（北京时间）';
}

function connectionLabel(item: PhoneConnection) {
  if (item.binding_conflict) return '分机绑定冲突';
  if (item.needs_reconnect) return '需要重新连接';
  if (!item.connected) return '尚未连接';
  if (item.last_error || !item.realtime_sync_enabled) return '同步需处理';
  if (!item.last_synced_at) return '等待首次同步';
  return '实时同步已启用';
}

export default function SalesPhoneConnections({ onConnectMine }: { onConnectMine?: () => void }) {
  const { employee, role } = useRole();
  const managing = ['admin', 'super_admin', 'sales_manager'].includes(role);
  const [items, setItems] = useState<PhoneConnection[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const retry = useCallback(() => setRefresh(value => value + 1), []);

  useEffect(() => {
    let live = true;
    const load = async () => {
      if (live) setLoading(true);
      try {
        const response = await invokeWithAuth({ url: '/api/ringcentral/team-status', method: 'GET' });
        if (!Array.isArray(response.data?.items)) throw new Error('Invalid connection response');
        if (live) { setItems(response.data.items); setError(false); }
      } catch { if (live) setError(true); }
      finally { if (live) setLoading(false); }
    };
    setItems(null);
    void load();
    const timer = window.setInterval(() => void load(), 30000);
    return () => { live = false; window.clearInterval(timer); };
  }, [employee?.id, role, refresh]);

  const attention = items?.filter(item => connectionLabel(item) !== '实时同步已启用').length || 0;
  return <section className="sales-phone-connections" aria-label={managing ? '团队电话接入' : '我的电话接入'} aria-busy={loading}>
    <details>
      <summary><span><strong>{managing ? '团队电话接入' : '我的电话接入'}</strong><small>{error ? '连接状态读取失败' : !items ? '正在检查连接…' : items.length === 0 ? '暂无可统计销售' : attention ? `${items.length} 位销售 · ${attention} 位需处理` : `${items.length} 位销售 · 实时同步已启用`}</small></span><ChevronDown size={16} /></summary>
      <div className="sales-phone-body">
        <div className="sales-phone-actions"><p>每位销售用自己的CRM账号连接已分配的RingCentral账号或分机，通话按绑定销售归属。</p><Button type="button" size="sm" variant="outline" disabled={loading} onClick={retry}><RefreshCw size={14} />刷新状态</Button></div>
        {error && <p className="sales-phone-warning" role="alert"><AlertCircle size={15} />连接状态暂不可用，不能据此判断销售没有拨打。{items && ' 下方保留上次读取结果。'}</p>}
        {items && items.length > 0 && <div className="sales-phone-grid">{items.map(item => {
          const label = connectionLabel(item);
          const healthy = label === '实时同步已启用';
          const mine = Number(employee?.id) === item.employee_id;
          return <article key={item.employee_id}>
            <div className="sales-phone-person"><strong>{item.employee_name}{mine && <small>（我）</small>}</strong><span className={healthy ? 'ready' : 'attention'}>{label}</span></div>
            <p>分机：{item.extension_number || '未绑定'}</p>
            <p>最近成功同步：{syncTime(item.last_synced_at)}</p>
            {item.last_event_at && <p>最近通话事件：{syncTime(item.last_event_at)}</p>}
            {item.binding_conflict ? <p className="sales-phone-error">同一分机绑定了多个员工，请管理员核对归属后处理。</p> : item.last_error ? <p className="sales-phone-error">{item.last_error}</p> : !healthy && <p>{item.message || '请销售连接自己的电话账号，并检查同步状态。'}</p>}
            {!healthy && (mine && onConnectMine ? <Button type="button" size="sm" variant="outline" onClick={onConnectMine}>{item.connected || item.needs_reconnect ? '重新连接我的账号' : '连接我的RingCentral'}</Button> : <p className="sales-phone-help">请该销售登录自己的CRM账号，在「拨号与任务设置」中连接。</p>)}
          </article>;
        })}</div>}
        <p className="sales-phone-footnote">接入状态表示当前连接情况；历史通话是否齐全仍需核对。未连接或同步异常时，报表中的0条不代表实际未拨打。</p>
      </div>
    </details>
    {(error || attention > 0) && <p className="sales-phone-summary-warning" role="status">{error ? '电话连接状态暂不可用' : `${attention} 位销售的电话接入需处理`}，通话统计可能不完整。展开查看详情。</p>}
  </section>;
}
