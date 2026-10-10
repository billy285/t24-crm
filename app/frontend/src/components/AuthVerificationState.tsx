import { useState } from 'react';
import { RefreshCw, ShieldCheck } from 'lucide-react';
import { Button } from '@/components/ui/button';

export default function AuthVerificationState({ message, onRetry }: { message: string; onRetry: () => Promise<void> }) {
  const [retrying, setRetrying] = useState(false);
  const retry = async () => {
    if (retrying) return;
    setRetrying(true);
    try { await onRetry(); } finally { setRetrying(false); }
  };

  return (
    <main className="flex min-h-[100dvh] items-center justify-center bg-[#f3f6fb] px-5 py-8" aria-busy={retrying}>
      <section className="w-full max-w-sm rounded-3xl border border-slate-200 bg-white p-6 text-center shadow-sm" aria-labelledby="auth-verification-heading">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-blue-50 text-blue-600">
          <ShieldCheck className="h-6 w-6" aria-hidden="true" />
        </div>
        <h1 id="auth-verification-heading" className="mt-5 text-lg font-bold text-slate-950">暂时无法验证登录</h1>
        <p className="mt-2 text-sm leading-6 text-slate-500" role="status">{message}</p>
        <Button className="mt-5 h-12 w-full rounded-2xl" onClick={() => void retry()} disabled={retrying}>
          <RefreshCw className={`mr-2 h-4 w-4${retrying ? ' animate-spin' : ''}`} aria-hidden="true" />
          {retrying ? '正在验证…' : '重新验证'}
        </Button>
      </section>
    </main>
  );
}
