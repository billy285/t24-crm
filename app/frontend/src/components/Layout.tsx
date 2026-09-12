import { useEffect, useRef, useState } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useRole, roleLabels } from '../lib/role-context';
import { pageLabels } from '../lib/permissions';
import {
  ArrowLeft, LayoutDashboard, LogOut, Menu, ChevronDown, User,
  Lock, KeyRound, ChevronRight,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger
} from '@/components/ui/dropdown-menu';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { toast } from 'sonner';
import { client } from '@/lib/api';
import {
  appNavigationItems,
  getDesktopNavigationSections,
  getRoleTodayPath,
} from '@/lib/app-navigation';
import { T24AppMark } from '@/components/MobileAppHome';
import MobileAppLauncher from '@/components/MobileAppLauncher';
import MobileBottomNav from '@/components/MobileBottomNav';
import MobileModuleMenu from '@/components/MobileModuleMenu';
import { getSafeInternalPath } from '@/lib/navigation-state';
import { getToken } from '@/lib/tokenStore';
import PwaInstallAction from '@/components/PwaInstallAction';
import DesktopBusinessNavigation from '@/components/DesktopBusinessNavigation';
import { getFinanceNavigationItem } from '@/lib/finance-navigation';

interface LayoutProps {
  children: React.ReactNode;
}

