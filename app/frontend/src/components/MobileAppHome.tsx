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
  indigo: 'bg-indigo-50 text-indigo-600 ring-indigo-100',
  blue: 'bg-blue-50 text-blue-600 ring-blue-100',
  cyan: 'bg-cyan-50 text-cyan-600 ring-cyan-100',
  violet: 'bg-violet-50 text-violet-600 ring-violet-100',
  emerald: 'bg-emerald-50 text-emerald-600 ring-emerald-100',
  slate: 'bg-slate-100 text-slate-600 ring-slate-200',
} as const;

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
        'mobile-app-home relative mx-auto min-h-[100dvh] w-full max-w-[32rem] overflow-x-hidden bg-[#f3f6fb] pb-[calc(6.25rem+env(safe-area-inset-bottom))] text-slate-950',
        className,
      )}
    >
      <div className="pointer-events-none absolute inset-x-0 top-0 h-[25rem] bg-[radial-gradient(circle_at_top_right,rgba(59,130,246,0.20),transparent_48%),radial-gradient(circle_at_top_left,rgba(139,92,246,0.10),transparent_42%),linear-gradient(180deg,#ffffff_0%,rgba(255,255,255,0)_100%)]" />

      <header className="relative pl-[max(1rem,env(safe-area-inset-left))] pr-[max(1rem,env(safe-area-inset-right))] pt-[max(env(safe-area-inset-top),1rem)]">
        <div className="flex min-h-12 items-center gap-3">
          <T24AppMark decorative />
          <div className="min-w-0 flex-1">
            <p className="truncate text-[15px] font-bold tracking-tight text-slate-950">T24 工作台</p>
            <p className="mt-0.5 truncate text-[11px] text-slate-500">{employeeName} · {roleLabel}</p>
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

        <div className="flex flex-col items-center pb-5 pt-5 text-center">
          <T24AppMark className="h-[76px] w-[76px] rounded-[24px] [&>span:nth-child(2)]:text-[20px]" />
          <h1 className="mt-3 text-[24px] font-black tracking-[-0.04em] text-[#10213f]">T24 OS</h1>
          <p className="mt-1 text-[13px] font-medium text-slate-600">企业经营管理系统</p>
          <p className="mt-1 text-[11px] text-slate-400">您的企业经营管理中心</p>
        </div>
      </header>

      <main className="relative space-y-6 pl-[max(1rem,env(safe-area-inset-left))] pr-[max(1rem,env(safe-area-inset-right))]">
        <section aria-labelledby="mobile-apps-heading" className="rounded-[28px] border border-white/90 bg-white/90 px-3 py-5 shadow-[0_24px_58px_-38px_rgba(37,70,132,0.65)] backdrop-blur-xl">
          <div className="mb-4 flex items-end justify-between px-1">
            <div>
              <h2 id="mobile-apps-heading" className="text-[15px] font-bold tracking-tight text-slate-950">工作应用</h2>
              <p className="mt-0.5 text-[10px] text-slate-400">只显示您有权使用的应用</p>
            </div>
          </div>
          <div className={cn('grid gap-x-2 gap-y-5', availableApps.length === 1 ? 'grid-cols-1' : 'grid-cols-3')}>
            {availableApps.map(app => {
              const Icon = app.icon;
              const badge = visibleBadge(appBadges[app.key]);
              return (
                <button
                  key={app.key}
                  type="button"
                  onClick={() => openPath(app.path)}
                  className="relative flex min-h-[82px] min-w-0 flex-col items-center justify-start gap-2 rounded-2xl px-1 py-1 text-center active:scale-[0.96]"
                  aria-label={`${app.label}：${app.description}`}
                >
                  <span className={cn('relative flex h-12 w-12 items-center justify-center rounded-[16px] ring-1 shadow-[0_10px_22px_-16px_rgba(15,23,42,0.55)]', iconTones[app.tone])}>
                    <Icon className="h-5 w-5" />
                    {badge ? <span className="absolute -right-2 -top-2 rounded-full bg-rose-500 px-1.5 py-0.5 text-[9px] font-bold text-white ring-2 ring-white">{badge}</span> : null}
                  </span>
                  <span className="max-w-full truncate text-[12px] font-bold text-slate-800">{app.label}</span>
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
      </main>
    </div>
  );
}
