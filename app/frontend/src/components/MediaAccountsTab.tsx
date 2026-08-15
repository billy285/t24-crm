import { useCallback, useEffect, useRef, useState } from 'react';
import { client } from '../lib/api';
import { useRole } from '../lib/role-context';
import { logOperation } from '../lib/operation-log-helper';
import { invokeWithAuth } from '../lib/tokenStore';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Textarea } from '@/components/ui/textarea';
import { NativeSelect } from '@/components/ui/native-select';
import ConfirmDialog from './ConfirmDialog';
import { toast } from 'sonner';
import { AlertTriangle, Plus, Edit, Trash2, Eye, EyeOff, ExternalLink, RefreshCw } from 'lucide-react';

const platformOptions = [
  { value: 'Facebook', label: 'Facebook' },
  { value: 'Instagram', label: 'Instagram' },
  { value: 'Google Business', label: 'Google Business' },
  { value: 'Yelp', label: 'Yelp' },
  { value: 'TikTok', label: 'TikTok' },
  { value: 'Twitter', label: 'Twitter/X' },
  { value: 'YouTube', label: 'YouTube' },
  { value: 'LinkedIn', label: 'LinkedIn' },
  { value: 'WeChat', label: '微信公众号' },
  { value: 'XiaoHongShu', label: '小红书' },
  { value: 'Other', label: '其他' },
];

const statusOptions = [
  { value: 'active', label: '正常' },
  { value: 'suspended', label: '暂停' },
  { value: 'disabled', label: '已禁用' },
  { value: 'pending', label: '待激活' },
];

const statusColors: Record<string, string> = {
  active: 'bg-green-100 text-green-700',
  suspended: 'bg-amber-100 text-amber-700',
  disabled: 'bg-red-100 text-red-700',
  pending: 'bg-slate-100 text-slate-600',
};

interface Props {
  customerId: number;
  customerName: string;
}

const emptyForm = {
  platform_name: 'Facebook',
  account_name: '',
  login_email: '',
  login_password: '',
  bound_phone: '',
  profile_url: '',
  account_status: 'active',
  notes: '',
};

