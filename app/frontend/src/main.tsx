import { createRoot } from 'react-dom/client';
import './index.css';
import './styles/t24-design-system.css';
import { loadRuntimeConfig } from './lib/config.ts';
import { initializePwaInstallCapture, installViteChunkRecovery, registerOnlineFirstServiceWorker } from './lib/pwa-install.ts';

initializePwaInstallCapture();
installViteChunkRecovery();
if (import.meta.env.PROD) registerOnlineFirstServiceWorker();

const BootstrapFailure = () => (
  <main className="flex min-h-screen items-center justify-center bg-slate-50 px-5 py-10">
    <section className="w-full max-w-md rounded-3xl border border-amber-200 bg-white p-6 text-center shadow-xl shadow-slate-200/60" role="alert">
      <img src="/t2-marketing-logo.png?v=t2-20260822-official" alt="T2 Marketing" className="mx-auto h-14 w-14 rounded-2xl border border-slate-200 bg-white object-cover shadow-sm" />
      <h1 className="mt-4 text-xl font-bold text-slate-950">系统暂时无法启动</h1>
      <p className="mt-2 text-sm leading-6 text-slate-600">系统可能刚完成更新，或当前网络连接不稳定。请重新加载，您的业务数据不会因此被修改。</p>
      <button type="button" className="mt-5 min-h-11 w-full rounded-xl bg-blue-600 px-4 text-sm font-semibold text-white hover:bg-blue-700" onClick={() => window.location.reload()}>重新加载系统</button>
    </section>
  </main>
);

async function initializeApp() {
  const rootElement = document.getElementById('root');
  if (!rootElement) throw new Error('Application root element is missing');
  const root = createRoot(rootElement);
  try {
    await loadRuntimeConfig();
    const { default: App } = await import('./App.tsx');
    root.render(<App />);
  } catch (error) {
    console.error('Application failed to initialize:', error);
    root.render(<BootstrapFailure />);
  }
}

void initializeApp();
