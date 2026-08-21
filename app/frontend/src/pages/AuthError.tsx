import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { AlertCircle } from 'lucide-react';

export default function AuthErrorPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const [countdown, setCountdown] = useState(3);
  const errorMessage =
    searchParams.get('msg') ||
    '登录信息无效或已经过期，请重新登录。';

  useEffect(() => {
    // Countdown logic
    const timer = setInterval(() => {
      setCountdown(prev => {
        if (prev <= 1) {
          clearInterval(timer);
          navigate('/login', { replace: true });
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    // Clean up timer
    return () => clearInterval(timer);
  }, [navigate]);

  const handleReturnHome = () => {
    navigate('/login', { replace: true });
  };

  return (
    <div className="flex min-h-[100dvh] flex-col items-center justify-center bg-[#f3f6fb] p-6 text-center">
      <div className="w-full max-w-sm space-y-6 rounded-[28px] border border-slate-200 bg-white p-7 shadow-sm">
        <div className="space-y-4">
          {/* Error icon */}
          <div className="flex justify-center">
            <div className="relative">
              <AlertCircle
                className="relative h-12 w-12 text-rose-500"
                strokeWidth={1.5}
              />
            </div>
          </div>

          {/* Error title */}
          <h1 className="text-2xl font-bold text-gray-800">
            登录状态异常
          </h1>

          {/* Error description */}
          <p className="text-base text-muted-foreground">{errorMessage}</p>

          {/* Countdown提示 */}
          <div className="pt-2">
            <p className="text-sm text-gray-500">
              {countdown > 0 ? `${countdown} 秒后自动返回登录页` : '正在返回登录页…'}
            </p>
          </div>
        </div>

        {/* Return to home button */}
        <div className="flex justify-center pt-2">
          <Button onClick={handleReturnHome} className="px-6">
            返回登录页
          </Button>
        </div>
      </div>
    </div>
  );
}
