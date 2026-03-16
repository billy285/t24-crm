import { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useRole, roleLabels } from '../lib/role-context';
import { pageLabels } from '../lib/permissions';
import {
  LayoutDashboard, Users, PhoneCall, Handshake, DollarSign,
  ListTodo, LogOut, Menu, X, ChevronDown, User, UserCog, Settings,
  ShieldCheck, Lock, KeyRound, ClipboardList, ListTree
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
import Login from '../pages/Login';

interface LayoutProps {
  children: React.ReactNode;
}

const allNavItems = [
  { path: '/', label: '仪表盘', icon: LayoutDashboard },
  { path: '/customers', label: '客户管理', icon: Users },
  { path: '/sales', label: '销售跟进', icon: PhoneCall },
  { path: '/deals', label: '成交管理', icon: Handshake },
  { path: '/finance', label: '财务管理', icon: DollarSign },
  { path: '/tasks', label: '任务协作', icon: ListTodo },
  { path: '/service-board', label: '服务进度看板', icon: ClipboardList },
  { path: '/callbacks', label: '电话回访', icon: PhoneCall },
  { path: '/employees', label: '员工管理', icon: UserCog },
  { path: '/settings', label: '系统设置', icon: Settings },
  { path: '/system-options', label: '选项管理', icon: ListTree },
  { path: '/permissions', label: '权限设置', icon: ShieldCheck },
];

export default function Layout({ children }: LayoutProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const { employee, role, loading, isLoggedIn, isDisabled, login, logout, canAccess } = useRole();
  const [showChangePwd, setShowChangePwd] = useState(false);
  const [pwdForm, setPwdForm] = useState({ current: '', newPwd: '', confirm: '' });
  const [changingPwd, setChangingPwd] = useState(false);

  const handleLogout = () => {
    logout();
    navigate('/');
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

  const handleLoginSuccess = (token: string, emp: any) => {
    login(token, emp);
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
      </div>
    );
  }

  if (!isLoggedIn && !isDisabled) {
    return <Login onLoginSuccess={handleLoginSuccess} />;
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
  const currentPath = location.pathname;
  const hasPageAccess = canAccess(currentPath);

  // Filter nav items based on role permissions
  const navItems = allNavItems.filter(item => canAccess(item.path));

  const displayRole = employee
    ? (roleLabels[employee.role] || employee.role)
    : '管理员模式';

  return (
    <div className="min-h-screen bg-slate-50 flex">
      {/* Mobile overlay */}
      {sidebarOpen && (
        <div className="fixed inset-0 bg-black/50 z-40 lg:hidden" onClick={() => setSidebarOpen(false)} />
      )}

      {/* Sidebar */}
      <aside className={`fixed lg:static inset-y-0 left-0 z-50 w-64 bg-slate-800 text-white transform transition-transform duration-200 ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'} lg:translate-x-0 flex flex-col`}>
        <div className="p-4 border-b border-slate-700">
          <div className="flex items-center justify-between">
            <h1 className="text-lg font-bold">T24 CRM</h1>
            <button className="lg:hidden text-slate-400 hover:text-white" onClick={() => setSidebarOpen(false)}>
              <X className="w-5 h-5" />
            </button>
          </div>
          {employee && (
            <p className="text-xs text-slate-400 mt-1">{employee.name} · {displayRole}</p>
          )}
        </div>

        <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
          {navItems.map((item) => {
            const isActive = location.pathname === item.path;
            return (
              <Link
                key={item.path}
                to={item.path}
                onClick={() => setSidebarOpen(false)}
                className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${
                  isActive ? 'bg-blue-600 text-white' : 'text-slate-300 hover:bg-slate-700 hover:text-white'
                }`}
              >
                <item.icon className="w-4 h-4 flex-shrink-0" />
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="p-3 border-t border-slate-700">
          <button
            onClick={handleLogout}
            className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-slate-300 hover:bg-slate-700 hover:text-white w-full transition-colors"
          >
            <LogOut className="w-4 h-4" />
            退出登录
          </button>
        </div>
      </aside>

      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top bar */}
        <header className="bg-white border-b border-slate-200 px-4 py-3 flex items-center justify-between sticky top-0 z-30">
          <button className="lg:hidden text-slate-600 hover:text-slate-800" onClick={() => setSidebarOpen(true)}>
            <Menu className="w-5 h-5" />
          </button>
          <div className="text-sm text-slate-500 hidden lg:block">
            {pageLabels[currentPath] || allNavItems.find(n => n.path === currentPath)?.label || ''}
          </div>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="sm" className="gap-2">
                <div className="w-7 h-7 rounded-full bg-blue-100 flex items-center justify-center">
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
        </header>

        {/* Page content */}
        <main className="flex-1 p-4 lg:p-6 overflow-auto">
          {hasPageAccess ? children : (
            <div className="flex flex-col items-center justify-center h-64 text-center">
              <div className="w-16 h-16 bg-red-50 rounded-full flex items-center justify-center mb-4">
                <Lock className="w-8 h-8 text-red-400" />
              </div>
              <h2 className="text-lg font-semibold text-slate-700 mb-2">无权限访问</h2>
              <p className="text-sm text-slate-500 mb-4">您没有访问此页面的权限，请联系管理员。</p>
              <Button variant="outline" onClick={() => navigate('/')}>返回首页</Button>
            </div>
          )}
        </main>
      </div>

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