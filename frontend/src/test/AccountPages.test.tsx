import { StrictMode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App } from '../App';
import { AuthProvider } from '../auth/AuthProvider';
import { getAccessToken, setSession } from '../lib/api';

// Synthetic fixture codes; these never correspond to real accounts.
const code = 'ABCD-EFGH-IJKL-MNOP';
const replacement = 'QRST-UVWX-YZ12-3456';
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });
function renderPage(path: string) {
  const cache = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<StrictMode><QueryClientProvider client={cache}><MemoryRouter initialEntries={[path]}><AuthProvider><App /></AuthProvider></MemoryRouter></QueryClientProvider></StrictMode>);
  return cache;
}
async function registerForm(interaction: ReturnType<typeof userEvent.setup>, confirm = 'Devpass123!') {
  await screen.findByLabelText('Display name');
  await interaction.type(screen.getByLabelText('Display name'), 'Dev User');
  await interaction.type(screen.getByLabelText('Username'), 'dev_user');
  await interaction.type(screen.getByLabelText('Email address'), 'dev@example.com');
  await interaction.type(screen.getByLabelText('Password', { exact: true }), 'Devpass123!');
  await interaction.type(screen.getByLabelText('Confirm password'), confirm);
}
async function resetForm(interaction: ReturnType<typeof userEvent.setup>, confirm = 'Devpass456!') {
  await screen.findByLabelText('Username');
  await interaction.type(screen.getByLabelText('Username'), 'dev_user');
  await interaction.type(screen.getByLabelText('Recovery code'), code.toLowerCase());
  await interaction.type(screen.getByLabelText('New password', { exact: true }), 'Devpass456!');
  await interaction.type(screen.getByLabelText('Confirm new password'), confirm);
}
function mockEndpoint(path: string, body: unknown, status = 200) {
  const fetcher = vi.fn((url: string) => Promise.resolve(url === path ? json(body, status) : json({}, 401)));
  vi.stubGlobal('fetch', fetcher); return fetcher;
}
beforeEach(() => { setSession(null); localStorage.clear(); sessionStorage.clear(); });

