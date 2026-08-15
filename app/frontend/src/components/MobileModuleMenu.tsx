import { Check, ChevronRight, Grid2X2, LayoutDashboard } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import {
  appNavigationItems,
  mobileBusinessApps,
  partnerBusinessApp,
} from '@/lib/app-navigation';
import { useRole } from '@/lib/role-context';
import { cn } from '@/lib/utils';
import { useState } from 'react';

const appTones = {
  indigo: 'bg-indigo-50 text-indigo-600 ring-indigo-100',
  blue: 'bg-blue-50 text-blue-600 ring-blue-100',
  cyan: 'bg-cyan-50 text-cyan-600 ring-cyan-100',
  violet: 'bg-violet-50 text-violet-600 ring-violet-100',
  emerald: 'bg-emerald-50 text-emerald-600 ring-emerald-100',
  slate: 'bg-slate-100 text-slate-600 ring-slate-200',
} as const;

export default function MobileModuleMenu({ currentPath }: { currentPath: string }) {
  const navigate = useNavigate();
  const { role, canAccess } = useRole();
  const [open, setOpen] = useState(false);
  const definitions = role === 'sales_partner' ? [partnerBusinessApp] : mobileBusinessApps;
  const currentApp = definitions.find(app => app.paths.includes(currentPath));
  const pages = currentApp?.paths
    .map(path => appNavigationItems.find(item => item.path === path))
    .filter((item): item is (typeof appNavigationItems)[number] => Boolean(item && canAccess(item.path))) || [];

  if (!currentApp || pages.length < 2) return null;

  const AppIcon = currentApp.icon;
  const navigateTo = (path: string) => {
    setOpen(false);
    navigate(path);
  };

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="flex h-11 w-11 items-center justify-center rounded-2xl border border-slate-200 bg-white text-blue-600 shadow-sm md:hidden"
        aria-label={`打开${currentApp.label}功能菜单`}
      >
        <Grid2X2 className="h-4 w-4" />
      </button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="bottom-0 top-auto w-full max-w-lg translate-y-0 rounded-b-none rounded-t-[28px] border-x-0 border-b-0 px-5 pb-[max(env(safe-area-inset-bottom),1.25rem)] pt-6 md:hidden">
          <DialogHeader className="text-left">
            <DialogTitle className="flex items-center gap-3">
              <span className={cn('flex h-11 w-11 items-center justify-center rounded-2xl ring-1', appTones[currentApp.tone])}>
                <AppIcon className="h-5 w-5" />
              </span>
              <span>
                <span className="block text-lg font-bold text-slate-950">{currentApp.label}</span>
                <span className="mt-1 block text-xs font-normal text-slate-500">{currentApp.description}</span>
              </span>
            </DialogTitle>
          </DialogHeader>

          <div className="grid gap-2">
            {pages.map(item => {
              const ItemIcon = item.icon;
              const isCurrent = item.path === currentPath;
              return (
                <button
                  key={item.path}
                  type="button"
                  onClick={() => navigateTo(item.path)}
                  className={cn(
                    'flex min-h-14 w-full items-center gap-3 rounded-2xl border px-4 text-left transition-colors',
                    isCurrent
                      ? 'border-blue-200 bg-blue-50 text-blue-800'
                      : 'border-slate-200 bg-white text-slate-800 active:bg-slate-50',
                  )}
                >
                  <ItemIcon className="h-4 w-4 shrink-0" />
                  <span className="min-w-0 flex-1 truncate text-sm font-semibold">{item.label}</span>
                  {isCurrent ? <Check className="h-4 w-4 shrink-0" /> : <ChevronRight className="h-4 w-4 shrink-0 text-slate-300" />}
                </button>
              );
            })}
          </div>

          <Button type="button" variant="outline" className="min-h-12 rounded-2xl" onClick={() => navigateTo('/apps')}>
            <LayoutDashboard className="mr-2 h-4 w-4" />返回全部应用
          </Button>
        </DialogContent>
      </Dialog>
    </>
  );
}
