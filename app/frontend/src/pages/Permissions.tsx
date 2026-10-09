import { useUnsavedChanges } from '@/lib/use-unsaved-changes';
import './admin-workspace.css';
import { useState, useEffect, useRef, useMemo } from 'react';
import { useRole } from '../lib/role-context';
import {
  type SystemRole, type ButtonPermission, type DataScope, type RolePermissionConfig,
  systemRoleLabels, buttonPermissionLabels, dataScopeLabels, pageLabels,
  loadRolePermissions, normalizeRolePermissions, defaultRolePermissions,
} from '../lib/permissions';
import { loadRemoteAppConfig, saveRemoteAppConfig } from '../lib/app-config';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { toast } from 'sonner';
import { ShieldCheck, Save, RotateCcw, Eye, MousePointerClick, Database, Lock } from 'lucide-react';
import { logOperation } from '../lib/operation-log-helper';
import { useIsMobile } from '@/hooks/use-mobile';

const allPages = Object.entries(pageLabels).map(([path, label]) => ({ path, label }));
const allButtons = Object.entries(buttonPermissionLabels).map(([key, label]) => ({ key: key as ButtonPermission, label }));
const roles = Object.keys(systemRoleLabels) as SystemRole[];

// Group buttons by category
const buttonGroups: { label: string; buttons: ButtonPermission[] }[] = [
  { label: '客户管理', buttons: ['customer_create', 'customer_edit', 'customer_delete', 'customer_export', 'customer_assign', 'customer_transfer'] },
  { label: '跟进记录', buttons: ['follow_up_create', 'follow_up_edit', 'follow_up_delete'] },
  { label: '成交管理', buttons: ['deal_create', 'deal_edit'] },
  { label: '财务管理', buttons: ['payment_create', 'payment_edit'] },
  { label: '任务管理', buttons: ['task_create', 'task_edit', 'task_delete'] },
  { label: '媒体账号', buttons: ['media_account_create', 'media_account_edit', 'media_account_delete'] },
  { label: '员工管理', buttons: ['employee_create', 'employee_edit', 'employee_disable', 'employee_reset_password'] },
  { label: '系统设置', buttons: ['settings_edit', 'permission_edit'] },
];

