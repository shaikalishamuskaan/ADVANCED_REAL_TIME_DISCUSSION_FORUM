import { useEffect, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ApiError, request, setSession } from '../lib/api';

const RECOVERY_CODE = /^[A-Z0-9]{4}(?:-[A-Z0-9]{4}){3}$/;
type RecoveryResponse = { recovery_code: string; recovery_code_notice: string };

function AccountFrame({ children, locked = false }: { children: ReactNode; locked?: boolean }) {
  const brand = <><span className="brand-mark" aria-hidden="true">f.</span><span>forum<span className="brand-dot">.</span></span></>;
  return <main className="account-page"><header>{locked ? <span className="brand">{brand}</span> : <Link className="brand" to="/login" aria-label="Forum sign in">{brand}</Link>}</header><section className="account-card login-form">{children}</section><p className="account-footer">A little curiosity. A better conversation.</p></main>;
}
function FormError({ error }: { error: unknown }) {
  if (!error) return null;
  const details = error instanceof ApiError ? Object.entries(error.details || {}).flatMap(([field, value]) => {
    const messages = Array.isArray(value) ? value.filter(item => typeof item === 'string') : typeof value === 'string' ? [value] : [];
    return messages.map(item => `${field.replaceAll('_', ' ')}: ${item}`);
  }) : [];
  return <div className="form-error" role="alert"><p>{error instanceof Error ? error.message : 'Please try again.'}</p>{details.length > 0 && <ul>{details.map((text, index) => <li key={index}>{text}</li>)}</ul>}</div>;
}
function RecoveryCodeStep({ code, notice, reset, onContinue }: { code: string; notice: string; reset: boolean; onContinue: () => void }) {
  const [saved, setSaved] = useState(false); const [copied, setCopied] = useState(false); const [copyError, setCopyError] = useState('');
  useEffect(() => {
    function warn(event: BeforeUnloadEvent) { if (!saved) { event.preventDefault(); event.returnValue = ''; } }
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [saved]);
  async function copy() {
    setCopyError('');
    try { await navigator.clipboard.writeText(code); setCopied(true); }
    catch { setCopyError('Copy was not available. Select the code and copy it manually.'); }
  }
  return <AccountFrame locked><p className="small-label">{reset ? 'PASSWORD UPDATED' : 'YOUR ACCOUNT IS READY'}</p><h1>Keep your way back.</h1><p className="muted">{reset ? 'Your old recovery code no longer works. Save this replacement code before signing in.' : 'This code is your way to reset a forgotten password. Save it somewhere private before you continue.'}</p><div className="recovery-box"><span className="small-label">{reset ? 'NEW RECOVERY CODE' : 'YOUR RECOVERY CODE'}</span><code aria-label="Your recovery code">{code}</code><button type="button" className="button secondary" onClick={() => void copy()}>{copied ? 'Copied' : 'Copy code'}</button></div><p className="recovery-notice">{notice || 'Shown once. Store it somewhere safe.'}</p>{copyError && <p className="form-error" role="alert">{copyError}</p>}<label className="saved-confirmation"><input type="checkbox" checked={saved} onChange={event => setSaved(event.target.checked)} />I have saved my recovery code somewhere safe.</label><button className="button primary sign-in" disabled={!saved} onClick={onContinue}>Continue to sign in</button><p className="login-note">This page does not save the code for you. It will disappear when you leave.</p></AccountFrame>;
}

export function Register() {
  const navigate = useNavigate();
  const [username, setUsername] = useState(''); const [displayName, setDisplayName] = useState(''); const [email, setEmail] = useState('');
  const [password, setPassword] = useState(''); const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false); const [error, setError] = useState<unknown>(null); const [recovery, setRecovery] = useState<RecoveryResponse | null>(null); const [completionError, setCompletionError] = useState('');
  async function submit(event: FormEvent) {
    event.preventDefault(); setError(null);
    if (password !== confirm) { setError(new Error('Passwords do not match.')); return; }
    if (!displayName.trim()) { setError(new Error('Please enter your display name.')); return; }
    setBusy(true);
    try {
      const response = await request<RecoveryResponse>('/api/auth/register', { method: 'POST', authenticated: false, body: JSON.stringify({ username: username.trim(), email: email.trim(), password, display_name: displayName.trim() }) });
      setPassword(''); setConfirm('');
      if (!RECOVERY_CODE.test(response.recovery_code || '')) { setCompletionError('Your account was created, but we could not display its recovery code. You can still sign in with your email and password.'); return; }
      setRecovery(response);
    } catch (problem) { setError(problem); } finally { setBusy(false); }
  }
  if (completionError) return <AccountFrame><p className="small-label">PLEASE NOTE</p><h1>One more thing.</h1><p className="form-error" role="alert">{completionError}</p><Link className="button primary sign-in" to="/login">Continue to sign in</Link></AccountFrame>;
  if (recovery) return <RecoveryCodeStep code={recovery.recovery_code} notice={recovery.recovery_code_notice} reset={false} onContinue={() => { setRecovery(null); navigate('/login', { replace: true, state: { notice: 'Your account is ready. Sign in to join the conversation.' } }); }} />;
  return <AccountFrame><p className="small-label">A PLACE FOR YOUR PERSPECTIVE</p><h1>Join the conversation.</h1><p className="muted">Create your account. Bring a little curiosity.</p><form onSubmit={event => void submit(event)}><fieldset disabled={busy}><label htmlFor="register-name">Display name</label><input id="register-name" name="display_name" autoComplete="name" maxLength={100} required value={displayName} onChange={event => setDisplayName(event.target.value)} /><label htmlFor="register-username">Username</label><input id="register-username" name="username" autoComplete="username" minLength={3} maxLength={30} pattern="[A-Za-z0-9_]{3,30}" aria-describedby="username-help" required value={username} onChange={event => setUsername(event.target.value)} /><p className="field-hint" id="username-help">3-30 letters, numbers, or underscores. People can mention you with this name.</p><label htmlFor="register-email">Email address</label><input id="register-email" name="email" type="email" autoComplete="email" maxLength={254} required value={email} onChange={event => setEmail(event.target.value)} /><label htmlFor="register-password">Password</label><input id="register-password" name="password" type="password" autoComplete="new-password" required value={password} onChange={event => setPassword(event.target.value)} /><label htmlFor="register-confirm">Confirm password</label><input id="register-confirm" name="confirm_password" type="password" autoComplete="new-password" required value={confirm} onChange={event => setConfirm(event.target.value)} /><FormError error={error} /><button className="button primary sign-in" disabled={busy}>{busy ? 'Creating account...' : 'Create account'}</button></fieldset></form><p className="account-switch">Already part of the community? <Link to="/login">Sign in</Link></p></AccountFrame>;
}

