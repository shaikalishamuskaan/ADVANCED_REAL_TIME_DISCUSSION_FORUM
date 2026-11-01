import { useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { Link, NavLink, Navigate, Outlet, Route, Routes, useLocation, useMatch, useNavigate, useSearchParams } from 'react-router-dom';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { useAuth } from './auth/AuthProvider';
import { Register, PasswordReset } from './auth/AccountPages';
import { useRealtime } from './realtime/useRealtime';
import { LikeButton, NewThread, ThreadView } from './pages/DiscussionPages';
import { Dashboard, SearchPage, NotificationsPage, ProfilePage, PublicProfile } from './pages/CommunityPages';
import { ActivityPage, AdminTagsPage, AdminUsersPage, ModerationPage } from './pages/ManagementPages';
import { request } from './lib/api';
import type { Page, Thread } from './lib/types';

function message(error: unknown) { return error instanceof Error ? error.message : 'Something went wrong. Please try again.'; }
function date(value: string) { return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric' }).format(new Date(value)); }
function pagePath(path: string, cursor: string | null, tag?: string) {
  const params = new URLSearchParams();
  if (cursor) params.set('cursor', cursor);
  if (tag) params.set('tag', tag);
  return `${path}${params.size ? `?${params}` : ''}`;
}
function Brand() { return <Link className="brand" to="/discussions" aria-label="Forum home"><span className="brand-mark" aria-hidden="true">f.</span><span>forum<span className="brand-dot">.</span></span></Link>; }
function Notice({ title, children, retry }: { title: string; children?: ReactNode; retry?: () => void }) {
  return <section className="notice" role="status"><span className="notice-icon" aria-hidden="true">↗</span><h2>{title}</h2>{children && <p>{children}</p>}{retry && <button className="button secondary" onClick={retry}>Try again</button>}</section>;
}
function Protected() {
  const auth = useAuth(); const location = useLocation();
  return auth.status === 'authenticated' ? <Outlet /> : <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
}
function RoleGuard({ roles }: { roles: string[] }) {
  const auth = useAuth();
  return roles.includes(auth.user?.role || '') ? <Outlet /> : <Notice title="This page is not available for your role."><Link to="/dashboard">Return to your dashboard</Link></Notice>;
}
function Shell() {
  const auth = useAuth(); const [error, setError] = useState(''); const [leaving, setLeaving] = useState(false);
  const match = useMatch('/discussions/:threadId'); const threadId = match?.params.threadId;
  const live = useRealtime(threadId === 'new' ? undefined : threadId);
  const unread = useQuery({ queryKey: ['unread'], queryFn: ({ signal }) => request<{ unread_count: number }>('/api/notifications/unread-count', { signal }), refetchInterval: 60_000 });
  async function logout() { setLeaving(true); setError(''); try { await auth.logout(); } catch (problem) { setError(message(problem)); } finally { setLeaving(false); } }
  return <><a className="skip-link" href="#main">Skip to content</a><header className="site-header"><div className="header-inner"><Brand /><div className="account"><span className={`live-status live-${live}`} role="status">{live === 'connected' ? 'Live' : live === 'offline' ? 'Offline' : 'Reconnecting'}</span><span className="avatar" aria-hidden="true">{auth.user?.username.slice(0, 1).toUpperCase()}</span><div className="account-name"><strong>{auth.user?.display_name || auth.user?.username}</strong><span className="role">{auth.user?.role}</span></div><button className="text-button" onClick={() => void logout()} disabled={leaving}>{leaving ? 'Signing out...' : 'Sign out'}</button></div><nav aria-label="Main navigation"><NavLink className="nav-link" to="/dashboard">Dashboard</NavLink><NavLink className="nav-link" to="/discussions">Discussions</NavLink><NavLink className="nav-link" to="/search">Search</NavLink><NavLink className="nav-link" to="/notifications">Notifications{Boolean(unread.data?.unread_count) && <span className="badge">{unread.data?.unread_count}</span>}</NavLink><NavLink className="nav-link" to="/profile">Profile</NavLink>{auth.user?.role !== 'member' && <><NavLink className="nav-link" to="/moderation">Reports</NavLink><NavLink className="nav-link" to="/activity">Activity</NavLink></>}{auth.user?.role === 'admin' && <NavLink className="nav-link" to="/admin/users">Members</NavLink>}</nav></div></header>{error && <p className="banner error" role="alert">{error}</p>}<main id="main" className="workspace"><Outlet /></main><footer className="site-footer"><span>forum.</span><p>A little curiosity. A better conversation.</p></footer></>;
}
function Login() {
  const auth = useAuth(); const navigate = useNavigate(); const location = useLocation();
  const [email, setEmail] = useState(''); const [password, setPassword] = useState(''); const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  const target = (location.state as { from?: string } | null)?.from;
  const destination = target?.startsWith('/') && !target.startsWith('//') ? target : '/dashboard';
  if (auth.status === 'authenticated') return <Navigate to={destination} replace />;
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      await auth.login(email.trim(), password);
      navigate(destination, { replace: true });
    } catch (problem) { setError(message(problem)); } finally { setBusy(false); }
  }
  return <main className="login-page"><section className="login-story"><Brand /><div className="story-body"><p className="eyebrow">ROOM FOR YOUR PERSPECTIVE</p><h1>Good conversations<br />start with<br /><em>curiosity.</em></h1><p className="story-description">A place to ask better questions, share what you know, and learn something together.</p><div className="conversation-art" aria-hidden="true"><span className="art-bubble">What if…</span><span className="art-line" /><span className="art-bubble reply">Let’s talk.</span><span className="art-star">✳</span></div></div><p className="story-foot">THOUGHTFUL QUESTIONS. DIFFERENT PERSPECTIVES.</p></section><section className="login-panel"><div className="login-form"><span className="small-label">WELCOME TO THE COMMUNITY</span><h2>Pick up the conversation.</h2><p className="muted">Sign in to read the latest discussions.</p>{(location.state as { notice?: string } | null)?.notice && <p className="success-notice" role="status">{(location.state as { notice: string }).notice}</p>}<form onSubmit={event => void submit(event)}><label htmlFor="email">Email address</label><input id="email" name="email" type="email" autoComplete="username" placeholder="you@example.com" required value={email} onChange={event => setEmail(event.target.value)} disabled={busy} /><label htmlFor="password">Password</label><input id="password" name="password" type="password" autoComplete="current-password" placeholder="Your password" required value={password} onChange={event => setPassword(event.target.value)} disabled={busy} />{error && <p className="form-error" role="alert">{error}</p>}<button className="button primary sign-in" type="submit" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}<span aria-hidden="true">↗</span></button></form><div className="auth-links"><Link to="/register">Create an account</Link><Link to="/password/reset">Forgot your password?</Link></div><p className="login-note">Bring your questions. Leave with a new perspective.</p></div><p className="login-copyright">Forum · A space for thoughtful discussion</p></section></main>;
}
function ThreadCard({ thread }: { thread: Thread }) {
  return <article className="thread-card"><div className="thread-meta"><span className="tiny-avatar" aria-hidden="true">{(thread.author?.username || '?').slice(0, 1).toUpperCase()}</span><span>{thread.author?.display_name || thread.author?.username || 'Unavailable user'}</span><span className="meta-divider">·</span><time dateTime={thread.created_at}>{date(thread.created_at)}</time></div><h2><Link to={`/discussions/${thread.id}`}>{thread.title}</Link></h2><p className="thread-preview">{thread.description}</p><div className="thread-bottom"><div className="tags">{thread.tags.map(tag => <Link key={tag} to={`/discussions?tag=${encodeURIComponent(tag)}`} className="tag">#{tag}</Link>)}</div><div className="thread-counts"><LikeButton kind="thread" id={thread.id} liked={thread.liked_by_me} count={thread.like_count} /><span aria-label={`${thread.comment_count} comments` }>↳ {thread.comment_count}<span className="count-label"> replies</span></span><Link className="read-thread" to={`/discussions/${thread.id}`} aria-label={`Read ${thread.title}`} >↗</Link></div></div></article>;
}
function Discussions() {
  const [params, setParams] = useSearchParams(); const tag = params.get('tag') || '';
  const threads = useInfiniteQuery({ queryKey: ['threads', tag], initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) => request<Page<Thread>>(pagePath('/api/forum/threads', pageParam, tag), { signal }),
    getNextPageParam: page => page.next_cursor ?? undefined });
  const items = [...new Map(threads.data?.pages.flatMap(page => page.items).map(thread => [thread.id, thread]) || []).values()];
  const tags = [...new Set(items.flatMap(thread => thread.tags))].sort();
  return <><section className="page-heading"><div><p className="eyebrow">THE COMMUNITY BOARD</p><h1>A meeting of <em>minds.</em></h1><p className="muted">Questions worth asking. Ideas worth sharing.</p></div><Link className="button primary" to="/discussions/new">New discussion</Link><span className="heading-symbol" aria-hidden="true">✳</span></section><div className="board-layout"><section aria-label="Discussions"><div className="list-toolbar"><div className="toolbar-tabs"><button className={!tag ? 'selected' : ''} onClick={() => setParams({})}>All discussions</button>{tag && <span className="selected-tag">#{tag}<button onClick={() => setParams({})} aria-label="Clear tag filter">×</button></span>}</div><button className="text-button" disabled={threads.isFetching} onClick={() => void threads.refetch()}>{threads.isFetching && !threads.isPending ? 'Refreshing…' : 'Refresh ↻'}</button></div>{threads.isPending ? <Notice title="Gathering the conversations…" /> : threads.isError && !threads.data ? <Notice title="We couldn’t load the discussions." retry={() => void threads.refetch()}>{message(threads.error)}</Notice> : items.length ? <div className="thread-list">{items.map(thread => <ThreadCard key={thread.id} thread={thread} />)}</div> : <Notice title={tag ? `No discussions tagged #${tag} yet.` : 'A fresh space for good questions.'}>Conversations will appear here as community members post them.</Notice>}{threads.isError && threads.data && <p className="form-error" role="alert">{message(threads.error)}</p>}{threads.hasNextPage && <button className="button secondary load-more" disabled={threads.isFetchingNextPage} onClick={() => void threads.fetchNextPage()}>{threads.isFetchingNextPage ? 'Loading…' : 'More conversations ↓'}</button>}{items.length > 0 && <p className="list-note">Showing {items.length} {items.length === 1 ? 'discussion' : 'discussions'} · Newest first</p>}</section><aside className="board-sidebar"><div className="aside-card"><span className="small-label">A GOOD PLACE TO START</span><h2>Stay curious.<br />Be generous.</h2><p>The best discussions make room for questions, fresh ideas, and a different point of view.</p><div className="aside-rule" /><span className="small-label">EXPLORE THE CONVERSATION</span>{tags.length ? <div className="sidebar-tags">{tags.map(topic => <button key={topic} onClick={() => setParams({ tag: topic })} className={topic === tag ? 'topic active-topic' : 'topic'}>#{topic}<span aria-hidden="true">↗</span></button>)}</div> : <p className="muted">Topics will appear as discussions are added.</p>}</div><p className="sidebar-note">Behind every question<br />is a chance to learn.</p></aside></div></>;
}
export function App() {
  const auth = useAuth();
  if (auth.status === 'loading') return <main className="startup"><Brand /><Notice title="Finding your place in the conversation…" /></main>;
  if (auth.status === 'error') return <main className="startup"><Brand /><Notice title="We couldn’t restore your session." retry={() => void auth.restore()}>{auth.error}</Notice></main>;
  return <Routes><Route path="/login" element={<Login />} /><Route path="/register" element={<Register />} /><Route path="/password/reset" element={<PasswordReset />} /><Route element={<Protected />}><Route element={<Shell />}><Route index element={<Navigate to="/dashboard" replace />} /><Route path="/dashboard" element={<Dashboard />} /><Route path="/discussions" element={<Discussions />} /><Route path="/discussions/new" element={<NewThread />} /><Route path="/discussions/:threadId" element={<ThreadView />} /><Route path="/search" element={<SearchPage />} /><Route path="/notifications" element={<NotificationsPage />} /><Route path="/profile" element={<ProfilePage />} /><Route path="/members/:username" element={<PublicProfile />} /><Route element={<RoleGuard roles={['moderator','admin']} />}><Route path="/moderation" element={<ModerationPage />} /><Route path="/activity" element={<ActivityPage />} /></Route><Route element={<RoleGuard roles={['admin']} />}><Route path="/admin/users" element={<AdminUsersPage />} /><Route path="/admin/tags" element={<AdminTagsPage />} /></Route></Route></Route><Route path="*" element={<main className="startup"><Brand /><Notice title="This page isn’t here."><Link to="/discussions">Return to discussions</Link></Notice></main>} /></Routes>;
}
