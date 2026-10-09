import type { LucideIcon } from 'lucide-react';
import {
  ArrowRight,
  Bell,
  Building2,
  CalendarDays,
  CalendarCheck2,
  ChevronRight,
  CircleUserRound,
  Clock3,
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
import './homepage-refined.css';

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

export interface MobileHomePriorityItem {
  id: string;
  title: string;
  count: number | null;
  path: string;
  actionLabel: string;
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
  priorityItems?: MobileHomePriorityItem[];
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

const mobileShortcutLabels: Record<string, string> = {
  '/': '今日经营',
  '/company-roadmap': '公司战略',
  '/management-decisions': '经营决策',
  '/sales-workbench': '今日拨打',
  '/merchant-pool': '商家池',
  '/sales-leads': '联系进展',
  '/sales-knowledge': '知识库',
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

export function T24AppMark({ className, decorative = false }: { className?: string; decorative?: boolean }) {
  return (
    <span
      className={cn(
        'relative inline-flex h-12 w-12 items-center justify-center overflow-hidden rounded-[17px] border border-slate-200 bg-white shadow-[0_14px_30px_-18px_rgba(2,32,57,0.55)] ring-1 ring-slate-100',
        className,
      )}
      role={decorative ? undefined : 'img'}
      aria-label={decorative ? undefined : 'T24 OS'}
      aria-hidden={decorative || undefined}
    >
      <img
        src="/t2-marketing-logo.png?v=t2-20260822-official"
        alt=""
        className="h-full w-full scale-[1.08] rounded-full object-cover"
      />
    </span>
  );
}

export default function MobileAppHome({
  todayItems = [],
  priorityItems,
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
  const topTodayItem = todayItems.find(item => canOpen(item.path));
  const accessiblePriorityItems = (priorityItems || [])
    .filter(item => canOpen(item.path))
    .map(item => ({ ...item, count: typeof item.count === 'number' && Number.isInteger(item.count) && item.count >= 0 ? item.count : null }))
    .filter(item => item.count !== 0);
  const hasStructuredPriority = priorityItems !== undefined;
  const accessibleRecentItems = recentItems.filter(item => canOpen(item.path)).slice(0, 3);
  const showRecentSection = accessibleRecentItems.length > 0 || loading || Boolean(loadError);
  const isOwnerHome = role === 'super_admin' || role === 'admin';
  const primaryPath = hasStructuredPriority || !topTodayItem ? resolvedTodayPath : topTodayItem.path;
  const primaryLabel = hasStructuredPriority || !topTodayItem ? '打开今日工作台' : topTodayItem.actionLabel || '立即处理';
  const roleLabel = roleLabels[employee?.role] || roleLabels[role] || '员工';
  const employeeName = employee?.name || employee?.full_name || '同事';
  const notificationBadge = visibleBadge(notificationCount);
  const today = new Date();
  const dateLabel = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: 'long', day: 'numeric' }).format(today);

  const openNotifications = () => {
    if (onOpenNotifications) {
      onOpenNotifications();
      return;
    }
    openPath(resolvedPendingPath);
  };

  const renderRecentItem = (item: MobileHomeRecentItem) => {
    const Icon = item.appKey ? recentIcons[item.appKey] : Building2;
    return (
      <button key={item.id} type="button" onClick={() => openPath(item.path)} className="home-recent-item">
        <span className="home-icon home-recent-icon"><Icon aria-hidden="true" /></span>
        <span className="home-recent-copy">
          <span className="home-recent-title">{item.title}</span>
          {[item.description, item.timestamp].some(Boolean) ? (
            <span className="home-recent-meta">{[item.description, item.timestamp].filter(Boolean).join(' · ')}</span>
          ) : null}
        </span>
        <span className="home-recent-action" aria-hidden="true">继续<ArrowRight /></span>
      </button>
    );
  };

  return (
    <div className={cn('mobile-app-home homepage-refined', className)}>
      <header className="home-topbar">
        <div className="home-topbar-inner">
          <div className="home-brand"><T24AppMark decorative className="home-brand-mark" /><span>T24 工作台</span></div>
          <div className="home-account-actions">
            <button type="button" onClick={openNotifications} className="home-header-button home-notifications" aria-label={notificationBadge ? `查看待办，${notificationBadge} 项未处理` : '查看待办'}>
              <Bell aria-hidden="true" />
              {notificationBadge ? <span className="home-notification-count">{notificationBadge}</span> : null}
            </button>
            <button type="button" onClick={onOpenProfile} className="home-header-button home-profile" aria-label="打开我的账户">
              <CircleUserRound aria-hidden="true" />
              <span className="home-account-name">{employeeName} · {roleLabel}</span>
            </button>
          </div>
        </div>
      </header>

      <main className="home-content">
        <div className="home-page-heading">
          <div><h1>今日工作</h1><time dateTime={today.toISOString()} title="北京时间">{dateLabel}</time></div>
          {isOwnerHome && resolvedTodayPath ? <button type="button" onClick={() => openPath(resolvedTodayPath)} className="home-outline-button home-overview-button">经营总览<ArrowRight aria-hidden="true" /></button> : null}
        </div>
        {loading ? (
          <div className="home-load-state" role="status" aria-live="polite">正在更新今日重点</div>
        ) : loadError ? (
          <div className="home-load-state home-load-warning" role="status" aria-live="polite">
            <span>{loadError}</span>
            {onRetry ? <button type="button" onClick={onRetry}>重新加载</button> : null}
          </div>
        ) : null}

        <div className={cn('home-work-grid', !showRecentSection && 'home-work-grid-single')}>
          <section aria-label="今日重点" className="home-panel home-priority-panel">
            <h2 id="mobile-today-heading">今日重点</h2>
            {hasStructuredPriority ? (
              accessiblePriorityItems.length > 0 ? (
                <div className="home-priority-list">
                  {accessiblePriorityItems.map(item => {
                    const Icon = item.id === 'overdue-tasks' ? Clock3 : item.id === 'renewal-risks' ? CalendarDays : WalletCards;
                    return (
                      <div key={item.id} role="group" aria-label={item.title} className="home-priority-row">
                        <span className={cn('home-icon home-priority-icon', (item.tone === 'critical' || item.tone === 'warning') && 'home-icon-amber')}><Icon aria-hidden="true" /></span>
                        <h3>{item.title}</h3>
                        <span className={cn('home-priority-count', item.count === null && 'home-count-unknown')}>{item.count === null ? '待更新' : item.count}</span>
                        <button type="button" onClick={() => openPath(item.path)} className="home-outline-button">{item.actionLabel}<ArrowRight aria-hidden="true" /></button>
                      </div>
                    );
                  })}
                </div>
              ) : <p className="home-empty-priority">{loading ? '正在更新今日重点' : loadError ? '今日重点待更新' : '暂无待处理提醒'}</p>
            ) : topTodayItem ? (
              <article className="home-today-item">
                <div className="home-today-copy">
                  <span className={cn('home-icon home-priority-icon', (topTodayItem.tone === 'critical' || topTodayItem.tone === 'warning') && 'home-icon-amber')}><CalendarCheck2 aria-hidden="true" /></span>
                  <div><h3>{topTodayItem.title}</h3>{topTodayItem.description ? <p>{topTodayItem.description}</p> : null}{topTodayItem.meta ? <p className="home-today-meta">{topTodayItem.meta}</p> : null}</div>
                </div>
              </article>
            ) : <p className="home-empty-priority">{loading ? '正在更新今日重点' : loadError ? '今日重点待更新' : '查看今日需要处理的事项'}</p>}
            {primaryPath ? <div className="home-primary-action"><button type="button" onClick={() => openPath(primaryPath)} className="home-primary-button">{primaryLabel}<ArrowRight aria-hidden="true" /></button></div> : null}
          </section>

          {showRecentSection ? <section aria-label="继续处理" className="home-panel home-recent-panel">
            <h2 id="mobile-recent-heading">继续处理</h2>
            {accessibleRecentItems.length > 0 ? (
              <>
                {renderRecentItem(accessibleRecentItems[0])}
                {accessibleRecentItems.length > 1 ? <details className="home-more-recent"><summary>更多最近事项<ChevronRight aria-hidden="true" /></summary><div>{accessibleRecentItems.slice(1).map(renderRecentItem)}</div></details> : null}
              </>
            ) : <p className="home-empty-recent">{loading || loadError ? '最近事项待更新' : '暂无最近事项'}</p>}
          </section> : null}
        </div>

        <section aria-label="工作应用" className="home-apps-section">
          <h2 id="mobile-apps-heading">常用应用</h2>
          <div className={cn('home-app-grid', availableApps.length === 1 && 'home-app-grid-one', availableApps.length === 2 && 'home-app-grid-two')}>
            {availableApps.map(app => {
              const Icon = app.icon;
              return <button key={app.key} type="button" onClick={() => openPath(app.path)} className="home-app-tile" aria-label={`${app.label}：${app.description}`}><span className="home-icon home-app-icon"><Icon aria-hidden="true" /></span><span>{app.label}</span><ChevronRight className="home-app-chevron" aria-hidden="true" /></button>;
            })}
          </div>
          {availableApps.length === 0 ? <p className="home-empty-apps">当前账号暂无可用业务应用</p> : null}
        </section>

        {appSections.length > 0 ? (
          <details className="home-all-functions" aria-labelledby="mobile-functions-heading">
            <summary><h2 id="mobile-functions-heading">全部功能</h2><ChevronRight aria-hidden="true" /></summary>
            <div className="home-function-groups">
              {appSections.map(section => (
                <section key={section.key} aria-labelledby={`mobile-function-group-${section.key}`} className="home-function-group">
                  <h3 id={`mobile-function-group-${section.key}`}><section.icon aria-hidden="true" />{section.label}</h3>
                  <div className="home-shortcut-grid">
                    {section.shortcuts.map(shortcut => {
                      const Icon = shortcut.icon;
                      return <button key={`${section.key}:${shortcut.path}`} type="button" onClick={() => openPath(shortcut.path)} className="home-shortcut-button" aria-label={`打开${shortcut.label}`}><Icon aria-hidden="true" /><span>{shortcut.label}</span><ChevronRight aria-hidden="true" /></button>;
                    })}
                  </div>
                </section>
              ))}
            </div>
          </details>
        ) : null}
      </main>
    </div>
  );
}