describe('registration and one-time recovery code', () => {
  it('submits the exact public contract, copies the code, and requires explicit saved confirmation', async () => {
    const interaction = userEvent.setup();
    const clipboard = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue();
    const fetcher = mockEndpoint('/api/auth/register', { user: { username: 'dev_user' }, recovery_code: code, recovery_code_notice: 'Shown once. Store it somewhere safe.' }, 201);
    const cache = renderPage('/register'); await registerForm(interaction);
    await interaction.click(screen.getByRole('button', { name: 'Create account' }));
    expect(await screen.findByLabelText('Your recovery code')).toHaveTextContent(code);
    const call = fetcher.mock.calls.find(([url]) => url === '/api/auth/register')!;
    const options = (fetcher.mock.calls as unknown as [string, RequestInit][]).find(([url]) => url === '/api/auth/register')![1];
    expect(call).toBeDefined();
    expect(JSON.parse(options.body as string)).toEqual({ username: 'dev_user', email: 'dev@example.com', password: 'Devpass123!', display_name: 'Dev User' });
    expect(new Headers(options.headers).get('Authorization')).toBeNull();
    const proceed = screen.getByRole('button', { name: 'Continue to sign in' });
    expect(proceed).toBeDisabled();
    const unsaved = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(unsaved); expect(unsaved.defaultPrevented).toBe(true);
    await interaction.click(screen.getByRole('button', { name: 'Copy code' }));
    expect(clipboard).toHaveBeenCalledWith(code);
    expect(screen.getByRole('button', { name: 'Copied' })).toBeInTheDocument();
    expect(proceed).toBeDisabled();
    expect(localStorage.length).toBe(0); expect(sessionStorage.length).toBe(0);
    expect(cache.getMutationCache().getAll()).toHaveLength(0); expect(getAccessToken()).toBeNull();
    await interaction.click(screen.getByRole('checkbox', { name: /I have saved/ }));
    const saved = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(saved); expect(saved.defaultPrevented).toBe(false);
    await interaction.click(proceed);
    expect(await screen.findByLabelText('Email address')).toBeInTheDocument();
    expect(screen.queryByText(code)).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Your account is ready.');
  });
  it('does not submit mismatched passwords', async () => {
    const interaction = userEvent.setup(); const fetcher = mockEndpoint('/api/auth/register', {});
    renderPage('/register'); await registerForm(interaction, 'Different123!');
    await interaction.click(screen.getByRole('button', { name: 'Create account' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Passwords do not match.');
    expect(fetcher.mock.calls.some(([url]) => url === '/api/auth/register')).toBe(false);
  });
  it.each([[409, 'username_taken', 'This username is already taken.'], [429, 'rate_limited', 'Please try again later.'], [503, 'dependency_unavailable', 'Registration is unavailable.']])('shows backend registration failure %i without losing the form', async (status, errorCode, message) => {
    const interaction = userEvent.setup(); mockEndpoint('/api/auth/register', { error: { code: errorCode, message, details: {} } }, status as number);
    renderPage('/register'); await registerForm(interaction);
    await interaction.click(screen.getByRole('button', { name: 'Create account' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(message as string);
    expect(screen.getByRole('button', { name: 'Create account' })).toBeEnabled();
    expect(screen.queryByLabelText('Your recovery code')).not.toBeInTheDocument();
  });
  it('displays field validation errors returned by DRF', async () => {
    const interaction = userEvent.setup(); mockEndpoint('/api/auth/register', { username: ['This field is invalid.'] }, 400);
    renderPage('/register'); await registerForm(interaction);
    await interaction.click(screen.getByRole('button', { name: 'Create account' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('username: This field is invalid.');
  });
  it('supports manual copying if clipboard access fails', async () => {
    const interaction = userEvent.setup(); vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(new Error('Denied'));
    mockEndpoint('/api/auth/register', { recovery_code: code });
    renderPage('/register'); await registerForm(interaction);
    await interaction.click(screen.getByRole('button', { name: 'Create account' }));
    await screen.findByLabelText('Your recovery code');
    await interaction.click(screen.getByRole('button', { name: 'Copy code' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Select the code and copy it manually.');
    expect(screen.getByLabelText('Your recovery code')).toHaveTextContent(code);
  });
});

describe('password reset', () => {
  it('normalizes the submitted code, displays its replacement, and continues to sign in', async () => {
    const interaction = userEvent.setup();
    const fetcher = mockEndpoint('/api/auth/password/reset', { message: 'Password reset successfully.', recovery_code: replacement, recovery_code_notice: 'This replacement code is shown once. Store it safely.' });
    renderPage('/password/reset'); await resetForm(interaction);
    await interaction.click(screen.getByRole('button', { name: 'Reset password' }));
    expect(await screen.findByLabelText('Your recovery code')).toHaveTextContent(replacement);
    const options = (fetcher.mock.calls as unknown as [string, RequestInit][]).find(([url]) => url === '/api/auth/password/reset')![1];
    expect(JSON.parse(options.body as string)).toEqual({ username: 'dev_user', recovery_code: code, new_password: 'Devpass456!' });
    expect(new Headers(options.headers).get('Authorization')).toBeNull();
    expect(screen.getByText(/Your old recovery code no longer works/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Continue to sign in' })).toBeDisabled();
    expect(localStorage.length).toBe(0); expect(sessionStorage.length).toBe(0);
    await interaction.click(screen.getByRole('checkbox', { name: /I have saved/ }));
    await interaction.click(screen.getByRole('button', { name: 'Continue to sign in' }));
    expect(await screen.findByLabelText('Password', { exact: true })).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Password updated.');
    expect(screen.queryByText(replacement)).not.toBeInTheDocument();
  });
  it.each([[400, 'invalid_reset_code', 'The username or recovery code is invalid.'], [429, 'rate_limited', 'Too many reset attempts.'], [503, 'dependency_unavailable', 'Try again later.']])('handles reset failure %i', async (status, errorCode, message) => {
    const interaction = userEvent.setup(); mockEndpoint('/api/auth/password/reset', { error: { code: errorCode, message, details: {} } }, status as number);
    renderPage('/password/reset'); await resetForm(interaction);
    await interaction.click(screen.getByRole('button', { name: 'Reset password' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(message as string);
    expect(screen.queryByLabelText('Your recovery code')).not.toBeInTheDocument();
  });
  it('does not submit mismatched new passwords', async () => {
    const interaction = userEvent.setup(); const fetcher = mockEndpoint('/api/auth/password/reset', {});
    renderPage('/password/reset'); await resetForm(interaction, 'Different123!');
    await interaction.click(screen.getByRole('button', { name: 'Reset password' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Passwords do not match.');
    expect(fetcher.mock.calls.some(([url]) => url === '/api/auth/password/reset')).toBe(false);
  });
  it('rejects malformed recovery codes with native validation', async () => {
    const interaction = userEvent.setup(); const fetcher = mockEndpoint('/api/auth/password/reset', {});
    renderPage('/password/reset'); await resetForm(interaction);
    await interaction.clear(screen.getByLabelText('Recovery code'));
    await interaction.type(screen.getByLabelText('Recovery code'), 'bad-code');
    await interaction.click(screen.getByRole('button', { name: 'Reset password' }));
    expect((screen.getByLabelText('Recovery code') as HTMLInputElement).checkValidity()).toBe(false);
    expect(fetcher.mock.calls.some(([url]) => url === '/api/auth/password/reset')).toBe(false);
  });
});

it('does not resubmit an already-created account when its success response lacks a code', async () => {
  const interaction = userEvent.setup(); const fetcher = mockEndpoint('/api/auth/register', { user: { username: 'dev_user' } }, 201);
  renderPage('/register'); await registerForm(interaction);
  await interaction.click(screen.getByRole('button', { name: 'Create account' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Your account was created');
  expect(screen.queryByRole('button', { name: 'Create account' })).not.toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Continue to sign in' })).toBeInTheDocument();
  expect(fetcher.mock.calls.filter(([url]) => url === '/api/auth/register')).toHaveLength(1);
});

it('does not repeat a completed password reset if the replacement code is missing', async () => {
  const interaction = userEvent.setup(); mockEndpoint('/api/auth/password/reset', { message: 'Password reset successfully.' });
  renderPage('/password/reset'); await resetForm(interaction);
  await interaction.click(screen.getByRole('button', { name: 'Reset password' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Your password was updated');
  expect(screen.queryByRole('button', { name: 'Reset password' })).not.toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Continue to sign in' })).toBeInTheDocument();
});
