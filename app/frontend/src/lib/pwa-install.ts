export interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed'; platform: string }>;
}

export interface PwaInstallSnapshot {
  canPrompt: boolean;
  isIos: boolean;
  isStandalone: boolean;
}

const subscribers = new Set<() => void>();
let deferredPrompt: BeforeInstallPromptEvent | null = null;
let initialized = false;
let displayModeQuery: MediaQueryList | null = null;
const CHUNK_RELOAD_KEY = 't24_chunk_reload_attempt';
const CHUNK_RELOAD_WINDOW_MS = 60_000;

function detectIos(): boolean {
  if (typeof navigator === 'undefined') return false;
  const userAgent = navigator.userAgent.toLowerCase();
  return /iphone|ipad|ipod/.test(userAgent)
    || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
}

function detectStandalone(): boolean {
  if (typeof window === 'undefined') return false;
  const iosNavigator = navigator as Navigator & { standalone?: boolean };
  return window.matchMedia('(display-mode: standalone)').matches || iosNavigator.standalone === true;
}

let snapshot: PwaInstallSnapshot = {
  canPrompt: false,
  isIos: false,
  isStandalone: false,
};

function updateSnapshot(): void {
  snapshot = {
    canPrompt: deferredPrompt !== null,
    isIos: detectIos(),
    isStandalone: detectStandalone(),
  };
  subscribers.forEach(listener => listener());
}

export function initializePwaInstallCapture(): void {
  if (initialized || typeof window === 'undefined') return;
  initialized = true;

  window.addEventListener('beforeinstallprompt', event => {
    event.preventDefault();
    deferredPrompt = event as BeforeInstallPromptEvent;
    updateSnapshot();
  });
  window.addEventListener('appinstalled', () => {
    deferredPrompt = null;
    updateSnapshot();
  });
  displayModeQuery = window.matchMedia('(display-mode: standalone)');
  displayModeQuery.addEventListener?.('change', updateSnapshot);
  updateSnapshot();
}

export function installViteChunkRecovery(): void {
  if (typeof window === 'undefined') return;
  window.addEventListener('vite:preloadError', event => {
    const route = `${window.location.pathname}${window.location.search}`;
    const now = Date.now();
    let shouldReload = false;
    try {
      const rawMarker = window.sessionStorage.getItem(CHUNK_RELOAD_KEY);
      const marker = rawMarker ? JSON.parse(rawMarker) as { route?: string; at?: number } : null;
      if (!marker || marker.route !== route || now - Number(marker.at || 0) > CHUNK_RELOAD_WINDOW_MS) {
        window.sessionStorage.setItem(CHUNK_RELOAD_KEY, JSON.stringify({ route, at: now }));
        shouldReload = true;
      }
    } catch {
      // If session storage is unavailable, let React surface a visible recovery page.
    }

    if (shouldReload) {
      event.preventDefault();
      window.location.reload();
    }
  });
}

export function subscribePwaInstall(listener: () => void): () => void {
  subscribers.add(listener);
  return () => subscribers.delete(listener);
}

export function getPwaInstallSnapshot(): PwaInstallSnapshot {
  return snapshot;
}

export function getPwaInstallServerSnapshot(): PwaInstallSnapshot {
  return { canPrompt: false, isIos: false, isStandalone: false };
}

export async function promptPwaInstall(): Promise<'accepted' | 'dismissed' | 'unavailable'> {
  const prompt = deferredPrompt;
  if (!prompt) return 'unavailable';
  await prompt.prompt();
  const choice = await prompt.userChoice;
  deferredPrompt = null;
  updateSnapshot();
  return choice.outcome;
}

export function registerOnlineFirstServiceWorker(): void {
  if (typeof window === 'undefined' || !('serviceWorker' in navigator)) return;
  window.addEventListener('load', () => {
    void navigator.serviceWorker.register('/sw.js', {
      scope: '/',
      updateViaCache: 'none',
    }).catch(error => {
      console.warn('T24 OS service worker registration failed:', error);
    });
  }, { once: true });
}