export default function Permissions() {
  const { isAdmin, employee } = useRole();
  const isMobile = useIsMobile();
  const [config, setConfig] = useState<Record<SystemRole, RolePermissionConfig>>(defaultRolePermissions);
  const [selectedRole, setSelectedRole] = useState<SystemRole>('sales');
  const [changed, setChanged] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const saveLock = useRef(false);
  const [baseline, setBaseline] = useState(defaultRolePermissions);
  const [configLoadError, setConfigLoadError] = useState(false);
  const [reloadVersion, setReloadVersion] = useState(0);
  const changeSummary = useMemo(() => roles.flatMap(role => {
    const before = baseline[role]; const after = config[role];
    if (JSON.stringify(before) === JSON.stringify(after)) return [];
    const pagesAdded = after.pages.filter(item => !before.pages.includes(item));
    const pagesRemoved = before.pages.filter(item => !after.pages.includes(item));
    const buttonsAdded = after.buttons.filter(item => !before.buttons.includes(item));
    const buttonsRemoved = before.buttons.filter(item => !after.buttons.includes(item));
    const details = [
      ...pagesAdded.map(item => `允许访问：${pageLabels[item] || item}`), ...pagesRemoved.map(item => `取消访问：${pageLabels[item] || item}`),
      ...buttonsAdded.map(item => `允许操作：${buttonPermissionLabels[item] || item}`), ...buttonsRemoved.map(item => `取消操作：${buttonPermissionLabels[item] || item}`),
      ...(before.dataScope !== after.dataScope ? [`数据范围：${dataScopeLabels[before.dataScope]} → ${dataScopeLabels[after.dataScope]}`] : []),
      ...Object.keys(after.sensitiveFields).filter(key => before.sensitiveFields[key as keyof typeof before.sensitiveFields] !== after.sensitiveFields[key as keyof typeof after.sensitiveFields]).map(key => `${({ viewPassword: '查看媒体密码', copyPassword: '复制媒体密码', viewFinance: '查看财务信息' } as Record<string, string>)[key] || key}：${after.sensitiveFields[key as keyof typeof after.sensitiveFields] ? '允许' : '禁止'}`),
    ];
    return [{ role, details }];
  }), [baseline, config]);
  const permissionDraft = useUnsavedChanges(changeSummary.length > 0);

  useEffect(() => {
    if (!isAdmin) { setLoading(false); return; }

    let active = true;
    const loadConfig = async () => {
      setLoading(true);
      try {
        const remote = await loadRemoteAppConfig('role_permissions', defaultRolePermissions);
        if (active) {
          const next = normalizeRolePermissions(remote); setConfig(next); setBaseline(next); setConfigLoadError(false);
        }
      } catch {
        if (active) {
          const cached = loadRolePermissions(); setConfig(cached); setBaseline(cached); setConfigLoadError(true);
          toast.error('加载权限配置失败，已回退到本地缓存');
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    };

    void loadConfig();
    return () => {
      active = false;
    };
  }, [isAdmin, reloadVersion]);

  if (!isAdmin) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-center">
        <Lock className="w-12 h-12 text-slate-300 mb-4" />
        <p className="text-slate-400">仅管理员可访问权限设置</p>
      </div>
    );
  }

  if (loading) {
    return <div className="flex h-64 items-center justify-center"><div className="h-8 w-8 animate-spin rounded-full border-b-2 border-blue-600" /></div>;
  }

  const currentPerms = config[selectedRole];
  if (isMobile) return <div className="app-page space-y-4" data-testid="mobile-permission-summary">
    <div className="flex items-center justify-between gap-3"><h2 className="app-page-heading">权限管理</h2><Badge variant="secondary">只读摘要</Badge></div>
    {configLoadError && <div role="alert" className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">当前为缓存摘要，尚未核实最新权限。<Button variant="outline" className="mt-2" onClick={() => setReloadVersion(value => value + 1)}>重新读取</Button></div>}
    <p className="text-sm text-slate-500">按角色查看访问范围；权限调整在电脑端完成。</p>
    <label className="block text-sm text-slate-600">查看角色<select aria-label="查看角色" value={selectedRole} onChange={event => setSelectedRole(event.target.value as SystemRole)} className="mt-2 min-h-11 w-full rounded-xl border border-slate-200 bg-white px-3 text-slate-900">{roles.map(role => <option key={role} value={role}>{systemRoleLabels[role]}</option>)}</select></label>
    <Card><CardHeader><CardTitle className="text-base">数据与敏感信息</CardTitle></CardHeader><CardContent><dl className="space-y-3 text-sm">{[['数据范围', dataScopeLabels[currentPerms.dataScope]], ['查看媒体密码', currentPerms.sensitiveFields.viewPassword ? '允许' : '禁止'], ['复制媒体密码', currentPerms.sensitiveFields.copyPassword ? '允许' : '禁止'], ['查看财务信息', currentPerms.sensitiveFields.viewFinance ? '允许' : '禁止']].map(([label,value]) => <div key={label} className="flex justify-between gap-3 border-b border-dashed border-slate-100 pb-2"><dt className="text-slate-500">{label}</dt><dd>{value}</dd></div>)}</dl></CardContent></Card>
    <Card><CardHeader><CardTitle className="text-base">可访问页面 · {currentPerms.pages.length}</CardTitle></CardHeader><CardContent><ul className="divide-y divide-slate-100 text-sm">{currentPerms.pages.map(path => <li key={path} className="min-h-11 py-3">{pageLabels[path] || path}</li>)}{!currentPerms.pages.length && <li className="text-slate-500">未开放页面</li>}</ul></CardContent></Card>
    <Card><CardHeader><CardTitle className="text-base">允许操作 · {currentPerms.buttons.length}</CardTitle></CardHeader><CardContent><ul className="divide-y divide-slate-100 text-sm">{currentPerms.buttons.map(key => <li key={key} className="min-h-11 py-3">{buttonPermissionLabels[key] || key}</li>)}{!currentPerms.buttons.length && <li className="text-slate-500">未开放操作</li>}</ul></CardContent></Card>
  </div>;


  const togglePage = (path: string) => {
    const pages = currentPerms.pages.includes(path)
      ? currentPerms.pages.filter(p => p !== path)
      : [...currentPerms.pages, path];
    setConfig({ ...config, [selectedRole]: { ...currentPerms, pages } });
    setChanged(true);
  };

  const toggleButton = (btn: ButtonPermission) => {
    const buttons = currentPerms.buttons.includes(btn)
      ? currentPerms.buttons.filter(b => b !== btn)
      : [...currentPerms.buttons, btn];
    setConfig({ ...config, [selectedRole]: { ...currentPerms, buttons } });
    setChanged(true);
  };

  const setDataScope = (scope: DataScope) => {
    setConfig({ ...config, [selectedRole]: { ...currentPerms, dataScope: scope } });
    setChanged(true);
  };

  const toggleSensitive = (field: keyof RolePermissionConfig['sensitiveFields']) => {
    setConfig({
      ...config,
      [selectedRole]: {
        ...currentPerms,
        sensitiveFields: { ...currentPerms.sensitiveFields, [field]: !currentPerms.sensitiveFields[field] },
      },
    });
    setChanged(true);
  };

  const handleSave = async () => {
    if (saveLock.current || configLoadError) return;
    saveLock.current = true; setSaving(true);
    try {
      const normalized = normalizeRolePermissions(config);
      await saveRemoteAppConfig('role_permissions', normalized);
      setConfig(normalized); setBaseline(normalized); permissionDraft.markSaved();
      setChanged(false);
      toast.success('权限配置已保存');
      const op = employee?.name || '管理员';
      logOperation({ actionType: 'other', actionDetail: `修改角色权限: ${changeSummary.map(item => systemRoleLabels[item.role]).join("、")}；${changeSummary.reduce((count, item) => count + item.details.length, 0)} 项调整`, operatorName: op });
    } catch {
      toast.error('保存权限配置失败');
    } finally { saveLock.current = false; setSaving(false); }
  };

  const handleReset = () => {
    if (saving || !window.confirm('恢复默认会替换所有角色的当前草稿。保存前可以在变更摘要中核对，是否继续？')) return;
    setConfig(normalizeRolePermissions(defaultRolePermissions));
    setChanged(true);
    toast.info('已恢复默认权限配置，请保存');
  };

  return (
    <>
      <div className="t24-settings-page calm-admin-page calm-permissions-page app-page space-y-5">
      <div className="app-page-title"><div>
        <p className="app-page-kicker">T24 Marketing · Access Control</p>
        <h2 className="app-page-heading flex items-center gap-2">
          <ShieldCheck className="w-5 h-5" /> 权限设置
        </h2>
        <p className="app-page-description">配置不同角色的页面、按钮、数据和敏感信息权限。</p>
      </div></div>

      {configLoadError && <div role="alert" className="flex items-center justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800"><span>当前显示缓存配置，重新读取成功后才能保存。</span><Button variant="outline" onClick={() => setReloadVersion(value => value + 1)}>重新读取</Button></div>}
      <fieldset disabled={saving || configLoadError} className="min-w-0 space-y-5 border-0 p-0">
      <div className="calm-permission-role">
        <label htmlFor="permission-role" className="text-sm font-medium text-slate-700">当前配置角色</label>
        <select id="permission-role" value={selectedRole} onChange={event => setSelectedRole(event.target.value as SystemRole)} className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm sm:w-56">{roles.map(role => <option key={role} value={role}>{systemRoleLabels[role]}</option>)}</select>
        <p className="text-xs text-slate-500">按页面、操作和数据范围逐项核对，修改后统一保存。</p>
      </div>

      <Tabs defaultValue="pages" className="w-full">
        <TabsList className="calm-admin-tab-navigation">
          <TabsTrigger value="pages" className="text-xs gap-1"><Eye className="w-3 h-3" /> 页面权限</TabsTrigger>
          <TabsTrigger value="buttons" className="text-xs gap-1"><MousePointerClick className="w-3 h-3" /> 按钮权限</TabsTrigger>
          <TabsTrigger value="data" className="text-xs gap-1"><Database className="w-3 h-3" /> 数据权限</TabsTrigger>
          <TabsTrigger value="sensitive" className="text-xs gap-1"><Lock className="w-3 h-3" /> 敏感信息</TabsTrigger>
        </TabsList>

        {/* Page Permissions */}
        <TabsContent value="pages">
          <Card className="border-slate-200">
            <CardHeader className="pb-3">
              <CardTitle className="text-base">页面访问权限</CardTitle>
              <CardDescription>控制 {systemRoleLabels[selectedRole]} 角色可以访问的页面</CardDescription>
            </CardHeader>
            <CardContent className="calm-page-permissions">
              {allPages.map(p => (
                <div key={p.path} className="flex items-center justify-between p-3 bg-slate-50 rounded-lg">
                  <div className="flex items-center gap-2">
                    <span className="text-sm">{p.label}</span>

                  </div>
                  <Switch
                    aria-label={`${p.label}页面访问`}
                    checked={currentPerms.pages.includes(p.path)}
                    onCheckedChange={() => togglePage(p.path)}
                    disabled={p.path === '/'} // Dashboard always accessible
                  />
                </div>
              ))}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Button Permissions */}
        <TabsContent value="buttons">
          <Card className="border-slate-200">
            <CardHeader className="pb-3">
              <CardTitle className="text-base">按钮操作权限</CardTitle>
              <CardDescription>控制 {systemRoleLabels[selectedRole]} 角色可以执行的操作</CardDescription>
            </CardHeader>
            <CardContent className="calm-button-permissions">
              {buttonGroups.map(group => (
                <details key={group.label} className="calm-permission-group">
                  <summary><span>{group.label}</span><span className="text-xs font-normal text-slate-500">{group.buttons.filter(button => currentPerms.buttons.includes(button)).length} / {group.buttons.length} 已允许</span></summary>
                  <div className="space-y-2 border-t border-slate-200 p-3">
                    {group.buttons.map(btn => (
                      <div key={btn} className="flex items-center justify-between p-2.5 bg-slate-50 rounded-lg">
                        <span className="text-sm">{buttonPermissionLabels[btn]}</span>
                        <Switch
                          aria-label={buttonPermissionLabels[btn]}
                          checked={currentPerms.buttons.includes(btn)}
                          onCheckedChange={() => toggleButton(btn)}
                        />
                      </div>
                    ))}
                  </div>
                </details>
              ))}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Data Scope */}
        <TabsContent value="data">
          <Card className="border-slate-200">
            <CardHeader className="pb-3">
              <CardTitle className="text-base">数据范围权限</CardTitle>
              <CardDescription>控制 {systemRoleLabels[selectedRole]} 角色可以查看的数据范围</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {(['self', 'department', 'all'] as DataScope[]).map(scope => (
                <div
                  key={scope}
                  className={`flex items-center justify-between p-4 rounded-lg border-2 cursor-pointer transition-colors ${
                    currentPerms.dataScope === scope ? 'border-blue-500 bg-blue-50' : 'border-slate-200 bg-slate-50 hover:border-slate-300'
                  }`}
                  onClick={() => setDataScope(scope)}
                >
                  <div>
                    <p className="text-sm font-medium">{dataScopeLabels[scope]}</p>
                    <p className="text-xs text-slate-500">
                      {scope === 'self' && '只能查看自己负责的客户和数据'}
                      {scope === 'department' && '可以查看本部门所有成员的客户和数据'}
                      {scope === 'all' && '可以查看系统中所有客户和数据'}
                    </p>
                  </div>
                  <div className={`w-5 h-5 rounded-full border-2 flex items-center justify-center ${
                    currentPerms.dataScope === scope ? 'border-blue-500 bg-blue-500' : 'border-slate-300'
                  }`}>
                    {currentPerms.dataScope === scope && <div className="w-2 h-2 rounded-full bg-white" />}
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Sensitive Fields */}
        <TabsContent value="sensitive">
          <Card className="border-slate-200">
            <CardHeader className="pb-3">
              <CardTitle className="text-base">敏感信息权限</CardTitle>
              <CardDescription>控制 {systemRoleLabels[selectedRole]} 角色对敏感信息的访问</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex items-center justify-between p-3 bg-slate-50 rounded-lg">
                <div><p className="text-sm font-medium">查看媒体账号密码</p><p className="text-xs text-slate-500">允许查看媒体账号的密码信息</p></div>
                <Switch aria-label="查看媒体账号密码" checked={currentPerms.sensitiveFields.viewPassword} onCheckedChange={() => toggleSensitive('viewPassword')} />
              </div>
              <div className="flex items-center justify-between p-3 bg-slate-50 rounded-lg">
                <div><p className="text-sm font-medium">复制媒体账号密码</p><p className="text-xs text-slate-500">允许复制密码到剪贴板</p></div>
                <Switch aria-label="复制媒体账号密码" checked={currentPerms.sensitiveFields.copyPassword} onCheckedChange={() => toggleSensitive('copyPassword')} />
              </div>
              <div className="flex items-center justify-between p-3 bg-slate-50 rounded-lg">
                <div><p className="text-sm font-medium">查看财务信息</p><p className="text-xs text-slate-500">仅老板、管理员和财务可查看；销售、运营、设计与合伙人固定隔离</p></div>
                <Switch aria-label="查看财务信息" checked={currentPerms.sensitiveFields.viewFinance} disabled={['sales', 'sales_manager', 'sales_partner', 'ops', 'design'].includes(selectedRole)} onCheckedChange={() => toggleSensitive('viewFinance')} />
              </div>
              <div className="mt-4 p-3 bg-amber-50 border border-amber-200 rounded-lg">
                <p className="text-xs text-amber-700">
                  <strong>安全提示:</strong> 查看密码操作会自动记录到操作日志中，便于审计追踪。
                </p>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      </fieldset>
      {changeSummary.length > 0 && <details open className="rounded-xl border border-amber-200 bg-amber-50 p-4"><summary className="cursor-pointer text-sm font-semibold text-amber-900">保存前核对 · {changeSummary.length} 个角色 · {changeSummary.reduce((count, item) => count + item.details.length, 0)} 项变更</summary><div className="mt-3 space-y-3">{changeSummary.map(item => <section key={item.role}><h3 className="text-sm font-semibold">{systemRoleLabels[item.role]}</h3><ul className="mt-1 space-y-1 text-sm text-slate-600">{item.details.map(detail => <li key={detail}>{detail}</li>)}</ul></section>)}</div></details>}
      {/* Save / Reset */}
      <div className="calm-permission-savebar">
        <p className="text-xs text-slate-500" role="status">{changeSummary.length > 0 ? '有未保存的权限调整' : '权限调整将在点击保存后生效'}</p>
        <Button variant="outline" size="sm" disabled={saving || configLoadError} onClick={handleReset}>
          <RotateCcw className="w-3.5 h-3.5 mr-1" /> 恢复默认
        </Button>
        <Button onClick={handleSave} disabled={changeSummary.length === 0 || saving || configLoadError} className="bg-blue-600 hover:bg-blue-700">
          <Save className="w-4 h-4 mr-1" /> {saving ? '保存中…' : '保存权限配置'}
        </Button>
      </div>
      </div>
    </>
  );
}
