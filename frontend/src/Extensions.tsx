import { useEffect, useState, type FormEvent } from 'react';
import { api, jsonBody, message, type FeedPage, type Pin, type User } from './api';
import Modal from './Modal';

type Preferences = { interests: string[]; available_interests: string[]; onboarding_complete: boolean; email_digest: boolean };
export function Settings({ onSaved }: { onSaved: () => void }) {
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  const [hidden, setHidden] = useState<{ id: string; title: string }[]>([]);
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    Promise.all([api<Preferences>('/settings'), api<{ items: typeof hidden }>('/settings/hidden')])
      .then(([prefs, rows]) => { setPrefs(prefs); setHidden(rows.items); }).catch(e => setError(message(e)));
  }, []);
  async function save(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError('');
    try { await api('/settings', jsonBody({ interests: prefs!.interests, onboarding_complete: true, email_digest: prefs!.email_digest }, 'PUT')); setStatus('Preferences saved.'); onSaved(); }
    catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  async function digest() {
    setBusy(true); setError('');
    try { const row = await api<{ status: string }>('/notifications/digest', { method: 'POST' }); setStatus(row.status === 'no_activity' ? 'No new activity for a digest.' : 'Digest requested. View delivery in Activity.'); }
    catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  async function unhide(id: string) {
    try { await api(`/pins/${id}/hide`, { method: 'DELETE' }); setHidden(rows => rows.filter(row => row.id !== id)); }
    catch (e) { setError(message(e)); }
  }
  return <section aria-label="Settings" className="extension-panel">
    <h2>Make your feed yours.</h2><p className="muted">Choose a few interests, or explore without choosing.</p>
    {prefs && <form onSubmit={save}>
      <fieldset><legend>Your interests</legend><div className="interest-options">{prefs.available_interests.map(interest => <label className="checkbox-label" key={interest}>
        <input type="checkbox" checked={prefs.interests.includes(interest)} onChange={e => setPrefs({ ...prefs, interests: e.target.checked ? [...prefs.interests, interest] : prefs.interests.filter(term => term !== interest) })} />{interest}
      </label>)}</div></fieldset>
      <label className="checkbox-label"><input type="checkbox" checked={prefs.email_digest} onChange={e => setPrefs({ ...prefs, email_digest: e.target.checked })} />Daily activity email</label>
      <button className="primary" disabled={busy}>Save preferences</button>
      {prefs.email_digest && <button type="button" className="secondary" disabled={busy} onClick={digest}>Request digest</button>}
    </form>}
    <h3>Hidden pins</h3>{hidden.map(pin => <p key={pin.id}>{pin.title} <button className="text-button" onClick={() => unhide(pin.id)}>Show again</button></p>)}
    {!hidden.length && <p className="muted">No hidden pins.</p>}
    {status && <p className="success" role="status">{status}</p>}{error && <p className="error" role="alert">{error}</p>}
  </section>;
}

export function ImportForm({ onClose, onPin }: { onClose: () => void; onPin: (pin: Pin) => void }) {
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); setBusy(true); setError(''); const data = new FormData(e.currentTarget);
    try { onPin(await api<Pin>('/pins/import', jsonBody({ url: data.get('url'), title: data.get('title'), description: data.get('description') }))); onClose(); }
    catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  return <Modal title="Import an image" onClose={onClose}><h2>Keep something you found.</h2>
    <p className="muted">Paste a direct JPEG, PNG or WebP image link.</p><form onSubmit={submit}>
      <label>Image URL<input name="url" type="url" required maxLength={2000} placeholder="https://…/image.jpg" /></label>
      <label>Title<input name="title" required maxLength={200} /></label>
      <label>Description<textarea name="description" maxLength={2000} /></label>
      {error && <p className="error" role="alert">{error}</p>}<button className="primary" disabled={busy}>{busy ? 'Importing…' : 'Import image'}</button>
    </form></Modal>;
}