export function PasswordReset() {
  const navigate = useNavigate();
  const [username, setUsername] = useState(''); const [code, setCode] = useState(''); const [password, setPassword] = useState(''); const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false); const [error, setError] = useState<unknown>(null); const [recovery, setRecovery] = useState<RecoveryResponse | null>(null); const [completionError, setCompletionError] = useState('');
  async function submit(event: FormEvent) {
    event.preventDefault(); setError(null);
    if (password !== confirm) { setError(new Error('Passwords do not match.')); return; }
    setBusy(true);
    try {
      const response = await request<RecoveryResponse>('/api/auth/password/reset', { method: 'POST', authenticated: false, body: JSON.stringify({ username: username.trim(), recovery_code: code.trim().toUpperCase(), new_password: password }) });
      setPassword(''); setConfirm(''); setCode(''); setSession(null);
      if (!RECOVERY_CODE.test(response.recovery_code || '')) { setCompletionError('Your password was updated, but we could not display its replacement recovery code. Sign in with your new password.'); return; }
      setRecovery(response);
    } catch (problem) { setError(problem); } finally { setBusy(false); }
  }
  if (completionError) return <AccountFrame><p className="small-label">PLEASE NOTE</p><h1>One more thing.</h1><p className="form-error" role="alert">{completionError}</p><Link className="button primary sign-in" to="/login">Continue to sign in</Link></AccountFrame>;
  if (recovery) return <RecoveryCodeStep code={recovery.recovery_code} notice={recovery.recovery_code_notice} reset onContinue={() => { setRecovery(null); navigate('/login', { replace: true, state: { notice: 'Password updated. Sign in with your new password.' } }); }} />;
  return <AccountFrame><p className="small-label">FIND YOUR WAY BACK</p><h1>A fresh start.</h1><p className="muted">Use your username and saved recovery code to choose a new password.</p><form onSubmit={event => void submit(event)}><fieldset disabled={busy}><label htmlFor="reset-username">Username</label><input id="reset-username" name="username" autoComplete="username" minLength={3} maxLength={30} pattern="[A-Za-z0-9_]{3,30}" required value={username} onChange={event => setUsername(event.target.value)} /><label htmlFor="reset-code">Recovery code</label><input id="reset-code" name="recovery_code" autoComplete="off" autoCapitalize="characters" spellCheck={false} maxLength={19} pattern="[A-Za-z0-9]{4}(-[A-Za-z0-9]{4}){3}" placeholder="XXXX-XXXX-XXXX-XXXX" aria-describedby="reset-code-help" required value={code} onChange={event => setCode(event.target.value)} /><p className="field-hint" id="reset-code-help">Enter the code you saved when creating your account.</p><label htmlFor="reset-password">New password</label><input id="reset-password" name="new_password" type="password" autoComplete="new-password" minLength={8} maxLength={128} required value={password} onChange={event => setPassword(event.target.value)} /><p className="field-hint">Use 8-128 characters. Your account's password rules still apply.</p><label htmlFor="reset-confirm">Confirm new password</label><input id="reset-confirm" name="confirm_password" type="password" autoComplete="new-password" required value={confirm} onChange={event => setConfirm(event.target.value)} /><FormError error={error} /><button className="button primary sign-in" disabled={busy}>{busy ? 'Resetting password...' : 'Reset password'}</button></fieldset></form><p className="account-switch"><Link to="/login">Back to sign in</Link></p></AccountFrame>;
}
