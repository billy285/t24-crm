import { useState, useEffect } from 'react';
import { useRole } from '../lib/role-context';
import {
  type SystemRole, type ButtonPermission, type DataScope, type RolePermissionConfig,
  systemRoleLabels, buttonPermissionLabels, dataScopeLabels, pageLabels,
  loadRolePermissions, saveRolePermissions, defaultRolePermissions, PAGE_PATHS,
} from '../lib/permissions';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { toast } from 'sonner';
import { ShieldCheck, Save, RotateCcw, Eye, MousePointerClick, Database, Lock } from 'lucide-react';
import { NativeSelect } from '@/components/ui/native-select';
import { logOperation } from '../lib/operation-log-helper';

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
  { label: '敏感信息', buttons: ['view_password', 'copy_password'] },
  { label: '员工管理', buttons: ['employee_create', 'employee_edit', 'employee_disable', 'employee_reset_password'] },
  { label: '系统设置', buttons: ['settings_edit', 'permission_edit'] },
];

export default function Permissions() {
  const { isAdmin, employee } = useRole();
  const [config, setConfig] = useState<Record<SystemRole, RolePermissionConfig>>(defaultRolePermissions);
  const [selectedRole, setSelectedRole] = useState<SystemRole>('sales');
  const [changed, setChanged] = useState(false);

  useEffect(() => {
    setConfig(loadRolePermissions());
  }, []);

  if (!isAdmin) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-center">
        <Lock className="w-12 h-12 text-slate-300 mb-4" />
        <p className="text-slate-400">仅管理员可访问权限设置</p>
      </div>
    );
  }

  const currentPerms = config[selectedRole];

  const togglePage = (path: string) => {
    const pages = currentPerms.pages.includes(path)
      ? currentPerms.pages.filter(p => p !== path)
      : [...currentPerms.pages, path];
    // Dashboard is always accessible
    if (!pages.includes('/')) pages.unshift('/');
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

  const handleSave = () => {
    saveRolePermissions(config);
    setChanged(false);
    toast.success('权限配置已保存');
    const op = employee?.name || '管理员';
    logOperation({ actionType: 'other', actionDetail: `修改角色权限: ${systemRoleLabels[selectedRole]}`, operatorName: op });
  };

  const handleReset = () => {
    setConfig({ ...defaultRolePermissions });
    setChanged(true);
    toast.info('已恢复默认权限配置，请保存');
  };

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-semibold text-slate-800 flex items-center gap-2">
          <ShieldCheck className="w-5 h-5" /> 权限设置
        </h2>
        <p className="text-sm text-slate-500 mt-1">配置不同角色的页面、按钮、数据和敏感信息权限</p>
      </div>

      {/* Role selector */}
      <div className="flex items-center gap-3 flex-wrap">
        <span className="text-sm text-slate-500">选择角色:</span>
        {roles.map(r => (
          <Button
            key={r}
            variant={selectedRole === r ? 'default' : 'outline'}
            size="sm"
            onClick={() => setSelectedRole(r)}
            className={selectedRole === r ? 'bg-blue-600 hover:bg-blue-700' : ''}
          >
            {systemRoleLabels[r]}
          </Button>
        ))}
      </div>

      <Tabs defaultValue="pages" className="w-full">
        <TabsList className="bg-slate-100 flex-wrap h-auto gap-1 p-1">
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
            <CardContent className="space-y-2">
              {allPages.map(p => (
                <div key={p.path} className="flex items-center justify-between p-3 bg-slate-50 rounded-lg">
                  <div className="flex items-center gap-2">
                    <span className="text-sm">{p.label}</span>
                    <code className="text-xs text-slate-400">{p.path}</code>
                  </div>
                  <Switch
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
            <CardContent className="space-y-6">
              {buttonGroups.map(group => (
                <div key={group.label}>
                  <h4 className="text-sm font-medium text-slate-700 mb-2">{group.label}</h4>
                  <div className="space-y-2">
                    {group.buttons.map(btn => (
                      <div key={btn} className="flex items-center justify-between p-2.5 bg-slate-50 rounded-lg">
                        <span className="text-sm">{buttonPermissionLabels[btn]}</span>
                        <Switch
                          checked={currentPerms.buttons.includes(btn)}
                          onCheckedChange={() => toggleButton(btn)}
                        />
                      </div>
                    ))}
                  </div>
                </div>
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
                <Switch checked={currentPerms.sensitiveFields.viewPassword} onCheckedChange={() => toggleSensitive('viewPassword')} />
              </div>
              <div className="flex items-center justify-between p-3 bg-slate-50 rounded-lg">
                <div><p className="text-sm font-medium">复制媒体账号密码</p><p className="text-xs text-slate-500">允许复制密码到剪贴板</p></div>
                <Switch checked={currentPerms.sensitiveFields.copyPassword} onCheckedChange={() => toggleSensitive('copyPassword')} />
              </div>
              <div className="flex items-center justify-between p-3 bg-slate-50 rounded-lg">
                <div><p className="text-sm font-medium">查看财务信息</p><p className="text-xs text-slate-500">允许查看客户的财务和收款信息</p></div>
                <Switch checked={currentPerms.sensitiveFields.viewFinance} onCheckedChange={() => toggleSensitive('viewFinance')} />
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

      {/* Save / Reset */}
      <div className="flex items-center justify-between pt-2">
        <Button variant="outline" size="sm" onClick={handleReset}>
          <RotateCcw className="w-3.5 h-3.5 mr-1" /> 恢复默认
        </Button>
        <Button onClick={handleSave} disabled={!changed} className="bg-blue-600 hover:bg-blue-700">
          <Save className="w-4 h-4 mr-1" /> 保存权限配置
        </Button>
      </div>
    </div>
  );
}