import { useState, useEffect } from 'react';
import { client } from '../lib/api';
import { useRole, roleLabels, departmentLabels, positionLabels } from '../lib/role-context';
import { systemRoleLabels } from '../lib/permissions';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { toast } from 'sonner';
import { Settings as SettingsIcon, Hash, Eye, RotateCcw, Save, Building2, BookOpen, Shield, Bell, FileText, Download, Lock } from 'lucide-react';
import { NativeSelect } from '@/components/ui/native-select';
import { actionTypeLabels } from '../lib/operation-log-helper';
import { type CustomerCodeSettings, defaultSettings, defaultIndustryPrefixes, loadSettings, saveSettings, previewCode } from '../lib/customer-code-settings';

const industryLabels: Record<string, string> = { restaurant: '餐厅', nail: '美甲', massage: '按摩', beauty: '美容', supermarket: '超市', other: '其他' };

// Local storage keys for settings
const COMPANY_KEY = 'crm_company_info';
const DICT_KEY = 'crm_dict_config';
const DASHBOARD_KEY = 'crm_dashboard_config';
const REMINDER_KEY = 'crm_reminder_config';
const SECURITY_KEY = 'crm_security_config';
const NOTIFICATION_KEY = 'crm_notification_config';
const EXPORT_KEY = 'crm_export_config';

function loadJson(key: string, def: any) { try { const s = localStorage.getItem(key); return s ? JSON.parse(s) : def; } catch { return def; } }
function saveJson(key: string, val: any) { localStorage.setItem(key, JSON.stringify(val)); }

