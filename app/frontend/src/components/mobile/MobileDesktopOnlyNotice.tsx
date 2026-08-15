import { ArrowLeft, MonitorSmartphone, ShieldCheck } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';

interface MobileDesktopOnlyNoticeProps {
  title: string;
  description: string;
  safeItems?: string[];
}

export default function MobileDesktopOnlyNotice({
  title,
  description,
  safeItems = ['手机端入口已隐藏', '直接访问不会显示管理按钮', '桌面端原有功能保持不变'],
}: MobileDesktopOnlyNoticeProps) {
  const navigate = useNavigate();

  return (
    <section
      className="mx-auto max-w-md rounded-[24px] border border-blue-100 bg-gradient-to-br from-blue-50 via-white to-slate-50 p-5 shadow-sm md:hidden"
      data-testid="mobile-desktop-only"
      aria-labelledby="mobile-desktop-only-title"
    >
      <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-blue-600 text-white shadow-sm">
        <MonitorSmartphone className="h-6 w-6" />
      </span>
      <h1 id="mobile-desktop-only-title" className="mt-4 text-xl font-bold tracking-tight text-slate-950">{title}</h1>
      <p className="mt-2 text-sm leading-6 text-slate-600">{description}</p>
      <div className="mt-4 space-y-2 rounded-2xl border border-slate-200 bg-white/90 p-3">
        {safeItems.map(item => (
          <div key={item} className="flex items-start gap-2 text-xs leading-5 text-slate-600">
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
            <span>{item}</span>
          </div>
        ))}
      </div>
      <Button type="button" variant="outline" className="mt-4 w-full rounded-2xl" onClick={() => navigate('/apps')}>
        <ArrowLeft className="h-4 w-4" />返回手机工作台
      </Button>
    </section>
  );
}
