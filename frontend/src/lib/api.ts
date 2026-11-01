export class ApiError extends Error {
  constructor(public status: number, message: string, public code = 'request_failed', public details?: Record<string, unknown>) { super(message); }
}
let accessToken: string | null = null;
let epoch = 0;
let refreshTask: Promise<string | null> | null = null;
const listeners = new Set<(token: string | null) => void>();
const announce = () => listeners.forEach(listener => listener(accessToken));
export function subscribeSession(listener: (token: string | null) => void) { listeners.add(listener); return () => { listeners.delete(listener); }; }
export function setSession(token: string | null) { epoch++; accessToken = token; announce(); }
export function getAccessToken() { return accessToken; }

type Options = RequestInit & { authenticated?: boolean };
async function send<T>(path: string, options: RequestInit, token: string | null): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set('Accept', 'application/json');
  if (options.body) headers.set('Content-Type', 'application/json');
  if (token) headers.set('Authorization', `Bearer ${token}`);
  let response: Response;
  try { response = await fetch(path, { ...options, headers, credentials: 'include' }); }
  catch (error) {
    if (error && typeof error === 'object' && 'name' in error && error.name === 'AbortError') throw error;
    throw new ApiError(0, 'We could not connect. Please check your connection and try again.');
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const issue = data?.error ?? data?.detail?.error;
    if (response.status === 403 && issue?.code === 'insufficient_role') window.dispatchEvent(new Event('forum:profile-stale'));
    const details = issue?.details ?? (data && typeof data === 'object' && !Array.isArray(data) && !data.detail ? data : undefined);
    throw new ApiError(response.status, issue?.message || (typeof data?.detail === 'string' ? data.detail : 'Your request could not be completed. Please try again.'), issue?.code, details);
  }
  return data as T;
}

export function refreshSession(): Promise<string | null> {
  if (refreshTask) return refreshTask;
  const started = epoch;
  refreshTask = (async () => {
    try {
      const result = await send<{ access_token: string }>('/api/auth/refresh', { method: 'POST', body: '{}' }, null);
      if (started !== epoch) return null;
      accessToken = result.access_token; announce(); return accessToken;
    } catch (error) {
      if (started === epoch && error instanceof ApiError && [401, 403].includes(error.status)) {
        accessToken = null; announce(); return null;
      }
      throw error;
    } finally { refreshTask = null; }
  })();
  return refreshTask;
}

export async function request<T>(path: string, options: Options = {}): Promise<T> {
  const { authenticated = true, ...init } = options;
  const original = authenticated ? accessToken : null;
  const started = epoch;
  try {
    const data = await send<T>(path, init, original);
    if (authenticated && epoch !== started) throw new DOMException('Session changed', 'AbortError');
    return data;
  }
  catch (error) {
    if (!authenticated || epoch !== started || !(error instanceof ApiError) || error.status !== 401) throw error;
    const renewed = accessToken && accessToken !== original ? accessToken : await refreshSession();
    if (!renewed) throw error;
    const retryEpoch = epoch;
    try {
      const data = await send<T>(path, init, renewed);
      if (epoch !== retryEpoch) throw new DOMException('Session changed', 'AbortError');
      return data;
    }
    catch (retryError) {
      if (retryError instanceof ApiError && retryError.status === 401 && accessToken === renewed) setSession(null);
      throw retryError;
    }
  }
}

export async function loginSession(email: string, password: string) {
  const started = ++epoch;
  const data = await request<{ access_token: string }>('/api/auth/login', { method: 'POST', body: JSON.stringify({ email, password }), authenticated: false });
  if (epoch !== started) throw new ApiError(409, 'Sign-in was interrupted. Please try again.');
  setSession(data.access_token);
}
export async function logoutSession() {
  epoch++; // A refresh already in flight must not restore a signed-out session.
  await request('/api/auth/logout', { method: 'POST', body: '{}', authenticated: false });
  setSession(null);
}