export default function Layout({ children }: LayoutProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const currentPath = location.pathname;
  const currentSearch = new URLSearchParams(location.search);
  const mainScrollRef = useRef<HTMLElement | null>(null);
  const scrollPositionsRef = useRef(new Map<string, number>());
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () => typeof window !== 'undefined' && window.localStorage.getItem('t24_sidebar_collapsed') === '1',
  );
  const { employee, role, loading, isLoggedIn, isDisabled, logout, canAccess } = useRole();

  useEffect(() => {
    window.localStorage.setItem('t24_sidebar_collapsed', sidebarCollapsed ? '1' : '0');
  }, [sidebarCollapsed]);

  const mobileDetailKey = currentPath === '/customers'
    ? currentSearch.get('detail') || ''
    : currentPath === '/tasks'
      ? currentSearch.get('task_id') || ''
      : '';

  const navigationSurfaceKey = currentPath === '/finance'
    ? `${currentPath}:${getFinanceNavigationItem(currentSearch.get('tab')).tab}`
    : `${currentPath}:${mobileDetailKey}`;

  useEffect(() => {
    const scrollContainer = mainScrollRef.current;
    if (!scrollContainer) return;
    const frame = window.requestAnimationFrame(() => {
      scrollContainer.scrollTo({
        top: scrollPositionsRef.current.get(navigationSurfaceKey) || 0,
        left: 0,
        behavior: 'auto',
      });
    });
    return () => {
      window.cancelAnimationFrame(frame);
      scrollPositionsRef.current.set(navigationSurfaceKey, scrollContainer.scrollTop);
    };
  }, [navigationSurfaceKey]);
  const [showChangePwd, setShowChangePwd] = useState(false);
  const [mobileProfileOpen, setMobileProfileOpen] = useState(false);
  const [pwdForm, setPwdForm] = useState({ current: '', newPwd: '', confirm: '' });
  const [changingPwd, setChangingPwd] = useState(false);
  const [isOffline, setIsOffline] = useState(() => typeof navigator !== 'undefined' && !navigator.onLine);

  useEffect(() => {
    const handleOnline = () => setIsOffline(false);
    const handleOffline = () => setIsOffline(true);
    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);
    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, []);

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const handleChangePassword = async () => {
    if (!pwdForm.current) {
      toast.error('请输入当前密码');
      return;
    }
    if (!pwdForm.newPwd || pwdForm.newPwd.length < 8) {
      toast.error('新密码至少8个字符');
      return;
    }
    if (pwdForm.newPwd !== pwdForm.confirm) {
      toast.error('两次密码输入不一致');
      return;
    }

    setChangingPwd(true);
    try {
      const token = getToken();
      await client.apiCall.invoke({
        url: '/api/v1/emp-auth/change-password',
        method: 'POST',
        data: {
          current_password: pwdForm.current,
          new_password: pwdForm.newPwd,
        },
        options: {
          headers: { Authorization: `Bearer ${token}` },
        },
      });
      toast.success('密码修改成功');
      setShowChangePwd(false);
      setPwdForm({ current: '', newPwd: '', confirm: '' });
    } catch (err: any) {
      const detail = err?.data?.detail || err?.response?.data?.detail || err?.message || '密码修改失败';
      toast.error(detail);
    } finally {
      setChangingPwd(false);
    }
  };

  if (loading || (isLoggedIn && !role)) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
      </div>
    );
  }

  if (!isLoggedIn && !isDisabled) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  // Disabled account - block access
  if (isDisabled) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="bg-white rounded-xl shadow-lg p-8 max-w-md w-full mx-4 text-center">
          <div className="w-16 h-16 bg-red-100 rounded-full flex items-center justify-center mx-auto mb-4">
            <Lock className="w-8 h-8 text-red-600" />
          </div>
          <h1 className="text-xl font-bold text-slate-800 mb-2">账号已停用</h1>
          <p className="text-slate-500 mb-2">
            您的账号已被管理员停用，无法访问系统。
          </p>
          <p className="text-sm text-slate-400 mb-6">
            如有疑问，请联系管理员恢复账号。
          </p>
          <Button onClick={handleLogout} variant="outline" className="w-full">
            退出登录
          </Button>
        </div>
      </div>
    );
  }

  // Check page access permission
  const hasPageAccess = canAccess(currentPath);

  // Keep the business grouping stable while hiding pages the current role cannot access.
  const visibleNavSections = getDesktopNavigationSections(canAccess);
  const activeNavSection = visibleNavSections.find(section => section.paths.includes(currentPath));
  const desktopPageLabel = currentPath === '/finance'
    ? getFinanceNavigationItem(currentSearch.get('tab')).label
    : appNavigationItems.find(item => item.path === currentPath)?.label || '';

  const displayRole = employee
    ? (roleLabels[employee.role] || employee.role)
    : '管理员模式';
  const homePath = getRoleTodayPath(role);
  const isAppLauncher = currentPath === '/apps';
  const isMobileDetailContext = (
    currentPath === '/customers' && currentSearch.has('detail')
  ) || (
    currentPath === '/tasks' && currentSearch.has('task_id')
  );
  const requestedReturnTo = getSafeInternalPath(currentSearch.get('returnTo'));
  let mobileContextReturnPath = '';
  if (currentPath === '/customers' && currentSearch.has('detail')) {
    if (requestedReturnTo) {
      mobileContextReturnPath = requestedReturnTo;
    } else if (currentSearch.get('from') === 'finance') {
      mobileContextReturnPath = `/finance?tab=${encodeURIComponent(currentSearch.get('financeTab') || 'subscriptions')}`;
    } else {
      const nextSearch = new URLSearchParams(currentSearch);
      ['detail', 'tab', 'reminder', 'from', 'financeTab', 'returnTo'].forEach(key => nextSearch.delete(key));
      mobileContextReturnPath = `/customers${nextSearch.size ? `?${nextSearch.toString()}` : ''}`;
    }
  } else if (currentPath === '/tasks' && currentSearch.has('task_id')) {
    if (requestedReturnTo) {
      mobileContextReturnPath = requestedReturnTo;
    } else {
      const nextSearch = new URLSearchParams(currentSearch);
      ['task_id', 'reminder', 'returnTo'].forEach(key => nextSearch.delete(key));
      mobileContextReturnPath = `/tasks${nextSearch.size ? `?${nextSearch.toString()}` : ''}`;
    }
  }
  const currentPageLabel = currentPath === '/management-decisions'
    && new URLSearchParams(location.search).get('section') === 'insights'
    ? '经营健康与决策'
    : pageLabels[currentPath] || appNavigationItems.find(n => n.path === currentPath)?.label || '';

  return (
    <div className={`t24-system app-shell mobile-app-layout flex h-[100dvh] overflow-hidden md:h-screen${sidebarCollapsed ? ' app-nav-secondary-collapsed' : ''}`}>
      {/* Mobile overlay */}
      {sidebarOpen && (
        <button type="button" tabIndex={-1} aria-label="关闭业务导航遮罩" className="fixed inset-0 z-40 hidden bg-slate-950/40 md:block lg:hidden" onClick={() => setSidebarOpen(false)} />
      )}

      {/* Sidebar */}
      {!isAppLauncher && <DesktopBusinessNavigation
        sections={visibleNavSections}
        pathname={currentPath}
        search={location.search}
        homePath={homePath}
        employeeName={employee?.name}
        roleLabel={displayRole}
        open={sidebarOpen}
        collapsed={sidebarCollapsed}
        onClose={() => setSidebarOpen(false)}
        onCollapsedChange={setSidebarCollapsed}
        onLogout={handleLogout}
      />}

      {/* Main content */}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        {isOffline && (
          <div className="sticky top-0 z-40 flex items-center justify-between gap-3 bg-amber-50 px-4 py-2 text-xs text-amber-800 shadow-sm">
            <span>当前网络连接不稳定，暂时不要重复提交表单。</span>
            <button type="button" className="font-semibold underline" onClick={() => window.location.reload()}>重新加载</button>
          </div>
        )}
        {/* Top bar */}
        <header className={`app-topbar sticky top-0 z-30 min-h-16 items-center justify-between px-3 py-2.5 md:px-4 md:py-3 lg:px-6 ${isAppLauncher ? 'hidden' : 'flex'}`}>
          <div className="flex min-w-0 flex-1 items-center gap-3 md:hidden">
            <button
              type="button"
              onClick={() => navigate(mobileContextReturnPath || '/apps')}
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl"
              aria-label={mobileContextReturnPath ? '返回上一工作位置' : '返回应用中心'}
            >
              {mobileContextReturnPath
                ? <ArrowLeft className="h-5 w-5 text-slate-700" />
                : <T24AppMark decorative className="h-10 w-10 rounded-[14px]" />}
            </button>
            <div className="min-w-0">
              <p className="text-[10px] font-semibold uppercase tracking-[0.13em] text-blue-500">T24 OS</p>
              <p className="truncate text-[15px] font-bold tracking-tight text-slate-900">{currentPageLabel}</p>
            </div>
          </div>
          <button className="hidden text-slate-600 hover:text-slate-800 md:block lg:hidden" onClick={() => setSidebarOpen(true)} aria-label="打开业务导航">
            <Menu className="w-5 h-5" />
          </button>
          <nav aria-label="当前位置" className="hidden min-w-0 items-center gap-2 text-sm lg:flex">
            {activeNavSection && <>
              <span className="shrink-0 text-slate-400">{activeNavSection.label}</span>
              <ChevronRight aria-hidden="true" className="h-3.5 w-3.5 shrink-0 text-slate-300" />
            </>}
            <span className="truncate font-semibold text-slate-800">{desktopPageLabel || currentPageLabel}</span>
          </nav>
          <div className="flex items-center gap-2">
            <MobileModuleMenu currentPath={currentPath} />
            <button
              type="button"
              onClick={() => setMobileProfileOpen(true)}
              className="flex h-11 w-11 items-center justify-center rounded-2xl border border-slate-200 bg-white text-blue-600 shadow-sm md:hidden"
              aria-label="打开我的账户"
            >
              <User className="h-4 w-4" />
            </button>
            {currentPath !== homePath && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="hidden h-9 gap-2 border-slate-200 bg-white px-2.5 text-slate-700 shadow-sm hover:border-blue-200 hover:bg-blue-50 hover:text-blue-700 md:inline-flex md:px-3"
                onClick={() => navigate(homePath)}
                aria-label="返回今日工作台"
              >
                <LayoutDashboard className="h-4 w-4" />
                <span className="hidden sm:inline">今日工作台</span>
              </Button>
            )}
            <div className="hidden md:block">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="sm" className="gap-2">
                  <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-blue-50 ring-1 ring-blue-100">
                    <User className="w-4 h-4 text-blue-600" />
                  </div>
                  <ChevronDown className="w-3 h-3 text-slate-400" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {employee && (
                  <div className="px-2 py-1.5 text-xs text-slate-500">
                    {employee.name} · {displayRole}
                  </div>
                )}
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={() => setShowChangePwd(true)}>
                  <KeyRound className="w-4 h-4 mr-2" />
                  修改密码
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={handleLogout}>
                  <LogOut className="w-4 h-4 mr-2" />
                  退出登录
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            </div>
          </div>
        </header>

        {/* Page content */}
        <main ref={mainScrollRef} className={`app-main min-h-0 min-w-0 flex-1 overflow-y-auto overflow-x-hidden ${isAppLauncher ? 'app-main-launcher p-0 md:p-4 lg:p-6' : 'px-3 pb-[calc(6.5rem+env(safe-area-inset-bottom))] pt-3 md:p-4 lg:p-6'}`}>
          {hasPageAccess ? (
            isAppLauncher
              ? <MobileAppLauncher key={`${employee?.id || 'unknown'}:${role}`} onOpenProfile={() => setMobileProfileOpen(true)} />
              : <div key={currentPath} className="mobile-route-stage">{children}</div>
          ) : (
            <div className="flex flex-col items-center justify-center h-64 text-center">
              <div className="w-16 h-16 bg-red-50 rounded-full flex items-center justify-center mb-4">
                <Lock className="w-8 h-8 text-red-400" />
              </div>
              <h2 className="text-lg font-semibold text-slate-700 mb-2">无权限访问</h2>
              <p className="text-sm text-slate-500 mb-4">您没有访问此页面的权限，请联系管理员。</p>
              <Button variant="outline" onClick={() => navigate(homePath)}>返回可用页面</Button>
            </div>
          )}
        </main>
        <MobileBottomNav onOpenProfile={() => setMobileProfileOpen(true)} hidden={isMobileDetailContext} profileOpen={mobileProfileOpen} />
      </div>

      <Dialog open={mobileProfileOpen} onOpenChange={setMobileProfileOpen}>
        <DialogContent className={`bottom-0 top-auto w-full max-w-lg translate-y-0 rounded-b-none rounded-t-[28px] border-x-0 border-b-0 px-5 pb-[max(env(safe-area-inset-bottom),1.25rem)] pt-6 ${isAppLauncher ? 'md:bottom-auto md:top-1/2 md:-translate-y-1/2 md:rounded-[28px] md:border' : 'md:hidden'}`}>
          <DialogHeader className="text-left">
            <DialogTitle>我的账户</DialogTitle>
          </DialogHeader>
          <div className="flex items-center gap-3 rounded-2xl bg-slate-50 p-4">
            <T24AppMark decorative className="h-12 w-12 shrink-0" />
            <div className="min-w-0">
              <p className="truncate font-bold text-slate-900">{employee?.name || 'T24 员工'}</p>
              <p className="mt-0.5 text-xs text-slate-500">{displayRole}</p>
            </div>
          </div>
          <div className="grid gap-2">
            <Button
              type="button"
              variant="outline"
              className="min-h-12 justify-start rounded-2xl"
              onClick={() => { setMobileProfileOpen(false); navigate('/apps'); }}
            >
              <LayoutDashboard className="mr-2 h-4 w-4" />应用中心
            </Button>
            <Button
              type="button"
              variant="outline"
              className="min-h-12 justify-start rounded-2xl"
              onClick={() => { setMobileProfileOpen(false); setShowChangePwd(true); }}
            >
              <KeyRound className="mr-2 h-4 w-4" />修改密码
            </Button>
            <PwaInstallAction />
            <Button
              type="button"
              variant="outline"
              className="min-h-12 justify-start rounded-2xl border-rose-200 text-rose-600 hover:bg-rose-50 hover:text-rose-700"
              onClick={handleLogout}
            >
              <LogOut className="mr-2 h-4 w-4" />退出登录
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Change Password Dialog */}
      <Dialog open={showChangePwd} onOpenChange={setShowChangePwd}>
        <DialogContent className="max-w-sm">
          <DialogHeader><DialogTitle>修改密码</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div>
              <Label>当前密码</Label>
              <Input type="password" value={pwdForm.current} onChange={e => setPwdForm({ ...pwdForm, current: e.target.value })} />
            </div>
            <div>
              <Label>新密码</Label>
              <Input type="password" value={pwdForm.newPwd} onChange={e => setPwdForm({ ...pwdForm, newPwd: e.target.value })} placeholder="至少8个字符" minLength={8} />
            </div>
            <div>
              <Label>确认新密码</Label>
              <Input type="password" value={pwdForm.confirm} onChange={e => setPwdForm({ ...pwdForm, confirm: e.target.value })} />
            </div>
          </div>
          <div className="flex justify-end gap-2 mt-4">
            <Button variant="outline" onClick={() => setShowChangePwd(false)}>取消</Button>
            <Button onClick={handleChangePassword} disabled={changingPwd} className="bg-blue-600 hover:bg-blue-700">
              {changingPwd ? '修改中...' : '确认修改'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
