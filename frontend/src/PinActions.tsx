import { useEffect, useState, type FormEvent } from 'react';
import { api, jsonBody, message, type FeedPage, type Page, type Pin, type User } from './api';
import { pagePins, ViewedPin } from './telemetry';

type Comment = { id: string; user_id: string; display_name: string; body: string };
export default function PinActions({ pin, user, onAuth, onHidden, onRelated }: {
  pin: Pin; user: User | null; onAuth: () => void; onHidden: () => void; onRelated: (pin: Pin) => void;
}) {
  const [comments, setComments] = useState<Comment[]>([]); const [cursor, setCursor] = useState<string | null>(null);
  const [related, setRelated] = useState<Pin[]>([]); const [relatedCursor, setRelatedCursor] = useState<string | null>(null);
  const [reaction, setReaction] = useState({ count: 0, liked: false }); const [body, setBody] = useState('');
  const [reason, setReason] = useState(''); const [reporting, setReporting] = useState(false);
  const [error, setError] = useState(''); const [status, setStatus] = useState(''); const [busy, setBusy] = useState(false);
  async function loadRelated(after?: string) {
    try { const page = await api<FeedPage>(`/pins/${pin.id}/related${after ? `?cursor=${encodeURIComponent(after)}` : ''}`); setRelated(old => after ? [...old, ...pagePins(page)] : pagePins(page)); setRelatedCursor(page.next_cursor); }
    catch (e) { setError(message(e)); }
  }
  useEffect(() => {
    let active = true;
    Promise.all([api<Page<Comment>>(`/pins/${pin.id}/comments`), api<typeof reaction>(`/pins/${pin.id}/reaction`)]).then(([page, reaction]) => {
      if (active) { setComments(page.items); setCursor(page.next_cursor); setReaction(reaction); }
    }).catch(e => { if (active) setError(message(e)); });
    if (user) void loadRelated();
    return () => { active = false; };
  }, [pin.id, user?.id]);
  async function like() {
    if (!user) { onAuth(); return; } setBusy(true); setError('');
    try { await api(`/pins/${pin.id}/reaction`, { method: reaction.liked ? 'DELETE' : 'PUT' }); setReaction(await api(`/pins/${pin.id}/reaction`)); }
    catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  async function comment(e: FormEvent) {
    e.preventDefault(); if (!user) { onAuth(); return; } setBusy(true); setError('');
    try { const row = await api<Comment>(`/pins/${pin.id}/comments`, jsonBody({ body })); setComments(old => [...old, row]); setBody(''); }
    catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  async function remove(id: string) {
    try { await api(`/comments/${id}`, { method: 'DELETE' }); setComments(old => old.filter(row => row.id !== id)); }
    catch (e) { setError(message(e)); }
  }
  async function moreComments() {
    try { const page = await api<Page<Comment>>(`/pins/${pin.id}/comments?cursor=${cursor}`); setComments(old => [...old, ...page.items]); setCursor(page.next_cursor); }
    catch (e) { setError(message(e)); }
  }
  async function hide() {
    if (!user) { onAuth(); return; }
    try { await api(`/pins/${pin.id}/hide`, { method: 'PUT' }); onHidden(); }
    catch (e) { setError(message(e)); }
  }
  async function report(e: FormEvent) {
    e.preventDefault(); if (!user) { onAuth(); return; } setBusy(true); setError('');
    try { await api(`/pins/${pin.id}/report`, jsonBody({ reason })); setStatus('Report submitted for review.'); setReporting(false); }
    catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  async function share() {
    const url = `${location.origin}/#pin/${pin.id}`;
    try { await navigator.clipboard.writeText(url); setStatus('Pin link copied.'); }
    catch { setStatus(url); }
  }
  return <section aria-label="Pin activity" className="pin-actions">
    <div className="save-controls"><button className="secondary" aria-pressed={reaction.liked} disabled={busy} onClick={like}>{reaction.liked ? 'Unlike' : 'Like'} · {reaction.count}</button>
      <button className="text-button" onClick={share}>Share link</button><button className="text-button" onClick={hide}>Hide pin</button>
      <button className="text-button" onClick={() => user ? setReporting(!reporting) : onAuth()}>Report pin</button></div>
    {reporting && <form onSubmit={report}><label>Reason for reporting<textarea value={reason} onChange={e => setReason(e.target.value)} required minLength={3} maxLength={1000} /></label><button className="primary" disabled={busy}>Submit report</button></form>}
    <h3>Comments</h3>{comments.map(row => <article className="comment" key={row.id}><strong>{row.display_name}</strong><p>{row.body}</p>{user?.id === row.user_id && <button className="text-button" onClick={() => remove(row.id)}>Delete comment</button>}</article>)}
    {cursor && <button className="text-button" onClick={moreComments}>More comments</button>}
    <form onSubmit={comment}><label>Add a comment<textarea value={body} onChange={e => setBody(e.target.value)} required maxLength={1000} /></label><button className="secondary" disabled={busy || !body.trim()}>Post comment</button></form>
    {related.length > 0 && <><h3>Related pins</h3><div className="related-grid">{related.map(pin => <ViewedPin pin={pin} key={pin.id}><button className="pin-open" onClick={() => onRelated(pin)} aria-label={`Related ${pin.title}`}><img src={pin.thumbnail_url || ''} alt={pin.title} /><h4>{pin.title}</h4></button></ViewedPin>)}</div>{relatedCursor && <button className="text-button" onClick={() => loadRelated(relatedCursor!)}>More related pins</button>}</>}
    {status && <p className="success" role="status">{status}</p>}{error && <p className="error" role="alert">{error}</p>}
  </section>;
}
