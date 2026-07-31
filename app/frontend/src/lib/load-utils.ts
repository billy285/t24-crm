const RETRYABLE_STATUS_CODES = new Set([408, 425, 429, 500, 502, 503, 504]);

export function getLoadErrorMessage(error: any, fallback = '服务器响应超时或暂时不可用，请重新加载。') {
  const detail =
    error?.response?.data?.detail ||
    error?.data?.detail ||
    error?.message ||
    '';

  if (/timeout|network error|failed to fetch|err_network/i.test(String(detail))) {
    return fallback;
  }
  return String(detail || fallback);
}

function isRetryable(error: any) {
  const status = Number(error?.response?.status || error?.data?.status || 0);
  const message = String(error?.message || error?.data?.message || '');
  return RETRYABLE_STATUS_CODES.has(status) ||
    /timeout|network error|failed to fetch|err_network/i.test(message);
}

export async function loadWithRetry<T>(
  action: () => Promise<T>,
  options: { attempts?: number; delayMs?: number } = {},
): Promise<T> {
  const attempts = Math.max(1, options.attempts ?? 2);
  const delayMs = Math.max(0, options.delayMs ?? 700);
  let lastError: unknown;

  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await action();
    } catch (error) {
      lastError = error;
      if (attempt >= attempts || !isRetryable(error)) throw error;
      await new Promise(resolve => window.setTimeout(resolve, delayMs * attempt));
    }
  }

  throw lastError;
}
