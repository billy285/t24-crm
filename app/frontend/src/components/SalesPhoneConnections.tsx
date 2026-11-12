import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertCircle, ChevronDown, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useRole } from '@/lib/role-context';
import { invokeWithAuth } from '@/lib/tokenStore';
import './sales-phone-connections.css';

export type SyncCoverage = {
  status: 'unknown' | 'gaps' | 'window_fetched';
  data_complete: false;
  requested_from: string;
  requested_to: string;
  unverified_ranges: { start: string; end: string }[];
  last_attempt?: { status: string; requested_from: string; requested_to: string; finished_at: string; pages: number; fetched: number; saved: number; skipped: number } | null;
  needs_retry?: boolean;
};

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
  coverage?: SyncCoverage;
};

function syncTime(value?: string | null) {
  if (!value) return '尚无成功同步记录';
  const date = new Date(/(Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : `${value.replace(' ', 'T')}Z`);
  if (Number.isNaN(date.getTime())) return '同步时间待确认';
  return new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(date) + '（北京时间）';
}

export function connectionLabel(item: PhoneConnection) {
  if (item.binding_conflict) return '分机绑定冲突';
  if (item.needs_reconnect) return '需要重新连接';
  if (!item.connected) return '待接入';
  if (item.last_error || !item.realtime_sync_enabled) return '同步需处理';
  if (!item.last_synced_at) return '待同步';
  return '实时同步已启用';
}

export function SyncCoverageDetails({ coverage }: { coverage?: SyncCoverage }) {
  if (!coverage) return <p>尚无可核对的同步期间记录。</p>;
  const last = coverage.last_attempt;
  return <details className="sales-sync-evidence"><summary>同步期间与覆盖依据<ChevronDown size={12}/></summary><div>
    <p>{last ? `最近补同步：${last.status === 'completed' ? '分页拉取完成' : last.status === 'partial' ? '部分完成，需处理' : '失败，需重试'}` : '尚无该分机绑定的分页拉取凭据'}</p>
    {last && <><p>{syncTime(last.requested_from)} 至 {syncTime(last.requested_to)}</p><p>读取 {last.pages} 页 · {last.fetched} 条 · 写入/更新 {last.saved} 条 · 未归属 {last.skipped} 条</p></>}
    {coverage.unverified_ranges.length > 0 && <details><summary>{coverage.unverified_ranges.length} 段尚未核验的期间（含新发生通话）<ChevronDown size={12} /></summary><ul>{coverage.unverified_ranges.map((range, index) => <li key={index}>{syncTime(range.start)} 至 {syncTime(range.end)}</li>)}</ul></details>}
    <p>分页已拉取仍不代表历史完整；通话可能延迟入账。</p>
  </div></details>;
}

export default function SalesPhoneConnections({ onConnectMine, periodDays = 7, onSyncComplete }: { onConnectMine?: () => void; periodDays?: number; onSyncComplete?: () => void }) {
  const { employee, role } = useRole();
  const managing = ['admin', 'super_admin', 'sales_manager'].includes(role);
  const [items, setItems] = useState<PhoneConnection[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [attentionOnly, setAttentionOnly] = useState(false);
  const [syncDays, setSyncDays] = useState(7);
  const [busy, setBusy] = useState<string | null>(null);
  const [actionNotice, setActionNotice] = useState<{ employeeId: number; text: string; failed: boolean } | null>(null);
  const actor = `${employee?.id || ''}:${role}`;
  const scope = `${actor}:${periodDays}`;
  const scopeRef = useRef(scope);
  const loadedScopeRef = useRef<string | null>(null);
  scopeRef.current = scope;
  const currentItems = loadedScopeRef.current === scope ? items : null;
  const actorRef = useRef<string | null>(actor);
  const actionRef = useRef<object | null>(null);
  actorRef.current = actor;
  const retry = useCallback(() => setRefresh(value => value + 1), []);
  useEffect(() => {
    actorRef.current = actor;
    setBusy(null); setActionNotice(null); actionRef.current = null;
    return () => { actorRef.current = null; actionRef.current = null; };
  }, [actor]);

  useEffect(() => {
    let live = true;
    const requestScope = scopeRef.current;
    const current = () => live && requestScope === scopeRef.current;
    const load = async () => {
      if (current()) setLoading(true);
      try {
        const response = await invokeWithAuth({ url: `/api/ringcentral/team-status?days=${periodDays}`, method: 'GET' });
        if (!Array.isArray(response.data?.items)) throw new Error('Invalid connection response');
        if (current()) { loadedScopeRef.current = requestScope; setItems(response.data.items); setError(false); }
      } catch (failure: any) {
        if (current()) {
          const status = failure?.response?.status || failure?.data?.status || failure?.status;
          if (status === 401 || status === 403) { loadedScopeRef.current = null; setItems(null); }
          setError(true);
        }
      }
      finally { if (current()) setLoading(false); }
    };
    if (loadedScopeRef.current !== requestScope) { setItems(null); setError(false); }
    void load();
    const timer = window.setInterval(() => void load(), 30000);
    return () => { live = false; window.clearInterval(timer); };
  }, [employee?.id, role, refresh, periodDays]);

  const needsAction = (item: PhoneConnection) => connectionLabel(item) !== '实时同步已启用' || !!item.coverage?.needs_retry || !item.coverage?.last_attempt;
  const runAction = async (item: PhoneConnection, action: 'sync' | 'repair' | 'connect') => {
    if (Number(employee?.id) !== item.employee_id || item.binding_conflict || actionRef.current || loading || error || loadedScopeRef.current !== scopeRef.current) return;
    const ticket = {};
    actionRef.current = ticket;
    const current = () => actorRef.current === actor && actionRef.current === ticket;
    setBusy(action);
    setActionNotice(null);
    try {
      if (action === 'connect') {
        if (onConnectMine) { onConnectMine(); return; }
        const result = await invokeWithAuth({ url: '/api/ringcentral/connect', method: 'GET' });
        if (!current()) return;
        if (!result.data?.authorization_url) throw new Error('暂时无法发起授权，请稍后重试。');
        window.location.assign(result.data.authorization_url);
        return;
      }
      if (action === 'repair') {
        await invokeWithAuth({ url: '/api/ringcentral/subscription/ensure', method: 'POST' });
        if (!current()) return;
      }
      if (loadedScopeRef.current !== scopeRef.current) return;
      const result = await invokeWithAuth({ url: `/api/ringcentral/sync?days=${syncDays}`, method: 'POST' });
      if (!current()) return;
      const partial = result.data?.sync_window?.status !== 'completed';
      setActionNotice({ employeeId: item.employee_id, failed: partial, text: partial ? '本次仅部分同步完成，请核对未归属记录或缩短期间重试。' : `已保存本次分页拉取凭据，保存 ${result.data?.synced || 0} 条；历史完整性仍待核验。` });
    } catch (error: any) {
      if (!current()) return;
      setActionNotice({ employeeId: item.employee_id, failed: true, text: error?.response?.data?.detail || error?.data?.detail || error?.message || '处理未完成，请稍后重试。' });
    } finally {
      if (current()) { actionRef.current = null; setBusy(null); retry(); onSyncComplete?.(); }
    }
  };

  const attention = currentItems?.filter(needsAction).length || 0;
  const displayed = currentItems?.filter(item => !attentionOnly || needsAction(item));
  return <section className="sales-phone-connections" aria-label={managing ? '团队电话接入' : '我的电话接入'} aria-busy={loading}>
    <details>
      <summary><span><strong>{managing ? '团队电话接入' : '我的电话接入'}</strong><small>{error ? '连接状态读取失败' : !currentItems ? '正在检查连接…' : currentItems.length === 0 ? '暂无可统计销售' : attention ? `${currentItems.length} 位销售 · ${attention} 位需处理` : `${currentItems.length} 位销售 · 实时同步已启用`}{loading && currentItems && ' · 更新中'}</small></span><ChevronDown size={16} /></summary>
      <div className="sales-phone-body">
        <div className="sales-phone-actions"><p>每位销售用自己的CRM账号连接已分配的RingCentral账号或分机，通话按绑定销售归属。</p><Button type="button" size="sm" variant="outline" disabled={loading} onClick={retry}><RefreshCw size={14} />刷新状态</Button></div>
        <div className="sales-sync-controls"><Button size="sm" variant="outline" aria-pressed={attentionOnly} onClick={() => setAttentionOnly(value => !value)}>{attentionOnly ? '查看全部员工' : `只看需处理（${attention}）`}</Button><label>本人补同步期间<select value={syncDays} onChange={event => setSyncDays(Number(event.target.value))} disabled={!!busy || loading || error}>{[1, 7, 30].map(days => <option key={days} value={days}>最近{days}天</option>)}</select></label></div>
        {error && <p className="sales-phone-warning" role="alert"><AlertCircle size={15} />连接状态暂不可用，不能据此判断销售没有拨打。{currentItems && ' 下方保留上次读取结果。'}<Button type="button" size="sm" variant="outline" disabled={loading} onClick={retry}>重新读取连接状态</Button></p>}
        {displayed && displayed.length === 0 && currentItems && currentItems.length > 0 && <p role="status">当前没有需要处理的接入或补同步记录。</p>}
        {displayed && displayed.length > 0 && <div className="sales-phone-grid">{displayed.map(item => {
          const label = connectionLabel(item);
          const healthy = label === '实时同步已启用';
          const mine = Number(employee?.id) === item.employee_id;
          return <article key={item.employee_id}>
            <div className="sales-phone-person"><strong>{item.employee_name}{mine && <small>（我）</small>}</strong><span className={healthy ? 'ready' : 'attention'}>{label}</span></div>
            <p>分机：{item.extension_number || '未绑定'}</p>
            <p>最近成功同步：{syncTime(item.last_synced_at)}</p>
            {item.last_event_at && <p>最近通话事件：{syncTime(item.last_event_at)}</p>}
            <SyncCoverageDetails coverage={item.coverage} />
            {actionNotice?.employeeId === item.employee_id && <p className={actionNotice.failed ? 'sales-phone-error' : 'sales-sync-success'} role="status">{actionNotice.text}</p>}
            {item.binding_conflict ? <p className="sales-phone-error">同一分机绑定了多个员工，请管理员核对归属后处理。</p> : item.last_error ? <p className="sales-phone-error">{item.last_error}</p> : !healthy && <p>{item.message || '请销售连接自己的电话账号，并检查同步状态。'}</p>}
            {mine && !item.binding_conflict ? <div className="sales-sync-buttons">{(!healthy || !item.connected) && <Button type="button" size="sm" variant="outline" disabled={!!busy || loading || error} onClick={() => void runAction(item, 'connect')}>{item.connected || item.needs_reconnect ? '重新连接我的账号' : '连接我的RingCentral'}</Button>}{item.connected && !item.needs_reconnect && <><Button type="button" size="sm" variant="outline" disabled={!!busy || loading || error} onClick={() => void runAction(item, 'sync')}>{busy === 'sync' ? '正在补同步…' : '补同步我的通话'}</Button>{!item.realtime_sync_enabled && <Button type="button" size="sm" variant="outline" disabled={!!busy || loading || error} onClick={() => void runAction(item, 'repair')}>{busy === 'repair' ? '正在修复…' : '修复实时同步并补同步'}</Button>}</>}</div> : !healthy && <p className="sales-phone-help">请该销售登录自己的CRM账号处理；主管不能代替授权或补同步。</p>}
          </article>;
        })}</div>}
        <p className="sales-phone-footnote">以上按北京时间核对最近{periodDays}个自然日；重新绑定前的期间不会算作新绑定凭据。未核验区间与0条记录都不能证明没有拨打。真实员工授权及受控通话仍需逐人现场验收。</p>
      </div>
    </details>
    {(error || attention > 0) && <p className="sales-phone-summary-warning" role="status"><span>{error ? '电话连接状态暂不可用' : `${attention} 位销售的电话接入需处理`}，通话统计可能不完整。展开查看详情。</span>{error && <Button type="button" size="sm" variant="outline" disabled={loading} onClick={retry}>重新读取状态</Button>}</p>}
  </section>;
}
