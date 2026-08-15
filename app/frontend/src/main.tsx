import { createRoot } from 'react-dom/client';
import './index.css';
import { loadRuntimeConfig } from './lib/config.ts';

async function initializeApp() {
  try {
    await loadRuntimeConfig();
    const { default: App } = await import('./App.tsx');
    const rootElement = document.getElementById('root');

    if (!rootElement) throw new Error('Application root element is missing');
    createRoot(rootElement).render(<App />);
  } catch (error) {
    console.error('Application failed to initialize:', error);
    const bootstrapMessage = document.getElementById('t24-bootstrap-message');
    if (bootstrapMessage) bootstrapMessage.textContent = '系统暂时无法加载，请刷新页面重试。';
  }
}

void initializeApp();
