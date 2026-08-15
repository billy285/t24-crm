import { useEffect, useState } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useRole, roleLabels } from '../lib/role-context';
import { pageLabels } from '../lib/permissions';
import {
  ArrowLeft, LayoutDashboard, LogOut, Menu, X, ChevronDown, User,
  Lock, KeyRound, PanelLeftClose, PanelLeftOpen, ChevronRight,
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
  appNavigationSections,
  getRoleTodayPath,
} from '@/lib/app-navigation';
import MobileAppHome, { T24AppMark } from '@/components/MobileAppHome';
import MobileBottomNav from '@/components/MobileBottomNav';
import MobileModuleMenu from '@/components/MobileModuleMenu';
import { getSafeInternalPath } from '@/lib/navigation-state';

interface LayoutProps {
  children: React.ReactNode;
}

export default function Layout({ children }: LayoutProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const currentPath = location.pathname;
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () => typeof window !== 'undefined' && window.localStorage.getItem('t24_sidebar_collapsed') === '1',
  );
  const [expandedSection, setExpandedSection] = useState<string | null>(
    () => appNavigationSections.find(section => section.paths.includes(location.pathname))?.label || '老板今日工作台',
  );
  const { employee, role, loading, isLoggedIn, isDisabled, logout, canAccess } = useRole();

  useEffect(() => {
    window.localStorage.setItem('t24_sidebar_collapsed', sidebarCollapsed ? '1' : '0');
  }, [sidebarCollapsed]);

  useEffect(() => {
    const activeSection = appNavigationSections.find(section => section.paths.includes(currentPath));
    if (activeSection) setExpandedSection(activeSection.label);
  }, [currentPath]);
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
    if (!pwdForm.newPwd || pwdForm.newPwd.length < 6) {
      toast.error('新密码至少6个字符');
      return;
    }
    if (pwdForm.newPwd !== pwdForm.confirm) {
      toast.error('两次密码输入不一致');
      return;
    }

    setChangingPwd(true);
    try {
      const token = localStorage.getItem('emp_auth_token');
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
  const visibleNavSections = appNavigationSections
    .map(section => ({
      ...section,
      items: section.paths
        .map(path => appNavigationItems.find(item => item.path === path))
        .filter((item): item is (typeof appNavigationItems)[number] => !!item && canAccess(item.path)),
    }))
    .filter(section => section.items.length > 0);

  const displayRole = employee
    ? (roleLabels[employee.role] || employee.role)
    : '管理员模式';
  const homePath = getRoleTodayPath(role);
  const isAppLauncher = currentPath === '/apps';
  const currentSearch = new URLSearchParams(location.search);
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
    <div className="app-shell mobile-app-layout flex h-screen overflow-hidden">
      {/* Mobile overlay */}
      {sidebarOpen && (
        <div className="fixed inset-0 z-40 hidden bg-black/50 md:block lg:hidden" onClick={() => setSidebarOpen(false)} />
      )}

      {/* Sidebar */}
      <aside className={`app-sidebar fixed inset-y-0 left-0 z-50 hidden w-[248px] transform flex-col text-white transition-[width,transform] duration-200 md:flex ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'} lg:sticky lg:top-0 lg:h-screen lg:translate-x-0 ${sidebarCollapsed ? 'lg:w-[72px]' : 'lg:w-[248px]'}`}>
        <div className={`border-b border-white/10 px-4 py-5 ${sidebarCollapsed ? 'lg:px-3' : ''}`}>
          <div className="flex items-center justify-between">
            <Link to={homePath} className={`flex min-w-0 items-center gap-3 ${sidebarCollapsed ? 'lg:w-full lg:justify-center' : ''}`} onClick={() => setSidebarOpen(false)}>
              <img
                src="/t2-marketing-logo.png?v=t2-20260709b"
                alt="T24 Marketing"
                className="h-10 w-10 flex-shrink-0 rounded-xl border border-white/15 bg-white object-cover shadow-md shadow-black/20"
              />
              <div className={`min-w-0 ${sidebarCollapsed ? 'lg:hidden' : ''}`}>
                <h1 className="truncate text-[17px] font-semibold leading-tight tracking-tight">T24 Marketing</h1>
                <p className="mt-1 truncate text-[11px] tracking-[0.08em] text-slate-400">BUSINESS OPERATING SYSTEM</p>
              </div>
            </Link>
            <button className="lg:hidden text-slate-400 hover:text-white" onClick={() => setSidebarOpen(false)}>
              <X className="w-5 h-5" />
            </button>
          </div>
          {employee && (
            <p className={`mt-3 rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-xs text-slate-300 ${sidebarCollapsed ? 'lg:hidden' : ''}`}>{employee.name} · {displayRole}</p>
          )}
        </div>

        <nav className="app-sidebar-nav flex-1 overflow-y-auto px-3 py-3">
          <div className={`px-3 pb-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500 ${sidebarCollapsed ? 'lg:sr-only' : ''}`}>
            业务中心
          </div>
          <div className="space-y-1.5">
            {visibleNavSections.map((section) => {
              const SectionIcon = section.icon;
              const primaryItem = section.items[0];
              const childItems = section.items.slice(1);
              const isSectionActive = section.paths.includes(currentPath);
              const isExpanded = expandedSection === section.label;
              return (
                <div key={section.label} className="space-y-1">
                  <div className={`group flex items-center rounded-lg ${isSectionActive ? 'bg-white/[0.06]' : 'hover:bg-white/[0.04]'}`}>
                    <Link
                      to={primaryItem.path}
                      onClick={() => {
                        setExpandedSection(section.label);
                        setSidebarOpen(false);
                      }}
                      title={sidebarCollapsed ? section.label : undefined}
                      className={`app-nav-item relative flex min-w-0 flex-1 items-center gap-3 rounded-lg px-3 py-2.5 text-sm ${
                        currentPath === primaryItem.path
                          ? 'app-nav-item-active text-white'
                          : isSectionActive ? 'text-white' : 'text-slate-300 hover:text-white'
                      } ${sidebarCollapsed ? 'lg:justify-center lg:gap-0 lg:px-2' : ''}`}
                    >
                      <SectionIcon className="h-4 w-4 flex-shrink-0" />
                      <span className={`truncate font-medium ${sidebarCollapsed ? 'lg:hidden' : ''}`}>{section.label}</span>
                    </Link>
                    {childItems.length > 0 && !sidebarCollapsed && (
                      <button
                        type="button"
                        onClick={() => setExpandedSection(value => value === section.label ? null : section.label)}
                        className="mr-1 block rounded-lg p-2 text-slate-400 hover:bg-white/10 hover:text-white"
                        aria-label={`${isExpanded ? '收起' : '展开'}${section.label}`}
                      >
                        <ChevronRight className={`h-3.5 w-3.5 transition-transform ${isExpanded ? 'rotate-90' : ''}`} />
                      </button>
                    )}
                  </div>
                  {childItems.length > 0 && isExpanded && (
                    <div className={`space-y-0.5 border-l border-white/10 pl-3 ${sidebarCollapsed ? 'lg:hidden' : ''}`}>
                      {childItems.map(item => {
                        const isActive = currentPath === item.path;
                        return (
                          <Link
                            key={item.path}
                            to={item.path}
                            onClick={() => setSidebarOpen(false)}
                            className={`flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] ${isActive ? 'bg-blue-500/20 font-medium text-blue-100' : 'text-slate-400 hover:bg-white/[0.06] hover:text-white'}`}
                          >
                            <item.icon className="h-3.5 w-3.5 flex-shrink-0" />
                            <span>{item.label}</span>
                          </Link>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          {!sidebarCollapsed && (
            <p className="mt-4 border-t border-white/[0.07] px-3 pt-3 text-[11px] leading-5 text-slate-500">
              先进入业务中心，再按需展开明细。日常不需要遍历所有页面。
            </p>
          )}
        </nav>

        <div className="border-t border-white/10 p-3">
          <button
            type="button"
            onClick={() => setSidebarCollapsed((value) => !value)}
            className={`mb-1 hidden w-full items-center rounded-xl px-3 py-2.5 text-sm text-slate-300 hover:bg-white/[0.07] hover:text-white lg:flex ${sidebarCollapsed ? 'justify-center' : 'gap-3'}`}
            aria-label={sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'}
            title={sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'}
          >
            {sidebarCollapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
            <span className={sidebarCollapsed ? 'lg:hidden' : ''}>收起侧边栏</span>
          </button>
          <button
            onClick={handleLogout}
            className={`flex w-full items-center rounded-xl px-3 py-2.5 text-sm text-slate-300 hover:bg-white/[0.07] hover:text-white ${sidebarCollapsed ? 'justify-center' : 'gap-3'}`}
            title={sidebarCollapsed ? '退出登录' : undefined}
          >
            <LogOut className="w-4 h-4" />
            <span className={sidebarCollapsed ? 'lg:hidden' : ''}>退出登录</span>
          </button>
        </div>
      </aside>

      {/* Main content */}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        {isOffline && (
          <div className="sticky top-0 z-40 flex items-center justify-between gap-3 bg-amber-50 px-4 py-2 text-xs text-amber-800 shadow-sm">
            <span>当前网络连接不稳定，暂时不要重复提交表单。</span>
            <button type="button" className="font-semibold underline" onClick={() => window.location.reload()}>重新加载</button>
          </div>
        )}
        {/* Top bar */}
        <header className={`app-topbar sticky top-0 z-30 min-h-16 items-center justify-between px-3 py-2.5 md:px-4 md:py-3 lg:px-6 ${isAppLauncher ? 'hidden md:flex' : 'flex'}`}>
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
          <div className="hidden items-center gap-3 lg:flex">
            <span className="h-6 w-1 rounded-full bg-blue-600" />
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">T24 Marketing</p>
              <p className="text-sm font-semibold text-slate-800">{currentPageLabel}</p>
            </div>
          </div>
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
        <main className={`app-main min-h-0 min-w-0 flex-1 overflow-y-auto overflow-x-hidden ${isAppLauncher ? 'app-main-launcher p-0 md:p-4 lg:p-6' : 'px-3 pb-[calc(6.5rem+env(safe-area-inset-bottom))] pt-3 md:p-4 lg:p-6'}`}>
          {hasPageAccess ? (
            isAppLauncher
              ? <MobileAppHome onOpenProfile={() => setMobileProfileOpen(true)} />
              : children
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
        <DialogContent className="bottom-0 top-auto w-full max-w-lg translate-y-0 rounded-b-none rounded-t-[28px] border-x-0 border-b-0 px-5 pb-[max(env(safe-area-inset-bottom),1.25rem)] pt-6 md:hidden">
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
              <Input type="password" value={pwdForm.newPwd} onChange={e => setPwdForm({ ...pwdForm, newPwd: e.target.value })} placeholder="至少6个字符" />
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
