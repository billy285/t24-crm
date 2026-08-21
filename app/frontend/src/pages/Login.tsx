import { useState } from 'react';
import { Mail, Lock, Eye, EyeOff, LogIn, Loader2, ShieldCheck } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { toast } from 'sonner';
import { client } from '@/lib/api';

interface LoginProps {
  onLoginSuccess: (token: string, employee: any, rememberMe: boolean) => void | Promise<void>;
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
        let persistentLoginReady = rememberMe;
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
          // A remembered login is only safe when the HttpOnly refresh cookie was
          // established. Downgrade to this browser session if that step fails.
          persistentLoginReady = false;
          if (rememberMe) toast.warning('长期登录暂不可用，本次仅保持到当前浏览器会话结束。');
        }
        toast.success(`欢迎回来，${data.employee.name}！`);
        await onLoginSuccess(data.token, data.employee, persistentLoginReady);
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
    <div className="flex min-h-[100dvh] items-center justify-center bg-[#f3f6fb] pl-[max(1rem,env(safe-area-inset-left))] pr-[max(1rem,env(safe-area-inset-right))] py-[max(1.5rem,env(safe-area-inset-top))]">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-3 px-1">
          <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-[18px] border border-blue-100 bg-white p-1 shadow-sm">
            <img
              src="/t2-marketing-logo.png?v=t2-20260709b"
              alt="T24 Marketing"
              className="h-full w-full rounded-[14px] object-cover"
            />
          </div>
          <div className="min-w-0">
            <p className="text-[11px] font-bold uppercase tracking-[0.16em] text-blue-600">T24 OS</p>
            <h1 className="mt-1 truncate text-lg font-bold tracking-tight text-slate-950">T24 Marketing 工作台</h1>
          </div>
        </div>

        <div className="rounded-[28px] border border-slate-200 bg-white p-5 shadow-[0_24px_60px_-42px_rgba(15,23,42,0.45)] sm:p-7">
          <div className="mb-6">
            <h2 className="text-2xl font-black tracking-[-0.035em] text-slate-950">登录工作台</h2>
            <p className="mt-2 text-sm leading-6 text-slate-500">进入与你岗位对应的客户、销售、交付或财务工作区。</p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-5">
            <div className="space-y-2">
              <Label className="text-sm font-semibold text-slate-700">邮箱地址</Label>
              <div className="relative">
                <Mail className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <Input
                  type="email"
                  placeholder="请输入邮箱"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="h-12 rounded-2xl border-slate-200 bg-slate-50 pl-11 text-base text-slate-950 placeholder:text-slate-400 focus:bg-white"
                  autoComplete="email"
                  inputMode="email"
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label className="text-sm font-semibold text-slate-700">密码</Label>
              <div className="relative">
                <Lock className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <Input
                  type={showPassword ? 'text' : 'password'}
                  placeholder="请输入密码"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="h-12 rounded-2xl border-slate-200 bg-slate-50 pl-11 pr-12 text-base text-slate-950 placeholder:text-slate-400 focus:bg-white"
                  autoComplete="current-password"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  aria-label={showPassword ? '隐藏密码' : '显示密码'}
                  className="absolute right-0 top-1/2 flex h-12 w-12 -translate-y-1/2 items-center justify-center rounded-2xl text-slate-400 hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
                >
                  {showPassword ? <EyeOff className="h-5 w-5" /> : <Eye className="h-5 w-5" />}
                </button>
              </div>
            </div>

            <label className="flex min-h-11 items-center gap-3 rounded-2xl bg-slate-50 px-3 text-sm text-slate-600">
                <input
                  type="checkbox"
                  checked={rememberMe}
                  onChange={(e) => setRememberMe(e.target.checked)}
                  className="h-5 w-5 rounded border-slate-300 accent-blue-600"
                />
                <span><span className="font-semibold text-slate-800">保持登录</span><span className="block text-[11px] text-slate-500">仅限你信任的个人设备</span></span>
            </label>

              <Button
                type="submit"
                disabled={loading}
                className="h-12 w-full rounded-2xl bg-blue-600 text-sm font-bold text-white shadow-sm hover:bg-blue-700"
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
          </form>

          <div className="mt-5 flex items-start gap-2 border-t border-slate-100 pt-4 text-xs leading-5 text-slate-500">
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
            登录后只显示当前账号有权限的业务应用和数据。
          </div>
        </div>

        <p className="mt-5 pb-[max(0rem,env(safe-area-inset-bottom))] text-center text-xs text-slate-400">
          © T24 Marketing · 内部员工系统
        </p>
      </div>
    </div>
  );
}