export function LensForm({ onPage }: { onPage: (page: FeedPage, append: boolean) => void }) {
  const [file, setFile] = useState<File | null>(null); const [preview, setPreview] = useState('');
  const [box, setBox] = useState({ left: 0, top: 0, right: 1, bottom: 1 });
  const [cursor, setCursor] = useState<string | null>(null); const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => { setCursor(null); if (!file) return; const url = URL.createObjectURL(file); setPreview(url); return () => URL.revokeObjectURL(url); }, [file]);
  useEffect(() => { setCursor(null); }, [box]);
  async function search(append = false) {
    if (!file) return; setBusy(true); setError(''); const data = new FormData();
    data.set('image', file); data.set('crop_box', JSON.stringify(box)); data.set('limit', '12');
    if (append && cursor) data.set('cursor', cursor);
    try { const page = await api<FeedPage>('/lens', { method: 'POST', body: data }); setCursor(page.next_cursor); onPage(page, append); }
    catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  return <section className="extension-panel" aria-label="Visual search">
    <form onSubmit={e => { e.preventDefault(); void search(); }}>
      <label>Search with an image<input type="file" accept="image/jpeg,image/png,image/webp" required onChange={e => setFile(e.target.files?.[0] || null)} /></label>
      {file && <><div className="crop-preview"><img src={preview} alt="Crop preview" /><div className="crop-outline" style={{ left: `${box.left * 100}%`, top: `${box.top * 100}%`, width: `${(box.right-box.left)*100}%`, height: `${(box.bottom-box.top)*100}%` }} /></div>
        <fieldset><legend>Choose a crop (0 to 1)</legend><div className="crop-fields">{(['left', 'top', 'right', 'bottom'] as const).map(edge => <label key={edge}>{edge}<input type="number" min={0} max={1} step={0.01} value={box[edge]} onChange={e => setBox({ ...box, [edge]: Number(e.target.value) })} /></label>)}</div></fieldset></>}
      <button className="primary" disabled={busy || !file}>{busy ? 'Finding similar pins…' : 'Find similar pins'}</button>
      {error && <p className="error" role="alert">{error}</p>}
    </form>{cursor && <button className="secondary" disabled={busy} onClick={() => search(true)}>More visual matches</button>}
  </section>;
}

type Report = { id: string; pin_id: string; title: string; reason: string; source: string };
export function Moderation({ user }: { user: User }) {
  const [rows, setRows] = useState<Report[]>([]); const [cursor, setCursor] = useState<string | null>(null);
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  async function load(after?: string) {
    try { const page = await api<{ items: Report[]; next_cursor: string | null }>(`/moderation/reports${after ? `?cursor=${after}` : ''}`); setRows(old => after ? [...old, ...page.items] : page.items); setCursor(page.next_cursor); }
    catch (e) { setError(message(e)); }
  }
  useEffect(() => { void load(); }, [user.id]);
  async function review(id: string, action: string) {
    setBusy(true); setError('');
    try { await api(`/moderation/reports/${id}`, jsonBody({ action }, 'PUT')); setRows(rows => rows.filter(row => row.id !== id)); }
    catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  return <section aria-label="Moderation queue">{rows.map(row => <article className="moderation-row" key={row.id}>
    <h2>{row.title}</h2><img src={`/api/moderation/pins/${row.pin_id}/image`} alt={row.title} width={180} />
    <p>{row.reason}</p><small>{row.source}</small><div className="save-controls">{['remove', 'restore', 'dismiss'].map(action => <button className="secondary" key={action} disabled={busy} onClick={() => review(row.id, action)}>{action}</button>)}</div>
  </article>)}{!rows.length && <p>No reports awaiting review.</p>}{cursor && <button className="secondary" onClick={() => load(cursor)}>More reports</button>}{error && <p className="error" role="alert">{error}</p>}</section>;
}
