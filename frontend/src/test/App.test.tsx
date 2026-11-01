import { StrictMode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App } from '../App';
import { AuthProvider } from '../auth/AuthProvider';
import { setSession } from '../lib/api';

const user = { id: 'user-1', username: 'alice', display_name: 'Alice', role: 'member', status: 'active', avatar_url: null, bio: '' };
const thread = { id: 'thread-1', title: 'How do refresh tokens work?', description: '<b data-bad="yes">Plain text, not HTML.</b>', author: { id: 'user-2', username: 'omar', display_name: 'Omar' }, tags: ['python'], like_count: 2, comment_count: 1, liked_by_me: false, created_at: '2026-10-27T09:14:03Z', updated_at: '2026-10-27T09:14:03Z', is_edited: false };
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });
function renderApp(path = '/discussions', cache = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })) {
  render(<StrictMode><QueryClientProvider client={cache}><MemoryRouter initialEntries={[path]}><AuthProvider><App /></AuthProvider></MemoryRouter></QueryClientProvider></StrictMode>);
  return cache;
}
function baseFetch(path: string) {
  if (path === '/api/auth/refresh') return json({ access_token: 'restored' });
  if (path === '/api/users/me') return json({ user });
  if (path.startsWith('/api/forum/threads')) return json({ items: [thread], next_cursor: null });
  return json({}, 404);
}
beforeEach(() => { setSession(null); });

