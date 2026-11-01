import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { ApiError } from '../lib/api';

export const message = (error: unknown) => error instanceof Error ? error.message : 'Please try again.';
export const date = (value: string) => new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric' }).format(new Date(value));
export function endpoint(path: string, values: Record<string, string | null | undefined>) { const query = new URLSearchParams(); for (const [key, value] of Object.entries(values)) if (value) query.set(key, value); return `${path}${query.size ? `?${query}` : ''}`; }
export function Failure({ error }: { error: unknown }) {
  if (!error) return null;
  const details = error instanceof ApiError ? Object.entries(error.details || {}).flatMap(([key, value]) => (Array.isArray(value) ? value : [value]).filter(value => typeof value === 'string').map(value => `${key.replaceAll('_', ' ')}: ${value}`)) : [];
  return <div className="form-error" role="alert"><p>{message(error)}</p>{details.length > 0 && <ul>{details.map((text, index) => <li key={index}>{text}</li>)}</ul>}</div>;
}
export function useAction() {
  const [busy, setBusy] = useState(false); const [error, setError] = useState<unknown>(null);
  async function run<T,>(work: () => Promise<T>): Promise<T | undefined> { setBusy(true); setError(null); try { return await work(); } catch (problem) { setError(problem); return undefined; } finally { setBusy(false); } }
  return { busy, error, run, clear: () => setError(null) };
}
export function useForumRefresh() { const cache = useQueryClient(); return async () => { await Promise.all(['threads','thread','comments','replies','search','reports'].map(key => cache.invalidateQueries({ queryKey: [key] }))); }; }
export function Heading({ eyebrow, title, children }: { eyebrow: string; title: string; children?: ReactNode }) { return <section className="page-heading"><div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1>{children && <div className="heading-description">{children}</div>}</div></section>; }
export function LoadMore({ more, busy, load }: { more: boolean; busy: boolean; load: () => void }) { return more ? <button className="button secondary load-more" onClick={load} disabled={busy}>{busy ? 'Loading...' : 'Load more'}</button> : null; }
export function Confirm({ label, children, busy, confirm, cancel }: { label: string; children: ReactNode; busy: boolean; confirm: () => void; cancel: () => void }) { return <section className="confirmation" aria-label={label}><p>{children}</p><div className="actions"><button className="button danger" disabled={busy} onClick={confirm}>{busy ? 'Working...' : label}</button><button className="button secondary" disabled={busy} onClick={cancel}>Cancel</button></div></section>; }
export function SecretReceipt({ code, notice, done }: { code: string; notice: string; done: () => void }) {
  const [saved, setSaved] = useState(false); const [status, setStatus] = useState('');
  async function copy() { try { if (!navigator.clipboard?.writeText) throw new Error(); await navigator.clipboard.writeText(code); setStatus('Copied'); } catch { setStatus('Select and copy the code manually.'); } }
  useEffect(() => { const warn = (event: BeforeUnloadEvent) => { if (!saved) { event.preventDefault(); event.returnValue = ''; } }; window.addEventListener('beforeunload', warn); return () => window.removeEventListener('beforeunload', warn); }, [saved]);
  return <section className="surface secret-receipt" aria-label="One-time recovery code"><h2>Save this recovery code.</h2><p className="muted">{notice}</p><div className="recovery-box"><code aria-label="Your recovery code">{code}</code><button className="button secondary" onClick={() => void copy()}>Copy code</button><p role="status">{status}</p></div><label className="saved-confirmation"><input type="checkbox" checked={saved} onChange={event => setSaved(event.target.checked)} />I have saved or securely shared this code.</label><button className="button primary" disabled={!saved} onClick={done}>Done</button></section>;
}
