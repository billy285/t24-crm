import { Component, type ErrorInfo, type ReactNode } from 'react';
import { AlertTriangle, Home, RefreshCw } from 'lucide-react';

type Props = { children: ReactNode };
type State = { error: Error | null };

export default class AppErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('T24 application render failed:', error, info);
  }

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-50 px-5 py-10">
        <section className="w-full max-w-md rounded-3xl border border-amber-200 bg-white p-6 text-center shadow-xl shadow-slate-200/60" role="alert">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-amber-100 text-amber-700">
            <AlertTriangle className="h-6 w-6" aria-hidden="true" />
          </div>
          <h1 className="mt-4 text-xl font-bold text-slate-950">当前页面没有正常加载</h1>
          <p className="mt-2 text-sm leading-6 text-slate-600">系统可能刚完成更新，或当前网络连接不稳定。您的业务数据没有被修改，请重新加载后继续。</p>
          <div className="mt-5 grid gap-3 sm:grid-cols-2">
            <button type="button" className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-blue-600 px-4 text-sm font-semibold text-white hover:bg-blue-700" onClick={() => window.location.reload()}>
              <RefreshCw className="h-4 w-4" aria-hidden="true" />重新加载系统
            </button>
            <button type="button" className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-4 text-sm font-semibold text-slate-700 hover:bg-slate-50" onClick={() => window.location.assign('/apps')}>
              <Home className="h-4 w-4" aria-hidden="true" />返回应用首页
            </button>
          </div>
        </section>
      </main>
    );
  }
}
