import { useEffect, useState, type FormEvent } from 'react';
import { api, jsonBody, message, type Board, type Page, type Profile, type Pin, type PinPage, type User } from './api';
import Modal from './Modal';

export function People({ onProfile }: { onProfile: (id: string) => void }) {
  const [query, setQuery] = useState('');
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function search(after: string | null = null) {
    setBusy(true); setError('');
    try {
      const params = new URLSearchParams({ q: query.trim(), ...(after ? { cursor: after } : {}) });
      const result = await api<Page<Profile>>(`/profiles?${params}`);
      setProfiles(previous => after ? [...previous, ...result.items] : result.items); setCursor(result.next_cursor);
    } catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  return <section aria-label="Find people">
    <form className="search-form" onSubmit={event => { event.preventDefault(); void search(); }}>
      <label>Search people<input value={query} onChange={event => { setQuery(event.target.value); setCursor(null); }} required minLength={2} maxLength={80} /></label>
      <button className="primary" disabled={busy || query.trim().length < 2}>Find people</button>
    </form>
    {error && <p role="alert" className="error">{error}</p>}
    <div className="people-grid">{profiles.map(profile => <button className="person-card" key={profile.id} onClick={() => onProfile(profile.id)}>
      <h2>{profile.display_name}</h2><p>{profile.bio || 'A collector of inspiration.'}</p><small>{profile.follower_count} followers</small>
    </button>)}</div>
    {cursor && <button className="secondary" disabled={busy} onClick={() => search(cursor)}>More people</button>}
  </section>;
}

export function ProfileDialog({ id, user, onClose, onAuth, onBoard, onEdited, onBlocked }: {
  id: string; user: User | null; onClose: () => void; onAuth: () => void;
  onBoard: (board: Board) => void; onEdited: (name: string) => void;
  onBlocked: () => void;
}) {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [boards, setBoards] = useState<Board[]>([]);
  const [boardCursor, setBoardCursor] = useState<string | null>(null);
  const [connections, setConnections] = useState<Profile[]>([]);
  const [relation, setRelation] = useState('');
  const [tab, setTab] = useState<'boards' | 'pins'>('boards');
  const [createdPins, setCreatedPins] = useState<Pin[]>([]);
  const [pinCursor, setPinCursor] = useState<string | null>(null);
  const [connectionCursor, setConnectionCursor] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const own = user?.id === id;
  useEffect(() => {
    let active = true;
    Promise.all([api<Profile>(`/profiles/${id}`), api<Page<Board>>(`/profiles/${id}/boards`)]).then(([profile, page]) => {
      if (active) { setProfile(profile); setBoards(page.items); setBoardCursor(page.next_cursor); }
    }).catch(error => { if (active) setError(message(error)); });
    return () => { active = false; };
  }, [id]);
  async function action(kind: string, remove = false) {
    if (!user) { onAuth(); return; }
    setBusy(true); setError('');
    try {
      await api(`/social/users/${id}/${kind}`, { method: remove ? 'DELETE' : 'PUT' });
      if (kind === 'block') { onBlocked(); return; }
      setProfile(await api<Profile>(`/profiles/${id}`));
    } catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  async function showConnections(kind: string, cursor: string | null = null) {
    setBusy(true); setError('');
    try {
      const page = await api<Page<Profile>>(`/profiles/${id}/connections/${kind}${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''}`);
      setConnections(previous => cursor ? [...previous, ...page.items] : page.items); setRelation(kind); setConnectionCursor(page.next_cursor);
    } catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  async function edit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError('');
    const data = new FormData(event.currentTarget);
    try {
      const updated = await api<Profile>('/profiles/me', jsonBody({ display_name: data.get('name'), bio: data.get('bio') }, 'PATCH'));
      setProfile(updated); setEditing(false); onEdited(updated.display_name);
    } catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  async function moreBoards() {
    setBusy(true); setError('');
    try {
      const page = await api<Page<Board>>(`/profiles/${id}/boards?cursor=${encodeURIComponent(boardCursor!)}`);
      setBoards(previous => [...previous, ...page.items]); setBoardCursor(page.next_cursor);
    } catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  async function showPins(after: string | null = null) {
    setBusy(true); setError('');
    try {
      const page = await api<PinPage>(`/profiles/${id}/pins${after ? `?cursor=${encodeURIComponent(after)}` : ''}`);
      setCreatedPins(previous => after ? [...previous, ...page.items] : page.items); setPinCursor(page.next_cursor); setTab('pins');
    } catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  return <Modal title={profile?.display_name || 'Profile'} onClose={onClose}>
    {profile ? <>
      <h2>{profile.display_name}</h2><p className="description">{profile.bio}</p>
      <div className="inline-actions">
        <button className="text-button" disabled={busy} onClick={() => showConnections('followers')}>{profile.follower_count} followers</button>
        <button className="text-button" disabled={busy} onClick={() => showConnections('following')}>{profile.following_count} following</button>
      </div>
      {!own && <div className="inline-actions">
        <button className="primary" disabled={busy} onClick={() => action('follow', profile.is_following)}>{profile.is_following ? 'Unfollow' : 'Follow'}</button>
        {user && <><button className="text-button" disabled={busy} onClick={() => action('mute', profile.is_muted)}>{profile.is_muted ? 'Unmute' : 'Mute'}</button>
          <button className="text-button" disabled={busy} onClick={() => action('block')}>Block</button></>}
      </div>}
      {own && <button className="secondary" onClick={() => setEditing(!editing)}>Edit profile</button>}
      {editing && <form onSubmit={edit}>
        <label>Display name<input name="name" defaultValue={profile.display_name} required maxLength={80} /></label>
        <label>About you<textarea name="bio" defaultValue={profile.bio} maxLength={500} /></label>
        <button className="primary" disabled={busy}>Save profile</button>
      </form>}
      {relation && <section aria-label={relation}>
        <h3>{relation === 'followers' ? 'Followers' : 'Following'}</h3>
        {connections.map(person => <p key={person.id}>{person.display_name}</p>)}
        {connections.length === 0 && <p className="muted">No people here yet.</p>}
        {connectionCursor && <button className="text-button" disabled={busy} onClick={() => showConnections(relation, connectionCursor)}>More connections</button>}
      </section>}
      <div role="tablist" aria-label="Profile collections" className="inline-actions">
        <button role="tab" aria-selected={tab === 'boards'} onClick={() => setTab('boards')}>Boards</button>
        <button role="tab" aria-selected={tab === 'pins'} disabled={busy} onClick={() => showPins()}>Created pins</button>
      </div>
      {tab === 'boards' ? <section role="tabpanel" aria-label="Boards">
      <h3>{own ? 'Your boards' : 'Public boards'}</h3>
      <div className="profile-boards">{boards.map(board => <button className="secondary" key={board.id} onClick={() => onBoard(board)}>{board.name}{board.is_secret ? ' · Secret' : ''}</button>)}</div>
      {boards.length === 0 && <p className="muted">No public boards yet.</p>}
      {boardCursor && <button className="text-button" disabled={busy} onClick={moreBoards}>More boards</button>}
      </section> : <section role="tabpanel" aria-label="Created pins"><div className="related-grid">{createdPins.map(pin => <button className="pin-open" key={pin.id} onClick={() => { onClose(); location.hash = `pin/${pin.id}`; }} aria-label={`Created ${pin.title}`}><img src={pin.thumbnail_url || ''} alt={pin.title} /><h4>{pin.title}</h4></button>)}</div>
        {!createdPins.length && <p className="muted">No published pins yet.</p>}
        {pinCursor && <button className="text-button" disabled={busy} onClick={() => showPins(pinCursor)}>More created pins</button>}
      </section>}
    </> : <p className="muted">Loading profile…</p>}
    {error && <p className="error" role="alert">{error}</p>}
  </Modal>;
}

type Notice = { id: string; actor_id: string; actor_name: string; kind: string; created_at: string; read_at: string | null };
type Preferences = { blocked: { id: string; display_name: string }[]; muted: { id: string; display_name: string }[] };
export function Activity({ onProfile }: { onProfile: (id: string) => void }) {
  const [notices, setNotices] = useState<Notice[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [preferences, setPreferences] = useState<Preferences>({ blocked: [], muted: [] });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    Promise.all([api<Page<Notice>>('/notifications'), api<Preferences>('/social/preferences')]).then(([page, prefs]) => {
      if (active) { setNotices(page.items); setCursor(page.next_cursor); setPreferences(prefs); }
    }).catch(error => { if (active) setError(message(error)); });
    return () => { active = false; };
  }, []);
  async function read(id: string) {
    setBusy(true); setError('');
    try { await api(`/notifications/${id}/read`, { method: 'PUT' }); setNotices(previous => previous.map(row => row.id === id ? { ...row, read_at: new Date().toISOString() } : row)); }
    catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  async function restore(id: string, kind: 'block' | 'mute') {
    setBusy(true); setError('');
    try { await api(`/social/users/${id}/${kind}`, { method: 'DELETE' }); setPreferences(await api<Preferences>('/social/preferences')); }
    catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  async function more() {
    setBusy(true); setError('');
    try { const page = await api<Page<Notice>>(`/notifications?cursor=${encodeURIComponent(cursor!)}`); setNotices(previous => [...previous, ...page.items]); setCursor(page.next_cursor); }
    catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  return <section aria-label="Activity and preferences">
    <DigestStatus />
    {error && <p className="error" role="alert">{error}</p>}
    {notices.map(row => <article className="activity-row" key={row.id}>
      <button className="text-button" onClick={() => onProfile(row.actor_id)}>{row.actor_name}</button>
      <span>{row.kind === 'board_follow' ? 'followed your board' : row.kind === 'comment' ? 'commented on your pin' : row.kind === 'reaction' ? 'liked your pin' : row.kind === 'save' ? 'saved your pin' : 'followed you'}</span>
      <time dateTime={row.created_at}>{new Date(row.created_at).toLocaleDateString()}</time>
      {!row.read_at && <button className="secondary" disabled={busy} onClick={() => read(row.id)}>Mark read</button>}
    </article>)}
    {notices.length === 0 && <p className="muted">Your latest activity will appear here.</p>}
    {cursor && <button className="secondary" disabled={busy} onClick={more}>More activity</button>}
    <h2>Your preferences</h2>
    {preferences.blocked.map(person => <p key={person.id}>{person.display_name} <button className="text-button" disabled={busy} onClick={() => restore(person.id, 'block')}>Unblock</button></p>)}
    {preferences.muted.map(person => <p key={person.id}>{person.display_name} <button className="text-button" disabled={busy} onClick={() => restore(person.id, 'mute')}>Unmute</button></p>)}
    {preferences.blocked.length + preferences.muted.length === 0 && <p className="muted">You haven’t muted or blocked anyone.</p>}
  </section>;
}

function DigestStatus() {
  const [rows, setRows] = useState<{ id: string; status: string; period: string }[]>([]);
  const [error, setError] = useState('');
  async function load() { try { const page = await api<{ items: typeof rows }>('/notifications/digests'); setRows(page.items); } catch (e) { setError(message(e)); } }
  useEffect(() => { void load(); }, []);
  return <section aria-label="Email digests"><h3>Email digests</h3>{rows.map(row => <p key={row.id}>{row.period} · {row.status}</p>)}<button className="text-button" onClick={load}>Refresh digest status</button>{error && <p role="alert">{error}</p>}</section>;
}
