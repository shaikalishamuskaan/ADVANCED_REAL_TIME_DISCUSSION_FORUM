import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { ApiError, loginSession, logoutSession, refreshSession, request, setSession, subscribeSession } from '../lib/api';
import type { ProfileResponse, User } from '../lib/types';

type State = { status: 'loading' | 'anonymous' | 'authenticated' | 'error'; user: User | null; error?: string };
type Auth = State & { login: (email: string, password: string) => Promise<void>; logout: () => Promise<void>; restore: () => Promise<void>; reloadProfile: () => Promise<void>; updateUser: (user: User) => void };
const Context = createContext<Auth | null>(null);
export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>({ status: 'loading', user: null });
  const sequence = useRef(0);
  const cache = useQueryClient();
  const clearCache = useCallback(() => { void cache.cancelQueries(); cache.clear(); }, [cache]);
  const profile = async () => {
    const response = await request<ProfileResponse>('/api/users/me');
    const user = response?.user;
    if (!user || typeof user.id !== 'string' || typeof user.username !== 'string' || !['active', 'disabled'].includes(user.status)) {
      throw new Error('We could not load your account details. Please try again.');
    }
    if (user.status !== 'active') throw new Error('Your account is disabled. Please contact an administrator.');
    return user;
  };
  const restore = useCallback(async () => {
    const current = ++sequence.current;
    setState({ status: 'loading', user: null });
    try {
      const token = await refreshSession();
      const user = token ? await profile() : null;
      if (sequence.current === current) setState({ status: user ? 'authenticated' : 'anonymous', user });
    } catch (error) {
      if (sequence.current === current) setState({ status: 'error', user: null, error: error instanceof Error ? error.message : 'Unable to restore your session.' });
    }
  }, []);
  const reloadProfile = useCallback(async () => {
    try { const user = await profile(); setState({ status: 'authenticated', user }); }
    catch (error) { if (error instanceof ApiError && [401, 403].includes(error.status)) setSession(null); throw error; }
  }, []);
  useEffect(() => {
    const update = () => { void reloadProfile().catch(() => {}); };
    window.addEventListener('forum:profile-stale', update);
    return () => window.removeEventListener('forum:profile-stale', update);
  }, [reloadProfile]);
  useEffect(() => {
    const unsubscribe = subscribeSession(token => {
      if (!token) { sequence.current++; clearCache(); setState({ status: 'anonymous', user: null }); }
    });
    void restore();
    return () => { unsubscribe(); sequence.current++; };
  }, [restore, clearCache]);
  async function login(email: string, password: string) {
    const current = ++sequence.current;
    clearCache();
    await loginSession(email, password);
    try {
      const user = await profile();
      if (current === sequence.current) setState({ status: 'authenticated', user });
    } catch (error) { if (current === sequence.current) setSession(null); throw error; }
  }
  async function logout() { await logoutSession(); }
  return <Context.Provider value={{ ...state, login, logout, restore, reloadProfile, updateUser: user => setState({ status: 'authenticated', user }) }}>{children}</Context.Provider>;
}
export function useAuth() { const value = useContext(Context); if (!value) throw new Error('AuthProvider is required'); return value; }
