import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { client } from '../lib/api';
import { invokeWithAuth } from '../lib/tokenStore';
import { useRole } from '../lib/role-context';
import { systemRoleLabels } from '../lib/permissions';
import { loadRemoteAppConfig, readCachedAppConfig, saveRemoteAppConfig } from '../lib/app-config';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { toast } from 'sonner';
import { Settings as SettingsIcon, Hash, Eye, RotateCcw, Save, Building2, BookOpen, Bell, FileText, Download, Lock, Bot, KeyRound, TestTube2 } from 'lucide-react';
import { NativeSelect } from '@/components/ui/native-select';
import { actionTypeLabels } from '../lib/operation-log-helper';
import { type CustomerCodeSettings, defaultSettings, defaultIndustryPrefixes, loadSettings, saveSettings, previewCode } from '../lib/customer-code-settings';
import { type BusinessDictConfig, defaultBusinessDictConfig, normalizeDictConfig } from '../lib/dict-config';
import { settingsApi, type AiSettings, type EnvConfig } from '../api/settings';
import ProductPlanSettings from '@/components/ProductPlanSettings';
import MobileDesktopOnlyNotice from '@/components/mobile/MobileDesktopOnlyNotice';
import { useIsMobile } from '@/hooks/use-mobile';

const industryLabels: Record<string, string> = { restaurant: '餐厅', nail: '美甲', massage: '按摩', beauty: '美容', supermarket: '超市', other: '其他' };
type EnvScope = 'backend_vars' | 'frontend_vars';

const defaultCompany = { name: '', address: '', phone: '', email: '', website: '', logo: '', description: '' };
const defaultDashboardConfig = {
  showTotalCustomers: true, showFollowing: true, showClosedMonth: true,
  showExpiring: true, showRevenue: true, showOverdue: true,
  showPendingTasks: true, showLost: true, showReminders: true,
  showRecentCustomers: true, showUpcomingTasks: true,
};
const defaultReminderConfig = {
  enableFollowUpReminder: true, followUpDaysBefore: 0,
  enableExpiryReminder: true, expiryDaysBefore: 7,
  enableNoFollowReminder: true, noFollowDays: 7,
  enableOverduePayment: true, enableDelayedTask: true,
};
const normalizeReminderConfig = (config: Partial<typeof defaultReminderConfig> | undefined | null) => ({
  ...defaultReminderConfig,
  ...(config || {}),
  expiryDaysBefore: Number(config?.expiryDaysBefore) === 30 ? 7 : Number(config?.expiryDaysBefore ?? defaultReminderConfig.expiryDaysBefore),
});
const defaultNotificationConfig = {
  enableBrowserNotif: false,
  enableEmailNotif: false,
  notifEmail: '',
};
const defaultExportConfig = {
  exportRoles: ['super_admin', 'admin', 'sales', 'finance'] as string[],
  defaultFormat: 'xlsx',
  includeNotes: true,
  includeSocialLinks: true,
};
const defaultAiSettings: AiSettings = {
  enabled: false,
  provider: 'openai',
  base_url: 'https://api.openai.com/v1',
  model: 'gpt-5.4-mini',
  api_key_set: false,
  api_key_preview: '',
  source: 'default',
  updated_at: null,
};

