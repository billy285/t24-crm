import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';

export default function AuthCallback() {
  const navigate = useNavigate();

  useEffect(() => {
    navigate('/login', {
      replace: true,
      state: { message: '系统已切换为员工账号登录，请使用邮箱和密码登录。' },
    });
  }, [navigate]);

  return (
    <div className="flex min-h-[100dvh] items-center justify-center bg-[#f3f6fb] px-6">
      <div className="w-full max-w-sm rounded-[28px] border border-slate-200 bg-white p-8 text-center shadow-sm">
        <div className="mx-auto mb-4 h-10 w-10 animate-spin rounded-full border-2 border-blue-100 border-b-blue-600" />
        <p className="font-semibold text-slate-800">正在打开登录页…</p>
      </div>
    </div>
  );
}
