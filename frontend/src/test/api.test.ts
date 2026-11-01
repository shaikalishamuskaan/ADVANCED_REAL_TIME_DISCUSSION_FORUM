import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, getAccessToken, loginSession, logoutSession, refreshSession, request, setSession } from '../lib/api';

const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
beforeEach(() => { setSession(null); localStorage.clear(); sessionStorage.clear(); });

it('rejects a successful protected response that arrives after logout',async()=>{
  setSession('token');const response=deferred<Response>();vi.stubGlobal('fetch',vi.fn(()=>response.promise));const work=request('/api/users/me');setSession(null);response.resolve(json({user:{id:'old-user'}}));await expect(work).rejects.toMatchObject({name:'AbortError'});
});
it('reads nested FastAPI errors and signals that role controls need refreshing',async()=>{
  setSession('token');const stale=vi.fn();window.addEventListener('forum:profile-stale',stale);
  try {vi.stubGlobal('fetch',vi.fn().mockResolvedValue(json({detail:{error:{code:'insufficient_role',message:'Your role has changed.'}}},403)));await expect(request('/api/forum/moderation/reports')).rejects.toMatchObject({status:403,code:'insufficient_role',message:'Your role has changed.'});expect(stale).toHaveBeenCalledOnce();}
  finally {window.removeEventListener('forum:profile-stale',stale);}
});

describe('API authentication', () => {
  it('logs in through the exact endpoint and keeps its token out of browser storage', async () => {
    const fetcher = vi.fn().mockResolvedValue(json({ access_token: 'access-token' })); vi.stubGlobal('fetch', fetcher);
    await loginSession('alice@example.com', 'password');
    expect(fetcher).toHaveBeenCalledWith('/api/auth/login', expect.objectContaining({ method: 'POST', credentials: 'include', body: JSON.stringify({ email: 'alice@example.com', password: 'password' }) }));
    expect(getAccessToken()).toBe('access-token'); expect(localStorage.length).toBe(0); expect(sessionStorage.length).toBe(0);
  });
  it('adds a bearer token to protected requests', async () => {
    setSession('token'); const fetcher = vi.fn().mockResolvedValue(json({ ok: true })); vi.stubGlobal('fetch', fetcher);
    await request('/api/forum/threads');
    expect(new Headers(fetcher.mock.calls[0][1].headers).get('Authorization')).toBe('Bearer token');
  });
  it('shares one rotating refresh among concurrent expired requests', async () => {
    setSession('old'); const refresh = deferred<Response>(); let refreshes = 0;
    vi.stubGlobal('fetch', vi.fn((path: string, options: RequestInit) => {
      if (path === '/api/auth/refresh') { refreshes++; return refresh.promise; }
      return Promise.resolve(new Headers(options.headers).get('Authorization') === 'Bearer new' ? json({ ok: true }) : json({ error: { message: 'Expired' } }, 401));
    }));
    const work = Promise.all([request('/api/one'), request('/api/two')]);
    await vi.waitFor(() => expect(refreshes).toBe(1)); refresh.resolve(json({ access_token: 'new' }));
    expect(await work).toEqual([{ ok: true }, { ok: true }]); expect(refreshes).toBe(1);
  });
  it('does not refresh repeatedly when the replacement token is rejected', async () => {
    setSession('old'); const fetcher = vi.fn((path: string) => Promise.resolve(path === '/api/auth/refresh' ? json({ access_token: 'new' }) : json({}, 401))); vi.stubGlobal('fetch', fetcher);
    await expect(request('/api/private')).rejects.toBeInstanceOf(ApiError);
    expect(fetcher).toHaveBeenCalledTimes(3); expect(getAccessToken()).toBeNull();
  });
  it('expires a session when refresh credentials are rejected', async () => {
    setSession('old'); vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({}, 401)));
    expect(await refreshSession()).toBeNull(); expect(getAccessToken()).toBeNull();
  });
  it('preserves the session and surfaces a temporary refresh outage', async () => {
    setSession('old'); vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({ error: { message: 'Unavailable' } }, 503)));
    await expect(refreshSession()).rejects.toMatchObject({ status: 503 }); expect(getAccessToken()).toBe('old');
  });
  it('does not let a late refresh restore a logged-out session', async () => {
    setSession('old'); const pending = deferred<Response>();
    vi.stubGlobal('fetch', vi.fn((path: string) => path === '/api/auth/refresh' ? pending.promise : Promise.resolve(json({ message: 'Logged out' }))));
    const refresh = refreshSession(); await logoutSession(); pending.resolve(json({ access_token: 'late' }));
    expect(await refresh).toBeNull(); expect(getAccessToken()).toBeNull();
  });
  it('does not replay a previous user request with a new user token', async () => {
    setSession('first-user'); const pending = deferred<Response>(); const fetcher = vi.fn().mockReturnValue(pending.promise); vi.stubGlobal('fetch', fetcher);
    const work = request('/api/private').catch(error => error); setSession('second-user'); pending.resolve(json({}, 401));
    expect(await work).toBeInstanceOf(ApiError); expect(fetcher).toHaveBeenCalledTimes(1); expect(getAccessToken()).toBe('second-user');
  });
  it('keeps the session when server logout fails so it can be retried', async () => {
    setSession('valid'); vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Network error')));
    await expect(logoutSession()).rejects.toMatchObject({ status: 0 }); expect(getAccessToken()).toBe('valid');
  });
  it('does not let a late login restore a logged-out session', async () => {
    const pending = deferred<Response>();
    vi.stubGlobal('fetch', vi.fn((path: string) => path === '/api/auth/login' ? pending.promise : Promise.resolve(json({ message: 'Logged out' }))));
    const login = loginSession('alice@example.com', 'password').catch(error => error);
    await logoutSession(); pending.resolve(json({ access_token: 'late-login' }));
    expect(await login).toMatchObject({ status: 409 }); expect(getAccessToken()).toBeNull();
  });
  it('forwards aborts rather than treating them as login failures', async () => {
    setSession('valid'); vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new DOMException('Aborted', 'AbortError')));
    await expect(request('/api/private')).rejects.toMatchObject({ name: 'AbortError' }); expect(getAccessToken()).toBe('valid');
  });
});
