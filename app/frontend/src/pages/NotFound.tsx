import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Home } from 'lucide-react';

export default function NotFound() {
  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center">
      <div className="text-center px-4">
        <h1 className="text-6xl font-bold text-slate-300 mb-4">404</h1>
        <p className="text-lg text-slate-600 mb-6">页面未找到</p>
        <Link to="/">
          <Button className="bg-blue-600 hover:bg-blue-700 gap-2">
            <Home className="w-4 h-4" />
            返回首页
          </Button>
        </Link>
      </div>
    </div>
  );
}