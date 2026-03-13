import { useState } from 'react';
import { Mail, Lock, Eye, EyeOff, LogIn, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { toast } from 'sonner';
import { client } from '@/lib/api';

interface LoginProps {
  onLoginSuccess: (token: string, employee: any) => void;
}

export default function Login({ onLoginSuccess }: LoginProps) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(true);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim()) {
      toast.error('请输入邮箱');
      return;
    }
    if (!password.trim()) {
      toast.error('请输入密码');
      return;
    }

    setLoading(true);
    try {
      const response = await client.apiCall.invoke({
        url: '/api/v1/emp-auth/login',
        method: 'POST',
        data: { email: email.trim(), username: email.trim(), password },
      });

      const data = response.data;
      if (data?.token && data?.employee) {
        // 设置 HttpOnly Refresh Token Cookie（根据 rememberMe 设置持久期或会话期）
        try {
          await client.apiCall.invoke({
            url: '/api/v1/emp-auth/set_refresh',
            method: 'POST',
            data: { remember_me: rememberMe },
            options: {
              headers: { Authorization: `Bearer ${data.token}` },
              withCredentials: true,
            },
          });
        } catch {
          // 忽略 Cookie 设置失败，仍然允许本次登录
        }
        toast.success(`欢迎回来，${data.employee.name}！`);
        onLoginSuccess(data.token, data.employee);
      } else {
        toast.error('登录失败，请重试');
      }
    } catch (err: any) {
      const detail =
        err?.data?.detail ||
        err?.response?.data?.detail ||
        err?.message ||
        '登录失败';
      toast.error(detail);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-blue-950 to-slate-900 flex items-center justify-center p-4">
      {/* Background decorations */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute -top-40 -right-40 w-80 h-80 bg-blue-500/10 rounded-full blur-3xl" />
        <div className="absolute -bottom-40 -left-40 w-80 h-80 bg-indigo-500/10 rounded-full blur-3xl" />
      </div>

      <div className="relative w-full max-w-md">
        {/* Logo & Title */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 bg-blue-600 rounded-2xl shadow-lg shadow-blue-600/30 mb-4">
            <span className="text-2xl font-bold text-white">T24</span>
          </div>
          <h1 className="text-2xl font-bold text-white mb-1">T24 客户管理系统</h1>
          <p className="text-slate-400 text-sm">适合美国华人餐厅/实体商家的一站式CRM</p>
        </div>

        {/* Login Card */}
        <div className="bg-white/5 backdrop-blur-xl border border-white/10 rounded-2xl p-8 shadow-2xl">
          <h2 className="text-lg font-semibold text-white mb-6">员工登录</h2>

          <form onSubmit={handleSubmit} className="space-y-5">
            <div className="space-y-2">
              <Label className="text-slate-300 text-sm">邮箱地址</Label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                <Input
                  type="email"
                  placeholder="请输入邮箱"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="pl-10 bg-white/5 border-white/10 text-white placeholder:text-slate-500 focus:border-blue-500 focus:ring-blue-500/20"
                  autoComplete="email"
                  autoFocus
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label className="text-slate-300 text-sm">密码</Label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                <Input
                  type={showPassword ? 'text' : 'password'}
                  placeholder="请输入密码"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="pl-10 pr-10 bg-white/5 border-white/10 text-white placeholder:text-slate-500 focus:border-blue-500 focus:ring-blue-500/20"
                  autoComplete="current-password"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-300 transition-colors"
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            <div className="flex items-center justify-between">
              <label className="flex items-center gap-2 text-slate-300 text-xs">
                <input
                  type="checkbox"
                  checked={rememberMe}
                  onChange={(e) => setRememberMe(e.target.checked)}
                  className="rounded border-white/20 bg-white/10"
                />
                保持登录
              </label>
              <Button
                type="submit"
                disabled={loading}
                className="bg-blue-600 hover:bg-blue-700 text-white h-11 text-sm font-medium shadow-lg shadow-blue-600/25 transition-all"
              >
                {loading ? (
                  <>
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    登录中...
                  </>
                ) : (
                  <>
                    <LogIn className="w-4 h-4 mr-2" />
                    登录
                  </>
                )}
              </Button>
            </div>
          </form>
        </div>

        {/* Footer */}
        <p className="text-center text-xs text-slate-600 mt-6">
          © 2024 T24 CRM · 员工专用系统
        </p>
      </div>
    </div>
  );
}