export default function MediaAccountsTab({ customerId, customerName }: Props) {
  const { employee, canViewPassword, hasPermission } = useRole();
  const canCreate = hasPermission('media_account_create');
  const canEdit = hasPermission('media_account_edit');
  const canDelete = hasPermission('media_account_delete');
  const [accounts, setAccounts] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editingHasPassword, setEditingHasPassword] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<any>(null);
  const [deleting, setDeleting] = useState(false);
  const [visiblePasswords, setVisiblePasswords] = useState<Record<number, string>>({});
  const [revealingId, setRevealingId] = useState<number | null>(null);
  const activeCustomerIdRef = useRef<number | null>(customerId);
  const accountsLoadSeqRef = useRef(0);
  const accountsAbortRef = useRef<AbortController | null>(null);
  const passwordRequestSeqRef = useRef(0);
  const passwordAbortRef = useRef<AbortController | null>(null);

  const loadAccounts = useCallback(async (targetCustomerId: number) => {
    const requestSeq = ++accountsLoadSeqRef.current;
    accountsAbortRef.current?.abort();
    const abortController = new AbortController();
    accountsAbortRef.current = abortController;
    setLoading(true);
    setLoadError('');
    try {
      const res = await invokeWithAuth({
        url: '/api/v1/entities/media_accounts',
        method: 'GET',
        data: {
          query: JSON.stringify({ customer_id: targetCustomerId }),
          sort: '-created_at',
          limit: 100,
        },
        options: { signal: abortController.signal },
      });
      if (
        abortController.signal.aborted
        || accountsLoadSeqRef.current !== requestSeq
        || activeCustomerIdRef.current !== targetCustomerId
      ) return;
      setAccounts(res?.data?.items || []);
      setVisiblePasswords({});
    } catch (err) {
      if (!abortController.signal.aborted && activeCustomerIdRef.current === targetCustomerId) {
        console.error(err);
        setLoadError('媒体账号加载失败，请重试');
      }
    } finally {
      if (accountsLoadSeqRef.current === requestSeq && activeCustomerIdRef.current === targetCustomerId) {
        setLoading(false);
        if (accountsAbortRef.current === abortController) accountsAbortRef.current = null;
      }
    }
  }, []);

  useEffect(() => {
    activeCustomerIdRef.current = customerId;
    accountsLoadSeqRef.current += 1;
    passwordRequestSeqRef.current += 1;
    accountsAbortRef.current?.abort();
    passwordAbortRef.current?.abort();
    accountsAbortRef.current = null;
    passwordAbortRef.current = null;

    // Never leave the previous customer's accounts, password, or draft visible
    // while the next customer's request is still in flight.
    setAccounts([]);
    setLoadError('');
    setVisiblePasswords({});
    setForm(emptyForm);
    setDeleteTarget(null);
    setShowForm(false);
    setEditingId(null);
    setEditingHasPassword(false);
    setRevealingId(null);
    setSaving(false);
    setDeleting(false);
    setLoading(true);
    void loadAccounts(customerId);

    return () => {
      if (activeCustomerIdRef.current === customerId) activeCustomerIdRef.current = null;
      accountsLoadSeqRef.current += 1;
      passwordRequestSeqRef.current += 1;
      accountsAbortRef.current?.abort();
      passwordAbortRef.current?.abort();
    };
  }, [customerId, loadAccounts]);

  const openCreate = () => {
    if (!canCreate) {
      toast.error('您没有新增媒体账号的权限');
      return;
    }
    setForm(emptyForm);
    setEditingId(null);
    setEditingHasPassword(false);
    setShowForm(true);
  };

  const openEdit = (a: any) => {
    if (!canEdit || !accounts.some(account => account.id === a.id)) {
      toast.error('您没有编辑媒体账号的权限');
      return;
    }
    setForm({
      platform_name: a.platform_name || 'Facebook',
      account_name: a.account_name || '',
      login_email: a.login_email || '',
      // Never prefill the real password back into the form.
      login_password: '',
      bound_phone: a.bound_phone || '',
      profile_url: a.profile_url || '',
      account_status: a.account_status || 'active',
      notes: a.notes || '',
    });
    setEditingId(a.id);
    setEditingHasPassword(Boolean(a.has_password));
    setShowForm(true);
  };

  const handleSave = async () => {
    const targetCustomerId = customerId;
    const targetEditingId = editingId;
    if ((targetEditingId && !canEdit) || (!targetEditingId && !canCreate)) {
      toast.error('您没有保存媒体账号的权限');
      return;
    }
    if (!form.platform_name || !form.account_name) {
      toast.error('请填写平台名称和账号名');
      return;
    }
    setSaving(true);
    try {
      const now = new Date().toISOString();
      const operatorName = employee?.name || '管理员';
      if (targetEditingId) {
        await client.entities.media_accounts.update({
          id: String(targetEditingId),
          data: { ...form, updated_at: now },
        });
        if (activeCustomerIdRef.current !== targetCustomerId) return;
        toast.success('媒体账号已更新');
        logOperation({
          customerId: targetCustomerId,
          actionType: 'edit_media_account',
          actionDetail: `编辑媒体账号: ${form.platform_name} - ${form.account_name}`,
          operatorName,
        });
      } else {
        await client.entities.media_accounts.create({
          data: { ...form, customer_id: targetCustomerId, created_at: now, updated_at: now },
        });
        if (activeCustomerIdRef.current !== targetCustomerId) return;
        toast.success('媒体账号已添加');
        logOperation({
          customerId: targetCustomerId,
          actionType: 'create_media_account',
          actionDetail: `新增媒体账号: ${form.platform_name} - ${form.account_name}`,
          operatorName,
        });
      }
      setShowForm(false);
      setEditingId(null);
      await loadAccounts(targetCustomerId);
    } catch (err) {
      if (activeCustomerIdRef.current === targetCustomerId) {
        toast.error('保存失败');
        console.error(err);
      }
    } finally {
      if (activeCustomerIdRef.current === targetCustomerId) setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget || !canDelete) {
      if (!canDelete) toast.error('您没有删除媒体账号的权限');
      return;
    }
    const targetCustomerId = customerId;
    const targetAccount = deleteTarget;
    setDeleting(true);
    try {
      await client.entities.media_accounts.delete({ id: String(targetAccount.id) });
      if (activeCustomerIdRef.current !== targetCustomerId) return;
      toast.success('媒体账号已删除');
      const operatorName = employee?.name || '管理员';
      logOperation({
        customerId: targetCustomerId,
        actionType: 'delete_media_account',
        actionDetail: `删除媒体账号: ${targetAccount.platform_name} - ${targetAccount.account_name}`,
        operatorName,
      });
      setDeleteTarget(null);
      await loadAccounts(targetCustomerId);
    } catch (err) {
      if (activeCustomerIdRef.current === targetCustomerId) {
        toast.error('删除失败');
        console.error(err);
      }
    } finally {
      if (activeCustomerIdRef.current === targetCustomerId) setDeleting(false);
    }
  };

  const togglePassword = async (id: number) => {
    if (!canViewPassword) {
      toast.error('您没有查看密码的权限');
      return;
    }

    const targetCustomerId = customerId;
    const account = accounts.find(item => item.id === id);
    if (!account) return;

    if (visiblePasswords[id]) {
      setVisiblePasswords(previous => {
        const nextPasswords = { ...previous };
        delete nextPasswords[id];
        return nextPasswords;
      });
      return;
    }

    const requestSeq = ++passwordRequestSeqRef.current;
    passwordAbortRef.current?.abort();
    const abortController = new AbortController();
    passwordAbortRef.current = abortController;
    setRevealingId(id);
    try {
      const response = await invokeWithAuth({
        url: `/api/v1/entities/media_accounts/${id}/password`,
        method: 'GET',
        options: { signal: abortController.signal },
      });
      if (
        abortController.signal.aborted
        || passwordRequestSeqRef.current !== requestSeq
        || activeCustomerIdRef.current !== targetCustomerId
      ) return;
      const password = response?.data?.login_password || '';
      setVisiblePasswords(prev => ({ ...prev, [id]: password }));
    } catch (err: any) {
      if (!abortController.signal.aborted && activeCustomerIdRef.current === targetCustomerId) {
        const detail = err?.data?.detail || err?.response?.data?.detail || err?.message || '查看密码失败';
        toast.error(detail);
      }
    } finally {
      if (passwordRequestSeqRef.current === requestSeq && activeCustomerIdRef.current === targetCustomerId) {
        setRevealingId(null);
        if (passwordAbortRef.current === abortController) passwordAbortRef.current = null;
      }
    }
  };

  if (loading) {
    return <div className="flex items-center justify-center py-8"><div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-600" /></div>;
  }

  if (loadError) {
    return (
      <div role="alert" className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
        <div className="flex min-w-0 items-start gap-2">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="min-w-0 flex-1">
            <p className="font-medium">{loadError}</p>
            <p className="mt-1 break-all text-xs text-amber-700">未显示“暂无账号”，以免把 {customerName} 的网络失败误认为没有数据。</p>
          </div>
        </div>
        <Button
          size="sm"
          variant="outline"
          className="mt-3 min-h-11 border-amber-300 bg-white text-amber-800 hover:bg-amber-100 md:min-h-0"
          onClick={() => void loadAccounts(customerId)}
        >
          <RefreshCw className="mr-1 h-3.5 w-3.5" /> 重新加载
        </Button>
      </div>
    );
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between gap-3">
        <span className="text-sm font-medium text-slate-600">媒体账号管理</span>
        {canCreate && (
          <Button size="sm" onClick={openCreate} className="min-h-11 shrink-0 bg-blue-600 hover:bg-blue-700 md:min-h-0">
            <Plus className="w-3.5 h-3.5 mr-1" /> 新增账号
          </Button>
        )}
      </div>

      {showForm && (editingId ? canEdit : canCreate) && (
        <div className="mb-4 p-4 border border-blue-200 bg-blue-50/50 rounded-lg space-y-3">
          <span className="text-sm font-medium text-blue-700">{editingId ? '编辑媒体账号' : '新增媒体账号'}</span>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <Label className="text-xs">平台 *</Label>
              <NativeSelect value={form.platform_name} onChange={v => setForm({ ...form, platform_name: v })} options={platformOptions} />
            </div>
            <div>
              <Label className="text-xs">账号名 *</Label>
              <Input value={form.account_name} onChange={e => setForm({ ...form, account_name: e.target.value })} placeholder="账号名称/用户名" />
            </div>
            <div>
              <Label className="text-xs">登录邮箱</Label>
              <Input value={form.login_email} onChange={e => setForm({ ...form, login_email: e.target.value })} placeholder="登录邮箱" />
            </div>
            <div>
              <Label className="text-xs">登录密码</Label>
              <Input
                type="password"
                value={form.login_password}
                onChange={e => setForm({ ...form, login_password: e.target.value })}
                placeholder={editingId && editingHasPassword ? '留空则保留原密码，填写则更新' : '登录密码'}
              />
              {editingId && editingHasPassword && <p className="text-[11px] text-slate-500 mt-1">当前密码已安全保存，如不修改可直接留空。</p>}
            </div>
            <div>
              <Label className="text-xs">绑定手机号</Label>
              <Input value={form.bound_phone} onChange={e => setForm({ ...form, bound_phone: e.target.value })} placeholder="绑定手机号" />
            </div>
            <div>
              <Label className="text-xs">主页链接</Label>
              <Input value={form.profile_url} onChange={e => setForm({ ...form, profile_url: e.target.value })} placeholder="https://..." />
            </div>
            <div>
              <Label className="text-xs">账号状态</Label>
              <NativeSelect value={form.account_status} onChange={v => setForm({ ...form, account_status: v })} options={statusOptions} />
            </div>
          </div>
          <div>
            <Label className="text-xs">备注</Label>
            <Textarea value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} rows={2} placeholder="备注信息..." />
          </div>
          <div className="sticky bottom-0 -mx-4 -mb-4 flex gap-2 border-t border-blue-200 bg-white/95 px-4 py-3 backdrop-blur sm:static sm:m-0 sm:justify-end sm:border-0 sm:bg-transparent sm:p-0">
            <Button variant="outline" size="sm" className="min-h-11 flex-1 sm:flex-none md:min-h-0" onClick={() => { setShowForm(false); setEditingId(null); }}>取消</Button>
            <Button size="sm" onClick={handleSave} disabled={saving} className="min-h-11 flex-1 bg-blue-600 hover:bg-blue-700 sm:flex-none md:min-h-0">
              {saving ? '保存中...' : editingId ? '更新' : '保存'}
            </Button>
          </div>
        </div>
      )}

      {accounts.length === 0 && !showForm ? (
        <p className="text-sm text-slate-400 text-center py-8">
          {canCreate ? '暂无媒体账号，点击上方按钮添加' : '暂无媒体账号'}
        </p>
      ) : (
        <div className="space-y-3">
          {accounts.map((a: any) => (
            <div key={a.id} className="group rounded-xl border border-slate-200 bg-slate-50 p-3">
              <div className="mb-2 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                  <span className="font-medium text-sm">{a.platform_name}</span>
                  <span className="min-w-0 truncate text-sm text-slate-500">@{a.account_name}</span>
                  <Badge className={`text-xs ${statusColors[a.account_status] || 'bg-slate-100 text-slate-600'}`}>
                    {statusOptions.find(o => o.value === a.account_status)?.label || a.account_status}
                  </Badge>
                </div>
                <div className="grid grid-cols-3 gap-1 opacity-100 transition-opacity sm:flex md:opacity-0 md:group-focus-within:opacity-100 md:group-hover:opacity-100">
                  {a.profile_url && (
                    <Button aria-label={`打开${a.platform_name}主页`} size="sm" variant="ghost" className="h-11 min-w-11 p-0 text-slate-500 hover:text-blue-600 md:h-7 md:min-w-7 md:w-7" onClick={() => window.open(a.profile_url, '_blank', 'noopener,noreferrer')}>
                      <ExternalLink className="w-3.5 h-3.5" />
                    </Button>
                  )}
                  {canEdit && (
                    <Button aria-label={`编辑媒体账号：${a.account_name}`} size="sm" variant="ghost" className="h-11 min-w-11 p-0 text-slate-500 hover:text-blue-600 md:h-7 md:min-w-7 md:w-7" onClick={() => openEdit(a)}>
                      <Edit className="w-3.5 h-3.5" />
                    </Button>
                  )}
                  {canDelete && (
                    <Button aria-label={`删除媒体账号：${a.account_name}`} size="sm" variant="ghost" className="h-11 min-w-11 p-0 text-slate-500 hover:text-red-600 md:h-7 md:min-w-7 md:w-7" onClick={() => setDeleteTarget(a)}>
                      <Trash2 className="w-3.5 h-3.5" />
                    </Button>
                  )}
                </div>
              </div>
              <div className="grid grid-cols-1 gap-2 text-xs text-slate-500 sm:grid-cols-2 sm:gap-1">
                {a.login_email && <span className="min-w-0 break-all">邮箱: {a.login_email}</span>}
                {a.has_password && (
                  <span className="flex min-w-0 flex-wrap items-center gap-1">
                    <span className="min-w-0 break-all">密码: {visiblePasswords[a.id] || '••••••••'}</span>
                    {canViewPassword && (
                      <button
                        type="button"
                        aria-label={visiblePasswords[a.id] ? `隐藏${a.account_name}的密码` : `查看${a.account_name}的密码`}
                        onClick={() => togglePassword(a.id)}
                        className="-my-3 inline-flex h-11 w-11 items-center justify-center rounded-lg text-slate-500 hover:bg-white hover:text-blue-600 disabled:opacity-60 md:-my-1.5 md:h-7 md:w-7"
                        disabled={revealingId === a.id}
                      >
                        {visiblePasswords[a.id] ? <EyeOff className="w-3 h-3" /> : <Eye className="w-3 h-3" />}
                      </button>
                    )}
                  </span>
                )}
                {a.bound_phone && <span className="min-w-0 break-all">手机: {a.bound_phone}</span>}
                {a.profile_url && <span className="min-w-0 break-all">链接: {a.profile_url}</span>}
                {a.notes && <span className="min-w-0 break-all sm:col-span-2">备注: {a.notes}</span>}
              </div>
            </div>
          ))}
        </div>
      )}

      {canDelete && (
        <ConfirmDialog
          open={!!deleteTarget}
          onOpenChange={(v) => { if (!v) setDeleteTarget(null); }}
          title="确认删除媒体账号"
          description={`确定要删除 ${deleteTarget?.platform_name} 账号「${deleteTarget?.account_name}」吗？此操作不可撤销。`}
          onConfirm={handleDelete}
          loading={deleting}
        />
      )}
    </div>
  );
}