describe('frontend foundation', () => {
  it('still blocks a genuinely disabled profile without requesting discussions', async () => {
    const fetcher = vi.fn((path: string) => Promise.resolve(path === '/api/users/me' ? json({ user: { ...user, status: 'disabled' } }) : baseFetch(path)));
    vi.stubGlobal('fetch', fetcher);
    renderApp();
    expect(await screen.findByText('Your account is disabled. Please contact an administrator.')).toBeInTheDocument();
    expect(fetcher.mock.calls.some(([path]) => path.startsWith('/api/forum/'))).toBe(false);
  });
  it.each([{}, { user: null }, { user: { id: 'user-1', username: 'alice' } }])('does not mislabel a malformed profile as disabled: %j', async payload => {
    const fetcher = vi.fn((path: string) => Promise.resolve(path === '/api/users/me' ? json(payload) : baseFetch(path)));
    vi.stubGlobal('fetch', fetcher);
    renderApp();
    expect(await screen.findByText('We could not load your account details. Please try again.')).toBeInTheDocument();
    expect(screen.queryByText('Your account is disabled. Please contact an administrator.')).not.toBeInTheDocument();
    expect(fetcher.mock.calls.some(([path]) => path.startsWith('/api/forum/'))).toBe(false);
  });
  it('restores one session in StrictMode and displays real API thread data as text', async () => {
    const fetcher = vi.fn((path: string) => Promise.resolve(baseFetch(path))); vi.stubGlobal('fetch', fetcher);
    renderApp();
    expect(await screen.findByRole('link', { name: thread.title })).toBeInTheDocument();
    expect(screen.getByText('Alice')).toBeInTheDocument(); expect(screen.getByText('member')).toBeInTheDocument();
    expect(screen.getByText(thread.description)).toBeInTheDocument(); expect(document.querySelector('[data-bad]')).toBeNull();
    expect(fetcher.mock.calls.filter(([path]) => path === '/api/auth/refresh')).toHaveLength(1);
  });
  it('redirects an unauthenticated user, then logs in and returns to the requested tag', async () => {
    const interaction = userEvent.setup();
    const fetcher = vi.fn((path: string) => Promise.resolve(path === '/api/auth/refresh' ? json({}, 401) : path === '/api/auth/login' ? json({ access_token: 'signed-in' }) : baseFetch(path)));
    vi.stubGlobal('fetch', fetcher); renderApp('/discussions?tag=python');
    await screen.findByLabelText('Email address');
    await interaction.type(screen.getByLabelText('Email address'), 'alice@example.com');
    await interaction.type(screen.getByLabelText('Password'), 'correct-password');
    await interaction.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('link', { name: thread.title })).toBeInTheDocument();
    expect(fetcher.mock.calls.some(([path]) => path === '/api/forum/threads?tag=python')).toBe(true);
  });
  it('shows server login errors and leaves the form available for retry', async () => {
    const interaction = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn((path: string) => Promise.resolve(path === '/api/auth/login' ? json({ error: { code: 'invalid_credentials', message: 'Email or password is incorrect.' } }, 401) : json({}, 401))));
    renderApp('/login'); await screen.findByLabelText('Email address');
    await interaction.type(screen.getByLabelText('Email address'), 'alice@example.com');
    await interaction.type(screen.getByLabelText('Password'), 'wrong-password');
    await interaction.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Email or password is incorrect.');
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeEnabled();
  });
  it('treats restore outages as retryable errors, then allows unauthenticated sign-in', async () => {
    const interaction = userEvent.setup(); let calls = 0;
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(++calls === 1 ? json({ error: { message: 'Temporarily unavailable' } }, 503) : json({}, 401))));
    renderApp();
    await screen.findByText('We couldn’t restore your session.');
    await interaction.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByLabelText('Email address')).toBeInTheDocument();
  });
  it('clears private query data after a successful server logout', async () => {
    const interaction = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn((path: string) => Promise.resolve(path === '/api/auth/logout' ? json({ message: 'Logged out' }) : baseFetch(path))));
    const cache = new QueryClient({ defaultOptions: { queries: { retry: false } } }); cache.setQueryData(['private-marker'], 'private value');
    renderApp('/discussions', cache); await screen.findByRole('button', { name: 'Sign out' });
    await interaction.click(screen.getByRole('button', { name: 'Sign out' }));
    expect(await screen.findByLabelText('Email address')).toBeInTheDocument();
    expect(cache.getQueryData(['private-marker'])).toBeUndefined();
  });
  it('renders an honest empty state and reloads a failed thread request', async () => {
    const interaction = userEvent.setup(); let unavailable = true;
    vi.stubGlobal('fetch', vi.fn((path: string) => Promise.resolve(path.startsWith('/api/forum/threads') ? (unavailable ? json({ error: { message: 'Unavailable' } }, 503) : json({ items: [], next_cursor: null })) : baseFetch(path))));
    renderApp(); await screen.findByText('We couldn’t load the discussions.');
    unavailable = false;
    await interaction.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByText('A fresh space for good questions.')).toBeInTheDocument();
  });
  it('uses backend cursors to load the next page', async () => {
    const interaction = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn((path: string) => Promise.resolve(path.startsWith('/api/forum/threads') ? json(path.includes('cursor=page-two') ? { items: [{ ...thread, id: 'thread-2', title: 'A second discussion' }], next_cursor: null } : { items: [thread], next_cursor: 'page-two' }) : baseFetch(path))));
    renderApp(); await screen.findByRole('link', { name: thread.title });
    await interaction.click(screen.getByRole('button', { name: /More conversations/ }));
    expect(await screen.findByRole('link', { name: 'A second discussion' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: thread.title })).toBeInTheDocument();
  });
  it('opens a deep-linked thread and loads comments and additional replies', async () => {
    const interaction = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn((path: string) => {
      if (path === '/api/forum/threads/thread-1') return Promise.resolve(json(thread));
      if (path === '/api/forum/threads/thread-1/comments') return Promise.resolve(json({ items: [{ id: 'comment-1', body: 'A useful answer', depth: 1, author: thread.author, like_count: 1, reply_count: 2, replies: [{ id: 'reply-1', depth: 2, body: 'First reply' }], replies_next_cursor: 'reply-two' }], next_cursor: null }));
      if (path === '/api/forum/comments/comment-1/replies') return Promise.resolve(json({ items: [{ id: 'reply-1', depth: 2, body: 'First reply', author: thread.author, like_count: 0, reply_count: 0 }], next_cursor: 'reply-two' }));
      if (path === '/api/forum/comments/comment-1/replies?cursor=reply-two') return Promise.resolve(json({ items: [{ id: 'reply-2', depth: 2, body: 'Second reply' }], next_cursor: null }));
      return Promise.resolve(baseFetch(path));
    }));
    renderApp('/discussions/thread-1'); await screen.findByRole('heading', { name: thread.title });
    expect(await screen.findByText('A useful answer')).toBeInTheDocument();
    expect(screen.getByText('First reply')).toBeInTheDocument();
    await interaction.click(screen.getByRole('button', { name: /Read replies/ }));
    await interaction.click(await screen.findByRole('button', { name: /Load more replies/ }));
    expect(await screen.findByText('Second reply')).toBeInTheDocument();
  });
});
