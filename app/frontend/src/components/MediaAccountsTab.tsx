import { useState, useEffect } from 'react';
import { client } from '../lib/api';
import { useRole } from '../lib/role-context';
import { logOperation } from '../lib/operation-log-helper';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Textarea } from '@/components/ui/textarea';
import { NativeSelect } from '@/components/ui/native-select';
import ConfirmDialog from './ConfirmDialog';
import { toast } from 'sonner';
import { Plus, Edit, Trash2, Eye, EyeOff, ExternalLink } from 'lucide-react';

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
  const { role, employee, hasPermission, canViewPassword } = useRole();
  const [accounts, setAccounts] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<any>(null);
  const [deleting, setDeleting] = useState(false);
  const [visiblePasswords, setVisiblePasswords] = useState<Set<number>>(new Set());

  useEffect(() => {
    loadAccounts();
  }, [customerId]);

  const loadAccounts = async () => {
    try {
      const res = await client.entities.media_accounts.query({
        query: { customer_id: customerId },
        sort: '-created_at',
        limit: 100,
      });
      setAccounts(res?.data?.items || []);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const openCreate = () => {
    setForm(emptyForm);
    setEditingId(null);
    setShowForm(true);
  };

  const openEdit = (a: any) => {
    setForm({
      platform_name: a.platform_name || 'Facebook',
      account_name: a.account_name || '',
      login_email: a.login_email || '',
      login_password: a.login_password || '',
      bound_phone: a.bound_phone || '',
      profile_url: a.profile_url || '',
      account_status: a.account_status || 'active',
      notes: a.notes || '',
    });
    setEditingId(a.id);
    setShowForm(true);
  };

  const handleSave = async () => {
    if (!form.platform_name || !form.account_name) {
      toast.error('请填写平台名称和账号名');
      return;
    }
    setSaving(true);
    try {
      const now = new Date().toISOString();
      const operatorName = employee?.name || '管理员';
      if (editingId) {
        await client.entities.media_accounts.update({
          id: String(editingId),
          data: { ...form, updated_at: now },
        });
        toast.success('媒体账号已更新');
        logOperation({
          customerId,
          actionType: 'edit_media_account',
          actionDetail: `编辑媒体账号: ${form.platform_name} - ${form.account_name}`,
          operatorName,
        });
      } else {
        await client.entities.media_accounts.create({
          data: { ...form, customer_id: customerId, created_at: now, updated_at: now },
        });
        toast.success('媒体账号已添加');
        logOperation({
          customerId,
          actionType: 'create_media_account',
          actionDetail: `新增媒体账号: ${form.platform_name} - ${form.account_name}`,
          operatorName,
        });
      }
      setShowForm(false);
      setEditingId(null);
      loadAccounts();
    } catch (err) {
      toast.error('保存失败');
      console.error(err);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await client.entities.media_accounts.delete({ id: String(deleteTarget.id) });
      toast.success('媒体账号已删除');
      const operatorName = employee?.name || '管理员';
      logOperation({
        customerId,
        actionType: 'delete_media_account',
        actionDetail: `删除媒体账号: ${deleteTarget.platform_name} - ${deleteTarget.account_name}`,
        operatorName,
      });
      setDeleteTarget(null);
      loadAccounts();
    } catch (err) {
      toast.error('删除失败');
      console.error(err);
    } finally {
      setDeleting(false);
    }
  };

  const togglePassword = (id: number) => {
    if (!canViewPassword) {
      toast.error('您没有查看密码的权限');
      return;
    }
    const newSet = new Set(visiblePasswords);
    if (newSet.has(id)) {
      newSet.delete(id);
    } else {
      newSet.add(id);
      const operatorName = employee?.name || '管理员';
      logOperation({
        customerId,
        actionType: 'view_password',
        actionDetail: `查看媒体账号密码: ${accounts.find(a => a.id === id)?.platform_name || ''} - ${accounts.find(a => a.id === id)?.account_name || ''}`,
        operatorName,
      });
    }
    setVisiblePasswords(newSet);
  };

  if (loading) {
    return <div className="flex items-center justify-center py-8"><div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-600" /></div>;
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <span className="text-sm font-medium text-slate-600">媒体账号管理</span>
        <Button size="sm" onClick={openCreate} className="bg-blue-600 hover:bg-blue-700">
          <Plus className="w-3.5 h-3.5 mr-1" /> 新增账号
        </Button>
      </div>

      {showForm && (
        <div className="mb-4 p-4 border border-blue-200 bg-blue-50/50 rounded-lg space-y-3">
          <span className="text-sm font-medium text-blue-700">{editingId ? '编辑媒体账号' : '新增媒体账号'}</span>
          <div className="grid grid-cols-2 gap-3">
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
              <Input type="password" value={form.login_password} onChange={e => setForm({ ...form, login_password: e.target.value })} placeholder="登录密码" />
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
          <div className="flex justify-end gap-2">
            <Button variant="outline" size="sm" onClick={() => { setShowForm(false); setEditingId(null); }}>取消</Button>
            <Button size="sm" onClick={handleSave} disabled={saving} className="bg-blue-600 hover:bg-blue-700">
              {saving ? '保存中...' : editingId ? '更新' : '保存'}
            </Button>
          </div>
        </div>
      )}

      {accounts.length === 0 && !showForm ? (
        <p className="text-sm text-slate-400 text-center py-8">暂无媒体账号，点击上方按钮添加</p>
      ) : (
        <div className="space-y-3">
          {accounts.map((a: any) => (
            <div key={a.id} className="p-3 bg-slate-50 rounded-lg group">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-sm">{a.platform_name}</span>
                  <span className="text-slate-500 text-sm">@{a.account_name}</span>
                  <Badge className={`text-xs ${statusColors[a.account_status] || 'bg-slate-100 text-slate-600'}`}>
                    {statusOptions.find(o => o.value === a.account_status)?.label || a.account_status}
                  </Badge>
                </div>
                <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  {a.profile_url && (
                    <Button size="sm" variant="ghost" className="h-7 w-7 p-0 text-slate-400 hover:text-blue-600" onClick={() => window.open(a.profile_url, '_blank')}>
                      <ExternalLink className="w-3.5 h-3.5" />
                    </Button>
                  )}
                  <Button size="sm" variant="ghost" className="h-7 w-7 p-0 text-slate-400 hover:text-blue-600" onClick={() => openEdit(a)}>
                    <Edit className="w-3.5 h-3.5" />
                  </Button>
                  <Button size="sm" variant="ghost" className="h-7 w-7 p-0 text-slate-400 hover:text-red-600" onClick={() => setDeleteTarget(a)}>
                    <Trash2 className="w-3.5 h-3.5" />
                  </Button>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-1 text-xs text-slate-500">
                {a.login_email && <span>邮箱: {a.login_email}</span>}
                {a.login_password && (
                  <span className="flex items-center gap-1">
                    密码: {visiblePasswords.has(a.id) ? a.login_password : '••••••••'}
                    <button onClick={() => togglePassword(a.id)} className="text-slate-400 hover:text-blue-600">
                      {visiblePasswords.has(a.id) ? <EyeOff className="w-3 h-3" /> : <Eye className="w-3 h-3" />}
                    </button>
                  </span>
                )}
                {a.bound_phone && <span>手机: {a.bound_phone}</span>}
                {a.profile_url && <span className="truncate">链接: {a.profile_url}</span>}
                {a.notes && <span className="col-span-2">备注: {a.notes}</span>}
              </div>
            </div>
          ))}
        </div>
      )}

      <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(v) => { if (!v) setDeleteTarget(null); }}
        title="确认删除媒体账号"
        description={`确定要删除 ${deleteTarget?.platform_name} 账号「${deleteTarget?.account_name}」吗？此操作不可撤销。`}
        onConfirm={handleDelete}
        loading={deleting}
      />
    </div>
  );
}