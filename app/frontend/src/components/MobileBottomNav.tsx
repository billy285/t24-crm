import type { LucideIcon } from 'lucide-react';
import { CalendarCheck2, CircleUserRound, Home, ListTodo, UsersRound } from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';
import { getRolePendingPath, getRoleTodayPath } from '@/lib/app-navigation';
import { getSafeInternalPath } from '@/lib/navigation-state';
import { useRole } from '@/lib/role-context';
import { cn } from '@/lib/utils';

interface MobileBottomNavProps {
  onOpenProfile: () => void;
  hidden?: boolean;
  profileOpen?: boolean;
}

type MobileTabKey = 'home' | 'today' | 'customers' | 'pending' | 'profile';

const pathnameOf = (value?: string) => {
  const safePath = getSafeInternalPath(value);
  if (!safePath) return '';
  return new URL(safePath, 'https://t24-crm.local').pathname;
};

export default function MobileBottomNav({ onOpenProfile, hidden = false, profileOpen = false }: MobileBottomNavProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const { role, canAccess } = useRole();

  const canOpen = (path?: string) => {
    const pathname = pathnameOf(path);
    return Boolean(pathname && canAccess(pathname));
  };
  const todayPath = getRoleTodayPath(role);
  const pendingPath = getRolePendingPath(role);
  const customerPath = canOpen('/customers') ? '/customers' : canOpen('/partner-portal') ? '/partner-portal' : undefined;
  let activeKey: MobileTabKey | undefined;
  if (location.pathname === '/apps') activeKey = 'home';
  else if (location.pathname === '/customers' || location.pathname === '/partner-portal') activeKey = 'customers';
  else if (
    location.pathname === '/tasks'
    || location.pathname === '/callbacks'
    || location.pathname === '/service-board'
    || (role === 'finance' && location.pathname === '/finance')
  ) activeKey = 'pending';
  else if (location.pathname === pathnameOf(todayPath)) activeKey = 'today';

  const openPath = (path?: string) => {
    const safePath = getSafeInternalPath(path);
    if (!safePath || !canOpen(safePath)) return;
    navigate(safePath);
  };

  if (hidden) return null;

  if (role === 'sales_partner') {
    return (
      <nav
        className="mobile-bottom-nav fixed inset-x-0 bottom-0 z-40 mx-auto max-w-lg border-t border-white/80 bg-white/90 pb-[max(env(safe-area-inset-bottom),0.5rem)] pl-[max(0.75rem,env(safe-area-inset-left))] pr-[max(0.75rem,env(safe-area-inset-right))] pt-2 shadow-[0_-12px_40px_-30px_rgba(15,23,42,0.55)] backdrop-blur-2xl md:hidden"
        aria-label="手机主导航"
      >
        <div className="grid grid-cols-3 gap-1">
          <MobileNavButton icon={Home} label="首页" active={activeKey === 'home'} onClick={() => navigate('/apps')} />
          <MobileNavButton icon={UsersRound} label="客户与分润" active={!profileOpen && activeKey === 'customers'} onClick={() => openPath('/partner-portal')} />
          <MobileNavButton icon={CircleUserRound} label="我的" active={profileOpen} onClick={onOpenProfile} />
        </div>
      </nav>
    );
  }

  return (
    <nav
      className="mobile-bottom-nav fixed inset-x-0 bottom-0 z-40 mx-auto max-w-lg border-t border-white/80 bg-white/90 pb-[max(env(safe-area-inset-bottom),0.5rem)] pl-[max(0.75rem,env(safe-area-inset-left))] pr-[max(0.75rem,env(safe-area-inset-right))] pt-2 shadow-[0_-12px_40px_-30px_rgba(15,23,42,0.55)] backdrop-blur-2xl md:hidden"
      aria-label="手机主导航"
    >
      <div className="grid grid-cols-5 gap-1">
        <MobileNavButton icon={Home} label="首页" active={activeKey === 'home'} onClick={() => navigate('/apps')} />
        <MobileNavButton icon={CalendarCheck2} label="今日" active={activeKey === 'today'} disabled={!canOpen(todayPath)} onClick={() => openPath(todayPath)} />
        <MobileNavButton icon={UsersRound} label="客户" active={activeKey === 'customers'} disabled={!customerPath} onClick={() => openPath(customerPath)} />
        <MobileNavButton icon={ListTodo} label="待办" active={activeKey === 'pending'} disabled={!canOpen(pendingPath)} onClick={() => openPath(pendingPath)} />
        <MobileNavButton icon={CircleUserRound} label="我的" active={profileOpen} onClick={onOpenProfile} />
      </div>
    </nav>
  );
}

function MobileNavButton({
  icon: Icon,
  label,
  active = false,
  disabled = false,
  onClick,
}: {
  icon: LucideIcon;
  label: string;
  active?: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={cn(
        'flex min-h-14 min-w-0 flex-col items-center justify-center gap-1 rounded-2xl text-slate-400 active:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-30',
        active && 'text-blue-700',
      )}
      aria-current={active ? 'page' : undefined}
      aria-label={label}
    >
      <Icon className="h-5 w-5" />
      <span className="text-[10px] font-bold leading-none">{label}</span>
    </button>
  );
}
