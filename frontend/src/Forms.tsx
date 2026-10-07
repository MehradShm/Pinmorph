import { useState, type FormEvent } from 'react';
import { api, jsonBody, message, type Board, type Pin, type User } from './api';
import Modal from './Modal';

export function AuthForm({ onClose, onUser }: { onClose: () => void; onUser: (user: User) => void }) {
  const [signup, setSignup] = useState(true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(''); setBusy(true);
    const data = new FormData(event.currentTarget);
    try {
      const user = await api<User>(`/auth/${signup ? 'signup' : 'login'}`, jsonBody({
        email: data.get('email'), password: data.get('password'), display_name: data.get('name'),
      }));
      onUser(user); onClose();
    } catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  return <Modal title={signup ? 'Create account' : 'Sign in'} onClose={onClose}>
    <p className="eyebrow">A place for your ideas</p>
    <h2>{signup ? 'Make it yours.' : 'Welcome back.'}</h2>
    <p className="muted">Collect inspiration, one pin at a time.</p>
    <form onSubmit={submit}>
      {signup && <label>Your name<input name="name" autoComplete="name" required maxLength={80} /></label>}
      <label>Email<input name="email" type="email" autoComplete="email" required maxLength={254} /></label>
      <label>Password<input name="password" type="password" required minLength={10} maxLength={128}
        autoComplete={signup ? 'new-password' : 'current-password'} /></label>
      {signup && <small className="muted">Use at least 10 characters.</small>}
      {error && <p className="error" role="alert">{error}</p>}
      <button className="primary" disabled={busy}>{busy ? 'Just a moment…' : signup ? 'Create account' : 'Sign in'}</button>
    </form>
    <button className="text-button" onClick={() => { setSignup(!signup); setError(''); }}>
      {signup ? 'Already have an account? Sign in' : 'New here? Create an account'}
    </button>
  </Modal>;
}

export function UploadForm({ onClose, onPin }: { onClose: () => void; onPin: (pin: Pin) => void }) {
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(''); setBusy(true);
    try {
      const pin = await api<Pin>('/pins', { method: 'POST', body: new FormData(event.currentTarget) });
      onPin(pin); onClose();
    } catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  return <Modal title="Create a pin" onClose={onClose}>
    <p className="eyebrow">Something worth keeping</p><h2>Create a pin.</h2>
    <form onSubmit={submit}>
      <label className="file-label">Choose an image<input type="file" name="image" required
        accept="image/jpeg,image/png,image/webp" /><small>JPEG, PNG or WebP · up to 12 MB</small></label>
      <label>Title<input name="title" required maxLength={200} placeholder="What caught your eye?" /></label>
      <label>Description<textarea name="description" maxLength={2000} rows={3} /></label>
      <label>Source link <span className="muted">(optional)</span><input name="source_url" type="url" placeholder="https://…" /></label>
      {error && <p className="error" role="alert">{error}</p>}
      <button className="primary" disabled={busy}>{busy ? 'Uploading…' : 'Publish pin'}</button>
    </form>
  </Modal>;
}

export function BoardForm({ onClose, onBoard }: { onClose: () => void; onBoard: (board: Board) => void }) {
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError('');
    const data = new FormData(event.currentTarget);
    try {
      onBoard(await api<Board>('/boards', jsonBody({ name: data.get('name') }))); onClose();
    } catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  return <Modal title="Create a board" onClose={onClose}>
    <p className="eyebrow">Give your ideas a home</p><h2>Create a board.</h2>
    <form onSubmit={submit}>
      <label>Board name<input name="name" required maxLength={100} placeholder="Everyday inspiration" /></label>
      {error && <p className="error" role="alert">{error}</p>}
      <button className="primary" disabled={busy}>{busy ? 'Creating…' : 'Create board'}</button>
    </form>
  </Modal>;
}
