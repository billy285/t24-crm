import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Home } from 'lucide-react';

export default function NotFound() {
  return (
    <div className="flex min-h-[100dvh] items-center justify-center bg-[#f3f6fb] px-4">
      <div className="w-full max-w-sm rounded-[28px] border border-slate-200 bg-white p-8 text-center shadow-sm">
        <h1 className="mb-4 text-6xl font-black tracking-[-0.06em] text-slate-200">404</h1>
        <p className="mb-2 text-lg font-bold text-slate-900">没有找到这个页面</p>
        <p className="mb-6 text-sm leading-6 text-slate-500">页面地址可能已变化，请返回 T24 工作台继续操作。</p>
        <Link to="/apps">
          <Button className="h-12 w-full gap-2 rounded-2xl bg-blue-600 hover:bg-blue-700">
            <Home className="w-4 h-4" />
            返回 T24 工作台
          </Button>
        </Link>
      </div>
    </div>
  );
}
