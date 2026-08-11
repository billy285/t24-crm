import { AlertTriangle, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';

type PageLoadStateProps = {
  error?: string | null;
  loading?: boolean;
  message?: string;
  onRetry?: () => void;
};

export default function PageLoadState({
  error,
  loading = false,
  message = '正在读取最新数据…',
  onRetry,
}: PageLoadStateProps) {
  if (error) {
    return (
      <div className="mx-auto flex min-h-[320px] max-w-xl items-center justify-center p-6">
        <div className="w-full rounded-xl border border-red-200 bg-red-50 p-6 text-center">
          <AlertTriangle className="mx-auto h-8 w-8 text-red-600" />
          <h2 className="mt-3 font-semibold text-slate-900">数据暂时无法加载</h2>
          <p className="mt-2 text-sm text-slate-600">{error}</p>
          {onRetry && (
            <Button className="mt-4 gap-2" onClick={onRetry}>
              <RefreshCw className="h-4 w-4" />
              重新加载
            </Button>
          )}
        </div>
      </div>
    );
  }

  if (!loading) return null;

  return (
    <div className="mx-auto w-full max-w-[1600px] space-y-4 animate-pulse" aria-live="polite" aria-busy="true">
      <div className="flex items-center justify-between gap-4">
        <div className="space-y-2">
          <div className="h-3 w-28 rounded bg-slate-200" />
          <div className="h-7 w-48 rounded bg-slate-200" />
          <div className="h-3 w-72 max-w-full rounded bg-slate-100" />
        </div>
        <div className="h-10 w-28 rounded-lg bg-slate-200" />
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {[0, 1, 2, 3].map(item => <div key={item} className="h-28 rounded-xl border border-slate-200 bg-white" />)}
      </div>
      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <div className="h-10 rounded-lg bg-slate-100" />
        <div className="mt-4 space-y-3">
          {[0, 1, 2, 3, 4].map(item => <div key={item} className="h-12 rounded-lg bg-slate-50" />)}
        </div>
      </div>
      <div className="sr-only">
        <p>{message}</p>
        <p>数据加载完成后会自动显示</p>
      </div>
    </div>
  );
}
