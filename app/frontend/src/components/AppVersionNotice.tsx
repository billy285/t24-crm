import { useEffect } from 'react';
import { toast } from 'sonner';
import { applyAppUpdate, installAppVersionChecks, useAppVersion } from '@/lib/app-version';

export default function AppVersionNotice() {
  const version = useAppVersion();
  useEffect(installAppVersionChecks, []);
  if (!version.available) return null;
  return <aside className="app-version-notice" aria-label="版本更新">
    <span>新版本已准备好</span>
    <button type="button" onClick={() => {
      if (!applyAppUpdate()) toast.info('请先保存或取消当前编辑，再更新版本');
    }}>更新</button>
  </aside>;
}
