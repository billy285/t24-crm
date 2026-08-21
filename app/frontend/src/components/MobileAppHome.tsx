import type { LucideIcon } from 'lucide-react';
import {
  Bell,
  Building2,
  CalendarCheck2,
  CheckCircle2,
  ChevronRight,
  CircleUserRound,
  Headphones,
  ListTodo,
  Settings2,
  Target,
  UsersRound,
  WalletCards,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { cn } from '@/lib/utils';
import {
  appNavigationItems,
  getRolePendingPath,
  getRoleTodayPath,
  getMobileBusinessApps,
  type MobileBusinessAppKey,
} from '@/lib/app-navigation';
import { getSafeInternalPath } from '@/lib/navigation-state';
import { roleLabels, useRole } from '@/lib/role-context';

export type { MobileBusinessAppKey } from '@/lib/app-navigation';

export type MobileHomeItemTone = 'critical' | 'warning' | 'info' | 'success';

export interface MobileHomeTodayItem {
  id: string | number;
  title: string;
  description?: string;
  meta?: string;
  path: string;
  actionLabel?: string;
  tone?: MobileHomeItemTone;
}

export interface MobileHomeRecentItem {
  id: string | number;
  title: string;
  description?: string;
  timestamp?: string;
  path: string;
  appKey?: MobileBusinessAppKey;
}

export interface MobileAppHomeProps {
  todayItems?: MobileHomeTodayItem[];
  appBadges?: Partial<Record<MobileBusinessAppKey, string | number>>;
  recentItems?: MobileHomeRecentItem[];
  notificationCount?: number;
  loading?: boolean;
  loadError?: string;
  onRetry?: () => void;
  onOpenProfile: () => void;
  onOpenNotifications?: () => void;
  todayPath?: string;
  pendingPath?: string;
  className?: string;
}

const toneStyles: Record<MobileHomeItemTone, { label: string; container: string; badge: string; button: string }> = {
  critical: {
    label: '高风险',
    container: 'border-rose-200 bg-gradient-to-br from-rose-50 to-white',
    badge: 'bg-rose-100 text-rose-700',
    button: 'bg-rose-600 text-white active:bg-rose-700',
  },
  warning: {
    label: '待处理',
    container: 'border-amber-200 bg-gradient-to-br from-amber-50 to-white',
    badge: 'bg-amber-100 text-amber-800',
    button: 'bg-amber-600 text-white active:bg-amber-700',
  },
  info: {
    label: '今日事项',
    container: 'border-blue-200 bg-gradient-to-br from-blue-50 to-white',
    badge: 'bg-blue-100 text-blue-700',
    button: 'bg-blue-600 text-white active:bg-blue-700',
  },
  success: {
    label: '进展正常',
    container: 'border-emerald-200 bg-gradient-to-br from-emerald-50 to-white',
    badge: 'bg-emerald-100 text-emerald-700',
    button: 'bg-emerald-600 text-white active:bg-emerald-700',
  },
};

const iconTones = {
  indigo: 'bg-gradient-to-br from-indigo-500 to-violet-600 text-white ring-indigo-200',
  blue: 'bg-gradient-to-br from-blue-500 to-blue-700 text-white ring-blue-200',
  cyan: 'bg-gradient-to-br from-cyan-400 to-blue-600 text-white ring-cyan-200',
  violet: 'bg-gradient-to-br from-violet-500 to-fuchsia-600 text-white ring-violet-200',
  emerald: 'bg-gradient-to-br from-emerald-400 to-teal-600 text-white ring-emerald-200',
  slate: 'bg-gradient-to-br from-slate-500 to-slate-700 text-white ring-slate-200',
} as const;

const shortcutIconTones = {
  indigo: 'bg-indigo-50 text-indigo-600 ring-indigo-100',
  blue: 'bg-blue-50 text-blue-600 ring-blue-100',
  cyan: 'bg-cyan-50 text-cyan-600 ring-cyan-100',
  violet: 'bg-violet-50 text-violet-600 ring-violet-100',
  emerald: 'bg-emerald-50 text-emerald-600 ring-emerald-100',
  slate: 'bg-slate-100 text-slate-600 ring-slate-200',
} as const;

const mobileShortcutLabels: Record<string, string> = {
  '/': '今日经营',
  '/company-roadmap': '公司战略',
  '/management-decisions': '经营决策',
  '/sales-workbench': '销售工作台',
  '/merchant-pool': '商家池',
  '/sales-leads': '电话销售',
  '/sales-knowledge': '销售知识',
  '/customers': '客户管理',
  '/sales': '成交客户',
  '/deals': '成交管理',
  '/customer-lifecycle': '客户周期',
  '/operations-workbench': '运营工作台',
  '/tasks': '任务协作',
  '/service-board': '服务进度',
  '/callbacks': '电话回访',
  '/finance': '财务管理',
  '/rmb-profit': '利润预估',
  '/commissions': '渠道分润',
  '/settings/deduction': '月度扣点',
  '/payroll': '工资表',
  '/employees': '员工管理',
  '/settings': '系统设置',
  '/permissions': '权限设置',
  '/partner-portal': '客户与分润',
};

const shortcutDefinitionByPath = new Map(appNavigationItems.map(item => [item.path, item]));

const recentIcons: Record<MobileBusinessAppKey, LucideIcon> = {
  strategy: Target,
  sales: Headphones,
  customers: UsersRound,
  delivery: ListTodo,
  finance: WalletCards,
  organization: Settings2,
  partner: WalletCards,
};

const pathNameOf = (value?: string) => {
  const safePath = getSafeInternalPath(value);
  if (!safePath) return '';
  return new URL(safePath, 'https://t24-crm.local').pathname;
};

const visibleBadge = (value: string | number | undefined) => {
  if (value === undefined || value === null || value === '' || value === 0 || value === '0') return '';
  if (typeof value === 'number' && value > 99) return '99+';
  return String(value);
};

const roleHomeCopy: Record<string, { eyebrow: string; title: string; subtitle: string }> = {
  super_admin: { eyebrow: '经营总览', title: '老板今日工作台', subtitle: '先看风险，再推进今天最重要的事项' },
  admin: { eyebrow: '经营总览', title: '管理工作台', subtitle: '查看团队、客户与财务的今日重点' },
  sales: { eyebrow: '销售执行', title: '我的销售工作台', subtitle: '先拨打、再回访，记录每一次有效沟通' },
  sales_manager: { eyebrow: '销售管理', title: '销售主管工作台', subtitle: '掌握团队进度，及时处理未完成任务' },
  ops: { eyebrow: '客户交付', title: '我的运营工作台', subtitle: '优先处理逾期、回访与客户问题' },
  design: { eyebrow: '设计交付', title: '我的设计工作台', subtitle: '集中处理自己的设计任务与素材事项' },
  finance: { eyebrow: '财务核对', title: '财务今日工作台', subtitle: '关注待收款、续费风险与异常记录' },
  sales_partner: { eyebrow: '合作进展', title: '客户与分润工作台', subtitle: '跟进客户续费与分润确认状态' },
};

export function T24AppMark({ className, decorative = false }: { className?: string; decorative?: boolean }) {
  return (
    <span
      className={cn(
        'relative inline-flex h-12 w-12 items-center justify-center overflow-hidden rounded-[17px] border border-white bg-gradient-to-br from-white to-blue-50 shadow-[0_16px_34px_-18px_rgba(37,99,235,0.6)] ring-1 ring-blue-100/80',
        className,
      )}
      role={decorative ? undefined : 'img'}
      aria-label={decorative ? undefined : 'T24 OS'}
      aria-hidden={decorative || undefined}
    >
      <span className="absolute -right-3 -top-3 h-9 w-9 rounded-full bg-blue-200/45 blur-md" />
      <span className="relative bg-gradient-to-br from-blue-500 to-blue-700 bg-clip-text text-[13px] font-black italic tracking-[-0.08em] text-transparent">
        T24
      </span>
      <span className="absolute bottom-[9px] left-[11px] h-[2px] w-6 -rotate-[26deg] rounded-full bg-gradient-to-r from-blue-300 to-blue-600" />
      <span className="absolute right-[9px] top-[9px] h-2.5 w-2.5 rotate-[-8deg] border-r-2 border-t-2 border-blue-600" />
    </span>
  );
}

export default function MobileAppHome({
  todayItems = [],
  appBadges = {},
  recentItems = [],
  notificationCount = 0,
  loading = false,
  loadError = '',
  onRetry,
  onOpenProfile,
  onOpenNotifications,
  todayPath,
  pendingPath,
  className,
}: MobileAppHomeProps) {
  const navigate = useNavigate();
  const { employee, role, canAccess } = useRole();

  const canOpen = (path?: string) => {
    const pathname = pathNameOf(path);
    return Boolean(pathname && canAccess(pathname));
  };

  const openPath = (path?: string) => {
    const safePath = getSafeInternalPath(path);
    if (!safePath || !canOpen(safePath)) return;
    navigate(safePath);
  };

  const firstAccessiblePath = (paths: string[]) => paths.find(canOpen);
  const appDefinitions = getMobileBusinessApps(role);
  const availableApps = appDefinitions
    .map(app => ({ ...app, path: firstAccessiblePath(app.paths) }))
    .filter((app): app is (typeof appDefinitions)[number] & { path: string } => Boolean(app.path));
  const appSections = availableApps
    .map(app => ({
      ...app,
      shortcuts: app.paths.flatMap(path => {
        const pathname = pathNameOf(path);
        const definition = shortcutDefinitionByPath.get(pathname);
        if (!pathname || !definition || !canOpen(path)) return [];
        return [{ ...definition, path, label: mobileShortcutLabels[pathname] || definition.label }];
      }),
    }))
    .filter(app => app.shortcuts.length > 0);

  const defaultTodayPath = getRoleTodayPath(role);
  const defaultPendingPath = getRolePendingPath(role);
  const resolvedTodayPath = canOpen(todayPath) ? todayPath : canOpen(defaultTodayPath) ? defaultTodayPath : availableApps[0]?.path;
  const resolvedPendingPath = canOpen(pendingPath) ? pendingPath : canOpen(defaultPendingPath) ? defaultPendingPath : resolvedTodayPath;
  const accessibleTodayItems = todayItems.filter(item => canOpen(item.path));
  const topTodayItem = accessibleTodayItems[0];
  const accessibleRecentItems = recentItems.filter(item => canOpen(item.path)).slice(0, 3);
  const roleLabel = roleLabels[employee?.role] || roleLabels[role] || '员工';
  const employeeName = employee?.name || employee?.full_name || '同事';
  const notificationBadge = visibleBadge(notificationCount);
  const todayTone = toneStyles[topTodayItem?.tone || 'info'];
  const homeCopy = roleHomeCopy[role] || roleHomeCopy.admin;

  const openNotifications = () => {
    if (onOpenNotifications) {
      onOpenNotifications();
      return;
    }
    openPath(resolvedPendingPath);
  };

  return (
    <div
      className={cn(
        'mobile-app-home relative mx-auto min-h-[100dvh] w-full max-w-[48rem] overflow-x-hidden bg-[#f3f6fb] pb-[calc(6.25rem+env(safe-area-inset-bottom))] text-slate-950 md:min-h-full md:pb-10',
        className,
      )}
    >
      <div className="pointer-events-none absolute inset-x-0 top-0 h-[25rem] bg-[radial-gradient(circle_at_top_right,rgba(59,130,246,0.20),transparent_48%),radial-gradient(circle_at_top_left,rgba(139,92,246,0.10),transparent_42%),linear-gradient(180deg,#ffffff_0%,rgba(255,255,255,0)_100%)]" />

      <header className="relative pl-[max(1rem,env(safe-area-inset-left))] pr-[max(1rem,env(safe-area-inset-right))] pt-[max(env(safe-area-inset-top),1rem)]">
        <div className="flex min-h-12 items-center gap-3">
          <T24AppMark decorative />
          <div className="min-w-0 flex-1">
            <p className="truncate text-[15px] font-bold tracking-tight text-slate-950">T24 工作台</p>
            <p className="mt-0.5 truncate text-[11px] text-slate-500"><span className="font-semibold text-blue-600">当前账号</span> · {employeeName} · {roleLabel}</p>
          </div>
          <button
            type="button"
            onClick={openNotifications}
            className="relative flex h-11 w-11 items-center justify-center rounded-full border border-white/90 bg-white/85 text-slate-700 shadow-sm backdrop-blur-xl active:scale-95"
            aria-label={notificationBadge ? `查看待办，${notificationBadge} 项未处理` : '查看待办'}
          >
            <Bell className="h-5 w-5" />
            {notificationBadge ? (
              <span className="absolute -right-0.5 -top-0.5 flex min-h-5 min-w-5 items-center justify-center rounded-full border-2 border-[#f3f6fb] bg-rose-500 px-1 text-[10px] font-bold text-white">
                {notificationBadge}
              </span>
            ) : null}
          </button>
          <button
            type="button"
            onClick={onOpenProfile}
            className="flex h-11 w-11 items-center justify-center rounded-full border border-white/90 bg-white/85 text-slate-700 shadow-sm backdrop-blur-xl active:scale-95"
            aria-label="打开我的账户"
          >
            <CircleUserRound className="h-6 w-6" />
          </button>
        </div>

        <div className="pb-5 pt-5 md:pb-6 md:pt-8">
          <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-blue-600">{homeCopy.eyebrow}</p>
          <h1 className="mt-1 text-[26px] font-black tracking-[-0.04em] text-[#10213f]">{homeCopy.title}</h1>
          <p className="mt-1.5 text-[12px] text-slate-500">{homeCopy.subtitle}</p>
        </div>
      </header>

      <main className="relative space-y-6 pl-[max(1rem,env(safe-area-inset-left))] pr-[max(1rem,env(safe-area-inset-right))]">
        {loading ? (
          <div className="flex items-center gap-2 rounded-2xl border border-blue-100 bg-blue-50/80 px-4 py-3 text-xs text-blue-700" role="status" aria-live="polite">
            <span className="h-2 w-2 animate-pulse rounded-full bg-blue-500" />
            正在更新当前账号的今日重点，应用入口可直接使用。
          </div>
        ) : loadError ? (
          <div className="flex items-center justify-between gap-3 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-800" role="status" aria-live="polite">
            <span>{loadError}</span>
            {onRetry ? <button type="button" className="shrink-0 font-bold underline" onClick={onRetry}>重新加载</button> : null}
          </div>
        ) : null}
        <section aria-label="工作应用" className="rounded-[24px] border border-white/90 bg-white/95 px-3 py-5 shadow-[0_20px_48px_-38px_rgba(37,70,132,0.58)] backdrop-blur-xl">
          <div className="mb-4 flex items-end justify-between px-1">
            <div>
              <h2 id="mobile-apps-heading" className="text-[17px] font-black tracking-tight text-slate-950">首页应用</h2>
              <p className="mt-0.5 text-[10px] text-slate-400">常用业务中心 · 按当前账号权限显示</p>
            </div>
            <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[10px] font-semibold text-slate-500">{availableApps.length} 个入口</span>
          </div>
          <div className={cn(
            'grid gap-x-2 gap-y-4',
            availableApps.length === 1 && 'grid-cols-1',
            (availableApps.length === 2 || availableApps.length === 4) && 'grid-cols-2',
            (availableApps.length === 3 || availableApps.length >= 5) && 'grid-cols-3',
            availableApps.length >= 4 && 'md:grid-cols-6',
          )}>
            {availableApps.map(app => {
              const Icon = app.icon;
              const badge = visibleBadge(appBadges[app.key]);
              return (
                <button
                  key={app.key}
                  type="button"
                  onClick={() => openPath(app.path)}
                  className={cn(
                    'relative flex min-h-[84px] min-w-0 flex-col items-center justify-start gap-2 rounded-2xl px-1 py-1 text-center transition active:scale-[0.96]',
                    availableApps.length === 1 && 'mx-auto w-28',
                  )}
                  aria-label={`${app.label}：${app.description}`}
                >
                  <span className={cn('relative flex h-12 w-12 items-center justify-center rounded-[16px] ring-1 shadow-[0_12px_24px_-14px_rgba(15,23,42,0.65)]', iconTones[app.tone])}>
                    <Icon className="h-5 w-5" />
                    {badge ? <span className="absolute -right-2 -top-2 rounded-full bg-rose-500 px-1.5 py-0.5 text-[9px] font-bold text-white ring-2 ring-white">{badge}</span> : null}
                  </span>
                  <span className="max-w-full text-[11px] font-bold leading-4 text-slate-800">{app.label}</span>
                </button>
              );
            })}
          </div>
          {availableApps.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 p-6 text-center text-sm text-slate-500">
              当前账号暂无可用业务应用，请联系管理员检查权限。
            </div>
          ) : null}
        </section>

        <section aria-labelledby="mobile-today-heading">
          <div className="mb-3 flex items-center justify-between px-1">
            <div>
              <h2 id="mobile-today-heading" className="text-[16px] font-bold tracking-tight text-slate-950">今天先处理</h2>
              <p className="mt-0.5 text-[11px] text-slate-500">先完成最重要的一件事</p>
            </div>
            {resolvedTodayPath ? (
              <button type="button" onClick={() => openPath(resolvedTodayPath)} className="flex min-h-11 items-center gap-0.5 px-1 text-sm font-semibold text-blue-700">
                今日工作台<ChevronRight className="h-4 w-4" />
              </button>
            ) : null}
          </div>

          {topTodayItem ? (
            <article className={cn('rounded-[24px] border p-4 shadow-[0_14px_40px_-28px_rgba(15,23,42,0.55)]', todayTone.container)}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <span className={cn('inline-flex rounded-full px-2.5 py-1 text-[11px] font-bold', todayTone.badge)}>{todayTone.label}</span>
                  <h3 className="mt-3 text-lg font-bold tracking-tight text-slate-950">{topTodayItem.title}</h3>
                  {topTodayItem.description ? <p className="mt-1.5 text-sm leading-5 text-slate-600">{topTodayItem.description}</p> : null}
                  {topTodayItem.meta ? <p className="mt-2 text-xs font-medium text-slate-500">{topTodayItem.meta}</p> : null}
                </div>
                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-white/85 text-slate-700 shadow-sm">
                  <CalendarCheck2 className="h-5 w-5" />
                </div>
              </div>
              <button
                type="button"
                onClick={() => openPath(topTodayItem.path)}
                className={cn('mt-4 flex min-h-12 w-full items-center justify-center gap-2 rounded-2xl px-4 text-sm font-bold shadow-sm active:scale-[0.99]', todayTone.button)}
              >
                {topTodayItem.actionLabel || '立即处理'}<ChevronRight className="h-4 w-4" />
              </button>
            </article>
          ) : (
            <button
              type="button"
              disabled={!resolvedTodayPath}
              onClick={() => openPath(resolvedTodayPath)}
              className="flex min-h-[78px] w-full items-center gap-3 rounded-[22px] border border-blue-100 bg-gradient-to-r from-blue-50 to-white p-4 text-left shadow-[0_14px_40px_-30px_rgba(15,23,42,0.4)] disabled:opacity-60"
            >
              <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-white text-blue-600 shadow-sm">
                <CheckCircle2 className="h-5 w-5" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-bold text-slate-900">打开今日工作台</span>
                <span className="mt-0.5 block text-xs text-slate-500">查看当前角色需要处理的真实事项</span>
              </span>
              <ChevronRight className="h-4 w-4 shrink-0 text-blue-400" />
            </button>
          )}
        </section>

        {accessibleRecentItems.length > 0 ? (
          <section aria-labelledby="mobile-recent-heading">
            <div className="mb-3 px-1">
              <h2 id="mobile-recent-heading" className="text-[16px] font-bold tracking-tight text-slate-950">继续处理</h2>
              <p className="mt-0.5 text-[11px] text-slate-500">回到刚才的客户或工作位置</p>
            </div>
            <div className="overflow-hidden rounded-[24px] border border-white/90 bg-white shadow-[0_16px_40px_-32px_rgba(15,23,42,0.6)]">
              {accessibleRecentItems.map((item, index) => {
                const Icon = item.appKey ? recentIcons[item.appKey] : Building2;
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => openPath(item.path)}
                    className={cn('flex min-h-[68px] w-full items-center gap-3 px-4 py-3 text-left active:bg-slate-50', index > 0 && 'border-t border-slate-100')}
                  >
                    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-slate-100 text-slate-600"><Icon className="h-4 w-4" /></span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-bold text-slate-900">{item.title}</span>
                      <span className="mt-0.5 block truncate text-xs text-slate-500">{[item.description, item.timestamp].filter(Boolean).join(' · ')}</span>
                    </span>
                    <ChevronRight className="h-4 w-4 shrink-0 text-slate-300" />
                  </button>
                );
              })}
            </div>
          </section>
        ) : null}

        {appSections.length > 0 ? (
          <section aria-labelledby="mobile-functions-heading" className="space-y-3">
            <div className="px-1">
              <h2 id="mobile-functions-heading" className="text-[17px] font-black tracking-tight text-slate-950">全部功能</h2>
              <p className="mt-0.5 text-[11px] text-slate-500">按业务分类，直接进入需要处理的页面</p>
            </div>
            {appSections.map(section => (
              <section
                key={section.key}
                aria-labelledby={`mobile-function-group-${section.key}`}
                className="rounded-[22px] border border-white/90 bg-white px-3 pb-4 pt-4 shadow-[0_18px_46px_-38px_rgba(15,23,42,0.6)]"
              >
                <div className="mb-4 flex items-center justify-between px-1">
                  <div className="flex min-w-0 items-center gap-2.5">
                    <span className={cn('flex h-8 w-8 shrink-0 items-center justify-center rounded-xl ring-1', shortcutIconTones[section.tone])}>
                      <section.icon className="h-4 w-4" />
                    </span>
                    <div className="min-w-0">
                      <h3 id={`mobile-function-group-${section.key}`} className="text-[15px] font-black text-slate-900">{section.label}</h3>
                      <p className="truncate text-[10px] text-slate-400">{section.description}</p>
                    </div>
                  </div>
                  <span className="text-[10px] font-semibold text-slate-400">{section.shortcuts.length} 项</span>
                </div>
                <div className={cn(
                  'grid gap-x-2 gap-y-3',
                  section.shortcuts.length === 1 && 'grid-cols-1',
                  section.shortcuts.length === 2 && 'grid-cols-2',
                  section.shortcuts.length === 3 && 'grid-cols-3',
                  section.shortcuts.length >= 4 && 'grid-cols-4',
                )}>
                  {section.shortcuts.map(shortcut => {
                    const ShortcutIcon = shortcut.icon;
                    return (
                      <button
                        key={`${section.key}:${shortcut.path}`}
                        type="button"
                        onClick={() => openPath(shortcut.path)}
                        className={cn(
                          'flex min-h-[76px] min-w-0 flex-col items-center justify-start gap-2 rounded-2xl px-1 py-1 text-center transition active:scale-[0.96] active:bg-slate-50',
                          section.shortcuts.length === 1 && 'mx-auto w-28',
                        )}
                        aria-label={`打开${shortcut.label}`}
                      >
                        <span className={cn('flex h-11 w-11 items-center justify-center rounded-[15px] ring-1', shortcutIconTones[section.tone])}>
                          <ShortcutIcon className="h-5 w-5" />
                        </span>
                        <span className="line-clamp-2 text-[11px] font-semibold leading-4 text-slate-700">{shortcut.label}</span>
                      </button>
                    );
                  })}
                </div>
              </section>
            ))}
          </section>
        ) : null}
      </main>
    </div>
  );
}
