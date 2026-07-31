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
    <div className="flex min-h-[320px] items-center justify-center p-6">
      <div className="text-center">
        <div className="mx-auto h-9 w-9 animate-spin rounded-full border-b-2 border-blue-600" />
        <p className="mt-4 text-sm text-slate-500">{message}</p>
        <p className="mt-1 text-xs text-slate-400">请勿重复刷新，数据加载完成后会自动显示</p>
      </div>
    </div>
  );
}