export default function Settings() {
  const { isAdmin, hasPermission } = useRole();
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  const canEditSettings = isAdmin || hasPermission('settings_edit');

  // Customer code settings
  const [codeSettings, setCodeSettings] = useState<CustomerCodeSettings>(defaultSettings);
  const [codeChanged, setCodeChanged] = useState(false);

  // Company info
  const [company, setCompany] = useState(defaultCompany);
  const [companyChanged, setCompanyChanged] = useState(false);

  // Dictionary config
  const [dictConfig, setDictConfig] = useState<BusinessDictConfig>(defaultBusinessDictConfig);
  const [dictChanged, setDictChanged] = useState(false);

  // Dashboard config
  const [dashboardConfig, setDashboardConfig] = useState(defaultDashboardConfig);
  const [dashChanged, setDashChanged] = useState(false);

  // Reminder config
  const [reminderConfig, setReminderConfig] = useState(defaultReminderConfig);
  const [reminderChanged, setReminderChanged] = useState(false);

  // Notification config
  const [notifConfig, setNotifConfig] = useState(defaultNotificationConfig);
  const [notifChanged, setNotifChanged] = useState(false);

  // Export config
  const [exportConfig, setExportConfig] = useState(defaultExportConfig);
  const [exportChanged, setExportChanged] = useState(false);
  const [settingsLoading, setSettingsLoading] = useState(true);

  // Operation logs
  const [logs, setLogs] = useState<any[]>([]);
  const [logsLoading, setLogsLoading] = useState(false);

  // Environment config (backend-powered)
  const [envConfig, setEnvConfig] = useState<EnvConfig>({ backend_vars: {}, frontend_vars: {} });
  const [envLoading, setEnvLoading] = useState(false);
  const [envSavingKey, setEnvSavingKey] = useState<string | null>(null);

  // AI config
  const [aiSettings, setAiSettings] = useState<AiSettings>(defaultAiSettings);
  const [aiApiKey, setAiApiKey] = useState('');
  const [aiChanged, setAiChanged] = useState(false);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiSaving, setAiSaving] = useState(false);
  const [aiTesting, setAiTesting] = useState(false);

  const loadEnvConfig = async () => {
    setEnvLoading(true);
    try {
      const data = await settingsApi.getConfig();
      setEnvConfig(data);
    } catch (err: any) {
      const detail = err?.data?.detail || err?.message || '加载环境配置失败';
      toast.error(detail);
    } finally {
      setEnvLoading(false);
    }
  };

  const loadAiSettings = async () => {
    setAiLoading(true);
    try {
      const data = await settingsApi.getAiSettings();
      setAiSettings(data);
      setAiApiKey('');
      setAiChanged(false);
    } catch (err: any) {
      const detail = err?.data?.detail || err?.message || '加载 AI 配置失败';
      toast.error(detail);
    } finally {
      setAiLoading(false);
    }
  };

  useEffect(() => {
    if (isMobile) {
      setSettingsLoading(false);
      return;
    }

    let active = true;

    const loadSettingsData = async () => {
      setSettingsLoading(true);
      try {
        const [
          remoteCode,
          remoteCompany,
          remoteDict,
          remoteDashboard,
          remoteReminder,
          remoteNotif,
          remoteExport,
        ] = await Promise.all([
          loadRemoteAppConfig('customer_code_settings', defaultSettings),
          loadRemoteAppConfig('company_info', defaultCompany),
          loadRemoteAppConfig('dict_config', defaultBusinessDictConfig),
          loadRemoteAppConfig('dashboard_config', defaultDashboardConfig),
          loadRemoteAppConfig('reminder_config', defaultReminderConfig),
          loadRemoteAppConfig('notification_config', defaultNotificationConfig),
          loadRemoteAppConfig('export_config', defaultExportConfig),
        ]);

        if (!active) return;

        setCodeSettings(remoteCode);
        setCompany(remoteCompany);
        setDictConfig(normalizeDictConfig(remoteDict));
        setDashboardConfig(remoteDashboard);
        setReminderConfig(normalizeReminderConfig(remoteReminder));
        setNotifConfig(remoteNotif);
        setExportConfig(remoteExport);
      } catch {
        if (!active) return;
        setCodeSettings(loadSettings());
        setCompany(readCachedAppConfig('company_info', defaultCompany));
        setDictConfig(normalizeDictConfig(readCachedAppConfig('dict_config', defaultBusinessDictConfig)));
        setDashboardConfig(readCachedAppConfig('dashboard_config', defaultDashboardConfig));
        setReminderConfig(normalizeReminderConfig(readCachedAppConfig('reminder_config', defaultReminderConfig)));
        setNotifConfig(readCachedAppConfig('notification_config', defaultNotificationConfig));
        setExportConfig(readCachedAppConfig('export_config', defaultExportConfig));
        toast.error('加载系统设置失败，已回退到缓存配置');
      } finally {
        if (active) {
          setSettingsLoading(false);
        }
      }

      if (canEditSettings) {
        await Promise.all([loadEnvConfig(), loadAiSettings()]);
      }
    };

    void loadSettingsData();

    return () => {
      active = false;
    };
  }, [canEditSettings, isMobile]);

  const loadLogs = async () => {
    setLogsLoading(true);
    try {
      const res = isAdmin
        ? await invokeWithAuth({
            url: '/api/v1/entities/operation_logs/all',
            method: 'GET',
            data: {
              sort: '-created_at',
              limit: 100,
            },
          })
        : await client.entities.operation_logs.query({
            sort: '-created_at',
            limit: 100,
          });
      setLogs(res?.data?.items || []);
    } catch (err) { console.error(err); }
    finally { setLogsLoading(false); }
  };

  const updateCode = (patch: Partial<CustomerCodeSettings>) => { setCodeSettings(prev => ({ ...prev, ...patch })); setCodeChanged(true); };
  const updateIndustryPrefix = (industry: string, newPrefix: string) => {
    setCodeSettings(prev => ({ ...prev, industryPrefixes: prev.industryPrefixes.map(ip => ip.industry === industry ? { ...ip, prefix: newPrefix.toUpperCase() } : ip) }));
    setCodeChanged(true);
  };

  const saveCodeSettings = async () => {
    if (!codeSettings.defaultPrefix.trim()) { toast.error('默认前缀不能为空'); return; }
    try {
      const saved = await saveRemoteAppConfig('customer_code_settings', codeSettings);
      saveSettings(saved);
      setCodeSettings(saved);
      setCodeChanged(false);
      toast.success('编号格式已保存');
    } catch {
      toast.error('保存编号格式失败');
    }
  };

  const saveCompany = async () => {
    try {
      const saved = await saveRemoteAppConfig('company_info', company);
      setCompany(saved);
      setCompanyChanged(false);
      toast.success('公司信息已保存');
    } catch {
      toast.error('保存公司信息失败');
    }
  };
  const saveDict = async () => {
    try {
      const saved = normalizeDictConfig(await saveRemoteAppConfig('dict_config', dictConfig));
      setDictConfig(saved);
      setDictChanged(false);
      toast.success('字典配置已保存');
    } catch {
      toast.error('保存字典配置失败');
    }
  };
  const saveDash = async () => {
    try {
      const saved = await saveRemoteAppConfig('dashboard_config', dashboardConfig);
      setDashboardConfig(saved);
      setDashChanged(false);
      toast.success('仪表盘配置已保存');
    } catch {
      toast.error('保存仪表盘配置失败');
    }
  };
  const saveReminder = async () => {
    try {
      const saved = await saveRemoteAppConfig('reminder_config', reminderConfig);
      setReminderConfig(saved);
      setReminderChanged(false);
      toast.success('提醒规则已保存');
    } catch {
      toast.error('保存提醒规则失败');
    }
  };
  const saveNotif = async () => {
    try {
      const saved = await saveRemoteAppConfig('notification_config', notifConfig);
      setNotifConfig(saved);
      setNotifChanged(false);
      toast.success('通知设置已保存');
    } catch {
      toast.error('保存通知设置失败');
    }
  };
  const saveExport = async () => {
    try {
      const saved = await saveRemoteAppConfig('export_config', exportConfig);
      setExportConfig(saved);
      setExportChanged(false);
      toast.success('导出配置已保存');
    } catch {
      toast.error('保存导出配置失败');
    }
  };

  const updateEnvValue = (scope: EnvScope, key: string, value: string) => {
    setEnvConfig(prev => ({
      ...prev,
      [scope]: {
        ...prev[scope],
        [key]: {
          ...prev[scope][key],
          value,
        },
      },
    }));
  };

  const saveEnvValue = async (scope: EnvScope, key: string) => {
    const savingKey = `${scope}:${key}`;
    setEnvSavingKey(savingKey);
    try {
      const value = envConfig[scope][key]?.value ?? '';
      const action = scope === 'backend_vars'
        ? settingsApi.updateBackendConfig(key, value)
        : settingsApi.updateFrontendConfig(key, value);
      const response = await action;
      toast.success(response.message || '配置已保存');
      await loadEnvConfig();
    } catch (err: any) {
      const detail = err?.data?.detail || err?.message || '保存失败';
      toast.error(detail);
    } finally {
      setEnvSavingKey(null);
    }
  };

  const updateAiSettings = (patch: Partial<AiSettings>) => {
    setAiSettings(prev => ({ ...prev, ...patch }));
    setAiChanged(true);
  };

  const saveAiSettings = async (options?: { clearApiKey?: boolean }) => {
    setAiSaving(true);
    try {
      const saved = await settingsApi.updateAiSettings({
        enabled: aiSettings.enabled,
        provider: aiSettings.provider || 'openai',
        base_url: aiSettings.base_url,
        model: aiSettings.model,
        api_key: aiApiKey.trim() || undefined,
        clear_api_key: Boolean(options?.clearApiKey),
      });
      setAiSettings(saved);
      setAiApiKey('');
      setAiChanged(false);
      toast.success(options?.clearApiKey ? 'OpenAI Key 已清空' : 'OpenAI 配置已保存');
    } catch (err: any) {
      const detail = err?.data?.detail || err?.message || '保存 OpenAI 配置失败';
      toast.error(detail);
    } finally {
      setAiSaving(false);
    }
  };

  const testAiSettings = async () => {
    if (aiChanged || aiApiKey.trim()) {
      toast.error('请先保存 OpenAI 配置，再测试连接');
      return;
    }
    setAiTesting(true);
    try {
      const result = await settingsApi.testAiSettings();
      toast.success(result.message || 'OpenAI 连接正常');
    } catch (err: any) {
      const detail = err?.data?.detail || err?.message || 'OpenAI 连接测试失败';
      toast.error(detail);
    } finally {
      setAiTesting(false);
    }
  };

  if (isMobile) {
    return (
      <MobileDesktopOnlyNotice
        title="全局设置请在电脑端处理"
        description="环境、权限、安全和导出规则会影响整个系统。手机版仅保留个人账户与安装入口，避免误触全局配置。"
      />
    );
  }

  if (!canEditSettings) {
    return <div className="flex items-center justify-center h-64"><p className="text-slate-400">仅管理员可访问系统设置</p></div>;
  }

  if (settingsLoading) {
    return (
      <>
        <div className="hidden h-64 items-center justify-center md:flex">
          <div className="h-8 w-8 animate-spin rounded-full border-b-2 border-blue-600" />
        </div>
      </>
    );
  }

  return (
    <>
      <div className="t24-settings-page app-page hidden space-y-5 md:block">
      <div className="app-page-title"><p className="app-page-kicker">T24 Marketing · System</p><h2 className="app-page-heading flex items-center gap-2"><SettingsIcon className="h-5 w-5 text-blue-600" />系统设置</h2><p className="app-page-description">配置公司资料、业务规则、产品套餐、提醒、安全与导出规则。</p></div>

      <Tabs defaultValue="company" className="w-full">
        <TabsList className="bg-slate-100 flex-wrap h-auto gap-1 p-1">
          <TabsTrigger value="ai" className="text-xs">AI配置</TabsTrigger>
          <TabsTrigger value="env" className="text-xs">环境配置</TabsTrigger>
          <TabsTrigger value="company" className="text-xs">公司信息</TabsTrigger>
          <TabsTrigger value="dict" className="text-xs">字典配置</TabsTrigger>
          <TabsTrigger value="products" className="text-xs">产品套餐</TabsTrigger>
          <TabsTrigger value="code" className="text-xs">编号规则</TabsTrigger>
          <TabsTrigger value="dashboard" className="text-xs">仪表盘</TabsTrigger>
          <TabsTrigger value="reminder" className="text-xs">提醒规则</TabsTrigger>
          <TabsTrigger value="security" className="text-xs">安全设置</TabsTrigger>
          <TabsTrigger value="notification" className="text-xs">通知设置</TabsTrigger>
          <TabsTrigger value="export" className="text-xs">导出配置</TabsTrigger>
          <TabsTrigger value="logs" className="text-xs" onClick={loadLogs}>操作日志</TabsTrigger>
        </TabsList>

        <TabsContent value="ai">
          <Card className="border-slate-200">
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <Bot className="w-4 h-4 text-blue-600" />
                OpenAI 文案生成配置
              </CardTitle>
              <CardDescription>
                用于客户详情里的 AI 文案生成。密钥只保存在后端，页面不会回显完整 Key。
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              {aiLoading ? (
                <div className="flex items-center justify-center py-8">
                  <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-600" />
                </div>
              ) : (
                <>
                  <div className="flex items-center justify-between p-4 bg-slate-50 rounded-lg">
                    <div>
                      <Label className="text-sm font-medium">启用 OpenAI</Label>
                      <p className="text-xs text-slate-500 mt-0.5">
                        开启后，客户 AI 文案会调用 OpenAI；关闭时仍会生成可编辑模板草稿。
                      </p>
                    </div>
                    <Switch
                      checked={aiSettings.enabled}
                      onCheckedChange={v => updateAiSettings({ enabled: v })}
                    />
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <Label>OpenAI Base URL</Label>
                      <Input
                        value={aiSettings.base_url}
                        onChange={e => updateAiSettings({ base_url: e.target.value })}
                        placeholder="https://api.openai.com/v1"
                      />
                      <p className="text-xs text-slate-400 mt-1">
                        官方 OpenAI 保持默认即可；兼容代理服务可填写对应地址。
                      </p>
                    </div>
                    <div>
                      <Label>文案模型</Label>
                      <Input
                        value={aiSettings.model}
                        onChange={e => updateAiSettings({ model: e.target.value })}
                        placeholder="gpt-5.4-mini"
                      />
                      <p className="text-xs text-slate-400 mt-1">
                        文案生成建议用 mini 类模型，速度快、成本更低。
                      </p>
                    </div>
                  </div>

                  <div className="p-4 border border-blue-100 bg-blue-50/60 rounded-lg space-y-3">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <Label className="flex items-center gap-1.5">
                          <KeyRound className="w-3.5 h-3.5 text-blue-600" />
                          OpenAI API Key
                        </Label>
                        <p className="text-xs text-slate-500 mt-1">
                          {aiSettings.api_key_set
                            ? `当前已保存：${aiSettings.api_key_preview}`
                            : '当前未保存 API Key'}
                        </p>
                      </div>
                      {aiSettings.api_key_set && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => saveAiSettings({ clearApiKey: true })}
                          disabled={aiSaving}
                        >
                          清空Key
                        </Button>
                      )}
                    </div>
                    <Input
                      type="password"
                      value={aiApiKey}
                      onChange={e => {
                        setAiApiKey(e.target.value);
                        setAiChanged(true);
                      }}
                      placeholder={aiSettings.api_key_set ? '如需更换 Key，请输入新的 OpenAI API Key' : '请输入 OpenAI API Key'}
                    />
                    <p className="text-xs text-slate-500">
                      不更换 Key 时这里留空即可。为了安全，系统不会把完整 Key 显示出来。
                    </p>
                  </div>

                  <div className="flex flex-wrap items-center justify-between gap-3 pt-2 border-t">
                    <div className="text-xs text-slate-500">
                      状态：
                      {aiSettings.enabled && aiSettings.api_key_set ? (
                        <Badge className="ml-1 bg-emerald-100 text-emerald-700 hover:bg-emerald-100">已启用</Badge>
                      ) : aiSettings.api_key_set ? (
                        <Badge variant="secondary" className="ml-1">已保存Key，未启用</Badge>
                      ) : (
                        <Badge variant="outline" className="ml-1">未配置</Badge>
                      )}
                    </div>
                    <div className="flex gap-2">
                      <Button variant="outline" onClick={loadAiSettings} disabled={aiLoading || aiSaving}>
                        刷新
                      </Button>
                      <Button variant="outline" onClick={testAiSettings} disabled={aiTesting || aiSaving || !aiSettings.enabled || !aiSettings.api_key_set}>
                        <TestTube2 className="w-4 h-4 mr-1" />
                        测试连接
                      </Button>
                      <Button onClick={() => saveAiSettings()} disabled={!aiChanged || aiSaving} className="bg-blue-600 hover:bg-blue-700">
                        <Save className="w-4 h-4 mr-1" />
                        保存配置
                      </Button>
                    </div>
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="env">
          <div className="space-y-4">
            <Card className="border-slate-200">
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <SettingsIcon className="w-4 h-4 text-blue-600" />
                  运行环境配置
                </CardTitle>
                <CardDescription>
                  这里的配置会直接写入后端 `.env` 与前端 `.env`。保存后通常需要重启对应服务才会生效。
                </CardDescription>
              </CardHeader>
              <CardContent className="flex justify-end">
                <Button variant="outline" size="sm" onClick={loadEnvConfig} disabled={envLoading}>
                  刷新配置
                </Button>
              </CardContent>
            </Card>

            {([
              { scope: 'backend_vars' as const, title: '后端环境变量', description: '数据库、JWT、回调地址等运行参数' },
              { scope: 'frontend_vars' as const, title: '前端环境变量', description: '前端 API 地址等浏览器端运行参数' },
            ]).map(section => (
              <Card key={section.scope} className="border-slate-200">
                <CardHeader className="pb-3">
                  <CardTitle className="text-base">{section.title}</CardTitle>
                  <CardDescription>{section.description}</CardDescription>
                </CardHeader>
                <CardContent>
                  {envLoading ? (
                    <div className="flex items-center justify-center py-8">
                      <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-600" />
                    </div>
                  ) : Object.keys(envConfig[section.scope]).length === 0 ? (
                    <p className="text-sm text-slate-400 py-4">暂无配置项</p>
                  ) : (
                    <div className="space-y-3">
                      {Object.entries(envConfig[section.scope]).map(([key, item]) => {
                        const savingKey = `${section.scope}:${key}`;
                        return (
                          <div key={key} className="p-3 bg-slate-50 rounded-lg space-y-2">
                            <div className="flex items-center justify-between gap-3">
                              <div className="min-w-0">
                                <p className="text-sm font-medium text-slate-800 break-all">{key}</p>
                                {item.description && (
                                  <p className="text-xs text-slate-500 mt-0.5">{item.description}</p>
                                )}
                              </div>
                              <Button
                                size="sm"
                                onClick={() => saveEnvValue(section.scope, key)}
                                disabled={envSavingKey === savingKey}
                                className="shrink-0 bg-blue-600 hover:bg-blue-700"
                              >
                                保存
                              </Button>
                            </div>
                            <Input
                              value={item.value}
                              onChange={e => updateEnvValue(section.scope, key, e.target.value)}
                              placeholder={`请输入 ${key}`}
                            />
                          </div>
                        );
                      })}
                    </div>
                  )}
                </CardContent>
              </Card>
            ))}
          </div>
        </TabsContent>

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
            <div><Label>客户意向套餐</Label><Textarea value={dictConfig.customerPackages} onChange={e => { setDictConfig({ ...dictConfig, customerPackages: e.target.value }); setDictChanged(true); }} rows={2} /></div>
            <div><Label>国家</Label><Textarea value={dictConfig.countries} onChange={e => { setDictConfig({ ...dictConfig, countries: e.target.value }); setDictChanged(true); }} rows={2} /></div>
            <div><Label>计费周期</Label><Textarea value={dictConfig.billingCycles} onChange={e => { setDictConfig({ ...dictConfig, billingCycles: e.target.value }); setDictChanged(true); }} rows={2} /></div>
            <div><Label>收款模式</Label><Textarea value={dictConfig.paymentModes} onChange={e => { setDictConfig({ ...dictConfig, paymentModes: e.target.value }); setDictChanged(true); }} rows={2} /></div>
            <div><Label>收款方式</Label><Textarea value={dictConfig.paymentMethods} onChange={e => { setDictConfig({ ...dictConfig, paymentMethods: e.target.value }); setDictChanged(true); }} rows={2} /></div>
            <div><Label>公司支出类型</Label><Textarea value={dictConfig.companyExpenseTypes} onChange={e => { setDictConfig({ ...dictConfig, companyExpenseTypes: e.target.value }); setDictChanged(true); }} rows={2} /></div>
            <div><Label>套餐状态</Label><Textarea value={dictConfig.subscriptionStatuses} onChange={e => { setDictConfig({ ...dictConfig, subscriptionStatuses: e.target.value }); setDictChanged(true); }} rows={2} /></div>
            <div><Label>跟进阶段</Label><Textarea value={dictConfig.followUpStages} onChange={e => { setDictConfig({ ...dictConfig, followUpStages: e.target.value }); setDictChanged(true); }} rows={3} /></div>
            <div><Label>跟进方式</Label><Textarea value={dictConfig.followUpMethods} onChange={e => { setDictConfig({ ...dictConfig, followUpMethods: e.target.value }); setDictChanged(true); }} rows={2} /></div>
            <div><Label>回访类型</Label><Textarea value={dictConfig.callbackTypes} onChange={e => { setDictConfig({ ...dictConfig, callbackTypes: e.target.value }); setDictChanged(true); }} rows={2} /></div>
            <div><Label>回访状态</Label><Textarea value={dictConfig.callbackStatuses} onChange={e => { setDictConfig({ ...dictConfig, callbackStatuses: e.target.value }); setDictChanged(true); }} rows={2} /></div>
            <div><Label>回访结果</Label><Textarea value={dictConfig.callbackResults} onChange={e => { setDictConfig({ ...dictConfig, callbackResults: e.target.value }); setDictChanged(true); }} rows={2} /></div>
            <div><Label>任务类型</Label><Textarea value={dictConfig.taskTypes} onChange={e => { setDictConfig({ ...dictConfig, taskTypes: e.target.value }); setDictChanged(true); }} rows={2} /></div>
            <div><Label>任务优先级</Label><Textarea value={dictConfig.taskPriorities} onChange={e => { setDictConfig({ ...dictConfig, taskPriorities: e.target.value }); setDictChanged(true); }} rows={2} /></div>
            <div><Label>任务状态</Label><Textarea value={dictConfig.taskStatuses} onChange={e => { setDictConfig({ ...dictConfig, taskStatuses: e.target.value }); setDictChanged(true); }} rows={2} /></div>
            <div className="flex justify-end"><Button onClick={saveDict} disabled={!dictChanged} className="bg-blue-600 hover:bg-blue-700"><Save className="w-4 h-4 mr-1" /> 保存</Button></div>
          </CardContent></Card>
        </TabsContent>

        <TabsContent value="products">
          <ProductPlanSettings canEdit={canEditSettings} />
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
            <div><Label>分隔符</Label><NativeSelect value={codeSettings.separator} onChange={v => updateCode({ separator: v })} className="w-40" options={[{ value: '', label: '无' }, { value: '-', label: '-' }, { value: '_', label: '_' }]} /></div>
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
          <Card className="border-slate-200">
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2"><Lock className="w-4 h-4 text-blue-600" /> 安全边界与执行状态</CardTitle>
              <CardDescription>这里只展示系统当前真正执行的规则，不提供未落地的全局开关。</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex items-start justify-between gap-4 rounded-lg bg-slate-50 p-4">
                <div>
                  <Label>媒体账号密码权限</Label>
                  <p className="mt-1 text-xs leading-5 text-slate-500">以“权限管理 → 敏感信息权限”为唯一生效来源；关闭后前端入口和后端接口都会拒绝。</p>
                </div>
                {isAdmin ? (
                  <Button type="button" variant="outline" size="sm" className="shrink-0" onClick={() => navigate('/permissions')}>前往权限管理</Button>
                ) : (
                  <Badge variant="outline" className="shrink-0">由管理员配置</Badge>
                )}
              </div>
              <div className="flex items-start justify-between gap-4 rounded-lg bg-slate-50 p-4">
                <div>
                  <Label>密码查看审计</Label>
                  <p className="mt-1 text-xs leading-5 text-slate-500">由服务器强制记录真实操作者、时间、来源地址、客户和账号；无法在此关闭。</p>
                </div>
                <Badge className="shrink-0 bg-emerald-100 text-emerald-700 hover:bg-emerald-100">强制开启</Badge>
              </div>
              <div className="flex items-start justify-between gap-4 rounded-lg bg-slate-50 p-4">
                <div>
                  <Label>删除二次确认</Label>
                  <p className="mt-1 text-xs leading-5 text-slate-500">由每个已完成适配的业务页面分别执行，不存在可以覆盖全系统的总开关。</p>
                </div>
                <Badge variant="outline" className="shrink-0">逐页面执行</Badge>
              </div>
              <div className="flex items-start justify-between gap-4 rounded-lg border border-amber-200 bg-amber-50 p-4">
                <div>
                  <Label>全局软删除</Label>
                  <p className="mt-1 text-xs leading-5 text-amber-700">当前未全局启用，删除后的可恢复性取决于具体业务模块。完善数据生命周期前，系统不会承诺所有删除都可恢复。</p>
                </div>
                <Badge variant="outline" className="shrink-0 border-amber-300 text-amber-700">未全局启用</Badge>
              </div>
            </CardContent>
          </Card>
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
    </>
  );
}