export default function Settings() {
  const { role, isAdmin, hasPermission } = useRole();

  // Customer code settings
  const [codeSettings, setCodeSettings] = useState<CustomerCodeSettings>(defaultSettings);
  const [codeChanged, setCodeChanged] = useState(false);

  // Company info
  const [company, setCompany] = useState({ name: '', address: '', phone: '', email: '', website: '', logo: '', description: '' });
  const [companyChanged, setCompanyChanged] = useState(false);

  // Dictionary config
  const [dictConfig, setDictConfig] = useState({
    industries: 'restaurant:餐厅,nail:美甲,massage:按摩,beauty:美容,supermarket:超市,other:其他',
    statuses: 'new:新线索,following:跟进中,closed:已成交,paused:暂停,lost:流失',
    sources: 'phone:电话销售,referral:转介绍,ads:广告,private:私域,returning:老客户,other:其他',
    levels: 'high:高意向,normal:普通,low:低意向,vip:VIP',
    products: 'ordering_system:线上点餐系统,social_media:新媒体代运营,ads:广告投放,website:网站设计,combo:组合套餐',
    countries: 'US:美国,CA:加拿大,GB:英国,AU:澳大利亚',
  });
  const [dictChanged, setDictChanged] = useState(false);

  // Dashboard config
  const [dashboardConfig, setDashboardConfig] = useState({
    showTotalCustomers: true, showFollowing: true, showClosedMonth: true,
    showExpiring: true, showRevenue: true, showOverdue: true,
    showPendingTasks: true, showLost: true, showReminders: true,
    showRecentCustomers: true, showUpcomingTasks: true,
  });
  const [dashChanged, setDashChanged] = useState(false);

  // Reminder config
  const [reminderConfig, setReminderConfig] = useState({
    enableFollowUpReminder: true, followUpDaysBefore: 0,
    enableExpiryReminder: true, expiryDaysBefore: 30,
    enableNoFollowReminder: true, noFollowDays: 7,
    enableOverduePayment: true, enableDelayedTask: true,
  });
  const [reminderChanged, setReminderChanged] = useState(false);

  // Security config
  const [securityConfig, setSecurityConfig] = useState({
    passwordViewRoles: ['boss'] as string[],
    logPasswordViews: true,
    requireConfirmDelete: true,
    enableSoftDelete: false,
  });
  const [securityChanged, setSecurityChanged] = useState(false);

  // Notification config
  const [notifConfig, setNotifConfig] = useState({
    enableBrowserNotif: false,
    enableEmailNotif: false,
    notifEmail: '',
  });
  const [notifChanged, setNotifChanged] = useState(false);

  // Export config
  const [exportConfig, setExportConfig] = useState({
    exportRoles: ['boss', 'sales'] as string[],
    defaultFormat: 'xlsx',
    includeNotes: true,
    includeSocialLinks: true,
  });
  const [exportChanged, setExportChanged] = useState(false);

  // Operation logs
  const [logs, setLogs] = useState<any[]>([]);
  const [logsLoading, setLogsLoading] = useState(false);

  useEffect(() => {
    setCodeSettings(loadSettings());
    setCompany(loadJson(COMPANY_KEY, company));
    setDictConfig(loadJson(DICT_KEY, dictConfig));
    setDashboardConfig(loadJson(DASHBOARD_KEY, dashboardConfig));
    setReminderConfig(loadJson(REMINDER_KEY, reminderConfig));
    setSecurityConfig(loadJson(SECURITY_KEY, securityConfig));
    setNotifConfig(loadJson(NOTIFICATION_KEY, notifConfig));
    setExportConfig(loadJson(EXPORT_KEY, exportConfig));
  }, []);

  const loadLogs = async () => {
    setLogsLoading(true);
    try {
      const res = await client.entities.operation_logs.query({ sort: '-created_at', limit: 100 });
      setLogs(res?.data?.items || []);
    } catch (err) { console.error(err); }
    finally { setLogsLoading(false); }
  };

  const updateCode = (patch: Partial<CustomerCodeSettings>) => { setCodeSettings(prev => ({ ...prev, ...patch })); setCodeChanged(true); };
  const updateIndustryPrefix = (industry: string, newPrefix: string) => {
    setCodeSettings(prev => ({ ...prev, industryPrefixes: prev.industryPrefixes.map(ip => ip.industry === industry ? { ...ip, prefix: newPrefix.toUpperCase() } : ip) }));
    setCodeChanged(true);
  };

  const saveCodeSettings = () => {
    if (!codeSettings.defaultPrefix.trim()) { toast.error('默认前缀不能为空'); return; }
    saveSettings(codeSettings); setCodeChanged(false); toast.success('编号格式已保存');
  };

  const saveCompany = () => { saveJson(COMPANY_KEY, company); setCompanyChanged(false); toast.success('公司信息已保存'); };
  const saveDict = () => { saveJson(DICT_KEY, dictConfig); setDictChanged(false); toast.success('字典配置已保存'); };
  const saveDash = () => { saveJson(DASHBOARD_KEY, dashboardConfig); setDashChanged(false); toast.success('仪表盘配置已保存'); };
  const saveReminder = () => { saveJson(REMINDER_KEY, reminderConfig); setReminderChanged(false); toast.success('提醒规则已保存'); };
  const saveSecurity = () => { saveJson(SECURITY_KEY, securityConfig); setSecurityChanged(false); toast.success('安全设置已保存'); };
  const saveNotif = () => { saveJson(NOTIFICATION_KEY, notifConfig); setNotifChanged(false); toast.success('通知设置已保存'); };
  const saveExport = () => { saveJson(EXPORT_KEY, exportConfig); setExportChanged(false); toast.success('导出配置已保存'); };

  if (!isAdmin && !hasPermission('settings_edit')) {
    return <div className="flex items-center justify-center h-64"><p className="text-slate-400">仅管理员可访问系统设置</p></div>;
  }

  return (
    <div className="space-y-4">
      <div><h2 className="text-xl font-semibold text-slate-800 flex items-center gap-2"><SettingsIcon className="w-5 h-5" /> 系统设置</h2><p className="text-sm text-slate-500 mt-1">配置系统参数、业务规则和权限</p></div>

      <Tabs defaultValue="company" className="w-full">
        <TabsList className="bg-slate-100 flex-wrap h-auto gap-1 p-1">
          <TabsTrigger value="company" className="text-xs">公司信息</TabsTrigger>
          <TabsTrigger value="dict" className="text-xs">字典配置</TabsTrigger>
          <TabsTrigger value="code" className="text-xs">编号规则</TabsTrigger>
          <TabsTrigger value="dashboard" className="text-xs">仪表盘</TabsTrigger>
          <TabsTrigger value="reminder" className="text-xs">提醒规则</TabsTrigger>
          <TabsTrigger value="security" className="text-xs">安全设置</TabsTrigger>
          <TabsTrigger value="notification" className="text-xs">通知设置</TabsTrigger>
          <TabsTrigger value="export" className="text-xs">导出配置</TabsTrigger>
          <TabsTrigger value="logs" className="text-xs" onClick={loadLogs}>操作日志</TabsTrigger>
        </TabsList>

        {/* Company Info */}
        <TabsContent value="company">
          <Card className="border-slate-200"><CardHeader className="pb-3"><CardTitle className="text-base flex items-center gap-2"><Building2 className="w-4 h-4 text-blue-600" /> 公司基础信息</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div><Label>公司名称</Label><Input value={company.name} onChange={e => { setCompany({ ...company, name: e.target.value }); setCompanyChanged(true); }} placeholder="公司名称" /></div>
              <div><Label>联系电话</Label><Input value={company.phone} onChange={e => { setCompany({ ...company, phone: e.target.value }); setCompanyChanged(true); }} placeholder="联系电话" /></div>
              <div><Label>邮箱</Label><Input value={company.email} onChange={e => { setCompany({ ...company, email: e.target.value }); setCompanyChanged(true); }} placeholder="邮箱" /></div>
              <div><Label>官网</Label><Input value={company.website} onChange={e => { setCompany({ ...company, website: e.target.value }); setCompanyChanged(true); }} placeholder="https://..." /></div>
              <div className="col-span-2"><Label>地址</Label><Input value={company.address} onChange={e => { setCompany({ ...company, address: e.target.value }); setCompanyChanged(true); }} placeholder="公司地址" /></div>
              <div className="col-span-2"><Label>简介</Label><Textarea value={company.description} onChange={e => { setCompany({ ...company, description: e.target.value }); setCompanyChanged(true); }} rows={3} placeholder="公司简介..." /></div>
            </div>
            <div className="flex justify-end"><Button onClick={saveCompany} disabled={!companyChanged} className="bg-blue-600 hover:bg-blue-700"><Save className="w-4 h-4 mr-1" /> 保存</Button></div>
          </CardContent></Card>
        </TabsContent>

        {/* Dictionary Config */}
        <TabsContent value="dict">
          <Card className="border-slate-200"><CardHeader className="pb-3"><CardTitle className="text-base flex items-center gap-2"><BookOpen className="w-4 h-4 text-blue-600" /> 字典配置</CardTitle><CardDescription>配置行业、状态、来源等下拉选项（格式: key:label, 逗号分隔）</CardDescription></CardHeader>
          <CardContent className="space-y-4">
            <div><Label>行业类型</Label><Textarea value={dictConfig.industries} onChange={e => { setDictConfig({ ...dictConfig, industries: e.target.value }); setDictChanged(true); }} rows={2} /></div>
            <div><Label>客户状态</Label><Textarea value={dictConfig.statuses} onChange={e => { setDictConfig({ ...dictConfig, statuses: e.target.value }); setDictChanged(true); }} rows={2} /></div>
            <div><Label>客户来源</Label><Textarea value={dictConfig.sources} onChange={e => { setDictConfig({ ...dictConfig, sources: e.target.value }); setDictChanged(true); }} rows={2} /></div>
            <div><Label>客户等级</Label><Textarea value={dictConfig.levels} onChange={e => { setDictConfig({ ...dictConfig, levels: e.target.value }); setDictChanged(true); }} rows={2} /></div>
            <div><Label>产品类型</Label><Textarea value={dictConfig.products} onChange={e => { setDictConfig({ ...dictConfig, products: e.target.value }); setDictChanged(true); }} rows={2} /></div>
            <div><Label>国家</Label><Textarea value={dictConfig.countries} onChange={e => { setDictConfig({ ...dictConfig, countries: e.target.value }); setDictChanged(true); }} rows={2} /></div>
            <div className="flex justify-end"><Button onClick={saveDict} disabled={!dictChanged} className="bg-blue-600 hover:bg-blue-700"><Save className="w-4 h-4 mr-1" /> 保存</Button></div>
          </CardContent></Card>
        </TabsContent>

        {/* Customer Code */}
        <TabsContent value="code">
          <Card className="border-slate-200"><CardHeader className="pb-3"><CardTitle className="text-base flex items-center gap-2"><Hash className="w-4 h-4 text-blue-600" /> 客户编号格式</CardTitle></CardHeader>
          <CardContent className="space-y-5">
            <div className="flex items-center justify-between p-4 bg-slate-50 rounded-lg">
              <div><Label className="text-sm font-medium">按行业分类前缀</Label><p className="text-xs text-slate-500 mt-0.5">不同行业使用不同前缀</p></div>
              <Switch checked={codeSettings.useIndustryPrefix} onCheckedChange={v => updateCode({ useIndustryPrefix: v })} />
            </div>
            {!codeSettings.useIndustryPrefix && <div><Label>默认前缀</Label><Input value={codeSettings.defaultPrefix} onChange={e => updateCode({ defaultPrefix: e.target.value.toUpperCase() })} className="w-40 font-mono uppercase" maxLength={5} /></div>}
            {codeSettings.useIndustryPrefix && (
              <div className="space-y-3"><Label>行业前缀</Label>
                {codeSettings.industryPrefixes.map(ip => (
                  <div key={ip.industry} className="flex items-center gap-3 p-3 bg-white border border-slate-200 rounded-lg">
                    <Badge variant="secondary" className="w-16 justify-center text-xs">{industryLabels[ip.industry] || ip.industry}</Badge>
                    <Input value={ip.prefix} onChange={e => updateIndustryPrefix(ip.industry, e.target.value)} className="w-24 font-mono uppercase text-center" maxLength={5} />
                    <span className="text-xs text-slate-400 font-mono">{previewCode(codeSettings, ip.industry)}</span>
                  </div>
                ))}
                <div><Label>回退前缀</Label><Input value={codeSettings.defaultPrefix} onChange={e => updateCode({ defaultPrefix: e.target.value.toUpperCase() })} className="w-40 font-mono uppercase" maxLength={5} /></div>
              </div>
            )}
            <div><Label>编号位数</Label><NativeSelect value={String(codeSettings.digitCount)} onChange={v => updateCode({ digitCount: parseInt(v, 10) })} className="w-40" options={[2, 3, 4, 5, 6].map(n => ({ value: String(n), label: `${n} 位` }))} /></div>
            <div className="flex items-center justify-between p-4 bg-slate-50 rounded-lg"><div><Label>包含年份</Label></div><Switch checked={codeSettings.includeYear} onCheckedChange={v => updateCode({ includeYear: v })} /></div>
            <div><Label>分隔符</Label><NativeSelect value={codeSettings.separator} onChange={v => updateCode({ separator: v })} className="w-40" options={[{ value: 'all', label: '无' }, { value: '-', label: '-' }, { value: '_', label: '_' }]} /></div>
            <div className="p-4 bg-blue-50 border border-blue-200 rounded-lg"><div className="flex items-center gap-2 mb-2"><Eye className="w-4 h-4 text-blue-600" /><span className="text-sm font-medium text-blue-800">预览</span></div>
              <code className="text-sm font-mono bg-white px-2 py-0.5 rounded border border-blue-200 text-blue-800">{previewCode(codeSettings, 'restaurant')}</code>
            </div>
            <div className="flex items-center justify-between pt-2 border-t"><Button variant="outline" size="sm" onClick={() => { setCodeSettings({ ...defaultSettings, industryPrefixes: defaultIndustryPrefixes.map(ip => ({ ...ip })) }); setCodeChanged(true); }}><RotateCcw className="w-3.5 h-3.5 mr-1" /> 恢复默认</Button><Button onClick={saveCodeSettings} disabled={!codeChanged} className="bg-blue-600 hover:bg-blue-700"><Save className="w-4 h-4 mr-1" /> 保存</Button></div>
          </CardContent></Card>
        </TabsContent>

        {/* Dashboard Config */}
        <TabsContent value="dashboard">
          <Card className="border-slate-200"><CardHeader className="pb-3"><CardTitle className="text-base">仪表盘显示项配置</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            {[
              { key: 'showTotalCustomers', label: '客户总数' }, { key: 'showFollowing', label: '跟进中' },
              { key: 'showClosedMonth', label: '本月成交' }, { key: 'showExpiring', label: '即将到期' },
              { key: 'showRevenue', label: '本月收入' }, { key: 'showOverdue', label: '欠费客户' },
              { key: 'showPendingTasks', label: '待办任务' }, { key: 'showLost', label: '流失客户' },
              { key: 'showReminders', label: '智能提醒' }, { key: 'showRecentCustomers', label: '最近客户' },
              { key: 'showUpcomingTasks', label: '待办任务列表' },
            ].map(item => (
              <div key={item.key} className="flex items-center justify-between p-3 bg-slate-50 rounded-lg">
                <span className="text-sm">{item.label}</span>
                <Switch checked={(dashboardConfig as any)[item.key]} onCheckedChange={v => { setDashboardConfig({ ...dashboardConfig, [item.key]: v }); setDashChanged(true); }} />
              </div>
            ))}
            <div className="flex justify-end pt-2"><Button onClick={saveDash} disabled={!dashChanged} className="bg-blue-600 hover:bg-blue-700"><Save className="w-4 h-4 mr-1" /> 保存</Button></div>
          </CardContent></Card>
        </TabsContent>

        {/* Reminder Config */}
        <TabsContent value="reminder">
          <Card className="border-slate-200"><CardHeader className="pb-3"><CardTitle className="text-base flex items-center gap-2"><Bell className="w-4 h-4 text-blue-600" /> 提醒规则设置</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between p-3 bg-slate-50 rounded-lg"><div><Label>跟进提醒</Label><p className="text-xs text-slate-500">到期跟进提醒</p></div><Switch checked={reminderConfig.enableFollowUpReminder} onCheckedChange={v => { setReminderConfig({ ...reminderConfig, enableFollowUpReminder: v }); setReminderChanged(true); }} /></div>
            <div className="flex items-center justify-between p-3 bg-slate-50 rounded-lg"><div><Label>到期提醒</Label><p className="text-xs text-slate-500">套餐到期前提醒</p></div>
              <div className="flex items-center gap-2"><Input type="number" value={reminderConfig.expiryDaysBefore} onChange={e => { setReminderConfig({ ...reminderConfig, expiryDaysBefore: Number(e.target.value) }); setReminderChanged(true); }} className="w-20 h-8 text-sm" /><span className="text-xs text-slate-500">天前</span><Switch checked={reminderConfig.enableExpiryReminder} onCheckedChange={v => { setReminderConfig({ ...reminderConfig, enableExpiryReminder: v }); setReminderChanged(true); }} /></div>
            </div>
            <div className="flex items-center justify-between p-3 bg-slate-50 rounded-lg"><div><Label>未跟进提醒</Label><p className="text-xs text-slate-500">超过N天未跟进</p></div>
              <div className="flex items-center gap-2"><Input type="number" value={reminderConfig.noFollowDays} onChange={e => { setReminderConfig({ ...reminderConfig, noFollowDays: Number(e.target.value) }); setReminderChanged(true); }} className="w-20 h-8 text-sm" /><span className="text-xs text-slate-500">天</span><Switch checked={reminderConfig.enableNoFollowReminder} onCheckedChange={v => { setReminderConfig({ ...reminderConfig, enableNoFollowReminder: v }); setReminderChanged(true); }} /></div>
            </div>
            <div className="flex items-center justify-between p-3 bg-slate-50 rounded-lg"><div><Label>欠费提醒</Label></div><Switch checked={reminderConfig.enableOverduePayment} onCheckedChange={v => { setReminderConfig({ ...reminderConfig, enableOverduePayment: v }); setReminderChanged(true); }} /></div>
            <div className="flex items-center justify-between p-3 bg-slate-50 rounded-lg"><div><Label>延期任务提醒</Label></div><Switch checked={reminderConfig.enableDelayedTask} onCheckedChange={v => { setReminderConfig({ ...reminderConfig, enableDelayedTask: v }); setReminderChanged(true); }} /></div>
            <div className="flex justify-end pt-2"><Button onClick={saveReminder} disabled={!reminderChanged} className="bg-blue-600 hover:bg-blue-700"><Save className="w-4 h-4 mr-1" /> 保存</Button></div>
          </CardContent></Card>
        </TabsContent>

        {/* Security */}
        <TabsContent value="security">
          <Card className="border-slate-200"><CardHeader className="pb-3"><CardTitle className="text-base flex items-center gap-2"><Lock className="w-4 h-4 text-blue-600" /> 安全设置</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <div className="p-3 bg-slate-50 rounded-lg space-y-2">
              <Label>密码查看权限（可查看媒体账号密码的角色）</Label>
              <div className="flex flex-wrap gap-2">{Object.entries(systemRoleLabels).map(([k, v]) => (
                <label key={k} className="flex items-center gap-1.5 text-xs cursor-pointer">
                  <input type="checkbox" checked={securityConfig.passwordViewRoles.includes(k)} onChange={e => {
                    const roles = e.target.checked ? [...securityConfig.passwordViewRoles, k] : securityConfig.passwordViewRoles.filter(r => r !== k);
                    setSecurityConfig({ ...securityConfig, passwordViewRoles: roles }); setSecurityChanged(true);
                  }} className="rounded" />{v}
                </label>
              ))}</div>
            </div>
            <div className="flex items-center justify-between p-3 bg-slate-50 rounded-lg"><div><Label>记录密码查看日志</Label><p className="text-xs text-slate-500">每次查看密码自动记录操作日志</p></div><Switch checked={securityConfig.logPasswordViews} onCheckedChange={v => { setSecurityConfig({ ...securityConfig, logPasswordViews: v }); setSecurityChanged(true); }} /></div>
            <div className="flex items-center justify-between p-3 bg-slate-50 rounded-lg"><div><Label>删除确认</Label><p className="text-xs text-slate-500">删除操作需二次确认</p></div><Switch checked={securityConfig.requireConfirmDelete} onCheckedChange={v => { setSecurityConfig({ ...securityConfig, requireConfirmDelete: v }); setSecurityChanged(true); }} /></div>
            <div className="flex items-center justify-between p-3 bg-slate-50 rounded-lg"><div><Label>软删除模式</Label><p className="text-xs text-slate-500">删除数据仅标记为已删除，不真正移除</p></div><Switch checked={securityConfig.enableSoftDelete} onCheckedChange={v => { setSecurityConfig({ ...securityConfig, enableSoftDelete: v }); setSecurityChanged(true); }} /></div>
            <div className="flex justify-end pt-2"><Button onClick={saveSecurity} disabled={!securityChanged} className="bg-blue-600 hover:bg-blue-700"><Save className="w-4 h-4 mr-1" /> 保存</Button></div>
          </CardContent></Card>
        </TabsContent>

        {/* Notification */}
        <TabsContent value="notification">
          <Card className="border-slate-200"><CardHeader className="pb-3"><CardTitle className="text-base flex items-center gap-2"><Bell className="w-4 h-4 text-blue-600" /> 系统通知设置</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between p-3 bg-slate-50 rounded-lg"><div><Label>浏览器通知</Label><p className="text-xs text-slate-500">启用浏览器推送通知</p></div><Switch checked={notifConfig.enableBrowserNotif} onCheckedChange={v => { setNotifConfig({ ...notifConfig, enableBrowserNotif: v }); setNotifChanged(true); }} /></div>
            <div className="flex items-center justify-between p-3 bg-slate-50 rounded-lg"><div><Label>邮件通知</Label><p className="text-xs text-slate-500">重要事项发送邮件通知</p></div><Switch checked={notifConfig.enableEmailNotif} onCheckedChange={v => { setNotifConfig({ ...notifConfig, enableEmailNotif: v }); setNotifChanged(true); }} /></div>
            {notifConfig.enableEmailNotif && <div><Label>通知邮箱</Label><Input value={notifConfig.notifEmail} onChange={e => { setNotifConfig({ ...notifConfig, notifEmail: e.target.value }); setNotifChanged(true); }} placeholder="接收通知的邮箱" /></div>}
            <div className="flex justify-end pt-2"><Button onClick={saveNotif} disabled={!notifChanged} className="bg-blue-600 hover:bg-blue-700"><Save className="w-4 h-4 mr-1" /> 保存</Button></div>
          </CardContent></Card>
        </TabsContent>

        {/* Export Config */}
        <TabsContent value="export">
          <Card className="border-slate-200"><CardHeader className="pb-3"><CardTitle className="text-base flex items-center gap-2"><Download className="w-4 h-4 text-blue-600" /> 导出权限与配置</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <div className="p-3 bg-slate-50 rounded-lg space-y-2">
              <Label>允许导出的角色</Label>
              <div className="flex flex-wrap gap-2">{Object.entries(systemRoleLabels).map(([k, v]) => (
                <label key={k} className="flex items-center gap-1.5 text-xs cursor-pointer">
                  <input type="checkbox" checked={exportConfig.exportRoles.includes(k)} onChange={e => {
                    const roles = e.target.checked ? [...exportConfig.exportRoles, k] : exportConfig.exportRoles.filter(r => r !== k);
                    setExportConfig({ ...exportConfig, exportRoles: roles }); setExportChanged(true);
                  }} className="rounded" />{v}
                </label>
              ))}</div>
            </div>
            <div><Label>默认导出格式</Label><NativeSelect value={exportConfig.defaultFormat} onChange={v => { setExportConfig({ ...exportConfig, defaultFormat: v }); setExportChanged(true); }} className="w-40" options={[{ value: 'xlsx', label: 'Excel (.xlsx)' }, { value: 'csv', label: 'CSV (.csv)' }]} /></div>
            <div className="flex items-center justify-between p-3 bg-slate-50 rounded-lg"><Label>导出包含备注</Label><Switch checked={exportConfig.includeNotes} onCheckedChange={v => { setExportConfig({ ...exportConfig, includeNotes: v }); setExportChanged(true); }} /></div>
            <div className="flex items-center justify-between p-3 bg-slate-50 rounded-lg"><Label>导出包含社交链接</Label><Switch checked={exportConfig.includeSocialLinks} onCheckedChange={v => { setExportConfig({ ...exportConfig, includeSocialLinks: v }); setExportChanged(true); }} /></div>
            <div className="flex justify-end pt-2"><Button onClick={saveExport} disabled={!exportChanged} className="bg-blue-600 hover:bg-blue-700"><Save className="w-4 h-4 mr-1" /> 保存</Button></div>
          </CardContent></Card>
        </TabsContent>

        {/* Operation Logs */}
        <TabsContent value="logs">
          <Card className="border-slate-200"><CardHeader className="pb-3"><CardTitle className="text-base flex items-center gap-2"><FileText className="w-4 h-4 text-blue-600" /> 全局操作日志</CardTitle></CardHeader>
          <CardContent>
            {logsLoading ? <div className="flex items-center justify-center py-8"><div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-600" /></div>
            : logs.length === 0 ? <p className="text-sm text-slate-400 text-center py-8">暂无操作日志</p>
            : <div className="space-y-2 max-h-96 overflow-y-auto">{logs.map((log: any) => (
              <div key={log.id} className="flex items-start gap-3 p-2.5 bg-slate-50 rounded-lg text-sm">
                <Badge variant="secondary" className="text-xs shrink-0">{actionTypeLabels[log.action_type] || log.action_type}</Badge>
                <div className="flex-1 min-w-0"><p className="text-slate-700">{log.action_detail}</p><p className="text-xs text-slate-400 mt-0.5">{log.operator_name || '系统'} · {log.created_at?.slice(0, 16).replace('T', ' ')}</p></div>
              </div>
            ))}</div>}
          </CardContent></Card>
        </TabsContent>
      </Tabs>
    
<div className="mt-6"><a href="/settings/deduction" className="text-blue-600 hover:underline">月度扣点比例设置</a></div>
</div>
  );
}