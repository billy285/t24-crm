import { useState, useSyncExternalStore } from 'react';
import { Download, Share2, Smartphone } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import {
  getPwaInstallServerSnapshot,
  getPwaInstallSnapshot,
  promptPwaInstall,
  subscribePwaInstall,
} from '@/lib/pwa-install';

export default function PwaInstallAction() {
  const installState = useSyncExternalStore(
    subscribePwaInstall,
    getPwaInstallSnapshot,
    getPwaInstallServerSnapshot,
  );
  const [showHelp, setShowHelp] = useState(false);

  if (installState.isStandalone) return null;

  const handleInstall = async () => {
    if (!installState.canPrompt) {
      setShowHelp(value => !value);
      return;
    }

    const outcome = await promptPwaInstall();
    if (outcome === 'accepted') toast.success('T24 OS 正在添加到手机桌面');
    if (outcome === 'dismissed') toast.info('已取消安装，稍后仍可从“我的账户”重新安装。');
  };

  return (
    <div className="rounded-2xl border border-blue-100 bg-blue-50/50 p-3">
      <Button
        type="button"
        variant="outline"
        className="min-h-12 w-full justify-start rounded-2xl border-blue-200 bg-white text-blue-700 hover:bg-blue-50 hover:text-blue-800"
        onClick={() => void handleInstall()}
      >
        <Download className="mr-2 h-4 w-4" />安装 T24 OS 到手机
      </Button>
      <p className="mt-2 px-1 text-xs leading-5 text-slate-500">
        安装后从手机桌面独立打开；业务数据仍需联网读取，不保存在离线缓存中。
      </p>
      {showHelp ? (
        <div className="mt-3 rounded-xl bg-white p-3 text-xs leading-5 text-slate-600 shadow-sm" role="status">
          {installState.isIos ? (
            <>
              <p className="flex items-center gap-2 font-semibold text-slate-800"><Share2 className="h-4 w-4 text-blue-600" />iPhone / iPad 安装方法</p>
              <ol className="mt-2 list-decimal space-y-1 pl-5">
                <li>请使用 Safari 打开当前系统。</li>
                <li>点击底部“分享”按钮。</li>
                <li>选择“添加到主屏幕”，再确认添加。</li>
              </ol>
            </>
          ) : (
            <>
              <p className="flex items-center gap-2 font-semibold text-slate-800"><Smartphone className="h-4 w-4 text-blue-600" />安装提示暂未出现</p>
              <p className="mt-2">请使用最新版 Chrome 或 Edge 打开，并从浏览器菜单选择“安装应用”或“添加到主屏幕”。</p>
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}
